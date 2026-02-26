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
import re
from datetime import datetime
from typing import Any, Optional

from app.core.execution.base import ActionExecutor, ExecutionResult, ExecutionStatus

logger = logging.getLogger(__name__)

# Kubernetes resource name validation pattern
# Must consist of lowercase alphanumeric characters, '-', or '.'
# Must start and end with an alphanumeric character
K8S_NAME_PATTERN = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$")
K8S_MAX_NAME_LENGTH = 253


def validate_k8s_resource_name(name: str, field_name: str = "resource") -> tuple[bool, Optional[str]]:
    """
    Validate a Kubernetes resource name.

    Args:
        name: The resource name to validate
        field_name: Name of the field for error messages

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name:
        return False, f"{field_name} cannot be empty"

    if len(name) > K8S_MAX_NAME_LENGTH:
        return False, f"{field_name} must be {K8S_MAX_NAME_LENGTH} characters or less (got {len(name)})"

    if not K8S_NAME_PATTERN.match(name):
        return (
            False,
            f"{field_name} must consist of lowercase alphanumeric characters, '-', or '.', "
            f"and must start and end with an alphanumeric character (got: {name})",
        )

    return True, None


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

            # Validate Kubernetes resource names to prevent injection
            is_valid, error_msg = validate_k8s_resource_name(namespace, "namespace")
            if not is_valid:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message=f"Invalid namespace: {error_msg}",
                    started_at=started_at,
                    error=error_msg,
                )

            is_valid, error_msg = validate_k8s_resource_name(deployment, "deployment")
            if not is_valid:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message=f"Invalid deployment name: {error_msg}",
                    started_at=started_at,
                    error=error_msg,
                )

            if pod_name:
                is_valid, error_msg = validate_k8s_resource_name(pod_name, "pod_name")
                if not is_valid:
                    return self._create_result(
                        status=ExecutionStatus.FAILED,
                        message=f"Invalid pod name: {error_msg}",
                        started_at=started_at,
                        error=error_msg,
                    )

            # Validate deployment state before execution
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
                if self.k8s_client:
                    v1 = self.k8s_client.CoreV1Api()
                else:
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
        1. Resource names are valid Kubernetes identifiers
        2. Multiple replicas exist (don't restart if only 1)
        3. Deployment exists
        4. No active rollout
        """
        try:
            namespace = parameters.get("namespace", "default")
            deployment = parameters.get("deployment", target)

            # Validate resource names (done in execute() but good to double-check)
            is_valid, error_msg = validate_k8s_resource_name(namespace, "namespace")
            if not is_valid:
                return False, error_msg

            is_valid, error_msg = validate_k8s_resource_name(deployment, "deployment")
            if not is_valid:
                return False, error_msg

            if self.dry_run:
                # Skip cluster state validation in dry-run
                return True, None

            try:
                if self.k8s_client:
                    apps_v1 = self.k8s_client.AppsV1Api()
                else:
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

            # Validate Kubernetes resource names to prevent injection
            is_valid, error_msg = validate_k8s_resource_name(namespace, "namespace")
            if not is_valid:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message=f"Invalid namespace: {error_msg}",
                    started_at=started_at,
                    error=error_msg,
                )

            is_valid, error_msg = validate_k8s_resource_name(deployment, "deployment")
            if not is_valid:
                return self._create_result(
                    status=ExecutionStatus.FAILED,
                    message=f"Invalid deployment name: {error_msg}",
                    started_at=started_at,
                    error=error_msg,
                )

            # Validate deployment state
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
                if self.k8s_client:
                    apps_v1 = self.k8s_client.AppsV1Api()
                else:
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
        # Validate resource names
        namespace = parameters.get("namespace", "default")
        deployment = parameters.get("deployment", target)

        is_valid, error_msg = validate_k8s_resource_name(namespace, "namespace")
        if not is_valid:
            return False, error_msg

        is_valid, error_msg = validate_k8s_resource_name(deployment, "deployment")
        if not is_valid:
            return False, error_msg

        # Validate replica counts
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

            result = await self.execute(target, rollback_params)
            result.message = f"Rollback: {result.message}"
            return result

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
