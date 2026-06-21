"""
Cross-incident correlation service.

When 3+ incidents appear within a 5-minute window across services that share a
common upstream dependency, they are grouped under a shared correlation_group_id.
This lets operators recognise a single blast-radius event (e.g. shared DB outage)
rather than triaging each affected service as an isolated problem.

Grouping logic:
  1. Find the upstream dependencies of the newly-created incident's service.
  2. Query for recent active incidents (last 5 min, not RESOLVED/FAILED) whose
     service also depends on any of those same upstreams.
  3. If any of those incidents already carry a correlation_group_id, join that
     group.  Otherwise, if total count (including the new one) reaches the
     threshold (≥ CORRELATION_THRESHOLD), mint a new group UUID and stamp all.
"""
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident import Incident, IncidentStatus

logger = logging.getLogger(__name__)

# Minimum number of related incidents before a correlation group is created.
CORRELATION_THRESHOLD = 3
# How far back to look for related incidents (seconds).
CORRELATION_WINDOW_SECONDS = 300

# Statuses that are "active" — resolved/failed incidents are excluded.
_INACTIVE_STATUSES = {IncidentStatus.RESOLVED, IncidentStatus.FAILED}


class CorrelationService:
    """Groups incidents that share a common upstream dependency."""

    def __init__(self) -> None:
        from app.services.dependency_graph import get_dependency_graph
        self._dep_graph = get_dependency_graph()

    async def correlate(
        self,
        new_incident: Incident,
        db: AsyncSession,
    ) -> UUID | None:
        """
        Attempt to assign a correlation_group_id to *new_incident*.

        Mutates new_incident.correlation_group_id in-place and persists all
        affected rows.  Returns the group UUID, or None if no group was formed.
        """
        service = new_incident.affected_service
        shared_upstreams = self._shared_upstreams_for(service)

        if not shared_upstreams:
            return None

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=CORRELATION_WINDOW_SECONDS)

        # Fetch recent active incidents for services sharing any upstream with ours.
        stmt = (
            select(Incident)
            .where(
                Incident.id != new_incident.id,
                Incident.detected_at >= cutoff,
                Incident.status.not_in(list(_INACTIVE_STATUSES)),
            )
            .order_by(Incident.detected_at.desc())
        )
        result = await db.execute(stmt)
        candidates: list[Incident] = list(result.scalars().all())

        # Keep only those whose service shares at least one upstream with ours.
        related = [
            c for c in candidates
            if self._shares_upstream(c.affected_service, shared_upstreams)
        ]

        if not related:
            return None

        # Prefer an existing group over minting a new one.
        existing_group_id: UUID | None = next(
            (c.correlation_group_id for c in related if c.correlation_group_id),
            None,
        )

        total = len(related) + 1  # +1 for new_incident
        if existing_group_id is None and total < CORRELATION_THRESHOLD:
            return None

        group_id = existing_group_id or uuid4()

        # Stamp all ungrouped related incidents.
        for incident in related:
            if incident.correlation_group_id is None:
                incident.correlation_group_id = group_id

        new_incident.correlation_group_id = group_id
        await db.flush()

        logger.info(
            "Correlated incident %s into group %s "
            "(shared upstreams: %s, group size: %d)",
            new_incident.id,
            group_id,
            ", ".join(sorted(shared_upstreams)),
            total,
        )
        return group_id

    def _shared_upstreams_for(self, service: str) -> set[str]:
        """Return the set of upstream dependencies for *service*."""
        try:
            return set(self._dep_graph.get_upstream_dependencies(service))
        except Exception as exc:
            logger.debug("Upstream lookup failed for %s: %s", service, exc)
            return set()

    def _shares_upstream(self, other_service: str, upstreams: set[str]) -> bool:
        """Return True if *other_service* depends on any service in *upstreams*."""
        try:
            other_upstreams = set(
                self._dep_graph.get_upstream_dependencies(other_service)
            )
            return bool(upstreams & other_upstreams)
        except Exception:
            return False


_correlation_service: CorrelationService | None = None


def get_correlation_service() -> CorrelationService:
    global _correlation_service
    if _correlation_service is None:
        _correlation_service = CorrelationService()
    return _correlation_service
