"""
Service Dependency Map and Topology Analysis.

Provides topology-aware reasoning for blast radius calculation
and dependency-based hypothesis ranking.

Senior Engineering Note:
- Pluggable adapters for different CMDBs
- Static YAML/JSON configuration for MVP
- ServiceNow CMDB integration for enterprises
- Cloud-native discovery adapters
"""
import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ServiceTier(str, Enum):
    """Service tier classification."""

    TIER_1 = "tier_1"  # Critical user-facing services
    TIER_2 = "tier_2"  # Important backend services
    TIER_3 = "tier_3"  # Supporting services
    TIER_4 = "tier_4"  # Non-critical services


class DependencyType(str, Enum):
    """Type of dependency relationship."""

    SYNCHRONOUS = "synchronous"  # Direct API calls
    ASYNCHRONOUS = "asynchronous"  # Message queues, events
    DATA = "data"  # Shared database, cache
    INFRASTRUCTURE = "infrastructure"  # Network, DNS, load balancer


class ServiceDependency(BaseModel):
    """A dependency relationship between services."""

    source_service: str = Field(..., description="Service that depends on target")
    target_service: str = Field(..., description="Service being depended on")
    dependency_type: DependencyType
    criticality: float = Field(..., ge=0.0, le=1.0, description="How critical is this dependency")


class ServiceMetadata(BaseModel):
    """Metadata about a service."""

    name: str
    tier: ServiceTier
    team: str
    repository: Optional[str] = None
    on_call: Optional[str] = None
    runbook_url: Optional[str] = None


class BlastRadius(BaseModel):
    """Calculated blast radius for a service failure."""

    affected_services: list[str] = Field(default_factory=list)
    affected_count: int = 0
    severity: str = "low"  # low, medium, high, critical
    impact_description: str = ""


class CMDBAdapter(ABC):
    """Abstract adapter for Configuration Management Database."""

    @abstractmethod
    async def get_service_dependencies(self, service_id: str) -> list[ServiceDependency]:
        """Get all dependencies for a service (upstream and downstream)."""
        pass

    @abstractmethod
    async def get_service_metadata(self, service_id: str) -> Optional[ServiceMetadata]:
        """Get metadata about a service."""
        pass

    @abstractmethod
    async def get_blast_radius(self, service_id: str) -> BlastRadius:
        """Calculate blast radius if this service fails."""
        pass


