"""
Assignment schemas for request/response validation.

Used for incident assignment API endpoints.
"""
from uuid import UUID

from pydantic import BaseModel, Field


class AutoAssignRequest(BaseModel):
    """Request to auto-assign incident."""

    strategy: str = Field(
        default="on_call",
        description="Assignment strategy: 'on_call' or 'load_balanced'",
    )


class ManualAssignRequest(BaseModel):
    """Request to manually assign incident to specific engineer."""

    engineer_id: UUID = Field(description="Engineer ID to assign to")
    force: bool = Field(
        default=False,
        description="Force assignment even if engineer is at capacity",
    )


class AssignmentResponse(BaseModel):
    """Response for assignment operations."""

    success: bool
    engineer: dict | None = None
    strategy: str | None = None
    reason: str | None = None

    class Config:
        from_attributes = True


class AssignmentInfo(BaseModel):
    """Information about current incident assignment."""

    incident_id: UUID
    is_assigned: bool
    assigned_engineer: dict | None = None
    assigned_at: str | None = None

    class Config:
        from_attributes = True
