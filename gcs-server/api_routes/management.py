"""GCS management and network helper routes."""

import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from schemas import (
    GCSConfigResponse,
    GCSConfigSaveResponse,
    GCSConfigUpdateRequest,
    RuntimeDocsResponse,
    RuntimeFleetDefaultsResponse,
    RuntimeStatusResponse,
)
from src.settings.deployment_profile import load_deployment_profile
from src.settings.runtime import resolve_runtime_mode

_PROCESS_START_MONOTONIC = time.monotonic()


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


def _describe_repo_access_mode(repo_url: str, token_file: str, ssh_key_file: str) -> str:
    normalized = str(repo_url or "").strip()
    if normalized.startswith("git@github.com:"):
        return "ssh_key"
    if normalized.startswith("https://github.com/") and token_file:
        return "https_token_file"
    if normalized.startswith("https://github.com/"):
        return "https_public_or_read_only"
    return "custom_or_unknown"


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
        repo_access_mode=_describe_repo_access_mode(repo_url, git_auth_token_file or "", git_ssh_key_file or ""),
        git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
        install_dir=install_dir,
        gcs_config_path=gcs_config_path,
        gcs_config_present=os.path.isfile(gcs_config_path),
        git_auth_token_file=git_auth_token_file,
        git_auth_token_file_readable=bool(git_auth_token_file and os.path.isfile(git_auth_token_file)),
        git_ssh_key_file=git_ssh_key_file,
        git_ssh_key_file_readable=bool(git_ssh_key_file and os.path.isfile(git_ssh_key_file)),
        fleet_defaults=RuntimeFleetDefaultsResponse(
            profile_id=deployment_profile.profile_id,
            profile_source=deployment_profile.source,
            connectivity_backend=deployment_profile.connectivity_backend,
            smart_wifi_manager_repo_url_https=deployment_profile.smart_wifi_manager_repo_url_https,
            smart_wifi_manager_ref=deployment_profile.smart_wifi_manager_ref,
            mavlink_management_mode=deployment_profile.mavlink_management_mode,
            mavlink_anywhere_repo_url_https=deployment_profile.mavlink_anywhere_repo_url_https,
            mavlink_anywhere_ref=deployment_profile.mavlink_anywhere_ref,
            mavlink_anywhere_install_dir=deployment_profile.mavlink_anywhere_install_dir,
            mavlink_anywhere_dashboard_listen=deployment_profile.mavlink_anywhere_dashboard_listen,
            mavlink_anywhere_skip_dashboard=deployment_profile.mavlink_anywhere_skip_dashboard,
        ),
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
