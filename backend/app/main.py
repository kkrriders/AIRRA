"""
AIRRA FastAPI Application.

Senior Engineering Note:
- Lifespan context for startup/shutdown
- CORS middleware for frontend integration
- Structured logging
- Health check endpoint
- API versioning
"""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger

from app.config import settings
from app.database import close_db, init_db

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan handler for startup and shutdown.

    Senior Engineering Note:
    This replaces the deprecated @app.on_event decorators.
    """
    # Startup
    logger.info("Starting AIRRA Backend API", extra={"version": settings.app_version})

    # Initialize database (create tables)
    # In production, use Alembic migrations instead
    if settings.environment == "development":
        logger.info("Initializing database...")
        await init_db()

    # Start background anomaly monitor
    from app.services.anomaly_monitor import start_anomaly_monitor
    logger.info("Starting anomaly detection monitor...")
    await start_anomaly_monitor()

    logger.info("AIRRA Backend started successfully")

    yield

    # Shutdown
    logger.info("Shutting down AIRRA Backend...")
    from app.services.anomaly_monitor import stop_anomaly_monitor
    await stop_anomaly_monitor()

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

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
from app.api.v1 import incidents, actions, approvals, learning, quick_incident, simulator  # noqa: E402
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
