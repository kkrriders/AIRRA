#!/usr/bin/env python3
"""
Seed AIRRA's RAG store with resolved incidents for the AI Engineering Platform.

Phase A3 of docs/superpowers/specs/2026-09-10-airra-ai-platform-integration-design.md.

AIRRA's analysis task retrieves prior art by vector-searching RESOLVED incidents
that have a joined postmortem and a non-null embedding (see
backend/app/worker/tasks/analysis.py). With none for the ai-platform services,
the first integrated incident's hypothesis has nothing to anchor on. This inserts
4 such (incident, postmortem, embedding) triples covering the topology in
config/service_dependencies.yaml.

Run inside the backend container (has DB creds + the embedding model):
    docker exec -it airra-backend python scripts/seed_ai_platform_patterns.py
    docker exec -it airra-backend python scripts/seed_ai_platform_patterns.py --verify
    docker exec -it airra-backend python scripts/seed_ai_platform_patterns.py --purge
"""
import argparse
import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import get_db_context  # noqa: E402

# Import every model so SQLAlchemy can resolve Incident's relationship() targets
# (Hypothesis, Action, IncidentEvent, ...) before the mapper is configured —
# same set app.database.init_db() imports.
from app.models.action import Action  # noqa: E402,F401
from app.models.audit_log import AgentAuditLog  # noqa: E402,F401
from app.models.engineer import Engineer  # noqa: E402,F401
from app.models.engineer_review import EngineerReview  # noqa: E402,F401
from app.models.hypothesis import Hypothesis  # noqa: E402,F401
from app.models.incident import Incident, IncidentSeverity, IncidentStatus  # noqa: E402
from app.models.incident_event import IncidentEvent  # noqa: E402,F401
from app.models.incident_pattern import IncidentPattern  # noqa: E402,F401
from app.models.notification import Notification  # noqa: E402,F401
from app.models.on_call_schedule import OnCallSchedule  # noqa: E402,F401
from app.models.postmortem import Postmortem  # noqa: E402
from app.services.embedding_service import get_embedding_service  # noqa: E402

SEED_SOURCE = "seed"  # detection_source marker — analysis.py excludes only "ai_generator"
SEED_TRUST = 0.7      # same weight as a human-approved incident; below postmortem-grade 1.0

