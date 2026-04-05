from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class ThreatActor(Base):
    __tablename__ = "threat_actors"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    country_origin = Column(String)
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    sophistication_level = Column(String)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "sophistication_level IN ('low', 'medium', 'high', 'advanced')", name="ck_threat_actors_sophistication"
        ),
    )

    campaigns = relationship("Campaign", secondary="actor_campaigns", back_populates="threat_actors")


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text)
    first_seen = Column(DateTime)
    last_seen = Column(DateTime)
    status = Column(String)
    target_sectors = Column(String)
    target_regions = Column(String)
    last_modified = Column(DateTime, server_default=func.now())
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('active', 'dormant', 'completed')", name="ck_campaigns_status"),
        Index("idx_campaigns_status", "status"),
    )

    threat_actors = relationship("ThreatActor", secondary="actor_campaigns", back_populates="campaigns")
    indicators = relationship("Indicator", secondary="campaign_indicators", back_populates="campaigns")


class Indicator(Base):
    __tablename__ = "indicators"

    id = Column(String, primary_key=True)
    type = Column(String, nullable=False, index=True)
    value = Column(String, nullable=False, index=True)
    confidence = Column(Integer)
    first_seen = Column(DateTime, index=True)
    last_seen = Column(DateTime, index=True)
    tags = Column(String)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("type", "value"),
        CheckConstraint("type IN ('ip', 'domain', 'url', 'hash')", name="ck_indicators_type"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_indicators_confidence"),
        Index("idx_indicators_first_seen_type", "first_seen", "type"),
    )

    campaigns = relationship("Campaign", secondary="campaign_indicators", back_populates="indicators")


class ActorCampaign(Base):
    __tablename__ = "actor_campaigns"

    threat_actor_id = Column(String, ForeignKey("threat_actors.id"), primary_key=True)
    campaign_id = Column(String, ForeignKey("campaigns.id"), primary_key=True)
    confidence = Column(Integer)

    __table_args__ = (
        Index("idx_actor_campaigns_actor", "threat_actor_id"),
        Index("idx_actor_campaigns_campaign", "campaign_id"),
        CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_actor_campaigns_confidence"),
    )


class CampaignIndicator(Base):
    __tablename__ = "campaign_indicators"

    campaign_id = Column(String, ForeignKey("campaigns.id"), primary_key=True)
    indicator_id = Column(String, ForeignKey("indicators.id"), primary_key=True)
    observed_at = Column(DateTime)

    __table_args__ = (
        Index("idx_campaign_indicators_campaign", "campaign_id"),
        Index("idx_campaign_indicators_indicator", "indicator_id"),
        Index("idx_campaign_indicators_campaign_observed", "campaign_id", "observed_at"),
        Index("idx_campaign_indicators_observed", "observed_at"),
    )


class IndicatorRelationship(Base):
    __tablename__ = "indicator_relationships"

    source_indicator_id = Column(String, ForeignKey("indicators.id"), primary_key=True)
    target_indicator_id = Column(String, ForeignKey("indicators.id"), primary_key=True)
    relationship_type = Column(String, primary_key=True)
    confidence = Column(Integer)
    first_observed = Column(DateTime)

    __table_args__ = (CheckConstraint("confidence BETWEEN 0 AND 100", name="ck_indicator_relationships_confidence"),)


class Observation(Base):
    __tablename__ = "observations"

    id = Column(String, primary_key=True)
    indicator_id = Column(String, ForeignKey("indicators.id"))
    observed_at = Column(DateTime)
    source = Column(String)
    notes = Column(Text)

    __table_args__ = (
        Index("idx_observations_indicator", "indicator_id"),
        Index("idx_observations_timestamp", "observed_at"),
    )


class CampaignTimelineSummary(Base):
    """Pre-aggregated campaign timeline data.

    Redshift production mapping:
      DISTKEY(campaign_id) — most queries filter by campaign
      SORTKEY(granularity, period) — range scans on period within granularity
    """

    __tablename__ = "campaign_timeline_summary"

    campaign_id = Column(String, ForeignKey("campaigns.id"), primary_key=True)
    granularity = Column(String, primary_key=True)
    period = Column(DateTime, primary_key=True)
    type_counts = Column(Text)
    indicator_sample = Column(Text)
    total_count = Column(Integer)
    total_indicators = Column(Integer)
    unique_ips = Column(Integer)
    unique_domains = Column(Integer)
    duration_days = Column(Integer)
    computed_at = Column(DateTime, server_default=func.now())

    __table_args__ = (CheckConstraint("granularity IN ('day', 'week')", name="ck_cts_granularity"),)


def create_engine(dsn: str) -> AsyncEngine:
    async_dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(async_dsn, pool_size=20, max_overflow=10)


def create_read_engine(read_dsn: str, write_dsn: str) -> AsyncEngine:
    effective_dsn = read_dsn if read_dsn else write_dsn
    async_dsn = effective_dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(async_dsn, pool_size=20, max_overflow=10)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)
