"""
Operator feedback loop for continuous improvement.

Senior Engineering Note:
- AIRRA will make mistakes - that's expected
- Operators should be able to:
  1. Mark hypotheses as incorrect (with correct root cause)
  2. Mark actions as inappropriate (with better action)
  3. Provide general incident feedback
- Store feedback in structured format
- Use for future improvements:
  - Adjust confidence formulas
  - Update runbooks
  - Train better models
- This is optional but valuable for long-term learning
"""
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from app.models.action import ActionType

logger = logging.getLogger(__name__)


class FeedbackType(str, Enum):
    """Type of operator feedback."""

    HYPOTHESIS_INCORRECT = "hypothesis_incorrect"  # Wrong root cause
    HYPOTHESIS_CORRECT = "hypothesis_correct"  # Confirmed correct
    ACTION_INAPPROPRIATE = "action_inappropriate"  # Wrong action chosen
    ACTION_SUCCESSFUL = "action_successful"  # Action worked well
    INCIDENT_RESOLVED = "incident_resolved"  # Incident resolved (by AIRRA or human)
    INCIDENT_ESCALATED = "incident_escalated"  # Required human intervention
    GENERAL_COMMENT = "general_comment"  # Free-form feedback


@dataclass
class OperatorFeedback:
    """Operator feedback on AIRRA's decisions."""

    feedback_id: str
    timestamp: datetime
    incident_id: str
    service_name: str
    operator_name: str

    feedback_type: FeedbackType
    feedback_text: str  # Human explanation

    # What AIRRA decided
    airra_hypothesis_category: Optional[str] = None
    airra_hypothesis_description: Optional[str] = None
    airra_confidence: Optional[float] = None
    airra_action_type: Optional[ActionType] = None

    # Operator corrections
    correct_hypothesis_category: Optional[str] = None
    correct_hypothesis_description: Optional[str] = None
    correct_action_type: Optional[ActionType] = None

    # Outcome
    incident_resolved: bool = False
    resolution_method: Optional[str] = None  # "airra_action", "manual", "self_healed"
    time_to_resolution_seconds: Optional[float] = None

    # Tags for analysis
    tags: list[str] = None

    def __post_init__(self):
        """Initialize default values."""
        if self.tags is None:
            self.tags = []


@dataclass
class FeedbackSummary:
    """Summary of operator feedback over time."""

    total_feedback_count: int
    feedback_by_type: dict[str, int]

    hypothesis_accuracy: float  # % of hypotheses marked correct
    action_success_rate: float  # % of actions marked successful

    common_mistakes: list[dict]  # Most common incorrect hypotheses
    improvement_suggestions: list[str]

    time_period_start: datetime
    time_period_end: datetime


