# Threat Intelligence API - Deep Codebase Analysis

## 1. Project Overview

This is a **FastAPI backend** powering a real-time security dashboard for threat intelligence. Security analysts use it to investigate malicious indicators (IPs, domains, URLs, file hashes), map threat actor relationships, and analyze historical campaign data.

The architecture follows **CQRS (Command Query Responsibility Segregation)** with **polyglot persistence**: OpenSearch handles real-time search, PostgreSQL handles OLAP analytics, and Redis provides caching with pre-computed views.

---

## 2. Repository Structure

```
challenge-threat-intelligence/
├── src/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app, lifespan, middleware, exception handling
│   │   ├── config.py               # Pydantic Settings (env-based config)
│   │   ├── db.py                   # SQLAlchemy 2.0 ORM models (schema source of truth)
│   │   ├── middleware.py           # CorrelationIdMiddleware for request tracing
│   │   ├── sanitize.py            # Input validation, UUID checks, OpenSearch escaping
│   │   ├── models/                 # Pydantic request/response schemas
│   │   │   ├── indicators.py       # IndicatorDetail, SearchResponse, SearchParams
│   │   │   ├── campaigns.py        # CampaignTimeline, TimelineParams
│   │   │   ├── dashboard.py        # DashboardSummary, TopThreatActor
│   │   │   └── health.py           # HealthResponse, ServiceStatus
│   │   ├── routers/                # API route handlers
│   │   │   ├── indicators.py       # /api/indicators/{id}, /api/indicators/search
│   │   │   ├── campaigns.py        # /api/campaigns/{id}/indicators
│   │   │   ├── dashboard.py        # /api/dashboard/summary
│   │   │   └── health.py           # /health
│   │   └── services/               # Backend service clients
│   │       ├── opensearch.py       # Async OpenSearch client
│   │       ├── postgres.py         # Async PostgreSQL client (SQLAlchemy + asyncpg)
│   │       ├── redis_client.py     # Async Redis client
│   │       ├── cache.py            # Cache-aside pattern (get_or_fetch)
│   │       └── background.py       # Periodic dashboard pre-computation
│   ├── alembic/
│   │   ├── env.py                  # Alembic config, reads models from db.py
│   │   └── versions/
│   │       └── e46ef46d0daf_initial_schema.py
│   └── tests/
│       ├── conftest.py             # Fixtures, mocks, sample data
│       ├── test_indicators.py      # 8 tests
│       ├── test_campaigns.py       # 5 tests
│       ├── test_dashboard.py       # 3 tests
│       ├── test_health.py          # 3 tests
│       ├── test_cache.py           # 3 tests
│       └── test_integration.py     # 4 tests (requires live services)
├── scripts/
│   ├── seed.py                     # ETL: SQLite -> PostgreSQL + OpenSearch
│   └── k6_loadtest.js              # k6 load test (50 VUs, 30s)
├── data/
│   ├── schema.sql                  # Reference SQL schema
│   └── threat_intel.db             # SQLite seed DB (gitignored)
├── docs/
│   ├── PRD.md                      # Product requirements
│   └── README.md                   # Dev guide with architecture and examples
├── Dockerfile                      # Production image (python:3.12-slim + uvicorn)
├── Dockerfile.seed                 # Seed container (migrations + data load)
├── docker-compose.yml              # 5 services: app, seed, opensearch, postgres, redis
├── Makefile                        # 13 dev targets
├── alembic.ini                     # Alembic configuration
├── pyproject.toml                  # Dependencies, ruff, mypy, pytest config
├── CLAUDE.md                       # AI assistant guidance
└── .env.example                    # Environment variable template
```

---

## 3. Infrastructure & Docker Setup

### docker-compose.yml — 5 Services

| Service | Image | Port | Health Check | Notes |
|---------|-------|------|-------------|-------|
| `app` | Custom (Dockerfile) | 8000 | — | Depends on `seed` completing successfully |
| `seed` | Custom (Dockerfile.seed) | — | — | Runs migrations + data load, then exits |
| `opensearch` | opensearch:2.x | 9200 | `/_cluster/health` (30 retries) | Single-node, security disabled |
| `postgres` | postgres:16 | 5433→5432 | `pg_isready` (10 retries) | Credentials: postgres:postgres |
| `redis` | redis:7-alpine | 6379 | `redis-cli ping` (10 retries) | Default config |

