"""GCS management and network helper routes."""

import os
import shlex
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from schemas import (
    GCSConfigApplyResponse,
    GCSConfigResponse,
    GCSConfigSaveResponse,
    GCSRuntimeUpdateResponse,
    GCSConfigUpdateRequest,
    EnvRegistryResponse,
    FleetRuntimeEnvNodePlan,
    FleetRuntimeEnvNodeResponse,
    FleetRuntimeEnvNodeUpdateResponse,
    FleetRuntimeEnvPlanRequest,
    FleetRuntimeEnvPlanResponse,
    GCSRuntimeEnvApplyResponse,
    GCSRuntimeEnvEntryResponse,
    GCSRuntimeEnvResponse,
    GCSRuntimeEnvUpdateRequest,
    GCSRuntimeEnvUpdateResponse,
    RuntimeConnectivityRuntimeResponse,
    RuntimeDocsResponse,
    RuntimeFleetDefaultsResponse,
    RuntimeGitAuthHealthResponse,
    RuntimeMavlinkRuntimeResponse,
    RuntimeRepoSyncStatusResponse,
    RuntimeStatusResponse,
)
from src.drone_api_routes import DRONE_ENV_ROUTE
from src.settings.env_files import persist_env_updates, read_env_assignments
from src.settings.env_registry import EnvRegistryEntry, EnvRegistryError, coerce_value, load_env_registry, redact_value
from src.managed_runtime_status import (
    as_bool,
    build_connectivity_runtime_summary,
    build_mavlink_runtime_summary,
)
from src.settings.deployment_profile import load_deployment_profile
from src.settings.runtime import resolve_runtime_mode
from src.sitl_control_service import SitlControlService

_PROCESS_START_MONOTONIC = time.monotonic()
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RESTART_SCHEDULE_LOCK = threading.Lock()
_LAST_RESTART_SCHEDULE_AT_MONOTONIC = 0.0
_RESTART_DEBOUNCE_SECONDS = 15.0
_RESTART_DELAY_MS = 2000
_UPDATE_SCHEDULE_LOCK = threading.Lock()
_LAST_UPDATE_SCHEDULE_AT_MONOTONIC = 0.0
_UPDATE_DEBOUNCE_SECONDS = 15.0
_UPDATE_DELAY_MS = 2000
_GCS_RUNTIME_UPDATE_SCRIPT = _REPO_ROOT / "tools" / "gcs_fast_forward_update.sh"
_GCS_RUNTIME_UPDATE_BLOCKED_PREFIXES = (
    "app/",
    "tools/",
    ".github/workflows/",
)
_GCS_RUNTIME_UPDATE_BLOCKED_BASENAMES = {
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "requirements-gcs.txt",
    "pyproject.toml",
    "poetry.lock",
    "Pipfile",
    "Pipfile.lock",
    "uv.lock",
}


def _get_gcs_config_path() -> Path:
    return Path(os.environ.get("MDS_GCS_SYSTEM_CONFIG", "/etc/mds/gcs.env"))


