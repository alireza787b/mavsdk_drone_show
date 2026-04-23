"""GCS management and network helper routes."""

import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from schemas import (
    GCSConfigResponse,
    GCSConfigSaveResponse,
    GCSConfigUpdateRequest,
    RuntimeConnectivityRuntimeResponse,
    RuntimeDocsResponse,
    RuntimeFleetDefaultsResponse,
    RuntimeGitAuthHealthResponse,
    RuntimeMavlinkRuntimeResponse,
    RuntimeStatusResponse,
)
from src.settings.deployment_profile import load_deployment_profile
from src.settings.runtime import resolve_runtime_mode

_PROCESS_START_MONOTONIC = time.monotonic()
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _build_gcs_config_response(deps: Any) -> GCSConfigResponse:
    return GCSConfigResponse(
        sim_mode=bool(deps.Params.sim_mode),
        gcs_port=int(deps.Params.gcs_api_port),
        git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
        acceptable_deviation=float(deps.Params.acceptable_deviation),
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
    gcs_config_path = os.environ.get("MDS_GCS_SYSTEM_CONFIG", "/etc/mds/gcs.env")
    git_auth_token_file = os.environ.get("MDS_GIT_AUTH_TOKEN_FILE") or None
    git_ssh_key_file = os.environ.get("MDS_GIT_SSH_KEY_FILE") or None
    docs_base = _normalize_github_docs_base(repo_url, repo_branch)
    repo_access_mode = _describe_repo_access_mode(repo_url, git_auth_token_file or "", git_ssh_key_file or "")

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
        git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
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
        """Stub acknowledgement for GCS config updates.

        The current UI expects an ACK surface here, but the FastAPI runtime does not
        persist Params mutations yet. Return an explicit compatibility response
        instead of pretending a durable save occurred.
        """
        try:
            del payload

            return GCSConfigSaveResponse(
                success=True,
                status="success",
                message="GCS configuration received, but persistence is not implemented in this runtime",
                persisted=False,
                warnings=[
                    "No server-side config file was changed. This endpoint remains a non-persisted stub until dedicated GCS config persistence is implemented.",
                ],
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/fleet/network-details", tags=["Network"])
    async def get_network_info():
        """Get per-drone network metadata gathered from heartbeats."""
        try:
            return JSONResponse(content=deps.get_network_info_from_heartbeats())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
