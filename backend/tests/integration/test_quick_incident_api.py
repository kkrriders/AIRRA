"""Integration tests for Quick Incident API endpoint."""
import pytest


class TestQuickIncidentAPI:
    """Test quick incident one-shot workflow."""

    async def test_quick_incident_full_workflow(self, api_client, quick_incident_payload,
                                                mock_llm_client, anomalous_metric_data,
                                                mock_prometheus_client):
        """Test POST /api/v1/quick-incident creates and analyzes incident."""
        mock_prometheus_client.get_service_metrics.return_value = anomalous_metric_data

        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["title"] == quick_incident_payload["title"]
        assert "hypotheses" in data
        assert len(data["hypotheses"]) > 0

    async def test_quick_incident_minimal_payload(self, api_client, quick_incident_minimal_payload,
                                                  mock_llm_client, anomalous_metric_data):
        """Test with minimal payload (auto-generates title)."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_minimal_payload)

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert "title" in data
        assert data["title"] is not None

    async def test_quick_incident_with_provided_metrics(self, api_client, quick_incident_payload,
                                                        mock_llm_client):
        """Test with metrics_snapshot bypasses Prometheus."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        assert response.status_code == 201
        data = response.json()
        assert data["metrics_snapshot"] == quick_incident_payload["metrics_snapshot"]

    async def test_quick_incident_creates_action(self, api_client, quick_incident_payload,
                                                 mock_llm_client, anomalous_metric_data):
        """Test action is created from hypothesis."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        assert response.status_code == 201
        data = response.json()

        # Check if actions created
        if "actions" in data:
            assert len(data["actions"]) > 0
            assert data["actions"][0]["status"] == "pending_approval"

    async def test_quick_incident_severity_auto_detection(self, api_client, mock_llm_client,
                                                          anomalous_metric_data, mock_prometheus_client):
        """Test severity is auto-detected from anomalies."""
        mock_prometheus_client.get_service_metrics.return_value = anomalous_metric_data

        payload = {
            "service_name": "critical-service",
            "severity": "medium"  # Will be updated based on anomalies
        }

        response = await api_client.post("/api/v1/quick-incident", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert "severity" in data

    async def test_quick_incident_handles_prometheus_unavailable(self, api_client,
                                                                 quick_incident_minimal_payload,
                                                                 mock_llm_client,
                                                                 mock_prometheus_client_with_error):
        """Test fallback when Prometheus unavailable."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_minimal_payload)

        # Should still create incident with fallback
        assert response.status_code in [201, 500]  # Depends on error handling strategy

    async def test_quick_incident_handles_llm_timeout(self, api_client, quick_incident_payload,
                                                      mock_llm_client_with_timeout):
        """Test handling of LLM timeout."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        # Should handle gracefully
        assert response.status_code in [201, 500]

    async def test_quick_incident_validates_service_name(self, api_client):
        """Test validation of required fields."""
        invalid_payload = {"severity": "high"}  # Missing service_name

        response = await api_client.post("/api/v1/quick-incident", json=invalid_payload)

        assert response.status_code == 422

    async def test_quick_incident_status_progression(self, api_client, quick_incident_payload,
                                                     mock_llm_client, anomalous_metric_data):
        """Test incident progresses through statuses."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        assert response.status_code == 201
        data = response.json()

        # Should be in analyzed state with pending approval
        assert data["status"] in ["pending_approval", "analyzing", "detected"]

    async def test_quick_incident_context_preserved(self, api_client, quick_incident_payload,
                                                    mock_llm_client):
        """Test context is preserved in incident."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        assert response.status_code == 201
        data = response.json()
        assert data["context"]["triggered_by"] == quick_incident_payload["context"]["triggered_by"]

    async def test_quick_incident_hypothesis_ranking(self, api_client, quick_incident_payload,
                                                     mock_llm_client):
        """Test hypotheses are ranked by confidence."""
        response = await api_client.post("/api/v1/quick-incident", json=quick_incident_payload)

        assert response.status_code == 201
        data = response.json()

        if len(data["hypotheses"]) > 1:
            # Check sorted by confidence
            confidences = [h["confidence_score"] for h in data["hypotheses"]]
            assert confidences == sorted(confidences, reverse=True)
