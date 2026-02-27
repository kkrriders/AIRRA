"""
Scenario Runner - Orchestrates Incident Simulations.

Coordinates:
1. Metric injection via MetricInjector
2. Incident creation and analysis via quick_incident API
3. Cleanup and state management
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Union
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.quick_incident import (
    QuickIncidentRequest,
    create_and_analyze_incident,
)
from app.core.simulation.metric_injector import get_metric_injector
from app.core.simulation.scenario_definitions import (
    IncidentScenario,
    get_scenario,
)

logger = logging.getLogger(__name__)


class SimulationResult:
    """Result of running a scenario simulation."""

    def __init__(
        self,
        simulation_id: str,
        scenario_id: str,
        incident_id: Optional[Union[UUID, str]] = None,
        status: str = "running",
        started_at: Optional[datetime] = None,
        error: Optional[str] = None,
    ):
        self.simulation_id = simulation_id
        self.scenario_id = scenario_id
        self.incident_id = str(incident_id) if incident_id else None
        self.status = status
        self.started_at = started_at or datetime.now(timezone.utc)
        self.completed_at: Optional[datetime] = None
        self.error = error
        self.hypotheses_count = 0
        self.actions_count = 0
        self.metrics_injected = False

    def to_dict(self) -> Dict:
        """Convert to dictionary for API response."""
        return {
            "simulation_id": self.simulation_id,
            "scenario_id": self.scenario_id,
            "incident_id": self.incident_id,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
            "hypotheses_count": self.hypotheses_count,
            "actions_count": self.actions_count,
            "metrics_injected": self.metrics_injected,
        }

    def mark_completed(self):
        """Mark simulation as completed."""
        self.status = "completed"
        self.completed_at = datetime.now(timezone.utc)

    def mark_failed(self, error: str):
        """Mark simulation as failed."""
        self.status = "failed"
        self.error = error
        self.completed_at = datetime.now(timezone.utc)


class ScenarioRunner:
    """
    Orchestrates scenario simulations.

    Coordinates metric injection, incident creation, and LLM analysis.
    """

    def __init__(self, mock_service_url: str = "http://localhost:5001"):
        """
        Initialize the scenario runner.

        Args:
            mock_service_url: URL of the mock service for metric injection
        """
        self.mock_service_url = mock_service_url
        self.metric_injector = get_metric_injector(mock_service_url)
        self._active_simulations: Dict[str, SimulationResult] = {}

    async def run_scenario(
        self,
        scenario_id: str,
        db: AsyncSession,
        auto_analyze: bool = True,
        execution_mode: str = "demo",
    ) -> SimulationResult:
        """
        Run a complete scenario simulation.

        This orchestrates:
        1. Load scenario definition
        2. Inject metrics into mock service
        3. Create incident via quick_incident API
        4. LLM analysis (if auto_analyze=True)
        5. Return results

        Args:
            scenario_id: ID of scenario to run
            db: Database session for incident creation
            auto_analyze: If True, automatically analyze with LLM
            execution_mode: Mode for action execution (demo, dry_run, live)

        Returns:
            SimulationResult with incident_id and analysis results

        Raises:
            ValueError: If scenario not found
            Exception: If simulation fails
        """
        # Generate unique simulation ID
        simulation_id = f"sim_{uuid.uuid4().hex[:8]}"

        # Load scenario
        scenario = get_scenario(scenario_id)
        if not scenario:
            raise ValueError(f"Scenario not found: {scenario_id}")

        logger.info(
            f"Starting simulation {simulation_id} for scenario '{scenario.name}'"
        )

        # Create result tracker
        result = SimulationResult(
            simulation_id=simulation_id,
            scenario_id=scenario_id,
        )
        self._active_simulations[simulation_id] = result

        try:
            # ========================================
            # Step 1: Inject Metrics
            # ========================================
            logger.info(f"Step 1: Injecting metrics for {scenario_id}")

            try:
                injection_result = await self.metric_injector.inject_scenario(
                    scenario=scenario,
                    auto_stop=True,
                )
                result.metrics_injected = True
                logger.info(f"Metrics injected: {injection_result}")

            except Exception as e:
                logger.warning(
                    f"Failed to inject metrics (mock service may be down): {str(e)}"
                )
                logger.info("Continuing with simulated metrics in incident creation")
                result.metrics_injected = False

            # ========================================
            # Step 2: Create and Analyze Incident
            # ========================================
            logger.info(f"Step 2: Creating incident for {scenario.service_name}")

            # Build request for quick_incident API
            quick_incident_request = QuickIncidentRequest(
                service_name=scenario.service_name,
                title=f"[SIMULATION] {scenario.name}",
                description=f"{scenario.description}\n\n"
                f"**This is a simulated incident for demonstration purposes.**\n"
                f"Scenario ID: {scenario_id}\n"
                f"Simulation ID: {simulation_id}",
                severity=scenario.expected_severity,  # type: ignore
                metrics_snapshot=scenario.to_metrics_snapshot(),
                context={
                    **scenario.context,
                    "simulation": True,
                    "simulation_id": simulation_id,
                    "scenario_id": scenario_id,
                    "execution_mode": execution_mode,
                },
            )

            # Call the quick_incident endpoint directly
            # This handles anomaly detection, LLM analysis, and action generation
            incident_with_relations = await create_and_analyze_incident(
                request=quick_incident_request,
                db=db,
            )

            result.incident_id = str(incident_with_relations.id)
            result.hypotheses_count = len(incident_with_relations.hypotheses)
            result.actions_count = len(incident_with_relations.actions)

            logger.info(
                f"Incident created: {incident_with_relations.id} with "
                f"{result.hypotheses_count} hypotheses and "
                f"{result.actions_count} actions"
            )

            # ========================================
            # Step 3: Mark Complete
            # ========================================
            result.mark_completed()

            logger.info(
                f"Simulation {simulation_id} completed successfully. "
                f"Incident: {result.incident_id}"
            )

            return result

        except Exception as e:
            logger.error(
                f"Simulation {simulation_id} failed: {str(e)}",
                exc_info=True,
            )
            result.mark_failed(str(e))
            raise

    async def stop_scenario(self, simulation_id: str) -> Dict:
        """
        Stop a running scenario simulation.

        Args:
            simulation_id: ID of simulation to stop

        Returns:
            Dict with stop status

        Raises:
            ValueError: If simulation not found
        """
        if simulation_id not in self._active_simulations:
            raise ValueError(f"Simulation not found: {simulation_id}")

        result = self._active_simulations[simulation_id]

        logger.info(f"Stopping simulation {simulation_id} (scenario: {result.scenario_id})")

        try:
            # Stop metric injection
            stop_result = await self.metric_injector.stop_injection(
                scenario_id=result.scenario_id
            )

            result.mark_completed()

            logger.info(f"Simulation {simulation_id} stopped: {stop_result}")

            return {
                "simulation_id": simulation_id,
                "scenario_id": result.scenario_id,
                "status": "stopped",
                "stop_result": stop_result,
            }

        except Exception as e:
            logger.error(f"Failed to stop simulation: {str(e)}")
            result.mark_failed(f"Stop failed: {str(e)}")
            raise

    def get_simulation(self, simulation_id: str) -> Optional[SimulationResult]:
        """
        Get simulation result by ID.

        Args:
            simulation_id: Simulation ID

        Returns:
            SimulationResult if found, None otherwise
        """
        return self._active_simulations.get(simulation_id)

    def list_active_simulations(self) -> list[SimulationResult]:
        """
        List all active simulations.

        Returns:
            List of active SimulationResults
        """
        return [
            result
            for result in self._active_simulations.values()
            if result.status == "running"
        ]

    async def cleanup(self) -> None:
        """Clean up resources and stop all active simulations."""
        logger.info("Cleaning up scenario runner...")

        # Stop all active simulations
        for simulation_id, result in list(self._active_simulations.items()):
            if result.status == "running":
                try:
                    await self.stop_scenario(simulation_id)
                except Exception as e:
                    logger.error(f"Failed to stop {simulation_id}: {e}")

        # Close metric injector
        await self.metric_injector.close()

        logger.info("Scenario runner cleanup complete")


# ============================================
# Singleton Instance
# ============================================

_runner_instance: Optional[ScenarioRunner] = None


def get_scenario_runner(mock_service_url: str = "http://localhost:5001") -> ScenarioRunner:
    """
    Get or create the singleton scenario runner instance.

    Args:
        mock_service_url: URL of mock service

    Returns:
        ScenarioRunner instance
    """
    global _runner_instance

    if _runner_instance is None:
        _runner_instance = ScenarioRunner(mock_service_url)
        logger.info("Created ScenarioRunner instance")

    return _runner_instance
