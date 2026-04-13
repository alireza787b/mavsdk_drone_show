"""GCS-side SITL control inventory and lifecycle service."""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from src.sitl_control_models import (
    SitlControlDockerState,
    SitlControlFeatureFlags,
    SitlControlHostResponse,
    SitlControlHostSummary,
    SitlControlImageListResponse,
    SitlControlImageSummary,
    SitlControlInstanceListResponse,
    SitlControlInstanceLogResponse,
    SitlControlInstanceSummary,
    SitlControlOperationListResponse,
    SitlControlOperationResponse,
    SitlControlPolicyDefaults,
    SitlControlPolicyResponse,
    SitlControlReconcileRequest,
)

try:
    import psutil
except Exception:  # pragma: no cover - graceful runtime fallback when dependency is absent
    psutil = None

try:
    import docker
    from docker.errors import DockerException, NotFound
except Exception:  # pragma: no cover - graceful runtime fallback when dependency is absent
    docker = None

    class DockerException(Exception):
        """Fallback docker exception when the SDK is unavailable."""

    class NotFound(Exception):
        """Fallback not-found exception when the SDK is unavailable."""


_CONTAINER_NAME_PATTERN = re.compile(r"^drone-(\d+)$")
_ACTIVE_OPERATION_STATUSES = {"accepted", "running"}
_DEFAULT_LOG_LIMIT = 200
_DEFAULT_HISTORY_LIMIT = 20


def _now_ms() -> int:
    return int(time.time() * 1000)


