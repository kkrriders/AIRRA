"""
AIRRA FastAPI Application.

Senior Engineering Note:
- Lifespan context for startup/shutdown
- CORS middleware for frontend integration
- Security headers and HTTPS enforcement
- Structured logging
- Health check endpoint
- API versioning
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from urllib.parse import urlparse

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.database import close_db, init_db, get_db_context

# Configure structured logging
logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(getattr(logging, settings.log_level))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Add security headers to all responses.

    Senior Engineering Note:
    - Prevents clickjacking with X-Frame-Options
    - Enables XSS protection
    - Prevents MIME sniffing
    - Enforces Content Security Policy
    - Adds HSTS for HTTPS enforcement
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"

        # Enable browser XSS protection
        response.headers["X-Content-Type-Options"] = "nosniff"

        # Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Permissions policy (formerly Feature-Policy)
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Content Security Policy - strict for API
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )

        # HSTS - only in production with HTTPS
        if settings.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains; preload"
            )

        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan handler for startup and shutdown.

    Senior Engineering Note:
    This replaces the deprecated @app.on_event decorators.
    """
    # Startup
    logger.info("Starting AIRRA Backend API", extra={"version": settings.app_version})

    # Validate critical configuration
    if not settings.api_key.get_secret_value():
        error_msg = (
            "AIRRA_API_KEY must be set in environment variables. "
            "For development, use a test key like 'dev-test-key-12345'. "
            "For production, use a strong random key."
        )
        logger.error(error_msg)
        raise ValueError(error_msg)

    logger.info("API key configured successfully")

    # Initialize database (create tables)
    # In production, use Alembic migrations instead
    if settings.environment == "development":
        logger.info("Initializing database...")
        await init_db()

    # Start background anomaly monitor
    from app.services.anomaly_monitor import start_anomaly_monitor
    logger.info("Starting anomaly detection monitor...")
    await start_anomaly_monitor()

    # Start AI incident generator (development only)
    if settings.environment == "development":
        from app.services.ai_incident_generator import start_ai_generator
        logger.info("Starting AI incident generator...")
        await start_ai_generator()

    # Auto-create and manage demo incidents in development mode
    # This creates STATIC incidents on startup for immediate demo
    # AI-generated incidents will appear over time (every 30-60 min)
    if settings.environment == "development":
        logger.info("Development mode: Managing static demo incidents...")
        try:
            from datetime import datetime, timedelta, timezone
            from sqlalchemy import select, delete
            from app.models.incident import Incident, IncidentStatus
            from app.core.simulation.scenario_runner import get_scenario_runner

            runner = get_scenario_runner()

            async with get_db_context() as db:
                # Step 1: Clean up old simulation incidents (older than 24 hours)
                cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
                old_sims_query = select(Incident).where(
                    Incident.detection_source == "quick_incident_ui",
                    Incident.detected_at < cutoff_time
                )
                old_sims = await db.execute(old_sims_query)
                old_sim_incidents = old_sims.scalars().all()

                if old_sim_incidents:
                    delete_query = delete(Incident).where(
                        Incident.detection_source == "quick_incident_ui",
                        Incident.detected_at < cutoff_time
                    )
                    await db.execute(delete_query)
                    await db.commit()
                    logger.info(f"Cleaned up {len(old_sim_incidents)} old simulation incidents (>24h)")

                # Step 2: Progress existing recent simulation incidents through lifecycle
                recent_sims_query = select(Incident).where(
                    Incident.detection_source == "quick_incident_ui",
                    Incident.detected_at >= cutoff_time,
                    Incident.status != IncidentStatus.RESOLVED
                ).order_by(Incident.detected_at.asc())

                recent_sims = await db.execute(recent_sims_query)
                recent_incidents = recent_sims.scalars().all()

                # Progress incidents through realistic lifecycle
                # IMPORTANT: We do NOT auto-approve - that would be dangerous!
                # Only progress incidents that have already been manually approved
                for idx, incident in enumerate(recent_incidents):
                    age_minutes = (datetime.now(timezone.utc) - incident.detected_at).total_seconds() / 60

                    # Realistic progression - no auto-approval!
                    if age_minutes > 120 and incident.status == IncidentStatus.PENDING_APPROVAL:
                        # After 2 hours without approval, escalate (realistic behavior)
                        incident.status = IncidentStatus.ESCALATED
                        logger.info(f"Escalated incident {incident.id} (unaddressed for {age_minutes:.0f}min)")
                    elif age_minutes > 30 and incident.status == IncidentStatus.APPROVED:
                        # If approved, simulate execution after 30 minutes
                        incident.status = IncidentStatus.EXECUTING
                        logger.info(f"Progressed incident {incident.id} to EXECUTING (age: {age_minutes:.0f}min)")
                    elif age_minutes > 15 and incident.status == IncidentStatus.EXECUTING:
                        # After 15 min of execution, mark as resolved (demo only)
                        incident.status = IncidentStatus.RESOLVED
                        incident.resolved_at = datetime.now(timezone.utc)
                        incident.resolution_summary = "Demo: Simulated successful resolution"
                        logger.info(f"Resolved incident {incident.id} (execution complete)")

                await db.commit()
                logger.info(f"Progressed {len(recent_incidents)} recent simulation incidents through lifecycle")

                # Step 3: Create new simulation incidents if needed (keep 3-5 active)
                active_count = len([i for i in recent_incidents if i.status != IncidentStatus.RESOLVED])

                if active_count < 3:
                    # All 5 available scenarios
                    all_scenarios = [
                        "memory_leak_gradual",
                        "cpu_spike_traffic_surge",
                        "latency_spike_database",
                        "pod_crash_loop",
                        "dependency_failure_timeout"
                    ]

                    # Rotate through scenarios - use hash of current hour to pick different ones
                    from hashlib import md5
                    current_hour_seed = int(datetime.utcnow().strftime("%Y%m%d%H"))
                    rotation_index = current_hour_seed % len(all_scenarios)

                    # Select 3 scenarios starting from rotation index
                    scenarios_to_create = [
                        all_scenarios[(rotation_index + i) % len(all_scenarios)]
                        for i in range(3 - active_count)
                    ]

                    logger.info(f"Creating {len(scenarios_to_create)} static demo incidents (rotation index: {rotation_index})")

                    for scenario_id in scenarios_to_create:
                        try:
                            result = await runner.run_scenario(
                                scenario_id=scenario_id,
                                db=db,
                                auto_analyze=True,
                                execution_mode="demo",
                            )
                            logger.info(f"Created STATIC demo incident: {result.incident_id} from scenario {scenario_id}")
                        except Exception as e:
                            logger.warning(f"Failed to create demo incident for {scenario_id}: {str(e)}")
                else:
                    logger.info(f"Sufficient active incidents ({active_count}), skipping creation")

            logger.info("Demo incident management complete")
        except Exception as e:
            logger.warning(f"Failed to manage demo incidents (non-fatal): {str(e)}", exc_info=True)

    logger.info("AIRRA Backend started successfully")

    yield

    # Shutdown
    logger.info("Shutting down AIRRA Backend...")
    from app.services.anomaly_monitor import stop_anomaly_monitor
    await stop_anomaly_monitor()

    # Stop AI incident generator
    if settings.environment == "development":
        from app.services.ai_incident_generator import stop_ai_generator
        await stop_ai_generator()

    # Close LLM cache Redis connection
    from app.services.llm_client import llm_cache
    await llm_cache.close()

    # Close Prometheus HTTP client
    from app.services.prometheus_client import close_prometheus_client
    await close_prometheus_client()

    await close_db()
    logger.info("AIRRA Backend shutdown complete")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Autonomous Incident Response & Reliability Agent",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)

