"""Fleet candidate enrollment and replacement routes."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from src.settings.runtime import resolve_runtime_mode

from fleet_candidates import (
    FleetCandidateConflictError,
    FleetCandidateNotFoundError,
    FleetCandidateValidationError,
)
from schemas import (
    FleetCandidateAcceptRequest,
    FleetCandidateActionRequest,
    FleetCandidateAnnounceRequest,
    FleetCandidateListResponse,
    FleetCandidatePostSyncPlan,
    FleetCandidateRecoverRequest,
    FleetCandidateMutationResponse,
    FleetCandidateRecord,
    FleetCandidateReplaceRequest,
    FleetCandidateState,
)
from src.gcs_api_routes import (
    GCS_FLEET_CANDIDATE_ACCEPT_ROUTE_TEMPLATE,
    GCS_FLEET_CANDIDATE_ANNOUNCE_ROUTE,
    GCS_FLEET_CANDIDATE_IGNORE_ROUTE_TEMPLATE,
    GCS_FLEET_CANDIDATE_RECOVER_ROUTE_TEMPLATE,
    GCS_FLEET_CANDIDATE_REJECT_ROUTE_TEMPLATE,
    GCS_FLEET_CANDIDATE_REPLACE_ROUTE_TEMPLATE,
    GCS_FLEET_CANDIDATE_ROUTE_TEMPLATE,
    GCS_FLEET_CANDIDATES_ROUTE,
)


def _translate_candidate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, FleetCandidateNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, FleetCandidateConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, FleetCandidateValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _build_list_response(candidates: list[FleetCandidateRecord], *, runtime_mode_filter: str) -> FleetCandidateListResponse:
    state_counts: dict[str, int] = {}
    runtime_mode_counts: dict[str, int] = {}
    for candidate in candidates:
        state = candidate.registration_state.value
        state_counts[state] = state_counts.get(state, 0) + 1
        mode = candidate.runtime_mode or "unknown"
        runtime_mode_counts[mode] = runtime_mode_counts.get(mode, 0) + 1
    return FleetCandidateListResponse(
        candidates=candidates,
        total_candidates=len(candidates),
        state_counts=state_counts,
        runtime_mode_filter=runtime_mode_filter,
        runtime_mode_counts=runtime_mode_counts,
        timestamp=int(time.time() * 1000),
    )


def _resolve_candidate_runtime_filter(runtime_mode: str | None) -> tuple[str | None, str]:
    normalized = (runtime_mode or "current").strip().lower()
    if normalized == "current":
        current_mode = resolve_runtime_mode().mode
        return current_mode, current_mode
    if normalized in {"real", "sitl"}:
        return normalized, normalized
    if normalized == "all":
        return None, "all"
    raise HTTPException(status_code=422, detail="runtime_mode must be current, real, sitl, or all")


def _build_post_sync_plan(
    candidate: FleetCandidateRecord,
    *,
    should_commit: bool,
    git_result: dict[str, Any] | None,
) -> FleetCandidatePostSyncPlan:
    target_hw_id = candidate.hw_id
    target_pos_id = candidate.replacement_target_pos_id

    if not should_commit:
        return FleetCandidatePostSyncPlan(
            required=True,
            mode="manual_repo_sync_required",
            target_hw_id=target_hw_id,
            target_pos_id=target_pos_id,
            summary="Enrollment updated the GCS fleet manifest locally only.",
            action_hint=(
                "Commit/push the repo changes on GCS, then sync the affected node so its local runtime config matches the accepted fleet state."
            ),
        )

    if git_result and git_result.get("success") is False:
        return FleetCandidatePostSyncPlan(
            required=True,
            mode="repo_push_recovery_required",
            target_hw_id=target_hw_id,
            target_pos_id=target_pos_id,
            summary="Enrollment updated GCS state, but the repo commit/push step did not finish cleanly.",
            action_hint=(
                "Resolve the GCS git issue first, then sync the affected node after the repo reflects the new fleet state."
            ),
        )

    if git_result and git_result.get("pushed") is False:
        return FleetCandidatePostSyncPlan(
            required=True,
            mode="manual_repo_sync_required",
            target_hw_id=target_hw_id,
            target_pos_id=target_pos_id,
            summary="Enrollment updated the GCS repo locally, but auto-push is disabled on this GCS.",
            action_hint=(
                "Push the repo changes manually, then sync the affected node so its local runtime config matches GCS."
            ),
        )

    return FleetCandidatePostSyncPlan(
        required=True,
        mode="git_sync_required",
        target_hw_id=target_hw_id,
        target_pos_id=target_pos_id,
        summary="Enrollment updated GCS state, but the node still needs a repo/config sync to apply it at runtime.",
        action_hint="Run Git Sync for the affected node before relying on the new enrollment state in flight.",
    )


def _build_mutation_response(
    *,
    message: str,
    candidate: FleetCandidateRecord,
    warnings: list[str],
    should_commit: bool,
    git_result: dict[str, Any] | None,
) -> FleetCandidateMutationResponse:
    response_warnings = list(warnings)
    status = "success"
    if git_result and git_result.get("success") is False:
        status = "warning"
        git_message = git_result.get("message")
        if git_message:
            response_warnings.append(git_message)

    return FleetCandidateMutationResponse(
        status=status,
        message=message,
        candidate=candidate,
        warnings=response_warnings,
        git_result=git_result,
        post_sync=_build_post_sync_plan(candidate, should_commit=should_commit, git_result=git_result),
    )


def create_fleet_candidates_router(deps: Any) -> APIRouter:
    router = APIRouter()

    async def _reconcile_runtime_fleet(warnings: list[str]) -> None:
        reconciler = getattr(deps, "reconcile_background_services", None)
        if not callable(reconciler):
            return
        try:
            await reconciler()
        except Exception as exc:
            deps.log_system_error(f"Runtime fleet reconciliation failed: {exc}", "fleet_enrollment")
            warnings.append(f"Runtime fleet reconciliation warning: {exc}")

    @router.get(GCS_FLEET_CANDIDATES_ROUTE, response_model=FleetCandidateListResponse, tags=["Fleet Enrollment"])
    async def list_fleet_candidates(
        include_inactive: bool = Query(False, description="Include resolved candidates"),
        runtime_mode: str | None = Query(
            "current",
            description="Runtime domain to list: current, real, sitl, or all",
        ),
    ):
        try:
            runtime_filter, runtime_label = _resolve_candidate_runtime_filter(runtime_mode)
            candidates = deps.list_fleet_candidates(
                include_inactive=include_inactive,
                runtime_mode=runtime_filter,
            )
            return _build_list_response(candidates, runtime_mode_filter=runtime_label)
        except HTTPException:
            raise
        except Exception as exc:
            raise _translate_candidate_error(exc) from exc

    @router.get(GCS_FLEET_CANDIDATE_ROUTE_TEMPLATE, response_model=FleetCandidateRecord, tags=["Fleet Enrollment"])
    async def get_fleet_candidate(
        candidate_id: str = PathParam(..., description="Candidate identifier"),
    ):
        try:
            return deps.get_fleet_candidate(candidate_id)
        except Exception as exc:
            raise _translate_candidate_error(exc) from exc

    @router.post(GCS_FLEET_CANDIDATE_ANNOUNCE_ROUTE, response_model=FleetCandidateRecord, tags=["Fleet Enrollment"])
    async def announce_fleet_candidate(payload: FleetCandidateAnnounceRequest):
        try:
            return deps.announce_fleet_candidate(payload)
        except Exception as exc:
            deps.log_system_error(f"Fleet candidate announce failed: {exc}", "fleet_enrollment")
            raise _translate_candidate_error(exc) from exc

    @router.post(GCS_FLEET_CANDIDATE_ACCEPT_ROUTE_TEMPLATE, response_model=FleetCandidateMutationResponse, tags=["Fleet Enrollment"])
    async def accept_fleet_candidate(
        payload: FleetCandidateAcceptRequest,
        candidate_id: str = PathParam(..., description="Candidate identifier"),
        commit: Optional[bool] = Query(None, description="Commit and push repo changes after acceptance"),
    ):
        try:
            candidate, warnings = deps.accept_fleet_candidate(candidate_id, payload)
            await _reconcile_runtime_fleet(warnings)
            git_result = None
            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            if should_commit:
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None,
                    deps.git_operations,
                    deps.BASE_DIR,
                    f"fleet: accept candidate {candidate.hw_id} as new fleet member",
                )
            return _build_mutation_response(
                message=f"Candidate {candidate.candidate_id} accepted as a new fleet member",
                candidate=candidate,
                warnings=warnings,
                should_commit=should_commit,
                git_result=git_result,
            )
        except Exception as exc:
            deps.log_system_error(f"Fleet candidate accept failed: {exc}", "fleet_enrollment")
            raise _translate_candidate_error(exc) from exc

    @router.post(GCS_FLEET_CANDIDATE_REPLACE_ROUTE_TEMPLATE, response_model=FleetCandidateMutationResponse, tags=["Fleet Enrollment"])
    async def replace_fleet_candidate(
        payload: FleetCandidateReplaceRequest,
        candidate_id: str = PathParam(..., description="Candidate identifier"),
        commit: Optional[bool] = Query(None, description="Commit and push repo changes after replacement"),
    ):
        try:
            candidate, warnings = deps.replace_fleet_candidate(candidate_id, payload)
            await _reconcile_runtime_fleet(warnings)
            git_result = None
            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            if should_commit:
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None,
                    deps.git_operations,
                    deps.BASE_DIR,
                    f"fleet: replace hw_id {payload.target_hw_id} with candidate {candidate.hw_id}",
                )
            return _build_mutation_response(
                message=f"Candidate {candidate.candidate_id} replaced fleet member hw_id {payload.target_hw_id}",
                candidate=candidate,
                warnings=warnings,
                should_commit=should_commit,
                git_result=git_result,
            )
        except Exception as exc:
            deps.log_system_error(f"Fleet candidate replacement failed: {exc}", "fleet_enrollment")
            raise _translate_candidate_error(exc) from exc

    @router.post(GCS_FLEET_CANDIDATE_RECOVER_ROUTE_TEMPLATE, response_model=FleetCandidateMutationResponse, tags=["Fleet Enrollment"])
    async def recover_fleet_candidate(
        payload: FleetCandidateRecoverRequest,
        candidate_id: str = PathParam(..., description="Candidate identifier"),
        commit: Optional[bool] = Query(None, description="Commit and push repo changes after recovery"),
    ):
        try:
            candidate, warnings = deps.recover_fleet_candidate(candidate_id, payload)
            await _reconcile_runtime_fleet(warnings)
            git_result = None
            should_commit = commit if commit is not None else deps.Params.GIT_AUTO_PUSH
            if should_commit:
                loop = asyncio.get_running_loop()
                git_result = await loop.run_in_executor(
                    None,
                    deps.git_operations,
                    deps.BASE_DIR,
                    f"fleet: recover candidate {candidate.hw_id} into existing fleet member",
                )
            return _build_mutation_response(
                message=f"Candidate {candidate.candidate_id} recovered existing fleet member hw_id {candidate.hw_id}",
                candidate=candidate,
                warnings=warnings,
                should_commit=should_commit,
                git_result=git_result,
            )
        except Exception as exc:
            deps.log_system_error(f"Fleet candidate recovery failed: {exc}", "fleet_enrollment")
            raise _translate_candidate_error(exc) from exc

    @router.post(GCS_FLEET_CANDIDATE_REJECT_ROUTE_TEMPLATE, response_model=FleetCandidateMutationResponse, tags=["Fleet Enrollment"])
    async def reject_fleet_candidate(
        payload: FleetCandidateActionRequest | None = None,
        candidate_id: str = PathParam(..., description="Candidate identifier"),
    ):
        try:
            candidate = deps.set_fleet_candidate_state(
                candidate_id,
                FleetCandidateState.REJECTED,
                reason=(payload.reason if payload else None),
            )
            return FleetCandidateMutationResponse(
                status="success",
                message=f"Candidate {candidate.candidate_id} rejected",
                candidate=candidate,
                warnings=[],
                git_result=None,
            )
        except Exception as exc:
            raise _translate_candidate_error(exc) from exc

    @router.post(GCS_FLEET_CANDIDATE_IGNORE_ROUTE_TEMPLATE, response_model=FleetCandidateMutationResponse, tags=["Fleet Enrollment"])
    async def ignore_fleet_candidate(
        payload: FleetCandidateActionRequest | None = None,
        candidate_id: str = PathParam(..., description="Candidate identifier"),
    ):
        try:
            candidate = deps.set_fleet_candidate_state(
                candidate_id,
                FleetCandidateState.IGNORED,
                reason=(payload.reason if payload else None),
            )
            return FleetCandidateMutationResponse(
                status="success",
                message=f"Candidate {candidate.candidate_id} ignored",
                candidate=candidate,
                warnings=[],
                git_result=None,
            )
        except Exception as exc:
            raise _translate_candidate_error(exc) from exc

    return router
