from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ThreatActorRef(BaseModel):
    id: str
    name: str
    confidence: int


class CampaignRef(BaseModel):
    id: str
    name: str
    active: bool


class RelatedIndicatorRef(BaseModel):
    id: str
    type: str
    value: str
    relationship: str


class IndicatorDetail(BaseModel):
    id: str
    type: str
    value: str
    confidence: int
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    threat_actors: list[ThreatActorRef] = []
    campaigns: list[CampaignRef] = []
    related_indicators: list[RelatedIndicatorRef] = []

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "id": "550e8400-e29b-41d4-a716-446655440000",
                    "type": "ip",
                    "value": "192.168.1.100",
                    "confidence": 85,
                    "first_seen": "2024-11-15T10:30:00Z",
                    "last_seen": "2024-12-20T14:22:00Z",
                    "threat_actors": [{"id": "actor-123", "name": "APT-North", "confidence": 90}],
                    "campaigns": [{"id": "camp-456", "name": "Operation ShadowNet", "active": True}],
                    "related_indicators": [
                        {
                            "id": "uuid",
                            "type": "domain",
                            "value": "malicious.example.com",
                            "relationship": "same_campaign",
                        }
                    ],
                }
            ]
        }
    }


class IndicatorSearchItem(BaseModel):
    id: str
    type: str
    value: str
    confidence: int
    first_seen: datetime | None = None
    campaign_count: int = 0
    threat_actor_count: int = 0


class SearchResponse(BaseModel):
    data: list[IndicatorSearchItem]
    total: int
    page: int
    limit: int
    total_pages: int


class SearchParams(BaseModel):
    type: Literal["ip", "domain", "url", "hash"] | None = Field(
        None, description="Indicator type: ip, domain, url, hash"
    )
    value: str | None = Field(None, max_length=256, description="Partial match on indicator value")
    threat_actor: str | None = Field(None, max_length=256, description="Filter by threat actor ID")
    campaign: str | None = Field(None, max_length=256, description="Filter by campaign ID")
    first_seen_after: datetime | None = Field(None, description="Indicators first seen after this date")
    last_seen_before: datetime | None = Field(None, description="Indicators last seen before this date")
    page: int = Field(1, ge=1, description="Page number (1-based)")
    limit: int = Field(20, ge=1, le=100, description="Results per page (max 100)")
