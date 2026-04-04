# Threat Intelligence API

A high-performance FastAPI backend for a real-time security dashboard. Enables security analysts to investigate malicious indicators (IPs, domains, URLs, file hashes), map threat actor relationships, and analyze historical campaign data.

## Architecture

CQRS with polyglot persistence: OpenSearch for real-time indicator lookups, PostgreSQL for campaign analytics, Redis for caching and pre-computed views.

```
                    ┌───────────────────────────┐
                    │      FastAPI App          │
                    │    (Docker container)     │
                    │                           │
                    │  Routers -> Services      │
                    │  Middleware (correlation  │
                    │  IDs, structured logging) │
                    └────────────┬──────────────┘
                                 │
              ┌──────────────────┼─────────────────┐
              │                  │                 │
        ┌─────▼───────┐   ┌──────▼──────┐   ┌──────▼──────┐
        │ OpenSearch  │   │   Redis     │   │ PostgreSQL  │
        │ (Hot Tier)  │   │  (Cache)    │   │(Cold/OLAP)  │
        │             │   │             │   │             │
        │ Denormalized│   │ Cache-aside │   │ SQLAlchemy  │
        │ indicators  │   │ + pre-comp. │   │ + Alembic   │
        └─────────────┘   └─────────────┘   └─────────────┘

        Endpoints 1&2        All endpoints     Endpoints 3&4
```

## Prerequisites

- Docker and Docker Compose
- Python 3.12+
- `pip install ".[dev]"` (for running seed script, tests, and dev tools locally)

## Quick Start

```bash
make up          # Start OpenSearch, PostgreSQL, Redis, and FastAPI
make seed        # Run migrations + load 10K indicators from seed data
# Visit http://localhost:8000/docs for the interactive API docs
```

## API Endpoints

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
curl "http://localhost:8000/api/indicators/search?type=domain&threat_actor=APT-North&page=1&limit=20"

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
| `make test` | Run unit tests (20 tests) |
| `make test-integration` | Run integration tests (requires running services + seed data) |
| `make lint` | Run ruff linter |
| `make format` | Run ruff formatter + auto-fix lint issues |
| `make typecheck` | Run mypy in strict mode |
| `make check` | Run lint + typecheck + tests |
| `make logs` | Tail FastAPI application logs |

## Project Structure

```
src/
  app/
    main.py            # FastAPI app, lifespan, middleware
    config.py          # pydantic-settings configuration
    db.py              # SQLAlchemy models (source of truth for DB schema)
    middleware.py       # Correlation ID + request logging
    models/            # Pydantic request/response schemas
    routers/           # API route handlers
    services/          # OpenSearch, PostgreSQL, Redis, cache clients
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
    test_integration.py# Integration tests (real Docker services)
scripts/
  seed.py              # ETL: runs migrations, then SQLite -> OpenSearch + PostgreSQL
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
