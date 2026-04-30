"""Git-tracked deployment profile defaults."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from src.settings.env_files import read_env_assignments

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DEPLOYMENT_PROFILE_PATH = REPO_ROOT / "deployment" / "defaults.env"

_DEPLOYMENT_PROFILE_CACHE: dict[Path, "DeploymentProfile"] = {}


@dataclass(frozen=True)
class DeploymentProfile:
    profile_id: str
    repo_slug: str
    repo_url_https: str
    repo_url_ssh: str
    branch: str
    real_gcs_ip: str
    sitl_gcs_ip: str
    gcs_api_port: int
    dashboard_port: int
    drone_api_port: int
    docker_image: str
    connectivity_backend: str
    smart_wifi_manager_repo_url_https: str
    smart_wifi_manager_ref: str
    smart_wifi_manager_mode: str
    smart_wifi_manager_import_mode: str
    smart_wifi_manager_install_dir: str
    smart_wifi_manager_dashboard_listen: str
    smart_wifi_manager_profile_path: str
    mavlink_management_mode: str
    mavlink_anywhere_repo_url_https: str
    mavlink_anywhere_ref: str
    mavlink_anywhere_install_dir: str
    mavlink_anywhere_dashboard_listen: str
    mavlink_anywhere_skip_dashboard: bool
    source: str

    @property
    def repo_owner(self) -> str:
        if "/" in self.repo_slug:
            return self.repo_slug.split("/", 1)[0]
        return self.repo_slug

    def gcs_ip_for_mode(self, mode: str) -> str:
        normalized = (mode or "").strip().lower()
        if normalized == "sitl":
            return self.sitl_gcs_ip
        return self.real_gcs_ip


def get_deployment_profile_path() -> Path:
    return Path(os.environ.get("MDS_DEPLOYMENT_PROFILE_FILE", str(DEFAULT_DEPLOYMENT_PROFILE_PATH)))


def _parse_env_profile(path: Path) -> dict[str, str]:
    return read_env_assignments(path)


def _parse_int(data: dict[str, str], key: str, default: int, path: Path) -> int:
    try:
        return int(data.get(key, str(default)))
    except ValueError:
        logger.warning("Invalid %s=%r in %s; using %s", key, data.get(key), path, default)
        return default


def _build_profile(path: Path) -> DeploymentProfile:
    data: dict[str, str] = {}
    source = "default"
    if path.exists():
        try:
            data = _parse_env_profile(path)
            source = f"file:{path}"
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.warning("Failed to parse deployment profile %s: %s", path, exc)

    repo_slug = data.get("MDS_DEFAULT_REPO_SLUG", "alireza787b/mavsdk_drone_show")
    repo_url_https = data.get("MDS_DEFAULT_REPO_URL_HTTPS", f"https://github.com/{repo_slug}.git")
    repo_url_ssh = data.get("MDS_DEFAULT_REPO_URL_SSH", f"git@github.com:{repo_slug}.git")
    branch = data.get("MDS_DEFAULT_BRANCH", "main")
    real_gcs_ip = data.get("MDS_DEFAULT_REAL_GCS_IP", "100.96.32.75")
    sitl_gcs_ip = data.get("MDS_DEFAULT_SITL_GCS_IP", "172.18.0.1")

    gcs_api_port = _parse_int(data, "MDS_DEFAULT_GCS_API_PORT", 5030, path)
    dashboard_port = _parse_int(data, "MDS_DEFAULT_DASHBOARD_PORT", 3030, path)
    drone_api_port = _parse_int(data, "MDS_DEFAULT_DRONE_API_PORT", 7070, path)
    docker_image = data.get("MDS_DEFAULT_DOCKER_IMAGE", "mavsdk-drone-show-sitl:latest")

    connectivity_backend = data.get("MDS_DEFAULT_CONNECTIVITY_BACKEND", "none")
    smart_wifi_manager_repo_url_https = data.get(
        "MDS_DEFAULT_SMART_WIFI_MANAGER_REPO_URL_HTTPS",
        "https://github.com/alireza787b/smart-wifi-manager.git",
    )
    smart_wifi_manager_ref = data.get("MDS_DEFAULT_SMART_WIFI_MANAGER_REF", "v2.1.0")
    smart_wifi_manager_mode = data.get("MDS_DEFAULT_SMART_WIFI_MANAGER_MODE", "observe")
    smart_wifi_manager_import_mode = data.get("MDS_DEFAULT_SMART_WIFI_MANAGER_IMPORT_MODE", "replace")
    smart_wifi_manager_install_dir = data.get("MDS_DEFAULT_SMART_WIFI_MANAGER_INSTALL_DIR", "/opt/smart-wifi-manager")
    smart_wifi_manager_dashboard_listen = data.get("MDS_DEFAULT_SMART_WIFI_MANAGER_DASHBOARD_LISTEN", "127.0.0.1:9080")
    smart_wifi_manager_profile_path = data.get(
        "MDS_DEFAULT_SMART_WIFI_MANAGER_PROFILE_PATH",
        "deployment/connectivity/smart-wifi-manager/profile.json",
    )
    mavlink_management_mode = data.get("MDS_DEFAULT_MAVLINK_MANAGEMENT_MODE", "managed")
    mavlink_anywhere_repo_url_https = data.get(
        "MDS_DEFAULT_MAVLINK_ANYWHERE_REPO_URL_HTTPS",
        "https://github.com/alireza787b/mavlink-anywhere.git",
    )
    mavlink_anywhere_ref = data.get("MDS_DEFAULT_MAVLINK_ANYWHERE_REF", "v3.0.8")
    mavlink_anywhere_install_dir = data.get("MDS_DEFAULT_MAVLINK_ANYWHERE_INSTALL_DIR", "/opt/mavlink-anywhere")
    mavlink_anywhere_dashboard_listen = data.get("MDS_DEFAULT_MAVLINK_ANYWHERE_DASHBOARD_LISTEN", "127.0.0.1:9070")
    mavlink_anywhere_skip_dashboard = data.get("MDS_DEFAULT_MAVLINK_ANYWHERE_SKIP_DASHBOARD", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    return DeploymentProfile(
        profile_id=data.get("MDS_DEFAULT_PROFILE_ID", "official-default"),
        repo_slug=repo_slug,
        repo_url_https=repo_url_https,
        repo_url_ssh=repo_url_ssh,
        branch=branch,
        real_gcs_ip=real_gcs_ip,
        sitl_gcs_ip=sitl_gcs_ip,
        gcs_api_port=gcs_api_port,
        dashboard_port=dashboard_port,
        drone_api_port=drone_api_port,
        docker_image=docker_image,
        connectivity_backend=connectivity_backend,
        smart_wifi_manager_repo_url_https=smart_wifi_manager_repo_url_https,
        smart_wifi_manager_ref=smart_wifi_manager_ref,
        smart_wifi_manager_mode=smart_wifi_manager_mode,
        smart_wifi_manager_import_mode=smart_wifi_manager_import_mode,
        smart_wifi_manager_install_dir=smart_wifi_manager_install_dir,
        smart_wifi_manager_dashboard_listen=smart_wifi_manager_dashboard_listen,
        smart_wifi_manager_profile_path=smart_wifi_manager_profile_path,
        mavlink_management_mode=mavlink_management_mode,
        mavlink_anywhere_repo_url_https=mavlink_anywhere_repo_url_https,
        mavlink_anywhere_ref=mavlink_anywhere_ref,
        mavlink_anywhere_install_dir=mavlink_anywhere_install_dir,
        mavlink_anywhere_dashboard_listen=mavlink_anywhere_dashboard_listen,
        mavlink_anywhere_skip_dashboard=mavlink_anywhere_skip_dashboard,
        source=source,
    )


def load_deployment_profile() -> DeploymentProfile:
    path = get_deployment_profile_path()
    cached = _DEPLOYMENT_PROFILE_CACHE.get(path)
    if cached is not None:
        return cached

    profile = _build_profile(path)
    _DEPLOYMENT_PROFILE_CACHE[path] = profile
    return profile


def reset_deployment_profile_cache() -> None:
    _DEPLOYMENT_PROFILE_CACHE.clear()
