"""
Unit tests for app/services/on_call_finder.py

Covers OnCallResult and the DB-driven methods using AsyncMock.
"""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.models.on_call_schedule import OnCallPriority
from app.services.on_call_finder import OnCallFinder, OnCallResult, on_call_finder


def _mock_engineer(name="Alice", email="alice@co.com", available=True):
    eng = MagicMock()
    eng.name = name
    eng.email = email
    eng.id = uuid4()
    eng.status = MagicMock()
    eng.status.value = "available"
    eng.current_review_count = 1
    eng.max_concurrent_reviews = 5
    eng.can_accept_review.return_value = available
    eng.to_dict.return_value = {"name": name, "email": email}
    return eng


def _mock_schedule(engineer=None, priority=OnCallPriority.PRIMARY, service="payment-service"):
    sched = MagicMock()
    sched.engineer = engineer or _mock_engineer()
    sched.priority = priority
    sched.service = service
    sched.to_dict.return_value = {"priority": priority.value, "service": service}
    return sched


class TestOnCallResult:
    def test_attributes_stored(self):
        eng = _mock_engineer()
        sched = _mock_schedule(engineer=eng)
        result = OnCallResult(eng, sched, OnCallPriority.PRIMARY)
        assert result.engineer is eng
        assert result.schedule is sched
        assert result.priority == OnCallPriority.PRIMARY

    def test_to_dict_contains_keys(self):
        eng = _mock_engineer()
        sched = _mock_schedule(engineer=eng)
        result = OnCallResult(eng, sched, OnCallPriority.PRIMARY)
        d = result.to_dict()
        assert "engineer" in d
        assert "schedule" in d
        assert "priority" in d

    def test_to_dict_priority_value(self):
        eng = _mock_engineer()
        sched = _mock_schedule(engineer=eng, priority=OnCallPriority.SECONDARY)
        result = OnCallResult(eng, sched, OnCallPriority.SECONDARY)
        d = result.to_dict()
        assert d["priority"] == OnCallPriority.SECONDARY.value


class TestFindOnCallEngineer:
    async def _execute_returning(self, schedule):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = schedule
        db.execute = AsyncMock(return_value=mock_result)
        return db

    async def test_returns_oncall_result_when_found(self):
        eng = _mock_engineer(available=True)
        sched = _mock_schedule(engineer=eng)
        db = await self._execute_returning(sched)
        finder = OnCallFinder()
        result = await finder.find_on_call_engineer(db, service="payment-service")
        assert result is not None
        assert result.engineer is eng

    async def test_returns_none_when_no_schedule(self):
        db = await self._execute_returning(None)
        finder = OnCallFinder()
        result = await finder.find_on_call_engineer(db, service="payment-service")
        assert result is None

    async def test_escalates_to_secondary_when_primary_unavailable(self):
        eng = _mock_engineer(available=False)
        sched = _mock_schedule(engineer=eng, priority=OnCallPriority.PRIMARY)
        # First call: primary (unavailable), second call: secondary (None)
        db = AsyncMock()
        results_queue = [sched, None]

        call_count = [0]

        async def mock_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = results_queue[call_count[0]]
            call_count[0] += 1
            return mock_result

        db.execute = mock_execute
        finder = OnCallFinder()
        result = await finder.find_on_call_engineer(db, service="payment-service")
        # Primary was unavailable, fell back to secondary (which also returned None)
        assert result is None
        assert call_count[0] == 2  # Two DB calls

    async def test_escalates_through_tertiary_when_all_unavailable(self):
        eng = _mock_engineer(available=False)
        sched = _mock_schedule(engineer=eng, priority=OnCallPriority.SECONDARY)
        db = AsyncMock()
        results = [sched, sched, None]
        call_count = [0]

        async def mock_execute(stmt):
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = results[call_count[0]]
            call_count[0] += 1
            return mock_result

        db.execute = mock_execute
        finder = OnCallFinder()
        # Start at secondary to exercise the secondary → tertiary escalation
        result = await finder.find_on_call_engineer(
            db, service="payment-service", priority=OnCallPriority.SECONDARY
        )
        assert result is None

    async def test_no_service_or_team_filter(self):
        eng = _mock_engineer(available=True)
        sched = _mock_schedule(engineer=eng)
        db = await self._execute_returning(sched)
        finder = OnCallFinder()
        result = await finder.find_on_call_engineer(db)
        assert result is not None

    async def test_with_team_filter(self):
        eng = _mock_engineer(available=True)
        sched = _mock_schedule(engineer=eng)
        db = await self._execute_returning(sched)
        finder = OnCallFinder()
        result = await finder.find_on_call_engineer(db, team="backend")
        assert result is not None

    async def test_at_time_passed_through(self):
        db = await self._execute_returning(None)
        finder = OnCallFinder()
        at = datetime.now(timezone.utc) - timedelta(hours=2)
        result = await finder.find_on_call_engineer(db, at_time=at)
        assert result is None

    async def test_tertiary_unavailable_returns_none(self):
        eng = _mock_engineer(available=False)
        sched = _mock_schedule(engineer=eng, priority=OnCallPriority.TERTIARY)
        db = await self._execute_returning(sched)
        finder = OnCallFinder()
        result = await finder.find_on_call_engineer(
            db, priority=OnCallPriority.TERTIARY
        )
        assert result is None


class TestFindEscalationChain:
    async def test_returns_empty_when_no_on_call(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        chain = await finder.find_escalation_chain(db)
        assert chain == []

    async def test_returns_chain_for_available_primaries(self):
        eng = _mock_engineer(available=True)
        sched = _mock_schedule(engineer=eng)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sched
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        chain = await finder.find_escalation_chain(db, service="payment-service")
        # All three priorities returned the same available engineer
        assert len(chain) == 3


class TestGetAllCurrentOnCall:
    async def test_returns_all_on_call(self):
        eng = _mock_engineer()
        sched = _mock_schedule(engineer=eng)
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sched]
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        results = await finder.get_all_current_on_call(db)
        assert len(results) == 1
        assert isinstance(results[0], OnCallResult)

    async def test_returns_empty_when_no_schedules(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        results = await finder.get_all_current_on_call(db)
        assert results == []

    async def test_with_at_time(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        at = datetime.now(timezone.utc) - timedelta(hours=1)
        results = await finder.get_all_current_on_call(db, at_time=at)
        assert results == []


class TestCheckEngineerOnCall:
    async def test_returns_schedules_for_engineer(self):
        sched = _mock_schedule()
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sched]
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        results = await finder.check_engineer_on_call(db, engineer_id=uuid4())
        assert len(results) == 1

    async def test_returns_empty_when_not_on_call(self):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)
        finder = OnCallFinder()
        results = await finder.check_engineer_on_call(db, engineer_id=uuid4())
        assert results == []


class TestGlobalInstance:
    def test_on_call_finder_instance(self):
        assert isinstance(on_call_finder, OnCallFinder)
