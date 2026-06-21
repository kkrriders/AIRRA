# Portfolio Fix List
*Compiled 2026-06-19. Resume narrative: AI Systems Engineering.*

---

## Career Direction

**Pursue: AI Systems Engineering**
Primary project: **AIRRA** | Secondary project: **MockPrep**

**Interview narrative:**
> "MockPrep taught me what breaks when AI doesn't work reliably in a product. AIRRA is what I built to solve those classes of problems at the infrastructure layer. Both projects independently led me to the same engineering principles — async task queues for LLM calls, deterministic scoring instead of LLM self-assessment, and injection guards on all user inputs."

---

## AIRRA Fixes (Priority 1 — primary portfolio project)

### Critical (do these first)

- [x] **Add eval harness** *(done 2026-06-19)*
  - `backend/tests/evals/` — 10 golden fixtures + `score.py` + `test_confidence_scoring.py`
  - 20 pytest tests: category ranking + confidence range for all 8 failure types
  - Runs in CI without LLM API key (tests deterministic confidence formula only)
  - `python -m tests.evals.score --min-accuracy 0.80` — currently 10/10

- [x] **Add GitHub Actions CI** *(done 2026-06-19)*
  - `.github/workflows/ci.yml` updated: lint → mypy → unit tests → eval harness
  - Eval harness step added to existing CI pipeline

- [x] **Add OpenTelemetry distributed tracing** *(done 2026-06-19)*
  - `backend/app/core/telemetry.py` — setup_telemetry + instrument_fastapi
  - FastAPI + SQLAlchemy + Redis instrumented; graceful degradation if packages absent
  - Jaeger added to `docker-compose.yml` under `profiles: tracing`
  - Enable: `AIRRA_OTEL_ENABLED=true docker compose --profile tracing up`
  - Jaeger UI: http://localhost:16686

### High (do before any interviews)

- [x] **Add per-user authentication (replace global API key)** *(done 2026-06-19)*
  - `backend/app/models/user.py` — User model (email, bcrypt password, role, last_login)
  - `backend/alembic/versions/011_add_users_table.py` — migration
  - `backend/app/services/auth_service.py` — hash_password, verify_password, create_access_token, create_refresh_token, decode_token (PyJWT + bcrypt)
  - `backend/app/api/v1/auth.py` — POST /register, POST /login, POST /refresh, GET /me
  - `backend/app/api/dependencies.py` — added get_current_user (JWT Bearer) alongside existing verify_api_key
  - Access: 15min | Refresh: 7 days with rotation

- [x] **Add streaming hypothesis output (WebSocket)** *(done 2026-06-19)*
  - `backend/app/api/v1/stream.py` — WS /api/v1/incidents/{id}/stream
  - Architecture: Celery tasks publish status events to Redis pub/sub `incident:{id}:events`
  - FastAPI WebSocket subscribes via dedicated connection (separate from shared pool)
  - Events: `connected`, `status_update` (PENDING_APPROVAL, FAILED), carries hypothesis count + top_category
  - `analysis_task.py` — publishes on PENDING_APPROVAL and FAILED transitions

- [x] **Add cost budget enforcement** *(done 2026-06-19)*
  - `backend/app/services/llm_client.py` — `_check_daily_budget()` pre-call + `_track_daily_budget()` post-call
  - Redis keys: `budget:daily:{model}:{YYYY-MM-DD}` — atomic INCRBY, 24h TTL
  - `BudgetExceededError` raised when `AIRRA_DAILY_TOKEN_BUDGET` tokens exceeded
  - `backend/app/api/v1/admin/usage.py` — GET /api/v1/admin/usage (7-day window, per-model breakdown)

### Medium (nice to have)

- [x] **Add Redis observability (SPOF monitoring)** *(done 2026-06-20)*
  - `redis-exporter` (oliver006/redis_exporter:v1.62.0-alpine) added to docker-compose — exposes `redis_memory_used_bytes`, `redis_up`, etc.
  - `monitoring/prometheus/alerts/redis.yml` — `RedisMemoryHigh` (>80% maxmemory, warning) + `RedisDown` (>1 min down, critical)
  - `monitoring/prometheus/prometheus.yml` — `rule_files` enabled; `redis` scrape job added; alerts dir mounted
  - **Known remaining SPOF**: single Redis instance is still broker + cache + rate-limiter. Next step = split into `redis-broker` (Celery) + `redis-cache` (rate-limit/dedup/pub-sub). Not done — Sentinel on a single host is theater; split-responsibility is the real fix and requires config refactor.

