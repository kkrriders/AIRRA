"""
Alert deduplication and normalization.

Senior Engineering Note:
- Alert storms corrupt reasoning - must be handled BEFORE perception
- Group alerts by signature + time window
- Drop duplicates
- Normalize severity
- Reasoning must see events, not spam
"""
import hashlib
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Normalized alert severity levels."""

    CRITICAL = "critical"  # Immediate action required
    HIGH = "high"  # Action required soon
    MEDIUM = "medium"  # Should investigate
    LOW = "low"  # Informational
    INFO = "info"  # Purely informational


@dataclass
class Alert:
    """Single alert from monitoring system."""

    source: str  # prometheus, pagerduty, cloudwatch, etc.
    name: str  # Alert name/rule name
    service: str  # Affected service
    severity: AlertSeverity
    message: str
    timestamp: datetime
    labels: dict[str, str] = field(default_factory=dict)
    annotations: dict[str, str] = field(default_factory=dict)
    fingerprint: Optional[str] = None  # For deduplication

    def __post_init__(self):
        """Calculate fingerprint if not provided."""
        if self.fingerprint is None:
            self.fingerprint = self._calculate_fingerprint()

    def _calculate_fingerprint(self) -> str:
        """
        Calculate unique fingerprint for this alert.

        Fingerprint is based on:
        - Service name
        - Alert name
        - Key labels (excluding timestamp, instance, pod)

        This allows grouping of identical alerts.
        """
        # Sort labels for consistent hashing
        stable_labels = {
            k: v for k, v in sorted(self.labels.items())
            if k not in {'instance', 'pod', 'timestamp', 'alertstate'}
        }

        fingerprint_str = f"{self.service}:{self.name}:{str(stable_labels)}"
        return hashlib.sha256(fingerprint_str.encode()).hexdigest()[:16]


@dataclass
class DedupedAlert:
    """Deduplicated alert with count and time range."""

    original_alert: Alert
    count: int  # Number of duplicate alerts
    first_seen: datetime
    last_seen: datetime
    severity: AlertSeverity  # Highest severity seen


class AlertDeduplicator:
    """
    Deduplicate and normalize alerts before perception.

    This is CRITICAL to prevent alert storms from corrupting reasoning.
    """

    def __init__(
        self,
        deduplication_window_seconds: int = 300,  # 5 minutes
        severity_normalization: Optional[dict[str, AlertSeverity]] = None,
    ):
        """
        Initialize alert deduplicator.

        Args:
            deduplication_window_seconds: Time window for grouping alerts
            severity_normalization: Custom severity mapping
        """
        self.dedup_window = timedelta(seconds=deduplication_window_seconds)
        self.severity_map = severity_normalization or self._default_severity_map()

    def _default_severity_map(self) -> dict[str, AlertSeverity]:
        """Default severity normalization mapping."""
        return {
            # Prometheus/Alertmanager
            "critical": AlertSeverity.CRITICAL,
            "warning": AlertSeverity.MEDIUM,
            "info": AlertSeverity.INFO,

            # PagerDuty
            "high": AlertSeverity.HIGH,
            "low": AlertSeverity.LOW,

            # AWS CloudWatch
            "alarm": AlertSeverity.HIGH,
            "insufficient_data": AlertSeverity.LOW,
            "ok": AlertSeverity.INFO,

            # Generic
            "error": AlertSeverity.HIGH,
            "warn": AlertSeverity.MEDIUM,
            "notice": AlertSeverity.LOW,
        }

    def deduplicate(
        self,
        alerts: list[Alert],
        max_age_seconds: Optional[int] = None,
    ) -> list[DedupedAlert]:
        """
        Deduplicate alerts by fingerprint and time window.

        Process:
        1. Filter out old alerts (if max_age specified)
        2. Group by fingerprint
        3. Merge duplicates within time window
        4. Normalize severity
        5. Return deduplicated list

        Args:
            alerts: List of raw alerts
            max_age_seconds: Discard alerts older than this (None = keep all)

        Returns:
            List of deduplicated alerts
        """
        if not alerts:
            return []

        # Filter by age if requested
        now = datetime.utcnow()
        if max_age_seconds is not None:
            cutoff = now - timedelta(seconds=max_age_seconds)
            alerts = [a for a in alerts if a.timestamp >= cutoff]

        logger.info(f"Deduplicating {len(alerts)} alerts")

        # Group by fingerprint
        fingerprint_groups: dict[str, list[Alert]] = defaultdict(list)
        for alert in alerts:
            fingerprint_groups[alert.fingerprint].append(alert)

        # Process each group
        deduped_alerts = []
        for fingerprint, group_alerts in fingerprint_groups.items():
            # Sort by timestamp
            group_alerts.sort(key=lambda a: a.timestamp)

            # Group within time windows
            windows = self._group_by_time_window(group_alerts)

            for window_alerts in windows:
                # Take the first alert as representative
                first_alert = window_alerts[0]
                last_alert = window_alerts[-1]

                # Find highest severity
                max_severity = max(
                    (a.severity for a in window_alerts),
                    key=lambda s: self._severity_to_int(s),
                )

                deduped = DedupedAlert(
                    original_alert=first_alert,
                    count=len(window_alerts),
                    first_seen=first_alert.timestamp,
                    last_seen=last_alert.timestamp,
                    severity=max_severity,
                )
                deduped_alerts.append(deduped)

        logger.info(
            f"Deduplicated to {len(deduped_alerts)} unique alerts "
            f"(compression ratio: {len(alerts) / max(1, len(deduped_alerts)):.1f}x)"
        )

        return deduped_alerts

    def _group_by_time_window(self, alerts: list[Alert]) -> list[list[Alert]]:
        """
        Group alerts by time window.

        Alerts within dedup_window of each other are grouped.

        Args:
            alerts: Sorted list of alerts (by timestamp)

        Returns:
            List of alert groups
        """
        if not alerts:
            return []

        windows = []
        current_window = [alerts[0]]

        for alert in alerts[1:]:
            # If this alert is within window of the first alert in current window
            if alert.timestamp - current_window[0].timestamp <= self.dedup_window:
                current_window.append(alert)
            else:
                # Start new window
                windows.append(current_window)
                current_window = [alert]

        # Don't forget the last window
        if current_window:
            windows.append(current_window)

        return windows

    def _severity_to_int(self, severity: AlertSeverity) -> int:
        """Convert severity to integer for comparison."""
        severity_order = {
            AlertSeverity.INFO: 0,
            AlertSeverity.LOW: 1,
            AlertSeverity.MEDIUM: 2,
            AlertSeverity.HIGH: 3,
            AlertSeverity.CRITICAL: 4,
        }
        return severity_order.get(severity, 0)

    def normalize_severity(
        self,
        raw_severity: str,
        source: str,
    ) -> AlertSeverity:
        """
        Normalize severity string to standard AlertSeverity.

        Args:
            raw_severity: Raw severity string from alert source
            source: Alert source (for source-specific mapping)

        Returns:
            Normalized AlertSeverity
        """
        normalized = raw_severity.lower().strip()

        # Try direct mapping
        if normalized in self.severity_map:
            return self.severity_map[normalized]

        # Try fuzzy matching
        if "crit" in normalized or "fatal" in normalized:
            return AlertSeverity.CRITICAL
        if "high" in normalized or "urgent" in normalized:
            return AlertSeverity.HIGH
        if "warn" in normalized or "medium" in normalized:
            return AlertSeverity.MEDIUM
        if "low" in normalized or "minor" in normalized:
            return AlertSeverity.LOW

        # Default to MEDIUM if unknown
        logger.warning(f"Unknown severity '{raw_severity}' from {source}, defaulting to MEDIUM")
        return AlertSeverity.MEDIUM

    def filter_noise(
        self,
        alerts: list[DedupedAlert],
        min_count: int = 2,
        min_severity: AlertSeverity = AlertSeverity.LOW,
    ) -> list[DedupedAlert]:
        """
        Filter out noise alerts.

        Args:
            alerts: Deduplicated alerts
            min_count: Minimum occurrence count
            min_severity: Minimum severity to keep

        Returns:
            Filtered alerts
        """
        min_severity_int = self._severity_to_int(min_severity)

        filtered = [
            a for a in alerts
            if a.count >= min_count
            and self._severity_to_int(a.severity) >= min_severity_int
        ]

        if len(filtered) < len(alerts):
            logger.info(f"Filtered out {len(alerts) - len(filtered)} noise alerts")

        return filtered
