import asyncio
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.models.health import HealthResponse, ServiceStatus

router = APIRouter(tags=["Health"])

TIMEOUT = 2.0


async def _check_service(name: str, check_fn: Callable[[], Awaitable[bool]]) -> tuple[str, ServiceStatus]:
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(check_fn(), timeout=TIMEOUT)
        latency = round((time.perf_counter() - start) * 1000, 2)
        status = "up" if result else "down"
    except (TimeoutError, Exception):
        latency = round((time.perf_counter() - start) * 1000, 2)
        status = "down"
    return name, ServiceStatus(status=status, latency_ms=latency)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Check connectivity to all backing services.",
)
async def health_check(request: Request) -> JSONResponse:
    checks = await asyncio.gather(
        _check_service("opensearch", request.app.state.opensearch_service.check_health),
        _check_service("postgresql", request.app.state.postgres_service.check_health),
        _check_service("redis", request.app.state.redis_service.ping),
    )

    services = {name: status for name, status in checks}
    up_count = sum(1 for s in services.values() if s.status == "up")

    if up_count == len(services):
        overall = "healthy"
    elif up_count > 0:
        overall = "degraded"
    else:
        overall = "unhealthy"

    response = HealthResponse(status=overall, services=services)
    status_code = 200 if overall != "unhealthy" else 503
    return JSONResponse(content=response.model_dump(), status_code=status_code)
