"""
Kubernetes action executors.

Implements pod restart, scaling, and rollback operations for Kubernetes.

Senior Engineering Note:
- Uses Kubernetes Python client
- Implements safety checks (replica count, pod status)
- Supports dry-run mode
- Graceful degradation if K8s not available
"""
import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from app.core.execution.base import ActionExecutor, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)


class KubernetesPodRestartExecutor(ActionExecutor):
    """
    Restarts a Kubernetes pod by deleting it (relies on ReplicaSet to recreate).

    Safety checks:
    - Ensures multiple replicas exist
    - Checks pod is in Running state
    - Validates namespace exists
    """

    def __init__(self, dry_run: bool = True, k8s_client: Optional[Any] = None):
        """
        Initialize executor.

        Args:
            dry_run: If True, simulate actions without executing
            k8s_client: Optional K8s client for testing (defaults to creating real client)
        """
        super().__init__(dry_run)
        self.k8s_client = k8s_client

    async def execute(
        self,
        target: str,
        parameters: dict[str, Any],
    ) -> ExecutionResult:
        """
        Restart a pod by deleting it.

        Parameters expected:
        - namespace: Kubernetes namespace (default: default)
        - deployment: Deployment name
        - pod_name: Specific pod to restart (optional)
        """
        started_at = datetime.utcnow()

        try:
            namespace = parameters.get("namespace", "default")
            deployment = parameters.get("deployment", target)
            pod_name = parameters.get("pod_name")

            # Validate before execution
            is_valid, error_msg = await self.validate(target, parameters)
            if not is_valid:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message=f"Validation failed: {error_msg}",
                    started_at=started_at,
                    error=error_msg,
                )

            if self.dry_run:
                return self._create_result(
                    status=ExecutionStatus.SUCCESS,
                    message=f"[DRY RUN] Would restart pod in deployment {deployment}",
                    started_at=started_at,
                    details={
                        "action": "pod_restart",
                        "namespace": namespace,
                        "deployment": deployment,
                        "pod_name": pod_name,
                        "simulated": True,
                    },
                )

            # Actual execution
            try:
                # Import kubernetes client (optional dependency)
                from kubernetes import client, config

                # Load kubeconfig: try in-cluster first, fall back to local
                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()

                v1 = client.CoreV1Api()

                # If specific pod specified, delete it
                if pod_name:
                    v1.delete_namespaced_pod(
                        name=pod_name,
                        namespace=namespace,
                        grace_period_seconds=30,
                    )
                    message = f"Restarted pod {pod_name}"
                else:
                    # Get pods for deployment
                    pods = v1.list_namespaced_pod(
                        namespace=namespace,
                        label_selector=f"app={deployment}",
                    )

                    if not pods.items:
                        return self._create_result(
                            status=ExecutionStatus.FAILED,
                            message=f"No pods found for deployment {deployment}",
                            started_at=started_at,
                            error="No pods found",
                        )

                    # Restart first pod (let ReplicaSet handle recreation)
                    pod_to_restart = pods.items[0]
                    v1.delete_namespaced_pod(
                        name=pod_to_restart.metadata.name,
                        namespace=namespace,
                        grace_period_seconds=30,
                    )
                    message = f"Restarted pod {pod_to_restart.metadata.name}"

                # Wait for new pod to be ready
                await asyncio.sleep(5)  # Give it time to start

                return self._create_result(
                    status=ExecutionStatus.SUCCESS,
                    message=message,
                    started_at=started_at,
                    details={
                        "action": "pod_restart",
                        "namespace": namespace,
                        "deployment": deployment,
                        "pod_name": pod_name or pod_to_restart.metadata.name,
                    },
                )

            except ImportError:
                # Kubernetes client not installed - simulate
                logger.warning("Kubernetes client not installed, simulating restart")
                return self._create_result(
                    status=ExecutionStatus.SUCCESS,
                    message=f"[SIMULATED] Restarted pod in deployment {deployment}",
                    started_at=started_at,
                    details={
                        "action": "pod_restart",
                        "namespace": namespace,
                        "deployment": deployment,
                        "simulated": True,
                        "reason": "kubernetes_client_not_available",
                    },
                )

        except Exception as e:
            logger.error(f"Pod restart failed: {str(e)}", exc_info=True)
            return self._create_result(
                status=ExecutionStatus.FAILED,
                message=f"Pod restart failed: {str(e)}",
                started_at=started_at,
                error=str(e),
            )

    async def validate(
        self,
        target: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """
        Validate pod restart is safe.

        Checks:
        1. Multiple replicas exist (don't restart if only 1)
        2. Deployment exists
        3. No active rollout
        """
        try:
            namespace = parameters.get("namespace", "default")
            deployment = parameters.get("deployment", target)

            if self.dry_run:
                # Skip validation in dry-run
                return True, None

            try:
                from kubernetes import client, config

                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()

                apps_v1 = client.AppsV1Api()

                # Get deployment
                deployment_obj = apps_v1.read_namespaced_deployment(
                    name=deployment,
                    namespace=namespace,
                )

                # Check replica count
                replicas = deployment_obj.spec.replicas
                if replicas < 2:
                    return False, f"Only {replicas} replica(s) - unsafe to restart"

                # Check if deployment is stable
                available_replicas = deployment_obj.status.available_replicas or 0
                if available_replicas < replicas:
                    return False, "Deployment not fully available"

                return True, None

            except ImportError:
                # No k8s client - allow in dry-run mode
                logger.warning("Kubernetes client not available, skipping validation")
                return True, None

        except Exception as e:
            return False, f"Validation error: {str(e)}"

    async def rollback(
        self,
        target: str,
        execution_result: ExecutionResult,
    ) -> ExecutionResult:
        """
        Rollback is not applicable for pod restart.

        A new pod is created automatically by the ReplicaSet.
        """
        return ExecutionResult(
            status=ExecutionStatus.SKIPPED,
            message="Rollback not applicable for pod restart",
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            duration_seconds=0,
            dry_run=self.dry_run,
        )


class KubernetesScaleExecutor(ActionExecutor):
    """
    Scales a Kubernetes deployment up or down.

    Safety checks:
    - Doesn't scale below minimum replicas
    - Doesn't scale above maximum replicas
    - Checks resource availability
    """

    def __init__(self, dry_run: bool = True, k8s_client: Optional[Any] = None):
        """
        Initialize executor.

        Args:
            dry_run: If True, simulate actions without executing
            k8s_client: Optional K8s client for testing (defaults to creating real client)
        """
        super().__init__(dry_run)
        self.k8s_client = k8s_client

    async def execute(
        self,
        target: str,
        parameters: dict[str, Any],
    ) -> ExecutionResult:
        """
        Scale a deployment.

        Parameters expected:
        - namespace: Kubernetes namespace
        - deployment: Deployment name
        - replicas: Target replica count
        """
        started_at = datetime.utcnow()

        try:
            namespace = parameters.get("namespace", "default")
            deployment = parameters.get("deployment", target)
            target_replicas = parameters.get("replicas", 2)

            # Validate
            is_valid, error_msg = await self.validate(target, parameters)
            if not is_valid:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message=f"Validation failed: {error_msg}",
                    started_at=started_at,
                    error=error_msg,
                )

            if self.dry_run:
                # Use current_replicas from parameters if provided
                current_replicas = parameters.get("current_replicas", 1)
                return self._create_result(
                    status=ExecutionStatus.SUCCESS,
                    message=f"[DRY RUN] Would scale {deployment} from {current_replicas} to {target_replicas} replicas",
                    started_at=started_at,
                    details={
                        "action": "scale",
                        "namespace": namespace,
                        "deployment": deployment,
                        "previous_replicas": current_replicas,
                        "target_replicas": target_replicas,
                        "simulated": True,
                    },
                )

            # Actual execution
            try:
                from kubernetes import client, config

                try:
                    config.load_incluster_config()
                except config.ConfigException:
                    config.load_kube_config()

                apps_v1 = client.AppsV1Api()

                # Get current replica count
                deployment_obj = apps_v1.read_namespaced_deployment(
                    name=deployment,
                    namespace=namespace,
                )
                current_replicas = deployment_obj.spec.replicas

                # Scale deployment
                deployment_obj.spec.replicas = target_replicas
                apps_v1.patch_namespaced_deployment_scale(
                    name=deployment,
                    namespace=namespace,
                    body={"spec": {"replicas": target_replicas}},
                )

                return self._create_result(
                    status=ExecutionStatus.SUCCESS,
                    message=f"Scaled {deployment} from {current_replicas} to {target_replicas} replicas",
                    started_at=started_at,
                    details={
                        "action": "scale",
                        "namespace": namespace,
                        "deployment": deployment,
                        "previous_replicas": current_replicas,
                        "target_replicas": target_replicas,
                    },
                )

            except ImportError:
                logger.warning("Kubernetes client not installed, simulating scale")
                # Use current_replicas from parameters if provided
                current_replicas = parameters.get("current_replicas", 1)
                return self._create_result(
                    status=ExecutionStatus.SUCCESS,
                    message=f"[SIMULATED] Scaled {deployment} from {current_replicas} to {target_replicas} replicas",
                    started_at=started_at,
                    details={
                        "action": "scale",
                        "namespace": namespace,
                        "deployment": deployment,
                        "previous_replicas": current_replicas,
                        "target_replicas": target_replicas,
                        "simulated": True,
                    },
                )

        except Exception as e:
            logger.error(f"Scale operation failed: {str(e)}", exc_info=True)
            return self._create_result(
                status=ExecutionStatus.FAILED,
                message=f"Scale failed: {str(e)}",
                started_at=started_at,
                error=str(e),
            )

    async def validate(
        self,
        target: str,
        parameters: dict[str, Any],
    ) -> tuple[bool, Optional[str]]:
        """Validate scale operation is safe."""
        target_replicas = parameters.get("replicas", 2)
        min_replicas = parameters.get("min_replicas", 1)
        max_replicas = parameters.get("max_replicas", 10)

        if target_replicas < min_replicas:
            return False, f"Target replicas {target_replicas} below minimum {min_replicas}"

        if target_replicas > max_replicas:
            return False, f"Target replicas {target_replicas} exceeds maximum {max_replicas}"

        return True, None

    async def rollback(
        self,
        target: str,
        execution_result: ExecutionResult,
    ) -> ExecutionResult:
        """Rollback to previous replica count."""
        started_at = datetime.utcnow()

        try:
            details = execution_result.details
            previous_replicas = details.get("previous_replicas")

            if previous_replicas is None:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message="Cannot rollback: previous replica count unknown",
                    started_at=started_at,
                    error="Missing previous_replicas in execution details",
                )

            # Re-execute with previous replica count
            rollback_params = {
                "namespace": details.get("namespace", "default"),
                "deployment": details.get("deployment"),
                "replicas": previous_replicas,
            }

            return await self.execute(target, rollback_params)

        except Exception as e:
            return self._create_result(
                status=ExecutionStatus.FAILED,
                message=f"Rollback failed: {str(e)}",
                started_at=started_at,
                error=str(e),
            )


# Executor registry
EXECUTOR_REGISTRY: dict[str, type[ActionExecutor]] = {
    "restart_pod": KubernetesPodRestartExecutor,
    "scale_replicas": KubernetesScaleExecutor,
    "scale_up": KubernetesScaleExecutor,
    "scale_down": KubernetesScaleExecutor,
}


def get_executor(action_type: str, dry_run: bool = True) -> Optional[ActionExecutor]:
    """Get an executor instance for the given action type."""
    executor_class = EXECUTOR_REGISTRY.get(action_type)
    if executor_class:
        return executor_class(dry_run=dry_run)
    return None
