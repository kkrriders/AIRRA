"""
Unit tests for app/core/perception/alert_deduplication.py

Pure in-memory logic — no external deps needed.
"""
from datetime import datetime, timedelta, timezone

from app.core.perception.alert_deduplication import (
    Alert,
    AlertDeduplicator,
    AlertSeverity,
    DedupedAlert,
)


def _make_alert(
    service: str = "payment-service",
    name: str = "HighMemory",
    severity: AlertSeverity = AlertSeverity.HIGH,
    message: str = "Memory usage elevated",
    offset_seconds: float = 0,
    labels: dict | None = None,
    fingerprint: str | None = None,
) -> Alert:
    now = datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    return Alert(
        source="prometheus",
        name=name,
        service=service,
        severity=severity,
        message=message,
        timestamp=now,
        labels=labels or {},
        fingerprint=fingerprint,
    )


class TestAlertFingerprint:
    def test_fingerprint_calculated_on_init(self):
        alert = _make_alert()
        assert alert.fingerprint is not None
        assert len(alert.fingerprint) == 16

    def test_same_service_name_same_fingerprint(self):
        a1 = _make_alert(service="svc", name="Alert", labels={})
        a2 = _make_alert(service="svc", name="Alert", labels={})
        assert a1.fingerprint == a2.fingerprint

    def test_different_service_different_fingerprint(self):
        a1 = _make_alert(service="svc-a", name="Alert")
        a2 = _make_alert(service="svc-b", name="Alert")
        assert a1.fingerprint != a2.fingerprint

    def test_fingerprint_excludes_instance_label(self):
        a1 = _make_alert(labels={"instance": "host1"})
        a2 = _make_alert(labels={"instance": "host2"})
        assert a1.fingerprint == a2.fingerprint

    def test_fingerprint_excludes_pod_label(self):
        a1 = _make_alert(labels={"pod": "pod-abc"})
        a2 = _make_alert(labels={"pod": "pod-xyz"})
        assert a1.fingerprint == a2.fingerprint

    def test_fingerprint_includes_custom_label(self):
        a1 = _make_alert(labels={"env": "prod"})
        a2 = _make_alert(labels={"env": "staging"})
        assert a1.fingerprint != a2.fingerprint

    def test_explicit_fingerprint_preserved(self):
        alert = _make_alert(fingerprint="custom_fp_abc123")
        assert alert.fingerprint == "custom_fp_abc123"

    def test_fingerprint_is_hex(self):
        alert = _make_alert()
        assert all(c in "0123456789abcdef" for c in alert.fingerprint)


class TestAlertDeduplicatorInit:
    def test_default_dedup_window(self):
        dedup = AlertDeduplicator()
        assert dedup.dedup_window == timedelta(seconds=300)

    def test_custom_dedup_window(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=60)
        assert dedup.dedup_window == timedelta(seconds=60)

    def test_default_severity_map_populated(self):
        dedup = AlertDeduplicator()
        assert "critical" in dedup.severity_map
        assert "warning" in dedup.severity_map
        assert dedup.severity_map["critical"] == AlertSeverity.CRITICAL

    def test_custom_severity_map(self):
        custom_map = {"urgent": AlertSeverity.CRITICAL}
        dedup = AlertDeduplicator(severity_normalization=custom_map)
        assert dedup.severity_map == custom_map


class TestDeduplicateMethod:
    def test_empty_list_returns_empty(self):
        dedup = AlertDeduplicator()
        assert dedup.deduplicate([]) == []

    def test_single_alert_returns_one_deduped(self):
        dedup = AlertDeduplicator()
        alert = _make_alert()
        result = dedup.deduplicate([alert])
        assert len(result) == 1
        assert result[0].count == 1

    def test_identical_alerts_grouped(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=300)
        # Three alerts with same fingerprint within 5 min window
        alerts = [_make_alert(offset_seconds=i * 30) for i in range(3)]
        result = dedup.deduplicate(alerts)
        assert len(result) == 1
        assert result[0].count == 3

    def test_alerts_outside_window_split(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=60)
        # Two alerts 120s apart → two separate windows
        a1 = _make_alert(offset_seconds=0)
        a2 = _make_alert(offset_seconds=130)  # beyond 60s window
        result = dedup.deduplicate([a1, a2])
        assert len(result) == 2

    def test_different_services_separate_groups(self):
        dedup = AlertDeduplicator()
        a1 = _make_alert(service="svc-a")
        a2 = _make_alert(service="svc-b")
        result = dedup.deduplicate([a1, a2])
        assert len(result) == 2

    def test_max_severity_escalated(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=300)
        # Force same fingerprint
        fp = "fixed_fingerprint"
        a1 = _make_alert(severity=AlertSeverity.LOW, fingerprint=fp, offset_seconds=0)
        a2 = _make_alert(severity=AlertSeverity.CRITICAL, fingerprint=fp, offset_seconds=10)
        result = dedup.deduplicate([a1, a2])
        assert len(result) == 1
        assert result[0].severity == AlertSeverity.CRITICAL

    def test_max_age_filters_old_alerts(self):
        dedup = AlertDeduplicator()
        old_alert = _make_alert(offset_seconds=-600)  # 10 min old
        recent_alert = _make_alert(offset_seconds=0)
        result = dedup.deduplicate([old_alert, recent_alert], max_age_seconds=300)
        assert len(result) == 1

    def test_max_age_none_keeps_all(self):
        dedup = AlertDeduplicator()
        old_alert = _make_alert(service="svc-old", offset_seconds=-3600)
        recent_alert = _make_alert(service="svc-new", offset_seconds=0)
        result = dedup.deduplicate([old_alert, recent_alert], max_age_seconds=None)
        assert len(result) == 2

    def test_deduped_alert_first_last_seen(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=300)
        fp = "fp_test"
        a1 = _make_alert(fingerprint=fp, offset_seconds=0)
        a2 = _make_alert(fingerprint=fp, offset_seconds=60)
        result = dedup.deduplicate([a1, a2])
        assert len(result) == 1
        assert result[0].first_seen <= result[0].last_seen

    def test_compression_ratio_multiple_duplicates(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=300)
        fp = "dup_fp"
        alerts = [_make_alert(fingerprint=fp, offset_seconds=i * 5) for i in range(10)]
        result = dedup.deduplicate(alerts)
        assert len(result) == 1
        assert result[0].count == 10


