from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi import HTTPException
import pytest

from api_routes.sitl_control import create_sitl_control_router
from src.sitl_control_models import (
    SitlControlDockerState,
    SitlControlFeatureFlags,
    SitlControlHostResponse,
    SitlControlHostSummary,
    SitlControlCreateInstanceRequest,
    SitlControlImageReleaseRequest,
    SitlControlImageListResponse,
    SitlControlImageSummary,
    SitlControlInstanceActionRequest,
    SitlControlInstanceListResponse,
    SitlControlInstanceLogResponse,
    SitlControlInstanceSummary,
    SitlControlOperationListResponse,
    SitlControlOperationResponse,
    SitlControlPolicyDefaults,
    SitlControlPolicyResponse,
    SitlControlReconcileRequest,
)


class _FakeSitlControlService:
    def build_policy(self):
        return SitlControlPolicyResponse(
            sim_mode=True,
            read_only=False,
            docs_path="docs/guides/sitl-validation-platform.md",
            features=SitlControlFeatureFlags(lifecycle_mutations=True, operations=True),
            defaults=SitlControlPolicyDefaults(
                default_image="mavsdk-drone-show-sitl:latest",
                default_network_name="drone-network",
                default_git_sync=True,
                default_requirements_sync=True,
                default_log_tail_lines=200,
            ),
            docker=SitlControlDockerState(
                available=True,
                socket_path="/var/run/docker.sock",
                socket_exists=True,
                daemon_reachable=True,
                server_version="28.0.0",
                api_version="1.47",
            ),
            timestamp=123,
        )

    def build_host_summary(self):
        return SitlControlHostResponse(
            host=SitlControlHostSummary(
                hostname="hetzner",
                platform="Linux",
                platform_release="6.8.0",
                architecture="x86_64",
                python_version="3.12.3",
                cpu_count_logical=8,
                memory_total_bytes=1024,
                memory_available_bytes=512,
                disk_path="/tmp",
                disk_total_bytes=4096,
                disk_free_bytes=2048,
                load_avg_1m=0.1,
                load_avg_5m=0.2,
                load_avg_15m=0.3,
                docker=SitlControlDockerState(
                    available=True,
                    socket_path="/var/run/docker.sock",
                    socket_exists=True,
                    daemon_reachable=True,
                    server_version="28.0.0",
                    api_version="1.47",
                ),
            ),
            timestamp=456,
        )

    def list_images(self):
        return SitlControlImageListResponse(
            images=[
                SitlControlImageSummary(
                    image_id="sha256:1",
                    primary_tag="mavsdk-drone-show-sitl:latest",
                    repo_tags=["mavsdk-drone-show-sitl:latest"],
                    size_bytes=100,
                    created_at="2026-04-13T00:00:00Z",
                    repo="mavsdk-drone-show-sitl",
                    version_tag="latest",
                    branch="main-candidate",
                    commit="abc123",
                    in_use_by_instances=1,
                )
            ],
            total_images=1,
            docker=SitlControlDockerState(
                available=True,
                socket_path="/var/run/docker.sock",
                socket_exists=True,
                daemon_reachable=True,
            ),
            timestamp=789,
        )

    def list_instances(self):
        return SitlControlInstanceListResponse(
            instances=[
                SitlControlInstanceSummary(
                    container_id="drone-1-short",
                    name="drone-1",
                    image_ref="mavsdk-drone-show-sitl:latest",
                    image_id="sha256:1",
                    status="running",
                    state="running",
                    hw_id="1",
                    pos_id_hint=1,
                    git_branch="main-candidate",
                    git_sync_enabled=True,
                    requirements_sync_enabled=True,
                    ip_addresses={"drone-network": "172.18.0.2"},
                )
            ],
            total_instances=1,
            docker=SitlControlDockerState(
                available=True,
                socket_path="/var/run/docker.sock",
                socket_exists=True,
                daemon_reachable=True,
            ),
            timestamp=1011,
        )

    def get_instance_logs(self, instance_name: str, *, tail_lines: int = 200):
        if instance_name == "missing":
            raise KeyError("SITL container missing not found")
        return SitlControlInstanceLogResponse(
            instance_name=instance_name,
            tail_lines=tail_lines,
            lines=["boot", "ready"],
            source="docker",
            docker=SitlControlDockerState(
                available=True,
                socket_path="/var/run/docker.sock",
                socket_exists=True,
                daemon_reachable=True,
            ),
            timestamp=1213,
        )

    def list_operations(self, *, limit: int = 20):
        del limit
        return SitlControlOperationListResponse(
            operations=[
                SitlControlOperationResponse(
                    operation_id="sitl-op-1",
                    operation_type="reconcile_fleet",
                    status="running",
                    summary="Reconciling SITL fleet",
                    detail="Waiting for readiness",
                    affected_instances=["drone-1"],
                    metadata={},
                    log_lines=["boot"],
                    created_at=1300,
                    updated_at=1301,
                )
            ],
            total_operations=1,
            active_operations=1,
            timestamp=1302,
        )

    def get_operation(self, operation_id: str):
        if operation_id == "missing":
            return None
        return SitlControlOperationResponse(
            operation_id=operation_id,
            operation_type="reconcile_fleet",
            status="succeeded",
            summary="Done",
            detail="Ready",
            affected_instances=["drone-1"],
            metadata={},
            log_lines=["boot", "ready"],
            created_at=1300,
            updated_at=1305,
            completed_at=1305,
        )

    def start_reconcile(self, request: SitlControlReconcileRequest):
        return SitlControlOperationResponse(
            operation_id="sitl-op-reconcile",
            operation_type="reconcile_fleet",
            status="accepted",
            summary=f"Reconciling to {request.target_count}",
            detail="Queued",
            affected_instances=["drone-1"],
            metadata=request.model_dump(mode="json"),
            log_lines=[],
            created_at=1400,
            updated_at=1400,
        )

    def create_instance(self, request: SitlControlCreateInstanceRequest):
        target = request.instance_id or 2
        return SitlControlOperationResponse(
            operation_id="sitl-op-create",
            operation_type="create_instance",
            status="accepted",
            summary=f"Creating drone-{target}",
            detail="Queued",
            affected_instances=[f"drone-{target}"],
            metadata=request.model_dump(mode="json"),
            log_lines=[],
            created_at=1450,
            updated_at=1450,
        )

    def instance_action(self, request: SitlControlInstanceActionRequest):
        return SitlControlOperationResponse(
            operation_id="sitl-op-batch",
            operation_type=f"{request.action}_instances",
            status="accepted",
            summary=f"{request.action} queued",
            detail="Queued",
            affected_instances=list(request.instance_names),
            metadata=request.model_dump(mode="json"),
            log_lines=[],
            created_at=1475,
            updated_at=1475,
        )

    def release_image(self, request: SitlControlImageReleaseRequest):
        return SitlControlOperationResponse(
            operation_id="sitl-op-image",
            operation_type="release_image",
            status="accepted",
            summary=f"Saving {request.image_repo}:{request.version_tag}",
            detail="Queued",
            affected_instances=[],
            metadata=request.model_dump(mode="json"),
            log_lines=[],
            created_at=1480,
            updated_at=1480,
        )

    def restart_instance(self, instance_name: str):
        return SitlControlOperationResponse(
            operation_id="sitl-op-restart",
            operation_type="restart_instance",
            status="accepted",
            summary=f"Restarting {instance_name}",
            detail="Queued",
            affected_instances=[instance_name],
            metadata={},
            log_lines=[],
            created_at=1500,
            updated_at=1500,
        )

    def remove_instance(self, instance_name: str):
        return SitlControlOperationResponse(
            operation_id="sitl-op-remove",
            operation_type="remove_instance",
            status="accepted",
            summary=f"Removing {instance_name}",
            detail="Queued",
            affected_instances=[instance_name],
            metadata={},
            log_lines=[],
            created_at=1600,
            updated_at=1600,
        )


