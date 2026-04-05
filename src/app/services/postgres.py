import asyncio
import json
import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import Row, case, delete, distinct, func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.db import (
    ActorCampaign,
    Campaign,
    CampaignIndicator,
    CampaignTimelineSummary,
    Indicator,
    ThreatActor,
    create_engine,
    create_read_engine,
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

STALENESS_THRESHOLD_S = 240

TIME_RANGE_MAP: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class PostgresService:
    def __init__(self, dsn: str, read_dsn: str = "") -> None:
        self._dsn = dsn
        self._read_dsn = read_dsn
        self._engine: AsyncEngine | None = None
        self._read_engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None
        self._read_session_factory: async_sessionmaker[AsyncSession] | None = None

    async def connect(self) -> None:
        for attempt in range(3):
            try:
                self._engine = create_engine(self._dsn)
                self._read_engine = create_read_engine(self._read_dsn, self._dsn)
                self._session_factory = create_session_factory(self._engine)
                self._read_session_factory = create_session_factory(self._read_engine)
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

    def _get_read_session(self) -> AsyncSession:
        if not self._read_session_factory:
            raise RuntimeError("PostgresService not connected")
        return self._read_session_factory()

    # ------------------------------------------------------------------
    # Shared helpers (DRY: used by both live query and summary fast path)
    # ------------------------------------------------------------------

    @staticmethod
    def _build_campaign_meta(row: Campaign) -> CampaignMeta:
        return CampaignMeta(
            id=str(row.id),
            name=str(row.name),
            description=row.description,
            first_seen=row.first_seen,
            last_seen=row.last_seen,
            status=str(row.status),
        )

    @staticmethod
    def _build_timeline_response(
        campaign: CampaignMeta,
        timeline: list[TimelinePeriod],
        summary: TimelineSummary,
    ) -> dict[str, object]:
        return CampaignTimeline(
            campaign=campaign,
            timeline=timeline,
            summary=summary,
        ).model_dump(mode="json")

    async def get_active_campaign_ids(self, since: datetime | None = None) -> list[str]:
        async with self._get_read_session() as session:
            stmt = select(Campaign.id).where(Campaign.status == "active")
            if since is not None:
                stmt = stmt.where(Campaign.last_modified >= since)
            result = await session.execute(stmt)
            return [str(row[0]) for row in result.all()]

    async def _fetch_campaign_meta(self, session: AsyncSession, campaign_id: str) -> CampaignMeta | None:
        result = await session.execute(select(Campaign).where(Campaign.id == campaign_id))
        row = result.scalar_one_or_none()
        if not row:
            return None
        return self._build_campaign_meta(row)

    # ------------------------------------------------------------------
    # Campaign timeline — live aggregation (Redshift-compatible SQL)
    # ------------------------------------------------------------------

    async def get_campaign_timeline(
        self,
        campaign_id: str,
        group_by: str,
        start_date: str | None,
        end_date: str | None,
    ) -> dict[str, object] | None:
        async with self._get_read_session() as session:
            campaign = await self._fetch_campaign_meta(session, campaign_id)
            if not campaign:
                return None

            trunc = "day" if group_by == "day" else "week"
            period_col = func.date_trunc(trunc, CampaignIndicator.observed_at).label("period")

            base_filter = [
                CampaignIndicator.campaign_id == campaign_id,
                CampaignIndicator.observed_at.isnot(None),
            ]
            if start_date:
                base_filter.append(CampaignIndicator.observed_at >= start_date)
            if end_date:
                base_filter.append(CampaignIndicator.observed_at <= end_date)

            # Query 1: aggregated counts per period
            counts_stmt = (
                select(period_col, Indicator.type, func.count().label("cnt"))
                .join(Indicator, Indicator.id == CampaignIndicator.indicator_id)
                .where(*base_filter)
                .group_by(period_col, Indicator.type)
                .order_by(period_col)
            )
            count_rows: Sequence[Row[tuple[datetime, str, int]]] = (await session.execute(counts_stmt)).all()

            # Query 2: sample indicators per period (max 20 via ROW_NUMBER)
            row_num = (
                func.row_number()
                .over(
                    partition_by=[period_col],
                    order_by=Indicator.id,
                )
                .label("rn")
            )

            sample_subq = (
                select(
                    period_col.label("period"),
                    Indicator.id.label("ind_id"),
                    Indicator.type.label("ind_type"),
                    Indicator.value.label("ind_value"),
                    row_num,
                )
                .join(Indicator, Indicator.id == CampaignIndicator.indicator_id)
                .where(*base_filter)
                .subquery()
            )

            sample_stmt = (
                select(
                    sample_subq.c.period,
                    sample_subq.c.ind_id,
                    sample_subq.c.ind_type,
                    sample_subq.c.ind_value,
                )
                .where(sample_subq.c.rn <= 20)
                .order_by(sample_subq.c.period, sample_subq.c.ind_type)
            )
            sample_rows = (await session.execute(sample_stmt)).all()

            # Query 3: summary stats
            summary_stmt = (
                select(
                    func.count(distinct(CampaignIndicator.indicator_id)).label("total"),
                    func.count(distinct(case((Indicator.type == "ip", Indicator.id)))).label("unique_ips"),
                    func.count(distinct(case((Indicator.type == "domain", Indicator.id)))).label("unique_domains"),
                )
                .join(Indicator, Indicator.id == CampaignIndicator.indicator_id)
                .where(*base_filter)
            )
            summary_row = (await session.execute(summary_stmt)).one()

            # Assemble timeline periods
            periods: dict[str, dict[str, int]] = {}
            for row in count_rows:
                key = row.period.strftime("%Y-%m-%d") if row.period else "unknown"
                if key not in periods:
                    periods[key] = {}
                periods[key][str(row.type)] = int(row.cnt)

            samples_by_period: dict[str, list[TimelinePeriodIndicator]] = {}
            for row in sample_rows:
                key = row.period.strftime("%Y-%m-%d") if row.period else "unknown"
                if key not in samples_by_period:
                    samples_by_period[key] = []
                samples_by_period[key].append(
                    TimelinePeriodIndicator(id=str(row.ind_id), type=str(row.ind_type), value=str(row.ind_value))
                )

            timeline: list[TimelinePeriod] = []
            for period_key in sorted(periods.keys()):
                timeline.append(
                    TimelinePeriod(
                        period=period_key,
                        indicators=samples_by_period.get(period_key, []),
                        counts=periods[period_key],
                    )
                )

            duration_days = 0
            if campaign.first_seen and campaign.last_seen:
                duration_days = (campaign.last_seen - campaign.first_seen).days

            summary = TimelineSummary(
                total_indicators=int(summary_row.total),
                unique_ips=int(summary_row.unique_ips),
                unique_domains=int(summary_row.unique_domains),
                duration_days=duration_days,
            )

            return self._build_timeline_response(campaign, timeline, summary)

    # ------------------------------------------------------------------
    # Campaign timeline — summary table fast path
    # ------------------------------------------------------------------

    async def get_campaign_timeline_from_summary(
        self,
        campaign_id: str,
        group_by: str,
        start_date: str | None,
        end_date: str | None,
    ) -> dict[str, object] | None:
        async with self._get_read_session() as session:
            campaign = await self._fetch_campaign_meta(session, campaign_id)
            if not campaign:
                return None

            stmt = (
                select(CampaignTimelineSummary)
                .where(
                    CampaignTimelineSummary.campaign_id == campaign_id,
                    CampaignTimelineSummary.granularity == group_by,
                )
                .order_by(CampaignTimelineSummary.period)
            )
            if start_date:
                stmt = stmt.where(CampaignTimelineSummary.period >= start_date)
            if end_date:
                stmt = stmt.where(CampaignTimelineSummary.period <= end_date)

            rows = (await session.execute(stmt)).scalars().all()
            if not rows:
                return None

            # Staleness check
            computed_times = [r.computed_at for r in rows if r.computed_at]
            if computed_times:
                newest = max(computed_times)
                now_naive = datetime.now(UTC).replace(tzinfo=None)
                age_s = (now_naive - newest).total_seconds()
                if age_s > STALENESS_THRESHOLD_S:
                    logger.warning(
                        "Summary data stale for campaign=%s granularity=%s age_s=%d",
                        campaign_id,
                        group_by,
                        int(age_s),
                    )

            try:
                timeline: list[TimelinePeriod] = []
                for row in rows:
                    counts: dict[str, int] = json.loads(str(row.type_counts)) if row.type_counts else {}
                    samples_raw: list[dict[str, str]] = (
                        json.loads(str(row.indicator_sample)) if row.indicator_sample else []
                    )
                    timeline.append(
                        TimelinePeriod(
                            period=row.period.strftime("%Y-%m-%d") if row.period else "unknown",
                            indicators=[TimelinePeriodIndicator(**s) for s in samples_raw],
                            counts=counts,
                        )
                    )

                first = rows[0]
                summary = TimelineSummary(
                    total_indicators=first.total_indicators or 0,
                    unique_ips=first.unique_ips or 0,
                    unique_domains=first.unique_domains or 0,
                    duration_days=first.duration_days or 0,
                )

                return self._build_timeline_response(campaign, timeline, summary)

            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as e:
                logger.warning("Malformed summary data for campaign=%s: %s", campaign_id, e)
                return None

    # ------------------------------------------------------------------
    # Summary table upsert (used by background worker)
    # ------------------------------------------------------------------

    async def upsert_campaign_timeline_summary(
        self,
        campaign_id: str,
        granularity: str,
        timeline_data: dict[str, object],
    ) -> None:
        summary_raw = timeline_data.get("summary")
        summary_dict: dict[str, object] = summary_raw if isinstance(summary_raw, dict) else {}

        def _int(val: object) -> int:
            if isinstance(val, int):
                return val
            if isinstance(val, (str, float)):
                return int(val)
            return 0

        s_total = _int(summary_dict.get("total_indicators", 0))
        s_ips = _int(summary_dict.get("unique_ips", 0))
        s_domains = _int(summary_dict.get("unique_domains", 0))
        s_days = _int(summary_dict.get("duration_days", 0))
        now = datetime.now(UTC).replace(tzinfo=None)

        try:
            async with self._get_session() as session:
                await session.execute(
                    delete(CampaignTimelineSummary).where(
                        CampaignTimelineSummary.campaign_id == campaign_id,
                        CampaignTimelineSummary.granularity == granularity,
                    )
                )
                timeline_list = timeline_data.get("timeline")
                periods: list[dict[str, object]] = timeline_list if isinstance(timeline_list, list) else []
                for period_data in periods:
                    counts = period_data.get("counts", {})
                    indicators = period_data.get("indicators", [])
                    period_str = period_data.get("period", "")
                    count_sum = sum(v for v in counts.values() if isinstance(v, int)) if isinstance(counts, dict) else 0
                    session.add(
                        CampaignTimelineSummary(
                            campaign_id=campaign_id,
                            granularity=granularity,
                            period=datetime.fromisoformat(str(period_str)),
                            type_counts=json.dumps(counts, default=str),
                            indicator_sample=json.dumps(indicators, default=str),
                            total_count=count_sum,
                            total_indicators=s_total,
                            unique_ips=s_ips,
                            unique_domains=s_domains,
                            duration_days=s_days,
                            computed_at=now,
                        )
                    )
                await session.commit()
        except IntegrityError:
            logger.warning("Campaign %s deleted during pre-computation, skipping", campaign_id)
        except OperationalError as e:
            logger.error("DB error upserting campaign %s summary: %s", campaign_id, e)

    # ------------------------------------------------------------------
    # Dashboard summary (Redshift-compatible parallel queries)
    # ------------------------------------------------------------------

    async def get_dashboard_summary(self, time_range: str) -> dict[str, object]:
        delta = TIME_RANGE_MAP.get(time_range, timedelta(days=7))
        cutoff = datetime.now(UTC).replace(tzinfo=None) - delta

        new_stmt = (
            select(Indicator.type, func.count().label("cnt"))
            .where(Indicator.first_seen >= cutoff)
            .group_by(Indicator.type)
        )
        active_stmt = select(func.count()).select_from(Campaign).where(Campaign.status == "active")
        top_stmt = (
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
        dist_stmt = select(Indicator.type, func.count().label("cnt")).group_by(Indicator.type)

        async with (
            self._get_read_session() as s1,
            self._get_read_session() as s2,
            self._get_read_session() as s3,
            self._get_read_session() as s4,
        ):
            new_result, active_result, top_result, dist_result = await asyncio.gather(
                s1.execute(new_stmt),
                s2.execute(active_stmt),
                s3.execute(top_stmt),
                s4.execute(dist_stmt),
            )

            new_indicators = {row.type: row.cnt for row in new_result.all()}
            active_campaigns: int = active_result.scalar_one() or 0
            top_actors = top_result.all()
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

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

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
        if self._read_engine and self._read_engine is not self._engine:
            await self._read_engine.dispose()
