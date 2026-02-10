
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)


@dataclass
class ServiceDependency:
    """Service dependency information."""

    service: str
    depends_on: list[str]  # Upstream dependencies
    depended_by: list[str]  # Downstream dependents
    tier: Optional[str] = None  # Service tier (tier-1, tier-2, etc.)
    team: Optional[str] = None  # Owning team
    criticality: str = "medium"  # low, medium, high, critical


class DependencyGraph:
    """Service dependency graph for topology-aware root cause analysis.

    Loads service dependency relationships from a YAML/JSON config file and
    provides methods for upstream/downstream resolution, cycle-safe traversal,
    criticality scoring, and confidence boosting based on topology.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize dependency graph.

        Args:
            config_path: Path to dependency config file (YAML/JSON)
                        Defaults to config/service_dependencies.yaml
        """
        if config_path is None:
            config_path = self._find_default_config()

        self.config_path = config_path
        self.dependencies: dict[str, ServiceDependency] = {}
        self._load_dependencies()

    def _find_default_config(self) -> str:
        """Find default config file."""
        possible_paths = [
            "config/service_dependencies.yaml",
            "config/service_dependencies.json",
            "/etc/airra/service_dependencies.yaml",
            os.getenv("AIRRA_DEPENDENCY_CONFIG", ""),
        ]

        for path in possible_paths:
            if path and os.path.exists(path):
                return path

        # Return default path (will be created if needed)
        return "config/service_dependencies.yaml"

    def _load_dependencies(self):
        """Load dependencies from config file."""
        if not os.path.exists(self.config_path):
            logger.warning(
                f"Dependency config not found at {self.config_path}. "
                "Using empty dependency graph. "
                "Create config file to enable dependency-aware RCA."
            )
            self._create_example_config()
            return

        try:
            with open(self.config_path, 'r') as f:
                if self.config_path.endswith('.json'):
                    config = json.load(f)
                else:
                    config = yaml.safe_load(f)

            # Parse dependencies
            services_config = config.get('services', {})

            # First pass: create all services
            for service_name, service_config in services_config.items():
                self.dependencies[service_name] = ServiceDependency(
                    service=service_name,
                    depends_on=service_config.get('depends_on', []),
                    depended_by=[],  # Will fill in second pass
                    tier=service_config.get('tier'),
                    team=service_config.get('team'),
                    criticality=service_config.get('criticality', 'medium'),
                )

            # Second pass: populate depended_by (reverse dependencies)
            for service_name, service_dep in self.dependencies.items():
                for upstream in service_dep.depends_on:
                    if upstream in self.dependencies:
                        self.dependencies[upstream].depended_by.append(service_name)

            logger.info(
                f"Loaded {len(self.dependencies)} services from dependency graph "
                f"({self.config_path})"
            )

        except Exception as e:
            logger.error(f"Failed to load dependency graph: {str(e)}")
            self.dependencies = {}

    def _create_example_config(self):
        """Create example configuration file."""
        example_config = {
            "services": {
                "frontend": {
                    "depends_on": ["api-gateway"],
                    "tier": "tier-1",
                    "team": "frontend",
                    "criticality": "high"
                },
                "api-gateway": {
                    "depends_on": ["auth-service", "payment-service", "order-service"],
                    "tier": "tier-1",
                    "team": "platform",
                    "criticality": "critical"
                },
                "payment-service": {
                    "depends_on": ["database", "redis", "payment-gateway"],
                    "tier": "tier-1",
                    "team": "payments",
                    "criticality": "critical"
                },
                "order-service": {
                    "depends_on": ["database", "redis", "payment-service"],
                    "tier": "tier-2",
                    "team": "orders",
                    "criticality": "high"
                },
                "auth-service": {
                    "depends_on": ["database", "redis"],
                    "tier": "tier-1",
                    "team": "platform",
                    "criticality": "critical"
                },
                "database": {
                    "depends_on": [],
                    "tier": "tier-0",
                    "team": "infrastructure",
                    "criticality": "critical"
                },
                "redis": {
                    "depends_on": [],
                    "tier": "tier-0",
                    "team": "infrastructure",
                    "criticality": "high"
                },
            }
        }

        try:
            # Create config directory if it doesn't exist
            os.makedirs("config", exist_ok=True)

            with open(self.config_path, 'w') as f:
                yaml.dump(example_config, f, default_flow_style=False, sort_keys=False)

            logger.info(f"Created example dependency config at {self.config_path}")

        except Exception as e:
            logger.error(f"Failed to create example config: {str(e)}")

    def get_upstream_dependencies(self, service: str) -> list[str]:
        """
        Get upstream dependencies (services this service depends on).

        Args:
            service: Service name

        Returns:
            List of upstream service names
        """
        if service not in self.dependencies:
            return []
        return self.dependencies[service].depends_on

    def get_downstream_dependents(self, service: str) -> list[str]:
        """
        Get downstream dependents (services that depend on this service).

        Args:
            service: Service name

        Returns:
            List of downstream service names
        """
        if service not in self.dependencies:
            return []
        return self.dependencies[service].depended_by

    def is_upstream_of(
        self,
        potential_upstream: str,
        service: str,
        _visited: set[str] | None = None,
    ) -> bool:
        """
        Check if one service is upstream of another.

        Args:
            potential_upstream: Service that might be upstream
            service: Service to check
            _visited: Internal set to detect cycles (do not pass manually)

        Returns:
            True if potential_upstream is in the dependency chain of service
        """
        if service not in self.dependencies:
            return False

        # Cycle detection: track visited nodes
        if _visited is None:
            _visited = set()
        if service in _visited:
            return False
        _visited.add(service)

        # Direct dependency
        if potential_upstream in self.dependencies[service].depends_on:
            return True

        # Transitive dependency (recursive check with visited set)
        for upstream in self.dependencies[service].depends_on:
            if self.is_upstream_of(potential_upstream, upstream, _visited):
                return True

        return False

    def calculate_dependency_boost(
        self,
        affected_service: str,
        hypothesis_service: str,
    ) -> float:
        """
        Calculate confidence boost for hypothesis based on service dependencies.

        If hypothesis_service is upstream of affected_service and also failing,
        boost confidence (likely root cause is upstream).

        Args:
            affected_service: Service currently experiencing issues
            hypothesis_service: Service hypothesized to be the root cause

        Returns:
            Confidence boost (0.0 to 0.2)
        """
        # If hypothesis is about the same service, no boost
        if affected_service == hypothesis_service:
            return 0.0

        # If hypothesis service is upstream, boost confidence
        if self.is_upstream_of(hypothesis_service, affected_service):
            # Stronger boost for direct dependencies
            if hypothesis_service in self.get_upstream_dependencies(affected_service):
                return 0.15  # Direct dependency: +15% confidence

            # Weaker boost for transitive dependencies
            return 0.08  # Transitive dependency: +8% confidence

        # If hypothesis service is downstream, penalize slightly
        # (unlikely that downstream issues cause upstream failures)
        if self.is_upstream_of(affected_service, hypothesis_service):
            return -0.05  # -5% confidence

        # Unrelated services, no adjustment
        return 0.0

    def get_criticality_score(self, service: str) -> float:
        """
        Get criticality score for a service (0.0 to 1.0).

        Args:
            service: Service name

        Returns:
            Criticality score
        """
        if service not in self.dependencies:
            return 0.5  # Default medium

        criticality_map = {
            "low": 0.3,
            "medium": 0.5,
            "high": 0.7,
            "critical": 0.9,
        }

        criticality = self.dependencies[service].criticality
        return criticality_map.get(criticality, 0.5)

    def get_service_info(self, service: str) -> Optional[ServiceDependency]:
        """Get complete service dependency information."""
        return self.dependencies.get(service)

    def get_all_services(self) -> list[str]:
        """Get list of all known services."""
        return list(self.dependencies.keys())


# Global instance (can be overridden for testing)
_dependency_graph: Optional[DependencyGraph] = None


def get_dependency_graph() -> DependencyGraph:
    """Get global dependency graph instance."""
    global _dependency_graph
    if _dependency_graph is None:
        _dependency_graph = DependencyGraph()
    return _dependency_graph