def _env_flag(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _env_map(env_list: list[str] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in env_list or []:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        env[key] = value
    return env


class SitlControlService:
    """Docker-backed SITL inventory and lifecycle control used by the dashboard and tooling."""

    def __init__(
        self,
        params: Any,
        *,
        docker_socket_path: str = "/var/run/docker.sock",
        client_factory: Callable[[], Any] | None = None,
        repo_root: str | None = None,
    ) -> None:
        self.params = params
        self.docker_socket_path = docker_socket_path
        self._client_factory = client_factory or self._default_client_factory
        self.repo_root = repo_root or str(Path(__file__).resolve().parents[1])
        self._operations: dict[str, SitlControlOperationResponse] = {}
        self._operations_lock = threading.Lock()

    def build_policy(self) -> SitlControlPolicyResponse:
        docker_state = self._get_docker_state()
        return SitlControlPolicyResponse(
            sim_mode=bool(getattr(self.params, "sim_mode", False)),
            read_only=False,
            docs_path="docs/guides/sitl-validation-platform.md",
            features=SitlControlFeatureFlags(
                lifecycle_mutations=True,
                operations=True,
                browser_terminal=False,
            ),
            defaults=SitlControlPolicyDefaults(
                default_image=os.environ.get("MDS_DOCKER_IMAGE", "mavsdk-drone-show-sitl:latest"),
                default_network_name=os.environ.get("MDS_SITL_DOCKER_NETWORK", "drone-network"),
                default_git_sync=_env_flag(os.environ.get("MDS_SITL_GIT_SYNC"), True),
                default_requirements_sync=_env_flag(os.environ.get("MDS_SITL_REQUIREMENTS_SYNC"), True),
                default_log_tail_lines=_DEFAULT_LOG_LIMIT,
            ),
            docker=docker_state,
            timestamp=_now_ms(),
        )

    def build_host_summary(self) -> SitlControlHostResponse:
        docker_state = self._get_docker_state()
        disk_path = self.repo_root if os.path.exists(self.repo_root) else "/"
        disk_usage = psutil.disk_usage(disk_path) if psutil is not None else shutil.disk_usage(disk_path)
        memory_total, memory_available = self._memory_snapshot()
        load_avg = os.getloadavg() if hasattr(os, "getloadavg") else None

        return SitlControlHostResponse(
            host=SitlControlHostSummary(
                hostname=platform.node(),
                platform=platform.system(),
                platform_release=platform.release(),
                architecture=platform.machine(),
                python_version=sys.version.split()[0],
                cpu_count_logical=self._cpu_count(),
                memory_total_bytes=memory_total,
                memory_available_bytes=memory_available,
                disk_path=disk_path,
                disk_total_bytes=int(disk_usage.total),
                disk_free_bytes=int(disk_usage.free),
                load_avg_1m=float(load_avg[0]) if load_avg else None,
                load_avg_5m=float(load_avg[1]) if load_avg else None,
                load_avg_15m=float(load_avg[2]) if load_avg else None,
                docker=docker_state,
            ),
            timestamp=_now_ms(),
        )

    def list_images(self) -> SitlControlImageListResponse:
        client, docker_state = self._get_client()
        if client is None:
            return SitlControlImageListResponse(images=[], total_images=0, docker=docker_state, timestamp=_now_ms())

        try:
            instances = self._list_relevant_containers(client)
            in_use_counts: dict[str, int] = {}
            for container in instances:
                image_id = str((container.attrs.get("Image") or container.image.id or "")).strip()
                if image_id:
                    in_use_counts[image_id] = in_use_counts.get(image_id, 0) + 1

            images: list[SitlControlImageSummary] = []
            for image in self._list_relevant_images(client, instances):
                labels = {str(key): str(value) for key, value in (image.labels or {}).items()}
                repo_tags = sorted(str(tag) for tag in (image.tags or []))
                primary_tag = repo_tags[0] if repo_tags else None
                repo = labels.get("mds.sitl.image.repo")
                version_tag = labels.get("mds.sitl.image.version")
                if primary_tag and not repo and ":" in primary_tag:
                    repo, version_tag = primary_tag.rsplit(":", 1)

                images.append(
                    SitlControlImageSummary(
                        image_id=str(image.id),
                        primary_tag=primary_tag,
                        repo_tags=repo_tags,
                        size_bytes=int(image.attrs.get("Size") or 0),
                        created_at=image.attrs.get("Created"),
                        repo=repo,
                        version_tag=version_tag,
                        branch=labels.get("mds.sitl.image.branch"),
                        commit=labels.get("mds.sitl.image.commit"),
                        prepared_from=labels.get("mds.sitl.image.prepared_from"),
                        in_use_by_instances=in_use_counts.get(str(image.id), 0),
                        labels=labels,
                    )
                )

            images.sort(key=lambda item: (item.primary_tag or "", item.created_at or ""), reverse=True)
            return SitlControlImageListResponse(
                images=images,
                total_images=len(images),
                docker=docker_state,
                timestamp=_now_ms(),
            )
        finally:
            self._close_client(client)

    def list_instances(self) -> SitlControlInstanceListResponse:
        client, docker_state = self._get_client()
        if client is None:
            return SitlControlInstanceListResponse(instances=[], total_instances=0, docker=docker_state, timestamp=_now_ms())

        try:
            instances = [self._summarize_container(container) for container in self._list_relevant_containers(client)]
            instances.sort(
                key=lambda item: (
                    item.pos_id_hint if item.pos_id_hint is not None else 10**9,
                    item.hw_id or "",
                    item.name,
                )
            )
            return SitlControlInstanceListResponse(
                instances=instances,
                total_instances=len(instances),
                docker=docker_state,
                timestamp=_now_ms(),
            )
        finally:
            self._close_client(client)

    def get_instance_logs(self, instance_name: str, *, tail_lines: int = _DEFAULT_LOG_LIMIT) -> SitlControlInstanceLogResponse:
        client, docker_state = self._get_client()
        if client is None:
            return SitlControlInstanceLogResponse(
                instance_name=str(instance_name),
                tail_lines=int(tail_lines),
                lines=[],
                source=None,
                docker=docker_state,
                timestamp=_now_ms(),
            )

        try:
            try:
                container = client.containers.get(str(instance_name))
            except (NotFound, KeyError) as exc:
                raise KeyError(f"SITL container {instance_name} not found") from exc

            if not self._is_relevant_container(container):
                raise KeyError(f"SITL container {instance_name} not found")

            env = _env_map((((container.attrs or {}).get("Config") or {}).get("Env") or []))
            raw_logs = container.logs(
                stdout=True,
                stderr=True,
                timestamps=True,
                tail=int(tail_lines),
            )
            content = raw_logs.decode("utf-8", errors="replace") if isinstance(raw_logs, (bytes, bytearray)) else str(raw_logs)
            lines = [line for line in content.splitlines() if line]
            source = "docker" if lines else None
            if not lines:
                source, lines = self._read_fallback_instance_logs(container, env, tail_lines=int(tail_lines))
            return SitlControlInstanceLogResponse(
                instance_name=str(instance_name),
                tail_lines=int(tail_lines),
                lines=lines,
                source=source,
                docker=docker_state,
                timestamp=_now_ms(),
            )
        finally:
            self._close_client(client)

    def list_operations(self, *, limit: int = _DEFAULT_HISTORY_LIMIT) -> SitlControlOperationListResponse:
        with self._operations_lock:
            all_operations = sorted(self._operations.values(), key=lambda item: item.created_at, reverse=True)
            operations = list(all_operations)
            if limit > 0:
                operations = operations[: int(limit)]
            active_operations = sum(1 for item in self._operations.values() if item.status in _ACTIVE_OPERATION_STATUSES)

        return SitlControlOperationListResponse(
            operations=operations,
            total_operations=len(all_operations),
            active_operations=active_operations,
            timestamp=_now_ms(),
        )

    def get_operation(self, operation_id: str) -> SitlControlOperationResponse | None:
        with self._operations_lock:
            return self._operations.get(str(operation_id))

    def start_reconcile(self, request: SitlControlReconcileRequest) -> SitlControlOperationResponse:
        self._ensure_mutation_allowed()
        operation = self._create_operation(
            operation_type="reconcile_fleet",
            summary=f"Reconciling SITL fleet to {request.target_count} instance(s)",
            detail="Launching the canonical Docker SITL bootstrap and waiting for readiness.",
            affected_instances=[f"drone-{drone_id}" for drone_id in self._desired_drone_ids(request)],
            metadata=request.model_dump(mode="json"),
        )
        self._launch_background_operation(
            target=self._run_reconcile_operation,
            name=f"sitl-reconcile-{operation.operation_id[:8]}",
            args=(operation.operation_id, request),
        )
        return operation

    def restart_instance(self, instance_name: str) -> SitlControlOperationResponse:
        self._ensure_mutation_allowed()
        operation = self._create_operation(
            operation_type="restart_instance",
            summary=f"Restarting {instance_name}",
            detail="Restarting the selected SITL container and waiting for Docker to report it healthy again.",
            affected_instances=[str(instance_name)],
        )
        self._launch_background_operation(
            target=self._run_instance_action,
            name=f"sitl-restart-{operation.operation_id[:8]}",
            args=(operation.operation_id, str(instance_name), "restart"),
        )
        return operation

    def remove_instance(self, instance_name: str) -> SitlControlOperationResponse:
        self._ensure_mutation_allowed()
        operation = self._create_operation(
            operation_type="remove_instance",
            summary=f"Removing {instance_name}",
            detail="Stopping and removing the selected SITL container with force cleanup.",
            affected_instances=[str(instance_name)],
        )
        self._launch_background_operation(
            target=self._run_instance_action,
            name=f"sitl-remove-{operation.operation_id[:8]}",
            args=(operation.operation_id, str(instance_name), "remove"),
        )
        return operation

    def _default_client_factory(self):
        if docker is None:
            raise DockerException("python docker SDK is not installed")
        return docker.from_env()

    @staticmethod
    def _cpu_count() -> int:
        if psutil is not None:
            return psutil.cpu_count(logical=True) or 0
        return os.cpu_count() or 0

    @staticmethod
    def _memory_snapshot() -> tuple[int, int]:
        if psutil is not None:
            memory = psutil.virtual_memory()
            return int(memory.total), int(memory.available)
        return 0, 0

    def _get_docker_state(self) -> SitlControlDockerState:
        socket_exists = os.path.exists(self.docker_socket_path)
        if docker is None:
            return SitlControlDockerState(
                available=False,
                socket_path=self.docker_socket_path,
                socket_exists=socket_exists,
                daemon_reachable=False,
                error="python docker SDK is not installed",
            )

        try:
            client = self._client_factory()
            try:
                client.ping()
                version = client.version() or {}
            finally:
                try:
                    client.close()
                except Exception:
                    pass
        except Exception as exc:
            return SitlControlDockerState(
                available=socket_exists,
                socket_path=self.docker_socket_path,
                socket_exists=socket_exists,
                daemon_reachable=False,
                error=str(exc),
            )

        return SitlControlDockerState(
            available=True,
            socket_path=self.docker_socket_path,
            socket_exists=socket_exists,
            daemon_reachable=True,
            server_version=str(version.get("Version") or ""),
            api_version=str(version.get("ApiVersion") or ""),
            error=None,
        )

    def _get_client(self) -> tuple[Any | None, SitlControlDockerState]:
        socket_exists = os.path.exists(self.docker_socket_path)
        if docker is None:
            state = SitlControlDockerState(
                available=False,
                socket_path=self.docker_socket_path,
                socket_exists=socket_exists,
                daemon_reachable=False,
                error="python docker SDK is not installed",
            )
            return None, state

        try:
            client = self._client_factory()
            client.ping()
            version = client.version() or {}
        except Exception as exc:
            state = SitlControlDockerState(
                available=socket_exists,
                socket_path=self.docker_socket_path,
                socket_exists=socket_exists,
                daemon_reachable=False,
                error=str(exc),
            )
            return None, state

        state = SitlControlDockerState(
            available=True,
            socket_path=self.docker_socket_path,
            socket_exists=socket_exists,
            daemon_reachable=True,
            server_version=str(version.get("Version") or ""),
            api_version=str(version.get("ApiVersion") or ""),
            error=None,
        )
        return client, state

    def _list_relevant_containers(self, client: Any) -> list[Any]:
        return [container for container in client.containers.list(all=True) if self._is_relevant_container(container)]

    def _list_relevant_images(self, client: Any, containers: list[Any]) -> list[Any]:
        images = list(client.images.list())
        used_image_ids = {
            str((container.attrs.get("Image") or container.image.id or "")).strip()
            for container in containers
            if str((container.attrs.get("Image") or container.image.id or "")).strip()
        }
        relevant = []
        for image in images:
            if self._is_relevant_image(image) or str(image.id) in used_image_ids:
                relevant.append(image)
        return relevant

    def _is_relevant_image(self, image: Any) -> bool:
        labels = image.labels or {}
        if "mds.sitl.image.repo" in labels:
            return True
        for tag in image.tags or []:
            if "sitl" in str(tag).lower() and ("mds" in str(tag).lower() or "mavsdk-drone-show" in str(tag).lower()):
                return True
        return False

    def _is_relevant_container(self, container: Any) -> bool:
        name = str(getattr(container, "name", "") or "")
        attrs = getattr(container, "attrs", {}) or {}
        env = _env_map(((attrs.get("Config") or {}).get("Env") or []))
        image_tags = [str(tag) for tag in ((getattr(container, "image", None) and container.image.tags) or [])]

        if _CONTAINER_NAME_PATTERN.match(name):
            if "MDS_BASE_DIR" in env or "MDS_BRANCH" in env or "MDS_REPO_URL" in env:
                return True
            if image_tags and any("sitl" in tag.lower() for tag in image_tags):
                return True

        image_labels = (((attrs.get("Config") or {}).get("Labels") or {}))
        return "mds.sitl.image.repo" in image_labels

    def _summarize_container(self, container: Any) -> SitlControlInstanceSummary:
        attrs = getattr(container, "attrs", {}) or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        host_config = attrs.get("HostConfig") or {}
        env = _env_map(config.get("Env") or [])
        ip_addresses = {
            network_name: str((network or {}).get("IPAddress") or "")
            for network_name, network in ((attrs.get("NetworkSettings") or {}).get("Networks") or {}).items()
            if str((network or {}).get("IPAddress") or "").strip()
        }

        hw_id = self._derive_hw_id(container.name, env)
        pos_id_hint = int(hw_id) if hw_id and hw_id.isdigit() else None
        image_ref = None
        if getattr(container, "image", None) is not None and container.image.tags:
            image_ref = str(container.image.tags[0])

        return SitlControlInstanceSummary(
            container_id=str(getattr(container, "short_id", None) or getattr(container, "id", "")),
            name=str(container.name),
            image_ref=image_ref,
            image_id=str((attrs.get("Image") or getattr(getattr(container, "image", None), "id", ""))),
            status=str(getattr(container, "status", "") or state.get("Status") or "unknown"),
            state=str(state.get("Status") or getattr(container, "status", "") or "unknown"),
            created_at=attrs.get("Created"),
            started_at=state.get("StartedAt"),
            finished_at=state.get("FinishedAt"),
            restart_policy=(host_config.get("RestartPolicy") or {}).get("Name"),
            health_status=((state.get("Health") or {}).get("Status")),
            hw_id=hw_id,
            pos_id_hint=pos_id_hint,
            git_repo_url=env.get("MDS_REPO_URL"),
            git_branch=env.get("MDS_BRANCH"),
            git_sync_enabled=_env_flag(env.get("MDS_SITL_GIT_SYNC"), True) if "MDS_SITL_GIT_SYNC" in env else None,
            requirements_sync_enabled=(
                _env_flag(env.get("MDS_SITL_REQUIREMENTS_SYNC"), True)
                if "MDS_SITL_REQUIREMENTS_SYNC" in env
                else None
            ),
            ip_addresses=ip_addresses,
        )

    @staticmethod
    def _derive_hw_id(container_name: str, env: dict[str, str]) -> str | None:
        for key in ("MDS_HW_ID", "MDS_HWID", "HW_ID"):
            value = env.get(key)
            if value:
                return str(value).strip()
        match = _CONTAINER_NAME_PATTERN.match(str(container_name))
        if match:
            return match.group(1)
        return None

    def _ensure_mutation_allowed(self) -> None:
        if not bool(getattr(self.params, "sim_mode", False)):
            raise RuntimeError("SITL lifecycle control is only available when GCS is running in simulation mode")

        docker_state = self._get_docker_state()
        if not docker_state.daemon_reachable:
            raise RuntimeError(docker_state.error or "Docker daemon is not reachable")

    def _desired_drone_ids(self, request: SitlControlReconcileRequest) -> list[int]:
        return list(range(request.start_id, request.start_id + request.target_count))

    def _read_fallback_instance_logs(
        self,
        container: Any,
        env: dict[str, str],
        *,
        tail_lines: int,
    ) -> tuple[str | None, list[str]]:
        base_dir = str(env.get("MDS_BASE_DIR") or "/root/mavsdk_drone_show").strip() or "/root/mavsdk_drone_show"
        candidates = [
            ("startup_sitl.log", f"{base_dir}/logs/startup_sitl.log"),
            ("coordinator.log", f"{base_dir}/logs/coordinator.log"),
            ("sitl_simulation.log", f"{base_dir}/logs/sitl_simulation.log"),
            ("mavlink_router.log", f"{base_dir}/logs/mavlink_router.log"),
        ]
        for source_name, path in candidates:
            lines = self._read_container_file_tail(container, path, tail_lines=tail_lines)
            if lines:
                return source_name, lines
        return None, []

    @staticmethod
    def _read_container_file_tail(container: Any, path: str, *, tail_lines: int) -> list[str]:
        command = [
            "/bin/sh",
            "-lc",
            f"test -f {shlex.quote(path)} && tail -n {int(tail_lines)} {shlex.quote(path)}",
        ]
        try:
            result = container.exec_run(command)
        except Exception:
            return []

        exit_code = getattr(result, "exit_code", None)
        output = getattr(result, "output", b"")
        if exit_code not in (0, None):
            return []
        content = output.decode("utf-8", errors="replace") if isinstance(output, (bytes, bytearray)) else str(output or "")
        return [line for line in content.splitlines() if line]

    def _desired_container_names(self, request: SitlControlReconcileRequest) -> set[str]:
        return {f"drone-{drone_id}" for drone_id in self._desired_drone_ids(request)}

    def _build_reconcile_command(self, request: SitlControlReconcileRequest) -> list[str]:
        command = [
            "bash",
            "multiple_sitl/create_dockers.sh",
            str(request.target_count),
            "--start-id",
            str(request.start_id),
            "--start-ip",
            str(request.start_ip),
        ]
        if request.subnet:
            command.extend(["--subnet", request.subnet])
        return command

    def _build_reconcile_env(self, request: SitlControlReconcileRequest) -> dict[str, str]:
        env = os.environ.copy()
        env["MDS_SITL_GIT_SYNC"] = "true" if request.git_sync_enabled else "false"
        env["MDS_SITL_REQUIREMENTS_SYNC"] = "true" if request.requirements_sync_enabled else "false"
        if request.image_ref:
            env["MDS_DOCKER_IMAGE"] = request.image_ref
        if request.docker_network_name:
            env["MDS_SITL_DOCKER_NETWORK"] = request.docker_network_name
        return env

    def _launch_background_operation(self, *, target: Callable[..., None], name: str, args: tuple[Any, ...]) -> None:
        thread = threading.Thread(target=target, name=name, args=args, daemon=True)
        thread.start()

    def _create_operation(
        self,
        *,
        operation_type: str,
        summary: str,
        detail: str | None = None,
        affected_instances: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SitlControlOperationResponse:
        timestamp = _now_ms()
        operation = SitlControlOperationResponse(
            operation_id=f"sitl-{uuid.uuid4().hex[:12]}",
            operation_type=operation_type,
            status="accepted",
            summary=summary,
            detail=detail,
            affected_instances=list(affected_instances or []),
            metadata=dict(metadata or {}),
            log_lines=[],
            created_at=timestamp,
            updated_at=timestamp,
            completed_at=None,
        )
        with self._operations_lock:
            self._operations[operation.operation_id] = operation
            self._prune_operation_history_locked()
        return operation

    def _update_operation(self, operation_id: str, **updates: Any) -> SitlControlOperationResponse | None:
        with self._operations_lock:
            current = self._operations.get(str(operation_id))
            if current is None:
                return None
            merged = current.model_dump(mode="json")
            merged.update(updates)
            merged["updated_at"] = _now_ms()
            next_operation = SitlControlOperationResponse.model_validate(merged)
            self._operations[operation_id] = next_operation
            return next_operation

    def _append_operation_log(self, operation_id: str, line: str) -> None:
        normalized = str(line).rstrip()
        if not normalized:
            return
        with self._operations_lock:
            current = self._operations.get(str(operation_id))
            if current is None:
                return
            next_lines = list(current.log_lines)
            next_lines.append(normalized)
            next_lines = next_lines[-_DEFAULT_LOG_LIMIT:]
            merged = current.model_dump(mode="json")
            merged["log_lines"] = next_lines
            merged["updated_at"] = _now_ms()
            self._operations[operation_id] = SitlControlOperationResponse.model_validate(merged)

    def _mark_operation_running(self, operation_id: str, *, detail: str | None = None) -> None:
        updates: dict[str, Any] = {"status": "running"}
        if detail is not None:
            updates["detail"] = detail
        self._update_operation(operation_id, **updates)

    def _mark_operation_succeeded(self, operation_id: str, *, summary: str, detail: str | None = None) -> None:
        self._update_operation(
            operation_id,
            status="succeeded",
            summary=summary,
            detail=detail,
            completed_at=_now_ms(),
        )

    def _mark_operation_failed(self, operation_id: str, *, summary: str, detail: str) -> None:
        self._update_operation(
            operation_id,
            status="failed",
            summary=summary,
            detail=detail,
            completed_at=_now_ms(),
        )
        self._append_operation_log(operation_id, f"ERROR: {detail}")

    def _prune_operation_history_locked(self) -> None:
        ordered_ids = sorted(self._operations, key=lambda key: self._operations[key].created_at, reverse=True)
        for operation_id in ordered_ids[_DEFAULT_HISTORY_LIMIT:]:
            self._operations.pop(operation_id, None)

    def _run_reconcile_operation(self, operation_id: str, request: SitlControlReconcileRequest) -> None:
        self._mark_operation_running(operation_id)
        command = self._build_reconcile_command(request)
        env = self._build_reconcile_env(request)
        desired_names = self._desired_container_names(request)

        self._append_operation_log(operation_id, f"Command: {' '.join(command)}")
        if request.image_ref:
            self._append_operation_log(operation_id, f"Image: {request.image_ref}")
        self._append_operation_log(
            operation_id,
            f"Sync flags: git={'on' if request.git_sync_enabled else 'off'}, requirements={'on' if request.requirements_sync_enabled else 'off'}",
        )

        try:
            process = subprocess.Popen(
                command,
                cwd=self.repo_root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except Exception as exc:
            self._mark_operation_failed(
                operation_id,
                summary="SITL reconcile failed",
                detail=f"Failed to launch create_dockers.sh: {exc}",
            )
            return

        try:
            if process.stdout is not None:
                for line in process.stdout:
                    self._append_operation_log(operation_id, line)
            return_code = process.wait()
        except Exception as exc:
            process.kill()
            process.wait()
            self._mark_operation_failed(
                operation_id,
                summary="SITL reconcile failed",
                detail=f"Reconcile process aborted unexpectedly: {exc}",
            )
            return

        if return_code != 0:
            self._mark_operation_failed(
                operation_id,
                summary="SITL reconcile failed",
                detail=f"create_dockers.sh exited with code {return_code}",
            )
            return

        try:
            removed_names = self._remove_unmanaged_instances(desired_names, operation_id=operation_id)
        except Exception as exc:
            self._mark_operation_failed(
                operation_id,
                summary="SITL reconcile incomplete",
                detail=f"Fleet created but extra container cleanup failed: {exc}",
            )
            return

        detail = f"{len(desired_names)} desired container(s) now match the requested fleet."
        if removed_names:
            detail = f"{detail} Removed extras: {', '.join(sorted(removed_names))}."
        self._mark_operation_succeeded(
            operation_id,
            summary=f"SITL fleet reconciled to {len(desired_names)} instance(s)",
            detail=detail,
        )

    def _run_instance_action(self, operation_id: str, instance_name: str, action: str) -> None:
        action = str(action)
        self._mark_operation_running(operation_id)
        client, _docker_state = self._get_client()
        if client is None:
            self._mark_operation_failed(
                operation_id,
                summary=f"SITL {action} failed",
                detail="Docker daemon is unavailable",
            )
            return

        try:
            container = client.containers.get(instance_name)
        except (NotFound, KeyError):
            self._mark_operation_failed(
                operation_id,
                summary=f"SITL {action} failed",
                detail=f"SITL container {instance_name} not found",
            )
            self._close_client(client)
            return

        if not self._is_relevant_container(container):
            self._mark_operation_failed(
                operation_id,
                summary=f"SITL {action} failed",
                detail=f"SITL container {instance_name} not found",
            )
            self._close_client(client)
            return

        try:
            if action == "restart":
                self._append_operation_log(operation_id, f"Restarting {instance_name}")
                container.restart()
                if hasattr(container, "reload"):
                    container.reload()
                self._mark_operation_succeeded(
                    operation_id,
                    summary=f"Restarted {instance_name}",
                    detail="Docker accepted the restart and refreshed the container state.",
                )
            elif action == "remove":
                self._append_operation_log(operation_id, f"Removing {instance_name}")
                container.remove(force=True)
                self._mark_operation_succeeded(
                    operation_id,
                    summary=f"Removed {instance_name}",
                    detail="Container was force-removed from the local SITL fleet.",
                )
            else:
                self._mark_operation_failed(
                    operation_id,
                    summary="Unsupported SITL action",
                    detail=f"Unsupported container action: {action}",
                )
        except Exception as exc:
            self._mark_operation_failed(
                operation_id,
                summary=f"SITL {action} failed",
                detail=str(exc),
            )
        finally:
            self._close_client(client)

    def _remove_unmanaged_instances(self, desired_names: set[str], *, operation_id: str) -> list[str]:
        client, docker_state = self._get_client()
        if client is None:
            raise RuntimeError(docker_state.error or "Docker daemon is unavailable")

        removed_names: list[str] = []
        try:
            for container in sorted(self._list_relevant_containers(client), key=lambda item: item.name):
                if container.name in desired_names:
                    continue
                if not _CONTAINER_NAME_PATTERN.match(str(container.name)):
                    continue
                self._append_operation_log(operation_id, f"Removing extra container {container.name}")
                container.remove(force=True)
                removed_names.append(str(container.name))
        finally:
            self._close_client(client)
        return removed_names

    @staticmethod
    def _close_client(client: Any) -> None:
        try:
            client.close()
        except Exception:
            pass
