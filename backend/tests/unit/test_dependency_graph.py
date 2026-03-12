"""
Unit tests for app/services/dependency_graph.py

Pure in-memory logic — no DB or HTTP deps needed.
Uses programmatic population to avoid file-system complexity.
"""
import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from app.services.dependency_graph import (
    DependencyGraph,
    ServiceDependency,
    get_dependency_graph,
)


def _make_graph_with_services(services: dict) -> DependencyGraph:
    """
    Build a DependencyGraph with pre-loaded dependencies
    (bypasses config file loading).
    """
    graph = DependencyGraph.__new__(DependencyGraph)
    graph.config_path = "dummy"
    graph.dependencies = {}

    # First pass: create services
    for svc_name, svc_cfg in services.items():
        graph.dependencies[svc_name] = ServiceDependency(
            service=svc_name,
            depends_on=svc_cfg.get("depends_on", []),
            depended_by=[],
            tier=svc_cfg.get("tier"),
            team=svc_cfg.get("team"),
            criticality=svc_cfg.get("criticality", "medium"),
        )

    # Second pass: fill in depended_by
    for svc_name, svc_dep in graph.dependencies.items():
        for upstream in svc_dep.depends_on:
            if upstream in graph.dependencies:
                graph.dependencies[upstream].depended_by.append(svc_name)

    return graph


# A sample topology:
# frontend → api-gateway → payment-service → database
#                        → auth-service    → database
#                        → order-service  → database
SAMPLE_SERVICES = {
    "frontend": {"depends_on": ["api-gateway"], "tier": "tier-1", "team": "fe", "criticality": "high"},
    "api-gateway": {"depends_on": ["payment-service", "auth-service", "order-service"], "tier": "tier-1", "team": "platform", "criticality": "critical"},
    "payment-service": {"depends_on": ["database", "redis"], "tier": "tier-1", "team": "payments", "criticality": "critical"},
    "auth-service": {"depends_on": ["database", "redis"], "tier": "tier-1", "team": "platform", "criticality": "critical"},
    "order-service": {"depends_on": ["database"], "tier": "tier-2", "team": "orders", "criticality": "high"},
    "database": {"depends_on": [], "tier": "tier-0", "team": "infra", "criticality": "critical"},
    "redis": {"depends_on": [], "tier": "tier-0", "team": "infra", "criticality": "high"},
}


class TestDependencyGraphInit:
    def test_init_with_yaml_config(self, tmp_path):
        config = {
            "services": {
                "api": {"depends_on": ["db"], "tier": "tier-1", "team": "core", "criticality": "high"},
                "db": {"depends_on": [], "tier": "tier-0", "team": "infra", "criticality": "critical"},
            }
        }
        config_file = tmp_path / "deps.yaml"
        config_file.write_text(yaml.dump(config))
        graph = DependencyGraph(config_path=str(config_file))
        assert "api" in graph.dependencies
        assert "db" in graph.dependencies

    def test_init_with_json_config(self, tmp_path):
        import json
        config = {
            "services": {
                "svc-a": {"depends_on": ["svc-b"], "criticality": "medium"},
                "svc-b": {"depends_on": [], "criticality": "low"},
            }
        }
        config_file = tmp_path / "deps.json"
        config_file.write_text(json.dumps(config))
        graph = DependencyGraph(config_path=str(config_file))
        assert "svc-a" in graph.dependencies

    def test_missing_config_creates_example(self, tmp_path, monkeypatch):
        config_file = tmp_path / "deps.yaml"
        created_calls = []

        def fake_create(self):
            created_calls.append(True)

        monkeypatch.setattr(DependencyGraph, "_create_example_config", fake_create)
        graph = DependencyGraph(config_path=str(config_file))
        assert created_calls == [True]

    def test_reverse_deps_populated(self, tmp_path):
        config = {
            "services": {
                "app": {"depends_on": ["db"]},
                "db": {"depends_on": []},
            }
        }
        config_file = tmp_path / "deps.yaml"
        config_file.write_text(yaml.dump(config))
        graph = DependencyGraph(config_path=str(config_file))
        assert "app" in graph.dependencies["db"].depended_by

    def test_invalid_yaml_results_in_empty_graph(self, tmp_path):
        config_file = tmp_path / "bad.yaml"
        config_file.write_text(": [bad yaml")
        graph = DependencyGraph(config_path=str(config_file))
        assert graph.dependencies == {}

    def test_find_default_config_env_var(self, tmp_path, monkeypatch):
        config_file = tmp_path / "custom_deps.yaml"
        # File must exist for the env-var branch to be selected
        config_file.write_text("services: {}")
        monkeypatch.setenv("AIRRA_DEPENDENCY_CONFIG", str(config_file))
        # Also ensure the other default paths do NOT exist
        with patch("os.path.exists", side_effect=lambda p: p == str(config_file)):
            graph = DependencyGraph.__new__(DependencyGraph)
            result = graph._find_default_config()
        assert result == str(config_file)

    def test_find_default_config_returns_string(self):
        graph = DependencyGraph.__new__(DependencyGraph)
        result = graph._find_default_config()
        assert isinstance(result, str)


class TestGetUpstreamDependencies:
    def setup_method(self):
        self.graph = _make_graph_with_services(SAMPLE_SERVICES)

    def test_direct_upstream(self):
        deps = self.graph.get_upstream_dependencies("api-gateway")
        assert "payment-service" in deps
        assert "auth-service" in deps

    def test_unknown_service_returns_empty(self):
        deps = self.graph.get_upstream_dependencies("unknown-svc")
        assert deps == []

    def test_leaf_node_has_no_upstream(self):
        deps = self.graph.get_upstream_dependencies("database")
        assert deps == []


