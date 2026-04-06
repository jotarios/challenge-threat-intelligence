import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_default_7d(client: AsyncClient, mock_postgres):
    resp = await client.get("/api/dashboard/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["time_range"] == "7d"
    assert "new_indicators" in data
    assert data["active_campaigns"] == 12


@pytest.mark.asyncio
async def test_dashboard_24h(client: AsyncClient, mock_postgres):
    mock_postgres.get_dashboard_summary.return_value = {
        "time_range": "24h",
        "new_indicators": {"ip": 10},
        "active_campaigns": 5,
        "top_threat_actors": [],
        "indicator_distribution": {"ip": 100},
    }
    resp = await client.get("/api/dashboard/summary", params={"time_range": "24h"})
    assert resp.status_code == 200
    assert resp.json()["time_range"] == "24h"


@pytest.mark.asyncio
async def test_dashboard_invalid_range(client: AsyncClient):
    resp = await client.get("/api/dashboard/summary", params={"time_range": "1y"})
    assert resp.status_code == 400
    assert "Invalid time_range" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_dashboard_rejects_unknown_params(client: AsyncClient):
    resp = await client.get("/api/dashboard/summary", params={"time_range": "7d", "foo": "bar"})
    assert resp.status_code == 422
    assert "foo" in resp.json()["detail"]
