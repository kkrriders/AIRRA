"""
Incident Simulator API Endpoints.

Provides REST API for running pre-packaged incident scenarios with automated
analysis. Perfect for demos, testing, and training.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.rate_limit import llm_rate_limit
from app.core.simulation.scenario_definitions import (
    ScenarioDifficulty,
    ScenarioTag,
    get_scenario,
    get_scenario_summary,
    list_scenarios,
)
from app.core.simulation.scenario_runner import get_scenario_runner
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


# ============================================
# Pydantic Schemas
# ============================================


class ScenarioSummary(BaseModel):
    """Summary information about a scenario."""

    id: str
    name: str
    description: str
    service: str
    severity: str
    difficulty: str
    tags: List[str]
    duration_seconds: int
    metric_count: int


class ScenarioDetail(BaseModel):
    """Detailed information about a scenario including metrics."""

    id: str
    name: str
    description: str
    service: str
    severity: str
    difficulty: str
    tags: List[str]
    duration_seconds: int
    metrics: List[dict]
    context: dict
    expected_root_cause: str
    expected_action_types: List[str]


class StartScenarioRequest(BaseModel):
    """Request to start a scenario simulation."""

    auto_analyze: bool = Field(
        default=True,
        description="If True, automatically analyze with LLM",
    )
    execution_mode: str = Field(
        default="demo",
        description="Execution mode: demo, dry_run, or live",
    )


class SimulationResponse(BaseModel):
    """Response from starting or stopping a simulation."""

    simulation_id: str
    scenario_id: str
    incident_id: Optional[int] = None
    status: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    hypotheses_count: int = 0
    actions_count: int = 0
    metrics_injected: bool = False


# ============================================
# API Endpoints
# ============================================


@router.get(
    "/scenarios",
    response_model=List[ScenarioSummary],
    summary="List all available scenarios",
)
async def list_available_scenarios(
    difficulty: Optional[ScenarioDifficulty] = None,
    tag: Optional[ScenarioTag] = None,
):
    """
    List all available incident scenarios.

    Optionally filter by difficulty level or tag.

    **Example use cases:**
    - Get all scenarios: `GET /api/v1/simulator/scenarios`
    - Get beginner scenarios: `GET /api/v1/simulator/scenarios?difficulty=beginner`
    - Get resource-related scenarios: `GET /api/v1/simulator/scenarios?tag=resource`
    """
    try:
        # Get filtered scenarios
        tags_filter = [tag] if tag else None
        scenarios = list_scenarios(difficulty=difficulty, tags=tags_filter)

        # Convert to summary format
        summaries = []
        for scenario in scenarios:
            summaries.append(
                ScenarioSummary(
                    id=scenario.scenario_id,
                    name=scenario.name,
                    description=scenario.description,
                    service=scenario.service_name,
                    severity=scenario.expected_severity,
                    difficulty=scenario.difficulty.value,
                    tags=[tag.value for tag in scenario.tags],
                    duration_seconds=scenario.duration_seconds,
                    metric_count=len(scenario.metrics),
                )
            )

        logger.info(f"Listed {len(summaries)} scenarios (filters: difficulty={difficulty}, tag={tag})")
        return summaries

    except Exception as e:
        logger.error(f"Failed to list scenarios: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list scenarios: {str(e)}",
        )


@router.get(
    "/scenarios/{scenario_id}",
    response_model=ScenarioDetail,
    summary="Get detailed information about a scenario",
)
async def get_scenario_details(scenario_id: str):
    """
    Get detailed information about a specific scenario.

    Includes all metrics, context, and expected outcomes.

    **Example:**
    ```
    GET /api/v1/simulator/scenarios/memory_leak_gradual
    ```
    """
    try:
        scenario = get_scenario(scenario_id)

        if not scenario:
            raise HTTPException(
                status_code=404,
                detail=f"Scenario not found: {scenario_id}",
            )

        # Convert metrics to dict format
        metrics_list = []
        for metric in scenario.metrics:
            metrics_list.append({
                "name": metric.metric_name,
                "value": metric.value,
                "baseline": metric.baseline,
                "deviation_sigma": metric.deviation_sigma,
                "pattern_type": metric.pattern_type.value,
                "unit": metric.unit,
                "is_anomalous": metric.is_anomalous,
            })

        detail = ScenarioDetail(
            id=scenario.scenario_id,
            name=scenario.name,
            description=scenario.description,
            service=scenario.service_name,
            severity=scenario.expected_severity,
            difficulty=scenario.difficulty.value,
            tags=[tag.value for tag in scenario.tags],
            duration_seconds=scenario.duration_seconds,
            metrics=metrics_list,
            context=scenario.context,
            expected_root_cause=scenario.expected_root_cause,
            expected_action_types=scenario.expected_action_types,
        )

        logger.info(f"Retrieved details for scenario: {scenario_id}")
        return detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get scenario details: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get scenario details: {str(e)}",
        )


@router.post(
    "/scenarios/{scenario_id}/start",
    response_model=SimulationResponse,
    status_code=201,
    summary="Start a scenario simulation",
    dependencies=[Depends(llm_rate_limit)],
)
async def start_scenario_simulation(
    scenario_id: str,
    request: StartScenarioRequest = StartScenarioRequest(),
    db: AsyncSession = Depends(get_db),
):
    """
    Start a scenario simulation.

    This will:
    1. Inject metrics into the mock service (if available)
    2. Create an incident in the database
    3. Analyze with LLM and generate hypotheses (if auto_analyze=True)
    4. Recommend remediation actions
    5. Auto-stop after scenario duration

    **Example:**
    ```bash
    curl -X POST http://localhost:8000/api/v1/simulator/scenarios/memory_leak_gradual/start \\
      -H "Content-Type: application/json" \\
      -d '{"auto_analyze": true, "execution_mode": "demo"}'
    ```

    **Response includes:**
    - `simulation_id`: Unique ID for this simulation run
    - `incident_id`: Database ID of created incident
    - `hypotheses_count`: Number of hypotheses generated
    - `actions_count`: Number of actions recommended
    """
    try:
        # Verify scenario exists
        scenario = get_scenario(scenario_id)
        if not scenario:
            raise HTTPException(
                status_code=404,
                detail=f"Scenario not found: {scenario_id}. "
                f"Use GET /api/v1/simulator/scenarios to list available scenarios.",
            )

        logger.info(
            f"Starting simulation for scenario '{scenario_id}' "
            f"(auto_analyze={request.auto_analyze}, mode={request.execution_mode})"
        )

        # Get scenario runner
        runner = get_scenario_runner()

        # Run the scenario
        result = await runner.run_scenario(
            scenario_id=scenario_id,
            db=db,
            auto_analyze=request.auto_analyze,
            execution_mode=request.execution_mode,
        )

        response = SimulationResponse(
            simulation_id=result.simulation_id,
            scenario_id=result.scenario_id,
            incident_id=result.incident_id,
            status=result.status,
            started_at=result.started_at.isoformat() if result.started_at else None,
            completed_at=result.completed_at.isoformat() if result.completed_at else None,
            error=result.error,
            hypotheses_count=result.hypotheses_count,
            actions_count=result.actions_count,
            metrics_injected=result.metrics_injected,
        )

        logger.info(
            f"Simulation started successfully: {result.simulation_id} "
            f"(incident: {result.incident_id})"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start simulation: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start simulation: {str(e)}",
        )


@router.post(
    "/simulations/{simulation_id}/stop",
    response_model=dict,
    summary="Stop a running simulation",
)
async def stop_simulation(simulation_id: str):
    """
    Stop a running simulation and clean up metrics.

    This will:
    1. Stop metric injection in the mock service
    2. Cancel auto-stop timer
    3. Mark simulation as stopped

    **Example:**
    ```bash
    curl -X POST http://localhost:8000/api/v1/simulator/simulations/sim_abc123/stop
    ```
    """
    try:
        runner = get_scenario_runner()

        logger.info(f"Stopping simulation: {simulation_id}")

        result = await runner.stop_scenario(simulation_id)

        logger.info(f"Simulation stopped: {simulation_id}")

        return {
            "status": "stopped",
            "simulation_id": simulation_id,
            "details": result,
        }

    except ValueError as e:
        raise HTTPException(
            status_code=404,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Failed to stop simulation: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to stop simulation: {str(e)}",
        )


@router.get(
    "/simulations/{simulation_id}",
    response_model=SimulationResponse,
    summary="Get simulation status",
)
async def get_simulation_status(simulation_id: str):
    """
    Get the current status of a simulation.

    **Example:**
    ```bash
    curl http://localhost:8000/api/v1/simulator/simulations/sim_abc123
    ```
    """
    try:
        runner = get_scenario_runner()

        result = runner.get_simulation(simulation_id)

        if not result:
            raise HTTPException(
                status_code=404,
                detail=f"Simulation not found: {simulation_id}",
            )

        response = SimulationResponse(
            simulation_id=result.simulation_id,
            scenario_id=result.scenario_id,
            incident_id=result.incident_id,
            status=result.status,
            started_at=result.started_at.isoformat() if result.started_at else None,
            completed_at=result.completed_at.isoformat() if result.completed_at else None,
            error=result.error,
            hypotheses_count=result.hypotheses_count,
            actions_count=result.actions_count,
            metrics_injected=result.metrics_injected,
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get simulation status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get simulation status: {str(e)}",
        )


@router.get(
    "/simulations",
    response_model=List[SimulationResponse],
    summary="List all active simulations",
)
async def list_active_simulations():
    """
    List all currently running simulations.

    **Example:**
    ```bash
    curl http://localhost:8000/api/v1/simulator/simulations
    ```
    """
    try:
        runner = get_scenario_runner()

        active_sims = runner.list_active_simulations()

        responses = []
        for result in active_sims:
            responses.append(
                SimulationResponse(
                    simulation_id=result.simulation_id,
                    scenario_id=result.scenario_id,
                    incident_id=result.incident_id,
                    status=result.status,
                    started_at=result.started_at.isoformat() if result.started_at else None,
                    completed_at=result.completed_at.isoformat() if result.completed_at else None,
                    error=result.error,
                    hypotheses_count=result.hypotheses_count,
                    actions_count=result.actions_count,
                    metrics_injected=result.metrics_injected,
                )
            )

        logger.info(f"Listed {len(responses)} active simulations")
        return responses

    except Exception as e:
        logger.error(f"Failed to list simulations: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list simulations: {str(e)}",
        )
