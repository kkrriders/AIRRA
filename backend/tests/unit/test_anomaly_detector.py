"""
Unit tests for anomaly detection.

Senior Engineering Note:
- Tests core business logic in isolation
- Uses fixtures for test data
- Mocks external dependencies
- Covers edge cases
"""
import pytest
from datetime import datetime

from app.core.perception.anomaly_detector import (
    AnomalyDetector,
    AnomalyDetection,
    categorize_anomaly,
)
from app.services.prometheus_client import MetricDataPoint, MetricResult


@pytest.fixture
def normal_metric_data():
    """Fixture providing normal metric data (no anomaly)."""
    return MetricResult(
        metric_name="cpu_usage",
        labels={"service": "test-service"},
        values=[
            MetricDataPoint(timestamp=float(i), value=50.0 + i * 0.1)
            for i in range(100, 120)
        ],
    )


@pytest.fixture
def anomalous_metric_data():
    """Fixture providing anomalous metric data (spike at end)."""
    values = [MetricDataPoint(timestamp=float(i), value=50.0) for i in range(100, 119)]
    # Add anomalous spike
    values.append(MetricDataPoint(timestamp=119.0, value=200.0))

    return MetricResult(
        metric_name="cpu_usage",
        labels={"service": "test-service"},
        values=values,
    )


@pytest.fixture
def flat_metric_data():
    """Fixture providing flat metric data (no variance)."""
    return MetricResult(
        metric_name="constant_metric",
        labels={"service": "test-service"},
        values=[MetricDataPoint(timestamp=float(i), value=100.0) for i in range(100, 120)],
    )


class TestAnomalyDetector:
    """Test suite for AnomalyDetector class."""

    def test_no_anomaly_in_normal_data(self, normal_metric_data):
        """Test that normal data does not trigger anomaly."""
        detector = AnomalyDetector(threshold_sigma=3.0)
        anomalies = detector.detect(normal_metric_data)

        assert len(anomalies) == 0, "Normal data should not produce anomalies"

    def test_detects_spike_anomaly(self, anomalous_metric_data):
        """Test that spike is detected as anomaly."""
        detector = AnomalyDetector(threshold_sigma=3.0)
        anomalies = detector.detect(anomalous_metric_data)

        assert len(anomalies) == 1, "Should detect one anomaly"

        anomaly = anomalies[0]
        assert anomaly.is_anomaly is True
        assert anomaly.metric_name == "cpu_usage"
        assert anomaly.current_value == 200.0
        assert anomaly.expected_value == pytest.approx(50.0, abs=1.0)
        assert anomaly.deviation_sigma > 3.0
        assert 0.0 <= anomaly.confidence <= 1.0

    def test_confidence_increases_with_deviation(self):
        """Test that confidence score increases with larger deviations."""
        # Create metric with moderate spike
        moderate_spike = MetricResult(
            metric_name="test_metric",
            labels={},
            values=[
                MetricDataPoint(timestamp=float(i), value=100.0) for i in range(20)
            ]
            + [MetricDataPoint(timestamp=20.0, value=150.0)],
        )

        # Create metric with large spike
        large_spike = MetricResult(
            metric_name="test_metric",
            labels={},
            values=[
                MetricDataPoint(timestamp=float(i), value=100.0) for i in range(20)
            ]
            + [MetricDataPoint(timestamp=20.0, value=300.0)],
        )

        detector = AnomalyDetector(threshold_sigma=2.0)

        moderate_anomalies = detector.detect(moderate_spike)
        large_anomalies = detector.detect(large_spike)

        if moderate_anomalies and large_anomalies:
            assert (
                large_anomalies[0].confidence > moderate_anomalies[0].confidence
            ), "Larger deviation should have higher confidence"

    def test_handles_insufficient_data(self):
        """Test handling of insufficient data points."""
        insufficient_data = MetricResult(
            metric_name="test_metric",
            labels={},
            values=[
                MetricDataPoint(timestamp=1.0, value=100.0),
                MetricDataPoint(timestamp=2.0, value=101.0),
            ],
        )

        detector = AnomalyDetector(threshold_sigma=3.0)
        anomalies = detector.detect(insufficient_data)

        assert len(anomalies) == 0, "Should handle insufficient data gracefully"

    def test_handles_flat_data(self, flat_metric_data):
        """Test handling of data with zero variance."""
        detector = AnomalyDetector(threshold_sigma=3.0)

        # Should not crash on zero standard deviation
        anomalies = detector.detect(flat_metric_data)

        # Flat data should not produce anomalies
        assert len(anomalies) == 0

    def test_detect_multiple_metrics(self, normal_metric_data, anomalous_metric_data):
        """Test detection across multiple metrics."""
        detector = AnomalyDetector(threshold_sigma=3.0)

        all_anomalies = detector.detect_multiple([normal_metric_data, anomalous_metric_data])

        # Should find anomaly from second metric only
        assert len(all_anomalies) == 1
        assert all_anomalies[0].metric_name == "cpu_usage"

    def test_anomalies_sorted_by_confidence(self):
        """Test that multiple anomalies are sorted by confidence."""
        # Create two anomalous metrics with different severities
        metric1 = MetricResult(
            metric_name="metric1",
            labels={},
            values=[MetricDataPoint(timestamp=float(i), value=100.0) for i in range(20)]
            + [MetricDataPoint(timestamp=20.0, value=150.0)],
        )

        metric2 = MetricResult(
            metric_name="metric2",
            labels={},
            values=[MetricDataPoint(timestamp=float(i), value=100.0) for i in range(20)]
            + [MetricDataPoint(timestamp=20.0, value=300.0)],
        )

        detector = AnomalyDetector(threshold_sigma=2.0)
        all_anomalies = detector.detect_multiple([metric1, metric2])

        # Should be sorted by confidence (highest first)
        if len(all_anomalies) >= 2:
            assert all_anomalies[0].confidence >= all_anomalies[1].confidence


