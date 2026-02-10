"""
Incident Scenario Definitions for Demo Simulations.

Provides pre-packaged realistic incident scenarios with metrics and context.
Each scenario includes:
- Metric patterns for injection into mock service
- Expected incident characteristics
- Context data (deployments, dependencies, etc.)
- Tags and difficulty levels for organization
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional


class MetricPatternType(str, Enum):
    """Type of metric pattern over time."""
    CONSTANT = "constant"  # Fixed value
    LINEAR = "linear"  # Gradual increase/decrease
    SPIKE = "spike"  # Sudden increase then recovery
    OSCILLATING = "oscillating"  # Periodic fluctuation
    STEP = "step"  # Sudden permanent change


class ScenarioDifficulty(str, Enum):
    """Difficulty level for tutorial/demo progression."""
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class ScenarioTag(str, Enum):
    """Tags for filtering and categorization."""
    RESOURCE = "resource"  # Resource exhaustion (memory, CPU, disk)
    PERFORMANCE = "performance"  # Latency, throughput issues
    AVAILABILITY = "availability"  # Crashes, restarts
    EXTERNAL = "external"  # External dependency issues
    CONFIGURATION = "configuration"  # Config or deployment issues


@dataclass
class MetricPattern:
    """Definition of how a metric should behave during simulation."""

    metric_name: str
    # Current/target value for the metric
    value: float
    # Expected baseline value (for comparison)
    baseline: float
    # Standard deviation factor (how many sigma from baseline)
    deviation_sigma: float
    # Pattern type for time-series behavior
    pattern_type: MetricPatternType = MetricPatternType.CONSTANT
    # Unit for display
    unit: str = ""

    @property
    def is_anomalous(self) -> bool:
        """Check if this metric represents an anomaly (>3 sigma)."""
        return abs(self.deviation_sigma) >= 3.0


@dataclass
class ScenarioPhase:
    """
    Multi-phase scenarios with progression over time.

    For future enhancement: scenarios that evolve (e.g., memory leak that
    starts gradual then becomes critical).
    """

    name: str
    duration_seconds: int
    metrics: List[MetricPattern]
    description: str = ""


@dataclass
class IncidentScenario:
    """
    Complete definition of a realistic incident scenario.

    Used by the simulator to:
    1. Inject metrics into mock service
    2. Create incident with proper context
    3. Validate LLM analysis against expected outcomes
    """

    # Unique identifier
    scenario_id: str

    # Display information
    name: str
    description: str

    # Service being simulated
    service_name: str

    # Metrics to inject
    metrics: List[MetricPattern]

    # Expected incident characteristics (for validation)
    expected_severity: str = "medium"
    expected_root_cause: str = ""
    expected_action_types: List[str] = field(default_factory=list)

    # Additional context to enrich the incident
    context: Dict = field(default_factory=dict)

    # Organization and filtering
    tags: List[ScenarioTag] = field(default_factory=list)
    difficulty: ScenarioDifficulty = ScenarioDifficulty.BEGINNER

    # Duration for auto-stop (in seconds)
    duration_seconds: int = 300

    # Multi-phase support (optional)
    phases: List[ScenarioPhase] = field(default_factory=list)

    def to_metrics_snapshot(self) -> Dict:
        """
        Convert scenario metrics to format expected by quick_incident API.

        Returns:
            Dict suitable for QuickIncidentRequest.metrics_snapshot
        """
        snapshot = {}
        for metric in self.metrics:
            snapshot[metric.metric_name] = {
                "current": metric.value,
                "expected": metric.baseline,
                "deviation": metric.deviation_sigma,
            }
        return snapshot


# ============================================
# Pre-defined Realistic Incident Scenarios
# ============================================

SCENARIO_MEMORY_LEAK = IncidentScenario(
    scenario_id="memory_leak_gradual",
    name="Gradual Memory Leak",
    description=(
        "A memory leak in the payment service gradually exhausts memory over time, "
        "eventually triggering OOM kills. Typical cause: unbounded cache, missing "
        "cleanup in long-lived connections, or accumulating event listeners."
    ),
    service_name="payment-service",
    metrics=[
        MetricPattern(
            metric_name="memory_usage_bytes",
            value=8589934592,  # 8 GB
            baseline=2147483648,  # 2 GB
            deviation_sigma=5.2,
            pattern_type=MetricPatternType.LINEAR,
            unit="bytes",
        ),
        MetricPattern(
            metric_name="memory_usage_percent",
            value=95.0,
            baseline=25.0,
            deviation_sigma=5.0,
            pattern_type=MetricPatternType.LINEAR,
            unit="%",
        ),
        MetricPattern(
            metric_name="heap_allocations_total",
            value=15000000,
            baseline=2000000,
            deviation_sigma=4.8,
            pattern_type=MetricPatternType.LINEAR,
            unit="count",
        ),
        MetricPattern(
            metric_name="garbage_collections_total",
            value=5000,
            baseline=500,
            deviation_sigma=4.5,
            pattern_type=MetricPatternType.LINEAR,
            unit="count",
        ),
    ],
    expected_severity="critical",
    expected_root_cause="memory_leak",
    expected_action_types=["restart", "scale"],
    context={
        "recent_deployments": [
            {
                "version": "v2.3.1",
                "deployed_at": (datetime.utcnow() - timedelta(hours=6)).isoformat(),
                "changes": ["Added Redis connection pooling", "Refactored payment processing"],
            }
        ],
        "environment": "production",
        "pod_count": 3,
    },
    tags=[ScenarioTag.RESOURCE, ScenarioTag.AVAILABILITY],
    difficulty=ScenarioDifficulty.BEGINNER,
    duration_seconds=300,
)

SCENARIO_CPU_SPIKE = IncidentScenario(
    scenario_id="cpu_spike_traffic_surge",
    name="CPU Spike from Traffic Surge",
    description=(
        "Sudden traffic surge (e.g., flash sale) causes CPU to max out, "
        "leading to request queueing and timeouts. May require horizontal scaling."
    ),
    service_name="payment-service",
    metrics=[
        MetricPattern(
            metric_name="cpu_usage_percent",
            value=98.5,
            baseline=45.0,
            deviation_sigma=6.0,
            pattern_type=MetricPatternType.SPIKE,
            unit="%",
        ),
        MetricPattern(
            metric_name="http_requests_per_second",
            value=3500,
            baseline=800,
            deviation_sigma=5.5,
            pattern_type=MetricPatternType.SPIKE,
            unit="req/s",
        ),
        MetricPattern(
            metric_name="http_request_duration_seconds_p95",
            value=4.2,
            baseline=0.3,
            deviation_sigma=5.0,
            pattern_type=MetricPatternType.SPIKE,
            unit="seconds",
        ),
        MetricPattern(
            metric_name="thread_pool_queue_size",
            value=450,
            baseline=5,
            deviation_sigma=4.8,
            pattern_type=MetricPatternType.SPIKE,
            unit="count",
        ),
    ],
    expected_severity="high",
    expected_root_cause="traffic_surge",
    expected_action_types=["scale", "rate_limit"],
    context={
        "recent_events": ["Marketing campaign launched 15 minutes ago"],
        "environment": "production",
        "pod_count": 3,
        "autoscaling_enabled": False,
    },
    tags=[ScenarioTag.RESOURCE, ScenarioTag.PERFORMANCE],
    difficulty=ScenarioDifficulty.BEGINNER,
    duration_seconds=180,
)

SCENARIO_LATENCY_DATABASE = IncidentScenario(
    scenario_id="latency_spike_database",
    name="High Latency from Slow Database Queries",
    description=(
        "Database queries suddenly slow down due to missing index, lock contention, "
        "or connection pool exhaustion. Affects all downstream services."
    ),
    service_name="payment-service",
    metrics=[
        MetricPattern(
            metric_name="http_request_duration_seconds_p95",
            value=8.5,
            baseline=0.4,
            deviation_sigma=6.5,
            pattern_type=MetricPatternType.STEP,
            unit="seconds",
        ),
        MetricPattern(
            metric_name="http_request_duration_seconds_p99",
            value=12.3,
            baseline=0.8,
            deviation_sigma=6.8,
            pattern_type=MetricPatternType.STEP,
            unit="seconds",
        ),
        MetricPattern(
            metric_name="database_query_duration_seconds",
            value=7.2,
            baseline=0.05,
            deviation_sigma=7.0,
            pattern_type=MetricPatternType.STEP,
            unit="seconds",
        ),
        MetricPattern(
            metric_name="database_connections_active",
            value=98,
            baseline=15,
            deviation_sigma=5.5,
            pattern_type=MetricPatternType.STEP,
            unit="count",
        ),
        MetricPattern(
            metric_name="http_requests_total",
            value=450,
            baseline=800,
            deviation_sigma=-4.2,  # Negative: requests dropping
            pattern_type=MetricPatternType.STEP,
            unit="req/s",
        ),
    ],
    expected_severity="high",
    expected_root_cause="database_performance",
    expected_action_types=["database_optimization", "connection_pool_tuning"],
    context={
        "recent_deployments": [
            {
                "version": "v2.4.0",
                "deployed_at": (datetime.utcnow() - timedelta(hours=2)).isoformat(),
                "changes": ["Added transaction history feature", "New complex JOIN queries"],
            }
        ],
        "database": {
            "type": "PostgreSQL",
            "version": "14.5",
            "connection_pool_size": 100,
        },
        "environment": "production",
    },
    tags=[ScenarioTag.PERFORMANCE, ScenarioTag.EXTERNAL],
    difficulty=ScenarioDifficulty.INTERMEDIATE,
    duration_seconds=240,
)

SCENARIO_POD_CRASH = IncidentScenario(
    scenario_id="pod_crash_loop",
    name="Pod Crash Loop After Bad Deployment",
    description=(
        "Recent deployment introduced a bug causing pods to crash and restart "
        "repeatedly. Application fails to start due to configuration error or "
        "unhandled exception during initialization."
    ),
    service_name="payment-service",
    metrics=[
        MetricPattern(
            metric_name="pod_restarts_total",
            value=45,
            baseline=0,
            deviation_sigma=8.0,
            pattern_type=MetricPatternType.LINEAR,
            unit="count",
        ),
        MetricPattern(
            metric_name="pod_ready_count",
            value=1,
            baseline=3,
            deviation_sigma=-5.5,  # Negative: pods down
            pattern_type=MetricPatternType.STEP,
            unit="count",
        ),
        MetricPattern(
            metric_name="http_requests_total",
            value=50,
            baseline=800,
            deviation_sigma=-6.0,  # Severe traffic drop
            pattern_type=MetricPatternType.STEP,
            unit="req/s",
        ),
        MetricPattern(
            metric_name="http_request_duration_seconds_p95",
            value=15.0,
            baseline=0.3,
            deviation_sigma=5.5,
            pattern_type=MetricPatternType.OSCILLATING,  # Intermittent as pods crash
            unit="seconds",
        ),
    ],
    expected_severity="critical",
    expected_root_cause="deployment_issue",
    expected_action_types=["rollback", "restart"],
    context={
        "recent_deployments": [
            {
                "version": "v2.5.0",
                "deployed_at": (datetime.utcnow() - timedelta(minutes=20)).isoformat(),
                "changes": [
                    "Updated database migration",
                    "Changed environment variable names",
                    "Added new required configuration",
                ],
            }
        ],
        "environment": "production",
        "pod_count": 3,
        "kubernetes": {
            "namespace": "production",
            "deployment": "payment-service",
        },
    },
    tags=[ScenarioTag.AVAILABILITY, ScenarioTag.CONFIGURATION],
    difficulty=ScenarioDifficulty.INTERMEDIATE,
    duration_seconds=300,
)

SCENARIO_DEPENDENCY_FAILURE = IncidentScenario(
    scenario_id="dependency_failure_timeout",
    name="External Service Dependency Failure",
    description=(
        "Upstream payment gateway is timing out, causing cascading failures. "
        "Service needs to implement circuit breaker or fallback behavior."
    ),
    service_name="payment-service",
    metrics=[
        MetricPattern(
            metric_name="http_requests_total",
            value=1500,
            baseline=800,
            deviation_sigma=4.5,
            pattern_type=MetricPatternType.SPIKE,
            unit="req/s",
        ),
        MetricPattern(
            metric_name="http_response_status_500_total",
            value=850,
            baseline=5,
            deviation_sigma=7.5,
            pattern_type=MetricPatternType.SPIKE,
            unit="count",
        ),
        MetricPattern(
            metric_name="external_api_call_duration_seconds",
            value=30.0,  # Timeout threshold
            baseline=0.5,
            deviation_sigma=8.0,
            pattern_type=MetricPatternType.STEP,
            unit="seconds",
        ),
        MetricPattern(
            metric_name="external_api_errors_total",
            value=720,
            baseline=2,
            deviation_sigma=7.8,
            pattern_type=MetricPatternType.SPIKE,
            unit="count",
        ),
        MetricPattern(
            metric_name="circuit_breaker_open",
            value=1,
            baseline=0,
            deviation_sigma=5.0,
            pattern_type=MetricPatternType.STEP,
            unit="boolean",
        ),
    ],
    expected_severity="high",
    expected_root_cause="external_dependency_failure",
    expected_action_types=["circuit_breaker", "fallback", "alert"],
    context={
        "dependencies": {
            "payment_gateway": {
                "name": "Stripe API",
                "endpoint": "https://api.stripe.com",
                "timeout_seconds": 30,
                "circuit_breaker_enabled": True,
            }
        },
        "environment": "production",
        "recent_alerts": [
            "External payment gateway reported degraded performance 10 minutes ago"
        ],
    },
    tags=[ScenarioTag.EXTERNAL, ScenarioTag.AVAILABILITY],
    difficulty=ScenarioDifficulty.ADVANCED,
    duration_seconds=200,
)


# ============================================
# Scenario Registry
# ============================================

SCENARIO_REGISTRY: Dict[str, IncidentScenario] = {
    "memory_leak_gradual": SCENARIO_MEMORY_LEAK,
    "cpu_spike_traffic_surge": SCENARIO_CPU_SPIKE,
    "latency_spike_database": SCENARIO_LATENCY_DATABASE,
    "pod_crash_loop": SCENARIO_POD_CRASH,
    "dependency_failure_timeout": SCENARIO_DEPENDENCY_FAILURE,
}


# ============================================
# Helper Functions
# ============================================

def get_scenario(scenario_id: str) -> Optional[IncidentScenario]:
    """
    Get a scenario by ID.

    Args:
        scenario_id: Unique scenario identifier

    Returns:
        IncidentScenario if found, None otherwise
    """
    return SCENARIO_REGISTRY.get(scenario_id)


def list_scenarios(
    difficulty: Optional[ScenarioDifficulty] = None,
    tags: Optional[List[ScenarioTag]] = None,
) -> List[IncidentScenario]:
    """
    List available scenarios with optional filtering.

    Args:
        difficulty: Filter by difficulty level
        tags: Filter by tags (scenarios must have ALL specified tags)

    Returns:
        List of matching scenarios
    """
    scenarios = list(SCENARIO_REGISTRY.values())

    if difficulty:
        scenarios = [s for s in scenarios if s.difficulty == difficulty]

    if tags:
        scenarios = [
            s for s in scenarios
            if all(tag in s.tags for tag in tags)
        ]

    return scenarios


def get_scenario_summary() -> List[Dict]:
    """
    Get a summary of all scenarios for display.

    Returns:
        List of dicts with key info for each scenario
    """
    summaries = []
    for scenario in SCENARIO_REGISTRY.values():
        summaries.append({
            "id": scenario.scenario_id,
            "name": scenario.name,
            "description": scenario.description,
            "service": scenario.service_name,
            "severity": scenario.expected_severity,
            "difficulty": scenario.difficulty.value,
            "tags": [tag.value for tag in scenario.tags],
            "duration_seconds": scenario.duration_seconds,
            "metric_count": len(scenario.metrics),
        })
    return summaries
