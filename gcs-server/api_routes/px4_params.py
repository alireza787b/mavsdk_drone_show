"""PX4 parameter orchestration routes for the GCS API."""

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Path as PathParam

from px4_param_store import (
    build_param_diff_response,
    build_px4_param_policy_payload,
    build_snapshot_rows_response,
    fetch_snapshots_for_targets,
    get_repo_profile,
    get_snapshot,
    import_mds_patch,
    import_qgc_parameter_file,
    list_repo_profiles,
)
from px4_param_job_models import JobRequest, JobResponse, ReviewRequest, ReviewResponse
from px4_param_journal import ParamJobConflict
from px4_param_jobs import close_px4_param_engine, get_px4_param_engine
from src.gcs_api_routes import (
    GCS_PX4_PARAMS_DIFF_ROUTE,
    GCS_PX4_PARAMS_MDS_IMPORT_ROUTE,
    GCS_PX4_PARAMS_PATCH_JOB_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_PATCH_JOB_LOOKUP_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_PATCH_JOBS_ROUTE,
    GCS_PX4_PARAMS_POLICY_ROUTE,
    GCS_PX4_PARAMS_PROFILE_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_PROFILES_ROUTE,
    GCS_PX4_PARAMS_QGC_IMPORT_ROUTE,
    GCS_PX4_PARAMS_SNAPSHOT_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_SNAPSHOT_ROWS_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_SNAPSHOTS_ROUTE,
    GCS_PX4_PARAMS_REVIEWS_ROUTE,
    GCS_PX4_PARAMS_REVIEW_ROUTE_TEMPLATE,
)
from src.px4_param_models import (
    Px4ParamDiffRequest,
    Px4ParamDiffResponse,
    Px4ParamFleetSnapshotRequest,
    Px4ParamFleetSnapshotResponse,
    Px4ParamImportRequest,
    Px4ParamImportResponse,
    Px4ParamPolicyResponse,
    Px4ParamProfileListResponse,
    Px4ParamProfileResponse,
    Px4ParamSnapshotResponse,
    Px4ParamSnapshotRowsResponse,
)


def create_px4_params_router(deps: Any) -> APIRouter:
    router = APIRouter()

    @router.on_event("shutdown")
    async def close_parameter_jobs():
        await asyncio.to_thread(close_px4_param_engine, deps)

    def job_error(exc: Exception) -> HTTPException:
        if isinstance(exc, ParamJobConflict):
            return HTTPException(status_code=409, detail=str(exc))
        deps.log_system_error(f"PX4 parameter receipt engine unavailable: {exc}", "px4_params")
        return HTTPException(status_code=503, detail="PX4 parameter receipt storage or runner is unavailable")

    @router.get(GCS_PX4_PARAMS_POLICY_ROUTE, response_model=Px4ParamPolicyResponse, tags=["PX4 Parameters"])
    async def get_px4_param_policy():
        return build_px4_param_policy_payload(deps.Params)

    @router.get(GCS_PX4_PARAMS_PROFILES_ROUTE, response_model=Px4ParamProfileListResponse, tags=["PX4 Parameters"])
    async def get_px4_param_profiles():
        try:
            return list_repo_profiles(deps.Params)
        except Exception as exc:
            deps.log_system_error(f"PX4 param profile listing failed: {exc}", "px4_params")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @router.get(GCS_PX4_PARAMS_PROFILE_ROUTE_TEMPLATE, response_model=Px4ParamProfileResponse, tags=["PX4 Parameters"])
    async def get_px4_param_profile(profile_id: str = PathParam(..., description="Profile identifier")):
        try:
            profile = get_repo_profile(deps.Params, profile_id)
        except Exception as exc:
            deps.log_system_error(f"PX4 param profile load failed: {exc}", "px4_params")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        if profile is None:
            raise HTTPException(status_code=404, detail=f"PX4 param profile {profile_id} not found")
        return profile

    @router.post(GCS_PX4_PARAMS_SNAPSHOTS_ROUTE, response_model=Px4ParamFleetSnapshotResponse, tags=["PX4 Parameters"])
    async def create_px4_param_snapshots(request: Px4ParamFleetSnapshotRequest):
        try:
            return await asyncio.to_thread(fetch_snapshots_for_targets, deps, request)
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

    @router.post(GCS_PX4_PARAMS_REVIEWS_ROUTE, response_model=ReviewResponse, tags=["PX4 Parameters"])
    async def prepare_px4_param_review(request: ReviewRequest):
        try:
            return await asyncio.to_thread(lambda: get_px4_param_engine(deps).prepare(request))
        except Exception as exc:
            raise job_error(exc) from exc

    @router.get(GCS_PX4_PARAMS_REVIEW_ROUTE_TEMPLATE, response_model=ReviewResponse, tags=["PX4 Parameters"])
    async def get_px4_param_review(review_id: str = PathParam(..., max_length=160)):
        try:
            review = await asyncio.to_thread(lambda: get_px4_param_engine(deps).get_review(review_id))
        except Exception as exc:
            raise job_error(exc) from exc
        if review is None:
            raise HTTPException(status_code=404, detail="PX4 parameter review not found")
        return review

    @router.post(GCS_PX4_PARAMS_PATCH_JOBS_ROUTE, response_model=JobResponse, status_code=202, tags=["PX4 Parameters"])
    async def create_px4_param_patch_job(request: JobRequest):
        try:
            return await asyncio.to_thread(lambda: get_px4_param_engine(deps).submit(request))
        except Exception as exc:
            raise job_error(exc) from exc

    @router.get(GCS_PX4_PARAMS_PATCH_JOB_LOOKUP_ROUTE_TEMPLATE, response_model=JobResponse, tags=["PX4 Parameters"])
    async def find_px4_param_patch_job(idempotency_key: str = PathParam(..., min_length=8, max_length=160)):
        try:
            job = await asyncio.to_thread(lambda: get_px4_param_engine(deps).find_request(idempotency_key))
        except Exception as exc:
            raise job_error(exc) from exc
        if job is None:
            raise HTTPException(status_code=404, detail="PX4 parameter request has no accepted receipt")
        return job

    @router.get(GCS_PX4_PARAMS_PATCH_JOB_ROUTE_TEMPLATE, response_model=JobResponse, tags=["PX4 Parameters"])
    async def get_px4_param_patch_job(job_id: str = PathParam(..., description="Patch job identifier")):
        try:
            job = await asyncio.to_thread(lambda: get_px4_param_engine(deps).get_job(job_id))
        except Exception as exc:
            raise job_error(exc) from exc
        if job is None:
            raise HTTPException(status_code=404, detail=f"PX4 param patch job {job_id} not found")
        return job

    return router
