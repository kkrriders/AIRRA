# AIRRA — Autonomous Incident Response & Reliability Agent

> AI-powered incident management platform that detects anomalies, generates root-cause hypotheses, recommends remediation actions, and coordinates on-call engineers — all with a human-in-the-loop approval gate.

![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.3+-37814A)
![Groq](https://img.shields.io/badge/LLM-Groq%20Free%20Tier-F55036)

---

## What It Does

Traditional incident response suffers from alert fatigue, slow manual triage, and inconsistent responses. AIRRA replaces that with a three-stage AI pipeline:

```
  PERCEIVE                  REASON                      ACT
  ────────                  ──────                      ───
  Prometheus metrics   →    LLM generates ranked   →    Risk-scored actions
  Z-score anomaly det.      hypotheses + evidence        Human approval gate
  Multi-signal correlation  Chain-of-thought SRE         Dry-run / Live exec
```

---

## Architecture

```
┌──────────────┐     HTTP      ┌─────────────────────────────────────────────┐
│  Next.js 14  │ ────────────▶ │              FastAPI Backend                │
│  :3000       │ ◀──────────── │                                             │
└──────────────┘     JSON      │  /api/v1/incidents    /api/v1/on-call       │
                               │  /api/v1/approvals    /api/v1/analytics     │
                               │  /api/v1/admin/engineers                    │
                               │  /metrics  /demo/metrics  (Prometheus)      │
                               └──────────────┬──────────────────────────────┘
                                              │
                           ┌──────────────────┼──────────────────┐
                           │                  │                  │
                  ┌────────▼────────┐  ┌──────▼──────┐  ┌───────▼──────┐
                  │   PostgreSQL    │  │    Redis    │  │  Prometheus  │
                  │  incidents      │  │  Celery     │  │  scrapes     │
                  │  engineers      │  │  LLM cache  │  │  /metrics    │
                  │  patterns       │  │  rate limit │  │  /demo/metr. │
                  └─────────────────┘  └──────┬──────┘  └──────────────┘
                                              │
                              ┌───────────────▼──────────────┐
                              │     Celery Worker + Beat     │
                              │                              │
                              │  run_anomaly_check  (60 s)   │
                              │  run_ai_generator   (30 min) │
                              │  analyze_incident   (demand) │
                              └──────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **API** | FastAPI (Python 3.11), fully async |
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS, React Query |
| **Database** | PostgreSQL 16 + SQLAlchemy 2 async ORM + Alembic |
| **Cache / Broker** | Redis 7 — Celery tasks, LLM response cache, rate limiter |
| **Task queue** | Celery 5.3 + Celery Beat (scheduled anomaly checks + AI gen) |
| **LLM** | Groq API — `llama-3.3-70b-versatile` (analysis) + `llama-3.1-8b-instant` (generation) |
| **Monitoring** | Prometheus — scrapes AIRRA metrics + synthetic demo-service Gauges |
| **Anomaly detection** | Z-score on 5 Golden Signal metrics; threshold configurable (default 3σ) |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A **free** [Groq API key](https://console.groq.com) — no credit card required

### 1. Configure environment

```bash
# Create a .env file at the project root (or export these variables)
AIRRA_API_KEY=dev-test-key-12345
AIRRA_OPENAI_API_KEY=gsk_your_groq_key_here
```

### 2. Start all services

```bash
docker compose up -d
```

Seven containers start in dependency order:

```
postgres ──┐
redis ──────┼──▶ db-migrate ──▶ backend ──┐
            │                  celery-worker ├──▶ frontend
prometheus ─┘                  celery-beat ─┘
```

### 3. Open the app

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Prometheus UI | http://localhost:9090 |

On first startup AIRRA automatically runs migrations, seeds 4 test engineers with on-call schedules for this week, and creates 3–5 static demo incidents.

---

## Pages

| Page | Path | Description |
|---|---|---|
| Dashboard | `/` | Live incident stats, active alerts, system health |
| Incidents | `/incidents` | Full list with status/severity/service filters |
| Incident Detail | `/incidents/[id]` | Hypotheses, actions, timeline, approval workflow |
| Approvals | `/approvals` | Actions waiting for human sign-off |
| On-Call | `/on-call` | Who is on-call now, grouped by service |
| Engineers | `/engineers` | Team roster, capacity bars, create new engineers |
| Notifications | `/notifications` | Alert delivery history, SLA tracking |
| Analytics | `/analytics` | MTTR, resolution rates, pattern learning |

---

## Incident Sources

AIRRA has three parallel incident sources so there is always something to show:

### Static Scenarios (startup, dev mode)

Five predefined scenarios run at startup if fewer than 3 active incidents exist. They rotate hourly so each restart brings a different starting set.

```
memory_leak_gradual  |  cpu_spike_traffic_surge  |  latency_spike_database
pod_crash_loop  |  dependency_failure_timeout
```

### AI Generator (every 30 min via Celery Beat)

`llama-3.1-8b-instant` (Groq free tier) generates unique incident text for a randomly chosen service + failure pattern. Produces ~48 incidents/day — well within the 14,400 req/day free limit.

### Prometheus Anomaly Detector (every 60 s via Celery Beat)

The backend exposes `/demo/metrics` — synthetic Prometheus Gauges for 5 services. Each service spikes one metric for 45 s every 10 minutes at a different offset:

| Service | Metric | Spike magnitude | Fires at |
|---|---|---|---|
| payment-service | error_rate | 18× baseline | t % 600 ∈ [0, 45s) |
| order-service | latency_p95 | 15× baseline | t % 600 ∈ [120, 165s) |
| user-service | cpu_usage | 4× baseline | t % 600 ∈ [240, 285s) |
| inventory-service | memory_bytes | 3.5× baseline | t % 600 ∈ [360, 405s) |
| notification-service | request_rate | 12× baseline | t % 600 ∈ [480, 525s) |

The Celery worker fetches 5-minute range data from Prometheus every 60 s, runs z-score analysis (baseline = last 19 points, current = point 20), and creates a `detection_source="airra_monitor"` incident when σ > 3 and confidence ≥ 0.75.

---

## Incident Lifecycle

```
DETECTED ──▶ ANALYZING ──▶ PENDING_APPROVAL ──▶ APPROVED ──▶ EXECUTING ──▶ RESOLVED
                                    │
                        (unaddressed > 120 min)
                                    │
                                    ▼
                               ESCALATED
```

Incidents are **never auto-approved**. A human must sign off on each remediation action. Actions execute in `dry_run` mode by default.

---

## On-Call Management

### Register an engineer (API or Engineers page)

```bash
curl -X POST http://localhost:8000/api/v1/admin/engineers/ \
  -H "X-API-Key: dev-test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Alice Chen",
    "email": "alice@example.com",
    "department": "Platform Engineering",
    "expertise": ["kubernetes", "aws", "prometheus"],
    "max_concurrent_reviews": 3
  }'
