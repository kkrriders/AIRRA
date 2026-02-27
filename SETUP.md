# AIRRA Setup Guide

Detailed setup and troubleshooting for AIRRA — Autonomous Incident Response & Reliability Agent.

---

## Prerequisites

- **Docker** and **Docker Compose** (Docker Desktop on macOS/Windows)
- A **free Groq API key** — get one at [console.groq.com](https://console.groq.com) (no credit card required)
- Ports **3000**, **5432**, **6379**, **8000**, **9090** free on your host

---

## Step 1 — Configure Environment Variables

Create a `.env` file at the **project root** (same directory as `docker-compose.yml`):

```bash
# Required: Groq API key (starts with gsk_)
AIRRA_OPENAI_API_KEY=gsk_your_groq_key_here

# Optional: change the API auth key (default works fine for local dev)
AIRRA_API_KEY=dev-test-key-12345
```

> **Why `AIRRA_OPENAI_API_KEY` for Groq?**
> The backend uses the OpenAI Python SDK with Groq's drop-in compatible endpoint.
> The env var name is kept for SDK compatibility; the value is your Groq key.

---

## Step 2 — Start All Services

```bash
docker compose up -d
```

This starts 7 containers in dependency order:

```
postgres ──┐
redis ──────┼──▶ db-migrate ──▶ backend ──┐
            │                  celery-worker ├──▶ frontend
prometheus ─┘                  celery-beat ─┘
```

On first startup, the backend automatically:
1. Runs Alembic database migrations
2. Seeds 4 test engineers with on-call schedules for the current week
3. Creates 3–5 static demo incidents (rotates hourly)

---

## Step 3 — Verify Everything Is Running

```bash
docker compose ps
```

Expected output (all services should show `Up` or `Up (healthy)`):

```
NAME                   STATUS
airra-postgres         Up (healthy)
airra-redis            Up (healthy)
airra-prometheus       Up (healthy)
airra-db-migrate       Exited (0)   ← one-shot, exits after migration
airra-backend          Up
airra-celery-worker    Up (healthy)
airra-celery-beat      Up (healthy)
airra-frontend         Up
```

Then open:

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Prometheus UI | http://localhost:9090 |

---

## Service Details

### Backend (FastAPI)

- Runs on port **8000** with hot-reload (`uvicorn --reload`)
- All API endpoints require `X-API-Key: dev-test-key-12345` (except `/health`, `/metrics`, `/demo/metrics`)
- Exposes two Prometheus scrape targets:
  - `/metrics` — AIRRA's own HTTP metrics (via `prometheus-fastapi-instrumentator`)
  - `/demo/metrics` — Synthetic Gauge data for 5 demo services (scraped every 15s)

### Celery Worker

- Processes two queues: `celery` (monitoring one-shots) and `analysis` (LLM tasks)
- Concurrency: 4 (configurable via `AIRRA_WORKER_CONCURRENCY`)
- Handles `analyze_incident` tasks triggered by `POST /api/v1/incidents/{id}/analyze`

### Celery Beat

- Scheduled tasks (stored in Redis via `redbeat.RedBeatScheduler`):
  - **Anomaly check** — every 60 seconds (fetches Prometheus, runs z-score, creates incidents)
  - **AI incident generator** — every 30 minutes (Groq `llama-3.1-8b-instant`)
- **NEVER scale past 1 replica** — duplicate Beat instances produce duplicate tasks

### Prometheus

- Scrapes three targets:
  1. `backend:8000/metrics` — FastAPI HTTP metrics
  2. `backend:8000/demo/metrics` — synthetic demo service Gauges
  3. Itself (default self-scrape)

---

## LLM Configuration

AIRRA uses Groq's free tier with two models for different cost/quality trade-offs:

| Task | Model | Approx. rate |
|---|---|---|
| AI incident generation | `llama-3.1-8b-instant` | ~48 incidents/day |
| Hypothesis analysis | `llama-3.3-70b-versatile` | On-demand per incident |

Both are on Groq's **free tier** ($0.00/day) at normal usage.

LLM responses are **cached in Redis** for 24 hours to avoid redundant API calls.

---

## Testing the System

### Verify incidents appear

```bash
curl -s http://localhost:8000/api/v1/incidents/?page=1 \
  -H "X-API-Key: dev-test-key-12345" | python3 -m json.tool | head -30
```

### Trigger incident analysis manually

```bash
# Get an incident ID first
INCIDENT_ID=$(curl -s http://localhost:8000/api/v1/incidents/?page=1 \
  -H "X-API-Key: dev-test-key-12345" | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")

# Trigger async analysis (returns 202 Accepted)
curl -X POST "http://localhost:8000/api/v1/incidents/$INCIDENT_ID/analyze" \
  -H "X-API-Key: dev-test-key-12345"

# Poll for completion (ANALYZING → PENDING_APPROVAL)
curl "http://localhost:8000/api/v1/incidents/$INCIDENT_ID" \
  -H "X-API-Key: dev-test-key-12345" | python3 -m json.tool | grep status
```

### Approve a remediation action

```bash
# List pending approvals
curl http://localhost:8000/api/v1/approvals/pending \
  -H "X-API-Key: dev-test-key-12345"

# Approve (replace ACTION_ID)
curl -X POST "http://localhost:8000/api/v1/approvals/ACTION_ID/approve" \
  -H "X-API-Key: dev-test-key-12345" \
  -H "Content-Type: application/json" \
  -d '{"approved_by": "you@example.com", "execution_mode": "dry_run"}'
```

### Check Celery workers

```bash
# Verify worker is alive
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect ping

# See active tasks
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect active
```

### Verify Prometheus scraping

```bash
# Check demo metrics are being generated
curl http://localhost:8000/demo/metrics | head -20

# Query Prometheus for a demo metric
curl 'http://localhost:9090/api/v1/query?query=airra_demo_error_rate'
```

---

## Common Commands

```bash
# Start everything
docker compose up -d

# Rebuild after code changes (backend/Celery)
docker compose up -d --build backend celery-worker celery-beat

# Live logs
docker compose logs -f backend
docker compose logs -f celery-worker

# Tail anomaly-detection logs only
docker compose logs -f celery-worker | grep -E "anomaly|incident|spike"

# Run database migration manually
docker compose run --rm db-migrate alembic upgrade head

# Open a Python shell in the backend container
docker compose exec backend python -c "from app.config import settings; print(settings.llm_model)"

# Reset all data (WARNING: destructive — drops all DB volumes)
docker compose down -v && docker compose up -d
```

---

## Local Development (without Docker)

If you want to run the backend outside Docker for faster iteration:

### 1. Install dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Start infrastructure services only

```bash
# From project root
docker compose up -d postgres redis prometheus
```

### 3. Set environment variables

```bash
export AIRRA_DATABASE_URL=postgresql+asyncpg://airra:airra@localhost:5432/airra
export AIRRA_REDIS_URL=redis://localhost:6379/0
export AIRRA_PROMETHEUS_URL=http://localhost:9090
export AIRRA_OPENAI_API_KEY=gsk_your_groq_key
export AIRRA_API_KEY=dev-test-key-12345
```

### 4. Run migrations and start backend

```bash
cd backend
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Start Celery (in separate terminals)

```bash
# Worker
celery -A app.worker.celery_app worker --loglevel=info -Q celery,analysis

# Beat scheduler
celery -A app.worker.celery_app beat --loglevel=info
```

---

## Troubleshooting

### No incidents appear after startup

```bash
docker compose logs backend | grep -E "demo incident|scenario|Seeded|engineer"
docker compose logs celery-worker | grep "AI incident\|generator"
docker compose exec backend env | grep OPENAI_API_KEY   # verify Groq key is set
```

### Analysis stays stuck in ANALYZING

```bash
# Check the Celery task was received
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect reserved

# Check for LLM errors
docker compose logs celery-worker | grep -E "LLM|groq|generate|error"
```

### Prometheus anomaly detection not creating incidents

```bash
# 1. Confirm demo metrics endpoint is alive
curl http://localhost:8000/demo/metrics | grep "airra_demo"

# 2. Check Prometheus is scraping it (look for airra-demo-services target)
open http://localhost:9090/targets

# 3. Tail celery-worker for anomaly check output
docker compose logs -f celery-worker | grep -E "sigma|anomaly|z_score"
```

### Celery Beat not scheduling tasks

```bash
# Check Beat is running
docker compose ps celery-beat

# Check Redis connectivity
docker compose exec celery-beat redis-cli -u redis://redis:6379/0 ping

# Restart Beat (safe — RedBeat state persists in Redis)
docker compose restart celery-beat
```

### Migration failed (DuplicateTableError or similar)

```bash
# Migrations are idempotent — safe to re-run
docker compose run --rm db-migrate alembic upgrade head
```

### Port conflicts

```bash
# Change host ports in docker-compose.yml
# Example: use 8001 for backend
# ports:
#   - "8001:8000"
```

### Groq API key errors

```bash
# Verify the key starts with gsk_
docker compose exec backend env | grep OPENAI_API_KEY

# Test the key directly
curl https://api.groq.com/openai/v1/models \
  -H "Authorization: Bearer gsk_your_key_here"
```

---

## Monitoring

### Prometheus queries

```promql
-- AIRRA HTTP request rate
rate(http_requests_total[1m])

-- Demo service error rates (anomaly targets)
airra_demo_error_rate

-- Demo service latency
airra_demo_latency_p95{service="payment-service"}
```

### Database inspection

```bash
docker compose exec postgres psql -U airra -d airra

-- Useful queries:
\dt                                    -- list tables
SELECT id, title, status, severity FROM incidents ORDER BY detected_at DESC LIMIT 10;
SELECT name, department FROM engineers;
SELECT engineer_id, service, priority FROM on_call_schedules WHERE is_active = true;
SELECT pattern_id, frequency FROM incident_patterns ORDER BY frequency DESC;
```

---

## Configuration Reference

All settings use the `AIRRA_` prefix. Set in the `.env` file at project root.

| Variable | Default | Description |
|---|---|---|
| `AIRRA_API_KEY` | `dev-test-key-12345` | Auth key for all API endpoints |
| `AIRRA_OPENAI_API_KEY` | *(required)* | Groq API key (`gsk_...`) |
| `AIRRA_LLM_PROVIDER` | `groq` | LLM provider |
| `AIRRA_LLM_MODEL` | `llama-3.3-70b-versatile` | Model for reasoning / analysis |
| `AIRRA_LLM_GENERATOR_MODEL` | `llama-3.1-8b-instant` | Model for AI incident generation |
| `AIRRA_ENVIRONMENT` | `development` | `development` or `production` |
| `AIRRA_DEBUG` | `false` | Enables `/docs` Swagger UI |
| `AIRRA_LOG_LEVEL` | `INFO` | Log verbosity |
| `AIRRA_DATABASE_URL` | `postgresql+asyncpg://airra:airra@postgres:5432/airra` | PostgreSQL DSN |
| `AIRRA_REDIS_URL` | `redis://redis:6379/0` | Redis DSN |
| `AIRRA_PROMETHEUS_URL` | `http://prometheus:9090` | Prometheus server URL |
| `AIRRA_ANOMALY_THRESHOLD_SIGMA` | `3.0` | Z-score threshold (default: 3σ) |
| `AIRRA_DRY_RUN_MODE` | `true` | Simulate actions without executing |
