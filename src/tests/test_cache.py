from unittest.mock import AsyncMock

import pytest

from app.services.cache import CacheService
from app.services.redis_client import RedisService


@pytest.mark.asyncio
async def test_cache_hit():
    redis = AsyncMock(spec=RedisService)
    redis.get.return_value = {"key": "cached_value"}
    cache = CacheService(redis)

    fetch_fn = AsyncMock(return_value={"key": "fresh_value"})
    result = await cache.get_or_fetch("test_key", 60, fetch_fn)

    assert result == {"key": "cached_value"}
    fetch_fn.assert_not_called()
    redis.setex.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss():
    redis = AsyncMock(spec=RedisService)
    redis.get.return_value = None
    cache = CacheService(redis)

    fetch_fn = AsyncMock(return_value={"key": "fresh_value"})
    result = await cache.get_or_fetch("test_key", 60, fetch_fn)

    assert result == {"key": "fresh_value"}
    fetch_fn.assert_called_once()
    redis.setex.assert_called_once_with("test_key", 60, {"key": "fresh_value"})


@pytest.mark.asyncio
async def test_cache_redis_down():
    redis = AsyncMock(spec=RedisService)
    redis.get.return_value = None
    redis.setex.side_effect = Exception("connection refused")
    cache = CacheService(redis)

    fetch_fn = AsyncMock(return_value={"key": "fresh_value"})
    result = await cache.get_or_fetch("test_key", 60, fetch_fn)

    assert result == {"key": "fresh_value"}
    fetch_fn.assert_called_once()