def _normalize_runtime_mode_value(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().lower()
    if normalized == "real":
        return "real"
    if normalized == "sitl":
        return "sitl"
    return None


def _persist_env_updates(path: Path, updates: dict[str, Any]) -> list[str]:
    return list(persist_env_updates(path, updates).changed_keys)


def _build_gcs_env_entry_response(entry: EnvRegistryEntry, values: dict[str, str]) -> GCSRuntimeEnvEntryResponse:
    value_present = entry.name in values
    raw_value = values.get(entry.name)
    secret_configured = bool(entry.secret and raw_value)
    value = redact_value(entry, raw_value) if value_present else None
    return GCSRuntimeEnvEntryResponse(
        name=entry.name,
        title=entry.title,
        scope=entry.scope,
        domain=entry.domain,
        source_of_truth=entry.source_of_truth,
        value_type=entry.value_type,
        value=value,
        value_present=value_present,
        secret=entry.secret,
        secret_configured=secret_configured,
        default=redact_value(entry, entry.default),
        editable=entry.editable,
        ui_visibility=entry.ui_visibility,
        restart_required=entry.restart_required,
        apply_action=entry.apply_action,
        allowed_values=list(entry.allowed_values),
        docs=entry.docs,
        deprecated=entry.deprecated,
        replacement=entry.replacement,
        notes=entry.notes,
    )


def _build_gcs_env_response() -> GCSRuntimeEnvResponse:
    registry = load_env_registry()
    config_path = _get_gcs_config_path()
    values = read_env_assignments(config_path)
    classified = registry.classify_keys(values)
    gcs_entries = [
        entry
        for entry in registry.list_entries(include_hidden=False)
        if "/etc/mds/gcs.env" in entry.source_of_truth or entry.source_of_truth == "/etc/mds/gcs.env"
    ]
    warnings: list[str] = []
    if classified["unknown"]:
        warnings.append(
            "This GCS env file contains unregistered keys. They are ignored by the env control plane until registered or removed."
        )
    if classified["deprecated"]:
        warnings.append("This GCS env file contains deprecated keys. Replace them with the registry replacement before release.")

    return GCSRuntimeEnvResponse(
        config_path=str(config_path),
        config_present=config_path.is_file(),
        registry_version=registry.version,
        registry_hash=registry.content_hash,
        values=[_build_gcs_env_entry_response(entry, values) for entry in gcs_entries],
        unknown_keys=classified["unknown"],
        deprecated_keys=classified["deprecated"],
        warnings=warnings,
    )


def _validate_gcs_env_updates(updates: dict[str, Any]) -> tuple[dict[str, str], list[str], list[str], bool]:
    registry = load_env_registry()
    validated: dict[str, str] = {}
    warnings: list[str] = []
    apply_actions: set[str] = set()
    restart_required = False

    for key, value in updates.items():
        entry = registry.get(key)
        if entry is None:
            raise HTTPException(status_code=422, detail=f"{key} is not registered in the MDS environment registry")
        if entry.scope not in {"gcs", "agent"}:
            raise HTTPException(status_code=422, detail=f"{key} is a {entry.scope} key and cannot be written to GCS env")
        if "/etc/mds/gcs.env" not in entry.source_of_truth and entry.source_of_truth != "/etc/mds/gcs.env":
            raise HTTPException(status_code=422, detail=f"{key} is not sourced from the GCS env file")
        if entry.deprecated:
            replacement = f"; use {entry.replacement}" if entry.replacement else ""
            raise HTTPException(status_code=422, detail=f"{key} is deprecated{replacement}")
        if not entry.editable:
            raise HTTPException(status_code=422, detail=f"{key} is not editable through the GCS env API")
        try:
            validated[key] = coerce_value(entry, value)
        except EnvRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        apply_actions.add(entry.apply_action)
        if entry.restart_required == "gcs" or entry.apply_action == "restart_gcs":
            restart_required = True
        if entry.ui_visibility == "advanced":
            warnings.append(f"{key} is an advanced setting; verify fleet docs and recovery path before applying.")

    return validated, warnings, sorted(action for action in apply_actions if action != "none"), restart_required


def _validate_fleet_env_plan_updates(updates: dict[str, Any]) -> tuple[dict[str, str], list[str], list[str], bool]:
    registry = load_env_registry()
    validated: dict[str, str] = {}
    warnings: list[str] = []
    apply_actions: set[str] = set()
    restart_required = False

    for key, value in updates.items():
        entry = registry.get(key)
        if entry is None:
            raise HTTPException(status_code=422, detail=f"{key} is not registered in the MDS environment registry")
        if entry.scope != "node":
            raise HTTPException(status_code=422, detail=f"{key} is a {entry.scope} key and cannot be planned for fleet-node env")
        if entry.deprecated:
            replacement = f"; use {entry.replacement}" if entry.replacement else ""
            raise HTTPException(status_code=422, detail=f"{key} is deprecated{replacement}")
        if not entry.editable:
            raise HTTPException(status_code=422, detail=f"{key} is not editable through fleet env planning")
        try:
            validated[key] = coerce_value(entry, value)
        except EnvRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        apply_actions.add(entry.apply_action)
        if entry.restart_required != "none" or entry.apply_action != "none":
            restart_required = True
        if entry.ui_visibility == "advanced":
            warnings.append(f"{key} is an advanced node setting; plan on one drone before fleet rollout.")

    return validated, warnings, sorted(action for action in apply_actions if action != "none"), restart_required


def _normalize_hw_id_list(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _resolve_fleet_env_plan_targets(deps: Any, requested_hw_ids: list[Any]) -> list[str]:
    requested = _normalize_hw_id_list(requested_hw_ids)
    if requested:
        return requested

    configured: list[str] = []
    try:
        for drone in deps.load_config() or []:
            hw_id = str((drone or {}).get("hw_id") or "").strip()
            if hw_id:
                configured.append(hw_id)
    except Exception:
        configured = []

    if configured:
        return _normalize_hw_id_list(configured)

    try:
        with deps.data_lock_git_status:
            return _normalize_hw_id_list(list(deps.git_status_data_all_drones.keys()))
    except Exception:
        return []


def _snapshot_git_status_env_reports(deps: Any) -> dict[str, dict[str, Any]]:
    try:
        with deps.data_lock_git_status:
            return {
                str(hw_id): dict(raw_data or {})
                for hw_id, raw_data in getattr(deps, "git_status_data_all_drones", {}).items()
            }
    except Exception:
        return {}


def _normalize_hw_id(value: Any) -> str:
    return str(value or "").strip()


def _drone_api_port(deps: Any) -> int:
    raw_value = getattr(getattr(deps, "Params", object()), "drone_api_port", None)
    if raw_value is None:
        raw_value = os.environ.get("MDS_DRONE_API_PORT", os.environ.get("MDS_DEFAULT_DRONE_API_PORT", "7070"))
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return 7070


def _extract_node_host(row: dict[str, Any] | None) -> str | None:
    if not isinstance(row, dict):
        return None
    for key in (
        "ip",
        "drone_ip",
        "node_ip",
        "netbird_ip",
        "primary_control_ip",
        "control_ip",
        "reported_ip",
        "observed_ip",
        "local_ip",
        "vpn_ip",
        "host",
    ):
        value = str(row.get(key) or "").strip()
        if value:
            return value.rstrip("/")
    return None


def _node_record_matches(row: dict[str, Any], key: Any, target: str) -> bool:
    row_hw_id = _normalize_hw_id(row.get("hw_id") or key)
    row_pos_id = _normalize_hw_id(row.get("pos_id"))
    return row_hw_id == target or row_pos_id == target


def _merge_node_records(config_row: dict[str, Any] | None, reported_row: dict[str, Any] | None) -> dict[str, Any]:
    """Keep fleet-config reachability data while preserving live node posture."""
    merged: dict[str, Any] = dict(config_row or {})
    for key, value in dict(reported_row or {}).items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        merged[key] = value
    return merged


def _resolve_config_node_record(deps: Any, target: str) -> dict[str, Any] | None:
    try:
        for raw_row in deps.load_config() or []:
            row = dict(raw_row or {})
            if _node_record_matches(row, row.get("hw_id"), target):
                return row
    except Exception:
        return None
    return None


def _resolve_node_record(deps: Any, hw_id: str) -> dict[str, Any] | None:
    target = _normalize_hw_id(hw_id)
    if not target:
        return None

    config_row = _resolve_config_node_record(deps, target)

    try:
        with deps.data_lock_git_status:
            git_status = dict(getattr(deps, "git_status_data_all_drones", {}) or {})
        for key, value in git_status.items():
            row = dict(value or {})
            if _node_record_matches(row, key, target):
                return _merge_node_records(config_row, row)
    except Exception:
        pass

    return config_row


def _build_node_env_url(deps: Any, host: str) -> str:
    normalized_host = str(host or "").strip().rstrip("/")
    if normalized_host.startswith(("http://", "https://")):
        return f"{normalized_host}{DRONE_ENV_ROUTE}"
    return f"http://{normalized_host}:{_drone_api_port(deps)}{DRONE_ENV_ROUTE}"


def _extract_proxy_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str) and detail.strip():
                return detail
    except Exception:
        pass
    return (response.text or "").strip() or f"node env API returned HTTP {response.status_code}"


async def _proxy_node_env_request(
    deps: Any,
    hw_id: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
    include_hidden: bool = False,
) -> tuple[str, dict[str, Any]]:
    record = _resolve_node_record(deps, hw_id)
    host = _extract_node_host(record)
    if not host:
        raise HTTPException(status_code=404, detail=f"No reachable node host is configured or reported for HW {hw_id}")

    endpoint = _build_node_env_url(deps, host)
    params = {"include_hidden": "true"} if include_hidden and method.upper() == "GET" else None
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.request(method.upper(), endpoint, params=params, json=payload)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=504, detail=f"Node env API for HW {hw_id} is unreachable: {exc}") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=_extract_proxy_error(response))

    try:
        return endpoint, response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=f"Node env API for HW {hw_id} did not return JSON") from exc


