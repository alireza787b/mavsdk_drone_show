"""Tests for typed runtime settings helpers."""

from __future__ import annotations

import importlib

from src.settings.deployment_profile import load_deployment_profile
from src.settings.identity import resolve_hw_id_info
from src.settings.runtime import resolve_runtime_mode


def test_resolve_runtime_mode_prefers_mds_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_MODE", "real")
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(tmp_path / "missing.env"))

    result = resolve_runtime_mode()

    assert result.mode == "real"
    assert result.sim_mode is False
    assert result.source == "env:MDS_MODE"


def test_resolve_runtime_mode_defaults_to_sitl_when_env_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_MODE", raising=False)
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(tmp_path / "missing.env"))

    result = resolve_runtime_mode()

    assert result.mode == "sitl"
    assert result.sim_mode is True
    assert result.source == "default:sitl"


def test_resolve_runtime_mode_ignores_legacy_marker_when_env_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_MODE", raising=False)
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(tmp_path / "missing.env"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "real.mode").write_text("", encoding="utf-8")

    result = resolve_runtime_mode()

    assert result.mode == "sitl"
    assert result.source == "default:sitl"


def test_resolve_runtime_mode_reads_canonical_mode_from_local_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_MODE", raising=False)
    local_env = tmp_path / "local.env"
    local_env.write_text("MDS_MODE=real\n", encoding="utf-8")
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(local_env))

    result = resolve_runtime_mode()

    assert result.mode == "real"
    assert result.sim_mode is False
    assert result.source == "env:MDS_MODE"


def test_resolve_hw_id_info_prefers_node_identity_manifest(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_HW_ID", raising=False)
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(tmp_path / "missing.env"))
    identity_file = tmp_path / "node_identity.json"
    identity_file.write_text('{"hw_id": 44, "node_uuid": "node-1"}', encoding="utf-8")
    monkeypatch.setenv("MDS_NODE_IDENTITY_FILE", str(identity_file))

    result = resolve_hw_id_info()

    assert result.hw_id == 44
    assert result.source == "file:node_identity"
    assert result.node_uuid == "node-1"


def test_resolve_hw_id_info_reads_mds_hw_id_from_local_env(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_HW_ID", raising=False)
    local_env = tmp_path / "local.env"
    local_env.write_text("MDS_HW_ID=71\n", encoding="utf-8")
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(local_env))
    monkeypatch.setenv("MDS_NODE_IDENTITY_FILE", str(tmp_path / "missing-identity.json"))

    result = resolve_hw_id_info()

    assert result.hw_id == 71
    assert result.source == "env:MDS_HW_ID"


def test_preloaded_local_env_does_not_leak_injected_values_across_paths(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_HW_ID", raising=False)
    monkeypatch.delenv("MDS_MODE", raising=False)
    monkeypatch.setenv("MDS_NODE_IDENTITY_FILE", str(tmp_path / "missing-identity.json"))

    first_env = tmp_path / "first.env"
    first_env.write_text("MDS_HW_ID=71\nMDS_MODE=real\n", encoding="utf-8")
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(first_env))
    first_result = resolve_hw_id_info()
    assert first_result.hw_id == 71

    second_env = tmp_path / "second.env"
    second_env.write_text("", encoding="utf-8")
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(second_env))

    second_result = resolve_hw_id_info()
    assert second_result.hw_id is None
    assert second_result.source == "missing"


def test_resolve_runtime_mode_invalid_env_defaults_to_sitl(monkeypatch, tmp_path):
    monkeypatch.setenv("MDS_MODE", "unexpected")
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(tmp_path / "missing.env"))

    result = resolve_runtime_mode()

    assert result.mode == "sitl"
    assert result.source == "default:sitl"


