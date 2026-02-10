"""Integration tests for Approvals API endpoints."""
import pytest


class TestApprovalsAPI:
    """Test Approvals workflow."""

    async def test_get_pending_approvals(self, api_client, pending_action):
        """Test GET /api/v1/approvals/pending."""
        response = await api_client.get("/api/v1/approvals/pending")

        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(action["id"] == str(pending_action.id) for action in data)

    async def test_approve_action(self, api_client, pending_action, action_approval_payload):
        """Test POST /api/v1/approvals/{action_id}/approve."""
        response = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/approve",
            json=action_approval_payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "approved"
        assert data["approved_by"] == action_approval_payload["approved_by"]

    async def test_reject_action(self, api_client, pending_action, action_rejection_payload):
        """Test POST /api/v1/approvals/{action_id}/reject."""
        response = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/reject",
            json=action_rejection_payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "rejected"
        assert data["rejection_reason"] == action_rejection_payload["rejection_reason"]

    async def test_approve_updates_incident_status(self, api_client, pending_action, action_approval_payload):
        """Test approval updates parent incident."""
        response = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/approve",
            json=action_approval_payload
        )

        assert response.status_code == 200

        # Check incident status updated
        incident_response = await api_client.get(f"/api/v1/incidents/{pending_action.incident_id}")
        incident_data = incident_response.json()

        assert incident_data["status"] in ["approved", "pending_approval"]

    async def test_reject_escalates_incident(self, api_client, pending_action, action_rejection_payload):
        """Test rejection escalates incident."""
        response = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/reject",
            json=action_rejection_payload
        )

        assert response.status_code == 200

        # Check incident escalated
        incident_response = await api_client.get(f"/api/v1/incidents/{pending_action.incident_id}")
        incident_data = incident_response.json()

        assert incident_data["status"] in ["escalated", "pending_approval"]

    async def test_approve_wrong_status_returns_400(self, api_client, approved_action, action_approval_payload):
        """Test approving already-approved action fails."""
        response = await api_client.post(
            f"/api/v1/approvals/{approved_action.id}/approve",
            json=action_approval_payload
        )

        assert response.status_code == 400

    async def test_approval_notes_captured(self, api_client, pending_action):
        """Test approval notes are stored."""
        payload = {
            "approved_by": "test@example.com",
            "approval_notes": "Approved after review",
            "execution_mode": "dry_run"
        }

        response = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/approve",
            json=payload
        )

        assert response.status_code == 200

        # Get action
        action_response = await api_client.get(f"/api/v1/actions/{pending_action.id}")
        action_data = action_response.json()

        assert "approval" in action_data or "approved_by" in action_data

    async def test_double_approval_prevented(self, api_client, pending_action, action_approval_payload):
        """Test action cannot be approved twice."""
        # First approval
        response1 = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/approve",
            json=action_approval_payload
        )
        assert response1.status_code == 200

        # Second approval should fail
        response2 = await api_client.post(
            f"/api/v1/approvals/{pending_action.id}/approve",
            json=action_approval_payload
        )
        assert response2.status_code == 400
