"""
Integration Tests for Incident Simulator API.

Tests the complete simulation flow:
- List scenarios
- Get scenario details
- Start simulation (with mocked LLM)
- Stop simulation
- Validate expected outcomes
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from app.core.simulation.scenario_definitions import SCENARIO_REGISTRY


@pytest.mark.asyncio
class TestSimulatorAPI:
    """Test suite for simulator API endpoints."""

    async def test_list_scenarios(self, api_client: AsyncClient):
        """Test listing all available scenarios."""
        response = await api_client.get("/api/v1/simulator/scenarios")

        assert response.status_code == 200
        scenarios = response.json()

        # Should have all 5 scenarios
        assert len(scenarios) == 5

        # Verify structure
        for scenario in scenarios:
            assert "id" in scenario
            assert "name" in scenario
            assert "description" in scenario
            assert "service" in scenario
            assert "severity" in scenario
            assert "difficulty" in scenario
            assert "tags" in scenario
            assert "duration_seconds" in scenario
            assert "metric_count" in scenario

        # Verify specific scenarios exist
        scenario_ids = [s["id"] for s in scenarios]
        assert "memory_leak_gradual" in scenario_ids
        assert "cpu_spike_traffic_surge" in scenario_ids
        assert "latency_spike_database" in scenario_ids
        assert "pod_crash_loop" in scenario_ids
        assert "dependency_failure_timeout" in scenario_ids

    async def test_list_scenarios_filtered_by_difficulty(self, api_client: AsyncClient):
        """Test filtering scenarios by difficulty."""
        response = await api_client.get(
            "/api/v1/simulator/scenarios",
            params={"difficulty": "beginner"},
        )

        assert response.status_code == 200
        scenarios = response.json()

        # All should be beginner level
        for scenario in scenarios:
            assert scenario["difficulty"] == "beginner"

    async def test_list_scenarios_filtered_by_tag(self, api_client: AsyncClient):
        """Test filtering scenarios by tag."""
        response = await api_client.get(
            "/api/v1/simulator/scenarios",
            params={"tag": "resource"},
        )

        assert response.status_code == 200
        scenarios = response.json()

        # All should have 'resource' tag
        for scenario in scenarios:
            assert "resource" in scenario["tags"]

    async def test_get_scenario_details(self, api_client: AsyncClient):
        """Test getting detailed scenario information."""
        response = await api_client.get(
            "/api/v1/simulator/scenarios/memory_leak_gradual"
        )

        assert response.status_code == 200
        scenario = response.json()

        # Verify detailed structure
        assert scenario["id"] == "memory_leak_gradual"
        assert scenario["name"] == "Gradual Memory Leak"
        assert scenario["service"] == "payment-service"
        assert scenario["severity"] == "critical"
        assert scenario["expected_root_cause"] == "memory_leak"

        # Should have metrics
        assert len(scenario["metrics"]) > 0
        for metric in scenario["metrics"]:
            assert "name" in metric
            assert "value" in metric
            assert "baseline" in metric
            assert "deviation_sigma" in metric
            assert "is_anomalous" in metric

        # Should have context
        assert "context" in scenario
        assert "expected_action_types" in scenario

    async def test_get_scenario_not_found(self, api_client: AsyncClient):
        """Test getting non-existent scenario."""
        response = await api_client.get(
            "/api/v1/simulator/scenarios/nonexistent_scenario"
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("app.core.simulation.metric_injector.httpx.AsyncClient")
    @patch("app.services.llm_client.get_llm_client")
    async def test_start_simulation_success(
        self,
        mock_get_llm_client,
        mock_http_client,
        api_client: AsyncClient,
    ):
        """Test starting a simulation successfully."""
        # Mock metric injector HTTP calls
        mock_client_instance = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "injected"}
        mock_client_instance.post.return_value = mock_response
        mock_http_client.return_value = mock_client_instance

        # Mock LLM client for hypothesis generation
        from app.core.reasoning.hypothesis_generator import HypothesesResponse, HypothesisItem
        from app.services.llm_client import LLMResponse

        mock_llm = AsyncMock()
        mock_get_llm_client.return_value = mock_llm

        # Create mock hypothesis response
        mock_hypothesis = HypothesisItem(
            description="Memory leak in Redis connection pooling",
            category="resource_exhaustion",
            confidence_score=0.85,
            reasoning="Recent deployment added connection pooling without proper cleanup",
            evidence=[],
        )

        mock_hypotheses_response = HypothesesResponse(
            hypotheses=[mock_hypothesis],
            overall_assessment="Multiple anomalies detected requiring investigation.", analysis_metadata={"total_anomalies": 4},
        )

        mock_llm_response = LLMResponse(
            content="",
            model="claude-3-5-sonnet-20241022",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
        )

        mock_llm.generate_hypotheses = AsyncMock(
            return_value=(mock_hypotheses_response, mock_llm_response)
        )

        # Start simulation
        response = await api_client.post(
            "/api/v1/simulator/scenarios/memory_leak_gradual/start",
            json={
                "auto_analyze": True,
                "execution_mode": "demo",
            },
        )

        assert response.status_code == 201
        result = response.json()

        # Verify response structure
        assert "simulation_id" in result
        assert result["scenario_id"] == "memory_leak_gradual"
        assert "incident_id" in result
        assert result["status"] in ["completed", "running"]
        assert result["hypotheses_count"] >= 0
        assert result["actions_count"] >= 0

        # Verify incident was created
        incident_id = result["incident_id"]
        assert incident_id is not None

        # Fetch incident to verify
        incident_response = await api_client.get(f"/api/v1/incidents/{incident_id}")
        assert incident_response.status_code == 200

        incident = incident_response.json()
        assert incident["affected_service"] == "payment-service"
        assert "[SIMULATION]" in incident["title"]
        assert incident["context"]["simulation"] is True

    async def test_start_simulation_invalid_scenario(self, api_client: AsyncClient):
        """Test starting simulation with invalid scenario ID."""
        response = await api_client.post(
            "/api/v1/simulator/scenarios/invalid_scenario/start",
            json={"auto_analyze": True},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("app.core.simulation.metric_injector.httpx.AsyncClient")
    async def test_start_simulation_without_mock_service(
        self,
        mock_http_client,
        api_client: AsyncClient,
    ):
        """Test starting simulation when mock service is unavailable."""
        # Mock HTTP client to raise connection error
        mock_client_instance = AsyncMock()
        mock_client_instance.post.side_effect = Exception("Connection refused")
        mock_http_client.return_value = mock_client_instance

        # Mock LLM for analysis
        with patch("app.services.llm_client.get_llm_client") as mock_get_llm:
            from app.core.reasoning.hypothesis_generator import HypothesesResponse, HypothesisItem
            from app.services.llm_client import LLMResponse

            mock_llm = AsyncMock()
            mock_get_llm.return_value = mock_llm

            mock_hypothesis = HypothesisItem(
                description="CPU saturation from traffic surge",
                category="capacity",
                confidence_score=0.90,
                reasoning="High CPU correlates with increased request rate",
                evidence=[],
            )

            mock_llm.generate_hypotheses = AsyncMock(
                return_value=(
                    HypothesesResponse(hypotheses=[mock_hypothesis], overall_assessment="Anomaly detected.", analysis_metadata={}),
                    LLMResponse(content="", model="test", prompt_tokens=10, completion_tokens=10, total_tokens=20),
                )
            )

            # Use a different scenario from test_start_simulation_success to
            # avoid in-memory scenario state leaking between tests.
            response = await api_client.post(
                "/api/v1/simulator/scenarios/latency_spike_database/start",
                json={"auto_analyze": True},
            )

            # Should succeed despite mock service being down.
            # The simulator is resilient — it falls back to simulated metrics
            # and still creates an incident regardless of mock service availability.
            assert response.status_code == 201
            result = response.json()
            assert "incident_id" in result
            assert result.get("scenario_id") == "latency_spike_database"

    async def test_list_active_simulations(self, api_client: AsyncClient):
        """Test listing active simulations."""
        response = await api_client.get("/api/v1/simulator/simulations")

        assert response.status_code == 200
        simulations = response.json()

        # Should be a list (may be empty)
        assert isinstance(simulations, list)

    async def test_get_simulation_status(self, api_client: AsyncClient):
        """Test getting simulation status."""
        # First start a simulation
        with patch("app.core.simulation.metric_injector.httpx.AsyncClient") as mock_http:
            with patch("app.services.llm_client.get_llm_client") as mock_llm_client:
                # Setup mocks
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"status": "injected"}
                mock_client.post.return_value = mock_response
                mock_http.return_value = mock_client

                from app.core.reasoning.hypothesis_generator import (
                    HypothesesResponse,
                    HypothesisItem,
                )
                from app.services.llm_client import LLMResponse

                mock_llm = AsyncMock()
                mock_llm_client.return_value = mock_llm
                mock_llm.generate_hypotheses = AsyncMock(
                    return_value=(
                        HypothesesResponse(
                            hypotheses=[
                                HypothesisItem(
                                    description="Test",
                                    category="test",
                                    confidence_score=0.8,
                                    reasoning="Test",
                                    evidence=[],
                                )
                            ],
                            overall_assessment="Anomaly detected.", analysis_metadata={},
                        ),
                        LLMResponse(content="", model="test", prompt_tokens=1, completion_tokens=1, total_tokens=2),
                    )
                )

                start_response = await api_client.post(
                    "/api/v1/simulator/scenarios/memory_leak_gradual/start",
                    json={"auto_analyze": True},
                )

                assert start_response.status_code == 201
                simulation_id = start_response.json()["simulation_id"]

                # Now get status
                status_response = await api_client.get(
                    f"/api/v1/simulator/simulations/{simulation_id}"
                )

                assert status_response.status_code == 200
                status = status_response.json()
                assert status["simulation_id"] == simulation_id
                assert "status" in status
                assert "incident_id" in status

    async def test_get_simulation_not_found(self, api_client: AsyncClient):
        """Test getting status of non-existent simulation."""
        response = await api_client.get(
            "/api/v1/simulator/simulations/sim_nonexistent"
        )

        assert response.status_code == 404

    @patch("app.core.simulation.metric_injector.httpx.AsyncClient")
    async def test_stop_simulation(self, mock_http_client, api_client: AsyncClient):
        """Test stopping a running simulation."""
        # Mock metric injector
        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "stopped"}
        mock_client.post.return_value = mock_response
        mock_http_client.return_value = mock_client

        with patch("app.services.llm_client.get_llm_client") as mock_llm_client:
            from app.core.reasoning.hypothesis_generator import HypothesesResponse, HypothesisItem
            from app.services.llm_client import LLMResponse

            mock_llm = AsyncMock()
            mock_llm_client.return_value = mock_llm
            mock_llm.generate_hypotheses = AsyncMock(
                return_value=(
                    HypothesesResponse(
                        hypotheses=[
                            HypothesisItem(
                                description="Test",
                                category="test",
                                confidence_score=0.8,
                                reasoning="Test",
                                evidence=[],
                            )
                        ],
                        overall_assessment="Anomaly detected.", analysis_metadata={},
                    ),
                    LLMResponse(content="", model="test", prompt_tokens=1, completion_tokens=1, total_tokens=2),
                )
            )

            # Start simulation
            start_response = await api_client.post(
                "/api/v1/simulator/scenarios/memory_leak_gradual/start",
                json={"auto_analyze": True},
            )

            assert start_response.status_code == 201
            simulation_id = start_response.json()["simulation_id"]

            # Stop simulation
            stop_response = await api_client.post(
                f"/api/v1/simulator/simulations/{simulation_id}/stop"
            )

            assert stop_response.status_code == 200
            result = stop_response.json()
            assert result["status"] == "stopped"
            assert result["simulation_id"] == simulation_id

    async def test_stop_simulation_not_found(self, api_client: AsyncClient):
        """Test stopping non-existent simulation."""
        response = await api_client.post(
            "/api/v1/simulator/simulations/sim_nonexistent/stop"
        )

        assert response.status_code == 404


@pytest.mark.asyncio
class TestScenarioValidation:
    """Test scenario definitions are valid."""

    def test_all_scenarios_have_required_fields(self):
        """Verify all scenarios have required fields."""
        for scenario_id, scenario in SCENARIO_REGISTRY.items():
            assert scenario.scenario_id == scenario_id
            assert scenario.name
            assert scenario.description
            assert scenario.service_name
            assert len(scenario.metrics) > 0
            assert scenario.expected_severity
            assert scenario.expected_root_cause
            assert scenario.duration_seconds > 0

    def test_all_scenarios_have_anomalous_metrics(self):
        """Verify all scenarios have at least one anomalous metric."""
        for scenario_id, scenario in SCENARIO_REGISTRY.items():
            anomalous_count = sum(1 for m in scenario.metrics if m.is_anomalous)
            assert anomalous_count > 0, f"Scenario {scenario_id} has no anomalous metrics"

    def test_scenario_metrics_snapshot_format(self):
        """Verify metrics snapshot format is correct."""
        for scenario_id, scenario in SCENARIO_REGISTRY.items():
            snapshot = scenario.to_metrics_snapshot()

            assert isinstance(snapshot, dict)
            for metric_name, metric_data in snapshot.items():
                assert "current" in metric_data
                assert "expected" in metric_data
                assert "deviation" in metric_data
                assert isinstance(metric_data["current"], (int, float))
                assert isinstance(metric_data["expected"], (int, float))
                assert isinstance(metric_data["deviation"], (int, float))
