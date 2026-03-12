"""
Unit tests for app/services/runbook_registry.py

Tests the registry with programmatic population to avoid filesystem config deps.
"""
import os
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from app.models.action import ActionType, RiskLevel
from app.services.runbook_registry import (
    Runbook,
    RunbookAction,
    RunbookRegistry,
    get_runbook_registry,
)


def _make_runbook_action(
    action_type: ActionType = ActionType.RESTART_POD,
    approval_required: bool = True,
    risk_level: RiskLevel = RiskLevel.MEDIUM,
) -> RunbookAction:
    return RunbookAction(
        action_type=action_type,
        description="Restart pod to fix memory leak",
        approval_required=approval_required,
        risk_level=risk_level,
        parameters_template={"namespace": "production"},
    )


def _make_runbook(
    id: str = "mem-leak",
    category: str = "memory_leak",
    service: str | None = None,
    actions: list | None = None,
) -> Runbook:
    return Runbook(
        id=id,
        name="Memory Leak Runbook",
        symptom="High memory usage",
        category=category,
        service=service,
        allowed_actions=actions or [_make_runbook_action()],
        diagnostic_queries={"mem": "container_memory_usage_bytes"},
        escalation_criteria=["Restart loop > 3 times"],
    )


class TestRunbookActionDataclass:
    def test_prerequisites_default_empty(self):
        action = RunbookAction(
            action_type=ActionType.SCALE_UP,
            description="Scale up",
            approval_required=False,
            risk_level=RiskLevel.LOW,
            parameters_template={},
        )
        assert action.prerequisites == []

    def test_prerequisites_preserved_when_provided(self):
        action = RunbookAction(
            action_type=ActionType.SCALE_UP,
            description="Scale up",
            approval_required=False,
            risk_level=RiskLevel.LOW,
            parameters_template={},
            prerequisites=["CPU > 80%"],
        )
        assert action.prerequisites == ["CPU > 80%"]


class TestRunbookDataclass:
    def test_allowed_actions_default_empty(self):
        rb = Runbook(id="x", name="X", symptom="y", category="z")
        assert rb.allowed_actions == []

    def test_diagnostic_queries_default_empty(self):
        rb = Runbook(id="x", name="X", symptom="y", category="z")
        assert rb.diagnostic_queries == {}

    def test_escalation_criteria_default_empty(self):
        rb = Runbook(id="x", name="X", symptom="y", category="z")
        assert rb.escalation_criteria == []


class TestRunbookRegistryWithYamlConfig:
    def test_load_yaml_config(self, tmp_path):
        config = {
            "runbooks": [
                {
                    "id": "mem-restart",
                    "name": "Memory Restart",
                    "symptom": "High memory",
                    "category": "memory_leak",
                    "allowed_actions": [
                        {
                            "action_type": "restart_pod",
                            "description": "Restart the pod",
                            "approval_required": True,
                            "risk_level": "medium",
                            "parameters": {"namespace": "prod"},
                            "prerequisites": ["Memory > 80%"],
                            "max_auto_executions_per_day": 5,
                        }
                    ],
                    "diagnostic_queries": {"mem": "container_memory_usage_bytes"},
                    "escalation_criteria": ["Restart loop"],
                }
            ]
        }
        config_file = tmp_path / "runbooks.yaml"
        config_file.write_text(yaml.dump(config))
        registry = RunbookRegistry(config_path=str(config_file))
        assert len(registry.runbooks) == 1
        assert "mem-restart" in registry.runbooks

    def test_load_json_config(self, tmp_path):
        import json
        config = {
            "runbooks": [
                {
                    "id": "cpu-scale",
                    "name": "CPU Scale",
                    "symptom": "High CPU",
                    "category": "cpu_spike",
                    "allowed_actions": [
                        {
                            "action_type": "scale_up",
                            "description": "Scale up replicas",
                            "approval_required": False,
                            "risk_level": "low",
                            "parameters": {},
                        }
                    ],
                }
            ]
        }
        config_file = tmp_path / "runbooks.json"
        config_file.write_text(json.dumps(config))
        registry = RunbookRegistry(config_path=str(config_file))
        assert "cpu-scale" in registry.runbooks

    def test_empty_runbooks_list(self, tmp_path):
        config = {"runbooks": []}
        config_file = tmp_path / "runbooks.yaml"
        config_file.write_text(yaml.dump(config))
        registry = RunbookRegistry(config_path=str(config_file))
        assert len(registry.runbooks) == 0

    def test_missing_config_path_logs_warning(self, tmp_path, monkeypatch):
        # Point to a nonexistent path; patch _create_example_runbooks so it
        # doesn't attempt to write relative paths that don't exist in test env
        config_file = tmp_path / "nonexistent_runbooks.yaml"
        created_calls = []

        def fake_create(self):
            created_calls.append(True)

        monkeypatch.setattr(RunbookRegistry, "_create_example_runbooks", fake_create)
        registry = RunbookRegistry(config_path=str(config_file))
        assert created_calls == [True]

    def test_invalid_config_results_in_empty_registry(self, tmp_path):
        config_file = tmp_path / "runbooks.yaml"
        config_file.write_text(": invalid: yaml: [\n")
        registry = RunbookRegistry(config_path=str(config_file))
        assert registry.runbooks == {}