def _make_deps():
    return SimpleNamespace(
        Params=SimpleNamespace(sim_mode=True),
        sitl_control_service=_FakeSitlControlService(),
        log_system_error=lambda *args, **kwargs: None,
    )


def _resolve_route_endpoint(app: FastAPI, path: str, method: str):
    method = method.upper()
    for route in app.routes:
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"Route {method} {path} not found")


def test_sitl_control_router_registers_expected_routes():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sitl_control_router(deps))

    routes = {route.path for route in app.routes}

    assert "/api/v1/system/sitl/policy" in routes
    assert "/api/v1/system/sitl/host" in routes
    assert "/api/v1/system/sitl/images" in routes
    assert "/api/v1/system/sitl/images/release" in routes
    assert "/api/v1/system/sitl/instances" in routes
    assert "/api/v1/system/sitl/instances/actions" in routes
    assert "/api/v1/system/sitl/instances/{instance_name}/logs" in routes
    assert "/api/v1/system/sitl/reconcile" in routes
    assert "/api/v1/system/sitl/instances/{instance_name}/restart" in routes
    assert "/api/v1/system/sitl/instances/{instance_name}" in routes
    assert "/api/v1/system/sitl/operations" in routes
    assert "/api/v1/system/sitl/operations/{operation_id}" in routes


