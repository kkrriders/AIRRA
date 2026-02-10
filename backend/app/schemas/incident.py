"""
Pydantic schemas for Incident API requests and responses.

Senior Engineering Note:
- Strict validation with type hints
- Separate schemas for create/update/response
- ConfigDict for ORM integration
"""
from datetime import datetime
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.incident import IncidentSeverity, IncidentStatus

if TYPE_CHECKING:
    from app.schemas.hypothesis import HypothesisResponse
    from app.schemas.action import ActionResponse


class IncidentBase(BaseModel):
    """Base schema with common fields."""

    title: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    severity: IncidentSeverity
    affected_service: str = Field(..., min_length=1, max_length=255)
    affected_components: list[str] = Field(default_factory=list)


class IncidentCreate(IncidentBase):
    """Schema for creating a new incident."""

    detected_at: datetime = Field(default_factory=datetime.utcnow)
    detection_source: str = Field(default="prometheus", max_length=100)
    metrics_snapshot: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    """Schema for updating an incident."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = Field(None, min_length=1)
    status: Optional[IncidentStatus] = None
    severity: Optional[IncidentSeverity] = None
    resolved_at: Optional[datetime] = None
    resolution_time_seconds: Optional[int] = Field(None, ge=0)


class IncidentResponse(IncidentBase):
    """Schema for incident responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: IncidentStatus
    detected_at: datetime
    detection_source: str
    resolved_at: Optional[datetime] = None
    resolution_time_seconds: Optional[int] = None
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


# Rebuild model to resolve forward references
from app.schemas.hypothesis import HypothesisResponse  # noqa: E402
from app.schemas.action import ActionResponse  # noqa: E402

IncidentWithRelations.model_rebuild()
