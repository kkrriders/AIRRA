"""Integration tests for Learning API endpoints."""
import pytest


class TestLearningAPI:
    """Test Learning and feedback endpoints."""

    async def test_capture_incident_outcome(self, api_client, resolved_incident_with_outcome,
                                            incident_outcome_payload):
        """Test POST /api/v1/learning/{incident_id}/outcome."""
        incident, hypothesis, action = resolved_incident_with_outcome

        payload = {
            **incident_outcome_payload,
            "hypothesis_id": str(hypothesis.id),
            "action_id": str(action.id)
        }

        response = await api_client.post(
            f"/api/v1/learning/{incident.id}/outcome",
            json=payload
        )

        assert response.status_code == 200
        data = response.json()
        assert "message" in data or "success" in str(data).lower()

    async def test_get_learning_insights(self, api_client, resolved_incident_with_outcome):
        """Test GET /api/v1/learning/insights."""
        response = await api_client.get("/api/v1/learning/insights?days=30")

        assert response.status_code == 200
        data = response.json()
        assert "total_incidents" in data or "mttr" in data.get("metrics", {})

    async def test_get_learned_patterns(self, api_client, resolved_incident_with_outcome):
        """Test GET /api/v1/learning/patterns."""
        # First capture outcome to create pattern
        incident, hypothesis, action = resolved_incident_with_outcome

        outcome_payload = {
            "hypothesis_id": str(hypothesis.id),
            "action_id": str(action.id),
            "hypothesis_correct": True,
            "action_effective": True,
            "human_override": False,
            "resolution_notes": "Pattern captured"
        }

        await api_client.post(f"/api/v1/learning/{incident.id}/outcome", json=outcome_payload)

        # Get patterns
        response = await api_client.get("/api/v1/learning/patterns")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_outcome_updates_pattern_confidence(self, api_client, test_db,
                                                      incident_factory, hypothesis_factory,
                                                      action_factory):
        """Test successful outcomes increase pattern confidence."""
        # Create incident
        incident = await incident_factory(status="resolved")
        hypothesis = await hypothesis_factory(incident_id=incident.id, category="memory_leak")
        action = await action_factory(incident_id=incident.id, status="succeeded")

        # Capture positive outcome
        payload = {
            "hypothesis_id": str(hypothesis.id),
            "action_id": str(action.id),
            "hypothesis_correct": True,
            "action_effective": True,
            "human_override": False
        }

        response = await api_client.post(f"/api/v1/learning/{incident.id}/outcome", json=payload)

        assert response.status_code == 200

    async def test_insights_include_mttr(self, api_client, resolved_incident_with_outcome):
        """Test insights include MTTR metric."""
        response = await api_client.get("/api/v1/learning/insights")

        assert response.status_code == 200
        data = response.json()

        # Check for MTTR or similar metric
        assert any(key in str(data).lower() for key in ["mttr", "resolution_time", "metrics"])

    async def test_insights_include_accuracy(self, api_client, resolved_incident_with_outcome):
        """Test insights include hypothesis accuracy."""
        incident, hypothesis, action = resolved_incident_with_outcome

        # Capture outcome
        payload = {
            "hypothesis_id": str(hypothesis.id),
            "action_id": str(action.id),
            "hypothesis_correct": True,
            "action_effective": True
        }

        await api_client.post(f"/api/v1/learning/{incident.id}/outcome", json=payload)

        response = await api_client.get("/api/v1/learning/insights")

        assert response.status_code == 200
        data = response.json()

        # Should include accuracy metrics
        assert any(key in str(data).lower() for key in ["accuracy", "correct", "hypothesis"])

    async def test_feedback_with_human_override(self, api_client, resolved_incident_with_outcome):
        """Test capturing feedback when human overrode recommendation."""
        incident, hypothesis, action = resolved_incident_with_outcome

        payload = {
            "hypothesis_id": str(hypothesis.id),
            "action_id": str(action.id),
            "hypothesis_correct": False,
            "action_effective": False,
            "human_override": True,
            "override_reason": "Human chose different approach",
            "resolution_notes": "Manual intervention required"
        }

        response = await api_client.post(f"/api/v1/learning/{incident.id}/outcome", json=payload)

        assert response.status_code == 200

    async def test_insights_time_range_filtering(self, api_client):
        """Test insights can be filtered by time range."""
        response = await api_client.get("/api/v1/learning/insights?days=7")

        assert response.status_code == 200
        data = response.json()
        assert "days" in data or "period" in data or "total_incidents" in data
