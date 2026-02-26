"""
Incident Assignment Service.

Intelligent assignment of incidents to engineers using multiple strategies:
1. On-call engineer lookup (industry standard)
2. Load-balanced assignment (least busy engineer)
3. Expertise-based matching (future enhancement)

Senior Engineering Note:
- Updates engineer.current_review_count automatically
- Logs assignment events for audit trail
- Handles edge cases (no engineers available, all at capacity)
- Thread-safe with database transactions
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engineer import Engineer, EngineerStatus
from app.models.incident import Incident, IncidentSeverity
from app.models.incident_event import IncidentEventType
from app.models.notification import NotificationChannel, NotificationPriority
from app.services.event_logger import event_logger
from app.services.on_call_finder import on_call_finder

logger = logging.getLogger(__name__)


class AssignmentStrategy:
    """Strategy for selecting which engineer to assign."""

    ON_CALL = "on_call"  # Assign to current on-call engineer
    LOAD_BALANCED = "load_balanced"  # Assign to least busy engineer
    MANUAL = "manual"  # Manual assignment by ID


class AssignmentResult:
    """Result of assignment operation."""

    def __init__(
        self,
        success: bool,
        engineer: Optional[Engineer] = None,
        strategy: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        self.success = success
        self.engineer = engineer
        self.strategy = strategy
        self.reason = reason

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "success": self.success,
            "engineer": self.engineer.to_dict() if self.engineer else None,
            "strategy": self.strategy,
            "reason": self.reason,
        }


class IncidentAssigner:
    """Service for assigning incidents to engineers."""

    async def auto_assign(
        self,
        db: AsyncSession,
        incident: Incident,
        strategy: str = AssignmentStrategy.ON_CALL,
    ) -> AssignmentResult:
        """
        Auto-assign incident to an engineer using specified strategy.

        Args:
            db: Database session
            incident: Incident to assign
            strategy: Assignment strategy to use

        Returns:
            AssignmentResult with assignment details
        """
        if incident.assigned_engineer_id:
            return AssignmentResult(
                success=False,
                reason=f"Incident already assigned to engineer {incident.assigned_engineer_id}",
            )

        # Strategy 1: Try on-call engineer first
        if strategy == AssignmentStrategy.ON_CALL:
            result = await self._assign_to_on_call(db, incident)
            if result.success:
                return result

            # Fallback to load-balanced if no on-call engineer
            logger.info(
                f"No on-call engineer for incident {incident.id}, falling back to load-balanced"
            )
            strategy = AssignmentStrategy.LOAD_BALANCED

        # Strategy 2: Load-balanced assignment
        if strategy == AssignmentStrategy.LOAD_BALANCED:
            result = await self._assign_load_balanced(db, incident)
            if result.success:
                return result

        # No engineers available
        return AssignmentResult(
            success=False,
            reason="No available engineers found",
        )

    async def _assign_to_on_call(
        self,
        db: AsyncSession,
        incident: Incident,
    ) -> AssignmentResult:
        """Assign to current on-call engineer for the affected service."""
        on_call_result = await on_call_finder.find_on_call_engineer(
            db,
            service=incident.affected_service,
            team=None,
            at_time=datetime.now(timezone.utc),
        )

        if not on_call_result:
            return AssignmentResult(
                success=False,
                reason=f"No on-call engineer found for service {incident.affected_service}",
            )

        engineer = on_call_result.engineer

        # Check if engineer can accept review
        if not engineer.can_accept_review():
            return AssignmentResult(
                success=False,
                reason=f"On-call engineer {engineer.name} is at capacity or unavailable",
            )

        # Assign
        await self._assign_engineer(db, incident, engineer, AssignmentStrategy.ON_CALL)

        logger.info(
            f"Assigned incident {incident.id} to on-call engineer {engineer.name} ({engineer.email})"
        )

        return AssignmentResult(
            success=True,
            engineer=engineer,
            strategy=AssignmentStrategy.ON_CALL,
            reason=f"Assigned to on-call engineer for {incident.affected_service}",
        )

    async def _assign_load_balanced(
        self,
        db: AsyncSession,
        incident: Incident,
    ) -> AssignmentResult:
        """Assign to least busy available engineer."""
        # Find all available engineers
        stmt = (
            select(Engineer)
            .where(
                Engineer.is_available == True,  # noqa: E712
                Engineer.status == EngineerStatus.ACTIVE,
            )
            .order_by(Engineer.current_review_count.asc())  # Least busy first
        )

        result = await db.execute(stmt)
        engineers = result.scalars().all()

        # Filter to those who can accept reviews
        available = [e for e in engineers if e.can_accept_review()]

        if not available:
            return AssignmentResult(
                success=False,
                reason="No available engineers (all at capacity or offline)",
            )

        # Assign to least busy
        engineer = available[0]
        await self._assign_engineer(db, incident, engineer, AssignmentStrategy.LOAD_BALANCED)

        logger.info(
            f"Assigned incident {incident.id} to engineer {engineer.name} "
            f"(load-balanced, workload: {engineer.current_review_count}/{engineer.max_concurrent_reviews})"
        )

        return AssignmentResult(
            success=True,
            engineer=engineer,
            strategy=AssignmentStrategy.LOAD_BALANCED,
            reason=f"Assigned to least busy engineer ({engineer.current_review_count} active incidents)",
        )

    async def assign_manual(
        self,
        db: AsyncSession,
        incident: Incident,
        engineer_id: UUID,
        force: bool = False,
    ) -> AssignmentResult:
        """
        Manually assign incident to specific engineer.

        Args:
            db: Database session
            incident: Incident to assign
            engineer_id: Engineer to assign to
            force: If True, allow assignment even if engineer is at capacity

        Returns:
            AssignmentResult
        """
        # Get engineer
        engineer = await db.get(Engineer, engineer_id)
        if not engineer:
            return AssignmentResult(
                success=False,
                reason=f"Engineer {engineer_id} not found",
            )

        # Check if can accept (unless forced)
        if not force and not engineer.can_accept_review():
            return AssignmentResult(
                success=False,
                engineer=engineer,
                reason=f"Engineer {engineer.name} cannot accept review (status: {engineer.status.value}, workload: {engineer.current_review_count}/{engineer.max_concurrent_reviews})",
            )

        # Unassign current engineer if reassignment
        if incident.assigned_engineer_id:
            await self._unassign_engineer(db, incident)

        # Assign new engineer
        await self._assign_engineer(db, incident, engineer, AssignmentStrategy.MANUAL)

        logger.info(
            f"Manually assigned incident {incident.id} to engineer {engineer.name} (force={force})"
        )

        return AssignmentResult(
            success=True,
            engineer=engineer,
            strategy=AssignmentStrategy.MANUAL,
            reason="Manual assignment",
        )

    async def unassign(
        self,
        db: AsyncSession,
        incident: Incident,
    ) -> AssignmentResult:
        """
        Unassign engineer from incident.

        Args:
            db: Database session
            incident: Incident to unassign

        Returns:
            AssignmentResult
        """
        if not incident.assigned_engineer_id:
            return AssignmentResult(
                success=False,
                reason="Incident not currently assigned",
            )

        # Get current engineer for logging
        engineer = await db.get(Engineer, incident.assigned_engineer_id)
        engineer_name = engineer.name if engineer else str(incident.assigned_engineer_id)

        await self._unassign_engineer(db, incident)

        logger.info(f"Unassigned engineer {engineer_name} from incident {incident.id}")

        return AssignmentResult(
            success=True,
            reason=f"Unassigned {engineer_name}",
        )

    async def _assign_engineer(
        self,
        db: AsyncSession,
        incident: Incident,
        engineer: Engineer,
        strategy: str,
    ):
        """Internal: Perform assignment and update counts."""
        # Update incident
        incident.assigned_engineer_id = engineer.id

        # Update engineer workload
        engineer.current_review_count += 1

        # Log event
        await event_logger.log(
            db=db,
            incident_id=incident.id,
            event_type=IncidentEventType.ENGINEER_ASSIGNED,
            description=f"Assigned to {engineer.name} ({engineer.email}) via {strategy} strategy",
            actor="system",
            metadata={
                "engineer_id": str(engineer.id),
                "engineer_name": engineer.name,
                "strategy": strategy,
                "engineer_workload": f"{engineer.current_review_count}/{engineer.max_concurrent_reviews}",
            },
        )

        await db.flush()

        # Send notification to engineer
        await self._send_assignment_notification(db, incident, engineer)

    async def _send_assignment_notification(
        self,
        db: AsyncSession,
        incident: Incident,
        engineer: Engineer,
    ):
        """Send notification to engineer about assignment."""
        try:
            # Import here to avoid circular dependency
            from app.services.notification_service import notification_service

            # Determine priority based on incident severity
            priority_map = {
                IncidentSeverity.CRITICAL: NotificationPriority.CRITICAL,
                IncidentSeverity.HIGH: NotificationPriority.HIGH,
                IncidentSeverity.MEDIUM: NotificationPriority.NORMAL,
                IncidentSeverity.LOW: NotificationPriority.LOW,
            }
            priority = priority_map.get(incident.severity, NotificationPriority.NORMAL)

            # Send email notification
            await notification_service.send_incident_notification(
                db=db,
                engineer_id=engineer.id,
                incident_id=incident.id,
                channel=NotificationChannel.EMAIL,
                priority=priority,
            )

            # Log notification event
            await event_logger.log(
                db=db,
                incident_id=incident.id,
                event_type=IncidentEventType.ENGINEER_NOTIFIED,
                description=f"Sent {priority.value} priority email notification to {engineer.name}",
                actor="system",
                metadata={
                    "engineer_id": str(engineer.id),
                    "notification_channel": "email",
                    "priority": priority.value,
                },
            )

            logger.info(
                f"Sent assignment notification to {engineer.name} for incident {incident.id}"
            )

        except Exception as e:
            # Don't fail assignment if notification fails
            logger.error(
                f"Failed to send assignment notification: {e}",
                exc_info=True,
            )

    async def _unassign_engineer(
        self,
        db: AsyncSession,
        incident: Incident,
    ):
        """Internal: Perform unassignment and update counts."""
        if not incident.assigned_engineer_id:
            return

        # Get engineer and decrement count
        engineer = await db.get(Engineer, incident.assigned_engineer_id)
        if engineer and engineer.current_review_count > 0:
            engineer.current_review_count -= 1

        engineer_name = engineer.name if engineer else "Unknown"

        # Log event
        await event_logger.log(
            db=db,
            incident_id=incident.id,
            event_type=IncidentEventType.ENGINEER_UNASSIGNED,
            description=f"Unassigned {engineer_name}",
            actor="system",
            metadata={
                "engineer_id": str(incident.assigned_engineer_id) if incident.assigned_engineer_id else None,
                "engineer_name": engineer_name,
            },
        )

        # Clear assignment
        incident.assigned_engineer_id = None

        await db.flush()


# Global instance
incident_assigner = IncidentAssigner()