def _build_fleet_env_plan_response(deps: Any, payload: FleetRuntimeEnvPlanRequest) -> FleetRuntimeEnvPlanResponse:
    registry = load_env_registry()
    updates = payload.updates or {}
    validated, warnings, apply_actions, restart_required = _validate_fleet_env_plan_updates(updates)
    targets = _resolve_fleet_env_plan_targets(deps, payload.target_hw_ids or [])
    env_reports = _snapshot_git_status_env_reports(deps)
    node_plans: list[FleetRuntimeEnvNodePlan] = []

    for hw_id in targets:
        raw_report = env_reports.get(str(hw_id)) or {}
        env_runtime = raw_report.get("env_runtime") if isinstance(raw_report.get("env_runtime"), dict) else None
        blocked_reasons: list[str] = []
        node_warnings: list[str] = []
        local_env_present = False
        registry_hash = ""
        registry_hash_match = False

        if not raw_report:
            blocked_reasons.append("No git/env status has been reported by this node yet.")
        elif not env_runtime:
            blocked_reasons.append("Node git status does not include env_runtime posture.")
        else:
            local_env_present = bool(env_runtime.get("local_env_present", False))
            registry_hash = str(env_runtime.get("registry_hash") or "")
            registry_hash_match = bool(registry_hash and registry_hash == registry.content_hash)
            if not local_env_present:
                blocked_reasons.append("Node local.env is not present; bootstrap or repair the node before env rollout.")
            if not registry_hash_match:
                node_warnings.append("Node registry hash differs from GCS; sync code before applying env changes.")
            unknown_keys = env_runtime.get("unknown_keys") if isinstance(env_runtime.get("unknown_keys"), list) else []
            deprecated_keys = env_runtime.get("deprecated_keys") if isinstance(env_runtime.get("deprecated_keys"), list) else []
            if unknown_keys:
                node_warnings.append(f"Node reports {len(unknown_keys)} unregistered local env key(s).")
            if deprecated_keys:
                node_warnings.append(f"Node reports {len(deprecated_keys)} deprecated local env key(s).")

        status = "planned" if not blocked_reasons else ("unavailable" if not raw_report else "blocked")
        node_plans.append(
            FleetRuntimeEnvNodePlan(
                hw_id=str(hw_id),
                status=status,
                env_report_present=bool(env_runtime),
                local_env_present=local_env_present,
                registry_hash=registry_hash,
                registry_hash_match=registry_hash_match,
                validated_keys=list(validated),
                apply_actions=apply_actions,
                restart_required=restart_required,
                blocked_reasons=blocked_reasons,
                warnings=node_warnings,
            )
        )

    if not targets:
        warnings.append("No configured or reporting fleet nodes were found for this dry-run plan.")

    blocked_count = len([plan for plan in node_plans if plan.status != "planned"])
    return FleetRuntimeEnvPlanResponse(
        success=True,
        dry_run=True,
        mutation_enabled=False,
        mutation_policy="Fleet-wide env mutation is dry-run only. Use single-node env inspection/editing for field repair, then promote stable changes into the fleet source of truth.",
        registry_version=registry.version,
        registry_hash=registry.content_hash,
        validated_keys=list(validated),
        apply_actions=apply_actions,
        target_count=len(node_plans),
        blocked_count=blocked_count,
        node_plans=node_plans,
        warnings=warnings,
    )


def _gcs_env_restart_required(values: dict[str, str]) -> bool:
    registry = load_env_registry()
    for entry in registry.list_entries(scope="gcs", include_hidden=False):
        if entry.restart_required != "gcs" and entry.apply_action != "restart_gcs":
            continue
        if entry.name not in values:
            continue
        if os.environ.get(entry.name) != values[entry.name]:
            return True
    return False


def _resolve_requested_runtime_mode(payload: GCSConfigUpdateRequest | None) -> str | None:
    if payload is None:
        return None

    requested_mode = None
    if payload.mode is not None:
        requested_mode = _normalize_runtime_mode_value(payload.mode)
        if requested_mode not in {"real", "sitl"}:
            raise HTTPException(status_code=422, detail="mode must be either 'real' or 'sitl'")

    if payload.sim_mode is None:
        return requested_mode

    requested_from_bool = "sitl" if payload.sim_mode else "real"
    if requested_mode is not None and requested_mode != requested_from_bool:
        raise HTTPException(status_code=422, detail="mode and sim_mode describe different runtime modes")
    return requested_from_bool


def _resolve_configured_runtime_mode(config_values: dict[str, str], fallback_mode: str) -> str:
    configured_mode = _normalize_runtime_mode_value(config_values.get("MDS_MODE"))
    return configured_mode or fallback_mode


def _resolve_configured_git_auto_push(config_values: dict[str, str], fallback_value: bool) -> bool:
    return as_bool(config_values.get("MDS_GIT_AUTO_PUSH"), default=fallback_value)


def _log_event(deps: Any, message: str, level: str = "INFO", subsystem: str = "runtime_admin") -> None:
    logger = getattr(deps, "log_system_event", None)
    if callable(logger):
        try:
            logger(message, level, subsystem)
        except TypeError:
            logger(message, level)


def _log_error(deps: Any, message: str, subsystem: str = "runtime_admin") -> None:
    logger = getattr(deps, "log_system_error", None)
    if callable(logger):
        logger(message, subsystem)


def _list_sitl_instance_count(deps: Any) -> int | None:
    service = getattr(deps, "sitl_control_service", None)
    if service is None:
        service = SitlControlService(deps.Params)

    try:
        summary = service.list_instances()
    except Exception:
        return None
    return int(getattr(summary, "total_instances", 0) or 0)


