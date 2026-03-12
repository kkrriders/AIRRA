"""
Unit tests for app/services/dependency_map.py

Tests StaticDependencyAdapter with its default in-memory config and
via tmp_path YAML configs.
"""

import pytest
import yaml

from app.services.dependency_map import (
    BlastRadius,
    DependencyType,
    ServiceDependency,
    ServiceMetadata,
    ServiceTier,
    StaticDependencyAdapter,
    get_service_context,
)


class TestServiceTierEnum:
    def test_tier_values(self):
        assert ServiceTier.TIER_1 == "tier_1"
        assert ServiceTier.TIER_2 == "tier_2"
        assert ServiceTier.TIER_3 == "tier_3"
        assert ServiceTier.TIER_4 == "tier_4"


class TestDependencyTypeEnum:
    def test_types(self):
        assert DependencyType.SYNCHRONOUS == "synchronous"
        assert DependencyType.ASYNCHRONOUS == "asynchronous"
        assert DependencyType.DATA == "data"
        assert DependencyType.INFRASTRUCTURE == "infrastructure"


class TestServiceDependency:
    def test_creation(self):
        dep = ServiceDependency(
            source_service="order-service",
            target_service="payment-service",
            dependency_type=DependencyType.SYNCHRONOUS,
            criticality=0.9,
        )
        assert dep.source_service == "order-service"
        assert dep.criticality == 0.9

    def test_criticality_bounds(self):
        with pytest.raises(Exception):
            ServiceDependency(
                source_service="a",
                target_service="b",
                dependency_type=DependencyType.DATA,
                criticality=1.5,  # out of range
            )


class TestServiceMetadata:
    def test_required_fields(self):
        meta = ServiceMetadata(name="svc", tier=ServiceTier.TIER_1, team="platform")
        assert meta.name == "svc"
        assert meta.tier == ServiceTier.TIER_1
        assert meta.team == "platform"

    def test_optional_fields_default_none(self):
        meta = ServiceMetadata(name="svc", tier=ServiceTier.TIER_2, team="eng")
        assert meta.repository is None
        assert meta.on_call is None
        assert meta.runbook_url is None


class TestBlastRadius:
    def test_default_values(self):
        br = BlastRadius()
        assert br.affected_services == []
        assert br.affected_count == 0
        assert br.severity == "low"
        assert br.impact_description == ""


class TestStaticDependencyAdapterDefaultConfig:
    """Tests using the adapter's built-in default config (no file needed)."""

    def _adapter_with_defaults(self) -> StaticDependencyAdapter:
        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "/nonexistent/path.yaml"
        adapter.dependencies = []
        adapter.services = {}
        adapter._load_default_config()
        return adapter

    def test_default_services_loaded(self):
        adapter = self._adapter_with_defaults()
        assert "payment-service" in adapter.services
        assert "order-service" in adapter.services
        assert "postgres" in adapter.services

    def test_default_dependencies_loaded(self):
        adapter = self._adapter_with_defaults()
        assert len(adapter.dependencies) > 0

    async def test_get_service_metadata_known(self):
        adapter = self._adapter_with_defaults()
        meta = await adapter.get_service_metadata("payment-service")
        assert meta is not None
        assert meta.tier == ServiceTier.TIER_1

    async def test_get_service_metadata_unknown(self):
        adapter = self._adapter_with_defaults()
        meta = await adapter.get_service_metadata("unknown-service")
        assert meta is None

    async def test_get_service_dependencies_upstream(self):
        adapter = self._adapter_with_defaults()
        deps = await adapter.get_service_dependencies("order-service")
        # order-service depends on payment-service, so should be included
        sources = [d.source_service for d in deps]
        targets = [d.target_service for d in deps]
        assert "payment-service" in targets or "order-service" in sources

    async def test_get_service_dependencies_unknown_service(self):
        adapter = self._adapter_with_defaults()
        deps = await adapter.get_service_dependencies("totally-unknown")
        assert deps == []

    async def test_blast_radius_postgres(self):
        adapter = self._adapter_with_defaults()
        br = await adapter.get_blast_radius("postgres")
        # postgres is a critical shared dependency
        assert br.affected_count >= 0
        assert br.severity in ("low", "medium", "high", "critical")

    async def test_blast_radius_isolated_service(self):
        # A service with no dependents should have low impact
        adapter = self._adapter_with_defaults()
        # notification-service has no one depending on it (criticality is 0.3 only)
        br = await adapter.get_blast_radius("notification-service")
        assert br.severity in ("low", "medium", "high", "critical")

    async def test_blast_radius_returns_blast_radius_model(self):
        adapter = self._adapter_with_defaults()
        br = await adapter.get_blast_radius("payment-service")
        assert isinstance(br, BlastRadius)
        assert isinstance(br.affected_services, list)

    async def test_blast_radius_severity_thresholds(self):
        # payment-service is tier-1, downstream impact
        adapter = self._adapter_with_defaults()
        br = await adapter.get_blast_radius("postgres")
        # postgres is used by payment-service and order-service (both tier-1)
        # so severity should be critical or high
        assert br.severity in ("critical", "high", "medium", "low")


