"""
Celery application configuration for AIRRA.

Replaces asyncio.create_task()-based background services with distributed tasks.
Beat handles scheduling so only one scheduler runs even with N API replicas.

Scheduler: PersistentScheduler (Celery built-in) stores schedule state in a
local shelve file. Tasks fire once on Beat startup after a container restart,
which is acceptable for AIRRA's 1-minute and 30-minute intervals.
"""
from celery import Celery

from app.config import settings

# Named constants for Beat schedule intervals (N5)
ANOMALY_CHECK_INTERVAL_SECONDS: float = 60.0      # every minute
AI_GENERATOR_INTERVAL_SECONDS: float = 30 * 60.0  # every 30 minutes (free-tier safe)

celery_app = Celery(
    "airra",
    broker=str(settings.redis_url),
    backend=str(settings.redis_url),
    include=[
        "app.worker.tasks.analysis",
        "app.worker.tasks.monitoring",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Re-queue task if worker dies mid-execution (at-least-once delivery)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Don't hoard tasks — each worker pulls one at a time for fair distribution
    worker_prefetch_multiplier=1,
    # Hard kill at 120s; soft signal at 90s so tasks can clean up
    task_time_limit=120,
    task_soft_time_limit=90,
    # Route slow LLM analysis tasks to a dedicated queue so high-frequency
    # monitoring tasks are never starved behind 3–8s LLM calls (S2)
    task_routes={
        "app.worker.tasks.analysis.analyze_incident": {"queue": "analysis"},
    },
    beat_schedule={
        "anomaly-monitor": {
            "task": "app.worker.tasks.monitoring.run_anomaly_check",
            "schedule": ANOMALY_CHECK_INTERVAL_SECONDS,
        },
        "ai-incident-generator": {
            "task": "app.worker.tasks.monitoring.run_ai_generator",
            "schedule": AI_GENERATOR_INTERVAL_SECONDS,
        },
    },
)