# --- The 4 seed incidents ---------------------------------------------------
# Each maps onto a real chaos scenario (labs/integration/chaos.ps1) so retrieval
# has something genuinely relevant when that fault is injected.
SEEDS = [
    {
        "key": "ai-platform/orchestrator-entrypoint-failure",
        "service": "orchestrator",
        "category": "error_spike",
        "severity": IncidentSeverity.CRITICAL,
        "metrics": ["error_rate", "request_rate"],
        "title": "orchestrator node raises on every run after bad prompt-template deploy",
        "description": (
            "error_rate for service=orchestrator jumped to ~1.0 within one minute. "
            "Every LangGraph run failed at the orchestrator entrypoint with a 500 "
            "before reaching any worker node. request_rate stayed flat, so this was "
            "a per-run failure, not a load problem."
        ),
        "root_cause": (
            "A prompt-template version published minutes earlier referenced an "
            "undefined variable; orchestrator_node raised KeyError on render for "
            "every run. No template smoke-test gate in CI."
        ),
        "resolution": (
            "Rolled the prompt-template back to the previous version. error_rate "
            "returned to 0 on the next monitor cycle. Added a template-render smoke "
            "test to CI and a canary run after each publish."
        ),
        "prevention": [
            "CI smoke-test that renders every prompt template with sample state",
            "Canary run gate after prompt-template publish before it goes live",
        ],
        "detection_improvements": [
            "Alert on orchestrator error_rate > 0.2 for 2 consecutive minutes",
        ],
    },
    {
        "key": "ai-platform/groq-rate-limit-storm",
        "service": "tool_runner",
        "category": "error_spike",
        "severity": IncidentSeverity.HIGH,
        "metrics": ["error_rate", "latency_p95"],
        "title": "Groq 429 storm fails tool_runner, executor and verifier together",
        "description": (
            "llm_gateway_errors_total{kind=\"rate_limit\"} climbed sharply and "
            "error_rate rose in parallel on tool_runner, executor and verifier — "
            "every node that calls Groq. researcher (Qdrant + Groq) was only "
            "partially affected. Shared upstream: the Groq gateway."
        ),
        "root_cause": (
            "A burst of concurrent runs exceeded the Groq account's requests-per-"
            "minute quota. No client-side rate limiting, so all LLM nodes retried "
            "into the same 429 wall and amplified the load."
        ),
        "resolution": (
            "Shed load by pausing the run queue for 5 minutes, switched the default "
            "model to the cheaper tier, and added a token-bucket limiter in llm.py "
            "sized to 80% of the account quota. Errors cleared once QPS dropped."
        ),
        "prevention": [
            "Client-side token-bucket limiter in app/llm.py at 80% of Groq quota",
            "Exponential backoff with jitter on 429, capped retries",
            "Per-project concurrency cap on run submission",
        ],
        "detection_improvements": [
            "Alert on llm_gateway_errors_total{kind=\"rate_limit\"} rate > 0.1/s",
        ],
    },
    {
        "key": "ai-platform/qdrant-unreachable",
        "service": "researcher",
        "category": "metric_anomaly",
        "severity": IncidentSeverity.MEDIUM,
        "metrics": ["error_rate"],
        "title": "researcher degrades when Qdrant is unreachable",
        "description": (
            "service_dependency_failures_total{service=\"researcher\","
            "dependency=\"qdrant\"} incremented on every run; researcher error_rate "
            "rose to ~0.15. The node fell back to keyword-only retrieval and runs "
            "still completed, so user-facing impact was degraded quality, not outage."
        ),
        "root_cause": (
            "The Qdrant container was stopped (maintenance) and the researcher node "
            "has no circuit breaker — it attempted the vector search, timed out, "
            "then fell back per-request, adding ~2s latency each run."
        ),
        "resolution": (
            "Restarted Qdrant; failures stopped immediately. Added a short-lived "
            "circuit breaker so researcher skips the vector call for 30s after a "
            "connection failure instead of timing out every request."
        ),
        "prevention": [
            "Circuit breaker around the Qdrant client in app/rag.py",
            "Qdrant liveness alert independent of the platform's own health",
        ],
        "detection_improvements": [
            "Page only if researcher error_rate > 0.05 sustained 10 min "
            "(keyword fallback is acceptable below that)",
        ],
    },
    {
        "key": "ai-platform/executor-postgres-slow-queries",
        "service": "executor",
        "category": "latency_spike",
        "severity": IncidentSeverity.HIGH,
        "metrics": ["latency_p95", "error_rate"],
        "title": "executor latency_p95 climbs from unindexed run_events scan",
        "description": (
            "latency_p95 for service=executor drifted from ~0.4s to ~4s over 20 "
            "minutes (EWMA drift, not a step change). error_rate followed as "
            "downstream calls began timing out. tool_runner, which shares Postgres, "
            "showed a milder version of the same drift."
        ),
        "root_cause": (
            "run_events grew past ~2M rows. executor_node queries it by "
            "(project_id, created_at) with no composite index, so each run did a "
            "sequential scan whose cost grew with table size."
        ),
        "resolution": (
            "Added CREATE INDEX CONCURRENTLY on run_events(project_id, created_at). "
            "latency_p95 dropped back under 0.5s within minutes. Backfilled a "
            "retention job to cap run_events at 90 days."
        ),
        "prevention": [
            "Composite index on run_events(project_id, created_at)",
            "90-day retention job on run_events",
            "Slow-query log review in weekly ops rotation",
        ],
        "detection_improvements": [
            "EWMA-drift alert on executor latency_p95 (catch gradual, not just spikes)",
        ],
    },
]


