"""
Unit tests for app/services/learning_engine.py

Focuses on pure-logic methods: PatternSignature, L1 cache, seed fallbacks,
and the _update_pattern_library logic using mocked DB sessions.
"""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.services.learning_engine import (
    IncidentOutcome,
    LearningEngine,
    PatternSignature,
    _SEED_PATTERNS,
)


class TestIncidentOutcomeModel:
    def test_defaults(self):
        outcome = IncidentOutcome(incident_id=uuid4())
        assert outcome.hypothesis_correct is False
        assert outcome.action_effective is False
        assert outcome.human_override is False
        assert outcome.resolution_notes == ""

    def test_full_construction(self):
        inc_id = uuid4()
        hyp_id = uuid4()
        act_id = uuid4()
        outcome = IncidentOutcome(
            incident_id=inc_id,
            hypothesis_id=hyp_id,
            hypothesis_correct=True,
            action_id=act_id,
            action_effective=True,
            time_to_resolution_minutes=15,
            human_override=False,
            resolution_notes="Fixed by restarting pod",
        )
        assert outcome.incident_id == inc_id
        assert outcome.hypothesis_correct is True
        assert outcome.time_to_resolution_minutes == 15


class TestPatternSignatureModel:
    def test_defaults(self):
        p = PatternSignature(
            pattern_id="svc:cat",
            name="Test Pattern",
            category="memory_leak",
            signal_indicators=["metric_a"],
        )
        assert p.confidence_adjustment == 0.0
        assert p.occurrence_count == 1
        assert p.success_rate == 0.0

    def test_confidence_adjustment_bounds(self):
        with pytest.raises(Exception):
            PatternSignature(
                pattern_id="x",
                name="x",
                category="x",
                signal_indicators=[],
                confidence_adjustment=0.9,  # out of range (max 0.5)
            )


class TestSeedPatterns:
    def test_seed_patterns_loaded(self):
        assert len(_SEED_PATTERNS) >= 5

    def test_seed_occurrence_count_zero(self):
        for name, pattern in _SEED_PATTERNS.items():
            assert pattern.occurrence_count == 0, f"Seed pattern {name} should have 0 occurrences"

    def test_seed_pattern_categories(self):
        categories = {p.category for p in _SEED_PATTERNS.values()}
        assert "memory_leak" in categories
        assert "cpu_spike" in categories
        assert "database_issue" in categories

    def test_seed_positive_adjustments(self):
        for name, pattern in _SEED_PATTERNS.items():
            assert pattern.confidence_adjustment >= 0, f"{name} seed should not penalize"


class TestLearningEngineInit:
    def test_empty_patterns_on_init(self):
        engine = LearningEngine()
        assert engine.patterns == {}


class TestGetPatternL1Cache:
    async def test_returns_pattern_from_l1_cache(self):
        engine = LearningEngine()
        pattern = PatternSignature(
            pattern_id="svc:cat",
            name="Cached Pattern",
            category="memory_leak",
            signal_indicators=["metric"],
            confidence_adjustment=0.1,
            occurrence_count=5,
            success_rate=0.8,
        )
        engine.patterns["svc:cat"] = pattern
        result = await engine.get_pattern("svc", "cat")
        assert result is pattern

    async def test_cache_miss_tries_db(self):
        engine = LearningEngine()
        # DB lookup fails gracefully
        with patch("app.services.learning_engine.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("DB unavailable")
            result = await engine.get_pattern("unknown-svc", "unknown-cat")
        assert result is None

    async def test_cache_miss_db_returns_none(self):
        engine = LearningEngine()

        async def mock_ctx_manager():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=mock_result)
            return db

        # Use contextlib.asynccontextmanager pattern
        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _mock_ctx():
            db = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            db.execute = AsyncMock(return_value=mock_result)
            yield db

        with patch("app.services.learning_engine.get_db_context", return_value=_mock_ctx()):
            result = await engine.get_pattern("svc-x", "cat-y")
        assert result is None


