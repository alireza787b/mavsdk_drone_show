"""Show-management routes extracted from the GCS FastAPI monolith."""

import asyncio
import time
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from schemas import (
    CustomShowImportResponse,
    CustomShowInfoResponse,
    ShowDeploymentRequest,
    ShowDeploymentResponse,
    ShowImportResponse,
)
from show_management import (
    build_comprehensive_metrics_payload,
    build_metrics_snapshot_payload,
    build_custom_show_info_payload,
    build_safety_report_payload,
    build_show_info_payload,
    build_trajectory_validation_payload,
    import_custom_show_csv,
    import_show_archive,
    list_show_plots_payload,
    resolve_custom_show_image_path,
    resolve_show_plot_path,
)
from src.enums import Mission


def create_show_management_router(deps: Any) -> APIRouter:
    router = APIRouter()

    def _safe_show_snapshot() -> dict[str, Any]:
        """Build a non-mutating aggregate for the Drone Show workspace."""
        package: dict[str, Any] = {"available": False}
        try:
            package = build_show_info_payload(deps.skybrush_dir)
            package["available"] = True
        except Exception:
            package = {"available": False, "drone_count": 0}

        metrics = None
        safety = None
        validation = None
        if package.get("available"):
            try:
                metrics = build_metrics_snapshot_payload(
                    metrics_available=bool(deps.METRICS_AVAILABLE),
                    load_saved_metrics_if_current_func=deps._load_saved_metrics_if_current,
                )
            except Exception:
                metrics = None
            try:
                safety = build_safety_report_payload(
                    metrics_available=bool(deps.METRICS_AVAILABLE),
                    metrics_engine_cls=deps.DroneShowMetrics,
                    processed_dir=deps.processed_dir,
                )
            except Exception:
                safety = None
            try:
                validation = build_trajectory_validation_payload(
                    metrics_available=bool(deps.METRICS_AVAILABLE),
                    metrics_engine_cls=deps.DroneShowMetrics,
                    processed_dir=deps.processed_dir,
                )
            except Exception:
                validation = None

        try:
            plots = list_show_plots_payload(deps.plots_directory)
        except Exception:
            plots = {"filenames": []}

        return {
            "package": package,
            "metrics": metrics,
            "safety": safety,
            "validation": validation,
            "plots": plots,
            "timestamp": int(time.time() * 1000),
        }

    @router.post("/api/v1/shows/skybrush/import", response_model=ShowImportResponse, tags=["Show Management"])
    async def import_show(file: UploadFile = File(...)):
        """Import and process drone show files from a SkyBrush ZIP package."""
        try:
            content = await file.read()
            loop = asyncio.get_running_loop()
            payload = await loop.run_in_executor(
                None,
                lambda: import_show_archive(
                    base_dir=deps.BASE_DIR,
                    filename=file.filename or "",
                    content=content,
                    allowed_file_func=deps.allowed_file,
                    run_formation_process_func=deps.run_formation_process,
                    clear_show_directories_func=deps.clear_show_directories,
                    git_operations_func=deps.git_operations,
                    git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
                    skybrush_dir=deps.skybrush_dir,
                    processed_dir=deps.processed_dir,
                    plots_directory=deps.plots_directory,
                    metrics_available=bool(deps.METRICS_AVAILABLE),
                    refresh_saved_show_metrics_func=lambda **kwargs: deps._refresh_saved_show_metrics(**kwargs),
                    log_event=deps.log_system_event,
                    log_warning=deps.log_system_warning,
                ),
            )
            return ShowImportResponse(**payload)
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Error importing show: {exc}", "show")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/shows/skybrush/archives/raw", tags=["Show Management"])
    async def download_raw_show():
        """Download raw imported SkyBrush files as a ZIP archive."""
        try:
            zip_file = deps.zip_directory(deps.skybrush_dir, f"{deps.BASE_DIR}/temp/raw_show")
            return FileResponse(zip_file, filename="raw_show.zip", media_type="application/zip")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error creating raw show zip: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/archives/processed", tags=["Show Management"])
    async def download_processed_show():
        """Download processed show trajectories as a ZIP archive."""
        try:
            zip_file = deps.zip_directory(deps.processed_dir, f"{deps.BASE_DIR}/temp/processed_show")
            return FileResponse(zip_file, filename="processed_show.zip", media_type="application/zip")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error creating processed show zip: {exc}") from exc

    @router.get("/api/v1/shows/skybrush", tags=["Show Management"])
    async def get_show_info():
        """Get high-level processed-show metadata for operator review."""
        try:
            return JSONResponse(content=build_show_info_payload(deps.skybrush_dir))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error reading show info: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/workspace", tags=["Show Management"])
    async def get_show_workspace():
        """Return the read-only aggregate consumed by the Drone Show workspace."""
        return JSONResponse(content=_safe_show_snapshot())

    @router.get("/api/v1/shows/operation/status", tags=["Show Management"])
    async def get_show_operation_status():
        """Return a typed, read-only live operation projection for Drone Show."""
        tracker = deps.get_command_tracker()
        active = await tracker.get_active_commands()
        show_missions = {Mission.DRONE_SHOW_FROM_CSV.value, Mission.CUSTOM_CSV_DRONE_SHOW.value}
        recovery_actions = {
            Mission.NONE.value,
            Mission.HOLD.value,
            Mission.LAND.value,
            Mission.RETURN_RTL.value,
        }
        tracked_missions = show_missions | recovery_actions
        recent = await tracker.get_recent(limit=30, mission_filter=list(tracked_missions))

        def command_sort_key(row: dict[str, Any]) -> int:
            return int(row.get("updated_at") or row.get("created_at") or 0)

        candidates = [
            row for row in [*active, *recent]
            if int(row.get("mission_type", -1)) in tracked_missions
        ]
        command = max(candidates, key=command_sort_key, default=None)

        now_ms = int(time.time() * 1000)
        telemetry = getattr(deps, "telemetry_data_all_drones", {}) or {}
        try:
            configured = deps.load_config()
        except Exception:
            configured = []
        target_ids = [str(item.get("hw_id")) for item in configured if item.get("hw_id") is not None]
        if command:
            target_ids = [str(value) for value in command.get("target_drones", target_ids)]

        fleet = []
        for hw_id in target_ids:
            row = telemetry.get(hw_id)
            if not row and str(hw_id).isdigit():
                row = telemetry.get(int(hw_id))
            row = row if isinstance(row, dict) else {}
            last_update = (
                row.get("telemetry_timestamp_ms")
                or row.get("heartbeat_last_seen")
                or row.get("preflight_last_update")
                or row.get("server_time")
                or row.get("timestamp")
            )
            try:
                numeric_update = float(last_update)
                if numeric_update < 1_000_000_000_000:
                    numeric_update *= 1000
                age_ms = max(0, now_ms - int(numeric_update))
            except (TypeError, ValueError):
                age_ms = None
            fleet.append({
                "hw_id": hw_id,
                "state": row.get("state") or row.get("flight_mode") or "unknown",
                "armed": bool(row.get("is_armed", row.get("armed", False))),
                "battery_percent": row.get("battery_remaining_percent", row.get("battery_percent")),
                "telemetry_age_ms": age_ms,
                "telemetry_fresh": age_ms is not None and age_ms < 5000,
            })

        phase = "idle"
        progress = 0
        if command:
            progress_data = command.get("progress") or {}
            phase = str(
                progress_data.get("stage")
                or command.get("phase")
                or command.get("status")
                or "unknown"
            )
            if phase == "in_progress":
                phase = "executing"
            progress = progress_data.get("percent", progress_data.get("progress_percent", 0))
            if not progress and command.get("outcome") == "completed":
                progress = 100
            if not isinstance(progress, (int, float)):
                progress = 0

        mission_type = command.get("mission_type") if command else None
        is_recovery = mission_type in recovery_actions
        if is_recovery and phase in {"completed", "terminal"}:
            phase = "idle"

        return JSONResponse(content={
            "state": (
                "active" if command and phase not in {"idle", "completed", "failed", "cancelled", "timeout", "terminal"}
                else (str(command.get("outcome") or "complete") if command else "idle")
            ),
            "phase": phase,
            "progress_percent": max(0, min(100, int(progress))),
            "command_id": command.get("command_id") if command else None,
            "mission_type": mission_type,
            "mission_name": command.get("mission_name") if command else None,
            "operation_kind": "recovery" if is_recovery else ("show" if command else None),
            "target_drone_ids": target_ids,
            "fleet": fleet,
            "command": command,
            "timestamp": now_ms,
        })

    @router.get("/api/v1/shows/custom", response_model=CustomShowInfoResponse, tags=["Show Management"])
    async def get_custom_show_info():
        """Get metadata for the active custom CSV workflow."""
        try:
            return JSONResponse(content=build_custom_show_info_payload(deps.shapes_dir))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error reading custom show info: {exc}") from exc

    @router.post("/api/v1/shows/custom/import", response_model=CustomShowImportResponse, tags=["Show Management"])
    async def import_custom_show(file: UploadFile = File(...)):
        """Upload, validate, and activate a custom per-drone replay CSV."""
        try:
            content = await file.read()
            loop = asyncio.get_running_loop()
            payload = await loop.run_in_executor(
                None,
                lambda: import_custom_show_csv(
                    base_dir=deps.BASE_DIR,
                    shapes_dir=deps.shapes_dir,
                    filename=file.filename or "",
                    content=content,
                    git_auto_push=bool(deps.Params.GIT_AUTO_PUSH),
                    inspect_custom_show_csv_func=deps._inspect_custom_show_csv,
                    generate_custom_show_preview_func=deps._generate_custom_show_preview,
                    git_operations_func=deps.git_operations,
                ),
            )
            return CustomShowImportResponse(**payload)
        except HTTPException:
            raise
        except Exception as exc:
            deps.log_system_error(f"Error importing custom show: {exc}", "show")
            raise HTTPException(status_code=500, detail=f"Error importing custom CSV: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/metrics", tags=["Show Management"])
    async def get_comprehensive_metrics():
        """Retrieve cached or recalculated comprehensive show metrics."""
        try:
            return JSONResponse(content=build_comprehensive_metrics_payload(
                metrics_available=bool(deps.METRICS_AVAILABLE),
                load_saved_metrics_if_current_func=deps._load_saved_metrics_if_current,
                refresh_saved_show_metrics_func=deps._refresh_saved_show_metrics,
            ))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error calculating comprehensive metrics: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/metrics/snapshot", tags=["Show Management"])
    async def get_metrics_snapshot():
        """Read the cached metrics snapshot without recalculating or writing metrics."""
        try:
            return JSONResponse(content=build_metrics_snapshot_payload(
                metrics_available=bool(deps.METRICS_AVAILABLE),
                load_saved_metrics_if_current_func=deps._load_saved_metrics_if_current,
            ))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error reading comprehensive metrics snapshot: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/safety-report", tags=["Show Management"])
    async def get_safety_report():
        """Get detailed safety-analysis output for the processed show."""
        try:
            return JSONResponse(content=build_safety_report_payload(
                metrics_available=bool(deps.METRICS_AVAILABLE),
                metrics_engine_cls=deps.DroneShowMetrics,
                processed_dir=deps.processed_dir,
            ))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error generating safety report: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/validation", tags=["Show Management"])
    async def validate_trajectory():
        """Run trajectory validation against the processed show package."""
        try:
            return JSONResponse(content=build_trajectory_validation_payload(
                metrics_available=bool(deps.METRICS_AVAILABLE),
                metrics_engine_cls=deps.DroneShowMetrics,
                processed_dir=deps.processed_dir,
            ))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error validating trajectory: {exc}") from exc

    @router.post("/api/v1/shows/skybrush/deployments", response_model=ShowDeploymentResponse, tags=["Show Management"])
    async def deploy_show(payload: Optional[ShowDeploymentRequest] = None):
        """Commit and push show changes for the fleet."""
        try:
            commit_message = (payload.message if payload else None) or (
                f"Deploy drone show: {deps.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )

            loop = asyncio.get_running_loop()
            git_result = await loop.run_in_executor(
                None,
                lambda: deps.git_operations(deps.BASE_DIR, commit_message),
            )

            if git_result.get("success"):
                return ShowDeploymentResponse(
                    success=True,
                    message="Show deployed successfully to drone fleet",
                    git_info=git_result,
                )

            raise HTTPException(status_code=500, detail=f"Deployment failed: {git_result.get('message')}")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error during deployment: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/plots/{filename}", tags=["Show Management"])
    async def get_show_plot_image(filename: str):
        """Get a specific generated show plot image."""
        try:
            file_path = resolve_show_plot_path(deps.plots_directory, filename)
            if not file_path.exists() or not file_path.is_file():
                raise HTTPException(status_code=404, detail="Plot image not found")
            return FileResponse(file_path)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get("/api/v1/shows/skybrush/plots", tags=["Show Management"])
    async def get_show_plots_list():
        """List available generated show plot images."""
        try:
            return JSONResponse(content=list_show_plots_payload(deps.plots_directory))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to list directory: {exc}") from exc

    @router.get("/api/v1/shows/custom/preview", tags=["Show Management"])
    async def get_custom_show_image():
        """Get the preview image for the active custom CSV show."""
        try:
            image_path = resolve_custom_show_image_path(deps.shapes_dir)
            return FileResponse(image_path, media_type="image/png")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router
