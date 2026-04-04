import pytest
from httpx import AsyncClient

from tests.conftest import SAMPLE_INDICATOR


@pytest.mark.asyncio
async def test_get_indicator_happy_path(client: AsyncClient, mock_opensearch):
    resp = await client.get(f"/api/indicators/{SAMPLE_INDICATOR['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == SAMPLE_INDICATOR["id"]
    assert data["type"] == "ip"
    assert len(data["threat_actors"]) == 1
    assert len(data["campaigns"]) == 1


@pytest.mark.asyncio
async def test_get_indicator_not_found(client: AsyncClient, mock_opensearch):
    mock_opensearch.get_indicator.return_value = None
    resp = await client.get("/api/indicators/nonexistent-id")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Indicator not found"


@pytest.mark.asyncio
async def test_search_happy_path(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search", params={"type": "ip", "limit": 10})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["page"] == 1
    assert data["limit"] == 10
    assert data["total_pages"] == 1
    assert len(data["data"]) == 1
    assert data["data"][0]["type"] == "ip"


@pytest.mark.asyncio
async def test_search_no_params(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search")
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["limit"] == 20


@pytest.mark.asyncio
async def test_search_bad_date(client: AsyncClient):
    resp = await client.get("/api/indicators/search", params={"first_seen_after": "not-a-date"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_limit_too_high(client: AsyncClient):
    resp = await client.get("/api/indicators/search", params={"limit": 200})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_empty_results(client: AsyncClient, mock_opensearch):
    mock_opensearch.search_indicators.return_value = ([], 0)
    resp = await client.get("/api/indicators/search")
    assert resp.status_code == 200
    data = resp.json()
    assert data["data"] == []
    assert data["total"] == 0
    assert data["total_pages"] == 0