class TestRunbookRegistryGetRunbook:
    def _registry_with_runbooks(self, runbooks: list[Runbook]) -> RunbookRegistry:
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        registry.runbooks = {rb.id: rb for rb in runbooks}
        return registry

    def test_get_runbook_by_category(self):
        registry = self._registry_with_runbooks([_make_runbook(category="memory_leak")])
        result = registry.get_runbook_for_category("memory_leak")
        assert result is not None
        assert result.category == "memory_leak"

    def test_get_runbook_exact_service_match(self):
        generic = _make_runbook(id="generic", category="cpu_spike", service=None)
        specific = _make_runbook(
            id="specific", category="cpu_spike", service="payment-service"
        )
        registry = self._registry_with_runbooks([generic, specific])
        result = registry.get_runbook_for_category("cpu_spike", service="payment-service")
        assert result.id == "specific"

    def test_get_runbook_falls_back_to_generic(self):
        generic = _make_runbook(id="generic", category="cpu_spike", service=None)
        registry = self._registry_with_runbooks([generic])
        result = registry.get_runbook_for_category("cpu_spike", service="some-service")
        assert result.id == "generic"

    def test_get_runbook_no_match_returns_none(self):
        registry = self._registry_with_runbooks([_make_runbook(category="memory_leak")])
        result = registry.get_runbook_for_category("unknown_category")
        assert result is None

    def test_get_runbook_no_service_arg(self):
        registry = self._registry_with_runbooks([_make_runbook(category="memory_leak", service=None)])
        result = registry.get_runbook_for_category("memory_leak")
        assert result is not None


class TestRunbookRegistryGetAllowedActions:
    def _registry_with_runbooks(self, runbooks: list[Runbook]) -> RunbookRegistry:
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        registry.runbooks = {rb.id: rb for rb in runbooks}
        return registry

    def test_returns_actions_for_known_category(self):
        action = _make_runbook_action(ActionType.RESTART_POD)
        registry = self._registry_with_runbooks([_make_runbook(actions=[action])])
        actions = registry.get_allowed_actions("memory_leak")
        assert len(actions) == 1
        assert actions[0].action_type == ActionType.RESTART_POD

    def test_returns_empty_for_unknown_category(self):
        registry = self._registry_with_runbooks([_make_runbook(category="memory_leak")])
        actions = registry.get_allowed_actions("no_such_category")
        assert actions == []


class TestRunbookRegistryIsActionAllowed:
    def _registry_with_runbooks(self, runbooks: list[Runbook]) -> RunbookRegistry:
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        registry.runbooks = {rb.id: rb for rb in runbooks}
        return registry

    def test_allowed_action_returns_true(self):
        action = _make_runbook_action(ActionType.RESTART_POD)
        registry = self._registry_with_runbooks([_make_runbook(actions=[action])])
        assert registry.is_action_allowed(ActionType.RESTART_POD, "memory_leak") is True

    def test_disallowed_action_returns_false(self):
        action = _make_runbook_action(ActionType.RESTART_POD)
        registry = self._registry_with_runbooks([_make_runbook(actions=[action])])
        assert registry.is_action_allowed(ActionType.SCALE_UP, "memory_leak") is False

    def test_unknown_category_returns_false(self):
        action = _make_runbook_action(ActionType.RESTART_POD)
        registry = self._registry_with_runbooks([_make_runbook(actions=[action])])
        assert registry.is_action_allowed(ActionType.RESTART_POD, "no_category") is False


class TestRunbookRegistryGetAllRunbooks:
    def test_returns_all_runbooks_as_list(self):
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        rb1 = _make_runbook(id="rb1", category="memory_leak")
        rb2 = _make_runbook(id="rb2", category="cpu_spike")
        registry.runbooks = {"rb1": rb1, "rb2": rb2}
        result = registry.get_all_runbooks()
        assert len(result) == 2

    def test_empty_registry_returns_empty_list(self):
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        registry.runbooks = {}
        assert registry.get_all_runbooks() == []


class TestRunbookRegistryFindDefaultConfig:
    def test_returns_string(self, tmp_path):
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        result = registry._find_default_config()
        assert isinstance(result, str)

    def test_returns_env_var_path_if_exists(self, tmp_path, monkeypatch):
        config_file = tmp_path / "runbooks.yaml"
        config_file.write_text("")
        monkeypatch.setenv("AIRRA_RUNBOOKS_CONFIG", str(config_file))
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        result = registry._find_default_config()
        assert result == str(config_file)


class TestGetRunbookRegistry:
    def test_returns_instance(self, monkeypatch):
        import app.services.runbook_registry as mod
        monkeypatch.setattr(mod, "_runbook_registry", None)
        # We need to point to a non-existent path to trigger example creation
        # but avoid writing to cwd in tests. Patch _load_runbooks to do nothing.
        monkeypatch.setattr(RunbookRegistry, "_load_runbooks", lambda self: None)
        result = mod.get_runbook_registry()
        assert isinstance(result, RunbookRegistry)

    def test_singleton_returned(self, monkeypatch):
        import app.services.runbook_registry as mod
        registry = RunbookRegistry.__new__(RunbookRegistry)
        registry.config_path = "dummy"
        registry.runbooks = {}
        monkeypatch.setattr(mod, "_runbook_registry", registry)
        result = mod.get_runbook_registry()
        assert result is registry
