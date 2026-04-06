from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.models.dashboard import DashboardSummary
from app.sanitize import reject_unknown_params

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

VALID_RANGES = {"24h", "7d", "30d"}
_ALLOWED_SUMMARY_PARAMS = frozenset({"time_range"})


@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="Dashboard summary",
    description="Landing page statistics for new indicators, active campaigns, and top threat actors.",
)
async def get_dashboard_summary(
    request: Request,
    time_range: str = Query("7d", description="Time range: 24h, 7d, or 30d"),
) -> DashboardSummary:
    reject_unknown_params(request, _ALLOWED_SUMMARY_PARAMS)
    if time_range not in VALID_RANGES:
        raise HTTPException(status_code=400, detail=f"Invalid time_range. Must be one of: {', '.join(VALID_RANGES)}")

    cache = request.app.state.cache_service
    postgres = request.app.state.postgres_service

    async def fetch() -> dict[str, Any]:
        result: dict[str, Any] = await postgres.get_dashboard_summary(time_range)
        return result

    result = await cache.get_or_fetch(f"dashboard:summary:{time_range}", 120, fetch)
    if not result:
        raise HTTPException(status_code=503, detail="Dashboard data unavailable")
    return DashboardSummary(**result)
