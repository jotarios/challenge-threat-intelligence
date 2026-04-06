import pytest
from httpx import AsyncClient

from app.models.indicators import SearchParams
from tests.conftest import SAMPLE_INDICATOR


def _last_search_params(mock_opensearch) -> SearchParams:
    """Extract the SearchParams from the most recent search_indicators call."""
    mock_opensearch.search_indicators.assert_called_once()
    return mock_opensearch.search_indicators.call_args[0][0]


# ── GET /api/indicators/{id} ──────────────────────────────────────────


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
    resp = await client.get("/api/indicators/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Indicator not found"


@pytest.mark.asyncio
async def test_get_indicator_invalid_id(client: AsyncClient):
    resp = await client.get("/api/indicators/not-a-uuid")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid indicator ID format"


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


# ── Search query param validation ─────────────────────────────────────


@pytest.mark.asyncio
async def test_search_rejects_unknown_params(client: AsyncClient):
    resp = await client.get("/api/indicators/search", params={"type": "ip", "foo": "bar"})
    assert resp.status_code == 422
    assert "foo" in resp.json()["detail"]


# ── Search query param forwarding ────────────────────────────────────


@pytest.mark.asyncio
async def test_search_filter_by_type(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search", params={"type": "domain"})
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.type == "domain"


@pytest.mark.asyncio
async def test_search_filter_by_value(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search", params={"value": "192.168"})
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.value == "192.168"


@pytest.mark.asyncio
async def test_search_filter_by_threat_actor(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search", params={"threat_actor": "actor-123"})
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.threat_actor == "actor-123"


@pytest.mark.asyncio
async def test_search_filter_by_campaign(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search", params={"campaign": "camp-456"})
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.campaign == "camp-456"


@pytest.mark.asyncio
async def test_search_filter_by_first_seen_after(client: AsyncClient, mock_opensearch):
    resp = await client.get(
        "/api/indicators/search", params={"first_seen_after": "2024-11-01T00:00:00"}
    )
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.first_seen_after is not None
    assert params.first_seen_after.year == 2024
    assert params.first_seen_after.month == 11
    assert params.first_seen_after.day == 1


@pytest.mark.asyncio
async def test_search_filter_by_last_seen_before(client: AsyncClient, mock_opensearch):
    resp = await client.get(
        "/api/indicators/search", params={"last_seen_before": "2024-12-31T23:59:59"}
    )
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.last_seen_before is not None
    assert params.last_seen_before.year == 2024
    assert params.last_seen_before.month == 12
    assert params.last_seen_before.day == 31


@pytest.mark.asyncio
async def test_search_pagination(client: AsyncClient, mock_opensearch):
    resp = await client.get("/api/indicators/search", params={"page": 3, "limit": 50})
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.page == 3
    assert params.limit == 50


@pytest.mark.asyncio
async def test_search_page_below_minimum(client: AsyncClient):
    resp = await client.get("/api/indicators/search", params={"page": 0})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_all_params_combined(client: AsyncClient, mock_opensearch):
    resp = await client.get(
        "/api/indicators/search",
        params={
            "type": "hash",
            "value": "abc123",
            "threat_actor": "actor-999",
            "campaign": "camp-001",
            "first_seen_after": "2024-01-01T00:00:00",
            "last_seen_before": "2024-06-30T00:00:00",
            "page": 2,
            "limit": 25,
        },
    )
    assert resp.status_code == 200
    params = _last_search_params(mock_opensearch)
    assert params.type == "hash"
    assert params.value == "abc123"
    assert params.threat_actor == "actor-999"
    assert params.campaign == "camp-001"
    assert params.first_seen_after is not None
    assert params.last_seen_before is not None
    assert params.page == 2
    assert params.limit == 25
