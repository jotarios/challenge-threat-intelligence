from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CampaignMeta(BaseModel):
    id: str
    name: str
    description: str | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    status: str


class TimelinePeriodIndicator(BaseModel):
    id: str
    type: str
    value: str


class TimelinePeriod(BaseModel):
    period: str
    indicators: list[TimelinePeriodIndicator]
    counts: dict[str, int]


class TimelineSummary(BaseModel):
    total_indicators: int
    unique_ips: int
    unique_domains: int
    duration_days: int


class CampaignTimeline(BaseModel):
    campaign: CampaignMeta
    timeline: list[TimelinePeriod]
    summary: TimelineSummary


class TimelineParams(BaseModel):
    group_by: Literal["day", "week"] = Field("day", description="Group timeline by day or week")
    start_date: date | None = Field(None, description="Start date for timeline range")
    end_date: date | None = Field(None, description="End date for timeline range")

    @model_validator(mode="after")
    def validate_date_range(self) -> "TimelineParams":
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must be before end_date")
        return self