class TestGetDownstreamDependents:
    def setup_method(self):
        self.graph = _make_graph_with_services(SAMPLE_SERVICES)

    def test_database_has_dependents(self):
        deps = self.graph.get_downstream_dependents("database")
        assert len(deps) >= 1

    def test_unknown_service_returns_empty(self):
        deps = self.graph.get_downstream_dependents("unknown")
        assert deps == []

    def test_frontend_has_no_dependents(self):
        deps = self.graph.get_downstream_dependents("frontend")
        assert deps == []


class TestIsUpstreamOf:
    def setup_method(self):
        self.graph = _make_graph_with_services(SAMPLE_SERVICES)

    def test_direct_upstream_detected(self):
        # api-gateway depends on payment-service
        assert self.graph.is_upstream_of("payment-service", "api-gateway") is True

    def test_transitive_upstream_detected(self):
        # database → payment-service → api-gateway → frontend
        assert self.graph.is_upstream_of("database", "frontend") is True

    def test_non_upstream_returns_false(self):
        # frontend does NOT depend on redis (indirectly, maybe; but let's use auth-service)
        assert self.graph.is_upstream_of("frontend", "database") is False

    def test_unknown_service_returns_false(self):
        assert self.graph.is_upstream_of("unknown", "api-gateway") is False

    def test_target_unknown_returns_false(self):
        assert self.graph.is_upstream_of("database", "no-svc") is False

    def test_cycle_safe(self):
        # Manually create a circular dependency
        graph = _make_graph_with_services({
            "svc-a": {"depends_on": ["svc-b"]},
            "svc-b": {"depends_on": ["svc-a"]},
        })
        # Should not infinite-loop
        result = graph.is_upstream_of("svc-b", "svc-a")
        assert isinstance(result, bool)


class TestCalculateDependencyBoost:
    def setup_method(self):
        self.graph = _make_graph_with_services(SAMPLE_SERVICES)

    def test_same_service_no_boost(self):
        boost = self.graph.calculate_dependency_boost("api-gateway", "api-gateway")
        assert boost == 0.0

    def test_direct_upstream_gives_high_boost(self):
        # payment-service is a direct upstream of api-gateway
        boost = self.graph.calculate_dependency_boost("api-gateway", "payment-service")
        assert boost == 0.15

    def test_transitive_upstream_gives_lower_boost(self):
        # database is transitive upstream of api-gateway (not direct)
        boost = self.graph.calculate_dependency_boost("api-gateway", "database")
        assert boost == 0.08

    def test_downstream_hypothesis_penalized(self):
        # frontend is downstream of api-gateway
        boost = self.graph.calculate_dependency_boost("database", "api-gateway")
        assert boost == -0.05

    def test_unrelated_services_no_boost(self):
        # redis has no relationship to frontend except through api-gateway
        # but let's use truly unrelated services
        graph = _make_graph_with_services({
            "svc-x": {"depends_on": []},
            "svc-y": {"depends_on": []},
        })
        boost = graph.calculate_dependency_boost("svc-x", "svc-y")
        assert boost == 0.0


class TestGetCriticalityScore:
    def setup_method(self):
        self.graph = _make_graph_with_services(SAMPLE_SERVICES)

    def test_critical_service_score(self):
        score = self.graph.get_criticality_score("database")
        assert score == 0.9

    def test_high_service_score(self):
        score = self.graph.get_criticality_score("redis")
        assert score == 0.7

    def test_unknown_service_default_medium(self):
        score = self.graph.get_criticality_score("unknown-svc")
        assert score == 0.5

    def test_medium_service_score(self):
        graph = _make_graph_with_services({
            "svc": {"depends_on": [], "criticality": "medium"},
        })
        score = graph.get_criticality_score("svc")
        assert score == 0.5

    def test_low_service_score(self):
        graph = _make_graph_with_services({
            "svc": {"depends_on": [], "criticality": "low"},
        })
        score = graph.get_criticality_score("svc")
        assert score == 0.3

    def test_unknown_criticality_defaults_to_medium(self):
        graph = _make_graph_with_services({
            "svc": {"depends_on": [], "criticality": "nonexistent_level"},
        })
        score = graph.get_criticality_score("svc")
        assert score == 0.5


class TestGetServiceInfo:
    def setup_method(self):
        self.graph = _make_graph_with_services(SAMPLE_SERVICES)

    def test_known_service_returns_dependency(self):
        info = self.graph.get_service_info("database")
        assert info is not None
        assert info.service == "database"

    def test_unknown_service_returns_none(self):
        info = self.graph.get_service_info("no-svc")
        assert info is None


class TestGetAllServices:
    def test_returns_all_service_names(self):
        graph = _make_graph_with_services(SAMPLE_SERVICES)
        services = graph.get_all_services()
        assert set(services) == set(SAMPLE_SERVICES.keys())

    def test_empty_graph_returns_empty_list(self):
        graph = _make_graph_with_services({})
        assert graph.get_all_services() == []


class TestGetDependencyGraph:
    def test_returns_instance(self, monkeypatch):
        import app.services.dependency_graph as mod
        monkeypatch.setattr(mod, "_dependency_graph", None)
        monkeypatch.setattr(DependencyGraph, "_load_dependencies", lambda self: None)
        result = mod.get_dependency_graph()
        assert isinstance(result, DependencyGraph)

    def test_singleton(self, monkeypatch):
        import app.services.dependency_graph as mod
        graph = _make_graph_with_services({})
        monkeypatch.setattr(mod, "_dependency_graph", graph)
        result = mod.get_dependency_graph()
        assert result is graph
