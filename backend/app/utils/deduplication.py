"""
Thread-Safe Incident Deduplication

Prevents duplicate incidents from being created for the same issue
using database-level locks and fingerprinting.

Features:
- Exact matching via SHA-256 fingerprints
- Fuzzy matching with normalized text and token-based similarity
- Severity-based time windows
- Thread-safe with row-level locking
"""
import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident, IncidentStatus

logger = logging.getLogger(__name__)

# Severity-based lookback windows (in minutes)
# Critical incidents cluster quickly, while low-severity issues recur over longer periods
SEVERITY_LOOKBACK_WINDOWS = {
    'critical': 15,   # 15 minutes - critical incidents happen in rapid succession
    'high': 30,       # 30 minutes - high priority issues
    'medium': 60,     # 1 hour - medium priority (default)
    'low': 120,       # 2 hours - low priority issues can recur over longer periods
}
DEFAULT_LOOKBACK_MINUTES = 60

# Fuzzy matching configuration
FUZZY_SIMILARITY_THRESHOLD = 0.7  # 70% token overlap required for fuzzy match

# Common word replacements for normalization (handle abbreviations)
WORD_NORMALIZATIONS = {
    'db': 'database',
    'api': 'api',
    'svc': 'service',
    'srv': 'server',
    'conn': 'connection',
    'auth': 'authentication',
    'err': 'error',
    'msg': 'message',
    'req': 'request',
    'resp': 'response',
    'timeout': 'timeout',
    'timed out': 'timeout',
}


def normalize_text(text: str) -> str:
    """
    Normalize text for fuzzy matching.

    - Lowercase
    - Remove punctuation
    - Normalize whitespace
    - Apply word normalizations (db -> database, etc.)

    Args:
        text: Input text

    Returns:
        Normalized text
    """
    # Lowercase and remove extra whitespace
    text = text.lower().strip()

    # Remove punctuation (keep alphanumeric and spaces)
    text = re.sub(r'[^a-z0-9\s]+', ' ', text)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Apply word normalizations
    words = text.split()
    normalized_words = [WORD_NORMALIZATIONS.get(word, word) for word in words]

    return ' '.join(normalized_words)


def calculate_token_similarity(text1: str, text2: str) -> float:
    """
    Calculate similarity between two texts using token overlap (Jaccard similarity).

    Args:
        text1: First text (normalized)
        text2: Second text (normalized)

    Returns:
        Similarity score between 0.0 and 1.0
    """
    tokens1 = set(text1.split())
    tokens2 = set(text2.split())

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2

    return len(intersection) / len(union) if union else 0.0


def generate_incident_fingerprint(
    service: str,
    description: str,
    affected_components: list[str] | None = None,
) -> str:
    """
    Generate a unique fingerprint for an incident based on service and description.

    Uses SHA-256 hash of normalized service + description + components.
    Similar incidents within a time window will have the same fingerprint.

    Args:
        service: Affected service name
        description: Incident description
        affected_components: Optional list of affected components

    Returns:
        32-character hex fingerprint
    """
    # Normalize inputs
    service_norm = service.lower().strip()
    desc_norm = description.lower().strip()
    components_norm = sorted([c.lower().strip() for c in (affected_components or [])])

    # Create fingerprint string
    fingerprint_str = f"{service_norm}|{desc_norm}|{','.join(components_norm)}"

    # Generate SHA-256 hash
    return hashlib.sha256(fingerprint_str.encode('utf-8')).hexdigest()[:32]


def is_fuzzy_match(
    service1: str,
    desc1: str,
    components1: list[str] | None,
    service2: str,
    desc2: str,
    components2: list[str] | None,
) -> bool:
    """
    Check if two incidents are fuzzy matches (similar but not exact).

    Uses normalized text comparison with token-based similarity.

    Args:
        service1, desc1, components1: First incident
        service2, desc2, components2: Second incident

    Returns:
        True if incidents are similar enough to be considered duplicates
    """
    # Service must match (case-insensitive)
    if service1.lower() != service2.lower():
        return False

    # Normalize descriptions
    desc1_norm = normalize_text(desc1)
    desc2_norm = normalize_text(desc2)

    # Calculate similarity
    similarity = calculate_token_similarity(desc1_norm, desc2_norm)

    if similarity >= FUZZY_SIMILARITY_THRESHOLD:
        logger.debug(f"Fuzzy match found: similarity={similarity:.2f} (threshold={FUZZY_SIMILARITY_THRESHOLD})")
        return True

    return False


