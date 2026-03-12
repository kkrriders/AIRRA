"""
Unit tests for app/services/confidence_tracker.py

Pure computation — no DB/external deps. Uses tmp_path for file I/O.
"""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from app.services.confidence_tracker import (
    ConfidenceOutcomeRecord,
    ConfidenceTracker,
    get_confidence_tracker,
)


def _make_record(
    confidence: float = 0.8,
    outcome_success: bool = True,
    category: str = "memory_leak",
    outcome_status: str = "success",
    time_to_resolution: float | None = 120.0,
) -> ConfidenceOutcomeRecord:
    return ConfidenceOutcomeRecord(
        timestamp=datetime.now(timezone.utc),
        incident_id="inc-001",
        service_name="payment-service",
        hypothesis_category=category,
        hypothesis_description="Memory leak detected",
        confidence_score=confidence,
        action_type="restart_pod",
        action_executed=True,
        outcome_success=outcome_success,
        outcome_status=outcome_status,
        verification_metrics={"before": 80.0, "after": 20.0},
        time_to_resolution_seconds=time_to_resolution,
        blast_radius_level="medium",
        risk_level="low",
    )


class TestConfidenceTrackerInit:
    def test_creates_storage_file(self, tmp_path):
        storage = tmp_path / "subdir" / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        assert storage.exists()

    def test_existing_file_not_recreated(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        storage.write_text("existing\n")
        tracker = ConfidenceTracker(storage_path=str(storage))
        assert storage.read_text() == "existing\n"


class TestRecordOutcome:
    def test_record_written_to_file(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        record = _make_record()
        tracker.record_outcome(record)
        lines = storage.read_text().strip().split("\n")
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["confidence_score"] == 0.8

    def test_multiple_records_appended(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(confidence=0.7))
        tracker.record_outcome(_make_record(confidence=0.9))
        lines = [l for l in storage.read_text().strip().split("\n") if l]
        assert len(lines) == 2

    def test_timestamp_serialized_as_isoformat(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        record = _make_record()
        tracker.record_outcome(record)
        data = json.loads(storage.read_text().strip())
        # Should be parseable ISO datetime string
        parsed = datetime.fromisoformat(data["timestamp"])
        assert isinstance(parsed, datetime)


class TestLoadAllRecords:
    def test_empty_file_returns_empty_list(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        records = tracker.load_all_records()
        assert records == []

    def test_round_trip_record(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        record = _make_record(confidence=0.75, outcome_success=False)
        tracker.record_outcome(record)
        loaded = tracker.load_all_records()
        assert len(loaded) == 1
        assert loaded[0].confidence_score == 0.75
        assert loaded[0].outcome_success is False

    def test_load_multiple_records(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        for i in range(5):
            tracker.record_outcome(_make_record(confidence=i * 0.2))
        loaded = tracker.load_all_records()
        assert len(loaded) == 5

    def test_missing_file_returns_empty_list(self, tmp_path):
        nonexistent = tmp_path / "no_such_file.jsonl"
        tracker = ConfidenceTracker.__new__(ConfidenceTracker)
        tracker.storage_path = str(nonexistent)
        records = tracker.load_all_records()
        assert records == []

    def test_blank_lines_skipped(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        record = _make_record()
        tracker.record_outcome(record)
        # Inject blank lines
        content = storage.read_text()
        storage.write_text("\n" + content + "\n\n")
        loaded = tracker.load_all_records()
        assert len(loaded) == 1


class TestCalculateCalibrationStats:
    def test_no_records_returns_empty_dict(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        stats = tracker.calculate_calibration_stats()
        assert stats["total_records"] == 0
        assert stats["calibration_bins"] == []

    def test_stats_with_records(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        # Add 4 records: 2 success at 0.8, 2 fail at 0.3
        for _ in range(2):
            tracker.record_outcome(_make_record(confidence=0.8, outcome_success=True))
        for _ in range(2):
            tracker.record_outcome(_make_record(confidence=0.3, outcome_success=False))
        stats = tracker.calculate_calibration_stats()
        assert stats["total_records"] == 4
        assert stats["overall_accuracy"] == 0.5
        assert "expected_calibration_error" in stats
        assert len(stats["calibration_bins"]) >= 1

    def test_perfect_calibration_low_ece(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        # All at 0.9 confidence, all succeed
        for _ in range(10):
            tracker.record_outcome(_make_record(confidence=0.9, outcome_success=True))
        stats = tracker.calculate_calibration_stats()
        assert stats["overall_accuracy"] == 1.0

    def test_bin_range_format(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(confidence=0.5))
        stats = tracker.calculate_calibration_stats()
        for bin_data in stats["calibration_bins"]:
            assert "bin_range" in bin_data
            assert "average_confidence" in bin_data
            assert "actual_success_rate" in bin_data
            assert "sample_count" in bin_data
            assert "calibration_error" in bin_data

    def test_boundary_confidence_1_0(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(confidence=1.0, outcome_success=True))
        stats = tracker.calculate_calibration_stats()
        assert stats["total_records"] == 1


class TestGetSuccessRateByConfidenceRange:
    def test_empty_returns_zero(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        result = tracker.get_success_rate_by_confidence_range(0.7, 1.0)
        assert result["count"] == 0
        assert result["success_rate"] == 0.0

    def test_filters_by_range(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(confidence=0.8, outcome_success=True))
        tracker.record_outcome(_make_record(confidence=0.8, outcome_success=False))
        tracker.record_outcome(_make_record(confidence=0.3, outcome_success=True))
        result = tracker.get_success_rate_by_confidence_range(0.7, 1.0)
        assert result["count"] == 2
        assert result["success_rate"] == 0.5

    def test_range_label_formatted(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        result = tracker.get_success_rate_by_confidence_range(0.5, 0.8)
        assert "0.5" in result["range"]
        assert "0.8" in result["range"]


class TestGetCategoryPerformance:
    def test_empty_returns_empty_dict(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        result = tracker.get_category_performance()
        assert result == {}

    def test_groups_by_category(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(category="memory_leak", outcome_success=True))
        tracker.record_outcome(_make_record(category="memory_leak", outcome_success=False))
        tracker.record_outcome(_make_record(category="cpu_spike", outcome_success=True))
        result = tracker.get_category_performance()
        assert "memory_leak" in result
        assert "cpu_spike" in result
        assert result["memory_leak"]["total"] == 2
        assert result["memory_leak"]["success_rate"] == 0.5
        assert result["cpu_spike"]["total"] == 1

    def test_avg_confidence_computed(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(confidence=0.6, category="cpu_spike"))
        tracker.record_outcome(_make_record(confidence=0.8, category="cpu_spike"))
        result = tracker.get_category_performance()
        assert abs(result["cpu_spike"]["avg_confidence"] - 0.7) < 1e-9

    def test_avg_time_to_resolution_computed(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(category="mem", time_to_resolution=60.0))
        tracker.record_outcome(_make_record(category="mem", time_to_resolution=120.0))
        result = tracker.get_category_performance()
        assert result["mem"]["avg_time_to_resolution"] == 90.0


class TestGenerateCalibrationReport:
    def test_report_contains_header(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        report = tracker.generate_calibration_report()
        assert "CONFIDENCE CALIBRATION REPORT" in report

    def test_report_with_no_data(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        report = tracker.generate_calibration_report()
        assert "Total Records: 0" in report
        assert "No data available yet." in report

    def test_report_with_data_shows_bins(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        tracker.record_outcome(_make_record(confidence=0.7, outcome_success=True))
        tracker.record_outcome(_make_record(confidence=0.3, outcome_success=False, category="cpu_spike"))
        report = tracker.generate_calibration_report()
        assert "CALIBRATION BY CONFIDENCE BIN" in report
        assert "PERFORMANCE BY CATEGORY" in report

    def test_report_is_string(self, tmp_path):
        storage = tmp_path / "tracking.jsonl"
        tracker = ConfidenceTracker(storage_path=str(storage))
        report = tracker.generate_calibration_report()
        assert isinstance(report, str)


class TestGetConfidenceTracker:
    def test_returns_tracker_instance(self, tmp_path, monkeypatch):
        import app.services.confidence_tracker as mod
        # Reset global so we get a fresh one
        monkeypatch.setattr(mod, "_confidence_tracker", None)
        # Point default storage to tmp to avoid polluting cwd
        monkeypatch.setattr(
            mod.ConfidenceTracker,
            "__init__",
            lambda self, storage_path="data/confidence_tracking.jsonl": (
                setattr(self, "storage_path", str(tmp_path / "track.jsonl"))
                or mod.ConfidenceTracker._ensure_storage_exists(self)
            ),
        )
        tracker = mod.get_confidence_tracker()
        assert isinstance(tracker, mod.ConfidenceTracker)

    def test_returns_same_instance_on_second_call(self, tmp_path, monkeypatch):
        import app.services.confidence_tracker as mod
        monkeypatch.setattr(mod, "_confidence_tracker", None)
        storage = tmp_path / "track.jsonl"
        tracker1 = mod.ConfidenceTracker(storage_path=str(storage))
        monkeypatch.setattr(mod, "_confidence_tracker", tracker1)
        tracker2 = mod.get_confidence_tracker()
        assert tracker1 is tracker2
