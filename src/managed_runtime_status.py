"""Shared helpers for managed node-side runtime tooling status."""

from __future__ import annotations

import os
import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from src.settings.deployment_profile import load_deployment_profile


def normalize_github_repo_web_url(repo_url: Optional[str], ref: Optional[str]) -> Optional[str]:
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


def as_bool(value: Optional[str], *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "present", "active"}


def parse_status_output(stdout: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def read_reconcile_status(repo_root: Path, script_relative_path: str, *, timeout: int = 5) -> Dict[str, str]:
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


def file_sha256(path: Optional[Union[str, Path]]) -> Optional[str]:
    if not path:
        return None
    candidate = Path(path)
    if not candidate.is_file():
        return None
    digest = hashlib.sha256()
    try:
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return None
    return digest.hexdigest()


def optional_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def build_mavlink_runtime_summary(repo_root: Path) -> Dict[str, Any]:
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
        "desired_config_hash": status.get("desired_config_hash") or None,
        "applied_config_hash": status.get("applied_config_hash") or None,
        "config_hash_match": optional_bool(status.get("config_hash_match")),
    }


def build_connectivity_runtime_summary(repo_root: Path) -> Dict[str, Any]:
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
        "profile_hash": status.get("profile_hash") or file_sha256(profile_path),
        "dashboard_listen": os.environ.get("MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN") or deployment_profile.smart_wifi_manager_dashboard_listen,
        "service_status": status.get("service_status", "unknown"),
        "desired_config_hash": status.get("desired_config_hash") or None,
        "applied_config_hash": status.get("applied_config_hash") or None,
        "config_hash_match": optional_bool(status.get("config_hash_match")),
    }


def resolve_dashboard_access(ip: Optional[str], listen: Optional[str]) -> Dict[str, Optional[str]]:
    raw_listen = str(listen or "").strip()
    if not raw_listen:
        return {"dashboard_access_mode": "unknown", "dashboard_url": None}

    scheme = "http"
    host = ""
    port: Optional[int] = None

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


def read_git_sync_runtime_summary() -> Dict[str, Any]:
    default_state_path = Path.home() / ".local/state/mds/git-sync/last_result.env"
    state_path = Path(os.environ.get("MDS_GIT_SYNC_STATE_FILE", str(default_state_path)))
    if not state_path.is_file():
        return {
            "status": "unknown",
            "summary": "No node-local git sync runtime state has been recorded yet.",
            "last_run_at_ms": None,
            "updated_units": [],
            "service_reload_status": "unknown",
            "service_reload_message": "",
            "deferred_unit_actions": [],
            "coordinator_restart_scheduled": False,
            "connectivity_reconcile_status": "unknown",
            "mavlink_runtime_reconcile_status": "unknown",
            "requirements_update_status": "unknown",
        }

    try:
        data = parse_status_output(state_path.read_text(encoding="utf-8"))
    except OSError:
        return {
            "status": "unknown",
            "summary": "Node-local git sync runtime state is unreadable.",
            "last_run_at_ms": None,
            "updated_units": [],
            "service_reload_status": "unknown",
            "service_reload_message": "",
            "deferred_unit_actions": [],
            "coordinator_restart_scheduled": False,
            "connectivity_reconcile_status": "unknown",
            "mavlink_runtime_reconcile_status": "unknown",
            "requirements_update_status": "unknown",
        }

    updated_units = [
        item.strip() for item in str(data.get("updated_units") or "").split(",") if item.strip()
    ]
    deferred_unit_actions = [
        item.strip() for item in str(data.get("deferred_unit_actions") or "").split(",") if item.strip()
    ]
    status = str(data.get("status") or "unknown").strip().lower() or "unknown"
    message = str(data.get("message") or "").strip()
    service_reload_status = str(data.get("service_reload_status") or "unknown").strip() or "unknown"
    service_reload_message = str(data.get("service_reload_message") or "").strip()
    connectivity_status = str(data.get("connectivity_reconcile_status") or "unknown").strip() or "unknown"
    mavlink_status = str(data.get("mavlink_runtime_reconcile_status") or "unknown").strip() or "unknown"
    requirements_status = str(data.get("requirements_update_status") or "unknown").strip() or "unknown"
    coordinator_restart_scheduled = as_bool(data.get("coordinator_restart_scheduled"), default=False)

    summary_parts: List[str] = []
    if message:
        summary_parts.append(message)
    if updated_units:
        summary_parts.append(f"Updated units: {', '.join(updated_units)}")
    if service_reload_message and service_reload_message != message:
        summary_parts.append(service_reload_message)
    if coordinator_restart_scheduled:
        summary_parts.append("Coordinator restart scheduled")
    if deferred_unit_actions:
        summary_parts.append(f"Deferred apply: {', '.join(deferred_unit_actions)}")
    if connectivity_status not in {"unknown", "not_required"}:
        summary_parts.append(f"Connectivity: {connectivity_status}")
    if mavlink_status not in {"unknown", "not_required"}:
        summary_parts.append(f"MAVLink runtime: {mavlink_status}")
    if requirements_status not in {"unknown", "unchanged", "not_required"}:
        summary_parts.append(f"Requirements: {requirements_status}")

    try:
        last_run_at_ms = int(str(data.get("timestamp_ms") or "").strip()) if data.get("timestamp_ms") else None
    except ValueError:
        last_run_at_ms = None

    return {
        "status": status,
        "summary": " · ".join(summary_parts) if summary_parts else "No node-local git sync runtime details recorded.",
        "last_run_at_ms": last_run_at_ms,
        "updated_units": updated_units,
        "service_reload_status": service_reload_status,
        "service_reload_message": service_reload_message,
        "deferred_unit_actions": deferred_unit_actions,
        "coordinator_restart_scheduled": coordinator_restart_scheduled,
        "connectivity_reconcile_status": connectivity_status,
        "mavlink_runtime_reconcile_status": mavlink_status,
        "requirements_update_status": requirements_status,
    }
