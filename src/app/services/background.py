import asyncio
import logging
import time
from datetime import UTC, datetime

from app.services.postgres import PostgresService
from app.services.redis_client import RedisService

logger = logging.getLogger(__name__)

DASHBOARD_TTL = 120
CAMPAIGN_TIMELINE_TTL = 300
TIME_RANGES = ["24h", "7d", "30d"]
PRECOMPUTE_BATCH_SIZE = 10

_dashboard_lock = asyncio.Lock()
_timeline_lock = asyncio.Lock()


async def precompute_dashboard(redis: RedisService, postgres: PostgresService) -> None:
    for tr in TIME_RANGES:
        try:
            summary = await postgres.get_dashboard_summary(tr)
            await redis.setex(f"dashboard:summary:{tr}", DASHBOARD_TTL, summary)
            logger.info("Pre-computed dashboard summary for %s", tr)
        except Exception as e:
            logger.error("Failed to pre-compute dashboard for %s: %s", tr, e)


async def _compute_one_timeline(
    campaign_id: str,
    granularity: str,
    redis: RedisService,
    postgres: PostgresService,
) -> None:
    try:
        timeline = await postgres.get_campaign_timeline(campaign_id, granularity, None, None)
        if timeline:
            await postgres.upsert_campaign_timeline_summary(campaign_id, granularity, timeline)
            cache_key = f"campaign:{campaign_id}:timeline:{granularity}::"
            await redis.setex(cache_key, CAMPAIGN_TIMELINE_TTL, timeline)
    except Exception as e:
        logger.error(
            "Failed to pre-compute timeline campaign=%s granularity=%s: %s",
            campaign_id,
            granularity,
            e,
        )


async def precompute_campaign_timelines(
    redis: RedisService,
    postgres: PostgresService,
    last_run: datetime | None = None,
) -> datetime:
    """Pre-compute timelines for active campaigns. Returns the timestamp of this run."""
    run_start = datetime.now(UTC).replace(tzinfo=None)
    campaign_ids = await postgres.get_active_campaign_ids(since=last_run)

    if not campaign_ids:
        logger.info("No campaigns to pre-compute (last_run=%s)", last_run)
        return run_start

    logger.info("Pre-computing timelines for %d campaigns", len(campaign_ids))
    start = time.monotonic()
    failures = 0

    tasks: list[tuple[str, str]] = [(cid, gran) for cid in campaign_ids for gran in ("day", "week")]

    for i in range(0, len(tasks), PRECOMPUTE_BATCH_SIZE):
        batch = tasks[i : i + PRECOMPUTE_BATCH_SIZE]
        results = await asyncio.gather(
            *[_compute_one_timeline(cid, gran, redis, postgres) for cid, gran in batch],
            return_exceptions=True,
        )
        failures += sum(1 for r in results if isinstance(r, BaseException))

    elapsed = time.monotonic() - start
    logger.info(
        "Timeline pre-computation complete: %d campaigns, %d failures, %.1fs",
        len(campaign_ids),
        failures,
        elapsed,
    )
    return run_start


async def run_dashboard_precompute(
    redis: RedisService,
    postgres: PostgresService,
    interval: int = 120,
) -> None:
    while True:
        if _dashboard_lock.locked():
            logger.warning("Dashboard pre-computation still running, skipping this cycle")
        else:
            async with _dashboard_lock:
                try:
                    await precompute_dashboard(redis, postgres)
                except Exception as e:
                    logger.error("Dashboard precompute failed: %s", e)
        await asyncio.sleep(interval)


async def run_timeline_precompute(
    redis: RedisService,
    postgres: PostgresService,
    interval: int = 120,
) -> None:
    last_run: datetime | None = None
    while True:
        if _timeline_lock.locked():
            logger.warning("Timeline pre-computation still running, skipping this cycle")
        else:
            async with _timeline_lock:
                try:
                    last_run = await precompute_campaign_timelines(redis, postgres, last_run)
                except Exception as e:
                    logger.error("Timeline precompute failed: %s", e)
        await asyncio.sleep(interval)
