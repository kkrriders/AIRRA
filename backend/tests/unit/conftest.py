"""
Unit test specific fixtures.

This module provides fixtures for isolated unit testing of individual components
without external dependencies.
"""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.perception.anomaly_detector import AnomalyDetection
from app.services.prometheus_client import MetricDataPoint, MetricResult


# ============================================================================
# Anomaly Detector Test Fixtures
# ============================================================================


@pytest.fixture
def normal_metric_data():
    """
    Fixture providing normal metric data (no anomaly).

    Returns MetricResult with stable values around mean=50.0.
    """
    return MetricResult(
        metric_name="cpu_usage",
        labels={"service": "test-service"},
        values=[MetricDataPoint(timestamp=float(i), value=50.0) for i in range(30)],
    )


@pytest.fixture
def anomalous_metric_data():
    """
    Fixture providing anomalous metric data (spike at end).

    Returns MetricResult with values around 50.0, then spike to 150.0.
    """
    return MetricResult(
        metric_name="cpu_usage",
        labels={"service": "test-service"},
        values=[MetricDataPoint(timestamp=float(i), value=50.0) for i in range(20)]
        + [
            MetricDataPoint(timestamp=20.0, value=150.0),
            MetricDataPoint(timestamp=21.0, value=145.0),
        ],
    )


@pytest.fixture
def flat_metric_data():
    """
    Fixture providing flat metric data (no variance).

    Returns MetricResult with identical values (zero standard deviation).
    """
    return MetricResult(
        metric_name="constant_metric",
        labels={"service": "test-service"},
        values=[MetricDataPoint(timestamp=float(i), value=100.0) for i in range(30)],
    )


@pytest.fixture
def insufficient_data():
    """
    Fixture providing insufficient metric data (< 10 points).

    Returns MetricResult with only 5 data points.
    """
    return MetricResult(
        metric_name="sparse_metric",
        labels={"service": "test-service"},
        values=[MetricDataPoint(timestamp=float(i), value=50.0) for i in range(5)],
    )


@pytest.fixture
def multiple_spikes_metric_data():
    """
    Fixture with multiple spikes for testing detection consistency.
    """
    values = [MetricDataPoint(timestamp=float(i), value=50.0) for i in range(30)]
    # Add spikes at positions 10 and 25
    values[10] = MetricDataPoint(timestamp=10.0, value=150.0)
    values[25] = MetricDataPoint(timestamp=25.0, value=160.0)

    return MetricResult(
        metric_name="cpu_usage",
        labels={"service": "test-service"},
        values=values,
    )


# ============================================================================
# Signal Correlator Test Fixtures
# ============================================================================


@pytest.fixture
def sample_metric_signal():
    """
    Sample metric signal for correlation testing.
    """
    from app.core.perception.signal_correlator import Signal, SignalType

    return Signal(
        signal_type=SignalType.METRIC,
        source="prometheus",
        name="high_cpu_usage",
        timestamp=datetime.utcnow(),
        value=95.0,
        labels={"service": "payment-service"},
        context={"deviation_sigma": 4.5, "expected": 50.0},
        anomaly_score=0.85,
    )


@pytest.fixture
def sample_log_signal():
    """
    Sample log signal for correlation testing.
    """
    from app.core.perception.signal_correlator import Signal, SignalType

    return Signal(
        signal_type=SignalType.LOG,
        source="loki",
        name="error_spike",
        timestamp=datetime.utcnow(),
        value=50.0,  # 50 errors per minute
        labels={"service": "payment-service"},
        context={"error_pattern": "OutOfMemoryError", "log_level": "ERROR"},
        anomaly_score=0.90,
    )


@pytest.fixture
def sample_trace_signal():
    """
    Sample trace signal for correlation testing.
    """
    from app.core.perception.signal_correlator import Signal, SignalType

    return Signal(
        signal_type=SignalType.TRACE,
        source="jaeger",
        name="slow_requests",
        timestamp=datetime.utcnow(),
        value=2.5,  # 2.5 seconds latency
        labels={"service": "payment-service"},
        context={"span_name": "database_query", "p95_latency": 2.5},
        anomaly_score=0.80,
    )


@pytest.fixture
def correlated_signals(sample_metric_signal, sample_log_signal):
    """
    Multiple signals from same service and time window (should correlate).
    """
    return [sample_metric_signal, sample_log_signal]


