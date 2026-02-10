"""
Base classes for action execution.

Senior Engineering Note:
- Abstract executor interface for different action types
- Dry-run mode support for safe testing
- Execution result tracking
- Safety validation before execution
"""
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ExecutionStatus(str, Enum):
    """Status of an action execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"


class ExecutionResult(BaseModel):
    """Result of an action execution."""

    status: ExecutionStatus
    message: str = Field(..., description="Human-readable result message")
    details: dict[str, Any] = Field(default_factory=dict, description="Execution details")
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    dry_run: bool = False
    error: Optional[str] = None


class ActionExecutor(ABC):
    """
    Abstract base class for action executors.

    Each executor implements a specific type of remediation action.
    """

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run

    @abstractmethod
    async def execute(
        self,
        target: str,
        parameters: dict[str, Any],
    ) -> ExecutionResult:
        """
        Execute the action.

        Args:
            target: Target resource (e.g., service name, pod name)
            parameters: Action-specific parameters

        Returns:
            ExecutionResult with status and details
        """
        pass

    @abstractmethod
    async def validate(
        self,
        target: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        Validate that the action can be safely executed.

        Args:
            target: Target resource
            parameters: Action-specific parameters

        Returns:
            Tuple of (is_valid, error_message)
        """
        pass

    @abstractmethod
    async def rollback(
        self,
        target: str,
        execution_result: ExecutionResult,
    ) -> ExecutionResult:
        """
        Rollback the action if possible.

        Args:
            target: Target resource
            execution_result: Original execution result

        Returns:
            ExecutionResult for the rollback operation
        """
        pass

    def _create_result(
        self,
        status: ExecutionStatus,
        message: str,
        started_at: datetime,
        details: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> ExecutionResult:
        """Helper to create execution result with timing."""
        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        return ExecutionResult(
            status=status,
            message=message,
            details=details or {},
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            dry_run=self.dry_run,
            error=error,
        )
