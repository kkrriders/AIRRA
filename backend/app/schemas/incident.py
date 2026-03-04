"""
Pydantic schemas for Incident API requests and responses.

Senior Engineering Note:
- Strict validation with type hints
- Separate schemas for create/update/response
- ConfigDict for ORM integration
"""
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.incident import IncidentSeverity, IncidentStatus

if TYPE_CHECKING:
    from app.schemas.action import ActionResponse
    from app.schemas.hypothesis import HypothesisResponse


class IncidentBase(BaseModel):
    """Base schema with common fields."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    severity: IncidentSeverity
    affected_service: str = Field(..., min_length=1, max_length=255)
    affected_components: list[str] = Field(default_factory=list)


class IncidentCreate(IncidentBase):
    """Schema for creating a new incident."""

    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detection_source: str = Field(default="prometheus", max_length=100)
    metrics_snapshot: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    """Schema for updating an incident.

    I6 fix: `status` is intentionally excluded. All status transitions must go
    through dedicated lifecycle endpoints (analyze, approve, reject, execute) to
    enforce the PENDING_APPROVAL → APPROVED → EXECUTING → RESOLVED safety gate.
    """

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, min_length=1)
    severity: IncidentSeverity | None = None
    resolved_at: datetime | None = None
    resolution_time_seconds: int | None = Field(None, ge=0)


class IncidentResponse(IncidentBase):
    """Schema for incident responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: IncidentStatus
    detected_at: datetime
    detection_source: str
    resolved_at: datetime | None = None
    resolution_time_seconds: int | None = None
    resolution_summary: str | None = None
    assigned_engineer_id: UUID | None = None
    metrics_snapshot: dict
    context: dict
    created_at: datetime
    updated_at: datetime


class IncidentWithRelations(IncidentResponse):
    """Schema for incident with related entities."""

    hypotheses: list["HypothesisResponse"] = Field(default_factory=list)
    actions: list["ActionResponse"] = Field(default_factory=list)


class IncidentListResponse(BaseModel):
    """Schema for paginated incident list."""

    items: list[IncidentResponse]
    total: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    pages: int = Field(..., ge=0)


class IncidentFilter(BaseModel):
    """Schema for filtering incidents with strict validation."""

    status: IncidentStatus | None = None
    service: str | None = Field(None, min_length=1, max_length=255)

    @field_validator("service")
    @classmethod
    def validate_service_name(cls, v: str | None) -> str | None:
        """Validate service name contains only safe characters."""
        if v is None:
            return v
        # Allow alphanumeric, hyphens, underscores only
        if not re.match(r"^[a-zA-Z0-9_-]+$", v):
            raise ValueError(
                "Service name must contain only alphanumeric characters, hyphens, and underscores"
            )
        return v


# Rebuild model to resolve forward references
from app.schemas.action import ActionResponse  # noqa: E402
from app.schemas.hypothesis import HypothesisResponse  # noqa: E402

IncidentWithRelations.model_rebuild()
