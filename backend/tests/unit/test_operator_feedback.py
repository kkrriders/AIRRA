"""
Unit tests for app/services/operator_feedback.py

Uses tmp_path for all file I/O. Covers record/load/analysis/reporting.
"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from app.models.action import ActionType
from app.services.operator_feedback import (
    FeedbackType,
    OperatorFeedback,
    OperatorFeedbackCollector,
    FeedbackSummary,
    get_operator_feedback_collector,
)


def _make_feedback(
    feedback_type: FeedbackType = FeedbackType.HYPOTHESIS_CORRECT,
    incident_id: str = "inc-001",
    category: str = "memory_leak",
    correct_category: str | None = None,
    airra_action: ActionType | None = None,
    correct_action: ActionType | None = None,
    incident_resolved: bool = True,
    time_to_res: float | None = 90.0,
    tags: list | None = None,
) -> OperatorFeedback:
    return OperatorFeedback(
        feedback_id="fb-001",
        timestamp=datetime.now(timezone.utc),
        incident_id=incident_id,
        service_name="payment-service",
        operator_name="alice",
        feedback_type=feedback_type,
        feedback_text="Looks correct.",
        airra_hypothesis_category=category,
        airra_hypothesis_description="Memory leak in cache",
        airra_confidence=0.85,
        airra_action_type=airra_action,
        correct_hypothesis_category=correct_category,
        correct_action_type=correct_action,
        incident_resolved=incident_resolved,
        resolution_method="airra_action",
        time_to_resolution_seconds=time_to_res,
        tags=tags,
    )


class TestOperatorFeedbackCollectorInit:
    def test_creates_storage_file(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        assert storage.exists()

    def test_nested_dir_created(self, tmp_path):
        storage = tmp_path / "sub" / "dir" / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        assert storage.exists()

    def test_existing_file_not_truncated(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        storage.write_text("existing\n")
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        assert storage.read_text() == "existing\n"


class TestOperatorFeedbackDataclass:
    def test_tags_default_to_empty_list(self):
        fb = OperatorFeedback(
            feedback_id="x",
            timestamp=datetime.now(timezone.utc),
            incident_id="i",
            service_name="svc",
            operator_name="bob",
            feedback_type=FeedbackType.GENERAL_COMMENT,
            feedback_text="ok",
        )
        assert fb.tags == []

    def test_tags_provided_preserved(self):
        fb = _make_feedback(tags=["urgent", "regression"])
        assert fb.tags == ["urgent", "regression"]


class TestRecordFeedback:
    def test_record_written_to_file(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback()
        collector.record_feedback(fb)
        lines = [l for l in storage.read_text().strip().split("\n") if l]
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["incident_id"] == "inc-001"

    def test_feedback_type_serialized_as_value(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback(feedback_type=FeedbackType.ACTION_SUCCESSFUL)
        collector.record_feedback(fb)
        data = json.loads(storage.read_text().strip())
        assert data["feedback_type"] == "action_successful"

    def test_airra_action_type_serialized(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback(airra_action=ActionType.RESTART_POD)
        collector.record_feedback(fb)
        data = json.loads(storage.read_text().strip())
        assert data["airra_action_type"] == "restart_pod"

    def test_correct_action_type_serialized(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback(correct_action=ActionType.SCALE_UP)
        collector.record_feedback(fb)
        data = json.loads(storage.read_text().strip())
        assert data["correct_action_type"] == "scale_up"

    def test_multiple_records_appended(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(incident_id="i1"))
        collector.record_feedback(_make_feedback(incident_id="i2"))
        lines = [l for l in storage.read_text().strip().split("\n") if l]
        assert len(lines) == 2


class TestLoadAllFeedback:
    def test_empty_file_returns_empty_list(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        result = collector.load_all_feedback()
        assert result == []

    def test_round_trip(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback(feedback_type=FeedbackType.HYPOTHESIS_INCORRECT)
        collector.record_feedback(fb)
        loaded = collector.load_all_feedback()
        assert len(loaded) == 1
        assert loaded[0].feedback_type == FeedbackType.HYPOTHESIS_INCORRECT

    def test_load_with_action_types(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback(
            airra_action=ActionType.ROLLBACK_DEPLOYMENT,
            correct_action=ActionType.SCALE_DOWN,
        )
        collector.record_feedback(fb)
        loaded = collector.load_all_feedback()
        assert loaded[0].airra_action_type == ActionType.ROLLBACK_DEPLOYMENT
        assert loaded[0].correct_action_type == ActionType.SCALE_DOWN

    def test_missing_file_returns_empty_list(self, tmp_path):
        collector = OperatorFeedbackCollector.__new__(OperatorFeedbackCollector)
        collector.storage_path = str(tmp_path / "nonexistent.jsonl")
        result = collector.load_all_feedback()
        assert result == []

    def test_blank_lines_skipped(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        fb = _make_feedback()
        collector.record_feedback(fb)
        content = storage.read_text()
        storage.write_text("\n" + content + "\n\n")
        loaded = collector.load_all_feedback()
        assert len(loaded) == 1


class TestGetFeedbackForIncident:
    def test_filters_by_incident_id(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(incident_id="inc-A"))
        collector.record_feedback(_make_feedback(incident_id="inc-B"))
        collector.record_feedback(_make_feedback(incident_id="inc-A"))
        result = collector.get_feedback_for_incident("inc-A")
        assert len(result) == 2
        assert all(f.incident_id == "inc-A" for f in result)

    def test_unknown_incident_returns_empty(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(incident_id="inc-X"))
        result = collector.get_feedback_for_incident("inc-Y")
        assert result == []


class TestCalculateAccuracyMetrics:
    def test_empty_returns_zero_summary(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        summary = collector.calculate_accuracy_metrics()
        assert summary.total_feedback_count == 0
        assert summary.hypothesis_accuracy == 0.0
        assert summary.action_success_rate == 0.0

    def test_hypothesis_accuracy_calculated(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        # 2 correct, 1 incorrect → 2/3 accuracy
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.HYPOTHESIS_CORRECT))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.HYPOTHESIS_CORRECT))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.HYPOTHESIS_INCORRECT))
        summary = collector.calculate_accuracy_metrics(time_period_days=365)
        assert abs(summary.hypothesis_accuracy - 2 / 3) < 1e-9

    def test_action_success_rate_calculated(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.ACTION_SUCCESSFUL))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.ACTION_INAPPROPRIATE))
        summary = collector.calculate_accuracy_metrics(time_period_days=365)
        assert summary.action_success_rate == 0.5

    def test_feedback_by_type_counted(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.GENERAL_COMMENT))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.GENERAL_COMMENT))
        summary = collector.calculate_accuracy_metrics(time_period_days=365)
        assert summary.feedback_by_type.get("general_comment", 0) == 2

    def test_common_mistakes_identified(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        # 3 times airra says memory_leak but it's cpu_spike
        for _ in range(3):
            fb = _make_feedback(
                feedback_type=FeedbackType.HYPOTHESIS_INCORRECT,
                category="memory_leak",
                correct_category="cpu_spike",
            )
            collector.record_feedback(fb)
        summary = collector.calculate_accuracy_metrics(time_period_days=365)
        assert len(summary.common_mistakes) >= 1
        assert summary.common_mistakes[0]["airra_said"] == "memory_leak"
        assert summary.common_mistakes[0]["actually_was"] == "cpu_spike"

    def test_improvement_suggestions_low_accuracy(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        # All incorrect → accuracy 0%
        for _ in range(5):
            collector.record_feedback(
                _make_feedback(feedback_type=FeedbackType.HYPOTHESIS_INCORRECT)
            )
        summary = collector.calculate_accuracy_metrics(time_period_days=365)
        assert len(summary.improvement_suggestions) >= 1

    def test_improvement_suggestions_low_action_rate(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        for _ in range(5):
            collector.record_feedback(
                _make_feedback(feedback_type=FeedbackType.ACTION_INAPPROPRIATE)
            )
        summary = collector.calculate_accuracy_metrics(time_period_days=365)
        assert any("action" in s.lower() for s in summary.improvement_suggestions)

    def test_time_period_filters_old_records(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        # Write a record with a very old timestamp manually
        old_ts = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
        old_record = {
            "feedback_id": "fb-old",
            "timestamp": old_ts,
            "incident_id": "inc-old",
            "service_name": "svc",
            "operator_name": "bob",
            "feedback_type": "general_comment",
            "feedback_text": "old",
            "airra_hypothesis_category": None,
            "airra_hypothesis_description": None,
            "airra_confidence": None,
            "airra_action_type": None,
            "correct_hypothesis_category": None,
            "correct_hypothesis_description": None,
            "correct_action_type": None,
            "incident_resolved": False,
            "resolution_method": None,
            "time_to_resolution_seconds": None,
            "tags": [],
        }
        with open(str(storage), "a") as f:
            f.write(json.dumps(old_record) + "\n")
        summary = collector.calculate_accuracy_metrics(time_period_days=1)
        assert summary.total_feedback_count == 0


class TestGenerateFeedbackReport:
    def test_report_contains_header(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        report = collector.generate_feedback_report()
        assert "OPERATOR FEEDBACK REPORT" in report

    def test_report_no_data_shows_placeholder(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        report = collector.generate_feedback_report()
        assert "No feedback data available" in report

    def test_report_with_data(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(feedback_type=FeedbackType.HYPOTHESIS_CORRECT))
        report = collector.generate_feedback_report(time_period_days=365)
        assert "hypothesis_correct" in report

    def test_report_with_mistakes(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        for _ in range(2):
            collector.record_feedback(
                _make_feedback(
                    feedback_type=FeedbackType.HYPOTHESIS_INCORRECT,
                    category="memory_leak",
                    correct_category="cpu_spike",
                )
            )
        report = collector.generate_feedback_report(time_period_days=365)
        assert "COMMON MISTAKES" in report

    def test_report_is_string(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        assert isinstance(collector.generate_feedback_report(), str)


class TestExportForAnalysis:
    def test_export_creates_file(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        export_path = tmp_path / "export.json"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback())
        collector.export_for_analysis(str(export_path))
        assert export_path.exists()

    def test_export_valid_json(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        export_path = tmp_path / "export.json"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback())
        collector.export_for_analysis(str(export_path))
        data = json.loads(export_path.read_text())
        assert isinstance(data, list)
        assert len(data) == 1

    def test_export_enum_as_string(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        export_path = tmp_path / "export.json"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.record_feedback(_make_feedback(airra_action=ActionType.RESTART_POD))
        collector.export_for_analysis(str(export_path))
        data = json.loads(export_path.read_text())
        assert data[0]["airra_action_type"] == "restart_pod"

    def test_export_empty_data(self, tmp_path):
        storage = tmp_path / "feedback.jsonl"
        export_path = tmp_path / "export.json"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        collector.export_for_analysis(str(export_path))
        data = json.loads(export_path.read_text())
        assert data == []


class TestGetOperatorFeedbackCollector:
    def test_returns_instance(self, tmp_path, monkeypatch):
        import app.services.operator_feedback as mod
        monkeypatch.setattr(mod, "_operator_feedback_collector", None)
        # Patch __init__ to use tmp dir
        orig_init = OperatorFeedbackCollector.__init__

        def patched_init(self, storage_path="data/operator_feedback.jsonl"):
            self.storage_path = str(tmp_path / "feedback.jsonl")
            OperatorFeedbackCollector._ensure_storage_exists(self)

        monkeypatch.setattr(OperatorFeedbackCollector, "__init__", patched_init)
        result = mod.get_operator_feedback_collector()
        assert isinstance(result, OperatorFeedbackCollector)

    def test_singleton_behavior(self, tmp_path, monkeypatch):
        import app.services.operator_feedback as mod
        storage = tmp_path / "feedback.jsonl"
        collector = OperatorFeedbackCollector(storage_path=str(storage))
        monkeypatch.setattr(mod, "_operator_feedback_collector", collector)
        result = mod.get_operator_feedback_collector()
        assert result is collector
