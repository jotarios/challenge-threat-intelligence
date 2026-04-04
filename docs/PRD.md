# Product Requirements Document (PRD): Threat Intelligence API

## 1. Project Overview
The Threat Intelligence API is a high-performance backend system designed to power a real-time security dashboard. It enables Security Analysts to rapidly investigate malicious indicators (IPs, domains, file hashes), map relationships to threat actors, and analyze historical campaign data to identify trends.

## 2. Goals & Objectives
* **Sub-millisecond Latency:** Provide near-instantaneous retrieval of threat indicator details and search results to support active threat hunting.
* **Deep Analytics:** Support heavy analytical queries over historical data without impacting the performance of real-time operational endpoints.
* **Scalability:** Handle high-throughput ingestion of real-time threat feeds (100M+ indicators) and concurrent analyst dashboard sessions.
* **High Availability:** Ensure zero-downtime deployments and regional fault tolerance.

## 3. Target Audience
* **Tier 1 & Tier 2 Security Analysts:** Need fast, reliable data retrieval to triage active alerts.
* **Threat Intelligence Researchers:** Need historical campaign timelines and aggregate data to model long-term threat actor behavior.

---

## 4. Product Scope & API Specifications

The system exposes 4 core RESTful endpoints. All responses are formatted as standard JSON.

### 4.1. Get Indicator Details (`GET /api/indicators/{id}`)
* **Purpose:** Retrieve complete context for a specific indicator.
* **Data Source:** API Cache (Redis) -> Hot Tier (OpenSearch).
* **Response Payload:**
  * Base details (type, value, confidence score).
  * Associated Threat Actors (with confidence levels).
  * Associated Campaigns (active status).
  * Timestamps (first_seen, last_seen).
  * Related indicators (limit 5).
* Example:
{ "id": "550e8400-e29b-41d4-a716-446655440000", "type": "ip", "value": "192.168.1.100", "confidence": 85, "first_seen": "2024-11-15T10:30:00Z", "last_seen": "2024-12-20T14:22:00Z", "threat_actors": [ { "id": "actor-123", "name": "APT-North", "confidence": 90 } ], "campaigns": [ { "id": "camp-456", "name": "Operation ShadowNet", "active": true } ], "related_indicators": [ { "id": "uuid", "type": "domain", "value": "malicious.example.com", "relationship": "same_campaign" } ] }

### 4.2. Search & Filter Indicators (`GET /api/indicators/search`)
* **Purpose:** Multi-parameter search capability across the active threat landscape.
* **Data Source:** Hot Tier (OpenSearch).
* **Query Parameters:** `type`, `value` (partial match), `threat_actor`, `campaign`, `first_seen_after`, `last_seen_before`, `page`, `limit`.
* **Response Payload:** Paginated array of matching indicators with total counts and pagination metadata.
* Example:
{ "data": [ { "id": "uuid", "type": "domain", "value": "phishing.example.com", "confidence": 75, "first_seen": "2024-10-01T08:00:00Z", "campaign_count": 2, "threat_actor_count": 1 } ], "total": 156, "page": 1, "limit": 20, "total_pages": 8 }

### 4.3. Campaign Timeline (`GET /api/campaigns/{id}/indicators`)
* **Purpose:** Retrieve time-series data for front-end timeline visualization.
* **Data Source:** Pre-computed API Cache (Redis) <- Historical Tier (AWS Redshift).
* **Query Parameters:** `group_by` (day/week), `start_date`, `end_date`.
* **Response Payload:** Campaign metadata, indicators grouped by the requested time period, and overall duration statistics.
* Example:
{ "campaign": { "id": "camp-456", "name": "Operation ShadowNet", "description": "Targeted phishing campaign", "first_seen": "2024-10-01T00:00:00Z", "last_seen": "2024-12-15T00:00:00Z", "status": "active" }, "timeline": [ { "period": "2024-10-01", "indicators": [ { "id": "uuid", "type": "ip", "value": "10.0.0.1" } ], "counts": { "ip": 5, "domain": 3, "url": 12 } } ], "summary": { "total_indicators": 234, "unique_ips": 45, "unique_domains": 67, "duration_days": 75 } }