```

### Assign an on-call shift

```bash
curl -X POST http://localhost:8000/api/v1/on-call/ \
  -H "X-API-Key: dev-test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{
    "engineer_id": "<UUID from above>",
    "service": "payment-service",
    "start_time": "2026-02-27T09:00:00Z",
    "end_time": "2026-02-28T09:00:00Z",
    "priority": "primary",
    "schedule_name": "Week 1 Rotation"
  }'
```

Priority levels: `primary` → `secondary` → `tertiary`. Set `service: null` for all-services coverage. The finder service (`/on-call/find-current`) automatically walks the escalation chain if the primary is unavailable.

---

## LLM Configuration

Two models serve different tasks to balance quality and cost:

| Task | Model | Reason |
|---|---|---|
| AI incident generation | `llama-3.1-8b-instant` | Fast creative text, Groq free tier |
| Hypothesis analysis | `llama-3.3-70b-versatile` | Deep reasoning over metric data |

Both run on **Groq's free tier** at $0.00/day with the right key from [console.groq.com](https://console.groq.com).

LLM responses are cached in Redis for 24 hours (SHA-256 key on prompt + model + temperature) to avoid redundant API calls.

---

## Configuration Reference

All settings use the `AIRRA_` env prefix. Defaults shown below.

| Variable | Default | Description |
|---|---|---|
| `AIRRA_API_KEY` | *(required)* | Auth key for all API endpoints |
| `AIRRA_OPENAI_API_KEY` | *(required)* | Groq API key (`gsk_...`) |
| `AIRRA_LLM_PROVIDER` | `groq` | LLM provider (`groq`, `anthropic`, `openai`, `openrouter`) |
| `AIRRA_LLM_MODEL` | `llama-3.3-70b-versatile` | Model for reasoning / analysis |
| `AIRRA_LLM_GENERATOR_MODEL` | `llama-3.1-8b-instant` | Model for AI incident generation |
| `AIRRA_ENVIRONMENT` | `development` | `development` or `production` |
| `AIRRA_DATABASE_URL` | `postgresql+asyncpg://airra:airra@postgres:5432/airra` | PostgreSQL DSN |
| `AIRRA_REDIS_URL` | `redis://redis:6379/0` | Redis DSN |
| `AIRRA_PROMETHEUS_URL` | `http://prometheus:9090` | Prometheus server |
| `AIRRA_ANOMALY_THRESHOLD_SIGMA` | `3.0` | Z-score threshold for anomaly detection |
| `AIRRA_MONITORED_SERVICES` | *(5 demo services)* | JSON array of service names to monitor |
| `AIRRA_DEBUG` | `false` | Enables `/docs` Swagger UI |
| `AIRRA_LOG_LEVEL` | `INFO` | Log level |

