"""Git-tracked deployment profile defaults."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

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
    data: dict[str, str] = {}
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
    return data


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
    branch = data.get("MDS_DEFAULT_BRANCH", "main-candidate")
    real_gcs_ip = data.get("MDS_DEFAULT_REAL_GCS_IP", "100.96.32.75")
    sitl_gcs_ip = data.get("MDS_DEFAULT_SITL_GCS_IP", "172.18.0.1")

    try:
        gcs_api_port = int(data.get("MDS_DEFAULT_GCS_API_PORT", "5000"))
    except ValueError:
        logger.warning(
            "Invalid MDS_DEFAULT_GCS_API_PORT=%r in %s; using 5000",
            data.get("MDS_DEFAULT_GCS_API_PORT"),
            path,
        )
        gcs_api_port = 5000

    return DeploymentProfile(
        profile_id=data.get("MDS_DEFAULT_PROFILE_ID", "official-default"),
        repo_slug=repo_slug,
        repo_url_https=repo_url_https,
        repo_url_ssh=repo_url_ssh,
        branch=branch,
        real_gcs_ip=real_gcs_ip,
        sitl_gcs_ip=sitl_gcs_ip,
        gcs_api_port=gcs_api_port,
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
