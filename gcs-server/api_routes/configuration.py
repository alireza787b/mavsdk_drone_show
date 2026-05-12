"""Configuration-related GCS FastAPI routes."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from fastapi.responses import JSONResponse

from schemas import (
    ConfigUpdateResponse,
    ConnectivityProfileStatusResponse,
    ConnectivityProfileUpdateRequest,
    FleetConfigEntryPayload,
)
from settings.deployment_profile import load_deployment_profile


_MAX_CONNECTIVITY_PROFILE_BYTES = 256 * 1024


def _canonical_profile_bytes(profile: dict[str, Any]) -> bytes:
    return json.dumps(profile, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _profile_hash(profile: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_profile_bytes(profile)).hexdigest()


def _summarize_connectivity_profile(profile: dict[str, Any]) -> dict[str, Any]:
    profiles = profile.get("profiles")
    network_count = len(profiles) if isinstance(profiles, list) else 0
    return {
        "profile_hash": _profile_hash(profile),
        "profile_valid": True,
        "mode": profile.get("mode") if isinstance(profile.get("mode"), str) else None,
        "network_count": network_count,
    }


def _connectivity_profile_target(deps: Any) -> tuple[Path, str, bool]:
    repo_root = Path(deps.BASE_DIR).resolve()
    profile = load_deployment_profile()
    configured_path = str(profile.smart_wifi_manager_profile_path or "deployment/connectivity/smart-wifi-manager/profile.json")
    candidate = Path(configured_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (repo_root / candidate).resolve()

    try:
        relative_path = str(resolved.relative_to(repo_root))
        dashboard_managed = True
    except ValueError:
        relative_path = configured_path
        dashboard_managed = False

    return resolved, relative_path, dashboard_managed


def _validate_connectivity_profile(profile: dict[str, Any]) -> None:
    if not isinstance(profile, dict):
        raise HTTPException(status_code=422, detail="Smart Wi-Fi profile must be a JSON object.")

    encoded = json.dumps(profile, ensure_ascii=False).encode("utf-8")
    if len(encoded) > _MAX_CONNECTIVITY_PROFILE_BYTES:
        raise HTTPException(status_code=413, detail="Smart Wi-Fi profile is too large.")

    profiles = profile.get("profiles")
    if profiles is not None:
        if not isinstance(profiles, list):
            raise HTTPException(status_code=422, detail="Smart Wi-Fi profile field 'profiles' must be a list when present.")
        for index, item in enumerate(profiles, start=1):
            if not isinstance(item, dict):
                raise HTTPException(status_code=422, detail=f"Smart Wi-Fi profile entry {index} must be an object.")
            if not str(item.get("ssid", "")).strip():
                raise HTTPException(status_code=422, detail=f"Smart Wi-Fi profile entry {index} must include a non-empty ssid.")


def _read_connectivity_profile_status(deps: Any, message: str | None = None) -> ConnectivityProfileStatusResponse:
    path, relative_path, dashboard_managed = _connectivity_profile_target(deps)
    base_payload: dict[str, Any] = {
        "profile_present": path.exists(),
        "dashboard_managed": dashboard_managed,
        "profile_path": relative_path,
        "profile_hash": None,
        "profile_valid": None,
        "mode": None,
        "network_count": None,
        "message": message or "Smart Wi-Fi fleet profile status loaded.",
    }

    if not dashboard_managed:
        base_payload["message"] = (
            "Smart Wi-Fi profile path is outside this repository; dashboard import is disabled for this path."
        )
        return ConnectivityProfileStatusResponse(**base_payload)

    if not path.exists():
        base_payload["message"] = message or "No repo-owned Smart Wi-Fi fleet profile is present yet."
        return ConnectivityProfileStatusResponse(**base_payload)

    try:
        raw = path.read_bytes()
        if len(raw) > _MAX_CONNECTIVITY_PROFILE_BYTES:
            base_payload["profile_valid"] = False
            base_payload["message"] = "Smart Wi-Fi fleet profile exists but is too large for dashboard management."
            return ConnectivityProfileStatusResponse(**base_payload)
        profile = json.loads(raw.decode("utf-8"))
        if not isinstance(profile, dict):
            base_payload["profile_valid"] = False
            base_payload["message"] = "Smart Wi-Fi fleet profile exists but is not a JSON object."
            return ConnectivityProfileStatusResponse(**base_payload)
        base_payload.update(_summarize_connectivity_profile(profile))
    except Exception as exc:
        base_payload["profile_valid"] = False
        base_payload["message"] = f"Smart Wi-Fi fleet profile exists but could not be parsed: {exc}"

    return ConnectivityProfileStatusResponse(**base_payload)


def _write_connectivity_profile(path: Path, profile: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    tmp_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _get_trajectory_start_position_payload(deps: Any, pos_id: int) -> dict[str, Any]:
    sim_mode = getattr(deps.Params, "sim_mode", False)
    north, east = deps.get_expected_position_from_trajectory(pos_id, sim_mode)

    if north is None or east is None:
        raise HTTPException(status_code=404, detail=f"Trajectory file not found for pos_id={pos_id}")

    return {
        "pos_id": pos_id,
        "x": north,
        "y": east,
        "source": f"Drone {pos_id}.csv (first waypoint)",
    }


def create_configuration_router(deps: Any) -> APIRouter:
    router = APIRouter()

    async def _reconcile_runtime_fleet() -> None:
        reconciler = getattr(deps, "reconcile_background_services", None)
        if callable(reconciler):
            await reconciler()

    @router.get("/api/v1/config/fleet", response_model=list[FleetConfigEntryPayload], tags=["Configuration"])
    async def get_config():
        """Get current drone configuration."""
        try:
            return deps.load_config()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error loading configuration: {exc}") from exc

    @router.put("/api/v1/config/fleet", response_model=ConfigUpdateResponse, tags=["Configuration"])
    async def save_config_route(
        config_data: list[FleetConfigEntryPayload],
        commit: bool | None = Query(None),
    ):
        """Validate and save drone configuration."""
        try:
            if not config_data:
                raise HTTPException(status_code=400, detail="No configuration data provided")

            deps.log_system_event("💾 Configuration update received", "INFO", "config")
            normalized_config = [entry.model_dump(exclude_none=True) for entry in config_data]

            sim_mode = getattr(deps.Params, "sim_mode", False)
            report = deps.validate_and_process_config(normalized_config, sim_mode)

            deps.save_config(report["updated_config"])
            await _reconcile_runtime_fleet()
            deps.log_system_event("✅ Configuration saved successfully", "INFO", "config")

            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            git_result = None
            if should_commit:
                drone_count = len(report["updated_config"])
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None,
                    deps.git_operations,
                    deps.BASE_DIR,
                    f"config: update config.json via dashboard ({drone_count} drones updated)",
                )

            return ConfigUpdateResponse(
                success=True,
                message="Configuration saved successfully",
                updated_count=len(report["updated_config"]),
                git_result=git_result,
            )
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Error saving configuration: {exc}", "config")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post("/api/v1/config/fleet/validation", tags=["Configuration"])
    async def validate_config_route(config_data: list[FleetConfigEntryPayload]):
        """Validate configuration without saving it."""
        try:
            if not config_data:
                raise HTTPException(status_code=400, detail="No configuration data provided")

            sim_mode = getattr(deps.Params, "sim_mode", False)
            report = deps.validate_and_process_config(
                [entry.model_dump(exclude_none=True) for entry in config_data],
                sim_mode,
            )
            return JSONResponse(content=report)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(
        "/api/v1/fleet/sidecars/connectivity/profile",
        response_model=ConnectivityProfileStatusResponse,
        tags=["Configuration"],
    )
    async def get_connectivity_profile_status():
        """Return a secret-safe summary of the repo-owned Smart Wi-Fi fleet profile."""
        try:
            return _read_connectivity_profile_status(deps)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.put(
        "/api/v1/fleet/sidecars/connectivity/profile",
        response_model=ConnectivityProfileStatusResponse,
        tags=["Configuration"],
    )
    async def update_connectivity_profile(request: ConnectivityProfileUpdateRequest):
        """Deprecated direct profile write route.

        Profile mutations now belong to Fleet Ops sidecar dry-run/apply routes.
        Keeping this route as a hard failure prevents old clients from silently
        bypassing confirmation.
        """
        raise HTTPException(
            status_code=410,
            detail=(
                "Direct Smart Wi-Fi profile import is disabled. Commit the approved "
                "fleet baseline under config/fleet-profiles/smart-wifi-manager/config.json "
                "and use /api/v1/fleet/sidecars/smart-wifi-manager/reconcile/dry-run "
                "followed by /api/v1/fleet/sidecars/smart-wifi-manager/reconcile/apply."
            ),
        )

    @router.get("/api/v1/config/fleet/trajectory-start-positions", tags=["Configuration"])
    async def get_drone_positions():
        """Get initial positions for all drones from trajectory CSV files."""
        try:
            return JSONResponse(content=deps.get_all_drone_positions())
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/config/fleet/trajectory-start-positions/{pos_id}", tags=["Configuration"])
    async def get_trajectory_start_position(
        pos_id: int = PathParam(..., description="Position ID"),
    ):
        """Get the first expected position from a trajectory CSV file using canonical x/y naming."""
        try:
            return JSONResponse(content=_get_trajectory_start_position_payload(deps, pos_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
