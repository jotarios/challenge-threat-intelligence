import pytest
from httpx import AsyncClient

VALID_CAMPAIGN_ID = "660e8400-e29b-41d4-a716-446655440001"
UNKNOWN_CAMPAIGN_ID = "00000000-0000-0000-0000-000000000000"


@pytest.mark.asyncio
async def test_campaign_timeline_happy_path(client: AsyncClient, mock_postgres):
    resp = await client.get(f"/api/campaigns/{VALID_CAMPAIGN_ID}/indicators")
    assert resp.status_code == 200
    data = resp.json()
    assert data["campaign"]["id"] == VALID_CAMPAIGN_ID
    assert len(data["timeline"]) == 1
    assert data["summary"]["total_indicators"] == 234


@pytest.mark.asyncio
async def test_campaign_timeline_group_by_week(client: AsyncClient, mock_postgres):
    resp = await client.get(f"/api/campaigns/{VALID_CAMPAIGN_ID}/indicators", params={"group_by": "week"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_campaign_not_found(client: AsyncClient, mock_postgres):
    mock_postgres.get_campaign_timeline_from_summary.return_value = None
    mock_postgres.get_campaign_timeline.return_value = None
    resp = await client.get(f"/api/campaigns/{UNKNOWN_CAMPAIGN_ID}/indicators")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Campaign not found"


@pytest.mark.asyncio
async def test_campaign_invalid_id(client: AsyncClient):
    resp = await client.get("/api/campaigns/not-a-uuid/indicators")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid campaign ID format"


@pytest.mark.asyncio
async def test_campaign_timeline_from_summary(client: AsyncClient, mock_postgres):
    from tests.conftest import SAMPLE_TIMELINE

    mock_postgres.get_campaign_timeline_from_summary.return_value = SAMPLE_TIMELINE.copy()
    resp = await client.get(f"/api/campaigns/{VALID_CAMPAIGN_ID}/indicators")
    assert resp.status_code == 200
    data = resp.json()
    assert data["campaign"]["id"] == VALID_CAMPAIGN_ID
    mock_postgres.get_campaign_timeline.assert_not_called()


@pytest.mark.asyncio
async def test_campaign_start_after_end(client: AsyncClient):
    resp = await client.get(
        f"/api/campaigns/{VALID_CAMPAIGN_ID}/indicators",
        params={"start_date": "2025-01-01", "end_date": "2024-01-01"},
    )
    assert resp.status_code == 400
