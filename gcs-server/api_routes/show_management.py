"""Show-management routes extracted from the GCS FastAPI monolith."""

import asyncio
from typing import Any

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from schemas import CustomShowImportResponse, CustomShowInfoResponse, ShowImportResponse
from show_management import (
    build_comprehensive_metrics_payload,
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


def create_show_management_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/shows/skybrush/import", response_model=ShowImportResponse, tags=["Show Management"])
    @router.post("/import-show", response_model=ShowImportResponse, tags=["Show Management"])
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
    @router.get("/download-raw-show", tags=["Show Management"])
    async def download_raw_show():
        """Download raw imported SkyBrush files as a ZIP archive."""
        try:
            zip_file = deps.zip_directory(deps.skybrush_dir, f"{deps.BASE_DIR}/temp/raw_show")
            return FileResponse(zip_file, filename="raw_show.zip", media_type="application/zip")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error creating raw show zip: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/archives/processed", tags=["Show Management"])
    @router.get("/download-processed-show", tags=["Show Management"])
    async def download_processed_show():
        """Download processed show trajectories as a ZIP archive."""
        try:
            zip_file = deps.zip_directory(deps.processed_dir, f"{deps.BASE_DIR}/temp/processed_show")
            return FileResponse(zip_file, filename="processed_show.zip", media_type="application/zip")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error creating processed show zip: {exc}") from exc

    @router.get("/api/v1/shows/skybrush", tags=["Show Management"])
    @router.get("/get-show-info", tags=["Show Management"])
    async def get_show_info():
        """Get high-level processed-show metadata for operator review."""
        try:
            return JSONResponse(content=build_show_info_payload(deps.skybrush_dir))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error reading show info: {exc}") from exc

    @router.get("/api/v1/shows/custom", response_model=CustomShowInfoResponse, tags=["Show Management"])
    @router.get("/get-custom-show-info", response_model=CustomShowInfoResponse, tags=["Show Management"])
    async def get_custom_show_info():
        """Get metadata for the active custom CSV workflow."""
        try:
            return JSONResponse(content=build_custom_show_info_payload(deps.shapes_dir))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error reading custom show info: {exc}") from exc

    @router.post("/api/v1/shows/custom/import", response_model=CustomShowImportResponse, tags=["Show Management"])
    @router.post("/import-custom-show", response_model=CustomShowImportResponse, tags=["Show Management"])
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
    @router.get("/get-comprehensive-metrics", tags=["Show Management"])
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

    @router.get("/api/v1/shows/skybrush/safety-report", tags=["Show Management"])
    @router.get("/get-safety-report", tags=["Show Management"])
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
    @router.post("/validate-trajectory", tags=["Show Management"])
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

    @router.post("/api/v1/shows/skybrush/deployments", tags=["Show Management"])
    @router.post("/deploy-show", tags=["Show Management"])
    async def deploy_show(request: Request):
        """Commit and push show changes for the fleet."""
        try:
            content_type = request.headers.get("content-type", "")
            data = await request.json() if content_type.startswith("application/json") else {}
            commit_message = data.get("message", f"Deploy drone show: {deps.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

            loop = asyncio.get_running_loop()
            git_result = await loop.run_in_executor(
                None,
                lambda: deps.git_operations(deps.BASE_DIR, commit_message),
            )

            if git_result.get("success"):
                return JSONResponse(content={
                    "success": True,
                    "message": "Show deployed successfully to drone fleet",
                    "git_info": git_result,
                })

            raise HTTPException(status_code=500, detail=f"Deployment failed: {git_result.get('message')}")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Error during deployment: {exc}") from exc

    @router.get("/api/v1/shows/skybrush/plots/{filename}", tags=["Show Management"])
    @router.get("/get-show-plots/{filename}", tags=["Show Management"])
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
    @router.get("/get-show-plots", tags=["Show Management"])
    async def get_show_plots_list():
        """List available generated show plot images."""
        try:
            return JSONResponse(content=list_show_plots_payload(deps.plots_directory))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to list directory: {exc}") from exc

    @router.get("/api/v1/shows/custom/preview", tags=["Show Management"])
    @router.get("/get-custom-show-image", tags=["Show Management"])
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
