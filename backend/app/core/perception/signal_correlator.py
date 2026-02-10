"""
Multi-Signal Correlation Engine.

Correlates metrics, logs, and traces to identify incident patterns.
Eliminates single-metric alert fatigue by analyzing signals together.

Senior Engineering Note:
- Time-window based correlation
- Weighted scoring based on signal types
- Pattern matching for known issues
- Eliminates false positives through multi-signal validation
"""
import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from app.core.perception.anomaly_detector import AnomalyDetection

logger = logging.getLogger(__name__)


class SignalType(str, Enum):
    """Type of observability signal."""

    METRIC = "metric"
    LOG = "log"
    TRACE = "trace"
    EVENT = "event"


class Signal(BaseModel):
    """Unified signal representation."""

    signal_type: SignalType
    source: str = Field(..., description="Source system (prometheus, loki, jaeger)")
    name: str = Field(..., description="Signal identifier")
    value: float = Field(..., description="Numeric value or severity score")
    timestamp: datetime
    labels: dict[str, str] = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    anomaly_score: float = Field(default=0.0, ge=0.0, le=1.0)


class CorrelatedIncident(BaseModel):
    """A correlated incident with multiple supporting signals."""

    service: str
    title: str
    description: str
    severity_score: float = Field(..., ge=0.0, le=1.0)
    signals: list[Signal] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    correlation_timestamp: datetime = Field(default_factory=datetime.utcnow)


class SignalCorrelator:
    """
    Correlates multiple signals to detect true incidents.

    Reduces alert fatigue by requiring multiple corroborating signals.
    """

    def __init__(
        self,
        correlation_window_seconds: int = 300,  # 5 minutes
        min_signal_count: int = 2,
        metric_weight: float = 0.4,
        log_weight: float = 0.3,
        trace_weight: float = 0.3,
    ):
        self.correlation_window = timedelta(seconds=correlation_window_seconds)
        self.min_signal_count = min_signal_count
        self.weights = {
            SignalType.METRIC: metric_weight,
            SignalType.LOG: log_weight,
            SignalType.TRACE: trace_weight,
            SignalType.EVENT: 0.2,
        }

    async def correlate_signals(
        self,
        signals: list[Signal],
        service_filter: Optional[str] = None,
    ) -> list[CorrelatedIncident]:
        """
        Correlate signals to identify incidents.

        Args:
            signals: List of signals from various sources
            service_filter: Optional service to filter by

        Returns:
            List of correlated incidents with high confidence
        """
        try:
            # Group signals by service and time window
            service_groups = self._group_by_service(signals, service_filter)

            correlated_incidents = []

            for service, service_signals in service_groups.items():
                # Time-window based grouping
                time_groups = self._group_by_time_window(service_signals)

                for window_start, window_signals in time_groups.items():
                    # Must have minimum signal count
                    if len(window_signals) < self.min_signal_count:
                        continue

                    # Must have signals from different types
                    signal_types = {s.signal_type for s in window_signals}
                    if len(signal_types) < 2:
                        continue

                    # Calculate correlation confidence
                    confidence = self._calculate_confidence(window_signals)

                    if confidence >= 0.6:  # Minimum confidence threshold
                        incident = self._create_correlated_incident(
                            service=service,
                            signals=window_signals,
                            confidence=confidence,
                        )
                        correlated_incidents.append(incident)

            return sorted(correlated_incidents, key=lambda x: x.confidence, reverse=True)

        except Exception as e:
            logger.error(f"Signal correlation failed: {str(e)}", exc_info=True)
            return []

    def _group_by_service(
        self, signals: list[Signal], service_filter: Optional[str]
    ) -> dict[str, list[Signal]]:
        """Group signals by service."""
        groups: dict[str, list[Signal]] = {}

        for signal in signals:
            service = signal.labels.get("service", signal.labels.get("app", "unknown"))

            if service_filter and service != service_filter:
                continue

            if service not in groups:
                groups[service] = []
            groups[service].append(signal)

        return groups

    def _group_by_time_window(self, signals: list[Signal]) -> dict[datetime, list[Signal]]:
        """Group signals into time windows."""
        if not signals:
            return {}

        # Sort by timestamp
        sorted_signals = sorted(signals, key=lambda s: s.timestamp)

        groups: dict[datetime, list[Signal]] = {}
        current_window_start = sorted_signals[0].timestamp
        current_group = []

        for signal in sorted_signals:
            if signal.timestamp - current_window_start <= self.correlation_window:
                current_group.append(signal)
            else:
                # Start new window
                groups[current_window_start] = current_group
                current_window_start = signal.timestamp
                current_group = [signal]

        # Add last group
        if current_group:
            groups[current_window_start] = current_group

        return groups

    def _calculate_confidence(self, signals: list[Signal]) -> float:
        """
        Calculate confidence score for correlated signals.

        Considers:
        - Signal diversity (different types)
        - Individual anomaly scores
        - Signal type weights
        """
        if not signals:
            return 0.0

        # Diversity bonus: more signal types = higher confidence
        signal_types = {s.signal_type for s in signals}
        diversity_bonus = min(0.3, len(signal_types) * 0.1)

        # Weighted average of anomaly scores
        weighted_score = 0.0
        total_weight = 0.0

        for signal in signals:
            weight = self.weights.get(signal.signal_type, 0.1)
            weighted_score += signal.anomaly_score * weight
            total_weight += weight

        avg_score = weighted_score / total_weight if total_weight > 0 else 0.0

        # Combine
        confidence = min(1.0, avg_score + diversity_bonus)

        return confidence

    def _create_correlated_incident(
        self,
        service: str,
        signals: list[Signal],
        confidence: float,
    ) -> CorrelatedIncident:
        """Create a correlated incident from signals."""
        # Determine severity based on signal anomaly scores
        max_anomaly = max(s.anomaly_score for s in signals)
        avg_anomaly = sum(s.anomaly_score for s in signals) / len(signals)

        severity_score = (max_anomaly + avg_anomaly) / 2

        # Generate title
        signal_summaries = [f"{s.name} ({s.signal_type.value})" for s in signals[:3]]
        title = f"Multiple anomalies detected in {service}"

        # Generate description
        description_parts = ["Correlated signals indicate an incident:"]
        for signal in signals:
            description_parts.append(
                f"  • {signal.signal_type.value}: {signal.name} "
                f"(score: {signal.anomaly_score:.2f})"
            )

        description = "\n".join(description_parts)

        return CorrelatedIncident(
            service=service,
            title=title,
            description=description,
            severity_score=severity_score,
            signals=signals,
            confidence=confidence,
        )

    @staticmethod
    def from_anomalies(anomalies: list[AnomalyDetection]) -> list[Signal]:
        """Convert anomaly detections to signals for correlation."""
        signals = []
        for anomaly in anomalies:
            signal = Signal(
                signal_type=SignalType.METRIC,
                source="prometheus",
                name=anomaly.metric_name,
                value=anomaly.current_value,
                timestamp=anomaly.timestamp,
                labels=anomaly.context.get("labels", {}),
                context=anomaly.context,
                anomaly_score=anomaly.confidence,
            )
            signals.append(signal)
        return signals


def get_correlator() -> SignalCorrelator:
    """Get a signal correlator instance."""
    return SignalCorrelator()
