"""
Pydantic schemas for Engineer API requests and responses.

Senior Engineering Note:
- Strict validation with type hints
- Separate schemas for create/update/response
- ConfigDict for ORM integration
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, EmailStr

from app.models.engineer import EngineerStatus


class EngineerBase(BaseModel):
    """Base schema with common fields."""

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr = Field(..., description="Engineer's email address")
    expertise: list[str] = Field(
        default_factory=list,
        description="Areas of expertise (e.g., ['kubernetes', 'databases'])",
    )
    department: Optional[str] = Field(None, max_length=100)


class EngineerCreate(EngineerBase):
    """Schema for creating a new engineer."""

    max_concurrent_reviews: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum concurrent review assignments",
    )
    slack_handle: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    additional_info: dict = Field(
        default_factory=dict,
        description="Additional metadata (timezone, preferences, etc.)",
    )


class EngineerUpdate(BaseModel):
    """Schema for updating an engineer."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    email: Optional[EmailStr] = None
    expertise: Optional[list[str]] = None
    department: Optional[str] = Field(None, max_length=100)
    status: Optional[EngineerStatus] = None
    is_available: Optional[bool] = None
    max_concurrent_reviews: Optional[int] = Field(None, ge=1, le=10)
    slack_handle: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=50)
    additional_info: Optional[dict] = None


class EngineerResponse(EngineerBase):
    """Schema for engineer responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: EngineerStatus
    is_available: bool
    max_concurrent_reviews: int
    current_review_count: int
    total_reviews_completed: int
    average_review_time_minutes: Optional[float] = None
    slack_handle: Optional[str] = None
    phone: Optional[str] = None
    additional_info: dict
    created_at: datetime
    updated_at: datetime


class EngineerWithStats(EngineerResponse):
    """Schema for engineer with additional statistics."""

    pending_reviews: int = Field(default=0, description="Number of pending reviews")
    in_progress_reviews: int = Field(default=0, description="Reviews currently in progress")
    completed_today: int = Field(default=0, description="Reviews completed today")
    capacity_percentage: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Current workload as percentage of capacity",
    )


class EngineerListResponse(BaseModel):
    """Schema for paginated engineer list."""

    items: list[EngineerResponse]
    total: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    pages: int = Field(..., ge=0)


class EngineerAvailability(BaseModel):
    """Schema for checking engineer availability."""

    engineer_id: UUID
    name: str
    is_available: bool
    current_review_count: int
    max_concurrent_reviews: int
    can_accept_review: bool
    reason: Optional[str] = Field(
        None,
        description="Reason if not available (e.g., 'At capacity', 'Offline')",
    )