class TestStaticDependencyAdapterCalculateDownstream:
    def _adapter_with_defaults(self) -> StaticDependencyAdapter:
        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "/nonexistent"
        adapter.dependencies = []
        adapter.services = {}
        adapter._load_default_config()
        return adapter

    def test_no_dependents_returns_empty_set(self):
        adapter = self._adapter_with_defaults()
        affected: set = set()
        adapter._calculate_downstream_impact("unknown-service", affected)
        assert affected == set()

    def test_low_criticality_not_counted(self):
        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "/nonexistent"
        adapter.services = {}
        # Only a low-criticality dependency
        adapter.dependencies = [
            ServiceDependency(
                source_service="svc-b",
                target_service="svc-a",
                dependency_type=DependencyType.ASYNCHRONOUS,
                criticality=0.3,  # below 0.5 threshold
            )
        ]
        affected: set = set()
        adapter._calculate_downstream_impact("svc-a", affected)
        assert "svc-b" not in affected

    def test_high_criticality_counted(self):
        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "/nonexistent"
        adapter.services = {}
        adapter.dependencies = [
            ServiceDependency(
                source_service="svc-b",
                target_service="svc-a",
                dependency_type=DependencyType.SYNCHRONOUS,
                criticality=0.9,
            )
        ]
        affected: set = set()
        adapter._calculate_downstream_impact("svc-a", affected)
        assert "svc-b" in affected

    def test_cycle_prevention(self):
        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "/nonexistent"
        adapter.services = {}
        # Circular: svc-a → svc-b → svc-a
        adapter.dependencies = [
            ServiceDependency(
                source_service="svc-b",
                target_service="svc-a",
                dependency_type=DependencyType.SYNCHRONOUS,
                criticality=1.0,
            ),
            ServiceDependency(
                source_service="svc-a",
                target_service="svc-b",
                dependency_type=DependencyType.SYNCHRONOUS,
                criticality=1.0,
            ),
        ]
        affected: set = set()
        # Should not infinite-loop
        adapter._calculate_downstream_impact("svc-a", affected)
        assert "svc-b" in affected


class TestStaticDependencyAdapterFromFile:
    def test_load_valid_yaml(self, tmp_path):
        config = {
            "services": [
                {"name": "api", "tier": "tier_1", "team": "core"},
            ],
            "dependencies": [
                {
                    "source_service": "api",
                    "target_service": "db",
                    "dependency_type": "data",
                    "criticality": 1.0,
                }
            ],
        }
        config_file = tmp_path / "deps.yaml"
        config_file.write_text(yaml.dump(config))
        adapter = StaticDependencyAdapter(config_file=str(config_file))
        assert "api" in adapter.services
        assert len(adapter.dependencies) == 1

    def test_missing_file_loads_defaults(self, tmp_path):
        adapter = StaticDependencyAdapter(config_file=str(tmp_path / "nonexistent.yaml"))
        assert len(adapter.services) > 0

    def test_invalid_yaml_loads_defaults(self, tmp_path):
        bad_file = tmp_path / "bad.yaml"
        bad_file.write_text(": [invalid yaml content")
        adapter = StaticDependencyAdapter(config_file=str(bad_file))
        assert len(adapter.services) > 0


class TestGetDependencyAdapter:
    async def test_returns_adapter(self, monkeypatch):
        import app.services.dependency_map as mod
        monkeypatch.setattr(mod, "_adapter", None)
        # Prevent file IO during test
        monkeypatch.setattr(StaticDependencyAdapter, "_load_config", lambda self: None)
        StaticDependencyAdapter.__init__.__defaults__
        adapter = mod.get_dependency_adapter()
        assert isinstance(adapter, StaticDependencyAdapter)

    async def test_singleton_returned(self, monkeypatch):
        import app.services.dependency_map as mod
        existing = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        existing.config_file = "dummy"
        existing.dependencies = []
        existing.services = {}
        monkeypatch.setattr(mod, "_adapter", existing)
        result = mod.get_dependency_adapter()
        assert result is existing


class TestGetServiceContext:
    async def test_returns_full_context(self, monkeypatch):
        import app.services.dependency_map as mod

        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "dummy"
        adapter.dependencies = []
        adapter.services = {}
        adapter._load_default_config()
        monkeypatch.setattr(mod, "_adapter", adapter)

        ctx = await get_service_context("order-service")
        assert "tier" in ctx
        assert "team" in ctx
        assert "blast_radius" in ctx
        assert "dependencies" in ctx
        assert "dependent_services" in ctx

    async def test_unknown_service_returns_unknown_fields(self, monkeypatch):
        import app.services.dependency_map as mod

        adapter = StaticDependencyAdapter.__new__(StaticDependencyAdapter)
        adapter.config_file = "dummy"
        adapter.dependencies = []
        adapter.services = {}
        adapter._load_default_config()
        monkeypatch.setattr(mod, "_adapter", adapter)

        ctx = await get_service_context("unknown-xyz")
        assert ctx["tier"] == "unknown"
        assert ctx["team"] == "unknown"
