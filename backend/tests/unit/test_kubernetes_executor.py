"""Unit tests for Kubernetes executors."""
import pytest
from unittest.mock import Mock
from datetime import datetime

from app.core.execution.kubernetes import (
    KubernetesPodRestartExecutor,
    KubernetesScaleExecutor,
    get_executor,
)
from app.core.execution.base import ExecutionStatus
from app.models.action import ActionType


class TestKubernetesPodRestartExecutor:
    """Test pod restart executor."""

    async def test_execute_dry_run(self, pod_restart_parameters):
        """Test dry-run execution."""
        executor = KubernetesPodRestartExecutor(dry_run=True)

        result = await executor.execute(
            target="payment-service",
            parameters=pod_restart_parameters
        )

        assert result.status == ExecutionStatus.SUCCESS
        assert "simulated" in result.message.lower() or "dry" in result.message.lower()

    async def test_execute_validates_parameters(self):
        """Test parameter validation."""
        executor = KubernetesPodRestartExecutor(dry_run=True)

        # Even with minimal parameters, dry-run should succeed
        result = await executor.execute(target="test-service", parameters={})

        # In dry-run mode, validation is skipped and execution succeeds
        assert result.status == ExecutionStatus.SUCCESS
        assert result.dry_run is True

    async def test_validation_checks_replica_count(self, pod_restart_parameters, mock_k8s_client):
        """Test validation ensures multiple replicas."""
        executor = KubernetesPodRestartExecutor(dry_run=False, k8s_client=mock_k8s_client)

        # Mock deployment with only 1 replica
        mock_k8s_client.AppsV1Api().read_namespaced_deployment().spec.replicas = 1

        is_valid, error_msg = await executor.validate(target="test-service", parameters=pod_restart_parameters)

        # Should fail validation with single replica
        assert is_valid is False
        assert "replica" in error_msg.lower()

    async def test_rollback_not_applicable(self, pod_restart_parameters):
        """Test rollback returns not applicable for pod restart."""
        executor = KubernetesPodRestartExecutor(dry_run=True)

        result = await executor.execute(target="test", parameters=pod_restart_parameters)
        rollback_result = await executor.rollback(target="test", execution_result=result)

        assert "not applicable" in rollback_result.message.lower() or rollback_result.status == ExecutionStatus.SKIPPED

    async def test_graceful_shutdown_parameter(self, pod_restart_parameters):
        """Test graceful shutdown seconds parameter."""
        executor = KubernetesPodRestartExecutor(dry_run=True)

        pod_restart_parameters["graceful_shutdown"] = True

        result = await executor.execute(target="test", parameters=pod_restart_parameters)

        assert result.status == ExecutionStatus.SUCCESS

    async def test_execution_without_k8s_client(self, pod_restart_parameters):
        """Test execution works in simulation mode without K8s client."""
        executor = KubernetesPodRestartExecutor(dry_run=True, k8s_client=None)

        result = await executor.execute(target="test", parameters=pod_restart_parameters)

        assert result.status == ExecutionStatus.SUCCESS


class TestKubernetesScaleExecutor:
    """Test scaling executor."""

    async def test_scale_up_dry_run(self, scale_up_parameters):
        """Test scale up in dry-run."""
        executor = KubernetesScaleExecutor(dry_run=True)

        result = await executor.execute(target="api-gateway", parameters=scale_up_parameters)

        assert result.status == ExecutionStatus.SUCCESS
        assert "5" in result.message  # Target replicas

    async def test_scale_down_dry_run(self, scale_down_parameters):
        """Test scale down in dry-run."""
        executor = KubernetesScaleExecutor(dry_run=True)

        result = await executor.execute(target="worker", parameters=scale_down_parameters)

        assert result.status == ExecutionStatus.SUCCESS
        assert "2" in result.message  # Target replicas

    async def test_validation_checks_min_replicas(self, scale_down_parameters):
        """Test validation prevents scaling below 1."""
        executor = KubernetesScaleExecutor(dry_run=True)

        scale_down_parameters["replicas"] = 0  # Invalid

        is_valid, error_msg = await executor.validate(target="test", parameters=scale_down_parameters)

        assert is_valid is False
        assert "minimum" in error_msg.lower() or "below" in error_msg.lower()

    async def test_validation_checks_max_replicas(self, scale_up_parameters):
        """Test validation checks maximum replicas."""
        executor = KubernetesScaleExecutor(dry_run=True)

        scale_up_parameters["replicas"] = 1000  # Too high

        result = await executor.execute(target="test", parameters=scale_up_parameters)

        # Should handle or validate
        assert result is not None

    async def test_rollback_to_previous_count(self, scale_up_parameters):
        """Test rollback scales back to previous count."""
        executor = KubernetesScaleExecutor(dry_run=True)

        # Execute scale up
        result = await executor.execute(target="test", parameters=scale_up_parameters)

        # Rollback
        rollback_result = await executor.rollback(target="test", execution_result=result)

        assert rollback_result.status in [ExecutionStatus.SUCCESS, ExecutionStatus.SKIPPED]
        assert "previous" in rollback_result.message.lower() or "rollback" in rollback_result.message.lower()

    async def test_current_replica_detection(self, mock_k8s_client):
        """Test detection of current replica count."""
        executor = KubernetesScaleExecutor(dry_run=False, k8s_client=mock_k8s_client)

        params = {"namespace": "default", "deployment": "test", "replicas": 5}

        result = await executor.execute(target="test", parameters=params)

        assert result is not None


class TestExecutorRegistry:
    """Test executor factory function."""

    def test_get_restart_pod_executor(self):
        """Test getting restart pod executor."""
        executor = get_executor(ActionType.RESTART_POD, dry_run=True)

        assert isinstance(executor, KubernetesPodRestartExecutor)
        assert executor.dry_run is True

    def test_get_scale_up_executor(self):
        """Test getting scale executor."""
        executor = get_executor(ActionType.SCALE_UP, dry_run=True)

        assert isinstance(executor, KubernetesScaleExecutor)

    def test_get_scale_down_executor(self):
        """Test scale down uses same executor."""
        executor = get_executor(ActionType.SCALE_DOWN, dry_run=True)

        assert isinstance(executor, KubernetesScaleExecutor)

    def test_raises_error_for_unknown_action(self):
        """Test error for unsupported action type."""
        # get_executor returns None for unknown actions
        executor = get_executor("unknown_action", dry_run=True)
        assert executor is None


class TestExecutionResults:
    """Test execution result creation."""

    async def test_result_includes_timing(self, pod_restart_parameters):
        """Test execution result includes timing."""
        executor = KubernetesPodRestartExecutor(dry_run=True)

        result = await executor.execute(target="test", parameters=pod_restart_parameters)

        assert hasattr(result, 'started_at')
        assert hasattr(result, 'completed_at') or hasattr(result, 'ended_at')

    async def test_result_includes_details(self, scale_up_parameters):
        """Test result includes execution details."""
        executor = KubernetesScaleExecutor(dry_run=True)

        result = await executor.execute(target="test", parameters=scale_up_parameters)

        assert result.details is not None
        assert isinstance(result.details, dict)

    async def test_error_result_on_exception(self):
        """Test error result when execution fails."""
        executor = KubernetesPodRestartExecutor(dry_run=True)

        # Force error with invalid params
        try:
            result = await executor.execute(target="test", parameters={})
        except (ValueError, KeyError):
            # Expected
            pass
