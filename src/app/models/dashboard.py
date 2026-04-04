from pydantic import BaseModel


class TopThreatActor(BaseModel):
    id: str
    name: str
    indicator_count: int


class DashboardSummary(BaseModel):
    time_range: str
    new_indicators: dict[str, int]
    active_campaigns: int
    top_threat_actors: list[TopThreatActor]
    indicator_distribution: dict[str, int]