@pytest.fixture
def uncorrelated_signals():
    """
    Signals from different services (should not correlate).
    """
    from app.core.perception.signal_correlator import Signal, SignalType

    now = datetime.utcnow()
    return [
        Signal(
            signal_type=SignalType.METRIC,
            source="prometheus",
            name="high_cpu",
            timestamp=now,
            value=90.0,
            labels={"service": "service-a"},
            context={},
            anomaly_score=0.8,
        ),
        Signal(
            signal_type=SignalType.LOG,
            source="loki",
            name="errors",
            timestamp=now,
            value=10.0,
            labels={"service": "service-b"},
            context={},
            anomaly_score=0.7,
        ),
    ]


# ============================================================================
# Hypothesis Generator Test Fixtures
# ============================================================================


@pytest.fixture
def memory_leak_anomalies():
    """
    Anomalies indicating a memory leak pattern.
    """
    now = datetime.utcnow()
    return [
        AnomalyDetection(
            metric_name="memory_usage_bytes",
            is_anomaly=True,
            confidence=0.90,
            current_value=7_500_000_000.0,  # 7.5GB
            expected_value=2_000_000_000.0,  # 2GB
            deviation_sigma=5.5,
            timestamp=now,
            context={"labels": {"service": "payment-service"}},
        ),
        AnomalyDetection(
            metric_name="gc_time_percent",
            is_anomaly=True,
            confidence=0.85,
            current_value=45.0,  # 45% time in GC
            expected_value=5.0,  # 5% normal
            deviation_sigma=8.0,
            timestamp=now,
            context={"labels": {"service": "payment-service"}},
        ),
    ]


@pytest.fixture
def cpu_spike_anomalies():
    """
    Anomalies indicating a CPU spike.
    """
    now = datetime.utcnow()
    return [
        AnomalyDetection(
            metric_name="cpu_usage_percent",
            is_anomaly=True,
            confidence=0.88,
            current_value=98.0,
            expected_value=45.0,
            deviation_sigma=6.5,
            timestamp=now,
            context={"labels": {"service": "api-gateway"}},
        ),
        AnomalyDetection(
            metric_name="thread_count",
            is_anomaly=True,
            confidence=0.75,
            current_value=500.0,
            expected_value=50.0,
            deviation_sigma=9.0,
            timestamp=now,
            context={"labels": {"service": "api-gateway"}},
        ),
    ]


@pytest.fixture
def network_issue_anomalies():
    """
    Anomalies indicating network issues.
    """
    now = datetime.utcnow()
    return [
        AnomalyDetection(
            metric_name="request_latency_p95",
            is_anomaly=True,
            confidence=0.92,
            current_value=5.0,  # 5 seconds
            expected_value=0.2,  # 200ms
            deviation_sigma=12.0,
            timestamp=now,
            context={"labels": {"service": "checkout-service"}},
        ),
        AnomalyDetection(
            metric_name="timeout_rate",
            is_anomaly=True,
            confidence=0.87,
            current_value=25.0,  # 25% timeout rate
            expected_value=0.1,  # 0.1%
            deviation_sigma=10.0,
            timestamp=now,
            context={"labels": {"service": "checkout-service"}},
        ),
    ]


# ============================================================================
# Action Selector Test Fixtures
# ============================================================================


@pytest.fixture
def memory_leak_hypothesis():
    """
    Sample hypothesis for memory leak scenario.
    """
    from app.core.reasoning.hypothesis_generator import Evidence, HypothesisItem

    return HypothesisItem(
        description="Memory leak in cache layer",
        category="memory_leak",
        confidence_score=0.85,
        evidence=[
            Evidence(
                signal_type="metric",
                signal_name="memory_usage",
                observation="Memory increased from 2GB to 7.5GB",
                relevance=0.95,
            )
        ],
        reasoning="Gradual memory growth indicates leak",
    )


@pytest.fixture
def cpu_spike_hypothesis():
    """
    Sample hypothesis for CPU spike scenario.
    """
    from app.core.reasoning.hypothesis_generator import Evidence, HypothesisItem

    return HypothesisItem(
        description="CPU spike due to infinite loop in request handler",
        category="cpu_spike",
        confidence_score=0.80,
        evidence=[
            Evidence(
                signal_type="metric",
                signal_name="cpu_usage",
                observation="CPU jumped to 98%",
                relevance=0.90,
            )
        ],
        reasoning="Sudden CPU spike suggests runaway process",
    )


