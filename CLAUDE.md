# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Threat Intelligence API — a FastAPI backend powering a real-time security dashboard. Security analysts use it to investigate malicious indicators (IPs, domains, URLs, file hashes), map threat actor relationships, and analyze historical campaign data.

See `docs/PRD.md` for full requirements.

## Architecture

CQRS with polyglot persistence:

- **API layer:** Python/FastAPI with Pydantic validation, containerized with Docker
- **Hot tier (real-time):** OpenSearch for fast indicator lookups and search (endpoints 1 & 2)
- **Historical tier (OLAP):** PostgreSQL locally (Redshift in production) for campaign timelines and dashboard analytics (endpoints 3 & 4)
- **Cache:** Redis (cache-aside for indicator details, pre-computed analytical views)
- **ORM:** SQLAlchemy 2.0 async with asyncpg driver
- **Migrations:** Alembic (autogenerate from SQLAlchemy models in `src/app/db.py`)

### Local Development Stack

- Docker Compose orchestrates FastAPI + OpenSearch + PostgreSQL + Redis
- PostgreSQL substitutes for Redshift locally (standard SQL only, no Redshift-specific features)
- Read/write DSN separation: `POSTGRES_READ_DSN` points to read replica (Redshift in production, same PG locally)
- SQLAlchemy models in `src/app/db.py` are the source of truth for the database schema
- Alembic migrations in `alembic/versions/` are auto-generated from the SQLAlchemy models
- Seed data: `data/threat_intel.db` (SQLite, gitignored) — 10K indicators, 50 threat actors, 100 campaigns with relationships

### AWS Service Mapping (production)

| AWS Service | Local Equivalent | Purpose |
|---|---|---|
| AWS Redshift | PostgreSQL 16 container | Historical tier (OLAP queries) |
| AWS ElastiCache | Redis 7 container | Cache layer + pre-computed views |
| AWS OpenSearch Service | OpenSearch 2 container | Hot tier search |
| AWS Kinesis / Firehose | Not yet implemented | Future: ingestion pipeline |

### Commands

| Command | Description |
|---|---|
| `make up` | Start all services (Docker Compose) |
| `make down` | Stop and remove all services + volumes |
| `make seed` | Run migrations + load seed data into OpenSearch + PostgreSQL |
| `make migrate` | Run Alembic migrations to head |
| `make revision msg="description"` | Generate a new Alembic migration |
| `make test` | Run unit tests |
| `make test-integration` | Run integration tests (requires `make up && make seed`) |
| `make lint` | Run ruff linter |
| `make format` | Run ruff formatter + auto-fix lint issues |
| `make typecheck` | Run mypy in strict mode |
| `make check` | Run lint + typecheck + tests |
| `make logs` | Tail FastAPI container logs |

## Core API Endpoints

| Endpoint | Purpose | Data Source |
|---|---|---|
| `GET /api/indicators/{id}` | Indicator details + related actors/campaigns/indicators | Redis -> OpenSearch |
| `GET /api/indicators/search` | Multi-param paginated search | OpenSearch |
| `GET /api/campaigns/{id}/indicators` | Campaign timeline (time-series) | Redis <- PostgreSQL |
| `GET /api/dashboard/summary` | Landing page stats (24h/7d/30d) | Redis <- PostgreSQL |
| `GET /health` | Service connectivity check | OpenSearch + PostgreSQL + Redis |

## Database

### Schema

SQLAlchemy models in `src/app/db.py` define 7 tables. Key entities and relationships:

- `indicators` <-> `campaigns` via `campaign_indicators` (many-to-many)
- `threat_actors` <-> `campaigns` via `actor_campaigns` (many-to-many)
- `indicators` <-> `indicators` via `indicator_relationships` (self-referential, typed: same_campaign/same_infrastructure/co_occurring)
- `observations` tracks when/where indicators were seen

Indicator types: `ip`, `domain`, `url`, `hash`. Confidence scores are 0-100 integers throughout.

### Migrations

To modify the schema:
1. Edit the SQLAlchemy models in `src/app/db.py`
2. Run `make revision msg="describe your change"`
3. Review the generated migration in `alembic/versions/`
4. Run `make migrate` to apply

## Code Quality

- **Linter/formatter:** ruff (replaces black, isort, flake8)
- **Type checker:** mypy in strict mode with pydantic plugin
- **Tests:** pytest + httpx (async), pytest-asyncio
- Run `make check` before committing (lint + typecheck + tests)

## Performance Requirements

- Real-time endpoints (1 & 2): < 100ms at p95
- Analytical endpoints (3 & 4): < 250ms via Redis pre-computation
- Must handle 100M+ indicators and concurrent dashboard sessions