def _schedule_gcs_restart(*, target_mode: str) -> bool:
    global _LAST_RESTART_SCHEDULE_AT_MONOTONIC

    with _RESTART_SCHEDULE_LOCK:
        now = time.monotonic()
        if now - _LAST_RESTART_SCHEDULE_AT_MONOTONIC < _RESTART_DEBOUNCE_SECONDS:
            return False

        start_script = _REPO_ROOT / "app" / "linux_dashboard_start.sh"
        if not start_script.is_file():
            raise RuntimeError(f"GCS launcher not found at {start_script}")

        restart_log_path = Path(os.environ.get("MDS_GCS_RESTART_LOG", "/tmp/mds_gcs_restart.log"))
        shell_command = (
            f"sleep {max(1, int(_RESTART_DELAY_MS / 1000))}; "
            f"cd {shlex.quote(str(_REPO_ROOT))} && "
            f"{shlex.quote(str(start_script))} --prod --{shlex.quote(str(target_mode))} "
            f">>{shlex.quote(str(restart_log_path))} 2>&1"
        )
        with open(os.devnull, "rb") as devnull_in, open(os.devnull, "ab") as devnull_out:
            subprocess.Popen(
                ["bash", "-lc", shell_command],
                cwd=str(_REPO_ROOT),
                stdin=devnull_in,
                stdout=devnull_out,
                stderr=devnull_out,
                start_new_session=True,
                close_fds=True,
            )

        _LAST_RESTART_SCHEDULE_AT_MONOTONIC = now
        return True


def _build_gcs_config_response(deps: Any) -> GCSConfigResponse:
    runtime_mode = resolve_runtime_mode()
    gcs_config_path = _get_gcs_config_path()
    config_values = read_env_assignments(gcs_config_path)
    running_git_auto_push = bool(deps.Params.GIT_AUTO_PUSH)
    configured_mode = _resolve_configured_runtime_mode(config_values, runtime_mode.mode)
    configured_git_auto_push = _resolve_configured_git_auto_push(config_values, running_git_auto_push)
    sitl_instance_count = _list_sitl_instance_count(deps)

    return GCSConfigResponse(
        sim_mode=bool(runtime_mode.sim_mode),
        mode=runtime_mode.mode,
        mode_source=runtime_mode.source,
        configured_mode=configured_mode,
        configured_sim_mode=(configured_mode == "sitl"),
        gcs_port=int(deps.Params.gcs_api_port),
        git_auto_push=running_git_auto_push,
        configured_git_auto_push=configured_git_auto_push,
        acceptable_deviation=float(deps.Params.acceptable_deviation),
        gcs_config_path=str(gcs_config_path),
        gcs_config_present=gcs_config_path.is_file(),
        sitl_instance_count=sitl_instance_count,
        restart_required=(configured_mode != runtime_mode.mode or configured_git_auto_push != running_git_auto_push),
    )


def _normalize_github_docs_base(repo_url: str, branch: str) -> str | None:
    normalized = str(repo_url or "").strip()
    if normalized.startswith("git@github.com:"):
        normalized = normalized.replace("git@github.com:", "https://github.com/", 1)
    if normalized.startswith("https://github.com/") and normalized.endswith(".git"):
        normalized = normalized[:-4]
    if not normalized.startswith("https://github.com/"):
        return None
    branch_name = str(branch or "").strip() or "main"
    return f"{normalized}/blob/{branch_name}"


def _describe_repo_access_mode(repo_url: str, token_file: str, ssh_key_file: str) -> str:
    normalized = str(repo_url or "").strip()
    if normalized.startswith("git@github.com:"):
        return "ssh_key"
    if normalized.startswith("https://github.com/") and token_file:
        return "https_token_file"
    if normalized.startswith("https://github.com/"):
        return "https_public_or_read_only"
    return "custom_or_unknown"


def _build_git_auth_health(
    repo_access_mode: str,
    git_auto_push: bool,
    token_file: str | None,
    token_file_readable: bool,
    ssh_key_file: str | None,
    ssh_key_file_readable: bool,
) -> RuntimeGitAuthHealthResponse:
    issues: list[str] = []

    if repo_access_mode == "https_token_file" and not token_file_readable:
        issues.append("HTTPS token-file mode is selected but the configured token file is missing or unreadable.")
    if repo_access_mode == "ssh_key" and not ssh_key_file_readable:
        issues.append("SSH-key mode is selected but the configured SSH key file is missing or unreadable.")
    if git_auto_push and repo_access_mode == "https_public_or_read_only":
        issues.append("Git auto-push is enabled, but the current HTTPS repo posture is read-only; write-back will fail.")
    if git_auto_push and repo_access_mode == "custom_or_unknown":
        issues.append("Git auto-push is enabled, but the current repo/auth posture is custom or unknown; verify write access explicitly.")

    if issues:
        status = "error" if any("missing or unreadable" in issue for issue in issues) else "warning"
    else:
        status = "healthy"

    if status == "healthy":
        if repo_access_mode == "https_token_file":
            summary = "HTTPS token-file access is configured and readable."
        elif repo_access_mode == "ssh_key":
            summary = "SSH-key access is configured and readable."
        elif repo_access_mode == "https_public_or_read_only":
            summary = "HTTPS read-only/public access is active; this is safe when auto-push is disabled."
        else:
            summary = "Runtime git auth posture does not report any immediate issues."
    elif status == "warning":
        summary = "Runtime git auth posture is usable but needs operator attention."
    else:
        summary = "Runtime git auth posture is broken for the currently selected access mode."

    return RuntimeGitAuthHealthResponse(status=status, summary=summary, issues=issues)


def _build_runtime_repo_sync_status_from_report(report: dict[str, Any] | None) -> RuntimeRepoSyncStatusResponse:
    report = report or {}
    branch = str(report.get("branch") or "unknown")
    commit = str(report.get("commit") or "")
    remote_url = report.get("remote_url")
    tracking_branch = report.get("tracking_branch") or None
    status = str(report.get("status") or "unknown")
    commits_ahead = int(report.get("commits_ahead") or 0)
    commits_behind = int(report.get("commits_behind") or 0)

    if status == "dirty":
        update_readiness = "blocked_dirty"
        update_summary = "Local working tree has uncommitted changes; controlled fast-forward update is unsafe."
        fast_forward_update_available = False
    elif commits_ahead > 0 and commits_behind > 0:
        update_readiness = "divergent"
        update_summary = "Local checkout diverged from its tracking branch; manual reconciliation is required."
        fast_forward_update_available = False
    elif commits_ahead > 0:
        update_readiness = "local_ahead"
        update_summary = "Local checkout is ahead of its tracking branch; automatic reset/pull would discard local history."
        fast_forward_update_available = False
    elif commits_behind > 0:
        update_readiness = "ready_to_fast_forward"
        update_summary = f"Tracking branch is ahead by {commits_behind} commit(s); a controlled fast-forward update is available."
        fast_forward_update_available = True
    elif tracking_branch:
        update_readiness = "up_to_date"
        update_summary = "Local checkout matches its tracking branch."
        fast_forward_update_available = False
    else:
        update_readiness = "no_tracking_branch"
        update_summary = "No tracking branch is configured; update readiness must be evaluated manually."
        fast_forward_update_available = False

    return RuntimeRepoSyncStatusResponse(
        branch=branch,
        commit=commit,
        remote_url=remote_url,
        tracking_branch=tracking_branch,
        status=status,
        commits_ahead=commits_ahead,
        commits_behind=commits_behind,
        update_readiness=update_readiness,
        update_summary=update_summary,
        fast_forward_update_available=fast_forward_update_available,
    )


