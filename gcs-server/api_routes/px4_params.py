"""PX4 parameter orchestration routes for the GCS API."""

from typing import Any

from fastapi import APIRouter, HTTPException, Path as PathParam

from px4_param_store import (
    build_param_diff_response,
    build_px4_param_policy_payload,
    build_snapshot_rows_response,
    fetch_snapshots_for_targets,
    get_patch_job,
    get_snapshot,
    import_mds_patch,
    import_qgc_parameter_file,
    run_patch_job_for_targets,
)
from src.gcs_api_routes import (
    GCS_PX4_PARAMS_DIFF_ROUTE,
    GCS_PX4_PARAMS_MDS_IMPORT_ROUTE,
    GCS_PX4_PARAMS_PATCH_JOB_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_PATCH_JOBS_ROUTE,
    GCS_PX4_PARAMS_POLICY_ROUTE,
    GCS_PX4_PARAMS_QGC_IMPORT_ROUTE,
    GCS_PX4_PARAMS_SNAPSHOT_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_SNAPSHOT_ROWS_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_SNAPSHOTS_ROUTE,
)
from src.px4_param_models import (
    Px4ParamDiffRequest,
    Px4ParamDiffResponse,
    Px4ParamFleetSnapshotRequest,
    Px4ParamFleetSnapshotResponse,
    Px4ParamImportRequest,
    Px4ParamImportResponse,
    Px4ParamPatchJobRequest,
    Px4ParamPatchJobResponse,
    Px4ParamPolicyResponse,
    Px4ParamSnapshotResponse,
    Px4ParamSnapshotRowsResponse,
)


def create_px4_params_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.get(GCS_PX4_PARAMS_POLICY_ROUTE, response_model=Px4ParamPolicyResponse, tags=["PX4 Parameters"])
    async def get_px4_param_policy():
        return build_px4_param_policy_payload(deps.Params)

    @router.post(GCS_PX4_PARAMS_SNAPSHOTS_ROUTE, response_model=Px4ParamFleetSnapshotResponse, tags=["PX4 Parameters"])
    async def create_px4_param_snapshots(request: Px4ParamFleetSnapshotRequest):
        try:
            return fetch_snapshots_for_targets(deps, request)
        except Exception as exc:
            deps.log_system_error(f"PX4 param snapshot orchestration failed: {exc}", "px4_params")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_PX4_PARAMS_SNAPSHOT_ROUTE_TEMPLATE, response_model=Px4ParamSnapshotResponse, tags=["PX4 Parameters"])
    async def get_px4_param_snapshot(snapshot_id: str = PathParam(..., description="Snapshot identifier")):
        snapshot = get_snapshot(snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"PX4 param snapshot {snapshot_id} not found")
        return snapshot

    @router.get(
        GCS_PX4_PARAMS_SNAPSHOT_ROWS_ROUTE_TEMPLATE,
        response_model=Px4ParamSnapshotRowsResponse,
        tags=["PX4 Parameters"],
    )
    async def get_px4_param_snapshot_rows(snapshot_id: str = PathParam(..., description="Snapshot identifier")):
        response = build_snapshot_rows_response(snapshot_id)
        if response is None:
            raise HTTPException(status_code=404, detail=f"PX4 param snapshot {snapshot_id} not found")
        return response

    @router.post(GCS_PX4_PARAMS_DIFF_ROUTE, response_model=Px4ParamDiffResponse, tags=["PX4 Parameters"])
    async def diff_px4_param_snapshot(request: Px4ParamDiffRequest):
        try:
            return build_param_diff_response(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"PX4 param snapshot {exc.args[0]} not found") from exc
        except Exception as exc:
            deps.log_system_error(f"PX4 param diff failed: {exc}", "px4_params")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.post(GCS_PX4_PARAMS_QGC_IMPORT_ROUTE, response_model=Px4ParamImportResponse, tags=["PX4 Parameters"])
    async def import_px4_param_qgc_file(request: Px4ParamImportRequest):
        try:
            return import_qgc_parameter_file(request)
        except Exception as exc:
            deps.log_system_error(f"PX4 param QGC import failed: {exc}", "px4_params")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post(GCS_PX4_PARAMS_MDS_IMPORT_ROUTE, response_model=Px4ParamImportResponse, tags=["PX4 Parameters"])
    async def import_px4_param_mds_patch(request: Px4ParamImportRequest):
        try:
            return import_mds_patch(request)
        except Exception as exc:
            deps.log_system_error(f"PX4 param MDS import failed: {exc}", "px4_params")
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post(GCS_PX4_PARAMS_PATCH_JOBS_ROUTE, response_model=Px4ParamPatchJobResponse, tags=["PX4 Parameters"])
    async def create_px4_param_patch_job(request: Px4ParamPatchJobRequest):
        try:
            return run_patch_job_for_targets(deps, request)
        except Exception as exc:
            deps.log_system_error(f"PX4 param patch job failed: {exc}", "px4_params")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_PX4_PARAMS_PATCH_JOB_ROUTE_TEMPLATE, response_model=Px4ParamPatchJobResponse, tags=["PX4 Parameters"])
    async def get_px4_param_patch_job(job_id: str = PathParam(..., description="Patch job identifier")):
        job = get_patch_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"PX4 param patch job {job_id} not found")
        return job

    return router
