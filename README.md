# Threat Intelligence API

A high-performance FastAPI backend for a real-time security dashboard. Enables security analysts to investigate malicious indicators (IPs, domains, URLs, file hashes), map threat actor relationships, and analyze historical campaign data.

## Architecture

CQRS with polyglot persistence: OpenSearch for real-time indicator lookups, PostgreSQL for campaign analytics, Redis for caching, pre-computed views, and rate limiting.

```
                    ┌───────────────────────────┐
                    │      FastAPI App          │
                    │    (Docker container)     │
                    │                           │
                    │  Routers -> Services      │
                    │  Middleware (rate limit,  │
                    │  correlation IDs, logging)│
                    └────────────┬──────────────┘
                                 │
              ┌──────────────────┼─────────────────┐
              │                  │                 │
        ┌─────▼───────┐   ┌──────▼──────┐   ┌──────▼──────┐
        │ OpenSearch  │   │   Redis     │   │ PostgreSQL  │
        │ (Hot Tier)  │   │  (Cache +   │   │(Cold/OLAP)  │
        │             │   │  Rate Limit)│   │             │
        │ Denormalized│   │ Cache-aside │   │ SQLAlchemy  │
        │ indicators  │   │ + pre-comp. │   │ + Alembic   │
        └─────────────┘   └─────────────┘   └─────────────┘

         Endpoints 1&2     All endpoints    Endpoints 3&4
```

### Final Thoughts

**Why Polyglot Persistence?**

- Gain: Each store is optimized for its access pattern: OpenSearch for sub-100ms full-text search, PostgreSQL/Redshift for complex analytical joins, Redis for sub-millisecond cached reads. Hot and Cold tiers scale independently.
- Trade-off: Operational complexity, Data consistency and overhead.
- Alternative considered: A single PostgreSQL instance with materialized views could serve all four endpoints at the scale of 10K indicators. The polyglot approach is justified only at the stated 100M+ indicator target.

**Why CQRS — Read-Only API with External Ingestion?**

- Gain: The API surface is simple and cacheable — no write-path complexity (conflict resolution, write-through invalidation, optimistic locking).
- Trade-off: In this particular challenge, I haven't worked on the ingestion path, however eventual consistency is the choiced option, for a real-time security dashboard, stale indicators during a high-velocity attack could mean missed detections.
- Alternative considered: Ingestion can scale independently via Kinesis/Firehose without affecting query latency.

**Why OpenSearch/ElasticSearch?**

- Gain: A single query returns the full indicator context (actors, campaigns, related indicators) — no joins, no fan-out, no N+1.
- Trade-off: Update amplification. Search filters use IDs (`campaigns.id`, `threat_actors.id`), so query correctness is not affected by stale display fields. However, denormalized display fields (campaign name, actor name, active status) are embedded in every indicator document. Updating these fields still requires touching every linked document — at 100M indicators this is a heavy reindexing operation, even though it only affects response rendering, not query accuracy.
- Alternative considered: Store only IDs in OpenSearch, resolve names at query time. If in the future we want to add search by campaign name, we should consider it.

**Why Redis Cache-Aside with TTL-Based Expiry?**

- Gain: Simple implementation — no distributed invalidation protocol, no pub/sub, no versioning. Also, Graceful degradation. if Redis is down, the system falls back to source databases with higher latency but no data loss.
- Trade-off: No proactive invalidation and cache stampede risk.
- Alternative considered: As I said before, I haven't worked on the ingestion path, but this should be considered when it is done.

**Why Background Precomputation Workers?**

- Gain: Dashboard and timeline endpoints serve precomputed results from Redis, meeting the <250ms p95 target without running expensive aggregations on the hot path. The `campaign_timeline_summary` table in PostgreSQL acts as a materialized cache, reducing repeated analytical query load on the read replica.
- Trade-off: Single-instance assumption, so no distributed coordination implemented. There is no leader election, distributed lock, or deduplication. Multiple replicas precomputing the same dashboard summary waste resources.
- Alternative considered: Dedicated and distributed worker processes (Celery / ECS scheduled task / Lambda).