class StaticDependencyAdapter(CMDBAdapter):
    """
    Static dependency map loaded from YAML/JSON file.

    For MVP and smaller deployments. Version-controlled alongside code.
    """

    def __init__(self, config_file: str = "/app/config/service_dependencies.yaml"):
        self.config_file = config_file
        self.dependencies: list[ServiceDependency] = []
        self.services: dict[str, ServiceMetadata] = {}
        self._load_config()

    def _load_config(self):
        """Load dependency configuration from file."""
        try:
            with open(self.config_file, "r") as f:
                config = yaml.safe_load(f)

            # Load service metadata
            for svc_config in config.get("services", []):
                service = ServiceMetadata(**svc_config)
                self.services[service.name] = service

            # Load dependencies
            for dep_config in config.get("dependencies", []):
                dependency = ServiceDependency(**dep_config)
                self.dependencies.append(dependency)

            logger.info(
                f"Loaded {len(self.services)} services and "
                f"{len(self.dependencies)} dependencies from {self.config_file}"
            )

        except FileNotFoundError:
            logger.warning(f"Dependency config file not found: {self.config_file}")
            self._load_default_config()
        except Exception as e:
            logger.error(f"Failed to load dependency config: {str(e)}")
            self._load_default_config()

    def _load_default_config(self):
        """Load default configuration for demo purposes."""
        logger.info("Loading default dependency configuration")

        # Default services
        self.services = {
            "payment-service": ServiceMetadata(
                name="payment-service",
                tier=ServiceTier.TIER_1,
                team="payments",
                on_call="payments-oncall@company.com",
            ),
            "order-service": ServiceMetadata(
                name="order-service",
                tier=ServiceTier.TIER_1,
                team="orders",
                on_call="orders-oncall@company.com",
            ),
            "user-service": ServiceMetadata(
                name="user-service",
                tier=ServiceTier.TIER_1,
                team="identity",
                on_call="identity-oncall@company.com",
            ),
            "inventory-service": ServiceMetadata(
                name="inventory-service",
                tier=ServiceTier.TIER_2,
                team="inventory",
            ),
            "notification-service": ServiceMetadata(
                name="notification-service",
                tier=ServiceTier.TIER_3,
                team="platform",
            ),
            "postgres": ServiceMetadata(
                name="postgres",
                tier=ServiceTier.TIER_1,
                team="infrastructure",
            ),
            "redis": ServiceMetadata(
                name="redis",
                tier=ServiceTier.TIER_2,
                team="infrastructure",
            ),
        }

        # Default dependencies
        self.dependencies = [
            ServiceDependency(
                source_service="order-service",
                target_service="payment-service",
                dependency_type=DependencyType.SYNCHRONOUS,
                criticality=1.0,
            ),
            ServiceDependency(
                source_service="order-service",
                target_service="inventory-service",
                dependency_type=DependencyType.SYNCHRONOUS,
                criticality=0.9,
            ),
            ServiceDependency(
                source_service="order-service",
                target_service="user-service",
                dependency_type=DependencyType.SYNCHRONOUS,
                criticality=0.8,
            ),
            ServiceDependency(
                source_service="payment-service",
                target_service="postgres",
                dependency_type=DependencyType.DATA,
                criticality=1.0,
            ),
            ServiceDependency(
                source_service="order-service",
                target_service="postgres",
                dependency_type=DependencyType.DATA,
                criticality=1.0,
            ),
            ServiceDependency(
                source_service="user-service",
                target_service="redis",
                dependency_type=DependencyType.DATA,
                criticality=0.7,
            ),
            ServiceDependency(
                source_service="order-service",
                target_service="notification-service",
                dependency_type=DependencyType.ASYNCHRONOUS,
                criticality=0.3,
            ),
        ]

    async def get_service_dependencies(self, service_id: str) -> list[ServiceDependency]:
        """Get all dependencies for a service."""
        # Get both upstream (services we depend on) and downstream (services that depend on us)
        upstream = [d for d in self.dependencies if d.source_service == service_id]
        downstream = [d for d in self.dependencies if d.target_service == service_id]
        return upstream + downstream

    async def get_service_metadata(self, service_id: str) -> Optional[ServiceMetadata]:
        """Get metadata about a service."""
        return self.services.get(service_id)

    async def get_blast_radius(self, service_id: str) -> BlastRadius:
        """Calculate blast radius if this service fails."""
        affected = set()
        self._calculate_downstream_impact(service_id, affected)

        # Determine severity based on affected count and tiers
        affected_count = len(affected)
        tier_1_affected = sum(
            1
            for svc in affected
            if self.services.get(svc, ServiceMetadata(name=svc, tier=ServiceTier.TIER_4, team="unknown")).tier
            == ServiceTier.TIER_1
        )

        if tier_1_affected > 0 or affected_count >= 5:
            severity = "critical"
        elif affected_count >= 3:
            severity = "high"
        elif affected_count >= 1:
            severity = "medium"
        else:
            severity = "low"

        impact_description = (
            f"{affected_count} service(s) affected"
            + (f", including {tier_1_affected} Tier-1 service(s)" if tier_1_affected > 0 else "")
        )

        return BlastRadius(
            affected_services=sorted(affected),
            affected_count=affected_count,
            severity=severity,
            impact_description=impact_description,
        )

    def _calculate_downstream_impact(
        self, service_id: str, affected: set, visited: Optional[set] = None
    ):
        """Recursively calculate downstream impact."""
        if visited is None:
            visited = set()

        if service_id in visited:
            return

        visited.add(service_id)

        # Find services that depend on this service
        dependent_services = [d for d in self.dependencies if d.target_service == service_id]

        for dep in dependent_services:
            # Only count critical dependencies (criticality > 0.5)
            if dep.criticality > 0.5:
                affected.add(dep.source_service)
                # Recursively check dependencies
                self._calculate_downstream_impact(dep.source_service, affected, visited)


# Global adapter instance
_adapter: Optional[CMDBAdapter] = None


def get_dependency_adapter() -> CMDBAdapter:
    """Get the global dependency adapter instance."""
    global _adapter
    if _adapter is None:
        # For now, always use static adapter
        # In production, this would be configurable (static, servicenow, cloud)
        _adapter = StaticDependencyAdapter()
    return _adapter


async def get_service_context(service_id: str) -> dict:
    """
    Get enriched service context for hypothesis generation.

    Returns a dict with dependencies, blast radius, and metadata.
    """
    adapter = get_dependency_adapter()

    metadata = await adapter.get_service_metadata(service_id)
    dependencies = await adapter.get_service_dependencies(service_id)
    blast_radius = await adapter.get_blast_radius(service_id)

    # Extract dependency names
    upstream_deps = [d.target_service for d in dependencies if d.source_service == service_id]
    downstream_deps = [d.source_service for d in dependencies if d.target_service == service_id]

    return {
        "tier": metadata.tier.value if metadata else "unknown",
        "team": metadata.team if metadata else "unknown",
        "on_call": metadata.on_call if metadata else None,
        "dependencies": upstream_deps,
        "dependent_services": downstream_deps,
        "blast_radius": blast_radius.severity,
        "blast_radius_services": blast_radius.affected_services,
        "blast_radius_description": blast_radius.impact_description,
    }