**Boot sequence:** OpenSearch + PostgreSQL + Redis start first → `seed` waits for health checks, runs migrations and loads data → `app` starts only after seed exits successfully.

### Dockerfiles

- **Dockerfile (production):** `python:3.12-slim`, installs deps from pyproject.toml, runs `uvicorn app.main:app` on port 8000.
- **Dockerfile.seed:** Same base, also copies `scripts/` and `data/`, runs `python scripts/seed.py`.

### Makefile Targets

| Command | Description |
|---------|-------------|
| `make up` | `docker compose up -d` |
| `make down` | `docker compose down -v` (removes volumes) |
| `make seed` | Local seed run (migrations + data load) |
| `make migrate` | `alembic upgrade head` |
| `make revision msg="..."` | Auto-generate migration from ORM models |
| `make test` | Unit tests (excludes integration) |
| `make test-integration` | Integration tests (requires running services) |
| `make lint` | `ruff check` |
| `make format` | `ruff format` + `ruff check --fix` |
| `make typecheck` | `mypy --strict` |
| `make check` | lint + typecheck + test (pre-commit gate) |
| `make loadtest` | `k6 run scripts/k6_loadtest.js` |
| `make logs` | `docker compose logs -f app` |

---

## 4. Configuration

### Environment Variables (`config.py`)

```python
class Settings(BaseSettings):
    opensearch_url: str = "http://localhost:9200"
    postgres_dsn: str = "postgresql://postgres:postgres@localhost:5433/postgres"
    redis_url: str = "redis://localhost:6379"
    log_level: str = "INFO"
    dashboard_refresh_interval: int = 120  # seconds
```

- Loaded from environment with no prefix, case-insensitive.
- Singleton via `@lru_cache` on `get_settings()`.

### pyproject.toml Highlights

- **Build system:** hatchling
- **Python:** >=3.12
- **Key dependencies:** FastAPI 0.135.3, SQLAlchemy 2.0.49, asyncpg 0.31.0, opensearch-py 3.1.0, redis 7.4.0, structlog 25.5.0
- **Dev tools:** pytest 9.0.2, pytest-asyncio 1.3.0, httpx 0.28.1, ruff 0.15.9, mypy 1.20.0
- **Ruff rules:** F, E, W, I, UP, B, SIM, RUF (ignores B008 for FastAPI defaults)
- **Mypy:** strict mode with pydantic plugin
- **Pytest:** `asyncio_mode = "auto"` (all async tests run automatically)

---

## 5. Database Schema

SQLAlchemy models in `src/app/db.py` define **7 tables** (3 entities, 3 junction tables, 1 event table):

### Entity Tables

**`threat_actors`**
| Column | Type | Constraints |
|--------|------|-------------|
| id | String | PK |
| name | String | NOT NULL |
| description | Text | nullable |
| country_origin | String | — |
| first_seen | DateTime | — |
| last_seen | DateTime | — |
| sophistication_level | String | CHECK: low/medium/high/advanced |
| created_at | DateTime | server default: now() |

**`campaigns`**
| Column | Type | Constraints |
|--------|------|-------------|
| id | String | PK |
| name | String | NOT NULL |
| description | Text | nullable |
| first_seen | DateTime | — |
| last_seen | DateTime | — |
| status | String | CHECK: active/dormant/completed |
| target_sectors | String | — |
| target_regions | String | — |
| created_at | DateTime | server default: now() |

**`indicators`**
| Column | Type | Constraints |
|--------|------|-------------|
| id | String | PK |
| type | String | NOT NULL, indexed, CHECK: ip/domain/url/hash |
| value | String | NOT NULL, indexed |
| confidence | Integer | CHECK: 0-100 |
| first_seen | DateTime | indexed |
| last_seen | DateTime | indexed |
| tags | String | CSV format |
| created_at | DateTime | server default: now() |
| — | — | UNIQUE(type, value) |

### Junction Tables

**`actor_campaigns`** — many-to-many between threat_actors and campaigns
- Composite PK: (threat_actor_id, campaign_id)
- confidence: Integer (0-100)
- Indexed on both FK columns

**`campaign_indicators`** — many-to-many between campaigns and indicators
- Composite PK: (campaign_id, indicator_id)
- observed_at: DateTime (when the indicator was seen in the campaign)
- Indexed on both FK columns