async def find_duplicate_incident(
    db: AsyncSession,
    service: str,
    description: str,
    severity: str | None = None,
    affected_components: list[str] | None = None,
    lookback_minutes: int | None = None,
) -> Optional[Incident]:
    """
    Find duplicate incident using fingerprint matching within a time window.

    Thread-safe implementation using SELECT FOR UPDATE to prevent race conditions.

    Args:
        db: Database session
        service: Service name
        description: Incident description
        severity: Incident severity (used for dynamic lookback window)
        affected_components: Affected components
        lookback_minutes: Override lookback window (if None, uses severity-based window)

    Returns:
        Existing incident if duplicate found, None otherwise

    Note:
        Severity-based lookback windows:
        - critical: 15 minutes (rapid clustering)
        - high: 30 minutes
        - medium: 60 minutes (default)
        - low: 120 minutes (longer recurrence patterns)
    """
    fingerprint = generate_incident_fingerprint(service, description, affected_components)

    # Determine lookback window based on severity
    if lookback_minutes is None:
        lookback_minutes = SEVERITY_LOOKBACK_WINDOWS.get(
            severity.lower() if severity else 'medium',
            DEFAULT_LOOKBACK_MINUTES
        )
        logger.debug(f"Using severity-based lookback: {lookback_minutes}min for severity={severity}")

    # Calculate time window
    cutoff_time = datetime.utcnow() - timedelta(minutes=lookback_minutes)

    # Search for existing incidents with same fingerprint
    # Use FOR UPDATE to lock the row and prevent concurrent duplicate creation
    stmt = (
        select(Incident)
        .where(
            Incident.affected_service == service,
            Incident.detected_at >= cutoff_time,
            Incident.status.in_([
                IncidentStatus.DETECTED,
                IncidentStatus.ANALYZING,
                IncidentStatus.PENDING_APPROVAL,
                IncidentStatus.APPROVED,
                IncidentStatus.EXECUTING,
            ])  # Don't dedupe resolved/failed/escalated incidents
        )
        .with_for_update()  # Row-level lock for thread safety
        .order_by(Incident.detected_at.desc())
        .limit(1)
    )

    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Verify fingerprint match (additional safety check)
        existing_fingerprint = generate_incident_fingerprint(
            existing.affected_service,
            existing.description,
            existing.affected_components,
        )

        if existing_fingerprint == fingerprint:
            logger.info(
                f"Found exact duplicate incident: {existing.id} (fingerprint: {fingerprint})"
            )
            return existing

    # No exact match found - try fuzzy matching
    # Get all recent incidents for the same service (without row lock for fuzzy search)
    fuzzy_stmt = (
        select(Incident)
        .where(
            Incident.affected_service == service,
            Incident.detected_at >= cutoff_time,
            Incident.status.in_([
                IncidentStatus.DETECTED,
                IncidentStatus.ANALYZING,
                IncidentStatus.PENDING_APPROVAL,
                IncidentStatus.APPROVED,
                IncidentStatus.EXECUTING,
            ])
        )
        .order_by(Incident.detected_at.desc())
        .limit(10)  # Check last 10 incidents for fuzzy match
    )

    fuzzy_result = await db.execute(fuzzy_stmt)
    recent_incidents = fuzzy_result.scalars().all()

    for candidate in recent_incidents:
        if is_fuzzy_match(
            service, description, affected_components,
            candidate.affected_service, candidate.description, candidate.affected_components
        ):
            logger.info(
                f"Found fuzzy duplicate incident: {candidate.id} "
                f"('{description[:50]}...' ~ '{candidate.description[:50]}...')"
            )
            # Lock the row now that we found a match
            lock_stmt = (
                select(Incident)
                .where(Incident.id == candidate.id)
                .with_for_update()
            )
            lock_result = await db.execute(lock_stmt)
            locked_incident = lock_result.scalar_one_or_none()
            return locked_incident

    return None


