from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db import Campaign, CampaignTimelineSummary
from app.services.postgres import STALENESS_THRESHOLD_S, PostgresService


def _make_summary_row(
    campaign_id: str = "camp-1",
    granularity: str = "day",
    period: datetime | None = None,
    type_counts: str = '{"ip": 5, "domain": 3}',
    indicator_sample: str = '[{"id": "ind-1", "type": "ip", "value": "10.0.0.1"}]',
    total_count: int = 8,
    total_indicators: int = 100,
    unique_ips: int = 20,
    unique_domains: int = 30,
    duration_days: int = 75,
    computed_at: datetime | None = None,
) -> CampaignTimelineSummary:
    row = CampaignTimelineSummary()
    row.campaign_id = campaign_id
    row.granularity = granularity
    row.period = period or datetime(2024, 10, 1)
    row.type_counts = type_counts
    row.indicator_sample = indicator_sample
    row.total_count = total_count
    row.total_indicators = total_indicators
    row.unique_ips = unique_ips
    row.unique_domains = unique_domains
    row.duration_days = duration_days
    row.computed_at = computed_at or datetime.now(UTC).replace(tzinfo=None)
    return row


def _make_campaign_row(
    campaign_id: str = "camp-1",
    name: str = "Operation X",
    status: str = "active",
) -> Campaign:
    row = Campaign()
    row.id = campaign_id
    row.name = name
    row.description = None
    row.first_seen = datetime(2024, 10, 1)
    row.last_seen = datetime(2024, 12, 15)
    row.status = status
    return row


@pytest.mark.asyncio
async def test_summary_happy_path():
    svc = PostgresService.__new__(PostgresService)
    campaign_row = _make_campaign_row()
    summary_rows = [_make_summary_row()]

    mock_session = AsyncMock()
    campaign_result = MagicMock()
    campaign_result.scalar_one_or_none.return_value = campaign_row
    summary_result = MagicMock()
    summary_result.scalars.return_value.all.return_value = summary_rows

    mock_session.execute = AsyncMock(side_effect=[campaign_result, summary_result])

    svc._read_session_factory = MagicMock()
    svc._read_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    svc._read_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    result = await svc.get_campaign_timeline_from_summary("camp-1", "day", None, None)
    assert result is not None
    assert result["campaign"]["id"] == "camp-1"
    assert len(result["timeline"]) == 1
    assert result["summary"]["unique_ips"] == 20


@pytest.mark.asyncio
async def test_summary_empty_returns_none():
    svc = PostgresService.__new__(PostgresService)
    campaign_row = _make_campaign_row()

    mock_session = AsyncMock()
    campaign_result = MagicMock()
    campaign_result.scalar_one_or_none.return_value = campaign_row
    summary_result = MagicMock()
    summary_result.scalars.return_value.all.return_value = []

    mock_session.execute = AsyncMock(side_effect=[campaign_result, summary_result])

    svc._read_session_factory = MagicMock()
    svc._read_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    svc._read_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    result = await svc.get_campaign_timeline_from_summary("camp-1", "day", None, None)
    assert result is None


@pytest.mark.asyncio
async def test_summary_stale_still_returns_data(caplog: pytest.LogCaptureFixture):
    svc = PostgresService.__new__(PostgresService)
    campaign_row = _make_campaign_row()
    stale_time = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=STALENESS_THRESHOLD_S + 60)
    summary_rows = [_make_summary_row(computed_at=stale_time)]

    mock_session = AsyncMock()
    campaign_result = MagicMock()
    campaign_result.scalar_one_or_none.return_value = campaign_row
    summary_result = MagicMock()
    summary_result.scalars.return_value.all.return_value = summary_rows

    mock_session.execute = AsyncMock(side_effect=[campaign_result, summary_result])

    svc._read_session_factory = MagicMock()
    svc._read_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    svc._read_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with caplog.at_level("WARNING"):
        result = await svc.get_campaign_timeline_from_summary("camp-1", "day", None, None)

    assert result is not None
    assert "stale" in caplog.text.lower()


@pytest.mark.asyncio
async def test_summary_malformed_json_returns_none():
    svc = PostgresService.__new__(PostgresService)
    campaign_row = _make_campaign_row()
    bad_row = _make_summary_row(type_counts="NOT VALID JSON")

    mock_session = AsyncMock()
    campaign_result = MagicMock()
    campaign_result.scalar_one_or_none.return_value = campaign_row
    summary_result = MagicMock()
    summary_result.scalars.return_value.all.return_value = [bad_row]

    mock_session.execute = AsyncMock(side_effect=[campaign_result, summary_result])

    svc._read_session_factory = MagicMock()
    svc._read_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    svc._read_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    result = await svc.get_campaign_timeline_from_summary("camp-1", "day", None, None)
    assert result is None