**`indicator_relationships`** — self-referential many-to-many on indicators
- Composite PK: (source_indicator_id, target_indicator_id, relationship_type)
- relationship_type: same_campaign / same_infrastructure / co_occurring
- confidence: Integer (0-100)
- first_observed: DateTime

### Event Table

**`observations`** — tracks when/where indicators were observed
- id: String (PK)
- indicator_id: String (FK)
- observed_at: DateTime (indexed)
- source: String
- notes: Text
- Indexed on indicator_id and observed_at

### Relationship Graph

```
threat_actors <--M:M--> campaigns     (via actor_campaigns, with confidence)
campaigns     <--M:M--> indicators    (via campaign_indicators, with observed_at)
indicators    <--M:M--> indicators    (via indicator_relationships, typed + confidence)
indicators    <--1:M--> observations  (temporal event log)
```

---

## 6. API Endpoints — Detailed Behavior

### `GET /health`

**Purpose:** Service connectivity check for all three backing stores.

**Logic:**
1. Concurrently pings OpenSearch, PostgreSQL, and Redis (2s timeout each).
2. Returns per-service status (up/down) with latency_ms.
3. Overall status: "healthy" (all up) / "degraded" (some up) / "unhealthy" (all down).
4. HTTP 200 for healthy/degraded, HTTP 503 for unhealthy.

**Response model:** `HealthResponse { status, services: dict[str, ServiceStatus] }`

---

### `GET /api/indicators/search`

**Purpose:** Multi-parameter paginated search across the active threat landscape.

**Data source:** OpenSearch (direct, no cache).

**Query parameters:**
| Param | Type | Default | Validation |
|-------|------|---------|------------|
| type | ip/domain/url/hash | None | Literal enum |
| value | str | None | max_length=256 |
| threat_actor | str | None | max_length=256 |
| campaign | str | None | max_length=256 |
| first_seen_after | datetime | None | ISO format |
| last_seen_before | datetime | None | ISO format |
| page | int | 1 | >= 1 |
| limit | int | 20 | 1-100 |

**OpenSearch query construction:**
- `type` → `term` filter on `type` field
- `value` → `wildcard` on `value.keyword` (wildcards escaped via `sanitize.py`)
- `threat_actor` → `nested` query on `threat_actors.name` (match)
- `campaign` → `nested` query on `campaigns.name` (match)
- `first_seen_after` → `range` filter (gte) on `first_seen`
- `last_seen_before` → `range` filter (lte) on `last_seen`
- Pagination: `from = (page-1) * limit`, `size = limit`

**Response model:** `SearchResponse { data: list[IndicatorSearchItem], total, page, limit, total_pages }`

---

### `GET /api/indicators/{indicator_id}`

**Purpose:** Full indicator details with related threat actors, campaigns, and indicators.

**Data source:** Redis cache (300s TTL) → OpenSearch fallback.

**Validation:** indicator_id must be valid UUID format (400 otherwise).

**Logic:**
1. Check Redis cache (`indicator:{sanitized_id}`).
2. On miss, fetch from OpenSearch by document ID.
3. OpenSearch returns a denormalized document with nested threat_actors, campaigns, related_indicators.
4. Validate via `IndicatorDetail` Pydantic model.
5. Cache result, return. 404 if not found.

**Response model:** `IndicatorDetail { id, type, value, confidence, first_seen, last_seen, threat_actors[], campaigns[], related_indicators[] }`

---

### `GET /api/campaigns/{campaign_id}/indicators`

**Purpose:** Campaign timeline — time-series indicator data grouped by day or week.

**Data source:** Redis cache (300s TTL) → PostgreSQL fallback.

**Query parameters:**
| Param | Type | Default | Validation |
|-------|------|---------|------------|
| group_by | day/week | day | Pattern match |
| start_date | date | None | Must be <= end_date |
| end_date | date | None | Must be >= start_date |

**PostgreSQL query:**
1. Fetch Campaign row by ID (404 if not found).
2. Join `campaign_indicators` → `indicators`, filter by campaign_id and optional date range.
3. Group by `date_trunc(group_by, observed_at)`.
4. Per period: collect indicators (max 20), count by type (ip/domain/url/hash).
5. Calculate summary: total_indicators, unique_ips, unique_domains, duration_days.

**Cache key:** `campaign:{id}:timeline:{group_by}:{start}:{end}` (300s TTL).

**Response model:** `CampaignTimeline { campaign: CampaignMeta, timeline: list[TimelinePeriod], summary: TimelineSummary }`

---

