import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import distinct, func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import (
    ActorCampaign,
    Campaign,
    CampaignIndicator,
    Indicator,
    ThreatActor,
    create_engine,
    create_session_factory,
)
from app.models.campaigns import (
    CampaignMeta,
    CampaignTimeline,
    TimelinePeriod,
    TimelinePeriodIndicator,
    TimelineSummary,
)
from app.models.dashboard import DashboardSummary, TopThreatActor

logger = logging.getLogger(__name__)

TIME_RANGE_MAP = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class PostgresService:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        for attempt in range(3):
            try:
                self._engine = create_engine(self._dsn)
                self._session_factory = create_session_factory(self._engine)
                async with self._session_factory() as session:
                    await session.execute(text("SELECT 1"))
                logger.info("PostgreSQL connected via SQLAlchemy")
                return
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2**attempt)
                else:
                    logger.error("PostgreSQL connection failed after 3 attempts: %s", e)
                    raise

    def _get_session(self) -> AsyncSession:
        if not self._session_factory:
            raise RuntimeError("PostgresService not connected")
        return self._session_factory()

    async def get_campaign_timeline(
        self,
        campaign_id: str,
        group_by: str,
        start_date: str | None,
        end_date: str | None,
    ) -> dict[str, Any] | None:
        async with self._get_session() as session:
            result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
            campaign_row = result.scalar_one_or_none()
            if not campaign_row:
                return None

            campaign = CampaignMeta(
                id=campaign_row.id,
                name=campaign_row.name,
                description=campaign_row.description,
                first_seen=campaign_row.first_seen,
                last_seen=campaign_row.last_seen,
                status=campaign_row.status,
            )

            trunc = "day" if group_by == "day" else "week"
            period_col = func.date_trunc(trunc, CampaignIndicator.observed_at).label("period")

            stmt = (
                select(period_col, Indicator.id, Indicator.type, Indicator.value)
                .join(Indicator, Indicator.id == CampaignIndicator.indicator_id)
                .where(CampaignIndicator.campaign_id == campaign_id)
            )

            if start_date:
                stmt = stmt.where(CampaignIndicator.observed_at >= start_date)
            if end_date:
                stmt = stmt.where(CampaignIndicator.observed_at <= end_date)

            stmt = stmt.order_by(period_col, Indicator.type, Indicator.id)
            rows = (await session.execute(stmt)).all()

            periods: dict[str, list[Any]] = {}
            for row in rows:
                p = row.period
                key = p.strftime("%Y-%m-%d") if p else "unknown"
                periods.setdefault(key, []).append(row)

            timeline: list[TimelinePeriod] = []
            total_indicators = 0
            unique_ips: set[str] = set()
            unique_domains: set[str] = set()

            for period_key, period_rows in sorted(periods.items()):
                counts: dict[str, int] = {}
                indicators: list[TimelinePeriodIndicator] = []
                for row in period_rows:
                    itype = row.type
                    counts[itype] = counts.get(itype, 0) + 1
                    if len(indicators) < 20:
                        indicators.append(
                            TimelinePeriodIndicator(
                                id=row.id,
                                type=row.type,
                                value=row.value,
                            )
                        )
                    if itype == "ip":
                        unique_ips.add(row.id)
                    elif itype == "domain":
                        unique_domains.add(row.id)
                    total_indicators += 1

                timeline.append(
                    TimelinePeriod(
                        period=period_key,
                        indicators=indicators,
                        counts=counts,
                    )
                )

            duration_days = 0
            if campaign.first_seen and campaign.last_seen:
                duration_days = (campaign.last_seen - campaign.first_seen).days

            result_model = CampaignTimeline(
                campaign=campaign,
                timeline=timeline,
                summary=TimelineSummary(
                    total_indicators=total_indicators,
                    unique_ips=len(unique_ips),
                    unique_domains=len(unique_domains),
                    duration_days=duration_days,
                ),
            )
            return result_model.model_dump(mode="json")

    async def get_dashboard_summary(self, time_range: str) -> dict[str, Any]:
        delta = TIME_RANGE_MAP.get(time_range, timedelta(days=7))
        cutoff = datetime.utcnow() - delta

        async with self._get_session() as session:
            new_result = await session.execute(
                select(Indicator.type, func.count().label("cnt"))
                .where(Indicator.first_seen >= cutoff)
                .group_by(Indicator.type)
            )
            new_indicators = {row.type: row.cnt for row in new_result.all()}

            active_result = await session.execute(
                select(func.count()).select_from(Campaign).where(Campaign.status == "active")
            )
            active_campaigns = active_result.scalar_one() or 0

            top_result = await session.execute(
                select(
                    ThreatActor.id,
                    ThreatActor.name,
                    func.count(distinct(CampaignIndicator.indicator_id)).label("indicator_count"),
                )
                .join(ActorCampaign, ActorCampaign.threat_actor_id == ThreatActor.id)
                .join(CampaignIndicator, CampaignIndicator.campaign_id == ActorCampaign.campaign_id)
                .group_by(ThreatActor.id, ThreatActor.name)
                .order_by(text("indicator_count DESC"))
                .limit(5)
            )
            top_actors = top_result.all()

            dist_result = await session.execute(
                select(Indicator.type, func.count().label("cnt")).group_by(Indicator.type)
            )
            indicator_distribution = {row.type: row.cnt for row in dist_result.all()}

        summary = DashboardSummary(
            time_range=time_range,
            new_indicators=new_indicators,
            active_campaigns=active_campaigns,
            top_threat_actors=[
                TopThreatActor(id=r.id, name=r.name, indicator_count=r.indicator_count) for r in top_actors
            ],
            indicator_distribution=indicator_distribution,
        )
        return summary.model_dump(mode="json")

    async def check_health(self) -> bool:
        try:
            async with self._get_session() as session:
                await session.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        if self._engine:
            await self._engine.dispose()
