"""
Root-level test fixtures shared across all tests.

This module provides:
- Mock LLM clients (Anthropic, OpenAI, OpenRouter)
- Mock Prometheus client with configurable metrics
- Test database setup (async SQLite in-memory)
- Test data factories (incidents, actions, hypotheses)
- FastAPI test client with dependency overrides
"""
import asyncio
from datetime import datetime, timedelta
from typing import AsyncGenerator
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.perception.anomaly_detector import AnomalyDetection
from app.core.reasoning.hypothesis_generator import (
    Evidence,
    HypothesisItem,
    HypothesesResponse,
)
from app.database import get_db
from app.main import app
from app.models import Base
from app.models.action import Action, ActionStatus
from app.models.hypothesis import Hypothesis
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.schemas.incident import IncidentCreate
from app.services.llm_client import LLMResponse
from app.services.prometheus_client import MetricDataPoint, MetricResult

# Configure pytest-asyncio
pytest_plugins = ("pytest_asyncio",)


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture(scope="function")
async def test_engine() -> AsyncGenerator[AsyncEngine, None]:
    """
    Create async SQLite in-memory engine for testing.

    Uses StaticPool to ensure same connection is reused within a test.
    Each test gets a fresh database.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False,  # Set to True for SQL debugging
    )

    # Enable foreign keys for SQLite
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    await engine.dispose()


@pytest.fixture(scope="function")
async def test_db(test_engine: AsyncEngine) -> AsyncGenerator[AsyncSession, None]:
    """
    Provides async database session for testing.

    Each test gets a fresh database with all tables created.
    Automatically rolls back after test completion.
    """
    async_session_maker = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session_maker() as session:
        yield session
        await session.rollback()


# ============================================================================
# Mock LLM Client Fixtures
# ============================================================================


@pytest.fixture
def mock_llm_response() -> tuple[HypothesesResponse, LLMResponse]:
    """
    Default mock LLM response for hypothesis generation.

    Returns realistic hypotheses with evidence for memory leak scenario.
    Can be overridden in individual tests for different scenarios.
    """
    hypotheses_response = HypothesesResponse(
        hypotheses=[
            HypothesisItem(
                description="Memory leak in cache layer causing gradual heap growth",
                category="memory_leak",
                confidence_score=0.85,
                evidence=[
                    Evidence(
                        signal_type="metric",
                        signal_name="memory_usage",
                        observation="Memory usage increased from 2GB to 7.5GB over 2 hours",
                        relevance=0.95,
                    ),
                    Evidence(
                        signal_type="metric",
                        signal_name="gc_pressure",
                        observation="Garbage collection frequency increased by 300%",
                        relevance=0.80,
                    ),
                ],
                reasoning="The gradual, linear increase in memory usage combined with increased GC pressure strongly suggests a memory leak. The pattern matches typical cache-related leaks where objects are retained unnecessarily.",
            ),
            HypothesisItem(
                description="Database connection pool exhaustion causing resource contention",
                category="database_issue",
                confidence_score=0.65,
                evidence=[
                    Evidence(
                        signal_type="metric",
                        signal_name="db_connections",
                        observation="Connection pool at 95% capacity",
                        relevance=0.75,
                    ),
                ],
                reasoning="High connection pool usage could cause cascading failures, but this is more likely a symptom than root cause given the memory growth pattern.",
            ),
        ],
        overall_assessment="Service experiencing memory leak, likely in caching layer. Recommend pod restart and heap dump analysis.",
    )

    llm_response = LLMResponse(
        content='{"hypotheses": [...], "overall_assessment": "..."}',
        prompt_tokens=500,
        completion_tokens=350,
        total_tokens=850,
        model="claude-3-5-sonnet-20241022",
    )

    return hypotheses_response, llm_response


@pytest.fixture
def mock_llm_client(mock_llm_response):
    """
    Mock LLM client that returns deterministic responses.

    Can be configured per-test by overriding generate_structured return value.
    """
    mock_client = AsyncMock()
    mock_client.generate_structured = AsyncMock(return_value=mock_llm_response)
    return mock_client


# ============================================================================
# Mock Prometheus Client Fixtures
# ============================================================================


@pytest.fixture
def normal_metric_data() -> dict[str, list[MetricResult]]:
    """
    Normal (non-anomalous) metric data for testing.

    Returns metrics with stable values showing no anomalies.
    """
    now = datetime.utcnow()
    values = [
        MetricDataPoint(timestamp=(now - timedelta(minutes=i)).timestamp(), value=50.0)
        for i in range(20, 0, -1)
    ]

    return {
        "request_rate": [
            MetricResult(
                metric_name="http_requests_per_second",
                labels={"service": "test-service", "method": "GET"},
                values=values,
            )
        ],
        "error_rate": [
            MetricResult(
                metric_name="http_errors_per_second",
                labels={"service": "test-service"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(), value=0.1
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
        "latency_p95": [
            MetricResult(
                metric_name="http_request_duration_seconds",
                labels={"service": "test-service", "quantile": "0.95"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(), value=0.15
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
        "cpu_usage": [
            MetricResult(
                metric_name="cpu_usage_percent",
                labels={"service": "test-service"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(), value=45.0
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
        "memory_usage": [
            MetricResult(
                metric_name="memory_usage_bytes",
                labels={"service": "test-service"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(),
                        value=2_000_000_000.0,
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
    }


@pytest.fixture
def anomalous_metric_data() -> dict[str, list[MetricResult]]:
    """
    Anomalous metric data with clear spike for testing.

    Returns metrics showing memory leak pattern.
    """
    now = datetime.utcnow()

    # Memory gradually increasing (leak pattern)
    memory_values = [
        MetricDataPoint(
            timestamp=(now - timedelta(minutes=i)).timestamp(),
            value=2_000_000_000.0 + (i * 250_000_000.0),  # 250MB per minute
        )
        for i in range(20, 0, -1)
    ]

    # CPU spike in last few minutes
    cpu_values = [
        MetricDataPoint(
            timestamp=(now - timedelta(minutes=i)).timestamp(),
            value=40.0 if i > 5 else 95.0,  # Spike in last 5 minutes
        )
        for i in range(20, 0, -1)
    ]

    return {
        "request_rate": [
            MetricResult(
                metric_name="http_requests_per_second",
                labels={"service": "test-service"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(), value=100.0
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
        "error_rate": [
            MetricResult(
                metric_name="http_errors_per_second",
                labels={"service": "test-service"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(),
                        value=0.5 if i > 5 else 15.0,  # Error spike
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
        "latency_p95": [
            MetricResult(
                metric_name="http_request_duration_seconds",
                labels={"service": "test-service", "quantile": "0.95"},
                values=[
                    MetricDataPoint(
                        timestamp=(now - timedelta(minutes=i)).timestamp(),
                        value=0.15 if i > 5 else 2.5,  # Latency spike
                    )
                    for i in range(20, 0, -1)
                ],
            )
        ],
        "cpu_usage": [
            MetricResult(
                metric_name="cpu_usage_percent",
                labels={"service": "test-service"},
                values=cpu_values,
            )
        ],
        "memory_usage": [
            MetricResult(
                metric_name="memory_usage_bytes",
                labels={"service": "test-service"},
                values=memory_values,
            )
        ],
    }


@pytest.fixture
def mock_prometheus_client(normal_metric_data):
    """
    Mock Prometheus client that returns configurable metric data.

    Default returns normal (non-anomalous) metrics.
    Override in tests by setting mock_prometheus_client.get_service_metrics.return_value.
    """
    mock_client = AsyncMock()
    mock_client.get_service_metrics = AsyncMock(return_value=normal_metric_data)
    mock_client.query = AsyncMock(return_value=[])
    mock_client.query_range = AsyncMock(return_value=[])
    mock_client.close = AsyncMock()
    return mock_client


# ============================================================================
# Test Data Factory Fixtures
# ============================================================================


@pytest.fixture
def incident_factory(test_db: AsyncSession):
    """
    Factory function for creating test incidents.

    Usage:
        incident = await incident_factory(
            title="Test Incident",
            severity=IncidentSeverity.HIGH
        )
    """

    async def _create_incident(**kwargs) -> Incident:
        defaults = {
            "title": "Test Incident",
            "description": "Test incident description",
            "severity": IncidentSeverity.MEDIUM,
            "status": IncidentStatus.DETECTED,
            "affected_service": "test-service",
            "affected_components": ["component-1"],
            "detected_at": datetime.utcnow(),
            "detection_source": "test",
            "metrics_snapshot": {},
            "context": {},
        }
        defaults.update(kwargs)

        incident = Incident(**defaults)
        test_db.add(incident)
        await test_db.commit()
        await test_db.refresh(incident)
        return incident

    return _create_incident


@pytest.fixture
def hypothesis_factory(test_db: AsyncSession):
    """
    Factory function for creating test hypotheses.

    Usage:
        hypothesis = await hypothesis_factory(
            incident_id=incident.id,
            confidence_score=0.85
        )
    """

    async def _create_hypothesis(incident_id: str, **kwargs) -> Hypothesis:
        defaults = {
            "incident_id": incident_id,
            "description": "Test hypothesis",
            "category": "memory_leak",
            "confidence_score": 0.75,
            "rank": 1,
            "evidence": [
                {
                    "signal_type": "metric",
                    "signal_name": "memory_usage",
                    "observation": "Memory increased by 50%",
                    "relevance": 0.9,
                }
            ],
            "reasoning": "Test reasoning",
        }
        defaults.update(kwargs)

        hypothesis = Hypothesis(**defaults)
        test_db.add(hypothesis)
        await test_db.commit()
        await test_db.refresh(hypothesis)
        return hypothesis

    return _create_hypothesis


@pytest.fixture
def action_factory(test_db: AsyncSession):
    """
    Factory function for creating test actions.

    Usage:
        action = await action_factory(
            incident_id=incident.id,
            action_type="restart_pod"
        )
    """

    async def _create_action(incident_id: str, **kwargs) -> Action:
        defaults = {
            "incident_id": incident_id,
            "action_type": "restart_pod",
            "target_service": "test-service",
            "target_resource": "test-service-pod-abc123",
            "description": "Restart pod to recover from issue",
            "status": ActionStatus.PENDING_APPROVAL,
            "risk_level": "LOW",
            "risk_score": 0.2,
            "requires_approval": True,
            "execution_mode": "dry_run",
            "parameters": {"namespace": "default", "deployment": "test-service"},
            "blast_radius": "single_pod",
        }
        defaults.update(kwargs)

        action = Action(**defaults)
        test_db.add(action)
        await test_db.commit()
        await test_db.refresh(action)
        return action

    return _create_action


@pytest.fixture
def anomaly_detection_factory():
    """
    Factory function for creating AnomalyDetection objects.

    Usage:
        anomaly = anomaly_detection_factory(
            metric_name="cpu_usage",
            current_value=95.0
        )
    """

    def _create_anomaly(**kwargs) -> AnomalyDetection:
        defaults = {
            "metric_name": "cpu_usage",
            "is_anomaly": True,
            "confidence": 0.85,
            "current_value": 90.0,
            "expected_value": 50.0,
            "deviation_sigma": 4.0,
            "timestamp": datetime.utcnow(),
            "context": {"labels": {"service": "test-service"}},
        }
        defaults.update(kwargs)
        return AnomalyDetection(**defaults)

    return _create_anomaly


# ============================================================================
# FastAPI Test Client Fixtures
# ============================================================================


@pytest.fixture
async def async_client(
    test_db: AsyncSession,
    mock_llm_client,
    mock_prometheus_client,
) -> AsyncGenerator[AsyncClient, None]:
    """
    Async HTTP client for testing FastAPI endpoints.

    Automatically overrides dependencies:
    - Database session uses test_db
    - LLM client uses mock_llm_client
    - Prometheus client uses mock_prometheus_client

    Usage:
        response = await async_client.post(
            "/api/v1/incidents",
            json={"title": "Test"}
        )
    """

    # Override dependencies
    async def override_get_db():
        yield test_db

    def override_get_llm_client():
        return mock_llm_client

    def override_get_prometheus_client():
        return mock_prometheus_client

    app.dependency_overrides[get_db] = override_get_db

    # Note: For LLM and Prometheus, we'll need to mock at the service level
    # since they use singleton patterns. This is handled in integration tests.

    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

    # Clear overrides
    app.dependency_overrides.clear()


# ============================================================================
# Utility Fixtures
# ============================================================================


@pytest.fixture
def sample_service_context() -> dict:
    """
    Sample service context data for testing.
    """
    return {
        "tier": "tier1",
        "team": "platform",
        "on_call": "oncall-platform@example.com",
        "dependencies": ["database", "redis", "payment-gateway"],
        "dependent_services": ["frontend", "api-gateway"],
        "recent_deployments": ["v1.2.3 deployed 2 hours ago"],
    }


@pytest.fixture(autouse=True)
def reset_singletons():
    """
    Reset singleton instances between tests.

    Some services use singleton patterns (get_llm_client, get_prometheus_client).
    This fixture ensures clean state between tests.
    """
    # Import here to avoid circular imports
    import app.services.llm_client as llm_module
    import app.services.prometheus_client as prom_module

    # Reset singleton caches if they exist
    if hasattr(llm_module, "_llm_client_instance"):
        llm_module._llm_client_instance = None
    if hasattr(prom_module, "_prometheus_client_instance"):
        prom_module._prometheus_client_instance = None

    yield

    # Cleanup after test
    if hasattr(llm_module, "_llm_client_instance"):
        llm_module._llm_client_instance = None
    if hasattr(prom_module, "_prometheus_client_instance"):
        prom_module._prometheus_client_instance = None