def _iso_recent(days_ago: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


async def _existing_keys(db) -> set[str]:
    rows = (
        await db.execute(
            select(Incident.context).where(Incident.detection_source == SEED_SOURCE)
        )
    ).scalars().all()
    return {c.get("seed_key") for c in rows if isinstance(c, dict) and c.get("seed_key")}


async def seed() -> None:
    embed = get_embedding_service()
    async with get_db_context() as db:
        have = await _existing_keys(db)
        created = 0
        for i, s in enumerate(SEEDS):
            if s["key"] in have:
                print(f"skip   {s['key']} (already seeded)")
                continue

            detected = _iso_recent(30 - i * 5)
            resolved = detected + timedelta(minutes=25 + i * 10)
            incident = Incident(
                title=s["title"],
                description=s["description"],
                status=IncidentStatus.RESOLVED,
                severity=s["severity"],
                affected_service=s["service"],
                affected_components=[s["service"]],
                detected_at=detected,
                resolved_at=resolved,
                resolution_time_seconds=int((resolved - detected).total_seconds()),
                resolution_summary=s["resolution"],
                detection_source=SEED_SOURCE,
                trust_score=SEED_TRUST,
                metrics_snapshot={"anomalous_metrics": s["metrics"], "namespace": "ai-platform"},
                context={"seed_key": s["key"], "category": s["category"], "namespace": "ai-platform"},
            )
            db.add(incident)
            await db.flush()  # assign incident.id

            db.add(
                Postmortem(
                    incident_id=incident.id,
                    actual_root_cause=s["root_cause"],
                    contributing_factors=[],
                    duration_minutes=int((resolved - detected).total_seconds() // 60),
                    what_went_well=["Fallback / rollback path existed", "Monitor caught it within one cycle"],
                    what_went_wrong=["No guard rail prevented the trigger"],
                    lessons_learned=[s["resolution"]],
                    action_items=[
                        {"description": p, "owner": "platform-oncall", "priority": "high", "status": "open"}
                        for p in s["prevention"]
                    ],
                    prevention_measures=s["prevention"],
                    detection_improvements=s["detection_improvements"],
                    response_improvements=[],
                    ai_hypothesis_correct=True,
                    published=True,
                    published_at=resolved,
                )
            )

            incident.embedding = embed.embed_incident(
                incident,
                extra_context={"root_cause": s["root_cause"], "resolution": s["resolution"]},
            )
            print(f"create {s['key']}  -> incident {incident.id} (embedding dim {len(incident.embedding)})")
            created += 1
        print(f"\n{created} seeded, {len(SEEDS) - created} already present.")


async def verify() -> int:
    async with get_db_context() as db:
        rows = (
            await db.execute(
                select(Incident)
                .where(Incident.detection_source == SEED_SOURCE)
                .where(Incident.context["seed_key"].isnot(None))
            )
        ).scalars().all()
        by_key = {r.context.get("seed_key"): r for r in rows}
        ok = True
        for s in SEEDS:
            r = by_key.get(s["key"])
            if r is None:
                print(f"MISSING  {s['key']}")
                ok = False
                continue
            pm = (
                await db.execute(select(Postmortem).where(Postmortem.incident_id == r.id))
            ).scalar_one_or_none()
            has_emb = r.embedding is not None and len(r.embedding) == 384
            has_pm = pm is not None
            retrievable = r.status == IncidentStatus.RESOLVED and has_emb and has_pm
            flag = "OK  " if retrievable else "BAD "
            print(f"{flag} {s['key']}  status={r.status.value} embedding={has_emb} postmortem={has_pm}")
            ok = ok and retrievable
        print("\nRAG-retrievable:" , "all 4 seeds" if ok else "INCOMPLETE — re-run without --verify")
        return 0 if ok else 1


async def purge() -> None:
    async with get_db_context() as db:
        rows = (
            await db.execute(
                select(Incident).where(Incident.detection_source == SEED_SOURCE)
            )
        ).scalars().all()
        for r in rows:
            await db.delete(r)  # postmortem cascades via ondelete="CASCADE"
        print(f"deleted {len(rows)} seed incident(s) (+ cascaded postmortems)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verify", action="store_true", help="check the seeds are RAG-retrievable, exit non-zero if not")
    ap.add_argument("--purge", action="store_true", help="delete all detection_source='seed' incidents")
    args = ap.parse_args()

    if args.verify:
        sys.exit(asyncio.run(verify()))
    elif args.purge:
        asyncio.run(purge())
    else:
        asyncio.run(seed())
