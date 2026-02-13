"""
On-call finder service for determining which engineer is on-call.

Senior Engineering Note:
- Time-aware lookups (who's on-call NOW)
- Service/team-specific matching
- Priority-based escalation chain
- Integration with engineer availability
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.engineer import Engineer, EngineerStatus
from app.models.on_call_schedule import OnCallSchedule, OnCallPriority

logger = logging.getLogger(__name__)


class OnCallResult:
    """Result of on-call lookup with engineer and schedule details."""

    def __init__(
        self,
        engineer: Engineer,
        schedule: OnCallSchedule,
        priority: OnCallPriority,
    ):
        self.engineer = engineer
        self.schedule = schedule
        self.priority = priority

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses."""
        return {
            "engineer": self.engineer.to_dict(),
            "schedule": self.schedule.to_dict(),
            "priority": self.priority.value,
        }


class OnCallFinder:
    """Service for finding on-call engineers."""

    async def find_on_call_engineer(
        self,
        db: AsyncSession,
        service: Optional[str] = None,
        team: Optional[str] = None,
        at_time: Optional[datetime] = None,
        priority: Optional[OnCallPriority] = None,
    ) -> Optional[OnCallResult]:
        """
        Find the on-call engineer for given criteria.

        Args:
            db: Database session
            service: Service name (e.g., 'payment-service')
            team: Team name (e.g., 'backend')
            at_time: Time to check (defaults to now)
            priority: Specific priority level (defaults to PRIMARY)

        Returns:
            OnCallResult with engineer and schedule, or None if no match
        """
        check_time = at_time or datetime.utcnow()
        target_priority = priority or OnCallPriority.PRIMARY

        # Build query for active on-call schedules
        stmt = (
            select(OnCallSchedule)
            .options(selectinload(OnCallSchedule.engineer))
            .where(
                and_(
                    OnCallSchedule.is_active == True,  # noqa: E712
                    OnCallSchedule.start_time <= check_time,
                    OnCallSchedule.end_time >= check_time,
                    OnCallSchedule.priority == target_priority,
                )
            )
        )

        # Filter by service (NULL service matches all services)
        if service:
            stmt = stmt.where(
                or_(
                    OnCallSchedule.service == service,
                    OnCallSchedule.service.is_(None),
                )
            )

        # Filter by team (NULL team matches all teams)
        if team:
            stmt = stmt.where(
                or_(
                    OnCallSchedule.team == team,
                    OnCallSchedule.team.is_(None),
                )
            )

        # Order by specificity (service-specific > team-specific > general)
        stmt = stmt.order_by(
            OnCallSchedule.service.is_not(None).desc(),  # Service-specific first
            OnCallSchedule.team.is_not(None).desc(),  # Then team-specific
            OnCallSchedule.start_time.desc(),  # Then newest schedule
        )

        result = await db.execute(stmt)
        schedule = result.scalar_one_or_none()

        if not schedule:
            logger.info(
                f"No on-call engineer found for service={service}, team={team}, "
                f"priority={target_priority.value}"
            )
            return None

        # Check if engineer is actually available
        engineer = schedule.engineer
        if not engineer.can_accept_review():
            logger.warning(
                f"On-call engineer {engineer.id} ({engineer.name}) is not available. "
                f"Status: {engineer.status.value}, "
                f"Workload: {engineer.current_review_count}/{engineer.max_concurrent_reviews}"
            )
            # Try to find backup (next priority level)
            if target_priority == OnCallPriority.PRIMARY:
                return await self.find_on_call_engineer(
                    db,
                    service,
                    team,
                    at_time,
                    OnCallPriority.SECONDARY,
                )
            elif target_priority == OnCallPriority.SECONDARY:
                return await self.find_on_call_engineer(
                    db,
                    service,
                    team,
                    at_time,
                    OnCallPriority.TERTIARY,
                )
            else:
                logger.error("All on-call engineers are unavailable (up to tertiary)")
                return None

        logger.info(
            f"Found on-call engineer: {engineer.name} ({engineer.email}) "
            f"for service={service}, team={team}, priority={target_priority.value}"
        )

        return OnCallResult(engineer, schedule, target_priority)

    async def find_escalation_chain(
        self,
        db: AsyncSession,
        service: Optional[str] = None,
        team: Optional[str] = None,
        at_time: Optional[datetime] = None,
    ) -> list[OnCallResult]:
        """
        Find complete escalation chain (primary → secondary → tertiary).

        Args:
            db: Database session
            service: Service name
            team: Team name
            at_time: Time to check

        Returns:
            List of OnCallResults ordered by priority
        """
        chain = []

        for priority in [
            OnCallPriority.PRIMARY,
            OnCallPriority.SECONDARY,
            OnCallPriority.TERTIARY,
        ]:
            result = await self.find_on_call_engineer(
                db,
                service=service,
                team=team,
                at_time=at_time,
                priority=priority,
            )
            if result:
                chain.append(result)

        logger.info(
            f"Found escalation chain for service={service}, team={team}: "
            f"{len(chain)} engineer(s)"
        )

        return chain

    async def get_all_current_on_call(
        self,
        db: AsyncSession,
        at_time: Optional[datetime] = None,
    ) -> list[OnCallResult]:
        """
        Get all currently on-call engineers across all services.

        Args:
            db: Database session
            at_time: Time to check (defaults to now)

        Returns:
            List of all on-call engineers
        """
        check_time = at_time or datetime.utcnow()

        stmt = (
            select(OnCallSchedule)
            .options(selectinload(OnCallSchedule.engineer))
            .where(
                and_(
                    OnCallSchedule.is_active == True,  # noqa: E712
                    OnCallSchedule.start_time <= check_time,
                    OnCallSchedule.end_time >= check_time,
                )
            )
            .order_by(
                OnCallSchedule.priority,
                OnCallSchedule.service,
            )
        )

        result = await db.execute(stmt)
        schedules = result.scalars().all()

        on_call_results = [
            OnCallResult(schedule.engineer, schedule, schedule.priority)
            for schedule in schedules
        ]

        logger.info(f"Found {len(on_call_results)} currently on-call engineers")

        return on_call_results

    async def check_engineer_on_call(
        self,
        db: AsyncSession,
        engineer_id: UUID,
        at_time: Optional[datetime] = None,
    ) -> list[OnCallSchedule]:
        """
        Check if a specific engineer is on-call.

        Args:
            db: Database session
            engineer_id: Engineer to check
            at_time: Time to check (defaults to now)

        Returns:
            List of active on-call schedules for the engineer
        """
        check_time = at_time or datetime.utcnow()

        stmt = (
            select(OnCallSchedule)
            .where(
                and_(
                    OnCallSchedule.engineer_id == engineer_id,
                    OnCallSchedule.is_active == True,  # noqa: E712
                    OnCallSchedule.start_time <= check_time,
                    OnCallSchedule.end_time >= check_time,
                )
            )
        )

        result = await db.execute(stmt)
        schedules = result.scalars().all()

        return list(schedules)


# Global instance
on_call_finder = OnCallFinder()