def test_sitl_control_router_returns_read_only_inventory_payloads():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sitl_control_router(deps))

    policy = asyncio.run(_resolve_route_endpoint(app, "/api/v1/system/sitl/policy", "GET")())
    host = asyncio.run(_resolve_route_endpoint(app, "/api/v1/system/sitl/host", "GET")())
    images = asyncio.run(_resolve_route_endpoint(app, "/api/v1/system/sitl/images", "GET")())
    instances = asyncio.run(_resolve_route_endpoint(app, "/api/v1/system/sitl/instances", "GET")())
    logs = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/instances/{instance_name}/logs", "GET")(
            instance_name="drone-1",
            tail=50,
        )
    )
    create_instance = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/instances", "POST")(
            request=SitlControlCreateInstanceRequest(
                instance_id=5,
                ip_last_octet=6,
                git_sync_enabled=True,
                requirements_sync_enabled=True,
            )
        )
    )
    batch_action = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/instances/actions", "POST")(
            request=SitlControlInstanceActionRequest(
                action="restart",
                instance_names=["drone-1"],
            )
        )
    )
    release_image = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/images/release", "POST")(
            request=SitlControlImageReleaseRequest(
                base_image_ref="mavsdk-drone-show-sitl:latest",
                image_repo="mavsdk-drone-show-sitl",
                version_tag="release-demo",
                tag_latest=True,
                tag_commit=True,
                export_archive=True,
                compress_archive=True,
            )
        )
    )
    operations = asyncio.run(_resolve_route_endpoint(app, "/api/v1/system/sitl/operations", "GET")(limit=20))
    operation = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/operations/{operation_id}", "GET")(operation_id="sitl-op-1")
    )
    reconcile = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/reconcile", "POST")(
            request=SitlControlReconcileRequest(
                target_count=3,
                start_id=1,
                start_ip=2,
                git_sync_enabled=True,
                requirements_sync_enabled=True,
            )
        )
    )
    restart = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/instances/{instance_name}/restart", "POST")(
            instance_name="drone-1"
        )
    )
    remove = asyncio.run(
        _resolve_route_endpoint(app, "/api/v1/system/sitl/instances/{instance_name}", "DELETE")(
            instance_name="drone-1"
        )
    )

    assert policy.read_only is False
    assert host.host.hostname == "hetzner"
    assert images.total_images == 1
    assert instances.instances[0].hw_id == "1"
    assert logs.tail_lines == 50
    assert logs.lines[-1] == "ready"
    assert logs.source == "docker"
    assert create_instance.operation_type == "create_instance"
    assert batch_action.operation_type == "restart_instances"
    assert release_image.operation_type == "release_image"
    assert operations.active_operations == 1
    assert operation.status == "succeeded"
    assert reconcile.operation_type == "reconcile_fleet"
    assert restart.operation_type == "restart_instance"
    assert remove.operation_type == "remove_instance"


def test_sitl_control_router_maps_missing_instance_logs_to_404():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sitl_control_router(deps))

    endpoint = _resolve_route_endpoint(app, "/api/v1/system/sitl/instances/{instance_name}/logs", "GET")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(endpoint(instance_name="missing", tail=200))

    assert exc_info.value.status_code == 404
    assert "missing" in str(exc_info.value.detail)


def test_sitl_control_router_maps_missing_operation_to_404():
    deps = _make_deps()
    app = FastAPI()
    app.include_router(create_sitl_control_router(deps))

    endpoint = _resolve_route_endpoint(app, "/api/v1/system/sitl/operations/{operation_id}", "GET")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(endpoint(operation_id="missing"))

    assert exc_info.value.status_code == 404
    assert "missing" in str(exc_info.value.detail)