- [x] **Add cross-incident correlation** *(done 2026-06-20)*
  - `backend/app/services/correlation_service.py` — groups incidents sharing a common upstream dependency
  - `backend/alembic/versions/012_add_correlation_group_id.py` — UUID column + index on `incidents`
  - Wired into `anomaly_monitor._create_incident` (best-effort, never blocks incident creation)
  - `GET /api/v1/incidents/?correlation_group_id=<uuid>` — returns all incidents in a blast-radius group
  - `correlation_group_id` surfaced in `IncidentResponse` schema and `Incident.to_dict()`
  - Threshold: 3+ incidents within 5-minute window sharing any upstream; joins existing group if one exists

- [x] **Update CLAUDE.md file structure section** *(done 2026-06-21)*
  - Added `correlation_service.py` to services tree
  - `core/` subdirectory structure (perception/reasoning/decision/execution/simulation) was already correct

---

## MockPrep Fixes (Priority 2 — secondary portfolio project)

### Critical

- [ ] **Migrate backend to TypeScript**
  - Add `tsconfig.json` at project root
  - Rename `src/**/*.js` → `src/**/*.ts`, add types to all service function signatures
  - Add `ts-node` + `tsx` for dev, compile to `dist/` for production
  - Why: in 2026 untyped Node.js backends read as a gap to any senior engineer

- [ ] **Build adaptive difficulty feature (currently listed as a known gap)**
  - After 3 consecutive answers with score > 80, increment question difficulty for the session
  - After 3 consecutive answers with score < 40, decrement difficulty
  - Store current difficulty level in `Interview.adaptiveDifficulty` field
  - Why: it is listed as a gap in the README — interviewers who read carefully will ask about it

### High

- [ ] **Add LLM eval harness for answer scorer**
  - Create `tests/evals/scorer-golden.json` with 10 fixed Q&A pairs
  - Each fixture: `{ question, answer, expectedScoreRange: { min, max }, expectedKeywordsHit }`
  - Write `npm run eval:scorer` script that runs all fixtures and reports accuracy
  - Why: shows you can measure LLM quality, not just integrate it

- [ ] **Fix the results page gaps (known gap)**
  - Display `diagramSnapshot` in read-only React Flow canvas for completed system design answers
  - Display `testResults` (pass/fail per case) for completed coding answers
  - Why: currently results page is incomplete for the two most interesting question types

### Medium

- [ ] **Rename "Company Research Agent" everywhere**
  - Change to "Company-tailored question generation" in README, UI, and code comments
  - Why: calling it an "agent" invites interview questions you can't fully answer (what does it plan? what tools does it choose?)

- [ ] **Add semantic weak-area retrieval**
  - Replace pure MongoDB `$match` + `$sort` in `retrieval-service.js` with embedding-based similarity
  - Use a lightweight embedding (e.g. `transformers.js` in-process or a Groq embedding call)
  - Why: current "history" is just DB queries — semantic search is what makes progress tracking actually useful

---

## Resume Framing (copy this exactly)

**AIRRA bullet:**
> Built an autonomous incident response system with Prometheus anomaly detection, pgvector RAG (composite vector + service-topology + metric-overlap scoring), Celery async analysis pipeline, deterministic LLM confidence scoring, and OWASP LLM01/06 security controls. Implemented human-in-the-loop approval lifecycle with policy engine veto and append-only audit trail.

**MockPrep bullet:**
> Built an AI mock interview platform with real-time answer scoring via SSE, BullMQ async scoring pipeline (Redis-absent fallback), multi-modal support across text/voice/system-design canvas (React Flow, 14 node types)/DSA coding (Monaco + Piston execution), and adaptive follow-up logic. Includes prompt injection guards and a provider-abstraction layer with automatic Groq → OpenRouter failover.

**Do not say:** "30 features", "agent" for the company research feature, or "fully autonomous" for AIRRA.

---

## What connects both projects (use in interviews)

Both independently arrived at the same engineering principles:

| Principle | MockPrep | AIRRA |
|---|---|---|
| Don't trust LLM self-assessment | Evidence gate in `answer-scorer.js` | Deterministic confidence formula |
| Async queue for LLM calls | BullMQ + setImmediate fallback | Celery analysis queue |
| Provider abstraction + fallback | Groq → OpenRouter | llm_client with model config |
| Injection guard on all inputs | `injection-guard.js` | `prompt_guard.py` (OWASP LLM01) |
| Real-time event streaming | SSE broadcaster | SSE + Celery task events |

**One-line summary for interviews:**
> "I've built on both sides of the AI stack. MockPrep taught me what breaks in AI products. AIRRA is the infrastructure-level answer to those problems."
