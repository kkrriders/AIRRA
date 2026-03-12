"""
Unit tests for app/services/incident_summarizer.py

Uses MagicMock for the Incident ORM object — no DB needed.
"""
from unittest.mock import MagicMock

from app.services.incident_summarizer import (
    IncidentSummarizer,
    _infer_error_patterns,
)


def _mock_incident(
    service: str = "payment-service",
    severity_value: str = "high",
    title: str = "High Memory Usage",
    description: str = "Memory usage exceeded threshold",
    metrics_snapshot: dict | None = None,
    affected_components: list | None = None,
    context: dict | None = None,
) -> MagicMock:
    incident = MagicMock()
    incident.affected_service = service
    incident.severity = MagicMock()
    incident.severity.value = severity_value
    incident.title = title
    incident.description = description
    incident.metrics_snapshot = metrics_snapshot
    incident.affected_components = affected_components
    incident.context = context or {}
    return incident


class TestInferErrorPatterns:
    def test_empty_metrics_returns_empty(self):
        assert _infer_error_patterns({}) == []

    def test_none_metrics_returns_empty(self):
        assert _infer_error_patterns(None) == []

    def test_error_rate_pattern(self):
        metrics = {"http_error_count": 100}
        patterns = _infer_error_patterns(metrics)
        assert "error_rate_spike" in patterns

    def test_connection_pattern(self):
        metrics = {"db_connection_pool": 90}
        patterns = _infer_error_patterns(metrics)
        assert "connection_failure" in patterns

    def test_memory_pattern(self):
        metrics = {"memory_usage_bytes": 8e9}
        patterns = _infer_error_patterns(metrics)
        assert "memory_pressure" in patterns

    def test_heap_pattern(self):
        metrics = {"heap_allocated": 500}
        patterns = _infer_error_patterns(metrics)
        assert "memory_pressure" in patterns

    def test_cpu_pattern(self):
        metrics = {"cpu_usage_percent": 98}
        patterns = _infer_error_patterns(metrics)
        assert "cpu_saturation" in patterns

    def test_latency_pattern(self):
        metrics = {"request_latency_p99": 5.0}
        patterns = _infer_error_patterns(metrics)
        assert "latency_degradation" in patterns

    def test_cache_pattern(self):
        metrics = {"cache_hit_rate": 0.1}
        patterns = _infer_error_patterns(metrics)
        assert "cache_miss_storm" in patterns

    def test_disk_pattern(self):
        metrics = {"disk_iops": 10000}
        patterns = _infer_error_patterns(metrics)
        assert "disk_pressure" in patterns

    def test_queue_pattern(self):
        metrics = {"queue_backlog_size": 9000}
        patterns = _infer_error_patterns(metrics)
        assert "queue_buildup" in patterns

    def test_max_three_patterns_returned(self):
        # Provide metrics triggering many patterns
        metrics = {
            "http_error_count": 100,
            "db_connection_pool": 90,
            "memory_usage_bytes": 8e9,
            "cpu_usage_percent": 98,
            "latency_p99": 5.0,
        }
        patterns = _infer_error_patterns(metrics)
        assert len(patterns) <= 3

    def test_5xx_pattern(self):
        metrics = {"rate_5xx_errors": 50}
        patterns = _infer_error_patterns(metrics)
        assert "error_rate_spike" in patterns

    def test_timeout_pattern(self):
        metrics = {"request_timeout_count": 30}
        patterns = _infer_error_patterns(metrics)
        assert "connection_failure" in patterns


