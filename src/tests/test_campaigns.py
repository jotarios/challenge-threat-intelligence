import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_campaign_timeline_happy_path(client: AsyncClient, mock_postgres):
    resp = await client.get("/api/campaigns/camp-456/indicators")
    assert resp.status_code == 200
    data = resp.json()
    assert data["campaign"]["id"] == "camp-456"
    assert len(data["timeline"]) == 1
    assert data["summary"]["total_indicators"] == 234


@pytest.mark.asyncio
async def test_campaign_timeline_group_by_week(client: AsyncClient, mock_postgres):
    resp = await client.get("/api/campaigns/camp-456/indicators", params={"group_by": "week"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_campaign_not_found(client: AsyncClient, mock_postgres):
    mock_postgres.get_campaign_timeline.return_value = None
    resp = await client.get("/api/campaigns/unknown-id/indicators")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Campaign not found"


@pytest.mark.asyncio
async def test_campaign_start_after_end(client: AsyncClient):
    resp = await client.get(
        "/api/campaigns/camp-456/indicators",
        params={"start_date": "2025-01-01", "end_date": "2024-01-01"},
    )
    assert resp.status_code == 400
