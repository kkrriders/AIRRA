"""
Simulation subsystem for what-if analysis and incident scenarios.

Allows operators to:
1. Compare multiple remediation actions before execution (what-if simulator)
2. Run pre-packaged incident scenarios for demos and testing (incident simulator)
"""
from app.core.simulation.what_if_simulator import (
    SimulatedOutcome,
    SimulationComparison,
    WhatIfSimulator,
    get_what_if_simulator,
)
from app.core.simulation.scenario_definitions import (
    IncidentScenario,
    MetricPattern,
    ScenarioDifficulty,
    ScenarioTag,
    get_scenario,
    list_scenarios,
    get_scenario_summary,
)
from app.core.simulation.scenario_runner import (
    ScenarioRunner,
    SimulationResult,
    get_scenario_runner,
)
from app.core.simulation.metric_injector import (
    MetricInjector,
    get_metric_injector,
)
from app.core.simulation.llm_scenario_generator import (
    LLMScenarioGenerator,
    get_scenario_generator,
    GeneratedScenario,
)

__all__ = [
    # What-if simulator
    "SimulatedOutcome",
    "SimulationComparison",
    "WhatIfSimulator",
    "get_what_if_simulator",
    # Incident simulator
    "IncidentScenario",
    "MetricPattern",
    "ScenarioDifficulty",
    "ScenarioTag",
    "get_scenario",
    "list_scenarios",
    "get_scenario_summary",
    "ScenarioRunner",
    "SimulationResult",
    "get_scenario_runner",
    "MetricInjector",
    "get_metric_injector",
    # LLM scenario generation
    "LLMScenarioGenerator",
    "get_scenario_generator",
    "GeneratedScenario",
]
