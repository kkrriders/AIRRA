"""
Incident summarizer — builds compact structured text from an Incident for embedding.

Design rationale:
- Pure Python, zero LLM calls (LLM would add latency + cost per embed)
- Structured format (key: value) produces tighter semantic clusters than free-form prose
- Top 5 anomalies by deviation_sigma are selected; the rest are truncated to stay within
  all-MiniLM-L6-v2's 256-token sweet spot (sentences beyond ~256 wordpiece tokens
  are truncated by the tokenizer anyway, so we don't gain anything from longer text)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.incident import Incident

logger = logging.getLogger(__name__)

_SEVERITY_MAP = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MEDIUM",
    "low": "LOW",
}

# Keyword → pattern name mapping used to produce structured error pattern tags from
# metric names.  Deterministic: no LLM, no ML — just string matching on metric keys.
_ERROR_PATTERN_RULES: list[tuple[list[str], str]] = [
    (["error", "5xx", "4xx", "failure"],        "error_rate_spike"),
    (["connection", "timeout", "refused"],       "connection_failure"),
    (["memory", "heap", "oom", "gc_pause"],      "memory_pressure"),
    (["cpu", "load_average", "context_switch"],  "cpu_saturation"),
    (["latency", "p99", "p95", "duration"],      "latency_degradation"),
    (["cache", "hit_rate", "eviction"],          "cache_miss_storm"),
    (["disk", "iops", "io_wait"],               "disk_pressure"),
    (["queue", "backlog", "lag"],               "queue_buildup"),
]


def _infer_error_patterns(metrics: dict) -> list[str]:
    """
    Infer structured error-pattern tags from metric names.

    Returns at most 3 patterns sorted by order of appearance to keep the
    embedding text concise and avoid drowning the token budget with tags.
    """
    if not metrics:
        return []
    combined = " ".join(metrics.keys()).lower()
    patterns: list[str] = []
    for keywords, label in _ERROR_PATTERN_RULES:
        if any(kw in combined for kw in keywords):
            patterns.append(label)
        if len(patterns) == 3:
            break
    return patterns


class IncidentSummarizer:
    """
    Converts an Incident object into compact structured text suitable for embedding.

    The output is intentionally human-readable — this helps during debugging
    and keeps the embedding space interpretable.
    """

    def summarize(self, incident: "Incident", extra_context: dict | None = None) -> str:
        """
        Build a compact structured text representation of an incident.

        Args:
            incident: The Incident ORM object to summarize.
            extra_context: Optional dict with resolved-incident enrichment, e.g.:
                           {"actual_root_cause": "...", "resolution": "..."}
                           Appended after the core summary to enrich embeddings of
                           resolved incidents, making future retrieval more accurate.

        Returns:
            Structured text string, ~100-250 characters.
        """
        lines: list[str] = [
            f"Service: {incident.affected_service}",
            f"Severity: {_SEVERITY_MAP.get(incident.severity.value, incident.severity.value)}",
            f"Title: {incident.title}",
        ]

        # Resolution enrichment placed EARLY so it survives the 256-token truncation
        # window of all-MiniLM-L6-v2.  Root cause + resolution are the most valuable
        # signals for RAG matching — putting them last (after symptoms) would risk
        # losing them on re-embeddings of resolved incidents.
        if extra_context:
            root_cause = extra_context.get("actual_root_cause", "")
            resolution = extra_context.get("resolution", "")
            if root_cause:
                lines.append(f"Root cause: {root_cause[:200]}")
            if resolution:
                lines.append(f"Resolution: {resolution[:200]}")

        # Description — truncate more aggressively when resolution context is present
        # (description adds noise; root_cause above is the discriminative signal).
        desc = incident.description or ""
        desc_limit = 150 if extra_context else 300
        if len(desc) > desc_limit:
            desc = desc[:desc_limit - 3] + "..."
        lines.append(f"Description: {desc}")

        # Top anomalies from metrics_snapshot, sorted by deviation
        metrics = incident.metrics_snapshot or {}
        sorted_metrics: list = []
        if metrics:
            sorted_metrics = sorted(
                metrics.items(),
                key=lambda kv: kv[1].get("deviation_sigma", 0) if isinstance(kv[1], dict) else 0,
                reverse=True,
            )

            # Primary anomaly line (dominant signal — most useful for RAG matching)
            if sorted_metrics:
                primary_name, primary_data = sorted_metrics[0]
                if isinstance(primary_data, dict):
                    sigma = primary_data.get("deviation_sigma", "?")
                    sigma_str = f"{sigma:.1f}σ" if isinstance(sigma, float) else str(sigma)
                    lines.append(f"Primary anomaly: {primary_name} ({sigma_str} deviation)")

            anomaly_lines: list[str] = []
            for metric_name, data in sorted_metrics[:5]:
                if isinstance(data, dict):
                    current = data.get("current", "?")
                    expected = data.get("expected", "?")
                    sigma = data.get("deviation_sigma", "?")
                    if isinstance(sigma, float):
                        sigma = f"{sigma:.1f}σ"
                    anomaly_lines.append(f"  - {metric_name}: {current} (expected {expected}, {sigma})")
                else:
                    anomaly_lines.append(f"  - {metric_name}: {data}")
            if anomaly_lines:
                lines.append("Symptoms:")
                lines.extend(anomaly_lines)

        # Affected components (multi-component incidents have richer matching signal)
        components = incident.affected_components or []
        if len(components) > 1:
            lines.append(f"Components: {', '.join(str(c) for c in components[:5])}")

        # Error patterns — structured tags inferred from metric names
        error_patterns = _infer_error_patterns(metrics)
        if error_patterns:
            lines.append(f"Error patterns: {', '.join(error_patterns)}")

        # Dependency / blast radius context (from incident context dict, set by anomaly_monitor)
        ctx = incident.context or {}
        blast = ctx.get("blast_radius", {})
        if blast.get("level") and blast["level"] not in ("minimal", "low"):
            lines.append(
                f"Blast radius: {blast['level']} "
                f"(urgency {blast.get('urgency_multiplier', 1.0):.1f}x, "
                f"{blast.get('affected_services_count', 0)} downstream services)"
            )
        upstream = ctx.get("upstream_dependencies", [])
        if upstream:
            lines.append(f"Upstream dependencies: {', '.join(upstream[:5])}")

        # Context tags (detection source, anomaly count)
        context_tags: list[str] = []
        if ctx.get("auto_detected"):
            context_tags.append("auto_detected")
        if ctx.get("anomaly_count"):
            context_tags.append(f"{ctx['anomaly_count']} anomalies")
        if ctx.get("ai_generated"):
            context_tags.append("ai_generated")
        if context_tags:
            lines.append(f"Context: {', '.join(context_tags)}")

        # (Resolution enrichment already written near the top of the text)

        return "\n".join(lines)


# Module-level singleton
_summarizer: IncidentSummarizer | None = None


def get_summarizer() -> IncidentSummarizer:
    global _summarizer
    if _summarizer is None:
        _summarizer = IncidentSummarizer()
    return _summarizer
