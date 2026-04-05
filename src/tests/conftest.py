from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.cache import CacheService
from app.services.opensearch import OpenSearchService
from app.services.postgres import PostgresService
from app.services.redis_client import RedisService

SAMPLE_INDICATOR = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "ip",
    "value": "192.168.1.100",
    "confidence": 85,
    "first_seen": "2024-11-15T10:30:00",
    "last_seen": "2024-12-20T14:22:00",
    "threat_actors": [{"id": "actor-123", "name": "APT-North", "confidence": 90}],
    "campaigns": [{"id": "camp-456", "name": "Operation ShadowNet", "active": True}],
    "related_indicators": [
        {"id": "ind-789", "type": "domain", "value": "malicious.example.com", "relationship": "same_campaign"}
    ],
}

SAMPLE_SEARCH_ITEM = {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "type": "ip",
    "value": "192.168.1.100",
    "confidence": 85,
    "first_seen": "2024-11-15T10:30:00",
    "campaign_count": 2,
    "threat_actor_count": 1,
}

SAMPLE_TIMELINE = {
    "campaign": {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "name": "Operation ShadowNet",
        "description": "Targeted phishing campaign",
        "first_seen": "2024-10-01T00:00:00",
        "last_seen": "2024-12-15T00:00:00",
        "status": "active",
    },
    "timeline": [
        {
            "period": "2024-10-01",
            "indicators": [{"id": "ind-1", "type": "ip", "value": "10.0.0.1"}],
            "counts": {"ip": 5, "domain": 3},
        }
    ],
    "summary": {
        "total_indicators": 234,
        "unique_ips": 45,
        "unique_domains": 67,
        "duration_days": 75,
    },
}

SAMPLE_DASHBOARD = {
    "time_range": "7d",
    "new_indicators": {"ip": 145, "domain": 89, "url": 234, "hash": 67},
    "active_campaigns": 12,
    "top_threat_actors": [{"id": "actor-123", "name": "APT-North", "indicator_count": 456}],
    "indicator_distribution": {"ip": 3421, "domain": 2876, "url": 2134, "hash": 1569},
}


@pytest.fixture
def mock_redis() -> RedisService:
    mock = AsyncMock(spec=RedisService)
    mock.get.return_value = None
    mock.setex.return_value = None
    mock.ping.return_value = True
    return mock


@pytest.fixture
def mock_opensearch() -> OpenSearchService:
    mock = AsyncMock(spec=OpenSearchService)
    mock.get_indicator.return_value = SAMPLE_INDICATOR.copy()
    mock.search_indicators.return_value = ([SAMPLE_SEARCH_ITEM.copy()], 1)
    mock.check_health.return_value = True
    return mock


@pytest.fixture
def mock_postgres() -> PostgresService:
    mock = AsyncMock(spec=PostgresService)
    mock.get_campaign_timeline_from_summary.return_value = None
    mock.get_campaign_timeline.return_value = SAMPLE_TIMELINE.copy()
    mock.get_dashboard_summary.return_value = SAMPLE_DASHBOARD.copy()
    mock.upsert_campaign_timeline_summary.return_value = None
    mock.check_health.return_value = True
    mock._get_read_session = AsyncMock()
    return mock


@pytest.fixture
def mock_cache(mock_redis: RedisService) -> CacheService:
    cache = CacheService(mock_redis)
    return cache


@pytest_asyncio.fixture
async def client(
    mock_redis: RedisService,
    mock_opensearch: OpenSearchService,
    mock_postgres: PostgresService,
    mock_cache: CacheService,
) -> AsyncGenerator[AsyncClient, None]:
    app.state.redis_service = mock_redis
    app.state.opensearch_service = mock_opensearch
    app.state.postgres_service = mock_postgres
    app.state.cache_service = mock_cache

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
