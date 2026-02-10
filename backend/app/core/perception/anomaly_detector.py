"""
Anomaly detection using statistical methods.

Senior Engineering Note:
- Z-score based detection (simple but effective for MVP)
- Can be extended with ML-based detection (Prophet, Isolation Forest, etc.)
- Returns confidence scores for detected anomalies
"""
import logging
import statistics
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.services.prometheus_client import MetricDataPoint, MetricResult

logger = logging.getLogger(__name__)


@dataclass
class AnomalyDetection:
    """Result of anomaly detection."""

    metric_name: str
    is_anomaly: bool
    confidence: float  # 0.0 to 1.0
    current_value: float
    expected_value: float
    deviation_sigma: float
    timestamp: datetime
    context: dict


class AnomalyDetector:
    """
    Statistical anomaly detector for time series metrics.

    Uses z-score (standard deviation) based detection.
    This is a simple but effective approach for MVP.

    For production, consider:
    - ML-based detection (Prophet, ARIMA, Isolation Forest)
    - Seasonal decomposition
    - Multi-variate analysis
    """

    def __init__(self, threshold_sigma: float = 3.0):
        """
        Initialize anomaly detector.

        Args:
            threshold_sigma: Number of standard deviations for anomaly threshold
        """
        self.threshold_sigma = threshold_sigma

    def detect(
        self,
        metric_result: MetricResult,
        window_size: Optional[int] = None,
    ) -> list[AnomalyDetection]:
        """
        Detect anomalies in metric data.

        Args:
            metric_result: Metric data from Prometheus
            window_size: Number of recent points to use for baseline
                        (None = use all points)

        Returns:
            List of anomaly detections (one per anomalous point)
        """
        if not metric_result.values:
            return []

        anomalies = []

        # Use all points except the last one for baseline
        all_values = [dp.value for dp in metric_result.values]

        if len(all_values) < 3:
            logger.warning(f"Insufficient data points for {metric_result.metric_name}")
            return []

        # Calculate baseline statistics
        baseline_values = all_values[:-1] if len(all_values) > 1 else all_values
        mean = statistics.mean(baseline_values)

        # Handle case where all values are the same
        try:
            stdev = statistics.stdev(baseline_values)
        except statistics.StatisticsError:
            stdev = 0.0

        # Check the most recent point
        current_point = metric_result.values[-1]
        current_value = current_point.value

        # Calculate z-score
        if stdev == 0:
            # If no variance, calculate relative deviation from mean.
            # Use the larger of abs(mean) and abs(current_value) as the
            # normalization base so the score stays bounded regardless of
            # sign or scale, with a floor of 1.0 to avoid division by zero.
            if current_value == mean:
                z_score = 0.0
            else:
                normalization_base = max(abs(mean), abs(current_value), 1.0)
                z_score = (abs(current_value - mean) / normalization_base) * 10.0
        else:
            z_score = abs(current_value - mean) / stdev

        is_anomaly = z_score > self.threshold_sigma

        # Calculate confidence based on how far beyond threshold
        if is_anomaly:
            # Confidence scales with z-score beyond threshold
            # Caps at 0.99 to avoid overconfidence
            excess_sigma = z_score - self.threshold_sigma
            confidence = min(0.99, 0.5 + (excess_sigma / 10.0))
        else:
            # Low confidence when below threshold
            confidence = max(0.0, z_score / self.threshold_sigma) * 0.4

        anomaly = AnomalyDetection(
            metric_name=metric_result.metric_name,
            is_anomaly=is_anomaly,
            confidence=confidence,
            current_value=current_value,
            expected_value=mean,
            deviation_sigma=z_score,
            timestamp=datetime.fromtimestamp(current_point.timestamp),
            context={
                "labels": metric_result.labels,
                "baseline_mean": mean,
                "baseline_stdev": stdev,
                "threshold_sigma": self.threshold_sigma,
                "sample_size": len(baseline_values),
            },
        )

        if is_anomaly:
            anomalies.append(anomaly)
            logger.info(
                f"Anomaly detected in {metric_result.metric_name}: "
                f"value={current_value:.2f}, expected={mean:.2f}, "
                f"sigma={z_score:.2f}, confidence={confidence:.2f}"
            )

        return anomalies

    def detect_multiple(
        self,
        metric_results: list[MetricResult],
    ) -> list[AnomalyDetection]:
        """
        Detect anomalies across multiple metrics.

        Returns all detected anomalies sorted by confidence.
        """
        all_anomalies = []

        for metric_result in metric_results:
            anomalies = self.detect(metric_result)
            all_anomalies.extend(anomalies)

        # Sort by confidence (highest first)
        all_anomalies.sort(key=lambda x: x.confidence, reverse=True)

        return all_anomalies


def categorize_anomaly(anomaly: AnomalyDetection) -> str:
    """
    Categorize anomaly based on metric name and characteristics.

    Senior Engineering Note:
    This is a simple heuristic categorization.
    In production, you'd use pattern matching or ML classification.
    """
    metric_name = anomaly.metric_name.lower()

    # Check if value is increasing or decreasing
    increasing = anomaly.current_value > anomaly.expected_value

    if "error" in metric_name or "failure" in metric_name:
        return "error_spike" if increasing else "error_recovery"
    elif "latency" in metric_name or "duration" in metric_name:
        return "latency_spike" if increasing else "latency_improvement"
    elif "memory" in metric_name or "heap" in metric_name:
        return "memory_leak" if increasing else "memory_release"
    elif "cpu" in metric_name:
        return "cpu_spike" if increasing else "cpu_drop"
    elif "request" in metric_name or "throughput" in metric_name:
        return "traffic_spike" if increasing else "traffic_drop"
    else:
        return "metric_anomaly"
