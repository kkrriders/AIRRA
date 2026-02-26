#!/bin/bash
set -e

# Note: Alembic migrations are intentionally NOT run here.
# In Docker Compose, the 'db-migrate' service runs 'alembic upgrade head' once
# before this container starts (condition: service_completed_successfully).
# In Kubernetes, use an initContainer to run the migration job.
# Running migrations from every replica simultaneously risks concurrent migration
# conflicts and deadlocks.

echo "Starting AIRRA backend API..."
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level "${AIRRA_LOG_LEVEL:-info}"
