"""
Celery tasks for periodic monitoring (anomaly detection + AI incident generation
+ escalation checks).

These are one-shot tasks — they do one check and exit. Celery Beat fires them on
the configured schedule (every 60s for anomaly checks, every 30min for AI generator,
every 10min for escalation checks).
This replaces the infinite while-loop + asyncio.sleep() pattern from the services.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from celery.utils.log import get_task_logger

from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)

# Incidents unaddressed in PENDING_APPROVAL longer than this get escalated.
ESCALATION_WINDOW_MINUTES: int = 120


@celery_app.task(name="app.worker.tasks.monitoring.run_anomaly_check")
def run_anomaly_check() -> dict:
    """
    One-shot anomaly check across all monitored services.

    Beat calls this every 60s. The AnomalyMonitor's deduplication window
    prevents duplicate incidents even if called frequently.
    """
    try:
        return asyncio.run(_anomaly_check())
    except Exception as e:
        logger.error(f"Anomaly check task failed: {e}", exc_info=True)
        return {"status": "error", "error": type(e).__name__}


@celery_app.task(name="app.worker.tasks.monitoring.run_ai_generator")
def run_ai_generator() -> dict:
    """
    One-shot AI incident generation cycle.

    Beat calls this every 30 minutes. Only generates incidents in development
    environment (checked inside _ai_generator()).
    """
    try:
        return asyncio.run(_ai_generator())
    except Exception as e:
        logger.error(f"AI generator task failed: {e}", exc_info=True)
        return {"status": "error", "error": type(e).__name__}


@celery_app.task(name="app.worker.tasks.monitoring.run_escalation_check")
def run_escalation_check() -> dict:
    """
    Escalate PENDING_APPROVAL incidents that have had no SRE response.

    Beat calls this every 10 minutes. Any incident stuck in PENDING_APPROVAL
    for longer than ESCALATION_WINDOW_MINUTES (120 min) is transitioned to
    ESCALATED and a Slack alert fires so on-call engineers are re-paged.
    """
    try:
        return asyncio.run(_escalation_check())
    except Exception as e:
        logger.error(f"Escalation check task failed: {e}", exc_info=True)
        return {"status": "error", "error": type(e).__name__}


async def _anomaly_check() -> dict:
    """Run a single anomaly detection cycle via the public facade (S1 fix)."""
    from app.services.anomaly_monitor import get_monitor

    monitor = get_monitor()
    await monitor.check_once()
    logger.info("Anomaly check cycle complete")
    return {"status": "ok"}


async def _ai_generator() -> dict:
    """Run a single AI incident generation cycle via the public facade (S1 fix)."""
    from app.config import settings
    from app.services.ai_incident_generator import get_ai_generator

    generator = get_ai_generator()
    if not generator.enabled or settings.environment != "development":
        logger.info("AI generator disabled or not in development — skipping")
        return {"status": "skipped"}

    await generator.generate_once()
    logger.info("AI incident generation cycle complete")
    return {"status": "ok"}


async def _escalation_check() -> dict:
    """
    Find PENDING_APPROVAL incidents with no activity for >ESCALATION_WINDOW_MINUTES
    and transition them to ESCALATED, firing a Slack alert for each.

    Uses updated_at (not detected_at) as the staleness marker: updated_at reflects
    the last time any field changed, which approximates when the incident entered
    PENDING_APPROVAL. A no-op ESCALATED→ESCALATED repeat is safe — the WHERE clause
    filters only PENDING_APPROVAL rows, so already-escalated incidents are skipped.
    """
    from sqlalchemy import select

    from app.database import get_db_context
    from app.models.incident import Incident, IncidentStatus

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=ESCALATION_WINDOW_MINUTES)
    escalated_count = 0

    # Snapshot the data needed for Slack BEFORE committing, then release the DB
    # connection before making the HTTP call.  Holding an open transaction across
    # a 10s Slack timeout would exhaust the connection pool under burst load.
    escalated: list[tuple[str, str, str, str]] = []  # (id, title, service, severity)

    async with get_db_context() as db:
        stmt = select(Incident).where(
            Incident.status == IncidentStatus.PENDING_APPROVAL,
            Incident.updated_at <= cutoff,
        )
        result = await db.execute(stmt)
        stale_incidents = result.scalars().all()

        for incident in stale_incidents:
            incident.status = IncidentStatus.ESCALATED
            escalated_count += 1
            escalated.append((
                str(incident.id),
                incident.title,
                incident.affected_service,
                incident.severity.value,
            ))
            logger.warning(
                f"Escalated incident {incident.id} ({incident.title}) — "
                f"unaddressed for >{ESCALATION_WINDOW_MINUTES} minutes"
            )
    # DB transaction committed; connection released.  Now send Slack alerts.
    for incident_id_str, title, service, severity in escalated:
        await _notify_escalation_slack(incident_id_str, title, service, severity)

    return {"status": "ok", "escalated": escalated_count}


async def _notify_escalation_slack(
    incident_id: str,
    title: str,
    service: str,
    severity: str,
) -> None:
    """
    Post an escalation alert to the Slack Incoming Webhook (best-effort).

    Accepts plain data (not an ORM object) so it can be called AFTER the DB
    transaction has been committed and the connection released.

    Unlike NotificationService._send_slack(), this bypasses the per-engineer
    routing layer — escalation is a channel-level broadcast, not a personal page.
    Falls back to simulation mode (log only) when AIRRA_SLACK_WEBHOOK_URL is unset.
    """
    import httpx

    from app.config import settings

    webhook_url = settings.slack_webhook_url
    if not webhook_url:
        logger.info(
            f"[SLACK SIMULATION] Escalation alert for incident {incident_id}: "
            f"{title} — set AIRRA_SLACK_WEBHOOK_URL to enable real delivery"
        )
        return

    payload = {
        "text": f":rotating_light: Incident ESCALATED: {title}",
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": ":rotating_light: Incident Escalated"},
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*{title}*\n"
                        f"*Service:* `{service}`\n"
                        f"*Severity:* {severity.upper()}\n"
                        f"*Pending >{ESCALATION_WINDOW_MINUTES}min with no SRE response*\n"
                        f"*ID:* `{incident_id}`"
                    ),
                },
            },
        ],
    }

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json=payload, timeout=10.0)
            resp.raise_for_status()
        logger.info(f"Escalation Slack alert sent for incident {incident_id}")
    except Exception as e:
        # Non-fatal: escalation DB write already committed; Slack failure is logged only.
        logger.error(f"Failed to send escalation Slack alert for {incident_id}: {e}")
