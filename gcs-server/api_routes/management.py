"""GCS management and network helper routes."""

import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from schemas import (
    GCSConfigApplyResponse,
    GCSConfigResponse,
    GCSConfigSaveResponse,
    GCSConfigUpdateRequest,
    RuntimeConnectivityRuntimeResponse,
    RuntimeDocsResponse,
    RuntimeFleetDefaultsResponse,
    RuntimeGitAuthHealthResponse,
    RuntimeMavlinkRuntimeResponse,
    RuntimeRepoSyncStatusResponse,
    RuntimeStatusResponse,
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


def _get_gcs_config_path() -> Path:
    return Path(os.environ.get("MDS_GCS_SYSTEM_CONFIG", "/etc/mds/gcs.env"))


def _normalize_runtime_mode_value(value: str | None) -> str | None:
    if value is None:
        return None

    normalized = str(value).strip().lower()
    if normalized in {"real", "hardware", "production"}:
        return "real"
    if normalized in {"sitl", "sim", "simulation", "simulated"}:
        return "sitl"
    return None


def _read_env_assignments(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        return {}

    return values


def _format_env_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _persist_env_updates(path: Path, updates: dict[str, Any]) -> list[str]:
    path.parent.mkdir(parents=True, exist_ok=True)

    original_lines: list[str]
    if path.exists():
        original_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    else:
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        original_lines = [
            "# MDS GCS Configuration\n",
            f"# Updated by gcs-server runtime admin on {timestamp}\n\n",
        ]

    changed_keys: list[str] = []
    remaining_keys = {key: _format_env_value(value) for key, value in updates.items()}
    rendered_lines: list[str] = []

    for raw_line in original_lines:
        line = raw_line.rstrip("\n")
        stripped = line.strip()

        if stripped and not stripped.startswith("#") and "=" in line:
            key, _, current_value = line.partition("=")
            env_key = key.strip()
            if env_key in remaining_keys:
                desired_value = remaining_keys.pop(env_key)
                normalized_current = current_value.strip().strip('"').strip("'")
                if normalized_current != desired_value:
                    changed_keys.append(env_key)
                    rendered_lines.append(f"{env_key}={desired_value}\n")
                else:
                    rendered_lines.append(raw_line if raw_line.endswith("\n") else f"{raw_line}\n")
                continue

        rendered_lines.append(raw_line if raw_line.endswith("\n") else f"{raw_line}\n")

    if remaining_keys:
        if rendered_lines and rendered_lines[-1].strip():
            rendered_lines.append("\n")
        for env_key, desired_value in remaining_keys.items():
            changed_keys.append(env_key)
            rendered_lines.append(f"{env_key}={desired_value}\n")

    if not changed_keys:
        return []

    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text("".join(rendered_lines), encoding="utf-8")
    if path.exists():
        try:
            shutil.copymode(path, temp_path)
        except OSError:
            pass
    else:
        temp_path.chmod(0o644)
    temp_path.replace(path)
    return changed_keys


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
    return _as_bool(config_values.get("MDS_GIT_AUTO_PUSH"), default=fallback_value)


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
    config_values = _read_env_assignments(gcs_config_path)
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
    branch_name = str(branch or "").strip() or "main-candidate"
    return f"{normalized}/blob/{branch_name}"


def _normalize_github_repo_web_url(repo_url: str, ref: str) -> str | None:
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


def _describe_repo_access_mode(repo_url: str, token_file: str, ssh_key_file: str) -> str:
    normalized = str(repo_url or "").strip()
    if normalized.startswith("git@github.com:"):
        return "ssh_key"
    if normalized.startswith("https://github.com/") and token_file:
        return "https_token_file"
    if normalized.startswith("https://github.com/"):
        return "https_public_or_read_only"
    return "custom_or_unknown"


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on", "present", "active"}


def _parse_status_output(stdout: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in str(stdout or "").splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def _read_reconcile_status(script_relative_path: str) -> dict[str, str]:
    script_path = _REPO_ROOT / script_relative_path
    if not script_path.is_file():
        return {"status_source": "missing_script"}

    try:
        result = subprocess.run(
            [str(script_path), "status", "--quiet"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"status_source": "timeout"}
    except OSError:
        return {"status_source": "invoke_error"}

    data = _parse_status_output(result.stdout)
    data["status_source"] = "script" if result.returncode == 0 else "script_error"
    if result.returncode != 0 and result.stderr:
        data["error"] = result.stderr.strip()
    return data


def _resolve_repo_relative_path(path_value: str) -> str:
    normalized = str(path_value or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("/"):
        return normalized
    return str((_REPO_ROOT / normalized).resolve())


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


def _build_runtime_repo_sync_status(deps: Any) -> RuntimeRepoSyncStatusResponse:
    try:
        report = deps.get_gcs_git_report() or {}
    except Exception:
        report = {}

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


def _build_mavlink_runtime_status(deployment_profile: Any) -> RuntimeMavlinkRuntimeResponse:
    status = _read_reconcile_status("tools/reconcile_mavlink_runtime.sh")
    repo_url = status.get("repo_url") or deployment_profile.mavlink_anywhere_repo_url_https
    ref = status.get("ref") or deployment_profile.mavlink_anywhere_ref
    install_dir = status.get("install_dir") or deployment_profile.mavlink_anywhere_install_dir
    install_dir_present = Path(install_dir).is_dir()
    runtime_present = _as_bool(status.get("runtime_present"), default=Path(install_dir, ".git").is_dir())
    dashboard_listen = status.get("dashboard_listen") or deployment_profile.mavlink_anywhere_dashboard_listen
    dashboard_enabled = not _as_bool(
        status.get("skip_dashboard"),
        default=bool(deployment_profile.mavlink_anywhere_skip_dashboard),
    )

    return RuntimeMavlinkRuntimeResponse(
        status_source=status.get("status_source", "fallback"),
        management_mode=status.get("mode") or deployment_profile.mavlink_management_mode,
        repo_url=repo_url,
        ref=ref,
        repo_web_url=_normalize_github_repo_web_url(repo_url, ref),
        install_dir=install_dir,
        install_dir_present=install_dir_present,
        runtime_present=runtime_present,
        runtime_head=status.get("runtime_head") or None,
        router_binary_present=(status.get("router_binary") == "present") if "router_binary" in status else bool(shutil.which("mavlink-routerd")),
        router_service_status=status.get("router_service", "unknown"),
        dashboard_enabled=dashboard_enabled,
        dashboard_listen=dashboard_listen,
        dashboard_service_status=status.get("dashboard_service", "unknown"),
    )


def _build_connectivity_runtime_status(deployment_profile: Any) -> RuntimeConnectivityRuntimeResponse:
    status = _read_reconcile_status("tools/reconcile_connectivity.sh")
    repo_url = status.get("repo_url") or deployment_profile.smart_wifi_manager_repo_url_https
    ref = status.get("ref") or deployment_profile.smart_wifi_manager_ref
    install_dir = status.get("install_dir") or deployment_profile.smart_wifi_manager_install_dir
    install_dir_present = Path(install_dir).is_dir()
    profile_path = status.get("profile_path") or _resolve_repo_relative_path(deployment_profile.smart_wifi_manager_profile_path)

    return RuntimeConnectivityRuntimeResponse(
        status_source=status.get("status_source", "fallback"),
        backend=status.get("backend") or deployment_profile.connectivity_backend,
        repo_url=repo_url,
        ref=ref,
        repo_web_url=_normalize_github_repo_web_url(repo_url, ref),
        install_dir=install_dir,
        install_dir_present=install_dir_present,
        mode=status.get("mode") or deployment_profile.smart_wifi_manager_mode,
        import_mode=deployment_profile.smart_wifi_manager_import_mode,
        profile_path=profile_path,
        profile_present=bool(profile_path and Path(profile_path).is_file()),
        dashboard_listen=os.environ.get("MDS_SMART_WIFI_MANAGER_DASHBOARD_LISTEN") or deployment_profile.smart_wifi_manager_dashboard_listen,
        service_status=status.get("service_status", "unknown"),
    )


def _build_runtime_status_response(deps: Any) -> RuntimeStatusResponse:
    runtime_mode = resolve_runtime_mode()
    deployment_profile = load_deployment_profile()
    repo_url = str(getattr(deps.Params, "GIT_REPO_URL", os.environ.get("MDS_REPO_URL", "")) or "")
    repo_branch = str(getattr(deps.Params, "GIT_BRANCH", os.environ.get("MDS_BRANCH", "")) or "")
    install_dir = os.environ.get("MDS_INSTALL_DIR") or None
    gcs_config_path = str(_get_gcs_config_path())
    gcs_config_values = _read_env_assignments(Path(gcs_config_path))
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
            config_values = _read_env_assignments(gcs_config_path)
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
            config_values = _read_env_assignments(gcs_config_path)
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

    @router.get("/api/v1/fleet/network-details", tags=["Network"])
    async def get_network_info():
        """Get per-drone network metadata gathered from heartbeats."""
        try:
            return JSONResponse(content=deps.get_network_info_from_heartbeats())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