def _build_runtime_repo_sync_status(deps: Any) -> RuntimeRepoSyncStatusResponse:
    try:
        report = deps.get_gcs_git_report() or {}
    except Exception:
        report = {}
    return _build_runtime_repo_sync_status_from_report(report)


def _run_repo_command(args: list[str], *, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _refresh_repo_sync_status(deps: Any) -> RuntimeRepoSyncStatusResponse:
    report = deps.get_gcs_git_report() or {}
    tracking_branch = str(report.get("tracking_branch") or "").strip()
    if tracking_branch:
        remote_name = tracking_branch.split("/", 1)[0] or "origin"
    else:
        remote_name = "origin"

    fetch_result = _run_repo_command(["git", "fetch", "--prune", remote_name], timeout=30)
    if fetch_result.returncode != 0:
        stderr = (fetch_result.stderr or fetch_result.stdout or "").strip()
        raise RuntimeError(stderr or f"git fetch failed for remote {remote_name}")

    refreshed_report = deps.get_gcs_git_report() or {}
    return _build_runtime_repo_sync_status_from_report(refreshed_report)


def _list_pending_update_paths(tracking_branch: str | None) -> list[str]:
    normalized_tracking = str(tracking_branch or "").strip()
    if not normalized_tracking:
        return []

    result = _run_repo_command(["git", "diff", "--name-only", f"HEAD..{normalized_tracking}"], timeout=15)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(stderr or f"git diff failed for {normalized_tracking}")

    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _resolve_target_commit(tracking_branch: str | None) -> str | None:
    normalized_tracking = str(tracking_branch or "").strip()
    if not normalized_tracking:
        return None

    result = _run_repo_command(["git", "rev-parse", normalized_tracking], timeout=10)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _blocked_gcs_update_paths(paths: list[str]) -> list[str]:
    blocked: list[str] = []
    for raw_path in paths:
        normalized = str(raw_path or "").strip().lstrip("./")
        if not normalized:
            continue
        if any(normalized.startswith(prefix) for prefix in _GCS_RUNTIME_UPDATE_BLOCKED_PREFIXES):
            blocked.append(normalized)
            continue
        if Path(normalized).name in _GCS_RUNTIME_UPDATE_BLOCKED_BASENAMES:
            blocked.append(normalized)
    return blocked


def _schedule_gcs_runtime_update(*, target_mode: str, tracking_branch: str) -> bool:
    global _LAST_UPDATE_SCHEDULE_AT_MONOTONIC

    with _UPDATE_SCHEDULE_LOCK:
        now = time.monotonic()
        if now - _LAST_UPDATE_SCHEDULE_AT_MONOTONIC < _UPDATE_DEBOUNCE_SECONDS:
            return False

        if not _GCS_RUNTIME_UPDATE_SCRIPT.is_file():
            raise RuntimeError(f"GCS runtime update script not found at {_GCS_RUNTIME_UPDATE_SCRIPT}")

        update_log_path = Path(os.environ.get("MDS_GCS_UPDATE_LOG", "/tmp/mds_gcs_update.log"))
        env = os.environ.copy()
        env["MDS_GCS_UPDATE_LOG"] = str(update_log_path)
        env["MDS_GCS_UPDATE_RESTART_DELAY_SECONDS"] = str(max(1, int(_UPDATE_DELAY_MS / 1000)))

        with open(os.devnull, "rb") as devnull_in, open(os.devnull, "ab") as devnull_out:
            subprocess.Popen(
                [str(_GCS_RUNTIME_UPDATE_SCRIPT), tracking_branch, target_mode],
                cwd=str(_REPO_ROOT),
                stdin=devnull_in,
                stdout=devnull_out,
                stderr=devnull_out,
                start_new_session=True,
                close_fds=True,
                env=env,
            )

        _LAST_UPDATE_SCHEDULE_AT_MONOTONIC = now
        return True


def _build_mavlink_runtime_status(deployment_profile: Any) -> RuntimeMavlinkRuntimeResponse:
    return RuntimeMavlinkRuntimeResponse(**build_mavlink_runtime_summary(_REPO_ROOT))


def _build_connectivity_runtime_status(deployment_profile: Any) -> RuntimeConnectivityRuntimeResponse:
    return RuntimeConnectivityRuntimeResponse(**build_connectivity_runtime_summary(_REPO_ROOT))


def _build_runtime_status_response(deps: Any) -> RuntimeStatusResponse:
    runtime_mode = resolve_runtime_mode()
    deployment_profile = load_deployment_profile()
    repo_url = str(getattr(deps.Params, "GIT_REPO_URL", os.environ.get("MDS_REPO_URL", "")) or "")
    repo_branch = str(getattr(deps.Params, "GIT_BRANCH", os.environ.get("MDS_BRANCH", "")) or "")
    install_dir = os.environ.get("MDS_INSTALL_DIR") or None
    gcs_config_path = str(_get_gcs_config_path())
    gcs_config_values = read_env_assignments(Path(gcs_config_path))
    git_auth_token_file = os.environ.get("MDS_GIT_AUTH_TOKEN_FILE") or None
    git_ssh_key_file = os.environ.get("MDS_GIT_SSH_KEY_FILE") or None
    docs_base = _normalize_github_docs_base(repo_url, repo_branch)
    repo_access_mode = _describe_repo_access_mode(repo_url, git_auth_token_file or "", git_ssh_key_file or "")
    configured_mode = _resolve_configured_runtime_mode(gcs_config_values, runtime_mode.mode)
    running_git_auto_push = bool(deps.Params.GIT_AUTO_PUSH)
    configured_git_auto_push = _resolve_configured_git_auto_push(gcs_config_values, running_git_auto_push)
    sitl_instance_count = _list_sitl_instance_count(deps)

    docs = RuntimeDocsResponse(
        mds_init_setup=f"{docs_base}/docs/guides/mds-init-setup.md" if docs_base else None,
        gcs_auth=f"{docs_base}/docs/guides/gcs-auth.md" if docs_base else None,
        fleet_sync_and_secrets=f"{docs_base}/docs/guides/fleet-sync-and-secrets.md" if docs_base else None,
        mavlink_routing_setup=f"{docs_base}/docs/guides/mavlink-routing-setup.md" if docs_base else None,
        git_sync_feature=f"{docs_base}/docs/features/git-sync.md" if docs_base else None,
    )

    return RuntimeStatusResponse(
        version=str(getattr(deps, "MDS_VERSION", "unknown")),
        timestamp=int(time.time() * 1000),
        uptime_seconds=max(0.0, time.monotonic() - _PROCESS_START_MONOTONIC),
        mode=runtime_mode.mode,
        mode_source=runtime_mode.source,
        sim_mode=bool(runtime_mode.sim_mode),
        gcs_port=int(deps.Params.gcs_api_port),
        acceptable_deviation=float(deps.Params.acceptable_deviation),
        repo_url=repo_url,
        repo_branch=repo_branch,
        repo_access_mode=repo_access_mode,
        git_auto_push=running_git_auto_push,
        configured_mode=configured_mode,
        configured_sim_mode=(configured_mode == "sitl"),
        configured_git_auto_push=configured_git_auto_push,
        restart_required=(configured_mode != runtime_mode.mode or configured_git_auto_push != running_git_auto_push),
        sitl_instance_count=sitl_instance_count,
        install_dir=install_dir,
        gcs_config_path=gcs_config_path,
        gcs_config_present=os.path.isfile(gcs_config_path),
        git_auth_token_file=git_auth_token_file,
        git_auth_token_file_readable=bool(git_auth_token_file and os.path.isfile(git_auth_token_file)),
        git_ssh_key_file=git_ssh_key_file,
        git_ssh_key_file_readable=bool(git_ssh_key_file and os.path.isfile(git_ssh_key_file)),
        git_auth_health=_build_git_auth_health(
            repo_access_mode=repo_access_mode,
            git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
            token_file=git_auth_token_file,
            token_file_readable=bool(git_auth_token_file and os.path.isfile(git_auth_token_file)),
            ssh_key_file=git_ssh_key_file,
            ssh_key_file_readable=bool(git_ssh_key_file and os.path.isfile(git_ssh_key_file)),
        ),
        repo_sync_status=_build_runtime_repo_sync_status(deps),
        fleet_defaults=RuntimeFleetDefaultsResponse(
            profile_id=deployment_profile.profile_id,
            profile_source=deployment_profile.source,
            connectivity_backend=deployment_profile.connectivity_backend,
            smart_wifi_manager_repo_url_https=deployment_profile.smart_wifi_manager_repo_url_https,
            smart_wifi_manager_ref=deployment_profile.smart_wifi_manager_ref,
            smart_wifi_manager_mode=deployment_profile.smart_wifi_manager_mode,
            smart_wifi_manager_import_mode=deployment_profile.smart_wifi_manager_import_mode,
            smart_wifi_manager_install_dir=deployment_profile.smart_wifi_manager_install_dir,
            smart_wifi_manager_dashboard_listen=deployment_profile.smart_wifi_manager_dashboard_listen,
            smart_wifi_manager_profile_path=deployment_profile.smart_wifi_manager_profile_path,
            mavlink_management_mode=deployment_profile.mavlink_management_mode,
            mavlink_anywhere_repo_url_https=deployment_profile.mavlink_anywhere_repo_url_https,
            mavlink_anywhere_ref=deployment_profile.mavlink_anywhere_ref,
            mavlink_anywhere_install_dir=deployment_profile.mavlink_anywhere_install_dir,
            mavlink_anywhere_dashboard_listen=deployment_profile.mavlink_anywhere_dashboard_listen,
            mavlink_anywhere_skip_dashboard=deployment_profile.mavlink_anywhere_skip_dashboard,
        ),
        mavlink_runtime=_build_mavlink_runtime_status(deployment_profile),
        connectivity_runtime=_build_connectivity_runtime_status(deployment_profile),
        docs=docs,
    )


def create_management_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/system/gcs-config", response_model=GCSConfigResponse, tags=["GCS Management"])
    async def get_gcs_config():
        """Get the current GCS runtime configuration surface exposed to the UI."""
        try:
            return _build_gcs_config_response(deps)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/system/runtime-status", response_model=RuntimeStatusResponse, tags=["GCS Management"])
    async def get_runtime_status():
        """Get the canonical runtime/admin status surface exposed to operators and agents."""
        try:
            return _build_runtime_status_response(deps)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/system/env/registry", response_model=EnvRegistryResponse, tags=["GCS Management"])
    async def get_env_registry():
        """Get the canonical MDS environment-variable registry."""
        try:
            return EnvRegistryResponse(**load_env_registry().public_payload())
        except EnvRegistryError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/system/env/gcs", response_model=GCSRuntimeEnvResponse, tags=["GCS Management"])
    async def get_gcs_env():
        """Get GCS host-local env posture with registry metadata."""
        try:
            return _build_gcs_env_response()
        except EnvRegistryError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/system/env/gcs", response_model=GCSRuntimeEnvUpdateResponse, tags=["GCS Management"])
    async def update_gcs_env(payload: GCSRuntimeEnvUpdateRequest):
        """Persist registry-approved host-local GCS env keys."""
        try:
            updates = payload.updates or {}
            validated, warnings, apply_actions, restart_required = _validate_gcs_env_updates(updates)
            config_path = _get_gcs_config_path()
            changed_keys: list[str] = []
            if not payload.dry_run and validated:
                changed_keys = _persist_env_updates(config_path, validated)
            return GCSRuntimeEnvUpdateResponse(
                success=True,
                dry_run=bool(payload.dry_run),
                config_path=str(config_path),
                updated_keys=list(validated),
                changed_keys=changed_keys,
                restart_required=bool(restart_required and (payload.dry_run or changed_keys)),
                apply_actions=apply_actions,
                warnings=warnings,
            )
        except HTTPException:
            raise
        except EnvRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/system/env/fleet/plan", response_model=FleetRuntimeEnvPlanResponse, tags=["GCS Management"])
    async def plan_fleet_env(payload: FleetRuntimeEnvPlanRequest):
        """Dry-run registry-approved node env changes without mutating drones."""
        try:
            return _build_fleet_env_plan_response(deps, payload)
        except HTTPException:
            raise
        except EnvRegistryError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/system/env/fleet/nodes/{hw_id}", response_model=FleetRuntimeEnvNodeResponse, tags=["GCS Management"])
    async def get_fleet_node_env(hw_id: str, include_hidden: bool = False):
        """Proxy one reachable node's registry-backed env values through the GCS."""
        try:
            endpoint, payload = await _proxy_node_env_request(
                deps,
                hw_id,
                method="GET",
                include_hidden=include_hidden,
            )
            return FleetRuntimeEnvNodeResponse(
                hw_id=str(hw_id),
                endpoint=endpoint,
                reachable=True,
                **payload,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/system/env/fleet/nodes/{hw_id}", response_model=FleetRuntimeEnvNodeUpdateResponse, tags=["GCS Management"])
    async def update_fleet_node_env(hw_id: str, payload: GCSRuntimeEnvUpdateRequest):
        """Proxy registry-approved single-node env edits through the GCS."""
        try:
            endpoint, node_payload = await _proxy_node_env_request(
                deps,
                hw_id,
                method="PUT",
                payload=payload.model_dump(),
            )
            return FleetRuntimeEnvNodeUpdateResponse(
                hw_id=str(hw_id),
                endpoint=endpoint,
                **node_payload,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/system/env/gcs/apply", response_model=GCSRuntimeEnvApplyResponse, tags=["GCS Management"])
    async def apply_gcs_env():
        """Apply persisted GCS env changes by scheduling a clean GCS restart when needed."""
        try:
            runtime_mode = resolve_runtime_mode()
            config_values = read_env_assignments(_get_gcs_config_path())
            restart_required = _gcs_env_restart_required(config_values)
            if not restart_required:
                return GCSRuntimeEnvApplyResponse(
                    success=True,
                    status="no_restart_required",
                    message="Running GCS env already matches persisted restart-sensitive values.",
                    restart_required=False,
                    scheduled=False,
                    restart_delay_ms=0,
                    warnings=[],
                )

            configured_mode = _resolve_configured_runtime_mode(config_values, runtime_mode.mode)
            scheduled = _schedule_gcs_restart(target_mode=configured_mode)
            if not scheduled:
                return GCSRuntimeEnvApplyResponse(
                    success=True,
                    status="already_scheduled",
                    message="A GCS env apply restart was already scheduled.",
                    restart_required=True,
                    scheduled=False,
                    restart_delay_ms=_RESTART_DELAY_MS,
                    warnings=[],
                )

            _log_event(deps, f"GCS env apply restart scheduled (mode={configured_mode})")
            return GCSRuntimeEnvApplyResponse(
                success=True,
                status="scheduled",
                message="GCS restart scheduled to apply persisted environment changes.",
                restart_required=True,
                scheduled=True,
                restart_delay_ms=_RESTART_DELAY_MS,
                warnings=[],
            )
        except Exception as exc:
            _log_error(deps, f"GCS env apply failed: {exc}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put("/api/v1/system/gcs-config", response_model=GCSConfigSaveResponse, tags=["GCS Management"])
    async def save_gcs_config(payload: GCSConfigUpdateRequest | None = None):
        """Persist the safe host-local GCS config subset."""
        try:
            requested_mode = _resolve_requested_runtime_mode(payload)
            warnings: list[str] = []
            updates: dict[str, Any] = {}

            if requested_mode is not None:
                updates["MDS_MODE"] = requested_mode

            if payload is not None and payload.git_auto_push is not None:
                updates["MDS_GIT_AUTO_PUSH"] = bool(payload.git_auto_push)

            unsupported_fields: list[str] = []
            if payload is not None and payload.gcs_port is not None:
                unsupported_fields.append("gcs_port")
            if payload is not None and payload.acceptable_deviation is not None:
                unsupported_fields.append("acceptable_deviation")
            if unsupported_fields:
                warnings.append(
                    "The following fields are not host-local runtime settings and were not persisted here: "
                    + ", ".join(sorted(unsupported_fields))
                    + ". Manage them through the canonical fleet/runtime config flow instead."
                )

            gcs_config_path = _get_gcs_config_path()
            changed_keys = _persist_env_updates(gcs_config_path, updates) if updates else []
            config_values = read_env_assignments(gcs_config_path)
            runtime_mode = resolve_runtime_mode()
            running_git_auto_push = bool(deps.Params.GIT_AUTO_PUSH)
            configured_mode = _resolve_configured_runtime_mode(
                config_values,
                updates.get("MDS_MODE", runtime_mode.mode),
            )
            configured_git_auto_push = _resolve_configured_git_auto_push(
                config_values,
                updates.get("MDS_GIT_AUTO_PUSH", running_git_auto_push),
            )
            restart_required = (
                configured_mode != runtime_mode.mode or configured_git_auto_push != running_git_auto_push
            )

            if not updates:
                status = "no_changes"
                message = "No supported host-local GCS settings were provided."
            elif changed_keys:
                status = "success"
                message = "Host-local GCS settings were persisted. Restart the GCS runtime to apply them."
            else:
                status = "success"
                message = "Requested host-local GCS settings already matched the persisted config."

            return GCSConfigSaveResponse(
                success=True,
                status=status,
                message=message,
                persisted=bool(changed_keys),
                config_path=str(gcs_config_path),
                updated_keys=changed_keys,
                configured_mode=configured_mode,
                configured_git_auto_push=configured_git_auto_push,
                restart_required=restart_required,
                warnings=warnings,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/system/gcs-config/apply", response_model=GCSConfigApplyResponse, tags=["GCS Management"])
    async def apply_gcs_config():
        """Apply the persisted host-local runtime config by scheduling a clean GCS restart."""
        try:
            runtime_mode = resolve_runtime_mode()
            gcs_config_path = _get_gcs_config_path()
            config_values = read_env_assignments(gcs_config_path)
            running_git_auto_push = bool(deps.Params.GIT_AUTO_PUSH)
            configured_mode = _resolve_configured_runtime_mode(config_values, runtime_mode.mode)
            configured_git_auto_push = _resolve_configured_git_auto_push(config_values, running_git_auto_push)
            restart_required = (
                configured_mode != runtime_mode.mode or configured_git_auto_push != running_git_auto_push
            )
            warnings: list[str] = []

            if not restart_required:
                return GCSConfigApplyResponse(
                    success=True,
                    status="no_restart_required",
                    message="Running GCS runtime already matches the persisted host-local config.",
                    configured_mode=configured_mode,
                    configured_git_auto_push=configured_git_auto_push,
                    restart_required=False,
                    scheduled=False,
                    restart_delay_ms=0,
                    warnings=warnings,
                )

            if runtime_mode.mode == "sitl" and configured_mode == "real":
                sitl_instance_count = _list_sitl_instance_count(deps)
                if sitl_instance_count:
                    warnings.append(
                        f"{sitl_instance_count} SITL instance(s) are still running. Their mode-tagged heartbeats will be ignored after restart, but the containers themselves are not stopped automatically."
                    )

            scheduled = _schedule_gcs_restart(target_mode=configured_mode)
            if not scheduled:
                return GCSConfigApplyResponse(
                    success=True,
                    status="already_scheduled",
                    message="A GCS runtime restart was already scheduled. Wait for the launcher to recycle the session.",
                    configured_mode=configured_mode,
                    configured_git_auto_push=configured_git_auto_push,
                    restart_required=True,
                    scheduled=False,
                    restart_delay_ms=_RESTART_DELAY_MS,
                    warnings=warnings,
                )

            _log_event(
                deps,
                f"GCS runtime restart scheduled to apply host-local config (mode={configured_mode}, git_auto_push={configured_git_auto_push})",
            )
            return GCSConfigApplyResponse(
                success=True,
                status="scheduled",
                message="GCS restart scheduled. The launcher will relaunch the runtime with the persisted host-local config.",
                configured_mode=configured_mode,
                configured_git_auto_push=configured_git_auto_push,
                restart_required=True,
                scheduled=True,
                restart_delay_ms=_RESTART_DELAY_MS,
                warnings=warnings,
            )
        except Exception as exc:
            _log_error(deps, f"GCS runtime apply failed: {exc}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/system/runtime-update", response_model=GCSRuntimeUpdateResponse, tags=["GCS Management"])
    async def apply_runtime_update():
        """Schedule a constrained GCS fast-forward update when the checkout is safe to mutate in place."""
        try:
            runtime_status = _build_runtime_status_response(deps)
            current_commit = runtime_status.repo_sync_status.commit
            tracking_branch = runtime_status.repo_sync_status.tracking_branch
            warnings: list[str] = []

            if runtime_status.restart_required:
                return GCSRuntimeUpdateResponse(
                    success=True,
                    status="restart_required_first",
                    message="Persisted host-local runtime changes are waiting for apply. Restart the GCS cleanly before attempting an in-place update.",
                    update_readiness=runtime_status.repo_sync_status.update_readiness,
                    current_commit=current_commit,
                    target_commit=None,
                    tracking_branch=tracking_branch,
                    pending_paths_count=0,
                    blocked_paths=[],
                    scheduled=False,
                    restart_delay_ms=0,
                    warnings=warnings,
                )

            refreshed_sync_status = _refresh_repo_sync_status(deps)
            tracking_branch = refreshed_sync_status.tracking_branch
            target_commit = _resolve_target_commit(tracking_branch)

            if refreshed_sync_status.update_readiness != "ready_to_fast_forward":
                return GCSRuntimeUpdateResponse(
                    success=True,
                    status=refreshed_sync_status.update_readiness,
                    message=refreshed_sync_status.update_summary,
                    update_readiness=refreshed_sync_status.update_readiness,
                    current_commit=refreshed_sync_status.commit,
                    target_commit=target_commit,
                    tracking_branch=tracking_branch,
                    pending_paths_count=0,
                    blocked_paths=[],
                    scheduled=False,
                    restart_delay_ms=0,
                    warnings=warnings,
                )

            pending_paths = _list_pending_update_paths(tracking_branch)
            blocked_paths = _blocked_gcs_update_paths(pending_paths)
            if blocked_paths:
                warnings.append(
                    "Controlled GCS self-update only covers runtime-safe fast-forward changes. Frontend, launcher, tooling, and dependency changes still require a manual update path."
                )
                return GCSRuntimeUpdateResponse(
                    success=True,
                    status="manual_update_required",
                    message="Incoming changes touch frontend, launcher, tooling, or dependency surfaces. Perform a manual GCS update instead of in-place self-update.",
                    update_readiness=refreshed_sync_status.update_readiness,
                    current_commit=refreshed_sync_status.commit,
                    target_commit=target_commit,
                    tracking_branch=tracking_branch,
                    pending_paths_count=len(pending_paths),
                    blocked_paths=blocked_paths,
                    scheduled=False,
                    restart_delay_ms=0,
                    warnings=warnings,
                )

            scheduled = _schedule_gcs_runtime_update(
                target_mode=runtime_status.mode,
                tracking_branch=tracking_branch,
            )
            if not scheduled:
                return GCSRuntimeUpdateResponse(
                    success=True,
                    status="already_scheduled",
                    message="A controlled GCS update was already scheduled. Wait for the launcher to recycle the runtime.",
                    update_readiness=refreshed_sync_status.update_readiness,
                    current_commit=refreshed_sync_status.commit,
                    target_commit=target_commit,
                    tracking_branch=tracking_branch,
                    pending_paths_count=len(pending_paths),
                    blocked_paths=[],
                    scheduled=False,
                    restart_delay_ms=_UPDATE_DELAY_MS,
                    warnings=warnings,
                )

            _log_event(
                deps,
                f"Controlled GCS fast-forward update scheduled (tracking_branch={tracking_branch}, target_commit={target_commit or 'unknown'})",
            )
            return GCSRuntimeUpdateResponse(
                success=True,
                status="scheduled",
                message="Controlled GCS update scheduled. The host will fast-forward to the fetched upstream commit and relaunch through the canonical launcher.",
                update_readiness=refreshed_sync_status.update_readiness,
                current_commit=refreshed_sync_status.commit,
                target_commit=target_commit,
                tracking_branch=tracking_branch,
                pending_paths_count=len(pending_paths),
                blocked_paths=[],
                scheduled=True,
                restart_delay_ms=_UPDATE_DELAY_MS,
                warnings=warnings,
            )
        except Exception as exc:
            _log_error(deps, f"GCS runtime update failed: {exc}")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/fleet/network-details", tags=["Network"])
    async def get_network_info():
        """Get per-drone network metadata gathered from heartbeats."""
        try:
            return JSONResponse(content=deps.get_network_info_from_heartbeats())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
