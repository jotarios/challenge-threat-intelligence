import os
import sqlite3
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests
from opensearchpy import OpenSearch, helpers
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def to_iso(dt_str: str | None) -> str | None:
    if not dt_str:
        return None
    return dt_str.replace(" ", "T") + "Z" if "T" not in dt_str else dt_str


OPENSEARCH_URL = os.environ.get("OPENSEARCH_URL", "http://localhost:9200")
POSTGRES_DSN = os.environ.get("POSTGRES_DSN", "postgresql://postgres:postgres@localhost:5433/postgres")
SQLITE_PATH = Path(__file__).parent.parent / "data" / "threat_intel.db"
PROJECT_ROOT = Path(__file__).parent.parent

INDEX_NAME = "indicators"
BATCH_SIZE = 500


def wait_for_services():
    print("Waiting for services...")
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            resp = requests.get(f"{OPENSEARCH_URL}/_cluster/health", timeout=2)
            if resp.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        print("ERROR: OpenSearch not ready after 60s")
        sys.exit(1)
    print("  OpenSearch ready")

    engine = create_engine(POSTGRES_DSN)
    while time.time() < deadline:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            break
        except Exception:
            time.sleep(2)
    else:
        print("ERROR: PostgreSQL not ready after 60s")
        sys.exit(1)
    engine.dispose()
    print("  PostgreSQL ready")


def load_sqlite():
    if not SQLITE_PATH.exists():
        print(f"ERROR: SQLite file not found at {SQLITE_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row

    tables = {}
    for table in [
        "threat_actors",
        "campaigns",
        "indicators",
        "actor_campaigns",
        "campaign_indicators",
        "indicator_relationships",
        "observations",
    ]:
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        tables[table] = [dict(row) for row in rows]
        print(f"  SQLite: {table} = {len(tables[table])} rows")

    conn.close()
    return tables


def run_migrations():
    print("\nRunning Alembic migrations...")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, "POSTGRES_DSN": POSTGRES_DSN},
    )
    if result.returncode != 0:
        print(f"  Alembic stderr: {result.stderr}")
        print("ERROR: Alembic migration failed")
        sys.exit(1)
    print("  Migrations applied")


def seed_postgres(tables: dict):
    print("\nSeeding PostgreSQL...")
    engine = create_engine(POSTGRES_DSN)

    truncate_order = [
        "observations",
        "indicator_relationships",
        "campaign_indicators",
        "actor_campaigns",
        "indicators",
        "campaigns",
        "threat_actors",
    ]

    insert_order = [
        (
            "threat_actors",
            ["id", "name", "description", "country_origin", "first_seen", "last_seen", "sophistication_level"],
        ),
        (
            "campaigns",
            ["id", "name", "description", "first_seen", "last_seen", "status", "target_sectors", "target_regions"],
        ),
        ("indicators", ["id", "type", "value", "confidence", "first_seen", "last_seen", "tags"]),
        ("actor_campaigns", ["threat_actor_id", "campaign_id", "confidence"]),
        ("campaign_indicators", ["campaign_id", "indicator_id", "observed_at"]),
        (
            "indicator_relationships",
            ["source_indicator_id", "target_indicator_id", "relationship_type", "confidence", "first_observed"],
        ),
        ("observations", ["id", "indicator_id", "observed_at", "source", "notes"]),
    ]

    with Session(engine) as session:
        for table in truncate_order:
            session.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        session.commit()

        for table_name, columns in insert_order:
            rows = tables[table_name]
            if not rows:
                continue
            col_names = ", ".join(columns)
            placeholders = ", ".join([f":{col}" for col in columns])
            sql = text(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})")
            batch = [{col: row.get(col) for col in columns} for row in rows]
            session.execute(sql, batch)
            print(f"  PostgreSQL: {table_name} = {len(rows)} rows inserted")

        session.commit()

    engine.dispose()


