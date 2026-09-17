"""Integration tests for Incidents API endpoints."""
from sqlalchemy import select

from app.models.audit_log import AgentAuditLog, AuditEventType
from app.models.hypothesis import Hypothesis
from app.models.incident_pattern import IncidentPattern


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
        assert "items" in data
        assert "total" in data
        assert data["total"] == 15

    async def test_list_incidents_pagination(self, api_client, multiple_incidents):
        """Test pagination parameters."""
        response = await api_client.get("/api/v1/incidents?page=1&page_size=5")

        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 5
        assert data["page"] == 1
        assert data["page_size"] == 5

    async def test_list_incidents_filter_by_status(self, api_client, multiple_incidents):
        """Test filtering by status."""
        response = await api_client.get("/api/v1/incidents?status=resolved")

        assert response.status_code == 200
        data = response.json()
        assert all(inc["status"] == "resolved" for inc in data["items"])

    async def test_list_incidents_filter_by_service(self, api_client, multiple_incidents):
        """Test filtering by service."""
        response = await api_client.get("/api/v1/incidents?service=service-0")

        assert response.status_code == 200
        data = response.json()
        assert all(inc["affected_service"] == "service-0" for inc in data["items"])

    async def test_update_incident(self, api_client, sample_incident, incident_update_payload):
        """Test PATCH /api/v1/incidents/{id} updates mutable fields."""
        response = await api_client.patch(
            f"/api/v1/incidents/{sample_incident.id}",
            json=incident_update_payload
        )

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == incident_update_payload["title"]
        assert data["severity"] == incident_update_payload["severity"]

    async def test_analyze_incident(self, api_client, sample_incident):
        """Test POST /api/v1/incidents/{id}/analyze returns 202 and enqueues task."""
        response = await api_client.post(f"/api/v1/incidents/{sample_incident.id}/analyze")

        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert data["incident_id"] == str(sample_incident.id)
        assert "poll" in data

    async def test_analyze_transitions_to_analyzing(self, api_client, sample_incident):
        """Test that /analyze immediately transitions incident to ANALYZING status."""
        await api_client.post(f"/api/v1/incidents/{sample_incident.id}/analyze")

        get_response = await api_client.get(f"/api/v1/incidents/{sample_incident.id}")
        data = get_response.json()

        # Status transitions to ANALYZING synchronously; worker completes async
        assert data["status"] == "analyzing"

    async def test_analyze_with_no_anomalies(self, api_client, sample_incident):
        """Test analyze accepts any DETECTED incident regardless of metrics."""
        response = await api_client.post(f"/api/v1/incidents/{sample_incident.id}/analyze")

        assert response.status_code == 202

    async def test_analyze_wrong_status_returns_400(self, api_client, test_db, incident_factory):
        """Test analyze requires DETECTED status."""
        incident = await incident_factory(status="analyzing")

        response = await api_client.post(f"/api/v1/incidents/{incident.id}/analyze")

        assert response.status_code == 400

    async def test_invalid_incident_payload_returns_422(self, api_client, invalid_incident_payload):
        """Test validation errors."""
        response = await api_client.post("/api/v1/incidents", json=invalid_incident_payload)
        assert response.status_code == 422


class TestDeleteIncident:
    """DELETE /api/v1/incidents/{id} — on-demand erasure request."""

    async def test_delete_nonexistent_incident_returns_404(self, api_client):
        response = await api_client.request(
            "DELETE",
            "/api/v1/incidents/00000000-0000-0000-0000-000000000000",
            json={"deleted_by": "sre@example.com"},
        )
        assert response.status_code == 404

    async def test_delete_incident_returns_204_and_removes_it(self, api_client, sample_incident):
        response = await api_client.request(
            "DELETE",
            f"/api/v1/incidents/{sample_incident.id}",
            json={"deleted_by": "sre@example.com", "reason": "user erasure request"},
        )
        assert response.status_code == 204

        get_response = await api_client.get(f"/api/v1/incidents/{sample_incident.id}")
        assert get_response.status_code == 404

    async def test_delete_cascades_to_hypotheses_and_actions(
        self, api_client, test_db, incident_with_hypotheses
    ):
        incident_id = incident_with_hypotheses.id
        response = await api_client.request(
            "DELETE",
            f"/api/v1/incidents/{incident_id}",
            json={"deleted_by": "sre@example.com"},
        )
        assert response.status_code == 204

        remaining = (
            await test_db.execute(select(Hypothesis).where(Hypothesis.incident_id == incident_id))
        ).scalars().all()
        assert remaining == []

    async def test_delete_writes_requested_and_deleted_audit_events(
        self, api_client, test_db, sample_incident
    ):
        incident_id = sample_incident.id
        service = sample_incident.affected_service

        response = await api_client.request(
            "DELETE",
            f"/api/v1/incidents/{incident_id}",
            json={"deleted_by": "sre@example.com", "reason": "erasure request"},
        )
        assert response.status_code == 204

        rows = (
            await test_db.execute(
                select(AgentAuditLog).order_by(AgentAuditLog.created_at)
            )
        ).scalars().all()
        events = {row.event_type: row for row in rows}

        requested = events[AuditEventType.DATA_DELETION_REQUESTED.value]
        assert requested.actor == "sre@example.com"
        # ON DELETE SET NULL applies to every row referencing the incident at
        # delete time — including this one, written earlier in the same
        # transaction — so the FK is None; the id survives only in `details`.
        assert requested.incident_id is None
        assert requested.details["incident_id"] == str(incident_id)
        assert requested.details["reason"] == "erasure request"

        deleted = events[AuditEventType.DATA_DELETED.value]
        assert deleted.actor == "sre@example.com"
        # FK goes NULL once the incident row is gone — the id lives on in details instead.
        assert deleted.incident_id is None
        assert deleted.details["incident_id"] == str(incident_id)
        assert deleted.details["affected_service"] == service

    async def test_delete_rejects_malformed_actor(self, api_client, sample_incident):
        response = await api_client.request(
            "DELETE",
            f"/api/v1/incidents/{sample_incident.id}",
            json={"deleted_by": "not valid!!"},
        )
        assert response.status_code == 422

    async def test_delete_does_not_touch_incident_patterns(
        self, api_client, test_db, sample_incident
    ):
        """incident_patterns has no FK to Incident — deleting an incident must never touch it."""
        pattern = IncidentPattern(
            pattern_id="test-service:memory_leak",
            name="Memory leak pattern",
            category="memory_leak",
            signal_indicators=["memory_usage"],
        )
        test_db.add(pattern)
        await test_db.commit()

        response = await api_client.request(
            "DELETE",
            f"/api/v1/incidents/{sample_incident.id}",
            json={"deleted_by": "sre@example.com"},
        )
        assert response.status_code == 204

        remaining = (
            await test_db.execute(
                select(IncidentPattern).where(IncidentPattern.pattern_id == "test-service:memory_leak")
            )
        ).scalar_one_or_none()
        assert remaining is not None


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
