"""Shared helpers for managed node-side runtime tooling status."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.settings.deployment_profile import load_deployment_profile


def normalize_github_repo_web_url(repo_url: str | None, ref: str | None) -> str | None:
    normalized = str(repo_url or "").strip()
    if normalized.startswith("git@github.com:"):
        normalized = normalized.replace("git@github.com:", "https://github.com/", 1)
    if normalized.startswith("https://github.com/") and normalized.endswith(".git"):
        normalized = normalized[:-4]
    if not normalized.startswith("https://github.com/"):
        return None

    ref_name = str(ref or "").strip()
    if ref_name:
        return f"{normalized}/tree/{ref_name}"
    return normalized


def as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "present", "active"}


def parse_status_output(stdout: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def read_reconcile_status(repo_root: Path, script_relative_path: str, *, timeout: int = 5) -> dict[str, str]:
    script_path = repo_root / script_relative_path
    if not script_path.is_file():
        return {"status_source": "missing_script"}

    try:
        result = subprocess.run(
            [str(script_path), "status", "--quiet"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status_source": "timeout"}
    except OSError:
        return {"status_source": "invoke_error"}

    data = parse_status_output(result.stdout)
    data["status_source"] = "script" if result.returncode == 0 else "script_error"
    if result.returncode != 0 and result.stderr:
        data["error"] = result.stderr.strip()
    return data


def build_mavlink_runtime_summary(repo_root: Path) -> dict[str, Any]:
    deployment_profile = load_deployment_profile()
    status = read_reconcile_status(repo_root, "tools/reconcile_mavlink_runtime.sh")
    repo_url = status.get("repo_url") or deployment_profile.mavlink_anywhere_repo_url_https
    ref = status.get("ref") or deployment_profile.mavlink_anywhere_ref
    install_dir = status.get("install_dir") or deployment_profile.mavlink_anywhere_install_dir
    install_dir_present = Path(install_dir).is_dir()
    runtime_present = as_bool(status.get("runtime_present"), default=Path(install_dir, ".git").is_dir())
    dashboard_listen = status.get("dashboard_listen") or deployment_profile.mavlink_anywhere_dashboard_listen
    dashboard_enabled = not as_bool(
        status.get("skip_dashboard"),
        default=bool(deployment_profile.mavlink_anywhere_skip_dashboard),
    )

    return {
        "status_source": status.get("status_source", "fallback"),
        "management_mode": status.get("mode") or deployment_profile.mavlink_management_mode,
        "repo_url": repo_url,
        "ref": ref,
        "repo_web_url": normalize_github_repo_web_url(repo_url, ref),
        "install_dir": install_dir,
        "install_dir_present": install_dir_present,
        "runtime_present": runtime_present,
        "runtime_head": status.get("runtime_head") or None,
        "router_binary_present": (
            status.get("router_binary") == "present"
            if "router_binary" in status
            else bool(shutil.which("mavlink-routerd"))
        ),
        "router_service_status": status.get("router_service", "unknown"),
        "dashboard_enabled": dashboard_enabled,
        "dashboard_listen": dashboard_listen,
        "dashboard_service_status": status.get("dashboard_service", "unknown"),
    }


def build_connectivity_runtime_summary(repo_root: Path) -> dict[str, Any]:
    deployment_profile = load_deployment_profile()
    status = read_reconcile_status(repo_root, "tools/reconcile_connectivity.sh")
    repo_url = status.get("repo_url") or deployment_profile.smart_wifi_manager_repo_url_https
    ref = status.get("ref") or deployment_profile.smart_wifi_manager_ref
    install_dir = status.get("install_dir") or deployment_profile.smart_wifi_manager_install_dir
    install_dir_present = Path(install_dir).is_dir()
    profile_path = status.get("profile_path") or str(
        Path(deployment_profile.smart_wifi_manager_profile_path).resolve()
        if str(deployment_profile.smart_wifi_manager_profile_path or "").startswith("/")
        else (repo_root / deployment_profile.smart_wifi_manager_profile_path).resolve()
    )

    return {
        "status_source": status.get("status_source", "fallback"),
        "backend": status.get("backend") or deployment_profile.connectivity_backend,
        "repo_url": repo_url,
        "ref": ref,
        "repo_web_url": normalize_github_repo_web_url(repo_url, ref),
        "install_dir": install_dir,
        "install_dir_present": install_dir_present,
        "mode": status.get("mode") or deployment_profile.smart_wifi_manager_mode,
        "import_mode": deployment_profile.smart_wifi_manager_import_mode,
        "profile_path": profile_path,
        "profile_present": bool(profile_path and Path(profile_path).is_file()),
        "dashboard_listen": os.environ.get("MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN") or deployment_profile.smart_wifi_manager_dashboard_listen,
        "service_status": status.get("service_status", "unknown"),
    }


def resolve_dashboard_access(ip: str | None, listen: str | None) -> dict[str, str | None]:
    raw_listen = str(listen or "").strip()
    if not raw_listen:
        return {"dashboard_access_mode": "unknown", "dashboard_url": None}

    scheme = "http"
    host = ""
    port: int | None = None

    if "://" in raw_listen:
        parsed = urlparse(raw_listen)
        scheme = parsed.scheme or "http"
        host = parsed.hostname or ""
        port = parsed.port
    elif raw_listen.isdigit():
        host = "127.0.0.1"
        port = int(raw_listen)
    elif raw_listen.startswith("[") and "]:" in raw_listen:
        host, _, tail = raw_listen[1:].partition("]:")
        port = int(tail) if tail.isdigit() else None
    elif raw_listen.count(":") == 1:
        host, port_raw = raw_listen.split(":", 1)
        port = int(port_raw) if port_raw.isdigit() else None
    else:
        return {"dashboard_access_mode": "unknown", "dashboard_url": None}

    normalized_host = host.strip().strip("[]").lower()
    if not port:
        return {"dashboard_access_mode": "unknown", "dashboard_url": None}
    if normalized_host in {"", "127.0.0.1", "localhost", "::1"}:
        return {"dashboard_access_mode": "local_only", "dashboard_url": None}
    if normalized_host in {"0.0.0.0", "::"}:
        if not ip:
            return {"dashboard_access_mode": "unknown", "dashboard_url": None}
        return {"dashboard_access_mode": "direct", "dashboard_url": f"{scheme}://{ip}:{port}"}
    return {"dashboard_access_mode": "direct", "dashboard_url": f"{scheme}://{host}:{port}"}