---

## Common Commands

```bash
# Start everything
docker compose up -d

# Rebuild after code changes
docker compose up -d --build backend celery-worker celery-beat

# Live logs
docker compose logs -f backend
docker compose logs -f celery-worker

# Run database migration manually
docker compose run --rm db-migrate alembic upgrade head

# Reset all data (WARNING: destructive)
docker compose down -v && docker compose up -d

# Check Celery is alive
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect ping

# Query Prometheus demo metrics
curl 'http://localhost:9090/api/v1/query?query=airra_demo_error_rate'

# Tail only anomaly-related logs
docker compose logs -f celery-worker | grep -E "anomaly|incident|spike"
```

---

## API Quick Reference

All endpoints require `X-API-Key: <key>` except `/health`, `/metrics`, and `/demo/metrics`.

```
# Core
GET  /health
GET  /metrics                            Prometheus scrape (AIRRA HTTP metrics)
GET  /demo/metrics                       Prometheus scrape (demo service Gauges)

# Incidents
GET  /api/v1/incidents/
POST /api/v1/incidents/
GET  /api/v1/incidents/{id}
POST /api/v1/incidents/{id}/analyze      → 202 Accepted, triggers Celery task

# Approvals
GET  /api/v1/approvals/pending
POST /api/v1/approvals/{action_id}/approve
POST /api/v1/approvals/{action_id}/reject

# On-Call
POST /api/v1/on-call/                    Create schedule
POST /api/v1/on-call/find-current        Who is on-call now for a service
POST /api/v1/on-call/escalation-chain    Full escalation chain
GET  /api/v1/on-call/current/all         Everyone on-call across all services

# Engineers
GET  /api/v1/admin/engineers/
POST /api/v1/admin/engineers/
GET  /api/v1/admin/engineers/{id}
GET  /api/v1/admin/engineers/available/list

# Analytics
GET  /api/v1/analytics/insights?days=30
GET  /api/v1/analytics/mttr
```

Full interactive docs: http://localhost:8000/docs (requires `AIRRA_DEBUG=true`)

---

## Project Structure

```
airra/
├── backend/
│   ├── app/
│   │   ├── api/v1/              # FastAPI routers (incidents, on-call, engineers, …)
│   │   ├── core/
│   │   │   ├── perception/      # Anomaly detection, signal correlator
│   │   │   ├── reasoning/       # Hypothesis generator, LLM prompting
│   │   │   ├── decision/        # Blast radius, action selection
│   │   │   ├── execution/       # Action executors (Kubernetes, scaling)
│   │   │   └── simulation/      # Static scenario runner + LLM scenario gen
│   │   ├── models/              # SQLAlchemy ORM (incident, engineer, on_call_schedule, …)
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   ├── services/            # External clients (Prometheus, Groq, Loki, on_call_finder)
│   │   ├── worker/
│   │   │   ├── celery_app.py    # Celery + Beat configuration
│   │   │   └── tasks/           # analysis.py, monitoring.py
│   │   └── main.py              # App factory, lifespan, router registration
│   ├── alembic/                 # Database migrations
│   └── Dockerfile
├── frontend/
│   └── src/app/                 # Next.js App Router pages
│       ├── page.tsx             # Dashboard
│       ├── incidents/           # List + detail
│       ├── approvals/
│       ├── on-call/
│       ├── engineers/           # New: team management
│       ├── notifications/
│       └── analytics/
├── monitoring/
│   └── prometheus/prometheus.yml
├── docker-compose.yml
├── SETUP.md                     # Detailed setup and troubleshooting
└── README.md
```

---

## Troubleshooting

**No incidents appear after startup**
```bash
docker compose logs backend | grep -E "demo incident|scenario|Seeded"
docker compose logs celery-worker | grep "AI incident\|generator"
docker compose exec backend env | grep OPENAI_API_KEY   # verify Groq key is set
```

**Analysis stays stuck in ANALYZING**
```bash
# Check the Celery task was received
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect reserved

# Check for LLM errors
docker compose logs celery-worker | grep -E "LLM|groq|generate|error"
```

**Prometheus targets show DOWN**
```bash
# Check target health in Prometheus UI
open http://localhost:9090/targets

# Test demo metrics endpoint
curl http://localhost:8000/demo/metrics
```

**Migration failed (DuplicateTableError)**
```bash
# Migrations are idempotent — safe to re-run
docker compose run --rm db-migrate alembic upgrade head
```

**Port conflicts**
```bash
# Change host ports in docker-compose.yml, e.g. "8001:8000" for backend
```

---

## License

MIT — academic / personal project.
