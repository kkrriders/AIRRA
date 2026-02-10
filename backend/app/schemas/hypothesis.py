"""Pydantic schemas for Hypothesis API requests and responses."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class HypothesisBase(BaseModel):
    """Base schema with common fields."""

    description: str = Field(..., min_length=1)
    category: str = Field(..., min_length=1, max_length=100)
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    evidence: dict = Field(default_factory=dict)
    supporting_signals: list[str] = Field(default_factory=list)


class HypothesisCreate(HypothesisBase):
    """Schema for creating a hypothesis."""

    incident_id: UUID
    rank: int = Field(..., ge=1)
    llm_model: str = Field(..., max_length=100)
    llm_prompt_tokens: Optional[int] = Field(None, ge=0)
    llm_completion_tokens: Optional[int] = Field(None, ge=0)
    llm_reasoning: Optional[str] = None


class HypothesisUpdate(BaseModel):
    """Schema for updating a hypothesis."""

    validated: Optional[bool] = None
    validation_feedback: Optional[str] = None


class HypothesisResponse(HypothesisBase):
    """Schema for hypothesis responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    incident_id: UUID
    rank: int
    llm_model: str
    validated: bool
    validation_feedback: Optional[str] = None
    created_at: datetime
