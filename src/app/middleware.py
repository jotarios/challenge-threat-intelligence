import contextvars
import time
import uuid

import structlog
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.services.rate_limiter import RateLimiter

correlation_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")

logger = structlog.get_logger()


class RateLimitMiddleware(BaseHTTPMiddleware):
    @staticmethod
    def _get_client_ip(request: Request, trusted_proxies: set[str]) -> str:
        direct_ip = request.client.host if request.client else "unknown"
        if direct_ip in trusted_proxies:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return direct_ip

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
        if limiter is None:
            return await call_next(request)

        exempt_paths: set[str] = getattr(request.app.state, "rate_limit_exempt_paths", set())
        capacity: int = getattr(request.app.state, "rate_limit_capacity", 100)

        trusted_proxies: set[str] = getattr(request.app.state, "rate_limit_trusted_proxies", set())

        if request.url.path in exempt_paths:
            return await call_next(request)

        client_ip = self._get_client_ip(request, trusted_proxies)
        allowed, remaining, retry_after = await limiter.acquire(client_ip)

        if not allowed:
            logger.warning(
                "rate_limited",
                client_ip=client_ip,
                path=request.url.path,
                retry_after=retry_after,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests",
                    "status_code": 429,
                    "retry_after": retry_after,
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(capacity),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(retry_after),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(capacity)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        cid = request.headers.get("x-request-id", str(uuid.uuid4()))
        correlation_id_var.set(cid)

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        logger.info(
            "request",
            correlation_id=cid,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
