import math
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.models.indicators import IndicatorDetail, IndicatorSearchItem, SearchParams, SearchResponse
from app.sanitize import is_valid_uuid, sanitize_cache_key_segment

router = APIRouter(prefix="/api/indicators", tags=["Indicators"])


def get_search_params(
    type: str | None = Query(None, description="Indicator type: ip, domain, url, hash"),
    value: str | None = Query(None, description="Partial match on indicator value"),
    threat_actor: str | None = Query(None, description="Filter by threat actor name"),
    campaign: str | None = Query(None, description="Filter by campaign name"),
    first_seen_after: datetime | None = Query(None, description="Indicators first seen after this date"),
    last_seen_before: datetime | None = Query(None, description="Indicators last seen before this date"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Results per page (max 100)"),
) -> SearchParams:
    return SearchParams(
        type=type,
        value=value,
        threat_actor=threat_actor,
        campaign=campaign,
        first_seen_after=first_seen_after,
        last_seen_before=last_seen_before,
        page=page,
        limit=limit,
    )


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="Search indicators",
    description="Multi-parameter paginated search across the active threat landscape.",
)
async def search_indicators(
    request: Request,
    params: SearchParams = Depends(get_search_params),
) -> SearchResponse:
    opensearch = request.app.state.opensearch_service
    items, total = await opensearch.search_indicators(params)
    total_pages = math.ceil(total / params.limit) if total > 0 else 0
    return SearchResponse(
        data=[IndicatorSearchItem(**item) for item in items],
        total=total,
        page=params.page,
        limit=params.limit,
        total_pages=total_pages,
    )


@router.get(
    "/{indicator_id}",
    response_model=IndicatorDetail,
    summary="Get indicator details",
    description="Retrieve complete context for a specific indicator including related actors, campaigns, and indicators.",  # noqa: E501
)
async def get_indicator(indicator_id: str, request: Request) -> IndicatorDetail:
    if not is_valid_uuid(indicator_id):
        raise HTTPException(status_code=400, detail="Invalid indicator ID format")

    cache = request.app.state.cache_service
    opensearch = request.app.state.opensearch_service
    safe_key = sanitize_cache_key_segment(indicator_id)

    async def fetch() -> dict[str, Any] | None:
        result: dict[str, Any] | None = await opensearch.get_indicator(indicator_id)
        return result

    result = await cache.get_or_fetch(f"indicator:{safe_key}", 300, fetch)
    if result is None:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return IndicatorDetail(**result)
