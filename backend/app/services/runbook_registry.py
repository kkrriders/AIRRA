"""
Runbook registry for constraining remediation actions.

Senior Engineering Note:
- Actions must be constrained via runbooks
- LLM can read runbooks but NEVER invent actions
- Runbooks define: symptom → allowed actions → approval required
- This prevents the system from taking unauthorized actions
"""
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from app.models.action import ActionType, RiskLevel

logger = logging.getLogger(__name__)


@dataclass
class RunbookAction:
    """Single action defined in a runbook."""

    action_type: ActionType
    description: str
    approval_required: bool
    risk_level: RiskLevel
    parameters_template: dict  # Template for action parameters
    prerequisites: list[str] = None  # Conditions that must be met
    max_auto_executions_per_day: Optional[int] = None  # Rate limiting

    def __post_init__(self):
        if self.prerequisites is None:
            self.prerequisites = []


@dataclass
class Runbook:
    """Runbook defining allowed actions for a symptom."""

    id: str
    name: str
    symptom: str  # What problem this runbook addresses
    category: str  # memory_leak, cpu_spike, etc.
    service: Optional[str] = None  # Specific service (None = any service)
    allowed_actions: list[RunbookAction] = None  # Actions that can be taken
    diagnostic_queries: dict[str, str] = None  # Prometheus queries for diagnostics
    escalation_criteria: list[str] = None  # When to escalate to human

    def __post_init__(self):
        if self.allowed_actions is None:
            self.allowed_actions = []
        if self.diagnostic_queries is None:
            self.diagnostic_queries = {}
        if self.escalation_criteria is None:
            self.escalation_criteria = []