### 4.4. Dashboard Summary (`GET /api/dashboard/summary`)
* **Purpose:** Power the primary landing page with high-level statistics.
* **Data Source:** Pre-computed API Cache (Redis) <- Historical Tier (AWS Redshift).
* **Query Parameters:** `time_range` (24h, 7d, 30d). Default 7d.
* **Response Payload:** Counts of new indicators by type, active campaigns, top 5 threat actors, and indicator distribution.
* Example:
{ "time_range": "7d", "new_indicators": { "ip": 145, "domain": 89, "url": 234, "hash": 67 }, "active_campaigns": 12, "top_threat_actors": [ { "id": "actor-123", "name": "APT-North", "indicator_count": 456 } ], "indicator_distribution": { "ip": 3421, "domain": 2876, "url": 2134, "hash": 1569 } }

---

## 5. Architecture & Tech Stack

The system utilizes a Polyglot Persistence and CQRS (Command Query Responsibility Segregation) architecture.

### 5.1. Application Layer
* **Framework:** Python (FastAPI).
* **Validation:** Pydantic for robust request/response schema validation.
* **Containerization:** Docker.

### 5.2. Data & Storage Tiers
* **The "Hot" Tier (Real-Time):** AWS OpenSearch. Handles Endpoints 1 & 2 via inverted indices for blazing-fast text search and fuzzy matching.
* **The "Historical" Tier (OLAP):** AWS Redshift. Stores long-term data for Endpoints 3 & 4. Supports deep SQL joins and aggregations.
* **The Caching Layer:** AWS ElastiCache (Redis).
  * Caches highly requested indicator details (Cache-Aside pattern).
  * Stores pre-computed analytical views generated by background workers.

### 5.3. Ingestion Pipeline (Event-Driven)
* **Stream:** AWS Kinesis Data Streams ingests external threat feeds.
* **Hot Routing:** A background worker (ECS Task/Lambda) indexes Kinesis data into OpenSearch.
* **Cold Routing:** AWS Kinesis Firehose batches data into S3, triggering COPY commands into AWS Redshift.

### 5.4. Infrastructure & Deployment
* **Compute:** AWS ECS (Elastic Container Service) via AWS Fargate for serverless, auto-scaling container execution.
* **Load Balancing:** AWS Application Load Balancer (ALB).
* **CI/CD:** GitHub Actions. Utilizes AWS OIDC for secure authentication, executing automated tests, Docker builds, and zero-downtime rolling deployments to ECS.

---

## 6. Security & Authorization
* **Edge Security:** AWS WAF to mitigate DDoS and SQLi/XSS attacks.
* **API Gateway:** Enforces Rate Limiting (e.g., 100 req/min per user) and validates upstream authentication tokens.
* **Secrets Management:** No hardcoded credentials. FastAPI retrieves database URIs dynamically from AWS Secrets Manager using IAM task execution roles.

## 7. Local Development Environment
To maintain parity with production while keeping costs at zero, the local stack utilizes:
* **MiniStack:** Emulates Kinesis, Firehose, ElastiCache (Redis), and AWS RDS (PostgreSQL used to mock Redshift SQL dialect).
* **Docker Compose:** Orchestrates the FastAPI container alongside MiniStack and a local OpenSearch container.

## 8. Non-Functional Requirements (NFRs)
* **Performance:** Real-time endpoints (1 & 2) must return within `< 100ms` at the 95th percentile. Analytical endpoints (3 & 4) must return within `< 250ms` via Redis pre-computation.
* **Reliability:** 99.9% Uptime SLA. Multi-AZ deployment for ECS, Redis, and OpenSearch.
* **Observability:** Centralized logging via AWS CloudWatch. Distributed tracing (e.g., AWS X-Ray/Datadog) implemented across all FastAPI routes to monitor downstream database latencies.

---

## 9. Future Enhancements (Out of scope)
* **Real-time alerts:** Push real-time alerts to the dashboard when critical indicators are ingested.
* **Machine Learning Integration:** Apply anomaly detection models (e.g., Isolation Forests) over the Redshift data to flag automated, non-human threat campaign behaviors.

---

## Appendix A: Database Schema (`data/schema.sql`)

This SQL schema defines the structure for the historical/relational tier (PostgreSQL/Redshift). It establishes the core entities and uses optimized junction tables for the complex many-to-many relationships inherent in threat intelligence.

## Appendix B: Seed data (`data/threat_intel.db`)

SQLite Database (`threat_intel.db`) with pre-populated data:
- 10,000 threat indicators (IPs, domains, URLs, file hashes)
- 50 threat actors
- 100 campaigns
- Relationships between indicators, campaigns, and threat actors
- Observation timestamps (when indicators were seen)
