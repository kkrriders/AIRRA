"""
Pydantic schemas for OnCallSchedule API requests and responses.

Senior Engineering Note:
- Timezone-aware datetime handling
- Validation for time ranges
- Priority level constraints
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.on_call_schedule import OnCallPriority


class OnCallScheduleBase(BaseModel):
    """Base schema with common fields."""

    service: Optional[str] = Field(
        None,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Service name (NULL = all services)",
    )
    team: Optional[str] = Field(
        None,
        max_length=100,
        description="Team name (NULL = all teams)",
    )
    start_time: datetime = Field(..., description="Shift start time (UTC)")
    end_time: datetime = Field(..., description="Shift end time (UTC)")
    priority: OnCallPriority = Field(
        default=OnCallPriority.PRIMARY,
        description="Escalation priority level",
    )

    @field_validator("end_time")
    @classmethod
    def validate_end_after_start(cls, v: datetime, info) -> datetime:
        """Ensure end_time is after start_time."""
        if "start_time" in info.data and v <= info.data["start_time"]:
            raise ValueError("end_time must be after start_time")
        return v


class OnCallScheduleCreate(OnCallScheduleBase):
    """Schema for creating a new on-call schedule."""

    engineer_id: UUID = Field(..., description="Engineer being assigned")
    schedule_name: Optional[str] = Field(None, max_length=255)
    rotation_week: Optional[int] = Field(None, ge=1, le=52)
    is_active: bool = Field(default=True)


class OnCallScheduleUpdate(BaseModel):
    """Schema for updating an on-call schedule."""

    service: Optional[str] = Field(None, max_length=255)
    team: Optional[str] = Field(None, max_length=100)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    priority: Optional[OnCallPriority] = None
    schedule_name: Optional[str] = Field(None, max_length=255)
    rotation_week: Optional[int] = Field(None, ge=1, le=52)
    is_active: Optional[bool] = None


class OnCallScheduleResponse(OnCallScheduleBase):
    """Schema for on-call schedule responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engineer_id: UUID
    schedule_name: Optional[str] = None
    rotation_week: Optional[int] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class OnCallScheduleWithEngineer(OnCallScheduleResponse):
    """Schema including engineer details."""

    engineer_name: str = Field(..., description="Engineer's name")
    engineer_email: str = Field(..., description="Engineer's email")
    engineer_status: str = Field(..., description="Engineer's availability status")


class OnCallFindRequest(BaseModel):
    """Schema for finding who's on-call."""

    service: Optional[str] = Field(
        None,
        max_length=255,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Filter by service",
    )
    team: Optional[str] = Field(None, max_length=100, description="Filter by team")
    time: Optional[datetime] = Field(
        None,
        description="Check on-call at specific time (defaults to now)",
    )
    priority: Optional[OnCallPriority] = Field(
        None,
        description="Filter by priority level",
    )


class OnCallListResponse(BaseModel):
    """Schema for paginated on-call schedule list."""

    items: list[OnCallScheduleResponse]
    total: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    pages: int = Field(..., ge=0)
