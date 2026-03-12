"""
Unit tests for LearningEngine.capture_outcome (lines 135-251).

Uses mocked get_db_context + embed_incident_task to stay pure unit tests.
"""
import pytest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.learning_engine import IncidentOutcome, LearningEngine

# Always patch embed_incident_task so tests don't try to reach Redis/Celery
pytestmark = pytest.mark.usefixtures("mock_embed_task")


@pytest.fixture(autouse=True)
def mock_embed_task():
    mock_task = MagicMock()
    mock_task.delay = MagicMock()
    with patch("app.worker.tasks.embedding.embed_incident_task", mock_task):
        yield mock_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_outcome(
    hypothesis_id=None,
    hypothesis_correct=False,
    action_id=None,
    action_effective=True,
    resolution_notes="Fixed",
):
    return IncidentOutcome(
        incident_id=uuid4(),
        hypothesis_id=hypothesis_id,
        hypothesis_correct=hypothesis_correct,
        action_id=action_id,
        action_effective=action_effective,
        resolution_notes=resolution_notes,
    )


def _make_incident_mock():
    inc = MagicMock()
    inc.id = uuid4()
    inc.affected_service = "payment-service"
    inc.context = {}
    inc.resolved_at = None
    inc.detected_at = None
    return inc


def _simple_ctx(return_values: list):
    """Build a context manager whose DB returns different scalar_one_or_none values per execute call."""
    call_count = [0]

    @asynccontextmanager
    async def _ctx():
        db = AsyncMock()
        db.commit = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        async def mock_exec(stmt):
            r = MagicMock()
            idx = call_count[0]
            call_count[0] += 1
            r.scalar_one_or_none.return_value = return_values[idx] if idx < len(return_values) else None
            return r

        db.execute = mock_exec
        yield db

    return _ctx()


# ---------------------------------------------------------------------------
# capture_outcome tests
# ---------------------------------------------------------------------------

