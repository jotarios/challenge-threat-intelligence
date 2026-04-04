import asyncio
import json
import logging
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError, TimeoutError

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self, url: str):
        self._url = url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        for attempt in range(3):
            try:
                self._client = aioredis.from_url(self._url, decode_responses=True)
                await self._client.ping()  # type: ignore[misc]
                logger.info("Redis connected")
                return
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                else:
                    logger.error("Redis connection failed after 3 attempts: %s", e)
                    raise

    async def get(self, key: str) -> dict[str, Any] | None:
        if not self._client:
            return None
        try:
            data = await self._client.get(key)
            if data is None:
                return None
            result: dict[str, Any] = json.loads(data)
            return result
        except (RedisConnectionError, TimeoutError) as e:
            logger.warning("Redis get failed for key=%s: %s", key, e)
            return None
        except (json.JSONDecodeError, ResponseError) as e:
            logger.warning("Redis get decode error for key=%s: %s", key, e)
            return None

    async def setex(self, key: str, ttl: int, value: dict[str, Any]) -> None:
        if not self._client:
            return
        try:
            await self._client.setex(key, ttl, json.dumps(value, default=str))
        except (RedisConnectionError, TimeoutError, ResponseError) as e:
            logger.warning("Redis setex failed for key=%s: %s", key, e)

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def ping(self) -> bool:
        if not self._client:
            return False
        try:
            result = await self._client.ping()  # type: ignore[misc]
            return bool(result)
        except Exception:
            return False
