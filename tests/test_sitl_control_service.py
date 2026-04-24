from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.sitl_control_models import (
    SitlControlCreateInstanceRequest,
    SitlControlImageReleaseRequest,
    SitlControlInstanceActionRequest,
    SitlControlReconcileRequest,
)
from src.sitl_control_service import SitlControlService


class _FakeImage:
    def __init__(self, image_id: str, tags: list[str], *, size: int = 0, labels: dict[str, str] | None = None):
        self.id = image_id
        self.tags = list(tags)
        self.labels = dict(labels or {})
        self.attrs = {
            "Size": size,
            "Created": "2026-04-13T00:00:00Z",
        }


class _FakeContainerCollection:
    def __init__(self, containers):
        self._containers = list(containers)

    def list(self, all=False):  # noqa: A002 - docker SDK signature
        return list(self._containers)

    def get(self, name: str):
        for container in self._containers:
            if container.name == name:
                return container
        raise KeyError(name)


class _FakeImageCollection:
    def __init__(self, images):
        self._images = list(images)

    def list(self):
        return list(self._images)


class _FakeClient:
    def __init__(self, containers, images):
        self.containers = _FakeContainerCollection(containers)
        self.images = _FakeImageCollection(images)
        self.closed = False

    def ping(self):
        return True

    def version(self):
        return {"Version": "28.0.0", "ApiVersion": "1.47"}

    def close(self):
        self.closed = True


class _FakeContainer:
    def __init__(
        self,
        *,
        name: str,
        image: _FakeImage,
        env: dict[str, str] | None = None,
        status: str = "running",
        ip: str = "172.18.0.2",
        logs: str = "",
    ):
        self.name = name
        self.id = f"{name}-long-id"
        self.short_id = f"{name[:12]}-short"
        self.image = image
        self.status = status
        self._logs = logs.encode("utf-8")
        self._file_logs = {}
        self.restart_calls = 0
        self.remove_calls = 0
        env_list = [f"{key}={value}" for key, value in (env or {}).items()]
        self.attrs = {
            "Image": image.id,
            "Created": "2026-04-13T00:00:00Z",
            "Config": {
                "Env": env_list,
                "Labels": dict(image.labels),
            },
            "State": {
                "Status": status,
                "StartedAt": "2026-04-13T00:01:00Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Health": {"Status": "healthy"},
            },
            "HostConfig": {
                "RestartPolicy": {"Name": "unless-stopped"},
            },
            "NetworkSettings": {
                "Networks": {
                    "drone-network": {"IPAddress": ip},
                }
            },
        }

    def logs(self, stdout=True, stderr=True, timestamps=True, tail=200):
        del stdout, stderr, timestamps, tail
        return self._logs

    def exec_run(self, command):
        rendered = " ".join(command) if isinstance(command, (list, tuple)) else str(command)
        for path, content in self._file_logs.items():
            if path in rendered:
                return SimpleNamespace(exit_code=0, output=content.encode("utf-8"))
        return SimpleNamespace(exit_code=1, output=b"")

    def restart(self):
        self.restart_calls += 1
        self.status = "running"
        self.attrs["State"]["Status"] = "running"

    def remove(self, force=True):
        del force
        self.remove_calls += 1

    def reload(self):
        return None


def _make_service(tmp_path: Path, containers=None, images=None) -> SitlControlService:
    socket_path = tmp_path / "docker.sock"
    socket_path.write_text("", encoding="utf-8")
    fake_client = _FakeClient(containers or [], images or [])
    params = SimpleNamespace(sim_mode=True)
    return SitlControlService(
        params,
        docker_socket_path=str(socket_path),
        client_factory=lambda: fake_client,
        repo_root=str(tmp_path),
    )


class _ImmediateOperationService(SitlControlService):
    def _launch_background_operation(self, *, target, name, args):
        del name
        target(*args)


def test_build_policy_and_host_summary_report_live_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("MDS_SITL_GIT_SYNC", raising=False)
    monkeypatch.delenv("MDS_SITL_USE_HOST_STARTUP_SCRIPT", raising=False)
    service = _make_service(tmp_path)

    policy = service.build_policy()
    host = service.build_host_summary()

    assert policy.sim_mode is True
    assert policy.read_only is False
    assert policy.features.lifecycle_mutations is True
    assert policy.docker.daemon_reachable is True
    assert policy.defaults.default_use_host_startup_script is True
    assert policy.defaults.default_startup_script_source == "host_override"
    assert host.host.docker.server_version == "28.0.0"
    assert host.host.disk_path == str(tmp_path)
    assert host.host.cpu_count_logical >= 0
    assert host.host.portainer_available is False


