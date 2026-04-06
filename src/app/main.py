import asyncio
import contextlib
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.middleware import CorrelationIdMiddleware, RateLimitMiddleware
from app.routers import campaigns, dashboard, health, indicators
from app.services.background import run_dashboard_precompute, run_timeline_precompute
from app.services.cache import CacheService
from app.services.opensearch import OpenSearchService
from app.services.postgres import PostgresService
from app.services.rate_limiter import RateLimiter
from app.services.redis_client import RedisService


def setup_logging(log_level: str) -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)

    redis_service = RedisService(settings.redis_url)
    opensearch_service = OpenSearchService(settings.opensearch_url)
    postgres_service = PostgresService(settings.postgres_dsn, settings.postgres_read_dsn)

    await redis_service.connect()
    try:
        await opensearch_service.connect()
    except Exception:
        await redis_service.close()
        raise
    try:
        await postgres_service.connect()
    except Exception:
        await opensearch_service.close()
        await redis_service.close()
        raise

    cache_service = CacheService(redis_service)

    app.state.redis_service = redis_service
    app.state.opensearch_service = opensearch_service
    app.state.postgres_service = postgres_service
    app.state.cache_service = cache_service

    if settings.rate_limit_enabled and redis_service.client is not None:
        refill_rate = settings.rate_limit_capacity / settings.rate_limit_window_seconds
        app.state.rate_limiter = RateLimiter(
            redis_client=redis_service.client,
            capacity=settings.rate_limit_capacity,
            refill_rate=refill_rate,
        )
        app.state.rate_limit_exempt_paths = {
            p.strip() for p in settings.rate_limit_exempt_paths.split(",") if p.strip()
        }
        app.state.rate_limit_capacity = settings.rate_limit_capacity
    else:
        app.state.rate_limiter = None

    dashboard_task = asyncio.create_task(
        run_dashboard_precompute(redis_service, postgres_service, settings.dashboard_refresh_interval)
    )
    timeline_task = asyncio.create_task(
        run_timeline_precompute(redis_service, postgres_service, settings.timeline_refresh_interval)
    )

    yield

    dashboard_task.cancel()
    timeline_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await dashboard_task
    with contextlib.suppress(asyncio.CancelledError):
        await timeline_task

    await opensearch_service.close()
    await postgres_service.close()
    await redis_service.close()


app = FastAPI(
    title="Threat Intelligence API",
    description="Real-time security dashboard backend with CQRS architecture. "
    "OpenSearch for fast indicator lookups, PostgreSQL for campaign analytics, Redis for caching.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(RateLimitMiddleware)
app.include_router(indicators.router)
app.include_router(campaigns.router)
app.include_router(dashboard.router)
app.include_router(health.router)


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "status_code": exc.status_code},
    )