@pytest.fixture
def database_issue_hypothesis():
    """
    Sample hypothesis for database issue.
    """
    from app.core.reasoning.hypothesis_generator import Evidence, HypothesisItem

    return HypothesisItem(
        description="Database connection pool exhausted",
        category="database_issue",
        confidence_score=0.75,
        evidence=[
            Evidence(
                signal_type="metric",
                signal_name="db_connections",
                observation="Connection pool at 100%",
                relevance=0.85,
            )
        ],
        reasoning="All connections in use, requests timing out",
    )


# ============================================================================
# LLM Client Test Fixtures
# ============================================================================


@pytest.fixture
def mock_anthropic_response():
    """
    Mock Anthropic API response structure.
    """
    mock_content = Mock()
    mock_content.text = '{"hypotheses": [{"description": "Test", "category": "memory_leak", "confidence_score": 0.8, "evidence": [], "reasoning": "Test"}], "overall_assessment": "Test assessment"}'

    mock_usage = Mock()
    mock_usage.input_tokens = 100
    mock_usage.output_tokens = 50

    mock_response = Mock()
    mock_response.content = [mock_content]
    mock_response.usage = mock_usage
    mock_response.model = "claude-3-5-sonnet-20241022"

    return mock_response


@pytest.fixture
def mock_openai_response():
    """
    Mock OpenAI API response structure.
    """
    mock_choice = Mock()
    mock_message = Mock()
    mock_message.content = '{"hypotheses": [{"description": "Test", "category": "memory_leak", "confidence_score": 0.8, "evidence": [], "reasoning": "Test"}], "overall_assessment": "Test assessment"}'
    mock_choice.message = mock_message

    mock_usage = Mock()
    mock_usage.prompt_tokens = 100
    mock_usage.completion_tokens = 50
    mock_usage.total_tokens = 150

    mock_response = Mock()
    mock_response.choices = [mock_choice]
    mock_response.usage = mock_usage
    mock_response.model = "gpt-4-turbo-preview"

    return mock_response


# ============================================================================
# Prometheus Client Test Fixtures
# ============================================================================


@pytest.fixture
def mock_prometheus_vector_response():
    """
    Mock Prometheus instant query response (vector type).
    """
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [
                {
                    "metric": {"__name__": "cpu_usage", "service": "test-service"},
                    "value": [1704067200.0, "75.5"],
                }
            ],
        },
    }


@pytest.fixture
def mock_prometheus_matrix_response():
    """
    Mock Prometheus range query response (matrix type).
    """
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [
                {
                    "metric": {"__name__": "memory_usage", "service": "test-service"},
                    "values": [
                        [1704067200.0, "2000000000"],
                        [1704067260.0, "2100000000"],
                        [1704067320.0, "2200000000"],
                    ],
                }
            ],
        },
    }


@pytest.fixture
def mock_prometheus_empty_response():
    """
    Mock Prometheus response with no results.
    """
    return {"status": "success", "data": {"resultType": "vector", "result": []}}


# ============================================================================
# Kubernetes Executor Test Fixtures
# ============================================================================


@pytest.fixture
def mock_k8s_client():
    """
    Mock Kubernetes client for testing executors.
    """
    mock_client = Mock()

    # Mock CoreV1Api
    mock_core_v1 = Mock()
    mock_core_v1.list_namespaced_pod = Mock(
        return_value=Mock(items=[Mock(metadata=Mock(name="test-pod-123"))])
    )
    mock_core_v1.delete_namespaced_pod = Mock()

    # Mock AppsV1Api
    mock_apps_v1 = Mock()
    mock_deployment = Mock()
    mock_deployment.spec.replicas = 3
    mock_deployment.status.ready_replicas = 3
    mock_apps_v1.read_namespaced_deployment = Mock(return_value=mock_deployment)
    mock_apps_v1.patch_namespaced_deployment_scale = Mock()

    mock_client.CoreV1Api = Mock(return_value=mock_core_v1)
    mock_client.AppsV1Api = Mock(return_value=mock_apps_v1)

    return mock_client


@pytest.fixture
def pod_restart_parameters():
    """
    Sample parameters for pod restart action.
    """
    return {
        "namespace": "production",
        "deployment": "payment-service",
        "pod_name": "payment-service-abc123",
        "graceful_shutdown": True,
    }


@pytest.fixture
def scale_up_parameters():
    """
    Sample parameters for scaling up.
    """
    return {
        "namespace": "production",
        "deployment": "api-gateway",
        "replicas": 5,
        "current_replicas": 3,
    }


@pytest.fixture
def scale_down_parameters():
    """
    Sample parameters for scaling down.
    """
    return {
        "namespace": "production",
        "deployment": "worker-service",
        "replicas": 2,
        "current_replicas": 5,
    }
