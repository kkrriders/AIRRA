"""
Integration test specific fixtures for API endpoint testing.

This module provides fixtures for testing FastAPI endpoints with:
- Mocked external dependencies (LLM, Prometheus, Kubernetes)
- Test database with realistic data
- HTTP client with proper dependency injection
"""
from datetime import datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.reasoning.hypothesis_generator import (
    Evidence,
    HypothesisItem,
    HypothesesResponse,
)
from app.database import get_db
from app.main import app
from app.models.action import Action, ActionStatus
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.services.llm_client import LLMResponse
from app.services.prometheus_client import MetricDataPoint, MetricResult


# ============================================================================
# API Test Client with Dependency Overrides
# ============================================================================


@pytest.fixture
async def api_client(
    test_db: AsyncSession,
    mock_llm_client,
    mock_prometheus_client,
) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTP client for testing API endpoints with mocked dependencies.

    This client:
    - Uses test database (isolated per test)
    - Mocks LLM client (deterministic responses)
    - Mocks Prometheus client (configurable metrics)
    - Mocks Kubernetes client (safe dry-run mode)

    Usage:
        response = await api_client.post(
            "/api/v1/incidents",
            json={"title": "Test Incident", ...}
        )
        assert response.status_code == 201
    """

    # Override database dependency
    async def override_get_db():
        yield test_db

    from app.api.rate_limit import llm_rate_limit
    async def override_rate_limit():
        pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[llm_rate_limit] = override_rate_limit

    # Mock service singletons where they are imported
    with patch("app.api.v1.incidents.get_llm_client", return_value=mock_llm_client), \
         patch("app.api.v1.incidents.get_prometheus_client", return_value=mock_prometheus_client), \
         patch("app.api.v1.quick_incident.get_llm_client", return_value=mock_llm_client), \
         patch("app.api.v1.quick_incident.get_prometheus_client", return_value=mock_prometheus_client):
        
        async with AsyncClient(
            app=app, 
            base_url="http://test",
            headers={"X-API-Key": "dev-test-key-12345"}
        ) as client:
            yield client

    # Clear overrides after test
    app.dependency_overrides.clear()


# ============================================================================
# Incident API Test Fixtures
# ============================================================================


@pytest.fixture
def incident_create_payload():
    """
    Valid payload for creating an incident via API.
    """
    return {
        "title": "High CPU usage in payment service",
        "description": "CPU spiked to 95% for 10 minutes",
        "severity": "high",
        "affected_service": "payment-service",
        "affected_components": ["payment-processor", "transaction-handler"],
        "detected_at": datetime.utcnow().isoformat(),
        "detection_source": "prometheus",
        "metrics_snapshot": {
            "cpu_usage": 95.0,
            "memory_usage": 3_500_000_000,
            "request_rate": 500.0,
        },
        "context": {
            "alert_name": "HighCPU",
            "severity": "critical",
        },
    }


@pytest.fixture
def incident_update_payload():
    """
    Valid payload for updating an incident.
    """
    return {
        "status": "analyzing",
        "context": {
            "investigation_notes": "Root cause identified",
            "updated_at": datetime.utcnow().isoformat(),
        },
    }


@pytest.fixture
async def sample_incident(test_db: AsyncSession, incident_factory) -> Incident:
    """
    Create a sample incident in the database for testing.
    """
    incident = await incident_factory(
        title="Sample Incident",
        description="Test incident for API testing",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.DETECTED,
        affected_service="test-service",
    )
    return incident


@pytest.fixture
async def incident_with_hypotheses(
    test_db: AsyncSession,
    incident_factory,
    hypothesis_factory,
) -> Incident:
    """
    Create an incident with associated hypotheses for testing.
    """
    incident = await incident_factory(
        title="Incident with Hypotheses",
        severity=IncidentSeverity.CRITICAL,
        status=IncidentStatus.ANALYZING,
    )

    # Create multiple hypotheses
    await hypothesis_factory(
        incident_id=incident.id,
        description="Memory leak in cache",
        category="memory_leak",
        confidence_score=0.85,
        rank=1,
    )

    await hypothesis_factory(
        incident_id=incident.id,
        description="Database connection pool exhausted",
        category="database_issue",
        confidence_score=0.65,
        rank=2,
    )

    # Refresh to load relationships
    await test_db.refresh(incident)
    stmt = (
        select(Incident)
        .where(Incident.id == incident.id)
        .options(
            selectinload(Incident.hypotheses),
            selectinload(Incident.actions),
        )
    )
    result = await test_db.execute(stmt)
    return result.scalar_one()


@pytest.fixture
async def incident_with_actions(
    test_db: AsyncSession,
    incident_factory,
    action_factory,
) -> Incident:
    """
    Create an incident with associated actions for testing.
    """
    incident = await incident_factory(
        title="Incident with Actions",
        severity=IncidentSeverity.HIGH,
        status=IncidentStatus.PENDING_APPROVAL,
    )

    # Create actions in different states
    await action_factory(
        incident_id=incident.id,
        action_type="restart_pod",
        status=ActionStatus.PENDING_APPROVAL,
        risk_level="LOW",
    )

    await action_factory(
        incident_id=incident.id,
        action_type="scale_up",
        status=ActionStatus.PENDING_APPROVAL,
        risk_level="MEDIUM",
    )

    # Refresh to load relationships
    await test_db.refresh(incident)
    return incident


# ============================================================================
# Action API Test Fixtures
# ============================================================================


@pytest.fixture
async def approved_action(test_db: AsyncSession, incident_factory, action_factory) -> Action:
    """
    Create an approved action ready for execution.
    """
    incident = await incident_factory(
        title="Incident for Action Execution",
        status=IncidentStatus.APPROVED,
    )

    action = await action_factory(
        incident_id=incident.id,
        action_type="restart_pod",
        status=ActionStatus.APPROVED,
        execution_mode="dry_run",
        approved_by="test-operator@example.com",
        approved_at=datetime.utcnow(),
    )

    return action


@pytest.fixture
async def pending_action(test_db: AsyncSession, incident_factory, action_factory) -> Action:
    """
    Create a pending action awaiting approval.
    """
    incident = await incident_factory(
        title="Incident Awaiting Approval",
        status=IncidentStatus.PENDING_APPROVAL,
    )

    action = await action_factory(
        incident_id=incident.id,
        action_type="restart_pod",
        status=ActionStatus.PENDING_APPROVAL,
        requires_approval=True,
    )

    return action


@pytest.fixture
def action_approval_payload():
    """
    Valid payload for approving an action.
    """
    return {
        "approved_by": "sre-team@example.com",
        "approval_notes": "Reviewed and approved for execution",
        "execution_mode": "dry_run",
    }


@pytest.fixture
def action_rejection_payload():
    """
    Valid payload for rejecting an action.
    """
    return {
        "rejected_by": "sre-lead@example.com",
        "rejection_reason": "Risk too high, need manual intervention",
    }


# ============================================================================
# Quick Incident API Test Fixtures
# ============================================================================


@pytest.fixture
def quick_incident_payload():
    """
    Valid payload for quick incident creation with auto-analysis.
    """
    return {
        "service_name": "payment-service",
        "title": "Payment service degradation",
        "description": "Service experiencing high latency",
        "severity": "high",
        "metrics_snapshot": {
            "cpu_usage": 85.0,
            "memory_usage": 6_000_000_000,
            "request_rate": 1000.0,
            "error_rate": 5.0,
            "latency_p95": 2.5,
        },
        "context": {
            "triggered_by": "monitoring_system",
            "alert_id": "ALERT-123",
        },
    }


@pytest.fixture
def quick_incident_minimal_payload():
    """
    Minimal payload for quick incident (auto-generated title/description).
    """
    return {
        "service_name": "api-gateway",
        "severity": "medium",
    }


# ============================================================================
# Learning API Test Fixtures
# ============================================================================


@pytest.fixture
async def resolved_incident_with_outcome(
    test_db: AsyncSession,
    incident_factory,
    hypothesis_factory,
    action_factory,
) -> tuple[Incident, Hypothesis, Action]:
    """
    Create a resolved incident with hypothesis and action for learning tests.
    """
    incident = await incident_factory(
        title="Resolved Incident",
        status=IncidentStatus.RESOLVED,
        resolved_at=datetime.utcnow(),
        resolution_time_seconds=720,  # 12 minutes
    )

    hypothesis = await hypothesis_factory(
        incident_id=incident.id,
        description="Memory leak identified",
        category="memory_leak",
        confidence_score=0.88,
        rank=1,
    )

    action = await action_factory(
        incident_id=incident.id,
        action_type="restart_pod",
        status=ActionStatus.SUCCEEDED,
        execution_result={
            "status": "success",
            "message": "Pod restarted successfully",
            "execution_time_seconds": 45,
        },
    )

    return incident, hypothesis, action


@pytest.fixture
def incident_outcome_payload():
    """
    Valid payload for capturing incident outcome.
    """
    return {
        "hypothesis_correct": True,
        "action_effective": True,
        "human_override": False,
        "resolution_notes": "Root cause was indeed memory leak. Pod restart resolved the issue.",
        "feedback": {
            "confidence_calibration": "accurate",
            "action_selection": "appropriate",
        },
    }


# ============================================================================
# Mock Response Fixtures for Different Scenarios
# ============================================================================


@pytest.fixture
def mock_llm_memory_leak_response():
    """
    Mock LLM response for memory leak scenario.
    """
    hypotheses_response = HypothesesResponse(
        hypotheses=[
            HypothesisItem(
                description="Memory leak in caching layer causing OOM",
                category="memory_leak",
                confidence_score=0.90,
                evidence=[
                    Evidence(
                        signal_type="metric",
                        signal_name="memory_usage",
                        observation="Memory grew from 2GB to 8GB over 3 hours",
                        relevance=0.95,
                    ),
                    Evidence(
                        signal_type="metric",
                        signal_name="gc_time",
                        observation="GC time increased to 40% of CPU time",
                        relevance=0.85,
                    ),
                ],
                reasoning="Linear memory growth combined with high GC pressure strongly indicates a memory leak. The rate of growth suggests object accumulation without proper cleanup.",
            ),
        ],
        overall_assessment="Critical memory leak requiring immediate pod restart",
    )

    llm_response = LLMResponse(
        content='{"hypotheses": [...]}',
        prompt_tokens=450,
        completion_tokens=280,
        total_tokens=730,
        model="claude-3-5-sonnet-20241022",
    )

    return hypotheses_response, llm_response


@pytest.fixture
def mock_llm_cpu_spike_response():
    """
    Mock LLM response for CPU spike scenario.
    """
    hypotheses_response = HypothesesResponse(
        hypotheses=[
            HypothesisItem(
                description="Infinite loop in request processing causing CPU exhaustion",
                category="cpu_spike",
                confidence_score=0.82,
                evidence=[
                    Evidence(
                        signal_type="metric",
                        signal_name="cpu_usage",
                        observation="CPU spiked to 98% suddenly",
                        relevance=0.90,
                    ),
                ],
                reasoning="Sudden CPU spike suggests runaway process or infinite loop",
            ),
        ],
        overall_assessment="CPU spike requires immediate investigation",
    )

    llm_response = LLMResponse(
        content='{"hypotheses": [...]}',
        prompt_tokens=400,
        completion_tokens=200,
        total_tokens=600,
        model="claude-3-5-sonnet-20241022",
    )

    return hypotheses_response, llm_response


@pytest.fixture
def mock_llm_no_clear_cause_response():
    """
    Mock LLM response when no clear root cause is found.
    """
    hypotheses_response = HypothesesResponse(
        hypotheses=[
            HypothesisItem(
                description="Temporary network congestion",
                category="network_issue",
                confidence_score=0.45,
                evidence=[
                    Evidence(
                        signal_type="metric",
                        signal_name="latency",
                        observation="Brief latency spike",
                        relevance=0.50,
                    ),
                ],
                reasoning="Insufficient evidence for definitive root cause",
            ),
        ],
        overall_assessment="Unclear root cause, recommend continued monitoring",
    )

    llm_response = LLMResponse(
        content='{"hypotheses": [...]}',
        prompt_tokens=300,
        completion_tokens=150,
        total_tokens=450,
        model="claude-3-5-sonnet-20241022",
    )

    return hypotheses_response, llm_response


# ============================================================================
# Pagination Test Fixtures
# ============================================================================


@pytest.fixture
async def multiple_incidents(
    test_db: AsyncSession,
    incident_factory,
) -> list[Incident]:
    """
    Create multiple incidents for testing pagination and filtering.
    """
    incidents = []

    # Create 15 incidents with varying properties
    for i in range(15):
        severity = (
            IncidentSeverity.CRITICAL
            if i < 3
            else IncidentSeverity.HIGH if i < 8 else IncidentSeverity.MEDIUM
        )

        status = (
            IncidentStatus.RESOLVED
            if i < 5
            else IncidentStatus.ANALYZING if i < 10 else IncidentStatus.DETECTED
        )

        service = f"service-{i % 3}"  # Rotate through 3 services

        incident = await incident_factory(
            title=f"Incident {i+1}",
            description=f"Test incident number {i+1}",
            severity=severity,
            status=status,
            affected_service=service,
            detected_at=datetime.utcnow() - timedelta(hours=i),
        )
        incidents.append(incident)

    return incidents


# ============================================================================
# Error Scenario Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_client_with_timeout(mock_llm_client):
    """
    Mock LLM client that raises timeout error.
    """
    mock_llm_client.generate_structured = AsyncMock(
        side_effect=TimeoutError("LLM request timed out")
    )
    return mock_llm_client


@pytest.fixture
def mock_prometheus_client_with_error(mock_prometheus_client):
    """
    Mock Prometheus client that raises connection error.
    """
    mock_prometheus_client.get_service_metrics = AsyncMock(
        side_effect=ConnectionError("Prometheus unavailable")
    )
    return mock_prometheus_client


@pytest.fixture
def invalid_incident_payload():
    """
    Invalid payload for testing validation errors.
    """
    return {
        "title": "",  # Empty title (should fail validation)
        "severity": "invalid_severity",  # Invalid enum
        "affected_service": None,  # Required field missing
    }


# ============================================================================
# Helper Imports for Integration Tests
# ============================================================================

from sqlalchemy.orm import selectinload  # noqa: E402

# This makes selectinload available for fixtures that need it
__all__ = [
    "api_client",
    "incident_create_payload",
    "sample_incident",
    "incident_with_hypotheses",
    "incident_with_actions",
    "approved_action",
    "pending_action",
    "quick_incident_payload",
    "resolved_incident_with_outcome",
    "multiple_incidents",
]
