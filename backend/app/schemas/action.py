"""Pydantic schemas for Action API requests and responses."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.action import ActionStatus, ActionType, RiskLevel


class ActionBase(BaseModel):
    """Base schema with common fields."""

    action_type: ActionType
    name: str = Field(..., min_length=1, max_length=255)
    description: str = Field(..., min_length=1)
    target_service: str = Field(..., min_length=1, max_length=255)
    target_resource: Optional[str] = Field(None, max_length=255)
    risk_level: RiskLevel
    risk_score: float = Field(..., ge=0.0, le=1.0)
    blast_radius: str = Field(..., max_length=50)
    parameters: dict = Field(default_factory=dict)


class ActionCreate(ActionBase):
    """Schema for creating an action."""

    incident_id: UUID
    requires_approval: bool = True
    execution_mode: str = Field(default="dry_run")


class ActionApprove(BaseModel):
    """Schema for approving an action."""

    approved_by: str = Field(..., min_length=1, max_length=255)
    execution_mode: str = Field(default="dry_run")


class ActionReject(BaseModel):
    """Schema for rejecting an action."""

    rejected_by: str = Field(..., min_length=1, max_length=255)
    rejection_reason: str = Field(..., min_length=1)


class ActionUpdate(BaseModel):
    """Schema for updating an action."""

    status: Optional[ActionStatus] = None
    execution_result: Optional[dict] = None


class ActionResponse(ActionBase):
    """Schema for action responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    status: ActionStatus
    requires_approval: bool
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    execution_mode: str
    executed_at: Optional[datetime] = None
    execution_duration_seconds: Optional[int] = None
    execution_result: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
