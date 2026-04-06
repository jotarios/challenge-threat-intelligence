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

## Prerequisites

- Docker and Docker Compose
- Python 3.12+
- `pip install ".[dev]"` (for running seed script, tests, and dev tools locally)
- [k6](https://grafana.com/docs/k6/) (for load testing, install via `brew install k6`)

## Quick Start

```bash
make up          # Start OpenSearch, PostgreSQL, Redis, and FastAPI
make seed        # Run migrations + load 10K indicators from seed data
```

Visit http://localhost:8000/docs for the interactive API docs

## API Endpoints

| Method | Path | Description | Data Source |
|--------|------|-------------|-------------|
| GET | `/api/indicators/{id}` | Indicator details with related actors, campaigns, indicators | Redis -> OpenSearch |
| GET | `/api/indicators/search` | Multi-param paginated search (type, value, actor, campaign, dates) | OpenSearch |
| GET | `/api/campaigns/{id}/indicators` | Campaign timeline grouped by day/week | Redis -> PostgreSQL |
| GET | `/api/dashboard/summary` | Landing page stats (24h/7d/30d) | Redis (pre-computed) |
| GET | `/health` | Service connectivity check | All services |

## Rate Limiting

All endpoints (including `/health`) are rate-limited using a token bucket algorithm backed by Redis. Each client IP gets a bucket of tokens that refills over time.

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
