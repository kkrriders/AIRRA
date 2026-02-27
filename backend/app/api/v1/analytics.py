"""
Incident Analytics and Reporting API

Provides insights into:
- Incident trends over time
- SLA compliance metrics
- Service reliability scores
- Top affected services
- Mean time to resolution (MTTR)
- Incident severity distribution

Performance Notes:
- Expensive queries use SQL aggregations (GROUP BY, COUNT, AVG)
- Results cached in Redis with 5-minute TTL
- Service names validated with regex to prevent injection
"""
import hashlib
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import verify_api_key
from app.database import get_db
from app.models.incident import Incident, IncidentStatus, IncidentSeverity
from app.models.notification import Notification
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# Service name validation regex (alphanumeric, hyphens, underscores only)
SERVICE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_-]+$')

# Cache TTL for analytics queries (5 minutes)
ANALYTICS_CACHE_TTL = 300

# Reliability Score Calculation Constants
# Formula: reliability_score = 100 - incident_penalty - critical_penalty
# Where incident_penalty = min(total_incidents * INCIDENT_PENALTY_WEIGHT, MAX_INCIDENT_PENALTY)
# And critical_penalty = min(critical_incidents * CRITICAL_PENALTY_WEIGHT, MAX_CRITICAL_PENALTY)
RELIABILITY_BASE_SCORE = 100  # Perfect score with no incidents
INCIDENT_PENALTY_WEIGHT = 2   # Each incident reduces score by 2 points
MAX_INCIDENT_PENALTY = 50     # Maximum penalty from total incidents (25+ incidents)
CRITICAL_PENALTY_WEIGHT = 10  # Each critical incident reduces score by 10 points
MAX_CRITICAL_PENALTY = 30     # Maximum penalty from critical incidents (3+ critical)

router = APIRouter()


async def get_cached_analytics(cache_key: str):
    """
    Get cached analytics result from Redis.

    Returns None if not cached or cache miss.
    """
    try:
        from app.services.llm_client import llm_cache
        cached = await llm_cache.redis_client.get(f"analytics:{cache_key}")
        if cached:
            logger.info(f"Analytics cache HIT for key: {cache_key}")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Failed to get analytics cache: {e}")
    return None


async def set_cached_analytics(cache_key: str, data: dict, ttl: int = ANALYTICS_CACHE_TTL):
    """
    Cache analytics result in Redis with TTL.
    """
    try:
        from app.services.llm_client import llm_cache
        await llm_cache.redis_client.setex(
            f"analytics:{cache_key}",
            ttl,
            json.dumps(data, default=str)  # default=str handles datetime serialization
        )
        logger.info(f"Analytics cached for {ttl}s: {cache_key}")
    except Exception as e:
        logger.warning(f"Failed to cache analytics: {e}")


def validate_service_name(service_name: str) -> str:
    """
    Validate service name to prevent injection attacks.

    Args:
        service_name: Service name to validate

    Returns:
        Validated service name

    Raises:
        HTTPException: If service name contains invalid characters
    """
    if not SERVICE_NAME_PATTERN.match(service_name):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid service name '{service_name}'. "
                   "Only alphanumeric characters, hyphens, and underscores are allowed."
        )
    return service_name


async def log_slow_query(query_name: str, start_time: float, threshold_seconds: float = 1.0):
    """
    Log slow database queries for performance monitoring.

    Args:
        query_name: Name/description of the query
        start_time: Query start time from time.perf_counter()
        threshold_seconds: Log warning if query exceeds this duration (default: 1.0s)
    """
    duration = time.perf_counter() - start_time
    if duration > threshold_seconds:
        logger.warning(
            f"Slow query detected: {query_name}",
            extra={
                "query_name": query_name,
                "duration_seconds": round(duration, 3),
                "threshold": threshold_seconds,
            }
        )
    else:
        logger.debug(f"Query completed: {query_name} ({round(duration, 3)}s)")


# Response Models
class IncidentTrend(BaseModel):
    """Incident count over time."""
    date: str
    count: int
    critical: int
    high: int
    medium: int
    low: int


class ServiceReliability(BaseModel):
    """Service reliability metrics."""
    service: str
    total_incidents: int
    critical_incidents: int
    avg_resolution_time_minutes: Optional[float]
    sla_compliance_rate: Optional[float]
    reliability_score: float  # 0-100, based on incident frequency and severity


