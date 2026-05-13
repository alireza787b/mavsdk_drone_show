"""Shared helpers for managed node-side runtime tooling status."""

from __future__ import annotations

import configparser
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from src.settings.deployment_profile import load_deployment_profile

SIDECAR_PROFILE_SCHEMA = "mds.sidecar_profile.v1"
SIDECAR_PROFILE_MODES = ("observe", "local", "fleet-merge", "fleet-strict")
SIDECAR_DRIFT_STATES = (
    "in_sync",
    "local_extra",
    "missing_fleet_baseline",
    "outdated",
    "unmanaged",
    "unreachable",
)


def normalize_sidecar_mode(value: Optional[str], *, default: str = "local", sidecar: str = "") -> str:
    normalized = str(value or "").strip().lower()
    aliases = {
        "manage": "fleet-merge",
        "managed": "fleet-merge",
        "manual": "local",
        "none": "observe",
        "disabled": "observe",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in SIDECAR_PROFILE_MODES else default


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


def short_hash(value: Optional[str]) -> Optional[str]:
    normalized = str(value or "").strip()
    return normalized[:12] if normalized else None


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def read_json_object(path: Optional[Union[str, Path]]) -> Dict[str, Any]:
    if not path:
        return {}
    candidate = Path(path)
    if not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def secret_status_from_profile(profile: Dict[str, Any]) -> str:
    explicit = str(profile.get("secret_status") or "").strip().lower()
    allowed = {"stored", "missing", "external file", "redacted"}
    if explicit in allowed:
        return explicit

    external_keys = {"password_file", "passphrase_file", "psk_file", "secret_file"}
    if any(str(profile.get(key) or "").strip() for key in external_keys):
        return "external file"

    secret_keys = {"password", "passphrase", "psk", "secret"}
    if any(str(profile.get(key) or "").strip() for key in secret_keys):
        return "stored"
    return "missing"


def summarize_smart_wifi_profiles(profile_path: Optional[Union[str, Path]]) -> Dict[str, Any]:
    payload = read_json_object(profile_path)
    raw_profiles = payload.get("profiles") if isinstance(payload.get("profiles"), list) else []
    profiles: List[Dict[str, Any]] = []
    for raw_profile in raw_profiles:
        if not isinstance(raw_profile, dict):
            continue
        profile_id = str(raw_profile.get("id") or raw_profile.get("ssid") or "").strip()
        ssid = str(raw_profile.get("ssid") or "").strip()
        if not profile_id and not ssid:
            continue
        profiles.append(
            {
                "id": profile_id or ssid,
                "ssid": ssid or profile_id,
                "priority": safe_int(raw_profile.get("priority"), 0),
                "connection_name": str(raw_profile.get("connection_name") or "").strip(),
                "autoconnect": as_bool(raw_profile.get("autoconnect"), default=True),
                "disabled": as_bool(raw_profile.get("disabled"), default=False),
                "secret_status": secret_status_from_profile(raw_profile),
            }
        )
    profiles.sort(key=lambda item: (-safe_int(item.get("priority"), 0), str(item.get("id") or "").lower()))
    return {
        "profile_count": len(profiles),
        "network_count": len(profiles),
        "profiles": profiles,
    }


def _router_option(section: Dict[str, str], *names: str) -> str:
    for name in names:
        value = section.get(name.lower())
        if value is not None:
            return str(value).strip()
    return ""


def _split_endpoint_section(section_name: str) -> tuple[str, str]:
    parts = str(section_name or "").strip().split(None, 1)
    endpoint_type = parts[0] if parts else "Endpoint"
    endpoint_name = parts[1] if len(parts) > 1 else endpoint_type
    return endpoint_type, endpoint_name


def summarize_mavlink_router_config(path: Optional[Union[str, Path]]) -> Dict[str, Any]:
    if not path:
        return {"router_config_present": False, "sources": [], "endpoints": [], "source_count": 0, "endpoint_count": 0}
    candidate = Path(path)
    if not candidate.is_file():
        return {"router_config_present": False, "sources": [], "endpoints": [], "source_count": 0, "endpoint_count": 0}

    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read(candidate, encoding="utf-8")
    except configparser.Error:
        return {"router_config_present": True, "sources": [], "endpoints": [], "source_count": 0, "endpoint_count": 0}

    sources: List[Dict[str, Any]] = []
    endpoints: List[Dict[str, Any]] = []
    for section_name in parser.sections():
        if "endpoint" not in section_name.lower():
            continue
        endpoint_type, endpoint_name = _split_endpoint_section(section_name)
        section = {str(key).lower(): str(value) for key, value in parser.items(section_name)}
        mode = _router_option(section, "mode") or "normal"
        address = _router_option(section, "address")
        port = safe_int(_router_option(section, "port"), 0)
        device = _router_option(section, "device")
        baud = safe_int(_router_option(section, "baud", "baudrate"), 0)
        enabled = not as_bool(_router_option(section, "disabled"), default=False)
        is_source = (
            endpoint_type.lower().startswith("uart")
            or (
                endpoint_type.lower().startswith("udp")
                and mode.lower() == "server"
                and endpoint_name.lower() in {"input", "source", "px4"}
            )
        )
        item: Dict[str, Any] = {
            "name": endpoint_name,
            "type": endpoint_type,
            "mode": mode.lower(),
            "enabled": enabled,
            "role": "source" if is_source else "endpoint",
        }
        if address:
            item["address"] = address
        if port:
            item["port"] = port
        if device:
            item["device"] = device
        if baud:
            item["baud"] = baud
        if is_source:
            sources.append(item)
        else:
            endpoints.append(item)

    sources.sort(key=lambda item: str(item.get("name") or "").lower())
    endpoints.sort(key=lambda item: str(item.get("name") or "").lower())
    return {
        "router_config_present": True,
        "sources": sources,
        "endpoints": endpoints,
        "source_count": len(sources),
        "endpoint_count": len(endpoints),
    }


def sidecar_drift_state(
    *,
    status_source: str,
    mode: str,
    installed: bool,
    desired_hash: Optional[str],
    applied_hash: Optional[str],
    local_hash: Optional[str],
    hash_match: Optional[bool],
    missing_baseline: bool = False,
) -> str:
    source = str(status_source or "").strip().lower()
    normalized_mode = str(mode or "").strip().lower()
    if source in {"timeout", "invoke_error", "script_error"}:
        return "unreachable"
    if not installed or normalized_mode in {"", "unknown", "disabled", "observe", "manual", "local"}:
        return "unmanaged"
    if missing_baseline:
        return "missing_fleet_baseline"
    if hash_match is True:
        return "in_sync"
    if hash_match is False:
        if desired_hash and not applied_hash:
            return "missing_fleet_baseline"
        if local_hash and desired_hash and local_hash != desired_hash:
            return "local_extra"
        return "outdated"
    if local_hash and desired_hash and local_hash != desired_hash:
        return "local_extra"
    if desired_hash and applied_hash and desired_hash == applied_hash:
        return "in_sync"
    return "unmanaged"


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
    desired_hash = status.get("desired_config_hash") or None
    applied_hash = status.get("applied_config_hash") or None
    hash_match = optional_bool(status.get("config_hash_match"))
    management_mode = normalize_sidecar_mode(
        status.get("mode") or deployment_profile.mavlink_management_mode,
        default="local",
        sidecar="mavlink-anywhere",
    )
    service_state = status.get("router_service", "unknown")
    router_config_path = status.get("router_config") or os.environ.get("MAVLINK_ROUTER_CONFIG") or "/etc/mavlink-router/main.conf"
    router_profile_summary = summarize_mavlink_router_config(router_config_path)
    drift_state = sidecar_drift_state(
        status_source=status.get("status_source", "fallback"),
        mode=management_mode,
        installed=runtime_present,
        desired_hash=desired_hash,
        applied_hash=applied_hash,
        local_hash=applied_hash,
        hash_match=hash_match,
        missing_baseline=False,
    )

    return {
        "tool": "mavlink-anywhere",
        "status_source": status.get("status_source", "fallback"),
        "mode": management_mode,
        "management_mode": management_mode,
        "service_state": service_state,
        "repo_url": repo_url,
        "ref": ref,
        "installed_ref": ref,
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
        "router_service_status": service_state,
        "dashboard_enabled": dashboard_enabled,
        "dashboard_listen": dashboard_listen,
        "dashboard_service_status": status.get("dashboard_service", "unknown"),
        "profile_source": "node-overlay",
        "desired_hash": desired_hash,
        "applied_hash": applied_hash,
        "local_hash": applied_hash,
        "drift_state": drift_state,
        "profile_summary": {
            "mode": management_mode,
            "desired_hash": short_hash(desired_hash),
            "applied_hash": short_hash(applied_hash),
            "router_service": service_state,
            "dashboard_service": status.get("dashboard_service", "unknown"),
            **router_profile_summary,
        },
        "last_apply_result": status.get("last_apply_result") or status.get("error") or drift_state,
        "desired_config_hash": desired_hash,
        "applied_config_hash": applied_hash,
        "config_hash_match": hash_match,
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
    profile_present = bool(profile_path and Path(profile_path).is_file())
    desired_hash = status.get("desired_config_hash") or None
    applied_hash = status.get("applied_config_hash") or None
    local_hash = status.get("profile_hash") or file_sha256(profile_path)
    hash_match = optional_bool(status.get("config_hash_match"))
    mode = normalize_sidecar_mode(
        status.get("mode") or deployment_profile.smart_wifi_manager_mode,
        default="fleet-merge",
        sidecar="smart-wifi-manager",
    )
    service_state = status.get("service_status", "unknown")
    wifi_profile_summary = summarize_smart_wifi_profiles(profile_path)
    drift_state = sidecar_drift_state(
        status_source=status.get("status_source", "fallback"),
        mode=mode,
        installed=install_dir_present,
        desired_hash=desired_hash,
        applied_hash=applied_hash,
        local_hash=local_hash,
        hash_match=hash_match,
        missing_baseline=(
            str(status.get("backend") or deployment_profile.connectivity_backend) == "smart-wifi-manager"
            and str(mode).lower() in {"fleet-merge", "fleet-strict"}
            and not profile_present
        ),
    )

    return {
        "tool": "smart-wifi-manager",
        "status_source": status.get("status_source", "fallback"),
        "backend": status.get("backend") or deployment_profile.connectivity_backend,
        "service_state": service_state,
        "repo_url": repo_url,
        "ref": ref,
        "installed_ref": ref,
        "repo_web_url": normalize_github_repo_web_url(repo_url, ref),
        "install_dir": install_dir,
        "install_dir_present": install_dir_present,
        "mode": mode,
        "import_mode": deployment_profile.smart_wifi_manager_import_mode,
        "profile_path": profile_path,
        "profile_present": profile_present,
        "profile_source": "fleet-profile" if profile_present else "missing",
        "profile_hash": local_hash,
        "desired_hash": desired_hash,
        "applied_hash": applied_hash,
        "local_hash": local_hash,
        "drift_state": drift_state,
        "profile_summary": {
            "mode": mode,
            "import_mode": deployment_profile.smart_wifi_manager_import_mode,
            "profile_present": profile_present,
            "profile_hash": short_hash(local_hash),
            "desired_hash": short_hash(desired_hash),
            "applied_hash": short_hash(applied_hash),
            **wifi_profile_summary,
        },
        "last_apply_result": status.get("last_apply_result") or status.get("error") or drift_state,
        "dashboard_listen": status.get("dashboard_listen")
        or os.environ.get("MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN")
        or deployment_profile.smart_wifi_manager_dashboard_listen,
        "service_status": service_state,
        "desired_config_hash": desired_hash,
        "applied_config_hash": applied_hash,
        "config_hash_match": hash_match,
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
            "mavsdk_runtime_status": "unknown",
            "requirements_update_status": "unknown",
            "recovery_action": "none",
            "recovery_backup_path": None,
            "disk_available_status": "unknown",
            "disk_free_kb": None,
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
            "mavsdk_runtime_status": "unknown",
            "requirements_update_status": "unknown",
            "recovery_action": "none",
            "recovery_backup_path": None,
            "disk_available_status": "unknown",
            "disk_free_kb": None,
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
    mavsdk_status = str(data.get("mavsdk_runtime_status") or "unknown").strip() or "unknown"
    requirements_status = str(data.get("requirements_update_status") or "unknown").strip() or "unknown"
    recovery_action = str(data.get("recovery_action") or "none").strip() or "none"
    recovery_backup_path = str(data.get("recovery_backup_path") or "").strip() or None
    disk_available_status = str(data.get("disk_available_status") or "unknown").strip() or "unknown"
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
    if mavsdk_status not in {"unknown", "not_checked", "present"}:
        summary_parts.append(f"MAVSDK runtime: {mavsdk_status}")
    if requirements_status not in {"unknown", "unchanged", "not_required"}:
        summary_parts.append(f"Requirements: {requirements_status}")
    if recovery_action not in {"", "none"}:
        summary_parts.append(f"Recovery: {recovery_action}")
    if disk_available_status not in {"unknown", "ok"}:
        summary_parts.append(f"Disk: {disk_available_status}")

    try:
        last_run_at_ms = int(str(data.get("timestamp_ms") or "").strip()) if data.get("timestamp_ms") else None
    except ValueError:
        last_run_at_ms = None
    try:
        disk_free_kb = int(str(data.get("disk_free_kb") or "").strip()) if data.get("disk_free_kb") else None
    except ValueError:
        disk_free_kb = None

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
        "mavsdk_runtime_status": mavsdk_status,
        "requirements_update_status": requirements_status,
        "recovery_action": recovery_action,
        "recovery_backup_path": recovery_backup_path,
        "disk_available_status": disk_available_status,
        "disk_free_kb": disk_free_kb,
    }