### `GET /api/dashboard/summary`

**Purpose:** Landing page statistics for the security dashboard.

**Data source:** Redis (pre-computed every 120s by background task) → PostgreSQL fallback.

**Query parameters:**
- `time_range`: "24h" / "7d" / "30d" (default: "7d")

**PostgreSQL queries (4 aggregations):**
1. **new_indicators:** Count indicators by type where `first_seen >= (now - time_range)`.
2. **active_campaigns:** Count campaigns with `status = 'active'`.
3. **top_threat_actors:** Top 5 by unique indicator count (joins through actor_campaigns → campaign_indicators).
4. **indicator_distribution:** Count all indicators by type (no time filter).

**Cache key:** `dashboard:summary:{time_range}` (120s TTL).

**Response model:** `DashboardSummary { time_range, new_indicators, active_campaigns, top_threat_actors[], indicator_distribution }`

---

## 7. Service Layer — Detailed Implementation

### OpenSearchService (`services/opensearch.py`)

- **Connection:** `AsyncOpenSearch` client, 3-attempt retry with exponential backoff.
- **get_indicator(id):** Direct document fetch by ID, validates via Pydantic, graceful error handling for NotFound/malformed docs.
- **search_indicators(params):** Builds dynamic bool query with term/wildcard/nested/range filters. Handles both dict and int formats for `hits.total`. Skips malformed results with warning logs.
- **Index:** "indicators" with nested mappings for threat_actors, campaigns, related_indicators.

### PostgresService (`services/postgres.py`)

- **Connection:** `create_async_engine` with asyncpg driver, pool_size=10, max_overflow=0, 3-attempt retry.
- **get_campaign_timeline():** Uses `date_trunc` for period grouping, joins campaign_indicators → indicators, limits 20 indicators per period.
- **get_dashboard_summary():** 4 separate queries: new indicator counts, active campaign count, top 5 threat actors (by indicator count), overall indicator distribution.
- **DSN conversion:** Automatically converts `postgresql://` to `postgresql+asyncpg://` for async driver.

### RedisService (`services/redis_client.py`)

- **Connection:** `redis.asyncio.from_url()` with `decode_responses=True`, 3-attempt retry.
- **get(key):** Returns parsed JSON dict or None. Catches RedisConnectionError, TimeoutError, JSONDecodeError, ResponseError — all non-fatal.
- **setex(key, ttl, value):** JSON serializes with `default=str` for datetime handling. Non-fatal on failure.
- **Design:** Complete graceful degradation — Redis being down never crashes the application.

### CacheService (`services/cache.py`)

- **Pattern:** Cache-aside via `get_or_fetch(key, ttl, fetch_fn)`.
- **Logic:** Check Redis → on miss, call fetch_fn → cache result → return.
- **Resilience:** Cache write failures are logged as warnings but don't affect the response.

### Background Task (`services/background.py`)

- **Purpose:** Pre-computes dashboard summaries for all 3 time ranges (24h, 7d, 30d) every 120 seconds.
- **Lifecycle:** Started as asyncio task in app lifespan, cancelled on shutdown.
- **TTL:** 120 seconds per key (matches refresh interval).
- **Errors:** Caught and logged, never crash the loop.

---

## 8. Middleware & Observability

### CorrelationIdMiddleware (`middleware.py`)

- Extracts `x-request-id` header or generates a UUID.
- Stores in `contextvars` for structured logging context.
- Measures request duration in milliseconds.
- Logs every request: `{correlation_id, method, path, status_code, duration_ms}`.

### Structured Logging

- Uses **structlog** with JSON renderer and ISO timestamps.
- Context variables propagate correlation IDs across async boundaries.
- Every service logs connection attempts, retries, failures, and key operations.

---

## 9. Input Validation & Security (`sanitize.py`)

- **`is_valid_uuid(value)`:** Regex-based UUID v4 validation. Used for indicator_id and campaign_id path params.
- **`escape_opensearch_wildcard(value)`:** Escapes `*` and `?` characters to prevent query injection in OpenSearch wildcard queries.
- **`clamp_length(value, max_length=256)`:** Truncates overly long inputs.
- **`sanitize_cache_key_segment(value)`:** Strips non-alphanumeric characters (except `_-`) from Redis cache keys to prevent key injection.
- **Pydantic validation:** All request parameters validated via Pydantic models with type constraints, length limits, and range checks.

---

## 10. Seed Data Pipeline (`scripts/seed.py`)

