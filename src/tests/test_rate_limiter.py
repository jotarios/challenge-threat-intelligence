from unittest.mock import AsyncMock

import pytest
from redis.exceptions import NoScriptError

from app.services.rate_limiter import RateLimiter


@pytest.mark.asyncio
async def test_acquire_allowed() -> None:
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="fake_sha")
    redis.evalsha = AsyncMock(return_value=[1, 99, 0])

    limiter = RateLimiter(redis, capacity=100, refill_rate=100 / 60)
    allowed, remaining, retry_after = await limiter.acquire("192.168.1.1")

    assert allowed is True
    assert remaining == 99
    assert retry_after == 0


@pytest.mark.asyncio
async def test_acquire_rejected() -> None:
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="fake_sha")
    redis.evalsha = AsyncMock(return_value=[0, 0, 1])

    limiter = RateLimiter(redis, capacity=100, refill_rate=100 / 60)
    allowed, remaining, retry_after = await limiter.acquire("192.168.1.1")

    assert allowed is False
    assert remaining == 0
    assert retry_after == 1


@pytest.mark.asyncio
async def test_acquire_fails_open_on_redis_error() -> None:
    redis = AsyncMock()
    redis.script_load = AsyncMock(side_effect=ConnectionError("Redis down"))

    limiter = RateLimiter(redis, capacity=100, refill_rate=100 / 60)
    allowed, remaining, retry_after = await limiter.acquire("192.168.1.1")

    assert allowed is True
    assert remaining == 100
    assert retry_after == 0


@pytest.mark.asyncio
async def test_acquire_reloads_script_on_noscripterror() -> None:
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="new_sha")
    redis.evalsha = AsyncMock(side_effect=[NoScriptError("gone"), [1, 50, 0]])

    limiter = RateLimiter(redis, capacity=100, refill_rate=100 / 60)
    limiter._script_sha = "old_sha"

    allowed, remaining, _ = await limiter.acquire("10.0.0.1")

    assert allowed is True
    assert remaining == 50
    assert redis.script_load.call_count == 1


@pytest.mark.asyncio
async def test_acquire_fails_open_on_retry_error() -> None:
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="new_sha")
    redis.evalsha = AsyncMock(side_effect=[NoScriptError("gone"), ConnectionError("down")])

    limiter = RateLimiter(redis, capacity=100, refill_rate=100 / 60)
    limiter._script_sha = "old_sha"

    allowed, remaining, retry_after = await limiter.acquire("192.168.1.1")

    assert allowed is True
    assert remaining == 100
    assert retry_after == 0


@pytest.mark.asyncio
async def test_acquire_uses_correct_key_prefix() -> None:
    redis = AsyncMock()
    redis.script_load = AsyncMock(return_value="sha")
    redis.evalsha = AsyncMock(return_value=[1, 99, 0])

    limiter = RateLimiter(redis, capacity=100, refill_rate=100 / 60, key_prefix="rl")
    await limiter.acquire("192.168.1.1")

    call_args = redis.evalsha.call_args
    assert call_args[0][2] == "rl:192.168.1.1"
