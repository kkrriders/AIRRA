"""
Push-based detection: Prometheus Alertmanager -> AIRRA webhook.

Replaces the ~15-60s Beat polling delay for services whose anomaly is already
expressible as a native PromQL alerting rule (see
monitoring/prometheus/alerts/ai-platform-anomaly.yml) -- Alertmanager fires
the moment its own evaluation_interval (15s) sees the rule go true, and pushes
here immediately instead of AIRRA having to ask.

The polling path (anomaly_monitor.py) is NOT removed: it stays as a slower,
independent fallback covering metrics/services without a native alerting
rule yet. Both paths share the same dedup window and incident-creation core
(AnomalyMonitor._create_incident_row) via create_incident_from_alert, so
whichever fires first wins and the other is a no-op.
"""
import logging

from fastapi import APIRouter, Depends

from app.api.dependencies import verify_alertmanager_token
from app.models.incident import IncidentSeverity

logger = logging.getLogger(__name__)

router = APIRouter()

_SEVERITY_MAP = {
    "critical": IncidentSeverity.CRITICAL,
    "warning": IncidentSeverity.MEDIUM,
}


@router.post("/alertmanager", dependencies=[Depends(verify_alertmanager_token)])
async def alertmanager_webhook(payload: dict) -> dict:
    """
    Receive Alertmanager's webhook notification and create an incident per
    firing alert. Accepts a raw dict (not a strict Pydantic schema) because
    Alertmanager's webhook payload shape has drifted across versions and a
    422 on an unrecognized field would silently drop a real alert -- better
    to defensively .get() and log what we couldn't use.
    """
    alerts = payload.get("alerts", [])
    created = 0
    for alert in alerts:
        if alert.get("status") != "firing":
            continue  # ignore "resolved" notifications -- AIRRA resolves via its own lifecycle

        labels = alert.get("labels", {})
        annotations = alert.get("annotations", {})
        service_name = labels.get("service")
        if not service_name:
            logger.warning("Alertmanager webhook: alert with no 'service' label, skipping: %s", labels)
            continue

        severity = _SEVERITY_MAP.get(labels.get("severity", ""), IncidentSeverity.MEDIUM)
        alertname = labels.get("alertname", "UnknownAlert")
        summary = annotations.get("summary", f"{alertname} on {service_name}")
        description = annotations.get("description", summary)

        from app.services.anomaly_monitor import get_monitor

        was_created = await get_monitor().create_incident_from_alert(
            service_name=service_name,
            title=summary,
            description=description,
            severity=severity,
            metrics_snapshot={},  # the alert doesn't carry raw values; PromQL already decided
            incident_context={
                "alertname": alertname,
                "starts_at": alert.get("startsAt"),
                "generator_url": alert.get("generatorURL"),
            },
        )
        if was_created:
            created += 1
            logger.info("Alertmanager webhook created incident for %s (%s)", service_name, alertname)
        else:
            logger.info("Alertmanager webhook: %s already reported recently, skipped", service_name)

    return {"status": "ok", "alerts_received": len(alerts), "incidents_created": created}
