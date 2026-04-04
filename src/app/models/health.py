from typing import Literal

from pydantic import BaseModel


class ServiceStatus(BaseModel):
    status: str
    latency_ms: float


class HealthResponse(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    services: dict[str, ServiceStatus]