class TestGroupByTimeWindow:
    def test_single_alert_single_window(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=300)
        alert = _make_alert()
        windows = dedup._group_by_time_window([alert])
        assert len(windows) == 1
        assert len(windows[0]) == 1

    def test_empty_input_returns_empty(self):
        dedup = AlertDeduplicator()
        result = dedup._group_by_time_window([])
        assert result == []

    def test_alerts_within_window_grouped(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=300)
        alerts = sorted(
            [_make_alert(offset_seconds=i * 30) for i in range(5)],
            key=lambda a: a.timestamp,
        )
        windows = dedup._group_by_time_window(alerts)
        assert len(windows) == 1
        assert len(windows[0]) == 5

    def test_gap_larger_than_window_creates_new_window(self):
        dedup = AlertDeduplicator(deduplication_window_seconds=60)
        a1 = _make_alert(offset_seconds=0)
        a2 = _make_alert(offset_seconds=120)  # beyond window
        windows = dedup._group_by_time_window(sorted([a1, a2], key=lambda a: a.timestamp))
        assert len(windows) == 2


class TestSeverityToInt:
    def test_order(self):
        dedup = AlertDeduplicator()
        assert dedup._severity_to_int(AlertSeverity.INFO) < dedup._severity_to_int(AlertSeverity.LOW)
        assert dedup._severity_to_int(AlertSeverity.LOW) < dedup._severity_to_int(AlertSeverity.MEDIUM)
        assert dedup._severity_to_int(AlertSeverity.MEDIUM) < dedup._severity_to_int(AlertSeverity.HIGH)
        assert dedup._severity_to_int(AlertSeverity.HIGH) < dedup._severity_to_int(AlertSeverity.CRITICAL)

    def test_unknown_severity_returns_zero(self):
        dedup = AlertDeduplicator()
        # passing a sentinel string (not in map) should return 0
        assert dedup._severity_to_int("nonexistent") == 0


class TestNormalizeSeverity:
    def test_direct_mapping_critical(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("critical", "prometheus")
        assert result == AlertSeverity.CRITICAL

    def test_direct_mapping_warning(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("warning", "prometheus")
        assert result == AlertSeverity.MEDIUM

    def test_fuzzy_crit_in_string(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("very_critical_alert", "custom")
        assert result == AlertSeverity.CRITICAL

    def test_fuzzy_fatal(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("fatal_error", "custom")
        assert result == AlertSeverity.CRITICAL

    def test_fuzzy_urgent(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("urgent_warning", "custom")
        assert result == AlertSeverity.HIGH

    def test_fuzzy_warn(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("warn_level", "custom")
        assert result == AlertSeverity.MEDIUM

    def test_fuzzy_minor(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("minor_issue", "custom")
        assert result == AlertSeverity.LOW

    def test_unknown_defaults_to_medium(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("unknown_gibberish_xyz", "custom")
        assert result == AlertSeverity.MEDIUM

    def test_case_insensitive(self):
        dedup = AlertDeduplicator()
        result = dedup.normalize_severity("CRITICAL", "prometheus")
        assert result == AlertSeverity.CRITICAL


class TestFilterNoise:
    def test_filters_below_min_count(self):
        dedup = AlertDeduplicator()
        fp = "fp_x"
        alert = _make_alert(fingerprint=fp, severity=AlertSeverity.HIGH)
        deduped = DedupedAlert(
            original_alert=alert,
            count=1,
            first_seen=alert.timestamp,
            last_seen=alert.timestamp,
            severity=AlertSeverity.HIGH,
        )
        result = dedup.filter_noise([deduped], min_count=2)
        assert result == []

    def test_keeps_above_min_count(self):
        dedup = AlertDeduplicator()
        alert = _make_alert(severity=AlertSeverity.HIGH)
        deduped = DedupedAlert(
            original_alert=alert,
            count=5,
            first_seen=alert.timestamp,
            last_seen=alert.timestamp,
            severity=AlertSeverity.HIGH,
        )
        result = dedup.filter_noise([deduped], min_count=2)
        assert len(result) == 1

    def test_filters_below_min_severity(self):
        dedup = AlertDeduplicator()
        alert = _make_alert(severity=AlertSeverity.INFO)
        deduped = DedupedAlert(
            original_alert=alert,
            count=10,
            first_seen=alert.timestamp,
            last_seen=alert.timestamp,
            severity=AlertSeverity.INFO,
        )
        result = dedup.filter_noise([deduped], min_count=1, min_severity=AlertSeverity.LOW)
        assert result == []

    def test_keeps_at_min_severity(self):
        dedup = AlertDeduplicator()
        alert = _make_alert(severity=AlertSeverity.LOW)
        deduped = DedupedAlert(
            original_alert=alert,
            count=3,
            first_seen=alert.timestamp,
            last_seen=alert.timestamp,
            severity=AlertSeverity.LOW,
        )
        result = dedup.filter_noise([deduped], min_count=1, min_severity=AlertSeverity.LOW)
        assert len(result) == 1

    def test_empty_list_returns_empty(self):
        dedup = AlertDeduplicator()
        assert dedup.filter_noise([]) == []
