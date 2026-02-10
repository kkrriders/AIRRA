"""
Unit tests for signal correlation.

Tests the multi-signal correlation engine that combines metrics, logs,
and traces to identify real incidents while eliminating false positives.

Senior Engineering Note:
- Tests time-window correlation logic
- Validates signal diversity requirements
- Verifies confidence scoring with weighted signals
- Covers edge cases and error scenarios
"""
import pytest
from datetime import datetime, timedelta

from app.core.perception.anomaly_detector import AnomalyDetection
from app.core.perception.signal_correlator import (
    CorrelatedIncident,
    Signal,
    SignalCorrelator,
    SignalType,
)


class TestSignalCorrelator:
    """Test suite for SignalCorrelator class."""

    async def test_correlates_multi_signal_incident(
        self, sample_metric_signal, sample_log_signal
    ):
        """
        Test correlation of metric + log signals from same service.

        Both signals are from payment-service and within time window.
        Should create correlated incident with high confidence.
        """
        correlator = SignalCorrelator(
            correlation_window_seconds=300,  # 5 minutes
            min_signal_count=2,
        )

        signals = [sample_metric_signal, sample_log_signal]
        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 1, "Should create one correlated incident"
        incident = incidents[0]

        assert incident.service == "payment-service"
        assert len(incident.signals) == 2
        assert incident.confidence >= 0.6, "Should have high confidence"
        assert "payment-service" in incident.title
        assert SignalType.METRIC in {s.signal_type for s in incident.signals}
        assert SignalType.LOG in {s.signal_type for s in incident.signals}

    async def test_requires_minimum_signal_count(self):
        """
        Test that correlation requires minimum number of signals.

        Single signal should not create incident (prevents false positives).
        """
        correlator = SignalCorrelator(min_signal_count=2)

        single_signal = Signal(
            signal_type=SignalType.METRIC,
            source="prometheus",
            name="cpu_high",
            value=90.0,
            timestamp=datetime.utcnow(),
            labels={"service": "api-gateway"},
            anomaly_score=0.85,
        )

        incidents = await correlator.correlate_signals([single_signal])

        assert len(incidents) == 0, "Single signal should not create incident"

    async def test_requires_signal_diversity(self):
        """
        Test that correlation requires signals from different types.

        Multiple metric signals of same type should not correlate
        (prevents metric-only false positives).
        """
        correlator = SignalCorrelator(min_signal_count=2)

        now = datetime.utcnow()
        # Two metric signals from same service
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="memory_high",
                value=7500000000.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.80,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert (
            len(incidents) == 0
        ), "Same-type signals should not create incident without diversity"

    async def test_time_window_correlation(self):
        """
        Test that signals outside time window don't correlate.

        Signals separated by > 5 minutes should create separate incidents.
        """
        correlator = SignalCorrelator(correlation_window_seconds=300)  # 5 minutes

        now = datetime.utcnow()

        # Signals separated by 10 minutes (outside window)
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="error_spike",
                value=50.0,
                timestamp=now + timedelta(minutes=10),  # 10 minutes later
                labels={"service": "api-gateway"},
                anomaly_score=0.80,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert (
            len(incidents) == 0
        ), "Signals outside time window should not correlate"

    async def test_time_window_correlation_within_window(self):
        """
        Test that signals within time window DO correlate.

        Signals within 5 minutes should create correlated incident.
        """
        correlator = SignalCorrelator(correlation_window_seconds=300)  # 5 minutes

        now = datetime.utcnow()

        # Signals within 2 minutes (inside window)
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="error_spike",
                value=50.0,
                timestamp=now + timedelta(minutes=2),  # 2 minutes later
                labels={"service": "api-gateway"},
                anomaly_score=0.80,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 1, "Signals within window should correlate"
        assert len(incidents[0].signals) == 2

    async def test_service_filtering(self):
        """
        Test filtering signals by service.

        Should only correlate signals matching the service filter.
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        # Signals from different services
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "service-a"},
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=50.0,
                timestamp=now,
                labels={"service": "service-a"},
                anomaly_score=0.80,
            ),
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=95.0,
                timestamp=now,
                labels={"service": "service-b"},
                anomaly_score=0.90,
            ),
        ]

        # Filter for service-a only
        incidents = await correlator.correlate_signals(signals, service_filter="service-a")

        assert len(incidents) == 1, "Should find one incident for service-a"
        assert incidents[0].service == "service-a"
        assert all(
            s.labels.get("service") == "service-a" for s in incidents[0].signals
        ), "All signals should be from service-a"

    async def test_confidence_calculation_with_diversity_bonus(self):
        """
        Test confidence calculation includes diversity bonus.

        More signal types should increase confidence due to diversity bonus.
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        # Three different signal types (metric, log, trace)
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.70,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=50.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.70,
            ),
            Signal(
                signal_type=SignalType.TRACE,
                source="jaeger",
                name="slow_traces",
                value=2.5,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.70,
            ),
        ]

        confidence = correlator._calculate_confidence(signals)

        # Diversity bonus: 3 types * 0.1 = 0.3
        # Weighted avg: ~0.70
        # Total: ~1.0 (capped)
        assert confidence >= 0.90, "Three signal types should have high confidence"

    async def test_confidence_calculation_weighted_signals(self):
        """
        Test that confidence calculation uses weighted scoring.

        Metrics have 0.4 weight, logs 0.3, traces 0.3.
        """
        correlator = SignalCorrelator(
            metric_weight=0.4, log_weight=0.3, trace_weight=0.3
        )

        now = datetime.utcnow()

        # Metric with high score, log with low score
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.90,  # High
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=10.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.50,  # Low
            ),
        ]

        confidence = correlator._calculate_confidence(signals)

        # Weighted avg: (0.90 * 0.4) + (0.50 * 0.3) / (0.4 + 0.3) = 0.74
        # Diversity bonus: 2 types * 0.1 = 0.2
        # Total: ~0.94
        assert 0.8 <= confidence <= 1.0, f"Expected weighted confidence ~0.94, got {confidence}"

    async def test_severity_score_calculation(self):
        """
        Test severity score is average of max and avg anomaly scores.
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.90,  # Max
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=50.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.70,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 1
        incident = incidents[0]

        # Max: 0.90, Avg: (0.90 + 0.70)/2 = 0.80
        # Severity: (0.90 + 0.80)/2 = 0.85
        expected_severity = 0.85
        assert (
            abs(incident.severity_score - expected_severity) < 0.01
        ), f"Expected severity {expected_severity}, got {incident.severity_score}"

    async def test_sorts_incidents_by_confidence(self):
        """
        Test that correlated incidents are sorted by confidence (highest first).
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        # Create signals for two services with different confidence levels
        signals = [
            # Service A: high confidence (2 signals, high scores)
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=95.0,
                timestamp=now,
                labels={"service": "service-a"},
                anomaly_score=0.95,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=100.0,
                timestamp=now,
                labels={"service": "service-a"},
                anomaly_score=0.90,
            ),
            # Service B: lower confidence (2 signals, lower scores)
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=70.0,
                timestamp=now,
                labels={"service": "service-b"},
                anomaly_score=0.65,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=20.0,
                timestamp=now,
                labels={"service": "service-b"},
                anomaly_score=0.60,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 2, "Should create two incidents"
        assert (
            incidents[0].confidence > incidents[1].confidence
        ), "Incidents should be sorted by confidence descending"
        assert incidents[0].service == "service-a", "Highest confidence should be first"

    async def test_handles_empty_signals(self):
        """
        Test graceful handling of empty signal list.
        """
        correlator = SignalCorrelator()

        incidents = await correlator.correlate_signals([])

        assert len(incidents) == 0, "Empty signals should return empty incidents"

    async def test_handles_signals_without_service_label(self):
        """
        Test handling of signals without service label (uses 'unknown').
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={},  # No service label
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=50.0,
                timestamp=now,
                labels={},  # No service label
                anomaly_score=0.80,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 1
        assert incidents[0].service == "unknown", "Should use 'unknown' for missing service"

    async def test_from_anomalies_conversion(self):
        """
        Test conversion from AnomalyDetection to Signal.
        """
        now = datetime.utcnow()
        anomalies = [
            AnomalyDetection(
                metric_name="cpu_usage",
                is_anomaly=True,
                confidence=0.85,
                current_value=90.0,
                expected_value=50.0,
                deviation_sigma=4.0,
                timestamp=now,
                context={"labels": {"service": "test-service", "env": "prod"}},
            ),
            AnomalyDetection(
                metric_name="memory_usage",
                is_anomaly=True,
                confidence=0.80,
                current_value=7500000000.0,
                expected_value=2000000000.0,
                deviation_sigma=5.5,
                timestamp=now,
                context={"labels": {"service": "test-service"}},
            ),
        ]

        signals = SignalCorrelator.from_anomalies(anomalies)

        assert len(signals) == 2, "Should convert all anomalies to signals"

        assert all(s.signal_type == SignalType.METRIC for s in signals)
        assert all(s.source == "prometheus" for s in signals)

        # Check first signal
        assert signals[0].name == "cpu_usage"
        assert signals[0].value == 90.0
        assert signals[0].anomaly_score == 0.85
        assert signals[0].labels["service"] == "test-service"
        assert signals[0].labels["env"] == "prod"

        # Check second signal
        assert signals[1].name == "memory_usage"
        assert signals[1].value == 7500000000.0
        assert signals[1].anomaly_score == 0.80

    async def test_minimum_confidence_threshold(self):
        """
        Test that only incidents with confidence >= 0.6 are returned.
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        # Signals with low anomaly scores (should not meet 0.6 threshold)
        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_slightly_high",
                value=60.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.40,  # Low
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="few_errors",
                value=2.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.35,  # Low
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert (
            len(incidents) == 0
        ), "Low confidence signals should not create incident"

    async def test_incident_description_includes_all_signals(self):
        """
        Test that incident description lists all correlated signals.
        """
        correlator = SignalCorrelator()

        now = datetime.utcnow()

        signals = [
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="error_spike",
                value=50.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.80,
            ),
            Signal(
                signal_type=SignalType.TRACE,
                source="jaeger",
                name="slow_requests",
                value=2.5,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.75,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 1
        description = incidents[0].description

        assert "cpu_high" in description, "Should mention metric signal"
        assert "error_spike" in description, "Should mention log signal"
        assert "slow_requests" in description, "Should mention trace signal"
        assert "metric" in description.lower()
        assert "log" in description.lower()
        assert "trace" in description.lower()


class TestSignalCorrelatorEdgeCases:
    """Test edge cases and error scenarios."""

    async def test_handles_exception_gracefully(self):
        """
        Test that exceptions in correlation are caught and empty list returned.
        """
        correlator = SignalCorrelator()

        # Create signal with invalid data that might cause exception
        invalid_signals = [None]  # type: ignore

        # Should not raise, should return empty list
        incidents = await correlator.correlate_signals(invalid_signals)  # type: ignore

        assert len(incidents) == 0, "Should return empty list on error"

    async def test_multiple_time_windows(self):
        """
        Test correlation with signals spanning multiple time windows.

        Should create separate incidents for each window.
        """
        correlator = SignalCorrelator(correlation_window_seconds=300)  # 5 minutes

        now = datetime.utcnow()

        # Two groups of signals separated by 10 minutes
        signals = [
            # First window (t=0)
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="cpu_high",
                value=90.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.85,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="errors",
                value=50.0,
                timestamp=now,
                labels={"service": "api-gateway"},
                anomaly_score=0.80,
            ),
            # Second window (t=15 minutes)
            Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name="memory_high",
                value=7500000000.0,
                timestamp=now + timedelta(minutes=15),
                labels={"service": "api-gateway"},
                anomaly_score=0.90,
            ),
            Signal(
                signal_type=SignalType.LOG,
                source="loki",
                name="oom_errors",
                value=100.0,
                timestamp=now + timedelta(minutes=15),
                labels={"service": "api-gateway"},
                anomaly_score=0.95,
            ),
        ]

        incidents = await correlator.correlate_signals(signals)

        assert len(incidents) == 2, "Should create two separate incidents for different windows"