def build_opensearch_docs(tables: dict) -> list[dict]:
    print("\nBuilding denormalized OpenSearch documents...")

    campaigns_by_id = {c["id"]: c for c in tables["campaigns"]}
    actors_by_id = {a["id"]: a for a in tables["threat_actors"]}

    campaign_to_actors: dict[str, list[dict]] = defaultdict(list)
    for ac in tables["actor_campaigns"]:
        actor = actors_by_id.get(ac["threat_actor_id"])
        if actor:
            campaign_to_actors[ac["campaign_id"]].append(
                {
                    "id": actor["id"],
                    "name": actor["name"],
                    "confidence": ac["confidence"],
                }
            )

    indicator_to_campaigns: dict[str, list[dict]] = defaultdict(list)
    indicator_to_actors: dict[str, set[str]] = defaultdict(set)
    actor_refs: dict[str, dict] = {}

    for ci in tables["campaign_indicators"]:
        campaign = campaigns_by_id.get(ci["campaign_id"])
        if campaign:
            indicator_to_campaigns[ci["indicator_id"]].append(
                {
                    "id": campaign["id"],
                    "name": campaign["name"],
                    "active": campaign["status"] == "active",
                }
            )
            for actor_ref in campaign_to_actors.get(ci["campaign_id"], []):
                key = f"{ci['indicator_id']}:{actor_ref['id']}"
                indicator_to_actors[ci["indicator_id"]].add(actor_ref["id"])
                if key not in actor_refs or (actor_ref["confidence"] or 0) > (actor_refs[key]["confidence"] or 0):
                    actor_refs[key] = actor_ref

    indicator_to_actor_list: dict[str, list[dict]] = defaultdict(list)
    for ind_id, actor_ids in indicator_to_actors.items():
        for aid in actor_ids:
            ref = actor_refs.get(f"{ind_id}:{aid}")
            if ref:
                indicator_to_actor_list[ind_id].append(ref)

    indicators_by_id = {i["id"]: i for i in tables["indicators"]}

    indicator_to_related: dict[str, list[dict]] = defaultdict(list)
    seen_pairs: dict[str, set[str]] = defaultdict(set)
    for rel in tables["indicator_relationships"]:
        src = rel["source_indicator_id"]
        tgt = rel["target_indicator_id"]
        conf = rel["confidence"] or 0
        rel_type = rel["relationship_type"]

        for ind_id, other_id in [(src, tgt), (tgt, src)]:
            if other_id in seen_pairs[ind_id]:
                continue
            seen_pairs[ind_id].add(other_id)
            other = indicators_by_id.get(other_id)
            if other:
                indicator_to_related[ind_id].append(
                    {
                        "id": other["id"],
                        "type": other["type"],
                        "value": other["value"],
                        "relationship": rel_type,
                        "_confidence": conf,
                    }
                )

    for ind_id in indicator_to_related:
        items = indicator_to_related[ind_id]
        items.sort(key=lambda x: (-x["_confidence"], x["id"]))
        indicator_to_related[ind_id] = [{k: v for k, v in item.items() if k != "_confidence"} for item in items[:5]]

    docs = []
    for ind in tables["indicators"]:
        tags = []
        if ind.get("tags"):
            tags = [t.strip() for t in ind["tags"].split(",") if t.strip()]

        doc = {
            "_index": INDEX_NAME,
            "_id": ind["id"],
            "_source": {
                "id": ind["id"],
                "type": ind["type"],
                "value": ind["value"],
                "confidence": ind["confidence"],
                "first_seen": to_iso(ind["first_seen"]),
                "last_seen": to_iso(ind["last_seen"]),
                "tags": tags,
                "threat_actors": indicator_to_actor_list.get(ind["id"], []),
                "campaigns": indicator_to_campaigns.get(ind["id"], []),
                "related_indicators": indicator_to_related.get(ind["id"], []),
            },
        }
        docs.append(doc)

    return docs


INDEX_MAPPING = {
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
    "mappings": {
        "properties": {
            "id": {"type": "keyword"},
            "type": {"type": "keyword"},
            "value": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "confidence": {"type": "integer"},
            "first_seen": {"type": "date"},
            "last_seen": {"type": "date"},
            "tags": {"type": "keyword"},
            "threat_actors": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "confidence": {"type": "integer"},
                },
            },
            "campaigns": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "name": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
                    "active": {"type": "boolean"},
                },
            },
            "related_indicators": {
                "type": "nested",
                "properties": {
                    "id": {"type": "keyword"},
                    "type": {"type": "keyword"},
                    "value": {"type": "text"},
                    "relationship": {"type": "keyword"},
                },
            },
        }
    },
}


def seed_opensearch(docs: list[dict]):
    print("\nSeeding OpenSearch...")
    client = OpenSearch(
        hosts=[OPENSEARCH_URL],
        use_ssl=False,
        verify_certs=False,
    )

    if client.indices.exists(index=INDEX_NAME):
        client.indices.delete(index=INDEX_NAME)
        print(f"  Deleted existing index '{INDEX_NAME}'")

    client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)
    print(f"  Created index '{INDEX_NAME}' with nested mapping")

    success, errors = helpers.bulk(client, docs, chunk_size=BATCH_SIZE, raise_on_error=False)
    if errors:
        print(f"  WARNING: {len(errors)} bulk indexing errors")
        if len(errors) > 0:
            print(f"  First error: {errors[0]}")
    print(f"  OpenSearch: {success} documents indexed")

    client.indices.refresh(index=INDEX_NAME)
    count = client.count(index=INDEX_NAME)["count"]
    print(f"  OpenSearch: {count} documents in index")

    client.close()


def verify_counts():
    print("\n--- Verification ---")
    engine = create_engine(POSTGRES_DSN)
    with Session(engine) as session:
        for table in [
            "threat_actors",
            "campaigns",
            "indicators",
            "actor_campaigns",
            "campaign_indicators",
            "indicator_relationships",
            "observations",
        ]:
            count = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            print(f"  PostgreSQL {table}: {count}")
    engine.dispose()

    client = OpenSearch(hosts=[OPENSEARCH_URL], use_ssl=False, verify_certs=False)
    count = client.count(index=INDEX_NAME)["count"]
    print(f"  OpenSearch {INDEX_NAME}: {count}")
    client.close()


def main():
    print("=== Threat Intelligence Seed Script ===\n")

    wait_for_services()

    run_migrations()

    print("\nLoading SQLite data...")
    tables = load_sqlite()

    seed_postgres(tables)

    docs = build_opensearch_docs(tables)
    seed_opensearch(docs)

    verify_counts()

    print("\n=== Seeding complete ===")


if __name__ == "__main__":
    main()
