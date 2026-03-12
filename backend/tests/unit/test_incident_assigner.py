"""
Unit tests for app/services/incident_assigner.py

Covers AssignmentResult, auto_assign (on_call + load_balanced strategies),
assign_manual, unassign, _assign_engineer, _unassign_engineer,
and _send_assignment_notification error handling.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.incident_assigner import (
    AssignmentResult,
    AssignmentStrategy,
    IncidentAssigner,
    incident_assigner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_engineer(name="Alice", email="alice@co.com", available=True, count=1, max_count=5):
    eng = MagicMock()
    eng.id = uuid4()
    eng.name = name
    eng.email = email
    eng.status = MagicMock()
    eng.status.value = "active"
    eng.current_review_count = count
    eng.max_concurrent_reviews = max_count
    eng.can_accept_review.return_value = available
    eng.to_dict.return_value = {"name": name, "email": email}
    return eng


def _mock_incident(assigned=False):
    inc = MagicMock()
    inc.id = uuid4()
    inc.title = "High Memory Usage"
    inc.affected_service = "payment-service"
    inc.severity = MagicMock()
    inc.severity.value = "high"
    inc.status = MagicMock()
    inc.status.value = "analyzing"
    inc.description = "Memory leak detected"
    inc.detected_at = MagicMock()
    inc.detected_at.strftime.return_value = "2026-03-11 12:00 UTC"
    inc.assigned_engineer_id = _mock_engineer().id if assigned else None
    return inc


def _mock_on_call_result(engineer):
    r = MagicMock()
    r.engineer = engineer
    return r


def _make_db():
    db = AsyncMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# AssignmentResult
# ---------------------------------------------------------------------------

class TestAssignmentResult:
    def test_success_true(self):
        eng = _mock_engineer()
        r = AssignmentResult(success=True, engineer=eng, strategy=AssignmentStrategy.ON_CALL, reason="ok")
        assert r.success is True
        assert r.engineer is eng
        assert r.strategy == AssignmentStrategy.ON_CALL
        assert r.reason == "ok"

    def test_success_false_no_engineer(self):
        r = AssignmentResult(success=False, reason="no engineers")
        assert r.success is False
        assert r.engineer is None
        assert r.strategy is None

    def test_to_dict_with_engineer(self):
        eng = _mock_engineer()
        r = AssignmentResult(success=True, engineer=eng, strategy=AssignmentStrategy.LOAD_BALANCED, reason="lb")
        d = r.to_dict()
        assert d["success"] is True
        assert d["engineer"] == eng.to_dict()
        assert d["strategy"] == AssignmentStrategy.LOAD_BALANCED
        assert d["reason"] == "lb"

    def test_to_dict_without_engineer(self):
        r = AssignmentResult(success=False, reason="none")
        d = r.to_dict()
        assert d["engineer"] is None
        assert d["success"] is False


# ---------------------------------------------------------------------------
# auto_assign — already assigned
# ---------------------------------------------------------------------------

class TestAutoAssignAlreadyAssigned:
    async def test_returns_failure_when_already_assigned(self):
        inc = _mock_incident(assigned=True)
        assigner = IncidentAssigner()
        db = _make_db()
        result = await assigner.auto_assign(db, inc)
        assert result.success is False
        assert "already assigned" in result.reason


# ---------------------------------------------------------------------------
# auto_assign — ON_CALL strategy
# ---------------------------------------------------------------------------

class TestAutoAssignOnCall:
    async def test_on_call_success(self):
        eng = _mock_engineer(available=True)
        inc = _mock_incident()
        db = _make_db()

        on_call_result = _mock_on_call_result(eng)
        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.on_call_finder") as mock_finder, \
             patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_finder.find_on_call_engineer = AsyncMock(return_value=on_call_result)
            mock_logger.log = AsyncMock()
            result = await assigner.auto_assign(db, inc, AssignmentStrategy.ON_CALL)

        assert result.success is True
        assert result.engineer is eng
        assert result.strategy == AssignmentStrategy.ON_CALL

    async def test_on_call_engineer_at_capacity_falls_back_to_load_balanced(self):
        eng = _mock_engineer(available=False)
        inc = _mock_incident()
        db = _make_db()

        available_eng = _mock_engineer(name="Bob", available=True)
        on_call_result = _mock_on_call_result(eng)

        # Second DB execute (load_balanced) returns available engineer
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [available_eng]
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.on_call_finder") as mock_finder, \
             patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_finder.find_on_call_engineer = AsyncMock(return_value=on_call_result)
            mock_logger.log = AsyncMock()
            result = await assigner.auto_assign(db, inc, AssignmentStrategy.ON_CALL)

        assert result.success is True
        assert result.engineer is available_eng
        assert result.strategy == AssignmentStrategy.LOAD_BALANCED

    async def test_on_call_none_falls_back_to_load_balanced(self):
        inc = _mock_incident()
        db = _make_db()

        available_eng = _mock_engineer(name="Carol", available=True)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [available_eng]
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.on_call_finder") as mock_finder, \
             patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_finder.find_on_call_engineer = AsyncMock(return_value=None)
            mock_logger.log = AsyncMock()
            result = await assigner.auto_assign(db, inc, AssignmentStrategy.ON_CALL)

        assert result.success is True
        assert result.engineer is available_eng

    async def test_on_call_none_no_load_balanced_returns_failure(self):
        inc = _mock_incident()
        db = _make_db()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.on_call_finder") as mock_finder:
            mock_finder.find_on_call_engineer = AsyncMock(return_value=None)
            result = await assigner.auto_assign(db, inc, AssignmentStrategy.ON_CALL)

        assert result.success is False
        assert "No available engineers" in result.reason


# ---------------------------------------------------------------------------
# auto_assign — LOAD_BALANCED strategy
# ---------------------------------------------------------------------------

class TestAutoAssignLoadBalanced:
    async def test_load_balanced_success(self):
        eng = _mock_engineer(available=True, count=2)
        inc = _mock_incident()
        db = _make_db()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [eng]
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_logger.log = AsyncMock()
            result = await assigner.auto_assign(db, inc, AssignmentStrategy.LOAD_BALANCED)

        assert result.success is True
        assert result.strategy == AssignmentStrategy.LOAD_BALANCED
        assert result.engineer is eng

    async def test_load_balanced_no_engineers_returns_failure(self):
        inc = _mock_incident()
        db = _make_db()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()
        result = await assigner.auto_assign(db, inc, AssignmentStrategy.LOAD_BALANCED)

        assert result.success is False
        assert "No available engineers" in result.reason

    async def test_load_balanced_all_at_capacity_returns_failure(self):
        eng = _mock_engineer(available=False)
        inc = _mock_incident()
        db = _make_db()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [eng]
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()
        result = await assigner.auto_assign(db, inc, AssignmentStrategy.LOAD_BALANCED)

        assert result.success is False

    async def test_load_balanced_picks_least_busy(self):
        eng1 = _mock_engineer(name="Alice", available=True, count=3)
        eng2 = _mock_engineer(name="Bob", available=True, count=1)
        inc = _mock_incident()
        db = _make_db()

        # DB returns in order (sorted by count asc from SQL), so eng2 first
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [eng2, eng1]
        db.execute = AsyncMock(return_value=mock_result)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_logger.log = AsyncMock()
            result = await assigner.auto_assign(db, inc, AssignmentStrategy.LOAD_BALANCED)

        assert result.engineer is eng2


# ---------------------------------------------------------------------------
# assign_manual
# ---------------------------------------------------------------------------

class TestAssignManual:
    async def test_manual_assign_success(self):
        eng = _mock_engineer(available=True)
        inc = _mock_incident()
        db = _make_db()
        db.get = AsyncMock(return_value=eng)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_logger.log = AsyncMock()
            result = await assigner.assign_manual(db, inc, eng.id)

        assert result.success is True
        assert result.strategy == AssignmentStrategy.MANUAL

    async def test_manual_assign_engineer_not_found(self):
        inc = _mock_incident()
        db = _make_db()
        db.get = AsyncMock(return_value=None)

        assigner = IncidentAssigner()
        result = await assigner.assign_manual(db, inc, uuid4())

        assert result.success is False
        assert "not found" in result.reason

    async def test_manual_assign_at_capacity_without_force(self):
        eng = _mock_engineer(available=False)
        inc = _mock_incident()
        db = _make_db()
        db.get = AsyncMock(return_value=eng)

        assigner = IncidentAssigner()
        result = await assigner.assign_manual(db, inc, eng.id, force=False)

        assert result.success is False
        assert "cannot accept" in result.reason

    async def test_manual_assign_at_capacity_with_force(self):
        eng = _mock_engineer(available=False)
        inc = _mock_incident()
        db = _make_db()
        db.get = AsyncMock(return_value=eng)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_logger.log = AsyncMock()
            result = await assigner.assign_manual(db, inc, eng.id, force=True)

        assert result.success is True

    async def test_manual_assign_with_existing_assignment_unassigns_first(self):
        eng = _mock_engineer(available=True)
        old_eng = _mock_engineer(name="OldEng")
        inc = _mock_incident(assigned=True)
        inc.assigned_engineer_id = old_eng.id
        db = _make_db()
        # First get: old engineer for unassign, second get: new engineer
        db.get = AsyncMock(side_effect=[old_eng, eng, eng])

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger, \
             patch.object(assigner, "_send_assignment_notification", AsyncMock()):
            mock_logger.log = AsyncMock()
            result = await assigner.assign_manual(db, inc, eng.id)

        assert result.success is True


# ---------------------------------------------------------------------------
# unassign
# ---------------------------------------------------------------------------

class TestUnassign:
    async def test_unassign_success(self):
        eng = _mock_engineer()
        inc = _mock_incident(assigned=True)
        inc.assigned_engineer_id = eng.id
        db = _make_db()
        db.get = AsyncMock(return_value=eng)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger:
            mock_logger.log = AsyncMock()
            result = await assigner.unassign(db, inc)

        assert result.success is True
        assert eng.name in result.reason

    async def test_unassign_not_assigned_returns_failure(self):
        inc = _mock_incident(assigned=False)
        db = _make_db()

        assigner = IncidentAssigner()
        result = await assigner.unassign(db, inc)

        assert result.success is False
        assert "not currently assigned" in result.reason

    async def test_unassign_engineer_not_found_still_succeeds(self):
        inc = _mock_incident(assigned=True)
        inc.assigned_engineer_id = uuid4()
        db = _make_db()
        db.get = AsyncMock(return_value=None)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger:
            mock_logger.log = AsyncMock()
            result = await assigner.unassign(db, inc)

        assert result.success is True


# ---------------------------------------------------------------------------
# _send_assignment_notification
# ---------------------------------------------------------------------------

class TestSendAssignmentNotification:
    async def test_notification_exception_does_not_propagate(self):
        """If notification_service.send_incident_notification raises, _assign_engineer still succeeds."""
        eng = _mock_engineer(available=True)
        inc = _mock_incident()
        db = _make_db()

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger:
            mock_logger.log = AsyncMock()
            # Patch inside _send_assignment_notification to raise
            with patch(
                "app.services.incident_assigner.notification_service",
                create=True,
            ) as mock_ns:
                mock_ns.send_incident_notification = AsyncMock(side_effect=Exception("smtp error"))
                # Call _send_assignment_notification directly
                await assigner._send_assignment_notification(db, inc, eng)

        # No exception raised — error was swallowed


# ---------------------------------------------------------------------------
# _unassign_engineer — internal paths
# ---------------------------------------------------------------------------

class TestUnassignEngineerInternal:
    async def test_unassign_engineer_no_assignment_is_noop(self):
        inc = _mock_incident(assigned=False)
        db = _make_db()

        assigner = IncidentAssigner()
        # Should return immediately without touching DB
        await assigner._unassign_engineer(db, inc)
        db.get.assert_not_called()

    async def test_unassign_engineer_decrements_count(self):
        eng = _mock_engineer()
        eng.current_review_count = 3
        inc = _mock_incident(assigned=True)
        inc.assigned_engineer_id = eng.id
        db = _make_db()
        db.get = AsyncMock(return_value=eng)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger:
            mock_logger.log = AsyncMock()
            await assigner._unassign_engineer(db, inc)

        assert eng.current_review_count == 2
        assert inc.assigned_engineer_id is None

    async def test_unassign_engineer_count_at_zero_not_decremented(self):
        eng = _mock_engineer()
        eng.current_review_count = 0
        inc = _mock_incident(assigned=True)
        inc.assigned_engineer_id = eng.id
        db = _make_db()
        db.get = AsyncMock(return_value=eng)

        assigner = IncidentAssigner()

        with patch("app.services.incident_assigner.event_logger") as mock_logger:
            mock_logger.log = AsyncMock()
            await assigner._unassign_engineer(db, inc)

        # Count should not go negative
        assert eng.current_review_count == 0


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

class TestGlobalInstance:
    def test_incident_assigner_instance(self):
        assert isinstance(incident_assigner, IncidentAssigner)