**Why Read/Write DSN Separation (PostgreSQL vs. Redshift) or OLAP?**

- Gain: Analytical queries (endpoints 3 & 4) can target a read replica or Redshift without affecting the write primary. Local development uses the same PostgreSQL instance for both DSNs, keeping the local stack simple.
- Trade-off: SQL dialect divergence and replication lag. In production, the read replica introduces replication lag. Combined with the cache TTL, an analyst could see data that is stale by replication_lag + TTL seconds, but the system does not surface this to the user.
- Alternative considred: Single PostgreSQL with read replicas, no Redshift. It will depends of the scale.

**What I'd improve with more time?**

- Build the ingestion pipeline and implement the GitHub Actions CI/CD + AWS Cloud deployment.

## Prerequisites

- Docker and Docker Compose
- Python 3.12+
- `pip install ".[dev]"` (for running seed script, tests, and dev tools locally)
- [k6](https://grafana.com/docs/k6/) (for load testing, install via `brew install k6`)

## Quick Start

```bash
# Start OpenSearch, PostgreSQL, Redis, and FastAPI
make up

# Run migrations + load 10K indicators from seed data
make seed
```

## API Endpoints

Visit http://localhost:8000/docs for the interactive API docs

| Method | Path | Description | Data Source |
|--------|------|-------------|-------------|
| GET | `/api/indicators/{id}` | Indicator details with related actors, campaigns, indicators | Redis -> OpenSearch |
| GET | `/api/indicators/search` | Multi-param paginated search (type, value, actor, campaign, dates) | OpenSearch |
| GET | `/api/campaigns/{id}/indicators` | Campaign timeline grouped by day/week | Redis -> PostgreSQL |
| GET | `/api/dashboard/summary` | Landing page stats (24h/7d/30d) | Redis (pre-computed) |
| GET | `/health` | Service connectivity check | All services |

## Example Requests

```bash
# Get indicator details
curl http://localhost:8000/api/indicators/550e8400-e29b-41d4-a716-446655440000

# Search indicators by type
curl "http://localhost:8000/api/indicators/search?type=ip&limit=5"

# Search with multiple filters
curl "http://localhost:8000/api/indicators/search?type=domain&threat_actor=actor-123&page=1&limit=20"

# Campaign timeline
curl "http://localhost:8000/api/campaigns/camp-456/indicators?group_by=day"

# Dashboard summary (default 7d)
curl http://localhost:8000/api/dashboard/summary

# Dashboard summary for last 24 hours
curl "http://localhost:8000/api/dashboard/summary?time_range=24h"

# Health check
curl http://localhost:8000/health
```


## Make Targets

| Command | Description |
|---------|-------------|
| `make up` | Start all services via Docker Compose |
| `make down` | Stop and remove all services and volumes |
| `make seed` | Run Alembic migrations + load seed data into OpenSearch and PostgreSQL |
| `make migrate` | Run Alembic migrations to head |
| `make revision msg="..."` | Auto-generate a new Alembic migration from model changes |
| `make test` | Run unit tests (57 tests) |
| `make test-integration` | Run integration tests (requires running services + seed data) |
| `make lint` | Run ruff linter |
| `make format` | Run ruff formatter + auto-fix lint issues |
| `make typecheck` | Run mypy in strict mode |
| `make check` | Run lint + typecheck + tests |
| `make loadtest` | Run k6 load test (50 VUs, 30s) against running services |
| `make logs` | Tail FastAPI application logs |

## Rate Limiting

All endpoints are rate-limited using a token bucket algorithm backed by Redis. Each client IP gets a bucket of tokens that refills over time.

Default configuration: 100 requests per 60 seconds per client IP. Responses include standard headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Bucket capacity |
| `X-RateLimit-Remaining` | Tokens left after this request |
| `Retry-After` | Seconds until a token is available (429 responses only) |

When the bucket is empty, the API returns HTTP 429 with a `Retry-After` header.

Configuration via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `RATE_LIMIT_ENABLED` | `true` | Enable/disable rate limiting |
| `RATE_LIMIT_CAPACITY` | `100` | Max burst size (tokens) |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Refill period |
| `RATE_LIMIT_EXEMPT_PATHS` | `/docs,/openapi.json` | Comma-separated paths to exempt |

If Redis is unavailable, the rate limiter fails open (requests are allowed through).

## Load Testing

The project includes a [k6](https://grafana.com/docs/k6/) load test that exercises all API endpoints with realistic traffic distribution and validates against the SLA targets from the PRD.

```bash
make up            # Start services
make loadtest      # 50 virtual users, 30 seconds
```

The test automatically discovers real indicator and campaign IDs during a warmup phase, then generates traffic with this distribution: 40% search, 30% indicator detail, 15% campaign timeline, 10% dashboard, 5% health.

k6 thresholds enforce the PRD performance requirements:
- Real-time endpoints (indicators, health): p95 < 100ms
- Analytical endpoints (campaigns, dashboard): p95 < 250ms
- Error rate: < 1%

The test exits with a non-zero code if any threshold is breached, making it suitable for CI pipelines.

You can override the target URL with `BASE_URL=http://remote:8000 make loadtest`.

Since k6 runs all virtual users from a single IP, you may need to disable rate limiting during load tests:

```bash
RATE_LIMIT_ENABLED=false make loadtest
```

## Project Structure

```
src/
  app/
    main.py            # FastAPI app, lifespan, middleware
    config.py          # pydantic-settings configuration
    db.py              # SQLAlchemy models (source of truth for DB schema)
    middleware.py       # Rate limiting + correlation ID + request logging
    sanitize.py        # Input validation helpers
    models/            # Pydantic request/response schemas
    routers/           # API route handlers
    services/          # OpenSearch, PostgreSQL, Redis, cache, rate limiter
  alembic/
    env.py             # Alembic environment (imports app.db.Base)
    versions/          # Auto-generated migrations
  tests/
    conftest.py        # Async fixtures, DI overrides, mock services
    test_indicators.py # Indicator endpoint tests
    test_campaigns.py  # Campaign endpoint tests
    test_dashboard.py  # Dashboard endpoint tests
    test_health.py     # Health check tests
    test_cache.py      # Cache service tests
    test_rate_limiter.py       # Rate limiter unit tests
    test_rate_limit_middleware.py # Rate limit middleware tests
    test_integration.py# Integration tests (real Docker services)
scripts/
  seed.py              # ETL: runs migrations, then SQLite -> OpenSearch + PostgreSQL
  k6_loadtest.js       # k6 load test with per-endpoint SLA thresholds
data/
  schema.sql           # Original SQL schema (reference only, models are in src/app/db.py)
  threat_intel.db      # SQLite seed data (gitignored)
docs/
  PRD.md               # Full product requirements
```

## Tech Stack

- **FastAPI** with async handlers and Pydantic validation
- **SQLAlchemy** 2.0 async ORM with asyncpg driver
- **Alembic** for database migrations (auto-generated from models)
- **OpenSearch** 2.x with nested document mappings
- **PostgreSQL** 16 (Redshift mock for local dev)
- **Redis** 7 with async client
- **structlog** for JSON structured logging with correlation IDs
- **ruff** for linting and formatting
- **mypy** for static type checking (strict mode)
- **Docker Compose** for local orchestration
- **pytest** + **httpx** for async test suite

## Development

```bash
# Install dev dependencies
pip install ".[dev]"

# Format code
make format

# Run all checks (lint + typecheck + tests)
make check

# Modify the database schema
# 1. Edit models in src/app/db.py
# 2. Generate migration:
make revision msg="add new column to indicators"
# 3. Apply:
make migrate
```