class RunbookRegistry:
    """
    Registry of runbooks that constrain allowed actions.

    This is MANDATORY to prevent free-form action generation.
    LLM = reasoning assistant, NOT action inventor.
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize runbook registry.

        Args:
            config_path: Path to runbooks config file (YAML/JSON)
                        Defaults to config/runbooks.yaml
        """
        if config_path is None:
            config_path = self._find_default_config()

        self.config_path = config_path
        self.runbooks: dict[str, Runbook] = {}
        self._load_runbooks()

    def _find_default_config(self) -> str:
        """Find default runbooks config file."""
        possible_paths = [
            "config/runbooks.yaml",
            "config/runbooks.json",
            "/etc/airra/runbooks.yaml",
            os.getenv("AIRRA_RUNBOOKS_CONFIG", ""),
        ]

        for path in possible_paths:
            if path and os.path.exists(path):
                return path

        return "config/runbooks.yaml"

    def _load_runbooks(self):
        """Load runbooks from config file."""
        if not os.path.exists(self.config_path):
            logger.warning(
                f"Runbooks config not found at {self.config_path}. "
                "Creating example runbooks. "
                "Customize this file to define your organization's approved actions."
            )
            self._create_example_runbooks()
            return

        try:
            with open(self.config_path, 'r') as f:
                if self.config_path.endswith('.json'):
                    config = json.load(f)
                else:
                    config = yaml.safe_load(f)

            # Parse runbooks
            for runbook_config in config.get('runbooks', []):
                runbook = self._parse_runbook(runbook_config)
                self.runbooks[runbook.id] = runbook

            logger.info(f"Loaded {len(self.runbooks)} runbooks from {self.config_path}")

        except Exception as e:
            logger.error(f"Failed to load runbooks: {str(e)}")
            self.runbooks = {}

    def _parse_runbook(self, config: dict) -> Runbook:
        """Parse runbook from configuration."""
        # Parse actions
        actions = []
        for action_config in config.get('allowed_actions', []):
            action = RunbookAction(
                action_type=ActionType(action_config['action_type']),
                description=action_config['description'],
                approval_required=action_config.get('approval_required', True),
                risk_level=RiskLevel(action_config.get('risk_level', 'medium')),
                parameters_template=action_config.get('parameters', {}),
                prerequisites=action_config.get('prerequisites', []),
                max_auto_executions_per_day=action_config.get('max_auto_executions_per_day'),
            )
            actions.append(action)

        return Runbook(
            id=config['id'],
            name=config['name'],
            symptom=config['symptom'],
            category=config['category'],
            service=config.get('service'),
            allowed_actions=actions,
            diagnostic_queries=config.get('diagnostic_queries', {}),
            escalation_criteria=config.get('escalation_criteria', []),
        )

    def _create_example_runbooks(self):
        """Create example runbooks configuration."""
        example_config = {
            "runbooks": [
                {
                    "id": "memory-leak-restart",
                    "name": "Memory Leak - Pod Restart",
                    "symptom": "Memory usage steadily increasing beyond normal bounds",
                    "category": "memory_leak",
                    "service": None,  # Applies to all services
                    "allowed_actions": [
                        {
                            "action_type": "restart_pod",
                            "description": "Restart pod to clear memory leak",
                            "approval_required": True,
                            "risk_level": "medium",
                            "parameters": {
                                "namespace": "production",
                                "graceful_shutdown": True,
                            },
                            "prerequisites": [
                                "Multiple replicas available",
                                "Memory usage > 80%",
                            ],
                            "max_auto_executions_per_day": 5,
                        }
                    ],
                    "diagnostic_queries": {
                        "memory_usage": 'container_memory_usage_bytes{pod=~"{{service}}.*"}',
                        "memory_limit": 'container_spec_memory_limit_bytes{pod=~"{{service}}.*"}',
                    },
                    "escalation_criteria": [
                        "Memory leak persists after restart",
                        "Multiple restarts within 1 hour",
                        "Affects tier-1 service",
                    ],
                },
                {
                    "id": "cpu-spike-scale-up",
                    "name": "CPU Spike - Scale Up",
                    "symptom": "CPU usage sustained above threshold",
                    "category": "cpu_spike",
                    "allowed_actions": [
                        {
                            "action_type": "scale_up",
                            "description": "Scale up replicas to handle CPU load",
                            "approval_required": False,
                            "risk_level": "low",
                            "parameters": {
                                "namespace": "production",
                                "min_replicas": 1,
                                "max_replicas": 10,
                            },
                            "prerequisites": [
                                "Current replicas < max_replicas",
                                "CPU usage > 70%",
                            ],
                            "max_auto_executions_per_day": 10,
                        }
                    ],
                    "diagnostic_queries": {
                        "cpu_usage": 'rate(container_cpu_usage_seconds_total{pod=~"{{service}}.*"}[5m]) * 100',
                    },
                    "escalation_criteria": [
                        "CPU remains high after scaling",
                        "Already at max replicas",
                    ],
                },
                {
                    "id": "error-spike-rollback",
                    "name": "Error Spike - Rollback Deployment",
                    "symptom": "Error rate spike after recent deployment",
                    "category": "error_spike",
                    "allowed_actions": [
                        {
                            "action_type": "rollback_deployment",
                            "description": "Rollback to previous deployment",
                            "approval_required": True,
                            "risk_level": "high",
                            "parameters": {
                                "namespace": "production",
                            },
                            "prerequisites": [
                                "Recent deployment within 2 hours",
                                "Error rate > 5%",
                            ],
                            "max_auto_executions_per_day": 3,
                        }
                    ],
                    "diagnostic_queries": {
                        "error_rate": 'rate(http_requests_total{service="{{service}}",status=~"5.."}[5m])',
                        "total_requests": 'rate(http_requests_total{service="{{service}}"}[5m])',
                    },
                    "escalation_criteria": [
                        "Errors persist after rollback",
                        "Affects payment processing",
                    ],
                },
                {
                    "id": "database-connection-pool-exhaustion",
                    "name": "Database Connection Pool Exhaustion",
                    "symptom": "Database connection pool exhausted",
                    "category": "database_issue",
                    "allowed_actions": [
                        {
                            "action_type": "restart_pod",
                            "description": "Restart pods to reset connection pools",
                            "approval_required": True,
                            "risk_level": "high",
                            "parameters": {
                                "namespace": "production",
                                "graceful_shutdown": True,
                            },
                            "prerequisites": [
                                "Multiple replicas available",
                                "Active DB connections > 90% of pool size",
                            ],
                        }
                    ],
                    "diagnostic_queries": {
                        "active_connections": 'db_connections_active{service="{{service}}"}',
                        "max_connections": 'db_connections_max{service="{{service}}"}',
                    },
                    "escalation_criteria": [
                        "Issue persists after restart",
                        "Database itself is unhealthy",
                    ],
                },
            ]
        }

        try:
            os.makedirs("config", exist_ok=True)
            with open(self.config_path, 'w') as f:
                yaml.dump(example_config, f, default_flow_style=False, sort_keys=False)
            logger.info(f"Created example runbooks at {self.config_path}")

        except Exception as e:
            logger.error(f"Failed to create example runbooks: {str(e)}")

    def get_runbook_for_category(
        self,
        category: str,
        service: Optional[str] = None,
    ) -> Optional[Runbook]:
        """
        Get runbook for a specific category and service.

        Args:
            category: Problem category (memory_leak, cpu_spike, etc.)
            service: Service name (optional)

        Returns:
            Matching runbook or None
        """
        # Try exact match first (category + service)
        if service:
            for runbook in self.runbooks.values():
                if runbook.category == category and runbook.service == service:
                    return runbook

        # Try category match with any service
        for runbook in self.runbooks.values():
            if runbook.category == category and runbook.service is None:
                return runbook

        logger.warning(f"No runbook found for category '{category}' and service '{service}'")
        return None

    def get_allowed_actions(
        self,
        category: str,
        service: Optional[str] = None,
    ) -> list[RunbookAction]:
        """
        Get allowed actions for a category/service.

        Args:
            category: Problem category
            service: Service name (optional)

        Returns:
            List of allowed actions
        """
        runbook = self.get_runbook_for_category(category, service)
        return runbook.allowed_actions if runbook else []

    def is_action_allowed(
        self,
        action_type: ActionType,
        category: str,
        service: Optional[str] = None,
    ) -> bool:
        """
        Check if an action is allowed for a category/service.

        Args:
            action_type: Type of action
            category: Problem category
            service: Service name

        Returns:
            True if action is allowed
        """
        allowed_actions = self.get_allowed_actions(category, service)
        return any(a.action_type == action_type for a in allowed_actions)

    def get_all_runbooks(self) -> list[Runbook]:
        """Get all loaded runbooks."""
        return list(self.runbooks.values())


# Global instance
_runbook_registry: Optional[RunbookRegistry] = None


def get_runbook_registry() -> RunbookRegistry:
    """Get global runbook registry instance."""
    global _runbook_registry
    if _runbook_registry is None:
        _runbook_registry = RunbookRegistry()
    return _runbook_registry