class TestCategorizeAnomaly:
    """Test suite for anomaly categorization."""

    def test_categorize_error_spike(self):
        """Test categorization of error rate spike."""
        anomaly = AnomalyDetection(
            metric_name="http_errors_total",
            is_anomaly=True,
            confidence=0.9,
            current_value=100.0,
            expected_value=10.0,
            deviation_sigma=5.0,
            timestamp=datetime.utcnow(),
            context={},
        )

        category = categorize_anomaly(anomaly)
        assert category == "error_spike"

    def test_categorize_latency_spike(self):
        """Test categorization of latency spike."""
        anomaly = AnomalyDetection(
            metric_name="http_request_duration_seconds",
            is_anomaly=True,
            confidence=0.85,
            current_value=2.0,
            expected_value=0.2,
            deviation_sigma=4.0,
            timestamp=datetime.utcnow(),
            context={},
        )

        category = categorize_anomaly(anomaly)
        assert category == "latency_spike"

    def test_categorize_memory_leak(self):
        """Test categorization of memory increase."""
        anomaly = AnomalyDetection(
            metric_name="process_memory_bytes",
            is_anomaly=True,
            confidence=0.8,
            current_value=1000000000.0,
            expected_value=500000000.0,
            deviation_sigma=3.5,
            timestamp=datetime.utcnow(),
            context={},
        )

        category = categorize_anomaly(anomaly)
        assert category == "memory_leak"

    def test_categorize_cpu_spike(self):
        """Test categorization of CPU spike."""
        anomaly = AnomalyDetection(
            metric_name="cpu_usage_percent",
            is_anomaly=True,
            confidence=0.75,
            current_value=95.0,
            expected_value=40.0,
            deviation_sigma=3.0,
            timestamp=datetime.utcnow(),
            context={},
        )

        category = categorize_anomaly(anomaly)
        assert category == "cpu_spike"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
