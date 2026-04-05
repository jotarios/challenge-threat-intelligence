import os

import asyncpg
import pytest
import pytest_asyncio
from opensearchpy import AsyncOpenSearch

OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://postgres:postgres@localhost:5433/postgres")

INDEX_NAME = "indicators"


@pytest_asyncio.fixture
async def os_client():
    client = AsyncOpenSearch(hosts=[OPENSEARCH_URL], use_ssl=False, verify_certs=False)
    yield client
    await client.close()


@pytest_asyncio.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=3)
    yield pool
    await pool.close()


@pytest.mark.asyncio
async def test_opensearch_doc_count(os_client: AsyncOpenSearch):
    count = (await os_client.count(index=INDEX_NAME))["count"]
    assert count == 10000, f"Expected 10000 indicators, got {count}"


@pytest.mark.asyncio
async def test_postgres_table_counts(pg_pool: asyncpg.Pool):
    expected = {
        "threat_actors": 50,
        "campaigns": 100,
        "indicators": 10000,
        "actor_campaigns": 199,
        "campaign_indicators": 10000,
        "indicator_relationships": 4939,
        "observations": 35147,
    }
    async with pg_pool.acquire() as conn:
        for table, expected_count in expected.items():
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {table}")
            assert count == expected_count, f"{table}: expected {expected_count}, got {count}"


@pytest.mark.asyncio
async def test_opensearch_compound_nested_query(os_client: AsyncOpenSearch):
    query = {
        "query": {
            "bool": {
                "filter": [
                    {"term": {"type": "ip"}},
                    {
                        "nested": {
                            "path": "threat_actors",
                            "query": {"exists": {"field": "threat_actors.id"}},
                        }
                    },
                    {
                        "nested": {
                            "path": "campaigns",
                            "query": {"exists": {"field": "campaigns.id"}},
                        }
                    },
                ]
            }
        },
        "size": 5,
    }
    result = await os_client.search(index=INDEX_NAME, body=query)
    hits = result["hits"]["hits"]
    assert len(hits) > 0, "Expected at least one IP indicator with actors and campaigns"
    for hit in hits:
        src = hit["_source"]
        assert src["type"] == "ip"
        assert len(src["threat_actors"]) > 0
        assert len(src["campaigns"]) > 0


@pytest.mark.asyncio
async def test_olap_indexes_exist(pg_pool: asyncpg.Pool):
    async with pg_pool.acquire() as conn:
        indexes = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename IN ('campaign_indicators', 'indicators', 'campaigns')"
        )
        names = {r["indexname"] for r in indexes}
        assert "idx_campaign_indicators_campaign_observed" in names
        assert "idx_campaign_indicators_observed" in names
        assert "idx_indicators_first_seen_type" in names
        assert "idx_campaigns_status" in names


@pytest.mark.asyncio
async def test_campaign_timeline_summary_populated(pg_pool: asyncpg.Pool):
    async with pg_pool.acquire() as conn:
        count = await conn.fetchval("SELECT COUNT(*) FROM campaign_timeline_summary")
        assert count > 0, "Summary table should be populated by seed"

        row = await conn.fetchrow("SELECT * FROM campaign_timeline_summary WHERE granularity = 'day' LIMIT 1")
        assert row is not None
        assert row["total_count"] > 0
        import json

        counts = json.loads(row["type_counts"])
        assert isinstance(counts, dict)


@pytest.mark.asyncio
async def test_campaign_timeline_uses_index(pg_pool: asyncpg.Pool):
    async with pg_pool.acquire() as conn:
        campaign_id = await conn.fetchval(
            "SELECT campaign_id FROM campaign_indicators GROUP BY campaign_id ORDER BY COUNT(*) DESC LIMIT 1"
        )
        assert campaign_id is not None

        plan = await conn.fetch(
            """
            EXPLAIN (FORMAT TEXT)
            SELECT date_trunc('day', ci.observed_at), i.type, COUNT(*)
            FROM campaign_indicators ci
            JOIN indicators i ON i.id = ci.indicator_id
            WHERE ci.campaign_id = $1
            GROUP BY 1, 2
        """,
            campaign_id,
        )
        plan_text = "\n".join(r[0] for r in plan)
        assert "Seq Scan on campaign_indicators" not in plan_text


@pytest.mark.asyncio
async def test_postgres_campaign_timeline_aggregation(pg_pool: asyncpg.Pool):
    async with pg_pool.acquire() as conn:
        campaign_id = await conn.fetchval(
            "SELECT campaign_id FROM campaign_indicators GROUP BY campaign_id ORDER BY COUNT(*) DESC LIMIT 1"
        )
        assert campaign_id is not None

        rows = await conn.fetch(
            """
            SELECT
                date_trunc('day', ci.observed_at) AS period,
                i.type,
                COUNT(*) as cnt
            FROM campaign_indicators ci
            JOIN indicators i ON i.id = ci.indicator_id
            WHERE ci.campaign_id = $1
            GROUP BY period, i.type
            ORDER BY period
        """,
            campaign_id,
        )

        assert len(rows) > 0, "Expected at least one timeline bucket"
        for row in rows:
            assert row["period"] is not None
            assert row["type"] in ("ip", "domain", "url", "hash")
            assert row["cnt"] > 0
