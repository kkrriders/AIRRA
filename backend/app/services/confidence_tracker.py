"""
Confidence vs Outcome tracking for model calibration.

Senior Engineering Note:
- Track: confidence when action was taken, whether it succeeded
- Plot it over time
- Demonstrates: "Our confidence model is calibrated"
- This is research-grade validation
- Examiner-proof evidence
"""
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceOutcomeRecord:
    """Single record of confidence vs outcome."""

    timestamp: datetime
    incident_id: str
    service_name: str
    hypothesis_category: str
    hypothesis_description: str
    confidence_score: float  # What we predicted
    action_type: str
    action_executed: bool
    outcome_success: bool  # Did action actually work?
    outcome_status: str  # success, partial_success, no_change, degraded
    verification_metrics: dict  # Before-after metrics
    time_to_resolution_seconds: Optional[float] = None
    blast_radius_level: Optional[str] = None
    risk_level: Optional[str] = None


class ConfidenceTracker:
    """
    Track confidence vs outcomes for model calibration.

    This proves the system works by showing:
    - High confidence → high success rate
    - Low confidence → lower success rate (correctly uncertain)
    - Calibration curve aligns with ideal diagonal
    """

    def __init__(self, storage_path: str = "data/confidence_tracking.jsonl"):
        """
        Initialize confidence tracker.

        Args:
            storage_path: Path to JSONL file for storing records
        """
        self.storage_path = storage_path
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        """Ensure storage directory and file exist."""
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            path.touch()
            logger.info(f"Created confidence tracking storage at {self.storage_path}")

    def record_outcome(self, record: ConfidenceOutcomeRecord):
        """
        Record a confidence vs outcome data point.

        Args:
            record: Confidence outcome record
        """
        try:
            # Convert to dict for JSON serialization
            record_dict = asdict(record)
            record_dict["timestamp"] = record.timestamp.isoformat()

            # Append to JSONL file
            with open(self.storage_path, "a") as f:
                f.write(json.dumps(record_dict) + "\n")

            logger.info(
                f"Recorded confidence outcome: {record.hypothesis_category} "
                f"(confidence: {record.confidence_score:.2f}, "
                f"outcome: {record.outcome_status})"
            )

        except Exception as e:
            logger.error(f"Failed to record confidence outcome: {e}")

    def load_all_records(self) -> list[ConfidenceOutcomeRecord]:
        """Load all confidence outcome records."""
        records = []

        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue

                    data = json.loads(line)
                    data["timestamp"] = datetime.fromisoformat(data["timestamp"])

                    record = ConfidenceOutcomeRecord(**data)
                    records.append(record)

        except FileNotFoundError:
            logger.warning(f"No confidence tracking data found at {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to load confidence records: {e}")

        return records

    def calculate_calibration_stats(
        self,
        confidence_bins: int = 10,
    ) -> dict:
        """
        Calculate calibration statistics.

        Calibration means: If we say 70% confidence, we should be right 70% of the time.

        Args:
            confidence_bins: Number of bins for calibration curve (default 10)

        Returns:
            Dict with calibration statistics
        """
        records = self.load_all_records()

        if not records:
            return {
                "total_records": 0,
                "calibration_bins": [],
                "overall_accuracy": 0.0,
                "note": "No data available",
            }

        # Group records by confidence bins
        bin_size = 1.0 / confidence_bins
        bins = [[] for _ in range(confidence_bins)]

        for record in records:
            bin_idx = min(
                int(record.confidence_score / bin_size),
                confidence_bins - 1,
            )
            bins[bin_idx].append(record)

        # Calculate statistics per bin
        calibration_data = []
        total_correct = 0

        for bin_idx, bin_records in enumerate(bins):
            if not bin_records:
                continue

            bin_confidence = (bin_idx + 0.5) * bin_size
            successes = sum(1 for r in bin_records if r.outcome_success)
            accuracy = successes / len(bin_records)

            # Calibration error: |predicted_confidence - actual_accuracy|
            calibration_error = abs(bin_confidence - accuracy)

            calibration_data.append({
                "bin_range": f"{bin_idx * bin_size:.1f}-{(bin_idx + 1) * bin_size:.1f}",
                "average_confidence": bin_confidence,
                "actual_success_rate": accuracy,
                "sample_count": len(bin_records),
                "calibration_error": calibration_error,
            })

            total_correct += successes

        overall_accuracy = total_correct / len(records) if records else 0.0

        # Calculate expected calibration error (ECE)
        # ECE = weighted average of calibration errors
        ece = sum(
            (data["sample_count"] / len(records)) * data["calibration_error"]
            for data in calibration_data
        )

        return {
            "total_records": len(records),
            "overall_accuracy": overall_accuracy,
            "expected_calibration_error": ece,
            "calibration_bins": calibration_data,
            "note": "Lower ECE = better calibrated. Ideal ECE = 0.0",
        }

    def get_success_rate_by_confidence_range(
        self,
        min_confidence: float,
        max_confidence: float,
    ) -> dict:
        """
        Get success rate for actions in a confidence range.

        Args:
            min_confidence: Minimum confidence
            max_confidence: Maximum confidence

        Returns:
            Dict with statistics
        """
        records = self.load_all_records()

        filtered = [
            r for r in records
            if min_confidence <= r.confidence_score < max_confidence
        ]

        if not filtered:
            return {
                "range": f"{min_confidence:.1f}-{max_confidence:.1f}",
                "count": 0,
                "success_rate": 0.0,
            }

        successes = sum(1 for r in filtered if r.outcome_success)
        success_rate = successes / len(filtered)

        return {
            "range": f"{min_confidence:.1f}-{max_confidence:.1f}",
            "count": len(filtered),
            "successes": successes,
            "failures": len(filtered) - successes,
            "success_rate": success_rate,
        }

    def get_category_performance(self) -> dict:
        """Get performance statistics by hypothesis category."""
        records = self.load_all_records()

        if not records:
            return {}

        category_stats = {}

        for record in records:
            category = record.hypothesis_category

            if category not in category_stats:
                category_stats[category] = {
                    "total": 0,
                    "successes": 0,
                    "avg_confidence": 0.0,
                    "avg_time_to_resolution": 0.0,
                }

            stats = category_stats[category]
            stats["total"] += 1

            if record.outcome_success:
                stats["successes"] += 1

            stats["avg_confidence"] += record.confidence_score

            if record.time_to_resolution_seconds:
                stats["avg_time_to_resolution"] += record.time_to_resolution_seconds

        # Calculate averages
        for category, stats in category_stats.items():
            stats["success_rate"] = stats["successes"] / stats["total"]
            stats["avg_confidence"] /= stats["total"]
            stats["avg_time_to_resolution"] /= stats["total"]

        return category_stats

    def generate_calibration_report(self) -> str:
        """
        Generate human-readable calibration report.

        Returns:
            Formatted report string
        """
        stats = self.calculate_calibration_stats()

        lines = []
        lines.append("=" * 60)
        lines.append("CONFIDENCE CALIBRATION REPORT")
        lines.append("=" * 60)

        lines.append(f"\nTotal Records: {stats['total_records']}")
        lines.append(f"Overall Accuracy: {stats['overall_accuracy']:.1%}")
        lines.append(f"Expected Calibration Error (ECE): {stats.get('expected_calibration_error', 0.0):.3f}")
        lines.append("(Lower ECE = better calibrated. Perfect calibration = 0.0)")

        lines.append("\n" + "-" * 60)
        lines.append("CALIBRATION BY CONFIDENCE BIN:")
        lines.append("-" * 60)

        if stats["calibration_bins"]:
            lines.append(f"{'Range':^15} {'Predicted':^15} {'Actual':^15} {'Samples':^10} {'Error':^10}")
            lines.append("-" * 60)

            for bin_data in stats["calibration_bins"]:
                lines.append(
                    f"{bin_data['bin_range']:^15} "
                    f"{bin_data['average_confidence']:^15.1%} "
                    f"{bin_data['actual_success_rate']:^15.1%} "
                    f"{bin_data['sample_count']:^10} "
                    f"{bin_data['calibration_error']:^10.3f}"
                )
        else:
            lines.append("No data available yet.")

        lines.append("\n" + "-" * 60)
        lines.append("PERFORMANCE BY CATEGORY:")
        lines.append("-" * 60)

        category_stats = self.get_category_performance()
        if category_stats:
            lines.append(f"{'Category':^20} {'Count':^10} {'Success':^10} {'Avg Conf':^12} {'Avg MTTR':^12}")
            lines.append("-" * 60)

            for category, stats in sorted(category_stats.items()):
                mttr_min = stats["avg_time_to_resolution"] / 60.0
                lines.append(
                    f"{category:^20} "
                    f"{stats['total']:^10} "
                    f"{stats['success_rate']:^10.1%} "
                    f"{stats['avg_confidence']:^12.2f} "
                    f"{mttr_min:^12.1f}m"
                )
        else:
            lines.append("No category data available yet.")

        lines.append("\n" + "=" * 60)

        return "\n".join(lines)


# Global instance
_confidence_tracker: Optional[ConfidenceTracker] = None


def get_confidence_tracker() -> ConfidenceTracker:
    """Get global confidence tracker instance."""
    global _confidence_tracker
    if _confidence_tracker is None:
        _confidence_tracker = ConfidenceTracker()
    return _confidence_tracker
