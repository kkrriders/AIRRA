# ADR-001: Celery over asyncio background tasks for scheduling

## Status
Accepted

## Context

AIRRA requires three categories of recurring work:
1. **Anomaly detection** — poll Prometheus every 60 seconds
2. **LLM analysis** — 3–8 second calls triggered per incident
3. **AI incident generation** — fire every 30 minutes (free-tier rate limit)

The initial implementation used `asyncio.create_task()` loops started at FastAPI startup. This approach has a critical flaw: tasks are bound to a single process. In a multi-replica deployment every replica would independently run all loops, producing duplicate incidents and duplicate Prometheus scrapes. Killing the API process silently terminates all background work with no retry or visibility.

## Decision

Replace all `asyncio.create_task()` loops with **Celery Beat + Celery workers**.

- `celery-beat` owns the schedule (one replica only; enforced operationally)
- `celery-worker` (-Q celery, concurrency=4) handles monitoring, embedding, and housekeeping
- `celery-analysis` (-Q analysis, concurrency=2) handles LLM tasks exclusively

Queue separation prevents a flood of fast monitoring tasks from starving the slow (3–8s) LLM analysis tasks — a head-of-line blocking problem that asyncio cannot solve without manual priority queuing.

Tasks that wrap async logic use `asyncio.run(_async_fn())` — the correct pattern for sync Celery workers calling async database code.

## Consequences

**Benefits:**
- Workers are horizontally scalable independently of the API process
- Beat schedule survives API restarts; task history is visible in Redis
- LLM tasks cannot be starved by high-frequency monitoring tasks
- Failed tasks are retried automatically with configurable backoff

**Trade-offs:**
- Two additional Docker services (`celery-worker`, `celery-beat`, `celery-analysis`)
- `celery-beat` must run as a single replica — multiple instances would fire duplicate tasks. This constraint is enforced operationally, not technically.
- Local development requires running all services (`docker compose up`) rather than just `uvicorn`

## Alternatives considered

**FastAPI `BackgroundTasks`**: designed for fire-and-forget per-request work, not recurring schedules. No retry, no persistence, no cross-process coordination.

**APScheduler in-process**: avoids additional services but still suffers from the multi-replica duplication problem and provides no task visibility.
