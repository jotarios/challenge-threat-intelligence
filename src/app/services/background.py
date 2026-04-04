import asyncio
import logging

from app.services.postgres import PostgresService
from app.services.redis_client import RedisService

logger = logging.getLogger(__name__)

DASHBOARD_TTL = 120
TIME_RANGES = ["24h", "7d", "30d"]


async def precompute_dashboard(redis: RedisService, postgres: PostgresService) -> None:
    for tr in TIME_RANGES:
        try:
            summary = await postgres.get_dashboard_summary(tr)
            await redis.setex(f"dashboard:summary:{tr}", DASHBOARD_TTL, summary)
            logger.info("Pre-computed dashboard summary for %s", tr)
        except Exception as e:
            logger.error("Failed to pre-compute dashboard for %s: %s", tr, e)


async def run_periodic_precompute(
    redis: RedisService,
    postgres: PostgresService,
    interval: int = 120,
) -> None:
    while True:
        try:
            await precompute_dashboard(redis, postgres)
        except Exception as e:
            logger.error("Periodic precompute failed: %s", e)
        await asyncio.sleep(interval)