def test_load_deployment_profile_reads_git_tracked_defaults(monkeypatch, tmp_path):
    profile_file = tmp_path / "deployment.env"
    profile_file.write_text(
        "\n".join(
            [
                "MDS_DEFAULT_PROFILE_ID=customer-alpha",
                "MDS_DEFAULT_REPO_SLUG=demo/customer-mds",
                "MDS_DEFAULT_REPO_URL_HTTPS=https://github.com/demo/customer-mds.git",
                "MDS_DEFAULT_REPO_URL_SSH=git@github.com:demo/customer-mds.git",
                "MDS_DEFAULT_BRANCH=release-candidate",
                "MDS_DEFAULT_REAL_GCS_IP=10.0.0.55",
                "MDS_DEFAULT_SITL_GCS_IP=172.30.0.1",
                "MDS_DEFAULT_GCS_API_PORT=5050",
                "MDS_DEFAULT_DASHBOARD_PORT=3035",
                "MDS_DEFAULT_DRONE_API_PORT=7075",
                "MDS_DEFAULT_DOCKER_IMAGE=customer-mds-sitl:latest",
                "MDS_DEFAULT_CONNECTIVITY_BACKEND=smart-wifi-manager",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS=https://github.com/demo/smart-wifi-manager.git",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_REF=v1.2.3",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_MODE=fleet-merge",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_IMPORT_MODE=merge",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_INSTALL_DIR=/opt/demo-smartwifi",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_DASHBOARD_LISTEN=0.0.0.0:9080",
                "MDS_DEFAULT_SMART_WIFI_MANAGER_PROFILE_PATH=deployment/connectivity/demo/profile.json",
                "MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE=fleet-merge",
                "MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS=https://github.com/demo/mavlink-anywhere.git",
                "MDS_DEFAULT_MAVLINK_ANYWHERE_REF=v9.9.9",
                "MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR=/opt/demo-mavlink",
                "MDS_DEFAULT_MAVLINK_ANYWHERE_DASHBOARD_LISTEN=0.0.0.0:9070",
                "MDS_DEFAULT_MAVLINK_ANYWHERE_SKIP_DASHBOARD=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MDS_DEPLOYMENT_PROFILE_FILE", str(profile_file))

    profile = load_deployment_profile()

    assert profile.profile_id == "customer-alpha"
    assert profile.repo_owner == "demo"
    assert profile.repo_url_https == "https://github.com/demo/customer-mds.git"
    assert profile.repo_url_ssh == "git@github.com:demo/customer-mds.git"
    assert profile.branch == "release-candidate"
    assert profile.real_gcs_ip == "10.0.0.55"
    assert profile.sitl_gcs_ip == "172.30.0.1"
    assert profile.gcs_api_port == 5050
    assert profile.dashboard_port == 3035
    assert profile.drone_api_port == 7075
    assert profile.docker_image == "customer-mds-sitl:latest"
    assert profile.connectivity_backend == "smart-wifi-manager"
    assert profile.smart_wifi_manager_repo_url_https == "https://github.com/demo/smart-wifi-manager.git"
    assert profile.smart_wifi_manager_ref == "v1.2.3"
    assert profile.smart_wifi_manager_mode == "fleet-merge"
    assert profile.smart_wifi_manager_import_mode == "merge"
    assert profile.smart_wifi_manager_install_dir == "/opt/demo-smartwifi"
    assert profile.smart_wifi_manager_dashboard_listen == "0.0.0.0:9080"
    assert profile.smart_wifi_manager_profile_path == "deployment/connectivity/demo/profile.json"
    assert profile.mavlink_management_mode == "fleet-merge"
    assert profile.mavlink_anywhere_repo_url_https == "https://github.com/demo/mavlink-anywhere.git"
    assert profile.mavlink_anywhere_ref == "v9.9.9"
    assert profile.mavlink_anywhere_install_dir == "/opt/demo-mavlink"
    assert profile.mavlink_anywhere_dashboard_listen == "0.0.0.0:9070"
    assert profile.mavlink_anywhere_skip_dashboard is True


def test_params_use_deployment_profile_defaults_when_runtime_env_is_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("MDS_REPO_URL", raising=False)
    monkeypatch.delenv("MDS_BRANCH", raising=False)
    monkeypatch.delenv("MDS_GCS_IP", raising=False)
    monkeypatch.delenv("MDS_GCS_API_PORT", raising=False)
    monkeypatch.delenv("MDS_MODE", raising=False)
    monkeypatch.setenv("MDS_LOCAL_ENV_FILE", str(tmp_path / "missing-local.env"))

    profile_file = tmp_path / "deployment.env"
    profile_file.write_text(
        "\n".join(
            [
                "MDS_DEFAULT_REPO_SLUG=demo/customer-mds",
                "MDS_DEFAULT_REPO_URL_HTTPS=https://github.com/demo/customer-mds.git",
                "MDS_DEFAULT_REPO_URL_SSH=git@github.com:demo/customer-mds.git",
                "MDS_DEFAULT_BRANCH=release-candidate",
                "MDS_DEFAULT_REAL_GCS_IP=10.0.0.55",
                "MDS_DEFAULT_SITL_GCS_IP=172.30.0.1",
                "MDS_DEFAULT_GCS_API_PORT=5050",
                "MDS_DEFAULT_DRONE_API_PORT=7075",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MDS_DEPLOYMENT_PROFILE_FILE", str(profile_file))

    import src.params as params_module

    params_module = importlib.reload(params_module)

    assert params_module.Params.GIT_REPO_URL == "git@github.com:demo/customer-mds.git"
    assert params_module.Params.GIT_BRANCH == "release-candidate"
    assert params_module.Params.GCS_IP == "172.30.0.1"
    assert params_module.Params.gcs_api_port == 5050
    assert params_module.Params.drone_api_port == 7075
