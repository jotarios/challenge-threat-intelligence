from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.models.campaigns import CampaignTimeline, TimelineParams
from app.sanitize import is_valid_uuid, sanitize_cache_key_segment

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
    if not is_valid_uuid(campaign_id):
        raise HTTPException(status_code=400, detail="Invalid campaign ID format")

    cache = request.app.state.cache_service
    postgres = request.app.state.postgres_service

    safe_key = sanitize_cache_key_segment(campaign_id)
    start_str = params.start_date.isoformat() if params.start_date else ""
    end_str = params.end_date.isoformat() if params.end_date else ""
    cache_key = f"campaign:{safe_key}:timeline:{params.group_by}:{start_str}:{end_str}"

    async def fetch() -> dict[str, Any] | None:
        summary_result: dict[str, Any] | None = await postgres.get_campaign_timeline_from_summary(
            campaign_id,
            params.group_by,
            str(params.start_date) if params.start_date else None,
            str(params.end_date) if params.end_date else None,
        )
        if summary_result is not None:
            return summary_result
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