### ETL Process

1. **Wait for services** — polls OpenSearch and PostgreSQL health (60s timeout).
2. **Run migrations** — `alembic upgrade head` via subprocess.
3. **Load SQLite** — reads all 7 tables from `data/threat_intel.db` into memory.
4. **Seed PostgreSQL** — truncates tables in dependency order, then bulk inserts.
5. **Build OpenSearch documents** — denormalizes relational data into nested documents:
   - Each indicator gets embedded arrays of threat_actors, campaigns, and related_indicators (top 5 by confidence).
   - Tags split from CSV to arrays.
6. **Seed OpenSearch** — creates index with nested mappings, bulk indexes in 500-doc batches.
7. **Verify** — prints row/document counts.

### Seed Data Volume

| Table | Count |
|-------|-------|
| threat_actors | 50 |
| campaigns | 100 |
| indicators | 10,000 |
| actor_campaigns | 199 |
| campaign_indicators | 10,000 |
| indicator_relationships | 4,939 |
| observations | 35,147 |

### OpenSearch Index Mapping

- **Settings:** 1 shard, 0 replicas (single-node local dev).
- **Fields:** id (keyword), type (keyword), value (text+keyword), confidence (integer), first_seen/last_seen (date), tags (keyword array).
- **Nested objects:** threat_actors, campaigns, related_indicators — enables nested queries for filtering by actor/campaign name.

---

## 11. Test Suite

### Unit Tests (22 tests across 6 files)

All unit tests use **mocked services** (AsyncMock) injected into `app.state`. The async test client is built with httpx's `ASGITransport`.

**test_cache.py (3 tests):**
- Cache hit returns cached data without calling fetch.
- Cache miss triggers fetch and writes to cache.
- Redis failure gracefully degrades (fetch still works).

**test_indicators.py (8 tests):**
- Happy path: full indicator detail with nested data.
- 404 on missing indicator.
- 400 on invalid UUID.
- Search with type filter, default params, bad dates (422), limit > 100 (422), empty results.

**test_campaigns.py (5 tests):**
- Timeline by day and by week.
- 404 on missing campaign.
- 400 on invalid UUID.
- 400 when start_date > end_date.

**test_dashboard.py (3 tests):**
- Default 7d range.
- 24h range.
- 400 on invalid range ("1y").

**test_health.py (3 tests):**
- All services up → healthy (200).
- One service down → degraded (200).
- All services down → unhealthy (503).

### Integration Tests (4 tests, requires `make up && make seed`)

- **test_opensearch_doc_count:** Verifies 10,000 indicators indexed.
- **test_opensearch_compound_nested_query:** Tests nested bool query filtering on threat_actors and campaigns.
- **test_postgres_table_counts:** Verifies exact row counts across all 7 tables.
- **test_postgres_campaign_timeline_aggregation:** Validates timeline bucketing with correct indicator type counts.

---

## 12. Load Testing (`scripts/k6_loadtest.js`)