def test_list_images_and_instances_filter_to_mds_sitl_runtime(tmp_path):
    official = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        size=1024,
        labels={
            "mds.sitl.image.repo": "mavsdk-drone-show-sitl",
            "mds.sitl.image.version": "latest",
            "mds.sitl.image.branch": "main-candidate",
            "mds.sitl.image.commit": "abc1234",
        },
    )
    unrelated = _FakeImage("sha256:other", ["postgres:16"], size=2048)

    drone = _FakeContainer(
        name="drone-2",
        image=official,
        env={
            "MDS_BASE_DIR": "/root/mavsdk_drone_show",
            "MDS_BRANCH": "main-candidate",
            "MDS_REPO_URL": "https://github.com/alireza787b/mavsdk_drone_show.git",
            "MDS_SITL_GIT_SYNC": "true",
            "MDS_SITL_REQUIREMENTS_SYNC": "false",
            "MDS_SITL_USE_HOST_STARTUP_SCRIPT": "true",
        },
        logs="2026-04-13T01:00:00Z boot ok\n2026-04-13T01:00:02Z ready",
    )
    unrelated_container = _FakeContainer(name="db", image=unrelated, env={}, ip="172.18.0.50")

    service = _make_service(tmp_path, containers=[drone, unrelated_container], images=[official, unrelated])

    images = service.list_images()
    instances = service.list_instances()

    assert images.total_images == 1
    assert images.images[0].repo == "mavsdk-drone-show-sitl"
    assert images.images[0].commit == "abc1234"
    assert images.images[0].in_use_by_instances == 1

    assert instances.total_instances == 1
    assert instances.instances[0].name == "drone-2"
    assert instances.instances[0].hw_id == "2"
    assert instances.instances[0].pos_id_hint == 2
    assert instances.instances[0].git_sync_enabled is True
    assert instances.instances[0].requirements_sync_enabled is False
    assert instances.instances[0].startup_script_source == "host_override"
    assert instances.instances[0].ip_addresses["drone-network"] == "172.18.0.2"


def test_build_policy_uses_baked_startup_script_when_git_sync_is_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_SITL_GIT_SYNC", "false")
    monkeypatch.delenv("MDS_SITL_USE_HOST_STARTUP_SCRIPT", raising=False)
    service = _make_service(tmp_path)

    policy = service.build_policy()

    assert policy.defaults.default_git_sync is False
    assert policy.defaults.default_use_host_startup_script is False
    assert policy.defaults.default_startup_script_source == "image_baked"


def test_build_reconcile_env_defaults_host_startup_script_when_git_sync_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("MDS_SITL_USE_HOST_STARTUP_SCRIPT", raising=False)
    service = _make_service(tmp_path)

    env = service._build_reconcile_env(
        SitlControlReconcileRequest(
            target_count=4,
            start_id=1,
            start_ip=2,
            git_sync_enabled=True,
            requirements_sync_enabled=True,
        )
    )

    assert env["MDS_SITL_USE_HOST_STARTUP_SCRIPT"] == "true"


def test_build_create_env_keeps_explicit_baked_startup_override(tmp_path, monkeypatch):
    monkeypatch.setenv("MDS_SITL_USE_HOST_STARTUP_SCRIPT", "false")
    service = _make_service(tmp_path)

    env = service._build_create_instance_env(
        SitlControlCreateInstanceRequest(
            instance_id=5,
            ip_last_octet=6,
            git_sync_enabled=True,
            requirements_sync_enabled=True,
        )
    )

    assert env["MDS_SITL_USE_HOST_STARTUP_SCRIPT"] == "false"


def test_build_host_summary_detects_running_portainer_panel(tmp_path):
    image = _FakeImage("sha256:portainer", ["portainer/portainer-ce:latest"])
    portainer = _FakeContainer(name="portainer", image=image)
    portainer.attrs["NetworkSettings"]["Ports"] = {
        "9000/tcp": [{"HostPort": "9000"}],
    }
    service = _make_service(tmp_path, containers=[portainer], images=[image])

    host = service.build_host_summary()

    assert host.host.portainer_available is True
    assert host.host.portainer_port == 9000
    assert host.host.portainer_scheme == "http"


def test_get_instance_logs_returns_tailed_content_for_relevant_container(tmp_path):
    image = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        labels={"mds.sitl.image.repo": "mavsdk-drone-show-sitl"},
    )
    drone = _FakeContainer(
        name="drone-1",
        image=image,
        env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"},
        logs="2026-04-13T01:00:00Z boot ok\n2026-04-13T01:00:02Z ready",
    )
    service = _make_service(tmp_path, containers=[drone], images=[image])

    response = service.get_instance_logs("drone-1", tail_lines=100)

    assert response.instance_name == "drone-1"
    assert response.tail_lines == 100
    assert response.lines[-1].endswith("ready")
    assert response.source == "docker"


def test_get_instance_logs_falls_back_to_startup_file_when_docker_logs_are_empty(tmp_path):
    image = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        labels={"mds.sitl.image.repo": "mavsdk-drone-show-sitl"},
    )
    drone = _FakeContainer(
        name="drone-1",
        image=image,
        env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"},
        logs="",
    )
    drone._file_logs["/root/mavsdk_drone_show/logs/startup_sitl.log"] = (
        "2026-04-13 00:00:01 - Boot\n"
        "2026-04-13 00:00:02 - Ready\n"
    )
    service = _make_service(tmp_path, containers=[drone], images=[image])

    response = service.get_instance_logs("drone-1", tail_lines=20)

    assert response.source == "startup_sitl.log"
    assert response.lines[-1].endswith("Ready")


