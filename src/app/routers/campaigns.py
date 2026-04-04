from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.models.campaigns import CampaignTimeline, TimelineParams

router = APIRouter(prefix="/api/campaigns", tags=["Campaigns"])


def get_timeline_params(
    group_by: str = Query("day", pattern="^(day|week)$", description="Group timeline by day or week"),
    start_date: date | None = Query(None, description="Start date for timeline range"),
    end_date: date | None = Query(None, description="End date for timeline range"),
) -> TimelineParams:
    try:
        return TimelineParams(group_by=group_by, start_date=start_date, end_date=end_date)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=str(e.errors()[0]["msg"])) from e


@router.get(
    "/{campaign_id}/indicators",
    response_model=CampaignTimeline,
    summary="Campaign timeline",
    description="Retrieve time-series indicator data for a campaign, grouped by day or week.",
)
async def get_campaign_timeline(
    campaign_id: str,
    request: Request,
    params: TimelineParams = Depends(get_timeline_params),
) -> CampaignTimeline:
    cache = request.app.state.cache_service
    postgres = request.app.state.postgres_service

    start_str = params.start_date.isoformat() if params.start_date else ""
    end_str = params.end_date.isoformat() if params.end_date else ""
    cache_key = f"campaign:{campaign_id}:timeline:{params.group_by}:{start_str}:{end_str}"

    async def fetch() -> dict[str, Any] | None:
        result: dict[str, Any] | None = await postgres.get_campaign_timeline(
            campaign_id,
            params.group_by,
            str(params.start_date) if params.start_date else None,
            str(params.end_date) if params.end_date else None,
        )
        return result

    result = await cache.get_or_fetch(cache_key, 300, fetch)
    if result is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return CampaignTimeline(**result)