**Tool:** k6 (Grafana's load testing framework).

**Configuration:**
- 50 virtual users, 30 seconds duration.
- `BASE_URL` configurable via environment variable.

**Traffic Distribution:**
| Weight | Endpoint | SLA (p95) |
|--------|----------|-----------|
| 40% | Search (random type filter, limit 10/20/50) | < 100ms |
| 30% | Indicator detail (random from discovered IDs) | < 100ms |
| 15% | Campaign timeline (random campaign, day/week) | < 250ms |
| 10% | Dashboard summary (random range) | < 250ms |
| 5% | Health check | < 100ms |

**Setup phase:** Discovers real indicator and campaign IDs via search endpoint before load test starts.

**Exit criteria (CI-friendly):**
- Per-endpoint p95 latency must stay under SLA.
- Error rate must be < 1%.
- Success rate must be > 99%.
- Non-zero exit code on any violation.

**Custom metrics:** Per-endpoint latency trends + SLA violation counter + success rate.

---

## 13. Architecture Patterns & Design Decisions

### CQRS (Command Query Responsibility Segregation)
- **Write path:** External (not exposed via API). The seed script is the only write mechanism.
- **Read paths:** Separated by query characteristics:
  - **Real-time lookups:** OpenSearch (indicator search and details).
  - **Analytical queries:** PostgreSQL (campaign timelines, dashboard aggregations).

### Polyglot Persistence
Each data store is chosen for its strength:
- **OpenSearch:** Full-text search, nested document queries, wildcard matching.
- **PostgreSQL:** Relational joins, date_trunc aggregations, COUNT/GROUP BY analytics. Locally substitutes for Redshift (production target).
- **Redis:** Sub-millisecond cache reads, JSON serialization, TTL-based expiry.

### Cache-Aside + Pre-Computation
- **Cache-aside:** Indicator details and campaign timelines cached on first access (300s TTL).
- **Pre-computation:** Dashboard summaries computed every 120s by a background task and pushed to Redis. The API reads pre-computed values, falling back to PostgreSQL if Redis is empty.

### Denormalization at Index Time
OpenSearch documents embed nested threat_actors, campaigns, and related_indicators directly into each indicator document. This avoids joins at query time and enables single-document retrieval for the detail endpoint. The trade-off is that updates require re-indexing.

### Graceful Degradation
- Redis failures never crash the app — cache misses fall through to the source.
- OpenSearch and PostgreSQL have 3-attempt retry with exponential backoff on connection.
- Health endpoint distinguishes "degraded" (partial failure) from "unhealthy" (total failure).

### Async Throughout
Every I/O operation is async: FastAPI handlers, OpenSearch queries (AsyncOpenSearch), PostgreSQL queries (asyncpg + SQLAlchemy async), Redis operations (redis.asyncio), and the background pre-computation loop.

---

## 14. Production Architecture (from PRD)

The local Docker Compose setup simulates a production AWS deployment:

| Local | Production |
|-------|-----------|
| OpenSearch 2.x container | AWS OpenSearch Service |
| PostgreSQL 16 container | AWS Redshift |
| Redis 7 container | AWS ElastiCache |
| Docker Compose | AWS ECS + Fargate |
| localhost:8000 | AWS ALB + WAF |
| — | AWS Kinesis (ingestion) |
| — | GitHub Actions CI/CD with OIDC |

**Production scale target:** 100M+ indicators with concurrent dashboard sessions.

---

## 15. Key Specificities & Notable Details

1. **String PKs everywhere** — all entity IDs are `String`, not `UUID` type, stored as UUIDs in string format. UUID validation happens at the API layer via regex, not the database.

2. **Tags as CSV** — indicator tags are stored as a single comma-separated string in PostgreSQL, split into arrays only at OpenSearch indexing time.

3. **PostgreSQL port 5433** — mapped externally to avoid conflicts with local PostgreSQL installs (internal container still uses 5432).

4. **No write API** — the application is read-only. All data enters through the seed script. The PRD mentions AWS Kinesis for production ingestion, but this is not implemented.

5. **OpenSearch security disabled** — `DISABLE_SECURITY_PLUGIN=true` for local development. Production would use AWS-managed security.

6. **Single Alembic migration** — the entire schema is created in one initial migration (no incremental evolution yet).

7. **`observed_at` in campaign_indicators** — this is the key column for timeline grouping, not the indicator's own first_seen/last_seen. This means the same indicator can appear in different time periods across different campaigns.

8. **Top 5 related indicators** — the seed script limits related_indicators per document to 5 (sorted by confidence descending), even though there may be more in the database. This is a deliberate denormalization trade-off.

9. **Pool configuration** — PostgreSQL engine uses `pool_size=10, max_overflow=0`, meaning exactly 10 connections max. This is conservative and tuned for local dev.

10. **JSON serialization in Redis** — uses `json.dumps(value, default=str)` which auto-converts datetimes to strings. On read, datetimes remain as strings (not re-parsed) — the Pydantic models handle coercion.

11. **Wildcard escaping** — search by value uses OpenSearch `wildcard` query with `*{escaped_value}*` pattern. The sanitize module escapes literal `*` and `?` to prevent query manipulation.

12. **20 indicators per timeline period** — the campaign timeline endpoint caps indicators at 20 per time bucket to prevent response bloat on large campaigns.

13. **`B008` ruff ignore** — FastAPI's `Depends()` calls in function signatures trigger ruff's "function call in default argument" rule; this is intentionally suppressed.

14. **No pagination on timeline/dashboard** — only the search endpoint supports pagination. Timeline returns all periods, dashboard returns all stats. This works because of the date range filters and pre-computation.

15. **Background task cancellation** — the periodic pre-compute task is properly cancelled during shutdown via `task.cancel()` in the lifespan context manager, preventing orphaned asyncio tasks.
