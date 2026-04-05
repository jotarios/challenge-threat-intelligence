from unittest.mock import AsyncMock

import pytest

from app.services.background import precompute_campaign_timelines, precompute_dashboard
from app.services.postgres import PostgresService
from app.services.redis_client import RedisService

SAMPLE_DASHBOARD = {
    "time_range": "7d",
    "new_indicators": {"ip": 10},
    "active_campaigns": 5,
    "top_threat_actors": [],
    "indicator_distribution": {"ip": 100},
}

SAMPLE_TIMELINE = {
    "campaign": {
        "id": "c1",
        "name": "Op X",
        "description": None,
        "first_seen": None,
        "last_seen": None,
        "status": "active",
    },
    "timeline": [{"period": "2024-10-01", "indicators": [], "counts": {"ip": 5}}],
    "summary": {"total_indicators": 5, "unique_ips": 3, "unique_domains": 0, "duration_days": 10},
}


@pytest.mark.asyncio
async def test_precompute_dashboard_success():
    redis = AsyncMock(spec=RedisService)
    postgres = AsyncMock(spec=PostgresService)
    postgres.get_dashboard_summary.return_value = SAMPLE_DASHBOARD

    await precompute_dashboard(redis, postgres)

    assert postgres.get_dashboard_summary.call_count == 3
    assert redis.setex.call_count == 3


@pytest.mark.asyncio
async def test_precompute_dashboard_partial_failure():
    redis = AsyncMock(spec=RedisService)
    postgres = AsyncMock(spec=PostgresService)
    postgres.get_dashboard_summary.side_effect = [
        SAMPLE_DASHBOARD,
        Exception("db timeout"),
        SAMPLE_DASHBOARD,
    ]

    await precompute_dashboard(redis, postgres)

    assert redis.setex.call_count == 2


@pytest.mark.asyncio
async def test_precompute_timelines_batch():
    redis = AsyncMock(spec=RedisService)
    postgres = AsyncMock(spec=PostgresService)
    postgres.get_active_campaign_ids.return_value = ["c1", "c2", "c3"]
    postgres.get_campaign_timeline.return_value = SAMPLE_TIMELINE
    postgres.upsert_campaign_timeline_summary.return_value = None

    run_time = await precompute_campaign_timelines(redis, postgres, last_run=None)

    assert run_time is not None
    assert postgres.get_campaign_timeline.call_count == 6
    assert postgres.upsert_campaign_timeline_summary.call_count == 6


@pytest.mark.asyncio
async def test_precompute_timelines_no_campaigns():
    redis = AsyncMock(spec=RedisService)
    postgres = AsyncMock(spec=PostgresService)
    postgres.get_active_campaign_ids.return_value = []

    run_time = await precompute_campaign_timelines(redis, postgres, last_run=None)

    assert run_time is not None
    postgres.get_campaign_timeline.assert_not_called()


@pytest.mark.asyncio
async def test_precompute_timelines_partial_failure():
    redis = AsyncMock(spec=RedisService)
    postgres = AsyncMock(spec=PostgresService)
    postgres.get_campaign_timeline.side_effect = [
        SAMPLE_TIMELINE,
        Exception("timeout"),
        SAMPLE_TIMELINE,
        SAMPLE_TIMELINE,
    ]
    postgres.upsert_campaign_timeline_summary.return_value = None
    postgres.get_active_campaign_ids.return_value = ["c1", "c2"]

    run_time = await precompute_campaign_timelines(redis, postgres, last_run=None)
    assert run_time is not None
