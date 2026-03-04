"""Pydantic schemas for Action API requests and responses."""
import re
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.action import ActionStatus, ActionType, RiskLevel

# Allowed approver identity format: email or simple username (alphanumeric + . _ - @)
_APPROVER_PATTERN = re.compile(r"^[\w.\-@+]{2,255}$")


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

    approved_by: str = Field(..., min_length=2, max_length=255)
    execution_mode: str = Field(default="dry_run")

    @field_validator("approved_by")
    @classmethod
    def validate_approved_by(cls, v: str) -> str:
        """S4 fix: reject obviously spoofed/system-impersonation values."""
        if not _APPROVER_PATTERN.match(v):
            raise ValueError(
                "approved_by must be a valid email or username (letters, digits, . _ - @ only)"
            )
        return v


class ActionReject(BaseModel):
    """Schema for rejecting an action."""

    rejected_by: str = Field(..., min_length=2, max_length=255)
    rejection_reason: str = Field(..., min_length=1)

    @field_validator("rejected_by")
    @classmethod
    def validate_rejected_by(cls, v: str) -> str:
        """S4 fix: reject obviously spoofed/system-impersonation values."""
        if not _APPROVER_PATTERN.match(v):
            raise ValueError(
                "rejected_by must be a valid email or username (letters, digits, . _ - @ only)"
            )
        return v


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
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    execution_mode: str
    executed_at: Optional[datetime] = None
    execution_duration_seconds: Optional[int] = None
    execution_result: Optional[dict] = None
    created_at: datetime
    updated_at: datetime