async def create_or_update_incident(
    db: AsyncSession,
    service: str,
    title: str,
    description: str,
    severity: str,
    affected_components: list[str] | None = None,
    metrics_snapshot: dict | None = None,
    context: dict | None = None,
    lookback_minutes: int = 60,
    auto_commit: bool = True,
) -> tuple[Incident, bool]:
    """
    Create a new incident or update existing duplicate (thread-safe).

    Args:
        db: Database session
        service: Service name
        title: Incident title
        description: Incident description
        severity: Severity level
        affected_components: Optional list of affected components
        metrics_snapshot: Optional metrics data
        context: Optional context data
        lookback_minutes: Time window for deduplication
        auto_commit: If True, commits immediately. If False, caller must commit.

    Returns:
        Tuple of (incident, created) where created=True if new incident was created

    Example:
        # With auto-commit (default):
        incident, created = await create_or_update_incident(
            db=db,
            service="payment-service",
            title="High Error Rate",
            description="500 errors spiking",
            severity="high",
        )

        # Without auto-commit (caller manages transaction):
        incident, created = await create_or_update_incident(
            db=db, service="api", title="Timeout", description="...",
            severity="high", auto_commit=False
        )
        await db.commit()  # Caller commits explicitly

    Note:
        When auto_commit=False, the incident will be added to the session
        but not committed. Caller must handle commit/rollback.
    """
    # Check for duplicates within time window (with row lock)
    # Severity-based lookback: critical=15min, high=30min, medium=60min, low=120min
    duplicate = await find_duplicate_incident(
        db=db,
        service=service,
        description=description,
        severity=severity,
        affected_components=affected_components,
        lookback_minutes=lookback_minutes,
    )

    if duplicate:
        # Update existing incident instead of creating new one
        logger.info(f"Deduplicating: updating existing incident {duplicate.id}")

        # Update metrics snapshot (merge with existing)
        if metrics_snapshot:
            existing_metrics = duplicate.metrics_snapshot or {}
            existing_metrics.update(metrics_snapshot)
            duplicate.metrics_snapshot = existing_metrics

        # Update context (merge with existing)
        if context:
            existing_context = duplicate.context or {}
            existing_context.update(context)
            existing_context['duplicate_count'] = existing_context.get('duplicate_count', 0) + 1
            existing_context['last_duplicate_at'] = datetime.utcnow().isoformat()
            duplicate.context = existing_context

        # Update severity if new one is higher
        severity_order = {'low': 1, 'medium': 2, 'high': 3, 'critical': 4}
        if severity_order.get(severity, 0) > severity_order.get(duplicate.severity.value, 0):
            logger.info(f"Escalating severity from {duplicate.severity} to {severity}")
            duplicate.severity = severity

        # Flush changes to database (get ID if needed) but don't commit yet
        await db.flush()

        if auto_commit:
            try:
                await db.commit()
                await db.refresh(duplicate)
            except Exception as e:
                await db.rollback()
                logger.error(f"Failed to commit incident update: {e}", exc_info=True)
                raise

        return duplicate, False  # Not created, updated existing

    # No duplicate found - create new incident
    new_incident = Incident(
        title=title,
        description=description,
        severity=severity,
        affected_service=service,
        affected_components=affected_components or [],
        metrics_snapshot=metrics_snapshot or {},
        context=context or {},
        detected_at=datetime.utcnow(),
    )

    db.add(new_incident)

    # Flush to get the incident ID without committing
    await db.flush()

    if auto_commit:
        try:
            await db.commit()
            await db.refresh(new_incident)
        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to commit new incident: {e}", exc_info=True)
            raise

    logger.info(f"Created new incident {new_incident.id} (no duplicates found)")

    return new_incident, True  # Created new incident
