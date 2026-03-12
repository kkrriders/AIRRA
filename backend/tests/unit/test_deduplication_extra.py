"""
Additional unit tests for app/utils/deduplication.py

Covers the fuzzy-match path (lines 282-298) and commit/rollback branches
in create_or_update_incident (lines 401-404, 429-432).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.utils.deduplication import (
    create_or_update_incident,
    find_duplicate_incident,
    generate_incident_fingerprint,
    is_fuzzy_match,
)


# ---------------------------------------------------------------------------
# Fuzzy match path in find_duplicate_incident (lines 282-298)
# ---------------------------------------------------------------------------

class TestFindDuplicateFuzzyMatch:
    async def test_fuzzy_match_found_returns_locked_incident(self):
        """When no exact match but fuzzy match exists, return the locked row."""
        service = "payment-service"
        description = "memory leak detected in heap"
        affected_components = ["heap", "jvm"]

        # exact match query → None (no exact)
        # fuzzy query scalars → [candidate] (fuzzy match)
        # lock query scalar_one_or_none → locked_incident

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        candidate = MagicMock()
        candidate.id = uuid4()
        candidate.affected_service = service
        candidate.description = "memory leak detected in heap allocation"
        candidate.affected_components = ["heap", "jvm"]

        locked = MagicMock()
        locked.id = candidate.id

        call_count = [0]

        async def mock_execute(stmt):
            r = MagicMock()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                # exact match query → None
                r.scalar_one_or_none.return_value = None
            elif idx == 1:
                # fuzzy query → [candidate]
                r.scalars.return_value.all.return_value = [candidate]
            elif idx == 2:
                # lock query → locked
                r.scalar_one_or_none.return_value = locked
            else:
                r.scalar_one_or_none.return_value = None
                r.scalars.return_value.all.return_value = []
            return r

        db.execute = mock_execute

        result = await find_duplicate_incident(
            db=db,
            service=service,
            description=description,
            severity="high",
            affected_components=affected_components,
        )

        assert result is locked

    async def test_fuzzy_match_not_found_returns_none(self):
        """When fuzzy candidates don't match, return None."""
        service = "payment-service"
        description = "out of memory error"

        db = AsyncMock()
        candidate = MagicMock()
        candidate.id = uuid4()
        candidate.affected_service = service
        candidate.description = "disk space full error"
        candidate.affected_components = []

        call_count = [0]

        async def mock_execute(stmt):
            r = MagicMock()
            idx = call_count[0]
            call_count[0] += 1

            if idx == 0:
                r.scalar_one_or_none.return_value = None
            elif idx == 1:
                r.scalars.return_value.all.return_value = [candidate]
            else:
                r.scalar_one_or_none.return_value = None
                r.scalars.return_value.all.return_value = []
            return r

        db.execute = mock_execute

        result = await find_duplicate_incident(
            db=db,
            service=service,
            description=description,
            severity="high",
        )

        assert result is None


# ---------------------------------------------------------------------------
# create_or_update_incident commit exception paths (lines 401-404, 429-432)
# ---------------------------------------------------------------------------

class TestCreateOrUpdateCommitException:
    async def test_update_commit_exception_rolls_back_and_reraises(self):
        """If commit raises on update path, rollback is called and exception propagates."""
        service = "payment-service"
        description = "memory leak detected"
        severity = "high"

        duplicate = MagicMock()
        duplicate.id = uuid4()
        duplicate.severity = MagicMock()
        duplicate.severity.value = "high"
        duplicate.metrics_snapshot = {}
        duplicate.context = {}

        db = AsyncMock()
        db.flush = AsyncMock()
        db.rollback = AsyncMock()
        db.commit = AsyncMock(side_effect=Exception("commit failed"))

        # Patch find_duplicate_incident to return our duplicate
        with patch("app.utils.deduplication.find_duplicate_incident",
                   AsyncMock(return_value=duplicate)):
            with pytest.raises(Exception, match="commit failed"):
                await create_or_update_incident(
                    db=db,
                    service=service,
                    title="Memory Leak",
                    description=description,
                    severity=severity,
                    auto_commit=True,
                )

        db.rollback.assert_called_once()

    async def test_create_commit_exception_rolls_back_and_reraises(self):
        """If commit raises on create path, rollback is called and exception propagates."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db.rollback = AsyncMock()
        db.commit = AsyncMock(side_effect=Exception("disk full"))

        with patch("app.utils.deduplication.find_duplicate_incident",
                   AsyncMock(return_value=None)):
            with pytest.raises(Exception, match="disk full"):
                await create_or_update_incident(
                    db=db,
                    service="api-gateway",
                    title="Timeout",
                    description="request timeout",
                    severity="medium",
                    auto_commit=True,
                )

        db.rollback.assert_called_once()

    async def test_update_no_auto_commit_does_not_commit(self):
        """With auto_commit=False on update path, commit is never called."""
        duplicate = MagicMock()
        duplicate.id = uuid4()
        duplicate.severity = MagicMock()
        duplicate.severity.value = "medium"
        duplicate.metrics_snapshot = {}
        duplicate.context = {}

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()

        with patch("app.utils.deduplication.find_duplicate_incident",
                   AsyncMock(return_value=duplicate)):
            incident, created = await create_or_update_incident(
                db=db,
                service="svc",
                title="Title",
                description="desc",
                severity="medium",
                auto_commit=False,
            )

        assert created is False
        db.commit.assert_not_called()

    async def test_create_no_auto_commit_does_not_commit(self):
        """With auto_commit=False on create path, commit is never called."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()
        db.commit = AsyncMock()

        with patch("app.utils.deduplication.find_duplicate_incident",
                   AsyncMock(return_value=None)):
            incident, created = await create_or_update_incident(
                db=db,
                service="svc",
                title="Title",
                description="desc",
                severity="low",
                auto_commit=False,
            )

        assert created is True
        db.commit.assert_not_called()

    async def test_update_metrics_and_context_merged(self):
        """Update path merges metrics_snapshot and context."""
        duplicate = MagicMock()
        duplicate.id = uuid4()
        duplicate.severity = MagicMock()
        duplicate.severity.value = "low"
        duplicate.metrics_snapshot = {"cpu": 50}
        duplicate.context = {"foo": "bar"}

        db = AsyncMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        with patch("app.utils.deduplication.find_duplicate_incident",
                   AsyncMock(return_value=duplicate)):
            incident, created = await create_or_update_incident(
                db=db,
                service="svc",
                title="Title",
                description="desc",
                severity="high",  # higher than existing "low"
                metrics_snapshot={"mem": 80},
                context={"extra": "data"},
                auto_commit=True,
            )

        assert created is False
        # Severity should be escalated — IncidentSeverity enum value
        from app.models.incident import IncidentSeverity
        assert duplicate.severity == IncidentSeverity.HIGH
        # Metrics should be merged (cpu=50 from original + mem=80 from new)
        assert duplicate.metrics_snapshot.get("mem") == 80
        # Context should include extra
        assert duplicate.context.get("extra") == "data"