class IncidentAnalytics(BaseModel):
    """Overall incident analytics."""
    total_incidents: int
    open_incidents: int
    resolved_incidents: int
    avg_resolution_time_minutes: Optional[float]
    mttr_minutes: Optional[float]  # Mean Time To Resolution
    sla_compliance_rate: Optional[float]

    # Severity distribution
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int

    # Top affected services
    top_services: list[ServiceReliability]

    # Trends
    trends: list[IncidentTrend]


@router.get("/analytics/summary", response_model=IncidentAnalytics)
async def get_analytics_summary(
    days: int = Query(30, ge=1, le=365, description="Number of days to analyze"),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Get comprehensive analytics summary for the specified time period.

    Returns incident counts, resolution times, SLA metrics, and trends.

    Performance:
    - Cached for 5 minutes
    - Uses SQL aggregations for efficiency
    """
    # Check cache first
    cache_key = f"summary:days={days}"
    cached_result = await get_cached_analytics(cache_key)
    if cached_result:
        return IncidentAnalytics(**cached_result)

    # Calculate time window
    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # OPTIMIZED: Use SQL aggregations instead of loading all incidents into memory

    # 1. Get overall counts using SQL COUNT
    total_count_stmt = select(func.count(Incident.id)).where(Incident.detected_at >= start_date)
    total_result = await db.execute(total_count_stmt)
    total_incidents = total_result.scalar() or 0

    # 2. Count open incidents (in-progress statuses, not yet resolved/failed/escalated)
    open_count_stmt = select(func.count(Incident.id)).where(
        and_(
            Incident.detected_at >= start_date,
            Incident.status.in_([
                IncidentStatus.DETECTED,
                IncidentStatus.ANALYZING,
                IncidentStatus.PENDING_APPROVAL,
                IncidentStatus.APPROVED,
                IncidentStatus.EXECUTING
            ])
        )
    )
    open_result = await db.execute(open_count_stmt)
    open_incidents = open_result.scalar() or 0

    # 3. Count resolved incidents
    resolved_count_stmt = select(func.count(Incident.id)).where(
        and_(
            Incident.detected_at >= start_date,
            Incident.status == IncidentStatus.RESOLVED
        )
    )
    resolved_result = await db.execute(resolved_count_stmt)
    resolved_incidents = resolved_result.scalar() or 0

    # 4. Get severity distribution using GROUP BY
    severity_stmt = select(
        Incident.severity,
        func.count(Incident.id).label('count')
    ).where(
        Incident.detected_at >= start_date
    ).group_by(Incident.severity)

    severity_result = await db.execute(severity_stmt)
    severity_rows = severity_result.all()

    severity_counts = {
        IncidentSeverity.CRITICAL: 0,
        IncidentSeverity.HIGH: 0,
        IncidentSeverity.MEDIUM: 0,
        IncidentSeverity.LOW: 0,
    }
    for severity, count in severity_rows:
        severity_counts[severity] = count

    # 5. Calculate average resolution time using SQL AVG
    # EXTRACT(EPOCH FROM ...) converts interval to seconds
    avg_resolution_stmt = select(
        func.avg(
            func.extract('epoch', Incident.resolved_at - Incident.detected_at) / 60.0
        )
    ).where(
        and_(
            Incident.detected_at >= start_date,
            Incident.resolved_at.isnot(None)
        )
    )
    avg_res_result = await db.execute(avg_resolution_stmt)
    avg_resolution_time = avg_res_result.scalar()
    mttr = avg_resolution_time  # MTTR is same as avg resolution time

    # 6. SLA compliance using SQL aggregation
    sla_compliance_stmt = select(
        func.count(Notification.id).label('total'),
        func.sum(func.cast(Notification.sla_met, type_=func.Integer)).label('met')
    ).where(
        and_(
            Notification.created_at >= start_date,
            Notification.sla_met.isnot(None)
        )
    )
    sla_result = await db.execute(sla_compliance_stmt)
    sla_row = sla_result.one_or_none()

    sla_compliance_rate = None
    if sla_row and sla_row.total and sla_row.total > 0:
        sla_compliance_rate = (sla_row.met or 0) / sla_row.total

    # 7. Service statistics using GROUP BY with multiple aggregations
    query_start = time.perf_counter()
    service_stats_stmt = select(
        Incident.affected_service,
        func.count(Incident.id).label('total_incidents'),
        func.sum(
            func.case((Incident.severity == IncidentSeverity.CRITICAL, 1), else_=0)
        ).label('critical_incidents'),
        func.avg(
            func.extract('epoch', Incident.resolved_at - Incident.detected_at) / 60.0
        ).label('avg_resolution_time')
    ).where(
        Incident.detected_at >= start_date
    ).group_by(
        Incident.affected_service
    ).order_by(
        func.count(Incident.id).desc()  # Sort by most incidents
    )

    service_stats_result = await db.execute(service_stats_stmt)
    service_rows = service_stats_result.all()
    await log_slow_query("service_statistics_aggregation", query_start)

    # 8. Get SLA compliance per service using JOIN and GROUP BY
    service_sla_stmt = select(
        Incident.affected_service,
        func.count(Notification.id).label('total'),
        func.sum(func.cast(Notification.sla_met, type_=func.Integer)).label('met')
    ).join(
        Notification, Incident.id == Notification.incident_id
    ).where(
        and_(
            Notification.created_at >= start_date,
            Notification.sla_met.isnot(None)
        )
    ).group_by(
        Incident.affected_service
    )

    service_sla_result = await db.execute(service_sla_stmt)
    service_sla_rows = service_sla_result.all()

    # Create SLA lookup dictionary
    service_sla_map = {}
    for service, total, met in service_sla_rows:
        if total and total > 0:
            service_sla_map[service] = (met or 0) / total

    # 9. Build service reliability list
    top_services = []
    for service, total, critical, avg_res_time in service_rows:
        # Reliability score calculation using constants
        incident_penalty = min((total or 0) * INCIDENT_PENALTY_WEIGHT, MAX_INCIDENT_PENALTY)
        critical_penalty = min((critical or 0) * CRITICAL_PENALTY_WEIGHT, MAX_CRITICAL_PENALTY)
        reliability_score = max(RELIABILITY_BASE_SCORE - incident_penalty - critical_penalty, 0)

        top_services.append(ServiceReliability(
            service=service,
            total_incidents=total or 0,
            critical_incidents=critical or 0,
            avg_resolution_time_minutes=float(avg_res_time) if avg_res_time else None,
            sla_compliance_rate=service_sla_map.get(service),
            reliability_score=reliability_score,
        ))

    # 10. Calculate daily trends using SQL GROUP BY date
    # Use date_trunc to group by day
    trends_stmt = select(
        func.date_trunc('day', Incident.detected_at).label('day'),
        func.count(Incident.id).label('total'),
        func.sum(func.case((Incident.severity == IncidentSeverity.CRITICAL, 1), else_=0)).label('critical'),
        func.sum(func.case((Incident.severity == IncidentSeverity.HIGH, 1), else_=0)).label('high'),
        func.sum(func.case((Incident.severity == IncidentSeverity.MEDIUM, 1), else_=0)).label('medium'),
        func.sum(func.case((Incident.severity == IncidentSeverity.LOW, 1), else_=0)).label('low'),
    ).where(
        Incident.detected_at >= start_date
    ).group_by(
        func.date_trunc('day', Incident.detected_at)
    ).order_by(
        func.date_trunc('day', Incident.detected_at)
    )

    trends_result = await db.execute(trends_stmt)
    trends_rows = trends_result.all()

    # Create a map of date -> counts for quick lookup
    trends_map = {}
    for day, total, critical, high, medium, low in trends_rows:
        date_str = day.strftime('%Y-%m-%d')
        trends_map[date_str] = {
            'count': total or 0,
            'critical': critical or 0,
            'high': high or 0,
            'medium': medium or 0,
            'low': low or 0,
        }

    # Build trends list with zero-filled days (for days with no incidents)
    trends = []
    for day_offset in range(days - 1, -1, -1):
        day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=day_offset)
        date_str = day_start.strftime('%Y-%m-%d')

        day_data = trends_map.get(date_str, {'count': 0, 'critical': 0, 'high': 0, 'medium': 0, 'low': 0})

        trends.append(IncidentTrend(
            date=date_str,
            count=day_data['count'],
            critical=day_data['critical'],
            high=day_data['high'],
            medium=day_data['medium'],
            low=day_data['low'],
        ))

    result = IncidentAnalytics(
        total_incidents=total_incidents,
        open_incidents=open_incidents,
        resolved_incidents=resolved_incidents,
        avg_resolution_time_minutes=avg_resolution_time,
        mttr_minutes=mttr,
        sla_compliance_rate=sla_compliance_rate,
        critical_count=severity_counts[IncidentSeverity.CRITICAL],
        high_count=severity_counts[IncidentSeverity.HIGH],
        medium_count=severity_counts[IncidentSeverity.MEDIUM],
        low_count=severity_counts[IncidentSeverity.LOW],
        top_services=top_services[:10],  # Top 10 services
        trends=trends,
    )

    # Cache the result
    await set_cached_analytics(cache_key, result.model_dump())

    return result


@router.get("/analytics/service/{service_name}", response_model=ServiceReliability)
async def get_service_analytics(
    service_name: str,
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _: str = Depends(verify_api_key),
):
    """
    Get detailed analytics for a specific service.

    Performance:
    - Cached for 5 minutes
    - Service name validated (alphanumeric, hyphens, underscores only)
    - Uses SQL aggregations for efficiency
    """
    # Validate service name to prevent injection
    service_name = validate_service_name(service_name)

    # Check cache first
    cache_key = f"service:{service_name}:days={days}"
    cached_result = await get_cached_analytics(cache_key)
    if cached_result:
        return ServiceReliability(**cached_result)

    start_date = datetime.now(timezone.utc) - timedelta(days=days)

    # OPTIMIZED: Use SQL aggregations instead of loading all incidents
    stats_stmt = select(
        func.count(Incident.id).label('total_incidents'),
        func.sum(
            func.case((Incident.severity == IncidentSeverity.CRITICAL, 1), else_=0)
        ).label('critical_incidents'),
        func.avg(
            func.extract('epoch', Incident.resolved_at - Incident.detected_at) / 60.0
        ).label('avg_resolution_time')
    ).where(
        and_(
            Incident.affected_service == service_name,
            Incident.detected_at >= start_date
        )
    )

    stats_result = await db.execute(stats_stmt)
    stats_row = stats_result.one_or_none()

    if not stats_row or stats_row.total_incidents == 0:
        # No incidents found for this service
        return ServiceReliability(
            service=service_name,
            total_incidents=0,
            critical_incidents=0,
            avg_resolution_time_minutes=None,
            sla_compliance_rate=None,
            reliability_score=100.0,  # Perfect score if no incidents
        )

    total_incidents = stats_row.total_incidents or 0
    critical_incidents = stats_row.critical_incidents or 0
    avg_resolution_time = float(stats_row.avg_resolution_time) if stats_row.avg_resolution_time else None

    # Calculate reliability score using constants
    incident_penalty = min(total_incidents * INCIDENT_PENALTY_WEIGHT, MAX_INCIDENT_PENALTY)
    critical_penalty = min(critical_incidents * CRITICAL_PENALTY_WEIGHT, MAX_CRITICAL_PENALTY)
    reliability_score = max(RELIABILITY_BASE_SCORE - incident_penalty - critical_penalty, 0)

    # Get SLA compliance using SQL aggregation
    sla_stmt = select(
        func.count(Notification.id).label('total'),
        func.sum(func.cast(Notification.sla_met, type_=func.Integer)).label('met')
    ).join(
        Incident, Incident.id == Notification.incident_id
    ).where(
        and_(
            Incident.affected_service == service_name,
            Notification.created_at >= start_date,
            Notification.sla_met.isnot(None)
        )
    )

    sla_result = await db.execute(sla_stmt)
    sla_row = sla_result.one_or_none()

    sla_compliance_rate = None
    if sla_row and sla_row.total and sla_row.total > 0:
        sla_compliance_rate = (sla_row.met or 0) / sla_row.total

    result = ServiceReliability(
        service=service_name,
        total_incidents=total_incidents,
        critical_incidents=critical_incidents,
        avg_resolution_time_minutes=avg_resolution_time,
        sla_compliance_rate=sla_compliance_rate,
        reliability_score=reliability_score,
    )

    # Cache the result
    await set_cached_analytics(cache_key, result.model_dump())

    return result