class TestIncidentSummarizerSummarize:
    def setup_method(self):
        self.summarizer = IncidentSummarizer()

    def test_basic_fields_present(self):
        incident = _mock_incident()
        result = self.summarizer.summarize(incident)
        assert "Service: payment-service" in result
        assert "Severity: HIGH" in result
        assert "Title: High Memory Usage" in result
        assert "Description:" in result

    def test_severity_mapped_correctly(self):
        for sev_val, expected_label in [
            ("critical", "CRITICAL"),
            ("high", "HIGH"),
            ("medium", "MEDIUM"),
            ("low", "LOW"),
        ]:
            incident = _mock_incident(severity_value=sev_val)
            result = self.summarizer.summarize(incident)
            assert expected_label in result

    def test_unknown_severity_uses_raw_value(self):
        incident = _mock_incident(severity_value="custom_sev")
        result = self.summarizer.summarize(incident)
        assert "custom_sev" in result

    def test_description_truncated_when_long(self):
        long_desc = "x" * 400
        incident = _mock_incident(description=long_desc)
        result = self.summarizer.summarize(incident)
        assert "..." in result
        # Original 400-char desc should be truncated
        lines = [line for line in result.split("\n") if line.startswith("Description:")]
        assert len(lines[0]) < 400

    def test_description_not_truncated_when_short(self):
        desc = "Short description."
        incident = _mock_incident(description=desc)
        result = self.summarizer.summarize(incident)
        assert desc in result

    def test_extra_context_root_cause_included(self):
        incident = _mock_incident()
        result = self.summarizer.summarize(
            incident,
            extra_context={"actual_root_cause": "Cache eviction bug", "resolution": "Cleared cache"},
        )
        assert "Root cause: Cache eviction bug" in result
        assert "Resolution: Cleared cache" in result

    def test_extra_context_description_limit_reduced(self):
        long_desc = "x" * 200
        incident = _mock_incident(description=long_desc)
        result_ctx = self.summarizer.summarize(
            incident, extra_context={"actual_root_cause": "bug"}
        )
        # With context, description is limited to 150 chars
        desc_line_ctx = [line for line in result_ctx.split("\n") if line.startswith("Description:")][0]
        assert len(desc_line_ctx) <= 165  # "Description: " + 150 + "..."

    def test_extra_context_empty_root_cause_skipped(self):
        incident = _mock_incident()
        result = self.summarizer.summarize(incident, extra_context={"actual_root_cause": ""})
        assert "Root cause:" not in result

    def test_extra_context_empty_resolution_skipped(self):
        incident = _mock_incident()
        result = self.summarizer.summarize(incident, extra_context={"resolution": ""})
        assert "Resolution:" not in result

    def test_metrics_primary_anomaly_shown(self):
        metrics = {
            "memory_usage": {"current": 7.5e9, "expected": 2e9, "deviation_sigma": 5.5},
            "cpu_usage": {"current": 90, "expected": 40, "deviation_sigma": 3.0},
        }
        incident = _mock_incident(metrics_snapshot=metrics)
        result = self.summarizer.summarize(incident)
        assert "Primary anomaly:" in result
        assert "memory_usage" in result  # highest sigma

    def test_metrics_sigma_formatted(self):
        metrics = {
            "latency": {"current": 5.0, "expected": 0.2, "deviation_sigma": 12.0},
        }
        incident = _mock_incident(metrics_snapshot=metrics)
        result = self.summarizer.summarize(incident)
        assert "12.0σ" in result

    def test_metrics_symptoms_section(self):
        metrics = {
            "error_rate": {"current": 50, "expected": 1, "deviation_sigma": 8.0},
        }
        incident = _mock_incident(metrics_snapshot=metrics)
        result = self.summarizer.summarize(incident)
        assert "Symptoms:" in result

    def test_metrics_non_dict_value_shown(self):
        metrics = {"simple_metric": "raw_value"}
        incident = _mock_incident(metrics_snapshot=metrics)
        result = self.summarizer.summarize(incident)
        assert "simple_metric" in result
        assert "raw_value" in result

    def test_no_metrics_no_symptoms_section(self):
        incident = _mock_incident(metrics_snapshot=None)
        result = self.summarizer.summarize(incident)
        assert "Symptoms:" not in result
        assert "Primary anomaly:" not in result

    def test_empty_metrics_dict_no_symptoms(self):
        incident = _mock_incident(metrics_snapshot={})
        result = self.summarizer.summarize(incident)
        assert "Symptoms:" not in result

    def test_multiple_components_shown(self):
        incident = _mock_incident(affected_components=["api", "cache", "db"])
        result = self.summarizer.summarize(incident)
        assert "Components:" in result
        assert "api" in result
        assert "cache" in result

    def test_single_component_not_shown(self):
        incident = _mock_incident(affected_components=["api"])
        result = self.summarizer.summarize(incident)
        assert "Components:" not in result

    def test_no_components_no_components_line(self):
        incident = _mock_incident(affected_components=None)
        result = self.summarizer.summarize(incident)
        assert "Components:" not in result

    def test_error_patterns_included(self):
        metrics = {"memory_usage_bytes": 8e9}
        incident = _mock_incident(metrics_snapshot=metrics)
        result = self.summarizer.summarize(incident)
        assert "Error patterns:" in result
        assert "memory_pressure" in result

    def test_blast_radius_high_shown(self):
        ctx = {
            "blast_radius": {
                "level": "high",
                "urgency_multiplier": 1.5,
                "affected_services_count": 3,
            }
        }
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "Blast radius: high" in result

    def test_blast_radius_low_not_shown(self):
        ctx = {"blast_radius": {"level": "low"}}
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "Blast radius:" not in result

    def test_blast_radius_minimal_not_shown(self):
        ctx = {"blast_radius": {"level": "minimal"}}
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "Blast radius:" not in result

    def test_upstream_dependencies_shown(self):
        ctx = {"upstream_dependencies": ["postgres", "redis"]}
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "Upstream dependencies: postgres, redis" in result

    def test_upstream_dependencies_not_shown_when_empty(self):
        incident = _mock_incident(context={})
        result = self.summarizer.summarize(incident)
        assert "Upstream dependencies:" not in result

    def test_context_tag_auto_detected(self):
        ctx = {"auto_detected": True}
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "auto_detected" in result

    def test_context_tag_anomaly_count(self):
        ctx = {"anomaly_count": 7}
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "7 anomalies" in result

    def test_context_tag_ai_generated(self):
        ctx = {"ai_generated": True}
        incident = _mock_incident(context=ctx)
        result = self.summarizer.summarize(incident)
        assert "ai_generated" in result

    def test_no_context_tags_no_context_line(self):
        incident = _mock_incident(context={})
        result = self.summarizer.summarize(incident)
        assert "Context:" not in result

    def test_returns_string(self):
        incident = _mock_incident()
        result = self.summarizer.summarize(incident)
        assert isinstance(result, str)

    def test_metrics_at_most_5_anomaly_lines(self):
        metrics = {f"metric_{i}": {"current": i, "expected": 0, "deviation_sigma": float(i)} for i in range(10)}
        incident = _mock_incident(metrics_snapshot=metrics)
        result = self.summarizer.summarize(incident)
        # Count anomaly lines (lines starting with "  - ")
        anomaly_lines = [line for line in result.split("\n") if line.strip().startswith("- ")]
        assert len(anomaly_lines) <= 5

    def test_extra_context_root_cause_truncated_at_200(self):
        long_rc = "R" * 300
        incident = _mock_incident()
        result = self.summarizer.summarize(incident, extra_context={"actual_root_cause": long_rc})
        rc_line = [line for line in result.split("\n") if line.startswith("Root cause:")][0]
        # Should be "Root cause: " + 200 chars
        assert len(rc_line) <= len("Root cause: ") + 200


class TestGetSummarizer:
    def test_returns_instance(self, monkeypatch):
        import app.services.incident_summarizer as mod
        monkeypatch.setattr(mod, "_summarizer", None)
        s = mod.get_summarizer()
        assert isinstance(s, IncidentSummarizer)

    def test_returns_singleton(self, monkeypatch):
        import app.services.incident_summarizer as mod
        summarizer = IncidentSummarizer()
        monkeypatch.setattr(mod, "_summarizer", summarizer)
        result = mod.get_summarizer()
        assert result is summarizer
