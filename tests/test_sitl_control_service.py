from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_build_policy_and_host_summary_report_live_environment(tmp_path):
    service = _make_service(tmp_path)

    policy = service.build_policy()
    host = service.build_host_summary()

    assert policy.sim_mode is True
    assert policy.read_only is False
    assert policy.features.lifecycle_mutations is True
    assert policy.docker.daemon_reachable is True
    assert host.host.docker.server_version == "28.0.0"
    assert host.host.disk_path == str(tmp_path)
    assert host.host.cpu_count_logical >= 0


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
    assert instances.instances[0].ip_addresses["drone-network"] == "172.18.0.2"


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
