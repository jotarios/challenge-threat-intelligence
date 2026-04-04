import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.redis_client import RedisService

logger = logging.getLogger(__name__)


class CacheService:
    def __init__(self, redis: RedisService):
        self._redis = redis

    async def get_or_fetch(
        self,
        key: str,
        ttl: int,
        fetch_fn: Callable[[], Awaitable[dict[str, Any] | None]],
    ) -> dict[str, Any] | None:
        cached = await self._redis.get(key)
        if cached is not None:
            return cached

        result = await fetch_fn()
        if result is not None:
            try:
                await self._redis.setex(key, ttl, result)
            except Exception as e:
                logger.warning("Cache write failed for key=%s: %s", key, e)
        return result
