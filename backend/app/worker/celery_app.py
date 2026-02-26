"""
Celery application configuration for AIRRA.

Replaces asyncio.create_task()-based background services with distributed tasks.
Beat handles scheduling so only one scheduler runs even with N API replicas.

Scheduler: redbeat.RedBeatScheduler stores schedule state in Redis, so Beat
survives container restarts without firing all tasks immediately (unlike
PersistentScheduler which uses a local file that is lost on restart).
"""
from celery import Celery

from app.config import settings

# Named constants for Beat schedule intervals (N5)
ANOMALY_CHECK_INTERVAL_SECONDS: float = 60.0      # every minute
AI_GENERATOR_INTERVAL_SECONDS: float = 30 * 60.0  # every 30 minutes

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
    # redbeat: stores last-run timestamps in Redis so Beat survives restarts
    # without firing all tasks immediately (C3 fix — replaces PersistentScheduler)
    beat_scheduler="redbeat.RedBeatScheduler",
    redbeat_redis_url=str(settings.redis_url),
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