# Add security middleware (order matters - added first, executed last)
# Security headers on all responses
app.add_middleware(SecurityHeadersMiddleware)

# HTTPS redirect in production only
if settings.environment == "production":
    app.add_middleware(HTTPSRedirectMiddleware)

    # Trusted host middleware to prevent host header attacks
    # Extract hostnames from CORS origins (TrustedHostMiddleware expects hostnames, not full URLs)
    allowed_hosts = []
    for origin in settings.cors_origins:
        try:
            parsed = urlparse(origin)
            # Get hostname with port if present (e.g., "localhost:3000")
            host = parsed.netloc if parsed.netloc else parsed.hostname
            if host:
                allowed_hosts.append(host)
        except Exception as e:
            logger.warning(f"Failed to parse CORS origin '{origin}': {e}")

    if allowed_hosts:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=allowed_hosts,
        )
    else:
        logger.warning("No valid hostnames extracted from CORS origins for TrustedHostMiddleware")

# CORS middleware with restricted methods and headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],  # Specific methods only
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],  # Specific headers
    max_age=3600,  # Cache preflight requests for 1 hour
)


# Health check endpoint
@app.get("/health", tags=["System"])
async def health_check():
    """
    Health check endpoint for monitoring and load balancers.

    Returns service status and version.
    """
    return JSONResponse(
        content={
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
        }
    )


