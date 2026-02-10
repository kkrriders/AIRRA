"""Integration tests for Actions API endpoints."""
import pytest


class TestActionsAPI:
    """Test Actions API operations."""

    async def test_get_action_by_id(self, api_client, approved_action):
        """Test GET /api/v1/actions/{id}."""
        response = await api_client.get(f"/api/v1/actions/{approved_action.id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(approved_action.id)
        assert data["action_type"] == approved_action.action_type.value

    async def test_get_actions_by_incident(self, api_client, incident_with_actions):
        """Test GET /api/v1/actions/incident/{incident_id}."""
        response = await api_client.get(f"/api/v1/actions/incident/{incident_with_actions.id}")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_list_all_actions(self, api_client, approved_action, pending_action):
        """Test GET /api/v1/actions."""
        response = await api_client.get("/api/v1/actions")

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 2

    async def test_execute_approved_action_dry_run(self, api_client, approved_action):
        """Test POST /api/v1/actions/{id}/execute in dry-run."""
        response = await api_client.post(f"/api/v1/actions/{approved_action.id}/execute")

        assert response.status_code == 200
        data = response.json()
        assert "status" in data

    async def test_execute_pending_action_returns_400(self, api_client, pending_action):
        """Test execution of non-approved action fails."""
        response = await api_client.post(f"/api/v1/actions/{pending_action.id}/execute")

        assert response.status_code == 400

    async def test_execute_action_updates_incident_status(self, api_client, approved_action, test_db):
        """Test successful execution updates parent incident."""
        response = await api_client.post(f"/api/v1/actions/{approved_action.id}/execute")

        assert response.status_code == 200

        # Get incident
        incident_response = await api_client.get(f"/api/v1/incidents/{approved_action.incident_id}")
        incident_data = incident_response.json()

        assert incident_data["status"] in ["resolved", "executing"]

    async def test_action_execution_result_captured(self, api_client, approved_action):
        """Test execution result is stored."""
        response = await api_client.post(f"/api/v1/actions/{approved_action.id}/execute")

        assert response.status_code == 200

        # Get action details
        action_response = await api_client.get(f"/api/v1/actions/{approved_action.id}")
        action_data = action_response.json()

        assert "execution_result" in action_data or action_data["status"] in ["succeeded", "executing"]

    async def test_get_nonexistent_action_returns_404(self, api_client):
        """Test 404 for invalid action ID."""
        response = await api_client.get("/api/v1/actions/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404
