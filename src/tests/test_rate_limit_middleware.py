from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.cache import CacheService
from app.services.opensearch import OpenSearchService
from app.services.postgres import PostgresService
from app.services.rate_limiter import RateLimiter
from app.services.redis_client import RedisService
from tests.conftest import SAMPLE_DASHBOARD, SAMPLE_SEARCH_ITEM


@pytest.fixture
def limiter_allowed() -> AsyncMock:
    limiter = AsyncMock(spec=RateLimiter)
    limiter.acquire.return_value = (True, 99, 0)
    return limiter


@pytest.fixture
def limiter_blocked() -> AsyncMock:
    limiter = AsyncMock(spec=RateLimiter)
    limiter.acquire.return_value = (False, 0, 2)
    return limiter


def _setup_app_state(
    limiter: AsyncMock | None,
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    app.state.rate_limiter = limiter
    app.state.rate_limit_capacity = 100
    app.state.rate_limit_exempt_paths = {"/docs", "/openapi.json"}
    app.state.redis_service = mock_redis
    app.state.opensearch_service = mock_opensearch
    app.state.postgres_service = mock_postgres
    app.state.cache_service = mock_cache


@pytest.fixture
def mock_redis() -> AsyncMock:
    mock = AsyncMock(spec=RedisService)
    mock.get.return_value = None
    mock.setex.return_value = None
    mock.ping.return_value = True
    return mock


@pytest.fixture
def mock_opensearch() -> AsyncMock:
    mock = AsyncMock(spec=OpenSearchService)
    mock.search_indicators.return_value = ([SAMPLE_SEARCH_ITEM.copy()], 1)
    mock.check_health.return_value = True
    return mock


@pytest.fixture
def mock_postgres() -> AsyncMock:
    mock = AsyncMock(spec=PostgresService)
    mock.get_dashboard_summary.return_value = SAMPLE_DASHBOARD.copy()
    mock.check_health.return_value = True
    return mock


@pytest.fixture
def mock_cache(mock_redis: AsyncMock) -> CacheService:
    return CacheService(mock_redis)


@pytest.mark.asyncio
async def test_request_passes_with_rate_limit_headers(
    limiter_allowed: AsyncMock,
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    _setup_app_state(limiter_allowed, mock_redis, mock_opensearch, mock_postgres, mock_cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/indicators/search")
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "100"
    assert resp.headers["X-RateLimit-Remaining"] == "99"


@pytest.mark.asyncio
async def test_request_blocked_returns_429(
    limiter_blocked: AsyncMock,
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    _setup_app_state(limiter_blocked, mock_redis, mock_opensearch, mock_postgres, mock_cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/indicators/search")
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "2"
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert resp.json()["detail"] == "Too many requests"


@pytest.mark.asyncio
async def test_health_is_rate_limited(
    limiter_blocked: AsyncMock,
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    _setup_app_state(limiter_blocked, mock_redis, mock_opensearch, mock_postgres, mock_cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 429
    limiter_blocked.acquire.assert_called_once()


@pytest.mark.asyncio
async def test_exempt_path_skips_rate_limiting(
    limiter_blocked: AsyncMock,
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    _setup_app_state(limiter_blocked, mock_redis, mock_opensearch, mock_postgres, mock_cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/docs")
    limiter_blocked.acquire.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_rate_limiter_passes_through(
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    _setup_app_state(None, mock_redis, mock_opensearch, mock_postgres, mock_cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/indicators/search")
    assert resp.status_code == 200
    assert "X-RateLimit-Limit" not in resp.headers


@pytest.mark.asyncio
async def test_x_forwarded_for_used_as_client_id(
    limiter_allowed: AsyncMock,
    mock_redis: AsyncMock,
    mock_opensearch: AsyncMock,
    mock_postgres: AsyncMock,
    mock_cache: CacheService,
) -> None:
    _setup_app_state(limiter_allowed, mock_redis, mock_opensearch, mock_postgres, mock_cache)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/indicators/search",
            headers={"X-Forwarded-For": "10.0.0.1, 192.168.1.1"},
        )
    assert resp.status_code == 200
    limiter_allowed.acquire.assert_called_once_with("10.0.0.1")
