"""
Unit tests for anomaly detection.

Senior Engineering Note:
- Tests core business logic in isolation
- Uses fixtures for test data
- Mocks external dependencies
- Covers edge cases
"""
from datetime import datetime, timezone

import pytest

from app.core.perception.anomaly_detector import (
    AnomalyDetection,
    AnomalyDetector,
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


class TestEnsembleDetection:
    """Tests for the multi-strategy (z-score + EWMA + MAD) ensemble."""

    @staticmethod
    def _metric(values: list[float], name: str = "cpu_usage") -> MetricResult:
        return MetricResult(
            metric_name=name,
            labels={"service": "test-service"},
            values=[
                MetricDataPoint(timestamp=float(i), value=v)
                for i, v in enumerate(values)
            ],
        )

    def test_gradual_drift_evades_zscore_but_ensemble_catches_it(self):
        """
        A slow ramp: the rolling mean moves with the metric, so the final point
        is only ~2 sigma above baseline and pure z-score misses it. EWMA drift
        accumulates and the ensemble flags it.
        """
        # 30 points ramping 100 -> 158 (~2/step), mild noise.
        ramp = [100.0 + i * 2.0 + (1.5 if i % 2 else -1.5) for i in range(30)]
        metric = self._metric(ramp)

        zscore_only = AnomalyDetector(threshold_sigma=3.0, methods=["zscore"])
        assert zscore_only.detect(metric) == [], "z-score alone should miss the drift"

        ensemble = AnomalyDetector(threshold_sigma=3.0)
        anomalies = ensemble.detect(metric)
        assert len(anomalies) == 1
        assert "ewma" in anomalies[0].methods_triggered

    def test_mad_survives_polluted_baseline(self):
        """
        One historical spike inflates stdev enough that a second, real anomaly
        is < 3 sigma by z-score. MAD ignores the outlier and still flags it.
        """
        values = [50.0] * 25
        values[5] = 400.0  # old spike pollutes the baseline stdev
        values.append(140.0)  # genuine anomaly on the latest point
        metric = self._metric(values)

        zscore_only = AnomalyDetector(threshold_sigma=3.0, methods=["zscore"])
        assert zscore_only.detect(metric) == []

        ensemble = AnomalyDetector(threshold_sigma=3.0)
        anomalies = ensemble.detect(metric)
        assert len(anomalies) == 1
        assert "mad" in anomalies[0].methods_triggered

    def test_single_weak_vote_is_suppressed_by_quorum(self):
        """One lone, non-extreme method firing is suppressed when min_votes=2."""
        # Tight baseline (stdev ~0.31); last point ~3.9 sigma up. Only z-score
        # reacts, and 3.9 sigma is below the strong-single cutoff (4.5).
        values = [100.0 + (0.3 if i % 2 else -0.3) for i in range(20)]
        values.append(101.2)
        metric = self._metric(values)

        # min_votes=1: the single z-score vote is enough to flag.
        lone = AnomalyDetector(threshold_sigma=3.0, min_votes=1).detect(metric)
        assert len(lone) == 1
        assert lone[0].methods_triggered == ["zscore"]

        # min_votes=2: that same lone vote is now suppressed.
        assert AnomalyDetector(threshold_sigma=3.0, min_votes=2).detect(metric) == []

    def test_flat_baseline_does_not_explode_into_false_positive_critical(self):
        """
        Regression: a near-idle metric whose baseline samples are all ~equal up
        to floating-point jitter (e.g. Prometheus rate() noise on a near-zero-
        traffic service) must not turn an unremarkable move into an absurd
        sigma reading. Caught live 2026-09-12: request_rate baseline ~0.067
        (jitter-only variance), a drop to 0.044 was reported as "10578 sigma,
        critical" -- dividing by a near-machine-epsilon stdev/MAD.
        """
        values = [0.0667 + (1e-9 if i % 2 else -1e-9) for i in range(20)]
        values.append(0.0444)  # ~33% real drop, tiny absolute magnitude
        metric = self._metric(values, name="request_rate")

        anomalies = AnomalyDetector(threshold_sigma=3.0).detect(metric)

        if anomalies:
            assert anomalies[0].deviation_sigma < 100, (
                "spread floor should keep sigma bounded instead of exploding "
                f"on float jitter, got {anomalies[0].deviation_sigma}"
            )

    def test_extreme_single_method_flags_alone(self):
        """An unambiguous 10x spike triggers even if only one method's model holds."""
        values = [50.0] * 20 + [500.0]
        metric = self._metric(values)

        detector = AnomalyDetector(threshold_sigma=3.0, min_votes=3)
        anomalies = detector.detect(metric)
        assert len(anomalies) == 1
        assert anomalies[0].context["strong_single"] is True

    def test_methods_recorded_in_context(self):
        values = [50.0] * 20 + [250.0]
        metric = self._metric(values)
        anomaly = AnomalyDetector(threshold_sigma=3.0).detect(metric)[0]

        assert set(anomaly.context["methods"]) == {"zscore", "ewma", "mad"}
        assert anomaly.context["votes"] == len(anomaly.methods_triggered)

    def test_method_subset_is_honoured(self):
        detector = AnomalyDetector(methods=["zscore", "mad"])
        assert detector.methods == ("zscore", "mad")
        values = [50.0] * 20 + [250.0]
        anomaly = detector.detect(self._metric(values))[0]
        assert set(anomaly.context["methods"]) == {"zscore", "mad"}


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
            timestamp=datetime.now(timezone.utc),
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
            timestamp=datetime.now(timezone.utc),
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
            timestamp=datetime.now(timezone.utc),
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
            timestamp=datetime.now(timezone.utc),
            context={},
        )

        category = categorize_anomaly(anomaly)
        assert category == "cpu_spike"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
