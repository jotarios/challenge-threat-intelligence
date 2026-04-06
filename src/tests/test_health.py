import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_all_up(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["services"]["opensearch"]["status"] == "up"
    assert data["services"]["postgresql"]["status"] == "up"
    assert data["services"]["redis"]["status"] == "up"


@pytest.mark.asyncio
async def test_health_one_down(client: AsyncClient, mock_redis):
    mock_redis.ping.return_value = False
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "degraded"
    assert data["services"]["redis"]["status"] == "down"
    assert data["services"]["opensearch"]["status"] == "up"


@pytest.mark.asyncio
async def test_health_all_down(client: AsyncClient, mock_opensearch, mock_postgres, mock_redis):
    mock_opensearch.check_health.return_value = False
    mock_postgres.check_health.return_value = False
    mock_redis.ping.return_value = False
    resp = await client.get("/health")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_health_rejects_unknown_params(client: AsyncClient):
    resp = await client.get("/health", params={"foo": "bar"})
    assert resp.status_code == 422
    assert "foo" in resp.json()["detail"]
