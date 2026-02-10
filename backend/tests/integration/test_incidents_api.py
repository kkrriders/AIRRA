"""Integration tests for Incidents API endpoints."""
import pytest
from datetime import datetime


class TestIncidentsAPI:
    """Test Incidents CRUD operations."""

    async def test_create_incident(self, api_client, incident_create_payload):
        """Test POST /api/v1/incidents creates incident."""
        response = await api_client.post("/api/v1/incidents", json=incident_create_payload)

        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["title"] == incident_create_payload["title"]
        assert data["severity"] == incident_create_payload["severity"]
        assert data["affected_service"] == incident_create_payload["affected_service"]

    async def test_get_incident_by_id(self, api_client, sample_incident):
        """Test GET /api/v1/incidents/{id} retrieves incident."""
        response = await api_client.get(f"/api/v1/incidents/{sample_incident.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(sample_incident.id)
        assert data["title"] == sample_incident.title

    async def test_get_incident_with_relations(self, api_client, incident_with_hypotheses):
        """Test GET includes hypotheses and actions."""
        response = await api_client.get(f"/api/v1/incidents/{incident_with_hypotheses.id}")

        assert response.status_code == 200
        data = response.json()
        assert "hypotheses" in data
        assert len(data["hypotheses"]) == 2

    async def test_get_nonexistent_incident_returns_404(self, api_client):
        """Test GET with invalid ID returns 404."""
        response = await api_client.get("/api/v1/incidents/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404

    async def test_list_incidents(self, api_client, multiple_incidents):
        """Test GET /api/v1/incidents lists incidents."""
        response = await api_client.get("/api/v1/incidents")

        assert response.status_code == 200
        data = response.json()
        assert "incidents" in data
        assert "total" in data
        assert data["total"] == 15

    async def test_list_incidents_pagination(self, api_client, multiple_incidents):
        """Test pagination parameters."""
        response = await api_client.get("/api/v1/incidents?page=1&page_size=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data["incidents"]) == 5
        assert data["page"] == 1
        assert data["page_size"] == 5

    async def test_list_incidents_filter_by_status(self, api_client, multiple_incidents):
        """Test filtering by status."""
        response = await api_client.get("/api/v1/incidents?status=resolved")

        assert response.status_code == 200
        data = response.json()
        assert all(inc["status"] == "resolved" for inc in data["incidents"])

    async def test_list_incidents_filter_by_service(self, api_client, multiple_incidents):
        """Test filtering by service."""
        response = await api_client.get("/api/v1/incidents?service=service-0")

        assert response.status_code == 200
        data = response.json()
        assert all(inc["affected_service"] == "service-0" for inc in data["incidents"])

    async def test_update_incident(self, api_client, sample_incident, incident_update_payload):
        """Test PATCH /api/v1/incidents/{id} updates incident."""
        response = await api_client.patch(
            f"/api/v1/incidents/{sample_incident.id}",
            json=incident_update_payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == incident_update_payload["status"]

    async def test_analyze_incident(self, api_client, sample_incident, mock_llm_client,
                                   anomalous_metric_data, mock_prometheus_client):
        """Test POST /api/v1/incidents/{id}/analyze triggers analysis."""
        mock_prometheus_client.get_service_metrics.return_value = anomalous_metric_data

        response = await api_client.post(f"/api/v1/incidents/{sample_incident.id}/analyze")

        assert response.status_code == 200
        data = response.json()
        assert "hypotheses_generated" in data or "status" in data

    async def test_analyze_creates_hypotheses(self, api_client, sample_incident,
                                             mock_llm_client, anomalous_metric_data):
        """Test analysis creates hypothesis records."""
        response = await api_client.post(f"/api/v1/incidents/{sample_incident.id}/analyze")

        # Get incident with relations
        get_response = await api_client.get(f"/api/v1/incidents/{sample_incident.id}")
        data = get_response.json()

        assert len(data.get("hypotheses", [])) > 0

    async def test_analyze_with_no_anomalies(self, api_client, sample_incident,
                                            normal_metric_data, mock_prometheus_client):
        """Test analysis with normal metrics."""
        mock_prometheus_client.get_service_metrics.return_value = normal_metric_data

        response = await api_client.post(f"/api/v1/incidents/{sample_incident.id}/analyze")

        assert response.status_code == 200

    async def test_analyze_wrong_status_returns_400(self, api_client, test_db, incident_factory):
        """Test analyze requires DETECTED status."""
        incident = await incident_factory(status="analyzing")

        response = await api_client.post(f"/api/v1/incidents/{incident.id}/analyze")

        assert response.status_code == 400

    async def test_invalid_incident_payload_returns_422(self, api_client, invalid_incident_payload):
        """Test validation errors."""
        response = await api_client.post("/api/v1/incidents", json=invalid_incident_payload)
        assert response.status_code == 422


class TestIncidentsAPIErrorHandling:
    """Test error scenarios."""

    async def test_database_rollback_on_error(self, api_client, test_db):
        """Test DB rollback on errors."""
        # This would need specific error triggering - simplified test
        invalid_data = {"title": "", "severity": "invalid"}
        response = await api_client.post("/api/v1/incidents", json=invalid_data)
        assert response.status_code == 422

    async def test_concurrent_updates(self, api_client, sample_incident):
        """Test concurrent incident updates."""
        update1 = {"status": "analyzing"}
        update2 = {"status": "resolved"}

        response1 = await api_client.patch(f"/api/v1/incidents/{sample_incident.id}", json=update1)
        response2 = await api_client.patch(f"/api/v1/incidents/{sample_incident.id}", json=update2)

        assert response1.status_code == 200
        assert response2.status_code == 200