def test_get_instance_logs_rejects_unknown_container(tmp_path):
    service = _make_service(tmp_path)

    with pytest.raises(KeyError):
        service.get_instance_logs("drone-9")


def test_restart_instance_operation_completes_immediately_with_test_runner(tmp_path):
    image = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        labels={"mds.sitl.image.repo": "mavsdk-drone-show-sitl"},
    )
    drone = _FakeContainer(name="drone-1", image=image, env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"})
    service = _ImmediateOperationService(
        params=SimpleNamespace(sim_mode=True),
        docker_socket_path=str(tmp_path / "docker.sock"),
        client_factory=lambda: _FakeClient([drone], [image]),
        repo_root=str(tmp_path),
    )
    Path(service.docker_socket_path).write_text("", encoding="utf-8")

    operation = service.restart_instance("drone-1")

    assert operation.operation_type == "restart_instance"
    result = service.get_operation(operation.operation_id)
    assert result is not None
    assert result.status == "succeeded"
    assert drone.restart_calls == 1


def test_remove_instance_operation_completes_immediately_with_test_runner(tmp_path):
    image = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        labels={"mds.sitl.image.repo": "mavsdk-drone-show-sitl"},
    )
    drone = _FakeContainer(name="drone-1", image=image, env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"})
    service = _ImmediateOperationService(
        params=SimpleNamespace(sim_mode=True),
        docker_socket_path=str(tmp_path / "docker.sock"),
        client_factory=lambda: _FakeClient([drone], [image]),
        repo_root=str(tmp_path),
    )
    Path(service.docker_socket_path).write_text("", encoding="utf-8")

    operation = service.remove_instance("drone-1")

    result = service.get_operation(operation.operation_id)
    assert result is not None
    assert result.status == "succeeded"
    assert drone.remove_calls == 1


def test_create_instance_operation_uses_next_available_id_and_ip(tmp_path):
    image = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        labels={"mds.sitl.image.repo": "mavsdk-drone-show-sitl"},
    )
    drone1 = _FakeContainer(name="drone-1", image=image, env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"}, ip="172.18.0.2")
    drone3 = _FakeContainer(name="drone-3", image=image, env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"}, ip="172.18.0.4")
    service = _make_service(tmp_path, containers=[drone1, drone3], images=[image])

    assert service._resolve_create_instance_id(SimpleNamespace(instance_id=None)) == 4
    assert service._resolve_create_instance_ip(SimpleNamespace(ip_last_octet=None), 4) == 5


def test_instance_batch_action_restarts_requested_visible_containers(tmp_path):
    image = _FakeImage(
        "sha256:official",
        ["mavsdk-drone-show-sitl:latest"],
        labels={"mds.sitl.image.repo": "mavsdk-drone-show-sitl"},
    )
    drone1 = _FakeContainer(name="drone-1", image=image, env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"})
    drone2 = _FakeContainer(name="drone-2", image=image, env={"MDS_BASE_DIR": "/root/mavsdk_drone_show"})
    service = _ImmediateOperationService(
        params=SimpleNamespace(sim_mode=True),
        docker_socket_path=str(tmp_path / "docker.sock"),
        client_factory=lambda: _FakeClient([drone1, drone2], [image]),
        repo_root=str(tmp_path),
    )
    Path(service.docker_socket_path).write_text("", encoding="utf-8")

    operation = service.instance_action(
        SitlControlInstanceActionRequest(action="restart", instance_names=["drone-1", "drone-2"])
    )

    result = service.get_operation(operation.operation_id)
    assert result is not None
    assert result.status == "succeeded"
    assert result.summary == "Restarted 2 instance(s)"
    assert drone1.restart_calls == 1
    assert drone2.restart_calls == 1


def test_build_image_release_command_includes_selected_flags(tmp_path):
    service = _make_service(tmp_path)

    command = service._build_image_release_command(
        SitlControlImageReleaseRequest(
            base_image_ref="mavsdk-drone-show-sitl:latest",
            image_repo="mavsdk-drone-show-sitl",
            version_tag="release-demo",
            repo_url="https://github.com/alireza787b/mavsdk_drone_show.git",
            branch="main-candidate",
            tag_latest=False,
            tag_commit=True,
            export_archive=True,
            archive_basename="demo-image",
            output_dir="/tmp/releases",
            compress_archive=False,
        )
    )

    assert command[:4] == ["bash", "tools/release_sitl_image.sh", "--base-image", "mavsdk-drone-show-sitl:latest"]
    assert "--repo-url" in command
    assert "--branch" in command
    assert "--no-tag-latest" in command
    assert "--no-tag-commit" not in command
    assert "--package" in command
    assert "--output-dir" in command
    assert "--archive-basename" in command
    assert "--no-compress" in command
