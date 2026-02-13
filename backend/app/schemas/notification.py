"""
Pydantic schemas for Notification API requests and responses.

Senior Engineering Note:
- Multi-channel notification support
- SLA tracking and validation
- Secure token handling
"""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, EmailStr

from app.models.notification import (
    NotificationChannel,
    NotificationStatus,
    NotificationPriority,
)


class NotificationBase(BaseModel):
    """Base schema with common fields."""

    channel: NotificationChannel = Field(..., description="Delivery channel")
    priority: NotificationPriority = Field(
        default=NotificationPriority.NORMAL,
        description="Notification urgency",
    )
    subject: str = Field(..., min_length=1, max_length=500)
    message: str = Field(..., min_length=1)


class NotificationCreate(NotificationBase):
    """Schema for creating a new notification."""

    engineer_id: UUID = Field(..., description="Target engineer")
    incident_id: Optional[UUID] = Field(None, description="Related incident")
    recipient_address: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Email, Slack ID, phone, etc.",
    )
    sla_target_seconds: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Response time SLA in seconds",
    )
    max_retries: int = Field(default=3, ge=0, le=10)


class NotificationUpdate(BaseModel):
    """Schema for updating a notification."""

    status: Optional[NotificationStatus] = None
    delivered_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    last_error: Optional[str] = None
    escalated: Optional[bool] = None
    escalated_to_engineer_id: Optional[UUID] = None


class NotificationResponse(NotificationBase):
    """Schema for notification responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engineer_id: UUID
    incident_id: Optional[UUID] = None
    status: NotificationStatus
    recipient_address: str
    sent_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    response_time_seconds: Optional[int] = None
    sla_target_seconds: int
    sla_met: Optional[bool] = None
    retry_count: int
    max_retries: int
    last_error: Optional[str] = None
    escalated: bool
    escalated_to_engineer_id: Optional[UUID] = None
    escalated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class NotificationWithDetails(NotificationResponse):
    """Schema including engineer and incident details."""

    engineer_name: str = Field(..., description="Engineer's name")
    engineer_email: str = Field(..., description="Engineer's email")
    incident_title: Optional[str] = Field(None, description="Incident title")
    incident_severity: Optional[str] = Field(None, description="Incident severity")


class NotificationAcknowledge(BaseModel):
    """Schema for acknowledging a notification via token."""

    token: str = Field(..., min_length=1, description="Acknowledgement token from email")


class NotificationSendRequest(BaseModel):
    """Schema for manually sending a notification."""

    engineer_id: UUID
    incident_id: UUID
    channel: NotificationChannel
    priority: NotificationPriority = NotificationPriority.NORMAL
    custom_message: Optional[str] = Field(
        None,
        description="Custom message (overrides default template)",
    )


class NotificationStatsResponse(BaseModel):
    """Schema for notification statistics."""

    total_sent: int
    total_delivered: int
    total_acknowledged: int
    total_failed: int
    average_response_time_seconds: Optional[float] = None
    sla_compliance_rate: Optional[float] = Field(
        None,
        description="Percentage of notifications acknowledged within SLA",
    )
    escalation_rate: Optional[float] = Field(
        None,
        description="Percentage of notifications that were escalated",
    )


class NotificationListResponse(BaseModel):
    """Schema for paginated notification list."""

    items: list[NotificationResponse]
    total: int
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1, le=100)
    pages: int = Field(..., ge=0)
