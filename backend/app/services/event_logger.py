"""
Event Logger Service - Track incident lifecycle events.

Simple helper to log events without boilerplate.

Usage:
    await event_logger.log(
        db=db,
        incident_id=incident.id,
        event_type=IncidentEventType.DETECTED,
        description="Incident detected: High error rate in payment-service",
        actor="system"
    )
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.incident_event import IncidentEvent, IncidentEventType

logger = logging.getLogger(__name__)


class EventLogger:
    """Service for logging incident events."""

    async def log(
        self,
        db: AsyncSession,
        incident_id: UUID,
        event_type: IncidentEventType,
        description: str,
        actor: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> IncidentEvent:
        """
        Log an incident event.

        Args:
            db: Database session
            incident_id: Incident UUID
            event_type: Type of event (from IncidentEventType enum)
            description: Human-readable description for timeline
            actor: Who triggered this (e.g., "alice@company.com", "system", "airra-bot")
            metadata: Additional event-specific data

        Returns:
            Created IncidentEvent

        Example:
            await event_logger.log(
                db=db,
                incident_id=incident.id,
                event_type=IncidentEventType.HYPOTHESES_GENERATED,
                description="AI generated 3 hypotheses",
                actor="airra-bot",
                metadata={"count": 3, "top_confidence": 0.87}
            )
        """
        event = IncidentEvent(
            incident_id=incident_id,
            event_type=event_type,
            description=description,
            actor=actor or "system",
            event_metadata=metadata or {},
        )

        db.add(event)
        await db.flush()  # Get the ID without committing

        logger.debug(
            f"Event logged: {event_type.value} for incident {incident_id}",
            extra={"incident_id": str(incident_id), "event_type": event_type.value}
        )

        return event

    # === Convenience methods for common events ===

    async def log_detected(
        self,
        db: AsyncSession,
        incident_id: UUID,
        description: str,
        metadata: Optional[dict] = None
    ):
        """Log incident detection."""
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.DETECTED,
            description=description,
            actor="system",
            metadata=metadata
        )

    async def log_hypotheses_generated(
        self,
        db: AsyncSession,
        incident_id: UUID,
        hypothesis_count: int,
        top_confidence: float
    ):
        """Log hypothesis generation."""
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.HYPOTHESES_GENERATED,
            description=f"AI generated {hypothesis_count} hypotheses (top confidence: {top_confidence:.0%})",
            actor="airra-bot",
            metadata={"count": hypothesis_count, "top_confidence": top_confidence}
        )

    async def log_engineer_assigned(
        self,
        db: AsyncSession,
        incident_id: UUID,
        engineer_name: str,
        engineer_email: str
    ):
        """Log engineer assignment."""
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.ENGINEER_ASSIGNED,
            description=f"Assigned to {engineer_name}",
            actor="system",
            metadata={"engineer_email": engineer_email}
        )

    async def log_action_approved(
        self,
        db: AsyncSession,
        incident_id: UUID,
        action_type: str,
        approver_email: str
    ):
        """Log action approval."""
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.ACTION_APPROVED,
            description=f"Action approved: {action_type}",
            actor=approver_email,
            metadata={"action_type": action_type}
        )

    async def log_action_executed(
        self,
        db: AsyncSession,
        incident_id: UUID,
        action_type: str,
        success: bool,
        details: Optional[dict] = None
    ):
        """Log action execution."""
        status = "completed successfully" if success else "failed"
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.ACTION_COMPLETED if success else IncidentEventType.ACTION_FAILED,
            description=f"Action {status}: {action_type}",
            actor="airra-bot",
            metadata=details or {}
        )

    async def log_verification(
        self,
        db: AsyncSession,
        incident_id: UUID,
        passed: bool,
        metrics: Optional[dict] = None
    ):
        """Log post-action verification."""
        status = "passed" if passed else "failed"
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.VERIFICATION_PASSED if passed else IncidentEventType.VERIFICATION_FAILED,
            description=f"Verification {status}",
            actor="airra-bot",
            metadata=metrics or {}
        )

    async def log_resolved(
        self,
        db: AsyncSession,
        incident_id: UUID,
        resolution_time_minutes: int
    ):
        """Log incident resolution."""
        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.INCIDENT_RESOLVED,
            description=f"Incident resolved (MTTR: {resolution_time_minutes}m)",
            actor="system",
            metadata={"resolution_time_minutes": resolution_time_minutes}
        )

    async def log_comment(
        self,
        db: AsyncSession,
        incident_id: UUID,
        comment: str,
        author_email: str
    ):
        """Log engineer comment."""
        # Truncate long comments for timeline
        preview = comment[:100] + "..." if len(comment) > 100 else comment

        return await self.log(
            db=db,
            incident_id=incident_id,
            event_type=IncidentEventType.COMMENT_ADDED,
            description=f"Comment added: {preview}",
            actor=author_email,
            metadata={"full_comment": comment}
        )


# Global singleton
event_logger = EventLogger()