# Root endpoint
@app.get("/", tags=["System"])
async def root():
    """Root endpoint with API information."""
    return {
        "service": settings.app_name,
        "version": settings.app_version,
        "docs": "/docs" if settings.debug else "Documentation disabled in production",
        "health": "/health",
    }


# Import and include API routers
from app.api.v1 import (  # noqa: E402
    incidents,
    actions,
    approvals,
    learning,
    quick_incident,
    simulator,
    on_call,
    notifications,
    analytics,
    postmortems,
)
from app.api.v1.admin import engineers, reviews  # noqa: E402
from app.api.dependencies import verify_api_key  # noqa: E402

app.include_router(
    incidents.router,
    prefix=f"{settings.api_v1_prefix}/incidents",
    tags=["Incidents"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    actions.router,
    prefix=f"{settings.api_v1_prefix}/actions",
    tags=["Actions"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    approvals.router,
    prefix=f"{settings.api_v1_prefix}/approvals",
    tags=["Approvals"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    learning.router,
    prefix=f"{settings.api_v1_prefix}/learning",
    tags=["Learning & Feedback"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    quick_incident.router,
    prefix=f"{settings.api_v1_prefix}",
    tags=["Quick Actions"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    simulator.router,
    prefix=f"{settings.api_v1_prefix}/simulator",
    tags=["Incident Simulator"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    engineers.router,
    prefix=f"{settings.api_v1_prefix}/admin/engineers",
    tags=["Admin - Engineers"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    reviews.router,
    prefix=f"{settings.api_v1_prefix}/admin",
    tags=["Admin - Reviews"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    on_call.router,
    prefix=f"{settings.api_v1_prefix}/on-call",
    tags=["On-Call Management"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    notifications.router,
    prefix=f"{settings.api_v1_prefix}/notifications",
    tags=["Notifications"],
    # Note: /acknowledge endpoint has no auth requirement (token-based)
)

app.include_router(
    analytics.router,
    prefix=f"{settings.api_v1_prefix}",
    tags=["Analytics"],
    dependencies=[Depends(verify_api_key)],
)

app.include_router(
    postmortems.router,
    prefix=f"{settings.api_v1_prefix}",
    tags=["Postmortems & Timeline"],
    dependencies=[Depends(verify_api_key)],
)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler for unhandled exceptions."""
    logger.error(
        "Unhandled exception",
        extra={
            "path": str(request.url),
            "method": request.method,
            "error": str(exc),
        },
        exc_info=True,
    )

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc) if settings.debug else "An unexpected error occurred",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
