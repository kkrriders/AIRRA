# AIRRA — Autonomous Incident Response & Reliability Agent

> AI-powered incident management platform that detects anomalies, generates root-cause hypotheses via semantic RAG, recommends remediation actions, and learns from every resolution — all with a human-in-the-loop approval gate.

![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![Next.js](https://img.shields.io/badge/Next.js-14-black?logo=next.js)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+pgvector-336791?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-5.3+-37814A)
![Groq](https://img.shields.io/badge/LLM-Groq%20Free%20Tier-F55036)

---

## The Problem

Production incidents are expensive. The median time-to-detect is 60 minutes; median time-to-resolve is 4 hours. The bottleneck is rarely hardware — it's the cognitive load on the SRE: parse dashboards, correlate signals, form a hypothesis, find the right runbook, decide whether to act.

Three deeper problems make this worse:

1. **Third-party opacity.** When AWS RDS or Stripe degrades, Prometheus shows green on everything you own. The incident is real but your observability is blind to its actual cause.

2. **Fake blast radius.** Ten microservices appear independent on an architecture diagram, but if all ten share one PostgreSQL cluster, one identity provider, and one NAT gateway, the real blast radius is 1. Current tooling counts decorative doors, not burning rooms.

3. **Knowledge decay.** The engineer who solved last quarter's memory leak left the company. The postmortem lives in a Confluence page nobody reads. When the same pattern recurs, the team starts from zero.

**AIRRA** addresses all three: semantic incident retrieval surfaces past knowledge automatically, shared-dependency correlation is an explicit extension point, and the feedback loop re-embeds resolved incidents with their actual root cause so future retrievals get richer context.

---

## Architecture — 12-Stage Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          AIRRA Pipeline                                      │
│                                                                               │
│  [1] Prometheus ──► [2] AnomalyMonitor ──► [3] Severity + Blast Radius      │
│                              │                                                │
│                              ▼                                                │
│                     [4] IncidentSummarizer (structured text, no LLM)         │
│                              │                                                │
│                              ▼                                                │
│                    [5] PostgreSQL Knowledge Base                              │
│                              │                                                │
│                              ▼                                                │
│              [6] EmbeddingService (all-MiniLM-L6-v2, 384-dim)               │
│                              │                                                │
│                              ▼                                                │
│          [7] pgvector HNSW semantic search (cosine distance)                 │
│                              │                                                │
│                     ┌────────┴────────┐                                       │
│                     │                 │                                       │
│           composite ≥ 0.75      composite < 0.75                             │
│             [12] SKIP LLM ◄──────[8] RAG Reasoning (LLM)                   │
│          reuse past resolution         │                                       │
│                                        ▼                                      │
│                          [9] Hypothesis Ranking                               │
│                                        │                                      │
│                                        ▼                                      │
│                     [10] SRE Notification (email / Slack)                    │
│                                        │                                      │
│                              human approval required                          │
│                                        │                                      │
│                                        ▼                                      │
│                         [11] Feedback Loop: re-embed with                    │
│                              actual root cause + resolution                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Stage-by-Stage Status

| # | Stage | Implementation | Status |
|---|-------|---------------|--------|
| 1 | **Prometheus Monitoring** | `anomaly_monitor.py` polls `/api/v1/query_range` | ✅ |
| 2 | **Anomaly Detection** | 3σ Z-score per metric, configurable window | ✅ |
| 3 | **Severity + Blast Radius** | `blast_radius.py`, sigma-weighted scoring | ✅ |
| 4 | **Incident Summarization** | `IncidentSummarizer` — structured text from metrics_snapshot (no LLM) | ✅ |
| 5 | **Knowledge Base** | PostgreSQL: incidents, hypotheses, actions, postmortems, patterns | ✅ |
| 6 | **Embedding Generation** | `EmbeddingService` — `all-MiniLM-L6-v2`, thread-pool CPU inference | ✅ |
| 7 | **Semantic Retrieval** | pgvector HNSW, fetch top-10, re-rank by composite score, pass top-3 to LLM | ✅ |
| 8 | **RAG Reasoning** | Groq LLaMA-3.3-70b — prompt auto-includes service topology + postmortems | ✅ |
| 9 | **Hypothesis Ranking** | `confidence × pattern_adjustment`; topology-aware confidence boost | ✅ |
| 10 | **SRE Notification** | SMTP email + Slack Incoming Webhook (Block Kit); HMAC token 4hr expiry | ✅ |
| 11 | **Feedback Loop** | Re-embed resolved incidents with `actual_root_cause` + lessons (top of text) | ✅ |
| 12 | **Cost Optimization** | Multi-signal composite ≥ 0.75 → skip LLM, reuse past resolution | ✅ |

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **API** | FastAPI (Python 3.11), fully async | REST endpoints, request validation |
| **Frontend** | Next.js 14, TypeScript, Tailwind CSS | Dashboard, approval UI |
| **Database** | PostgreSQL 16 + pgvector | Relational store + 384-dim vector similarity |
| **Embeddings** | sentence-transformers `all-MiniLM-L6-v2` | 384-dim, CPU-only, MIT license |
| **LLM (reasoning)** | Groq LLaMA-3.3-70b-versatile | Hypothesis generation, RAG synthesis |
| **LLM (generation)** | Groq LLaMA-3.1-8b-instant | AI incident generation (free tier) |
| **Task Queue** | Celery 5.3 + Celery Beat | Async LLM calls, scheduling, embedding |
| **Cache / Broker** | Redis 7 | Rate limiting, LLM response cache, Celery broker |
| **Monitoring** | Prometheus + Grafana | System observability, AIRRA self-metrics |

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- A **free** [Groq API key](https://console.groq.com) — no credit card required

### 1. Configure environment

```bash
# Create a .env file at the project root
AIRRA_API_KEY=dev-test-key-12345
AIRRA_LLM_PROVIDER=groq
AIRRA_GROQ_API_KEY=gsk_your_groq_key_here

# Optional: Slack notifications
AIRRA_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

### 2. Start all services

```bash
docker compose up --build
```

Eight containers start in dependency order:

```
postgres ──┐
redis ──────┼──▶ db-migrate ──▶ backend ─────┐
            │                  celery-worker  ├──▶ frontend
prometheus ─┘                  celery-analysis├──▶ grafana
                               celery-beat ───┘
```

On first startup AIRRA automatically:
- Runs all 7 Alembic migrations (including pgvector extension + HNSW index)
- Seeds 4 test engineers with on-call schedules
- Creates 3–5 static demo incidents
- Warms the embedding model on the first incident

### 3. Open the app

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | API key from .env |
| API docs (Swagger) | http://localhost:8000/docs | — |
| Prometheus UI | http://localhost:9090 | — |
| Grafana | http://localhost:3001 | admin / admin |

---

## How an Incident Flows

```
1. Celery Beat runs anomaly_check every 60s
   └─ AnomalyMonitor queries Prometheus for each configured service
   └─ Z-score > 3σ → creates Incident (DETECTED)
   └─ Triggers embed_incident_task.delay(incident_id)

2. EmbeddingService (in Celery worker)
   └─ IncidentSummarizer builds structured text from metrics_snapshot
   └─ all-MiniLM-L6-v2 encodes → 384-dim vector
   └─ Stored in incidents.embedding (pgvector column)

3. Engineer or Celery triggers POST /incidents/{id}/analyze
   └─ Status: DETECTED → ANALYZING (immediate DB write, <50ms)
   └─ Returns 202 Accepted, enqueues analyze_incident task

4. Analysis task (Celery worker, analysis queue)
   └─ Embeds current incident
   └─ pgvector HNSW search: ORDER BY embedding <=> query LIMIT 10
   └─ Compute composite score for each candidate:
      └─ 0.5 × vector_similarity + 0.3 × service_match + 0.2 × metric_overlap
      └─ service_match: 1.0 (same), 0.5 (upstream/downstream), 0.0 (unrelated)
   └─ Re-rank by composite; take top-3 for LLM context
   └─ [Stage 12] If top composite ≥ AIRRA_SIMILARITY_SKIP_THRESHOLD (default 0.75):
      └─ Copy past resolution, set PENDING_APPROVAL, skip LLM
   └─ [Stage 8] Else: RAG prompt → service topology + top-3 postmortems → LLM
   └─ LLM returns structured JSON: hypotheses + recommended actions
   └─ Hypothesis confidence boosted by topology signals (DB upstream → +0.08, etc.)
   └─ Status: ANALYZING → PENDING_APPROVAL

5. Notification service
   └─ Email (SMTP) or Slack (Block Kit webhook) to assigned SRE
   └─ Acknowledgement token in email link (HMAC-signed, 4hr expiry)

6. SRE approves/rejects via frontend
   └─ APPROVED → EXECUTING → action runs (dry-run by default)
   └─ RESOLVED → learning_engine.capture_outcome()

7. Feedback loop (Stage 11)
   └─ Postmortem fetched for actual_root_cause + lessons_learned
   └─ embed_incident_task.delay(incident_id, extra_context={root_cause, resolution})
   └─ Richer embedding stored — future searches retrieve better context
   └─ Pattern library updated (occurrence_count, success_rate, confidence_adjustment)
```

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
|---------|--------|-----------------|----------|
| payment-service | error_rate | 18× baseline | t % 600 ∈ [0, 45s) |
| order-service | latency_p95 | 15× baseline | t % 600 ∈ [120, 165s) |
| user-service | cpu_usage | 4× baseline | t % 600 ∈ [240, 285s) |
| inventory-service | memory_bytes | 3.5× baseline | t % 600 ∈ [360, 405s) |
| notification-service | request_rate | 12× baseline | t % 600 ∈ [480, 525s) |

---

## Key Design Decisions

### Why `all-MiniLM-L6-v2` for embeddings?
- 384 dimensions (compact), runs CPU-only with no GPU required
- 80MB model, loads once per process via lazy singleton with thread lock
- MIT license, strong semantic textual similarity benchmarks
- Trade-off: less accurate than `text-embedding-3-large` but zero API cost per call

### Why HNSW over IVFFlat?
pgvector supports both. HNSW offers better recall at query time with no training phase — it handles small datasets gracefully from the start. IVFFlat requires a minimum cluster size for good centroids. AIRRA's pattern space is small (~100 `service:category` pairs), making HNSW the right choice.

### Why separate `celery` and `analysis` queues?
LLM analysis tasks take 3–8 seconds. Without queue separation, a flood of monitoring/embedding tasks would starve LLM analysis. The `analysis` queue processes only `analyze_incident`; the `celery` queue handles monitoring, embedding, and housekeeping.

### Why `SELECT FOR UPDATE` on pattern updates?
Multiple Celery worker replicas can process outcomes concurrently. Without pessimistic locking, two replicas reading `occurrence_count=5` simultaneously would both write `occurrence_count=6` — off by one per race. `SELECT FOR UPDATE` serializes access at the database level.

### Why `/analyze` returns 202 instead of the result?
LLM calls take 3–8s. Blocking an HTTP connection for 8 seconds prevents horizontal scaling and increases P99 latency. The endpoint returns `202 Accepted` in <50ms and enqueues a Celery task. The frontend polls `GET /incidents/{id}` until status transitions from `ANALYZING` → `PENDING_APPROVAL`.

### Multi-signal composite similarity (Stage 7 + 12)
Raw cosine distance alone is a poor similarity proxy — two incidents in different services can share near-identical symptoms but have completely different root causes. AIRRA uses a weighted composite:

```
composite = 0.5 × vector_similarity
          + 0.3 × service_match      (1.0 exact, 0.5 upstream/downstream, 0.0 unrelated)
          + 0.2 × metric_overlap     (Jaccard of metric name sets)
```

Retrieval fetches 10 pgvector candidates, re-ranks by composite, and passes the top-3 to the LLM. If the top composite ≥ `AIRRA_SIMILARITY_SKIP_THRESHOLD` (default 0.75), the LLM call is skipped and the past resolution is reused directly — saving ~$0.02–0.05 per call. Engineers still approve before any action executes.

### Service dependency graph in LLM prompts
Every analysis prompt auto-includes a `## Service Topology` section: the incident service's upstream dependencies, downstream dependents, criticality tier, and SLA. The hypothesis confidence formula then applies topology boosts:
- `database_issue` hypothesis + upstream service has DB keyword → +0.08
- `latency_spike`/`error_spike` + upstream Redis/cache → +0.05
- `network_issue` + ≥3 upstream deps → +0.05

### Hybrid retrieval (10 → re-rank → top-3)
Fetching more candidates before re-ranking significantly improves precision vs. pure "top-k from HNSW". The 10-candidate window is wide enough to surface cross-service matches the embedding alone might rank low, while the composite re-ranker promotes the genuinely relevant ones to the top-3 context window.

### Cold-start seed patterns
With zero incident history, `pattern_adjustment` would always be 1.0 (neutral), giving the hypothesis ranking nothing to work with. AIRRA ships six pre-seeded `PatternSignature` objects for common failure categories (`database_issue`, `memory_leak`, `cpu_spike`, `traffic_spike`, `network_issue`, `error_spike`) with hand-tuned confidence adjustments. These act as Bayesian priors until real data accumulates.

### Blast radius criticality weighting
The downstream blast score is multiplied by the criticality of each affected service:
`downstream_score = min(1.0, Σ(downstream_count × crit_mult) / 10)`
where `crit_mult`: `low=0.7`, `medium=1.0`, `high=1.3`, `critical=1.6`. This prevents 10 low-criticality toy services from generating the same blast score as 3 critical payment-tier services.

---

## Known Limitations

### Third-Party Opacity
When AWS RDS, Stripe, or any external dependency degrades, Prometheus shows green on all AIRRA-owned services. AIRRA detects the symptom (elevated error rates, latency) but cannot trace it to the external root cause. Planned mitigation: AWS Health API integration + cross-service simultaneity detection.

### Blast Radius Accuracy
The blast radius calculator now uses criticality-weighted downstream scoring and injects service topology into every LLM prompt. However, AIRRA does not yet model *shared physical infrastructure* (a single PostgreSQL cluster serving 10 services has an effective blast radius of 1, not 10). True shared-dependency mapping requires infrastructure-layer telemetry (AWS resource IDs, Kubernetes namespace topology) beyond what Prometheus exposes.

### Embedding Model Cold Start
`all-MiniLM-L6-v2` loads lazily on first use. The first embedding request per worker process takes ~2–4s (model load). Subsequent requests: ~20ms. In production, trigger a warm-up embed at worker startup.

### Single Celery Beat
Redis-backed Beat state is shared, but `celery-beat` must run as a single replica. Multiple Beat instances would fire duplicate tasks. Enforce this constraint manually in production.

---

## Pages

| Page | Path | Description |
|------|------|-------------|
| Dashboard | `/` | Live incident stats, active alerts, system health |
| Incidents | `/incidents` | Full list with status/severity/service filters |
| Incident Detail | `/incidents/[id]` | Hypotheses, actions, timeline, approval workflow |
| Approvals | `/approvals` | Actions waiting for human sign-off |
| On-Call | `/on-call` | Who is on-call now, grouped by service |
| Engineers | `/engineers` | Team roster, capacity bars, create new engineers |
| Notifications | `/notifications` | Alert delivery history, SLA tracking |
| Analytics | `/analytics` | MTTR, resolution rates, pattern learning |
| Learning | `/learning` | Pattern library, hypothesis accuracy insights |

---

## On-Call Management

### Register an engineer

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
    "start_time": "2026-03-06T09:00:00Z",
    "end_time": "2026-03-07T09:00:00Z",
    "priority": "primary",
    "schedule_name": "Week 1 Rotation"
  }'
```

Priority levels: `primary` → `secondary` → `tertiary`. Set `service: null` for all-services coverage.

---

## Configuration Reference

All settings use the `AIRRA_` env prefix.

| Variable | Default | Description |
|----------|---------|-------------|
| `AIRRA_API_KEY` | *(required)* | Auth key for all API endpoints |
| `AIRRA_LLM_PROVIDER` | `groq` | LLM provider: `groq`, `anthropic`, `openai` |
| `AIRRA_GROQ_API_KEY` | — | Groq API key (`gsk_...`) |
| `AIRRA_LLM_MODEL` | `llama-3.3-70b-versatile` | Model for reasoning/analysis |
| `AIRRA_LLM_GENERATOR_MODEL` | `llama-3.1-8b-instant` | Model for AI incident generation |
| `AIRRA_SLACK_WEBHOOK_URL` | — | Slack Incoming Webhook (empty = disabled) |
| `AIRRA_SMTP_ENABLED` | `false` | Enable real SMTP (false = simulation) |
| `AIRRA_ENVIRONMENT` | `development` | `development`, `staging`, `production` |
| `AIRRA_DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL DSN |
| `AIRRA_REDIS_URL` | `redis://localhost:6379/0` | Redis DSN |
| `AIRRA_DRY_RUN_MODE` | `true` | Prevent real action execution |
| `AIRRA_ANOMALY_THRESHOLD_SIGMA` | `3.0` | Z-score threshold for anomaly detection |
| `AIRRA_CONFIDENCE_THRESHOLD_HIGH` | `0.8` | High confidence → auto-propose action |
| `AIRRA_SIMILARITY_SKIP_THRESHOLD` | `0.75` | Composite score (0–1) above which LLM is skipped; lower = more LLM calls |
| `AIRRA_DEBUG` | `false` | Enable Swagger UI at `/docs` |

---

## Common Commands

```bash
# Start everything
docker compose up -d

# Rebuild after code changes
docker compose up -d --build backend celery-worker celery-analysis celery-beat

# Live logs
docker compose logs -f backend
docker compose logs -f celery-worker

# Run database migration manually
docker compose run --rm db-migrate alembic upgrade head

# Verify pgvector and embeddings
docker exec airra-postgres psql -U airra -c \
  "SELECT * FROM pg_extension WHERE extname='vector';"
docker exec airra-postgres psql -U airra -c \
  "SELECT id, embedding IS NOT NULL as has_embedding FROM incidents LIMIT 5;"

# Check Celery is alive
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect ping

# Trigger analysis on an incident
curl -X POST http://localhost:8000/api/v1/incidents/{id}/analyze \
  -H "X-API-Key: dev-test-key-12345"
# Returns 202 — poll GET /incidents/{id} for PENDING_APPROVAL

# Watch vector search + similarity skip in action
docker compose logs -f celery-worker | grep -E "embed|similarity|vector|hypothesis"

# Reset all data (WARNING: destructive)
docker compose down -v && docker compose up -d
```

---

## API Quick Reference

All endpoints require `X-API-Key: <key>` except `/health`, `/metrics`, and `/demo/metrics`.

```
GET  /health
GET  /metrics                            Prometheus scrape (AIRRA HTTP metrics)
GET  /demo/metrics                       Prometheus scrape (demo service Gauges)

# Incidents
GET  /api/v1/incidents/
POST /api/v1/incidents/
GET  /api/v1/incidents/{id}
POST /api/v1/incidents/{id}/analyze      → 202 Accepted, triggers Celery task
POST /api/v1/incidents/{id}/assign       Auto-assign to on-call engineer
POST /api/v1/incidents/{id}/assign/{eid} Manual assignment

# Approvals & Actions
GET  /api/v1/approvals/pending
POST /api/v1/approvals/{action_id}/approve
POST /api/v1/approvals/{action_id}/reject

# On-Call
POST /api/v1/on-call/                    Create schedule
POST /api/v1/on-call/find-current        Who is on-call for a service
GET  /api/v1/on-call/current/all         Everyone on-call across all services

# Engineers
GET  /api/v1/admin/engineers/
POST /api/v1/admin/engineers/
GET  /api/v1/admin/engineers/available/list

# Analytics + Learning
GET  /api/v1/analytics/insights?days=30
GET  /api/v1/learning/insights
```

Full interactive docs: http://localhost:8000/docs

---

## Project Structure

```
AIRRA/
├── backend/
│   ├── app/
│   │   ├── api/v1/                    # REST endpoints
│   │   ├── core/
│   │   │   ├── perception/            # Anomaly detection, signal correlator
│   │   │   ├── reasoning/             # Hypothesis generator, LLM prompting
│   │   │   ├── decision/              # Blast radius, action selection
│   │   │   ├── execution/             # Action executors (Kubernetes, scaling)
│   │   │   └── simulation/            # Static scenario runner
│   │   ├── models/                    # SQLAlchemy ORM models
│   │   │   ├── incident.py            # Incident + Vector(384) embedding column
│   │   │   ├── incident_pattern.py    # Learned patterns (L2 persistent cache)
│   │   │   └── ...
│   │   ├── services/
│   │   │   ├── anomaly_monitor.py     # Stage 1–3: Prometheus polling + detection
│   │   │   ├── incident_summarizer.py # Stage 4: structured text for embedding
│   │   │   ├── embedding_service.py   # Stage 6: sentence-transformers wrapper
│   │   │   ├── llm_client.py          # Groq/OpenAI/Anthropic abstraction
│   │   │   ├── notification_service.py # Stage 10: email + Slack webhook
│   │   │   └── learning_engine.py     # Stage 11: feedback + pattern library
│   │   ├── worker/
│   │   │   ├── celery_app.py          # Celery config + Beat schedule
│   │   │   └── tasks/
│   │   │       ├── analysis.py        # Stages 7-9: hybrid retrieval + composite score + LLM
│   │   │       ├── embedding.py       # Stage 6: async embed Celery task
│   │   │       └── monitoring.py      # anomaly check + AI generator + escalation task  
│   │   └── config.py                  # Pydantic settings (AIRRA_ prefix)
│   ├── alembic/versions/
│   │   ├── 005_add_incident_patterns.py
│   │   ├── 006_add_action_rejected_fields.py
│   │   └── 007_add_incident_embeddings.py  # pgvector extension + HNSW index
│   └── requirements.txt
├── frontend/
│   └── src/app/                        # Next.js App Router pages
├── monitoring/prometheus/prometheus.yml
├── grafana/provisioning/
├── docker-compose.yml
├── SETUP.md
└── README.md
```

---

## Troubleshooting

**No incidents appear after startup**
```bash
docker compose logs backend | grep -E "demo incident|scenario|Seeded"
docker compose logs celery-worker | grep "AI incident\|generator"
docker compose exec backend env | grep GROQ_API_KEY
```

**Analysis stays stuck in ANALYZING**
```bash
docker compose exec celery-worker \
  celery -A app.worker.celery_app inspect reserved
docker compose logs celery-worker | grep -E "LLM|groq|generate|error"
```

**Embeddings not generating**
```bash
docker compose logs celery-worker | grep -E "embed|sentence|MiniLM"
docker exec airra-postgres psql -U airra -c \
  "SELECT COUNT(*) FROM incidents WHERE embedding IS NOT NULL;"
```

**Prometheus targets show DOWN**
```bash
open http://localhost:9090/targets
curl http://localhost:8000/demo/metrics
```

**Migration failed**
```bash
# Migrations are idempotent — safe to re-run
docker compose run --rm db-migrate alembic upgrade head
```

**Port conflicts**
```bash
# Change host ports in docker-compose.yml, e.g. "8001:8000" for backend
```

---

## Roadmap

- [ ] **AWS Health API integration** — surface third-party incidents alongside Prometheus anomalies
- [x] **Service topology** — `DependencyGraph` wired into hypothesis prompts, confidence scoring, and blast radius (Prometheus-only; Loki/Jaeger extension points ready)
- [x] **Escalation pipeline** — Celery Beat `run_escalation_check` task (every 10 min) + Slack channel-level broadcast for unaddressed `PENDING_APPROVAL` incidents
- [x] **Separate worker pools** — `celery-worker` (monitoring/embedding, concurrency 4) + `celery-analysis` (LLM tasks, concurrency 2)
- [ ] **Multi-agent architecture** — specialized agents per stage using Anthropic Agent SDK
- [ ] **MCP tools** — expose AIRRA's incident API as MCP tools for Claude integration
- [ ] **Streaming hypothesis generation** — WebSocket updates as LLM reasons
- [ ] **Loki / Jaeger integration** — extend `SignalCorrelator` with log + trace signals for multi-source correlation

---

## Comparison Context

**Anthropic SRE Cookbook**: A reference SDK demo showing multi-agent coordination with Claude. AIRRA provides the full production pipeline (persistence, feedback loop, SRE notifications, Grafana dashboards, semantic retrieval) rather than an SDK reference.

**AWS DevOps Agent**: AWS-native managed service integrated with CloudWatch and Systems Manager. Excellent within the AWS ecosystem but closed-source and requires AWS lock-in. AIRRA is provider-agnostic and self-hostable with a semantic learning loop that AWS DevOps Agent does not expose.

---

## License

MIT — academic / personal project.