class OperatorFeedbackCollector:
    """
    Collect and analyze operator feedback.

    This creates a learning loop:
    1. AIRRA makes decisions
    2. Operators provide feedback
    3. Feedback stored for analysis
    4. Future: Use feedback to improve models/formulas
    """

    def __init__(self, storage_path: str = "data/operator_feedback.jsonl"):
        """
        Initialize feedback collector.

        Args:
            storage_path: Path to JSONL file for storing feedback
        """
        self.storage_path = storage_path
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        """Ensure storage directory and file exist."""
        path = Path(self.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        if not path.exists():
            path.touch()
            logger.info(f"Created operator feedback storage at {self.storage_path}")

    def record_feedback(self, feedback: OperatorFeedback):
        """
        Record operator feedback.

        Args:
            feedback: Operator feedback record
        """
        try:
            # Convert to dict for JSON serialization
            feedback_dict = asdict(feedback)
            feedback_dict["timestamp"] = feedback.timestamp.isoformat()

            # Convert enums to strings
            if feedback.feedback_type:
                feedback_dict["feedback_type"] = feedback.feedback_type.value
            if feedback.airra_action_type:
                feedback_dict["airra_action_type"] = feedback.airra_action_type.value
            if feedback.correct_action_type:
                feedback_dict["correct_action_type"] = feedback.correct_action_type.value

            # Append to JSONL file
            with open(self.storage_path, "a") as f:
                f.write(json.dumps(feedback_dict) + "\n")

            logger.info(
                f"Recorded operator feedback: {feedback.feedback_type.value} "
                f"for incident {feedback.incident_id}"
            )

        except Exception as e:
            logger.error(f"Failed to record operator feedback: {e}")

    def load_all_feedback(self) -> list[OperatorFeedback]:
        """Load all operator feedback records."""
        feedback_records = []

        try:
            with open(self.storage_path, "r") as f:
                for line in f:
                    if not line.strip():
                        continue

                    data = json.loads(line)
                    data["timestamp"] = datetime.fromisoformat(data["timestamp"])

                    # Convert string enums back to enum types
                    if "feedback_type" in data:
                        data["feedback_type"] = FeedbackType(data["feedback_type"])
                    if "airra_action_type" in data and data["airra_action_type"]:
                        data["airra_action_type"] = ActionType(
                            data["airra_action_type"]
                        )
                    if "correct_action_type" in data and data["correct_action_type"]:
                        data["correct_action_type"] = ActionType(
                            data["correct_action_type"]
                        )

                    record = OperatorFeedback(**data)
                    feedback_records.append(record)

        except FileNotFoundError:
            logger.warning(f"No operator feedback data found at {self.storage_path}")
        except Exception as e:
            logger.error(f"Failed to load operator feedback: {e}")

        return feedback_records

    def get_feedback_for_incident(self, incident_id: str) -> list[OperatorFeedback]:
        """
        Get all feedback for a specific incident.

        Args:
            incident_id: Incident ID

        Returns:
            List of feedback records
        """
        all_feedback = self.load_all_feedback()
        return [f for f in all_feedback if f.incident_id == incident_id]

    def calculate_accuracy_metrics(
        self,
        time_period_days: int = 30,
    ) -> FeedbackSummary:
        """
        Calculate accuracy metrics from operator feedback.

        Args:
            time_period_days: Number of days to analyze

        Returns:
            FeedbackSummary with metrics
        """
        feedback_records = self.load_all_feedback()

        if not feedback_records:
            return FeedbackSummary(
                total_feedback_count=0,
                feedback_by_type={},
                hypothesis_accuracy=0.0,
                action_success_rate=0.0,
                common_mistakes=[],
                improvement_suggestions=[],
                time_period_start=datetime.now(timezone.utc),
                time_period_end=datetime.now(timezone.utc),
            )

        # Filter by time period
        cutoff_time = datetime.now(timezone.utc).timestamp() - (time_period_days * 86400)
        recent_feedback = [
            f for f in feedback_records if f.timestamp.timestamp() >= cutoff_time
        ]

        # Count by type
        feedback_by_type = {}
        for feedback in recent_feedback:
            type_str = feedback.feedback_type.value
            feedback_by_type[type_str] = feedback_by_type.get(type_str, 0) + 1

        # Calculate hypothesis accuracy
        hypothesis_feedback = [
            f
            for f in recent_feedback
            if f.feedback_type
            in [FeedbackType.HYPOTHESIS_CORRECT, FeedbackType.HYPOTHESIS_INCORRECT]
        ]
        hypothesis_correct = [
            f
            for f in hypothesis_feedback
            if f.feedback_type == FeedbackType.HYPOTHESIS_CORRECT
        ]
        hypothesis_accuracy = (
            len(hypothesis_correct) / len(hypothesis_feedback)
            if hypothesis_feedback
            else 0.0
        )

        # Calculate action success rate
        action_feedback = [
            f
            for f in recent_feedback
            if f.feedback_type
            in [FeedbackType.ACTION_SUCCESSFUL, FeedbackType.ACTION_INAPPROPRIATE]
        ]
        action_successes = [
            f
            for f in action_feedback
            if f.feedback_type == FeedbackType.ACTION_SUCCESSFUL
        ]
        action_success_rate = (
            len(action_successes) / len(action_feedback) if action_feedback else 0.0
        )

        # Identify common mistakes
        incorrect_hypotheses = [
            f
            for f in recent_feedback
            if f.feedback_type == FeedbackType.HYPOTHESIS_INCORRECT
        ]

        mistake_counts = {}
        for feedback in incorrect_hypotheses:
            if feedback.airra_hypothesis_category:
                key = (
                    feedback.airra_hypothesis_category,
                    feedback.correct_hypothesis_category or "unknown",
                )
                mistake_counts[key] = mistake_counts.get(key, 0) + 1

        common_mistakes = [
            {
                "airra_said": airra_cat,
                "actually_was": correct_cat,
                "count": count,
            }
            for (airra_cat, correct_cat), count in sorted(
                mistake_counts.items(), key=lambda x: x[1], reverse=True
            )[:5]
        ]

        # Generate improvement suggestions
        improvement_suggestions = []

        if hypothesis_accuracy < 0.70:
            improvement_suggestions.append(
                f"Hypothesis accuracy is low ({hypothesis_accuracy:.1%}). "
                "Review confidence formula and dependency boost weights."
            )

        if action_success_rate < 0.70:
            improvement_suggestions.append(
                f"Action success rate is low ({action_success_rate:.1%}). "
                "Review runbooks and action selection logic."
            )

        if common_mistakes:
            top_mistake = common_mistakes[0]
            improvement_suggestions.append(
                f"Most common mistake: Saying '{top_mistake['airra_said']}' "
                f"when it's actually '{top_mistake['actually_was']}' "
                f"({top_mistake['count']} times). Add detection logic."
            )

        time_period_start = (
            min(f.timestamp for f in recent_feedback)
            if recent_feedback
            else datetime.now(timezone.utc)
        )
        time_period_end = (
            max(f.timestamp for f in recent_feedback)
            if recent_feedback
            else datetime.now(timezone.utc)
        )

        return FeedbackSummary(
            total_feedback_count=len(recent_feedback),
            feedback_by_type=feedback_by_type,
            hypothesis_accuracy=hypothesis_accuracy,
            action_success_rate=action_success_rate,
            common_mistakes=common_mistakes,
            improvement_suggestions=improvement_suggestions,
            time_period_start=time_period_start,
            time_period_end=time_period_end,
        )

    def generate_feedback_report(self, time_period_days: int = 30) -> str:
        """
        Generate human-readable feedback report.

        Args:
            time_period_days: Number of days to analyze

        Returns:
            Formatted report string
        """
        summary = self.calculate_accuracy_metrics(time_period_days)

        lines = []
        lines.append("=" * 60)
        lines.append("OPERATOR FEEDBACK REPORT")
        lines.append("=" * 60)

        lines.append(f"\nTime Period: {time_period_days} days")
        lines.append(
            f"Date Range: {summary.time_period_start.date()} to {summary.time_period_end.date()}"
        )
        lines.append(f"Total Feedback: {summary.total_feedback_count}")

        lines.append("\n" + "-" * 60)
        lines.append("FEEDBACK BY TYPE:")
        lines.append("-" * 60)

        if summary.feedback_by_type:
            for feedback_type, count in sorted(
                summary.feedback_by_type.items(), key=lambda x: x[1], reverse=True
            ):
                lines.append(f"  {feedback_type:30} {count:>5}")
        else:
            lines.append("  No feedback data available")

        lines.append("\n" + "-" * 60)
        lines.append("ACCURACY METRICS:")
        lines.append("-" * 60)
        lines.append(f"  Hypothesis Accuracy: {summary.hypothesis_accuracy:.1%}")
        lines.append(f"  Action Success Rate: {summary.action_success_rate:.1%}")

        if summary.common_mistakes:
            lines.append("\n" + "-" * 60)
            lines.append("COMMON MISTAKES:")
            lines.append("-" * 60)
            for mistake in summary.common_mistakes:
                lines.append(
                    f"  AIRRA: '{mistake['airra_said']}' → "
                    f"Actually: '{mistake['actually_was']}' "
                    f"({mistake['count']} times)"
                )

        if summary.improvement_suggestions:
            lines.append("\n" + "-" * 60)
            lines.append("IMPROVEMENT SUGGESTIONS:")
            lines.append("-" * 60)
            for suggestion in summary.improvement_suggestions:
                lines.append(f"  • {suggestion}")

        lines.append("\n" + "=" * 60)

        return "\n".join(lines)

    def export_for_analysis(self, output_path: str):
        """
        Export feedback data for external analysis.

        Args:
            output_path: Path to export JSON file
        """
        feedback_records = self.load_all_feedback()

        export_data = []
        for record in feedback_records:
            record_dict = asdict(record)
            record_dict["timestamp"] = record.timestamp.isoformat()

            # Convert enums to strings
            if record.feedback_type:
                record_dict["feedback_type"] = record.feedback_type.value
            if record.airra_action_type:
                record_dict["airra_action_type"] = record.airra_action_type.value
            if record.correct_action_type:
                record_dict["correct_action_type"] = record.correct_action_type.value

            export_data.append(record_dict)

        with open(output_path, "w") as f:
            json.dump(export_data, f, indent=2)

        logger.info(
            f"Exported {len(export_data)} feedback records to {output_path}"
        )


# Global instance
_operator_feedback_collector: Optional[OperatorFeedbackCollector] = None


def get_operator_feedback_collector() -> OperatorFeedbackCollector:
    """Get global operator feedback collector instance."""
    global _operator_feedback_collector
    if _operator_feedback_collector is None:
        _operator_feedback_collector = OperatorFeedbackCollector()
    return _operator_feedback_collector