class TestGetConfidenceAdjustment:
    async def test_returns_pattern_confidence_when_in_cache(self):
        engine = LearningEngine()
        engine.patterns["svc:memory_leak"] = PatternSignature(
            pattern_id="svc:memory_leak",
            name="P",
            category="memory_leak",
            signal_indicators=[],
            confidence_adjustment=0.15,
            occurrence_count=10,
            success_rate=0.9,
        )
        adj = await engine.get_confidence_adjustment("svc", "memory_leak")
        assert adj == 0.15

    async def test_seed_fallback_when_no_real_pattern(self):
        engine = LearningEngine()
        # No in-memory pattern, DB will fail → seed fallback
        with patch("app.services.learning_engine.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("no DB")
            adj = await engine.get_confidence_adjustment("unknown-svc", "memory_leak")
        # memory_leak has a seed with positive confidence_adjustment
        assert adj > 0

    async def test_zero_when_no_pattern_no_seed(self):
        engine = LearningEngine()
        with patch("app.services.learning_engine.get_db_context") as mock_ctx:
            mock_ctx.side_effect = Exception("no DB")
            adj = await engine.get_confidence_adjustment("svc", "totally_unknown_category")
        assert adj == 0.0

    async def test_zero_occurrence_count_uses_seed(self):
        engine = LearningEngine()
        # Pattern with occurrence_count=0 should fall back to seed
        engine.patterns["svc:memory_leak"] = PatternSignature(
            pattern_id="svc:memory_leak",
            name="P",
            category="memory_leak",
            signal_indicators=[],
            confidence_adjustment=0.45,
            occurrence_count=0,  # synthetic/seed-like
            success_rate=0.0,
        )
        adj = await engine.get_confidence_adjustment("svc", "memory_leak")
        # occurrence_count == 0 → use seed fallback, not the cached pattern
        seed = _SEED_PATTERNS.get("memory_leak")
        assert adj == (seed.confidence_adjustment if seed else 0.0)


class TestUpdatePatternLibraryLogic:
    """Test the _update_pattern_library method with mocked DB."""

    async def _make_db_with_pattern(self, existing_pattern):
        db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing_pattern
        db.execute = AsyncMock(return_value=mock_result)
        return db

    async def test_creates_new_pattern_when_none_exists(self):
        engine = LearningEngine()
        incident = MagicMock()
        incident.affected_service = "payment-service"
        hypothesis = MagicMock()
        hypothesis.category = "memory_leak"
        hypothesis.supporting_signals = ["metric_a"]

        db = await self._make_db_with_pattern(None)

        await engine._update_pattern_library(db, incident, hypothesis, was_correct=True)

        db.add.assert_called_once()
        pattern_id = "payment-service:memory_leak"
        assert pattern_id in engine.patterns
        assert engine.patterns[pattern_id].success_rate == 1.0

    async def test_updates_existing_pattern_correct(self):
        engine = LearningEngine()

        existing = MagicMock()
        existing.occurrence_count = 5
        existing.success_rate = 0.8
        existing.name = "Payment memory_leak"
        existing.category = "memory_leak"
        existing.signal_indicators = ["mem"]

        incident = MagicMock()
        incident.affected_service = "payment-service"
        hypothesis = MagicMock()
        hypothesis.category = "memory_leak"
        hypothesis.supporting_signals = ["mem"]

        db = await self._make_db_with_pattern(existing)

        await engine._update_pattern_library(db, incident, hypothesis, was_correct=True)

        # Count should increase
        assert existing.occurrence_count == 6
        # Success rate should increase (was_correct=True)
        assert existing.success_rate > 0.8

    async def test_updates_existing_pattern_incorrect(self):
        engine = LearningEngine()

        existing = MagicMock()
        existing.occurrence_count = 10
        existing.success_rate = 0.5
        existing.name = "svc:cat"
        existing.category = "cpu_spike"
        existing.signal_indicators = ["cpu"]

        incident = MagicMock()
        incident.affected_service = "api-gateway"
        hypothesis = MagicMock()
        hypothesis.category = "cpu_spike"
        hypothesis.supporting_signals = ["cpu"]

        db = await self._make_db_with_pattern(existing)

        await engine._update_pattern_library(db, incident, hypothesis, was_correct=False)

        assert existing.occurrence_count == 11
        # was_correct=False, success_rate should decrease
        assert existing.success_rate < 0.5

    async def test_high_success_rate_gives_positive_confidence(self):
        engine = LearningEngine()

        existing = MagicMock()
        existing.occurrence_count = 10
        existing.success_rate = 0.9  # high → next step will also be > 0.8
        existing.name = "p"
        existing.category = "memory_leak"
        existing.signal_indicators = []

        incident = MagicMock()
        incident.affected_service = "svc"
        hypothesis = MagicMock()
        hypothesis.category = "memory_leak"
        hypothesis.supporting_signals = []

        db = await self._make_db_with_pattern(existing)
        await engine._update_pattern_library(db, incident, hypothesis, was_correct=True)
        assert existing.confidence_adjustment == 0.1

    async def test_low_success_rate_gives_negative_confidence(self):
        engine = LearningEngine()

        existing = MagicMock()
        existing.occurrence_count = 10
        existing.success_rate = 0.1  # low
        existing.name = "p"
        existing.category = "cpu_spike"
        existing.signal_indicators = []

        incident = MagicMock()
        incident.affected_service = "svc"
        hypothesis = MagicMock()
        hypothesis.category = "cpu_spike"
        hypothesis.supporting_signals = []

        db = await self._make_db_with_pattern(existing)
        await engine._update_pattern_library(db, incident, hypothesis, was_correct=False)
        # New rate: (0.1*10) / 11 ≈ 0.09, which is < 0.3
        assert existing.confidence_adjustment == -0.1
