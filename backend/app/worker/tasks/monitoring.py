"""
Celery tasks for periodic monitoring (anomaly detection + AI incident generation).

These are one-shot tasks — they do one check and exit. Celery Beat fires them on
the configured schedule (every 60s for anomaly checks, every 30min for AI generator).
This replaces the infinite while-loop + asyncio.sleep() pattern from the services.
"""
import asyncio
import logging

from celery.utils.log import get_task_logger

from app.worker.celery_app import celery_app

logger = get_task_logger(__name__)


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
        return {"status": "error", "message": str(e)}


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
        return {"status": "error", "message": str(e)}


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
