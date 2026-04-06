import logging
import time
from typing import cast

import redis.asyncio as aioredis
from redis.exceptions import NoScriptError

logger = logging.getLogger(__name__)

TOKEN_BUCKET_SCRIPT = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + (elapsed * refill_rate))
last_refill = now

if tokens >= 1 then
    tokens = tokens - 1
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) + 1)
    return {1, math.floor(tokens), 0}
else
    local retry_after = math.ceil((1 - tokens) / refill_rate)
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
    redis.call('EXPIRE', key, math.ceil(capacity / refill_rate) + 1)
    return {0, 0, retry_after}
end
"""


class RateLimiter:
    def __init__(
        self,
        redis_client: aioredis.Redis,
        capacity: int = 100,
        refill_rate: float = 100 / 60,
        key_prefix: str = "rl",
    ) -> None:
        self._redis = redis_client
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._key_prefix = key_prefix
        self._script_sha: str | None = None

    async def _ensure_script(self) -> str:
        if self._script_sha is None:
            self._script_sha = cast(str, await self._redis.script_load(TOKEN_BUCKET_SCRIPT))
        return self._script_sha

    async def _eval(self, key: str, now: float) -> tuple[bool, int, int]:
        sha = await self._ensure_script()
        result: list[int] = await self._redis.evalsha(  # type: ignore[misc]
            sha,
            1,
            key,
            str(self._capacity),
            str(self._refill_rate),
            str(now),
        )
        return bool(result[0]), int(result[1]), int(result[2])

    async def acquire(self, client_id: str) -> tuple[bool, int, int]:
        key = f"{self._key_prefix}:{client_id}"
        now = time.time()

        try:
            return await self._eval(key, now)
        except NoScriptError:
            self._script_sha = None
            try:
                return await self._eval(key, now)
            except Exception as e:
                logger.warning("Rate limiter Redis error on retry, failing open: %s", e)
                return True, self._capacity, 0
        except Exception as e:
            logger.warning("Rate limiter Redis error, failing open: %s", e)
            return True, self._capacity, 0