class TestCaptureOutcome:
    async def test_incident_not_found_returns_silently(self):
        engine = LearningEngine()
        outcome = _make_outcome()

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([None])):
            await engine.capture_outcome(outcome)

    async def test_basic_capture_with_no_hypothesis_or_action(self):
        engine = LearningEngine()
        outcome = _make_outcome(hypothesis_id=None, action_id=None, hypothesis_correct=False)
        inc = _make_incident_mock()

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc])):
            await engine.capture_outcome(outcome)

        assert "learning" in inc.context
        assert inc.context["learning"]["hypothesis_correct"] is False

    async def test_resolution_time_calculated_when_timestamps_present(self):
        engine = LearningEngine()
        outcome = _make_outcome(hypothesis_id=None, action_id=None, hypothesis_correct=False)

        inc = MagicMock()
        inc.id = uuid4()
        inc.affected_service = "svc"
        inc.context = {}
        detected = datetime(2026, 3, 11, 12, 0, tzinfo=timezone.utc)
        resolved = datetime(2026, 3, 11, 12, 5, tzinfo=timezone.utc)
        inc.detected_at = detected
        inc.resolved_at = resolved

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc])):
            await engine.capture_outcome(outcome)

        assert inc.resolution_time_seconds == 300

    async def test_capture_with_hypothesis(self):
        engine = LearningEngine()
        hyp_id = uuid4()
        # hypothesis_correct=False avoids re-embed path
        outcome = _make_outcome(hypothesis_id=hyp_id, hypothesis_correct=False)

        inc = _make_incident_mock()

        hyp = MagicMock()
        hyp.category = "memory_leak"
        hyp.supporting_signals = ["mem_rss"]

        # Returns: incident, hypothesis, None (pattern lookup in _update_pattern_library)
        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, hyp, None])):
            await engine.capture_outcome(outcome)

        assert hyp.validated is False
        assert hyp.validation_feedback == "Fixed"

    async def test_capture_with_hypothesis_correct(self):
        engine = LearningEngine()
        hyp_id = uuid4()
        outcome = _make_outcome(hypothesis_id=hyp_id, hypothesis_correct=True)

        inc = _make_incident_mock()
        hyp = MagicMock()
        hyp.category = "memory_leak"
        hyp.supporting_signals = []

        # Returns: incident, hypothesis, None (pattern), None (postmortem)
        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, hyp, None, None])):
            await engine.capture_outcome(outcome)

        assert hyp.validated is True

    async def test_capture_with_action(self):
        engine = LearningEngine()
        act_id = uuid4()
        outcome = _make_outcome(hypothesis_id=None, action_id=act_id,
                                action_effective=True, hypothesis_correct=False)

        inc = _make_incident_mock()
        act = MagicMock()
        act.execution_result = {}

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, act])):
            await engine.capture_outcome(outcome)

        assert "effective" in act.execution_result
        assert act.execution_result["effective"] is True
        assert act.execution_result["resolution_notes"] == "Fixed"

    async def test_capture_exception_does_not_propagate(self):
        engine = LearningEngine()
        outcome = _make_outcome()

        with patch("app.services.learning_engine.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("DB error")
            await engine.capture_outcome(outcome)

    async def test_context_updated_with_learning_metadata(self):
        engine = LearningEngine()
        outcome = _make_outcome(
            hypothesis_id=None, action_id=None,
            hypothesis_correct=False, action_effective=True,
            resolution_notes="Restarted pod"
        )
        inc = _make_incident_mock()

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc])):
            await engine.capture_outcome(outcome)

        learning = inc.context["learning"]
        assert learning["hypothesis_correct"] is False
        assert learning["action_effective"] is True
        assert "captured_at" in learning

    async def test_re_embed_triggered_when_hypothesis_correct(self, mock_embed_task):
        engine = LearningEngine()
        hyp_id = uuid4()
        outcome = _make_outcome(hypothesis_id=hyp_id, hypothesis_correct=True)

        inc = _make_incident_mock()
        hyp = MagicMock()
        hyp.category = "memory_leak"
        hyp.supporting_signals = []

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, hyp, None, None])):
            await engine.capture_outcome(outcome)

        mock_embed_task.delay.assert_called_once()

    async def test_re_embed_not_triggered_when_hypothesis_incorrect(self, mock_embed_task):
        engine = LearningEngine()
        hyp_id = uuid4()
        outcome = _make_outcome(hypothesis_id=hyp_id, hypothesis_correct=False)

        inc = _make_incident_mock()
        hyp = MagicMock()
        hyp.category = "memory_leak"
        hyp.supporting_signals = []

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, hyp, None])):
            await engine.capture_outcome(outcome)

        mock_embed_task.delay.assert_not_called()

    async def test_re_embed_with_postmortem_context(self, mock_embed_task):
        engine = LearningEngine()
        hyp_id = uuid4()
        outcome = _make_outcome(hypothesis_id=hyp_id, hypothesis_correct=True)

        inc = _make_incident_mock()
        hyp = MagicMock()
        hyp.category = "memory_leak"
        hyp.supporting_signals = []

        postmortem = MagicMock()
        postmortem.actual_root_cause = "Memory leak in connection pool"
        postmortem.lessons_learned = ["Increase heap size", "Add circuit breaker"]

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, hyp, None, postmortem])):
            await engine.capture_outcome(outcome)

        mock_embed_task.delay.assert_called_once()
        call_args = mock_embed_task.delay.call_args
        extra_ctx = call_args[0][1]
        assert extra_ctx is not None
        assert "actual_root_cause" in extra_ctx

    async def test_re_embed_embed_exception_does_not_break_capture(self, mock_embed_task):
        engine = LearningEngine()
        hyp_id = uuid4()
        outcome = _make_outcome(hypothesis_id=hyp_id, hypothesis_correct=True)

        inc = _make_incident_mock()
        hyp = MagicMock()
        hyp.category = "memory_leak"
        hyp.supporting_signals = []

        mock_embed_task.delay.side_effect = Exception("Celery broker unavailable")

        with patch("app.services.learning_engine.get_db_context",
                   return_value=_simple_ctx([inc, hyp, None, None])):
            # Should not raise
            await engine.capture_outcome(outcome)
