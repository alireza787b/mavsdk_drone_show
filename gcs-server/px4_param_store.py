"""GCS-side PX4 parameter snapshot orchestration."""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any

import requests

from src.drone_api_routes import DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE
from src.drone_api_routes import DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE
from src.px4_param_models import (
    Px4ParamFleetSnapshotError,
    Px4ParamFleetSnapshotRequest,
    Px4ParamFleetSnapshotResponse,
    Px4ParamPatchApplyResponse,
    Px4ParamPatchJobDroneResult,
    Px4ParamPatchJobRequest,
    Px4ParamPatchJobResponse,
    Px4ParamPolicyResponse,
    Px4ParamSnapshotResponse,
    Px4ParamSnapshotRowsResponse,
)
from src.px4_params.service import Px4ParamService


_SNAPSHOT_STORE: dict[str, Px4ParamSnapshotResponse] = {}
_SNAPSHOT_STORE_LOCK = threading.Lock()
_PATCH_JOB_STORE: dict[str, Px4ParamPatchJobResponse] = {}
_PATCH_JOB_STORE_LOCK = threading.Lock()


def build_px4_param_policy_payload(params: Any) -> Px4ParamPolicyResponse:
    return Px4ParamService(params, hw_id="gcs").build_policy()


def save_snapshot(snapshot: Px4ParamSnapshotResponse) -> None:
    with _SNAPSHOT_STORE_LOCK:
        _SNAPSHOT_STORE[snapshot.snapshot.snapshot_id] = snapshot


def save_patch_job(job: Px4ParamPatchJobResponse) -> None:
    with _PATCH_JOB_STORE_LOCK:
        _PATCH_JOB_STORE[job.job_id] = job


def get_snapshot(snapshot_id: str) -> Px4ParamSnapshotResponse | None:
    with _SNAPSHOT_STORE_LOCK:
        return _SNAPSHOT_STORE.get(snapshot_id)


def get_patch_job(job_id: str) -> Px4ParamPatchJobResponse | None:
    with _PATCH_JOB_STORE_LOCK:
        return _PATCH_JOB_STORE.get(job_id)


def build_snapshot_rows_response(snapshot_id: str) -> Px4ParamSnapshotRowsResponse | None:
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        return None
    return Px4ParamSnapshotRowsResponse(
        snapshot_id=snapshot.snapshot.snapshot_id,
        rows=snapshot.rows,
        total_rows=len(snapshot.rows),
        timestamp=int(time.time() * 1000),
    )


def fetch_snapshots_for_targets(deps: Any, request: Px4ParamFleetSnapshotRequest) -> Px4ParamFleetSnapshotResponse:
    drones = deps.load_config()
    lookup = {str(drone["hw_id"]): drone for drone in drones}
    snapshots = []
    errors = []
    timeout_sec = float(getattr(deps.Params, "PX4_PARAMETER_HTTP_TIMEOUT_SEC", 20.0))
    port = int(getattr(deps.Params, "drone_api_port", 7070))

    for hw_id in request.hw_ids:
        drone = lookup.get(str(hw_id))
        if drone is None:
            errors.append(Px4ParamFleetSnapshotError(hw_id=str(hw_id), error="Target drone not found in config"))
            continue

        ip = str(drone.get("ip", "")).strip()
        if not ip:
            errors.append(Px4ParamFleetSnapshotError(hw_id=str(hw_id), error="Target drone has no configured IP"))
            continue

        url = f"http://{ip}:{port}{DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE}"
        try:
            response = requests.post(
                url,
                json={"component_id": request.component_id},
                timeout=timeout_sec,
            )
            response.raise_for_status()
            snapshot = Px4ParamSnapshotResponse.model_validate(response.json())
            save_snapshot(snapshot)
            snapshots.append(snapshot)
        except requests.RequestException as exc:
            errors.append(Px4ParamFleetSnapshotError(hw_id=str(hw_id), error=str(exc)))
        except Exception as exc:
            errors.append(Px4ParamFleetSnapshotError(hw_id=str(hw_id), error=str(exc)))

    return Px4ParamFleetSnapshotResponse(
        snapshots=snapshots,
        errors=errors,
        total_targets=len(request.hw_ids),
        timestamp=int(time.time() * 1000),
    )


def _resolve_target_drone(deps: Any, hw_id: str) -> dict[str, Any] | None:
    drones = deps.load_config()
    lookup = {str(drone["hw_id"]): drone for drone in drones}
    return lookup.get(str(hw_id))


def _build_drone_api_url(ip: str, port: int, route: str) -> str:
    return f"http://{ip}:{port}{route}"


def _request_json(method: str, url: str, *, timeout_sec: float, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    response = requests.request(method, url, json=payload, timeout=timeout_sec)
    response.raise_for_status()
    return response.json()


def run_patch_job_for_targets(deps: Any, request: Px4ParamPatchJobRequest) -> Px4ParamPatchJobResponse:
    timeout_sec = float(getattr(deps.Params, "PX4_PARAMETER_HTTP_TIMEOUT_SEC", 20.0))
    port = int(getattr(deps.Params, "drone_api_port", 7070))
    created_at = int(time.time() * 1000)
    results: list[Px4ParamPatchJobDroneResult] = []

    for hw_id in request.hw_ids:
        drone = _resolve_target_drone(deps, hw_id)
        if drone is None:
            results.append(
                Px4ParamPatchJobDroneResult(
                    hw_id=str(hw_id),
                    applied=False,
                    verified=False,
                    error="Target drone not found in config",
                )
            )
            continue

        ip = str(drone.get("ip", "")).strip()
        if not ip:
            results.append(
                Px4ParamPatchJobDroneResult(
                    hw_id=str(hw_id),
                    applied=False,
                    verified=False,
                    error="Target drone has no configured IP",
                )
            )
            continue

        try:
            patch_payload = {
                "source": request.source.value,
                "verify_readback": request.verify_readback,
                "entries": [entry.model_dump(mode="json") for entry in request.entries],
            }
            patch_url = _build_drone_api_url(ip, port, DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE)
            patch_body = _request_json("post", patch_url, timeout_sec=timeout_sec, payload=patch_payload)
            patch_result = Px4ParamPatchApplyResponse.model_validate(patch_body)

            refresh_url = _build_drone_api_url(ip, port, DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE)
            refresh_body = _request_json(
                "post",
                refresh_url,
                timeout_sec=timeout_sec,
                payload={"component_id": request.entries[0].component_id},
            )
            save_snapshot(Px4ParamSnapshotResponse.model_validate(refresh_body))

            results.append(
                Px4ParamPatchJobDroneResult(
                    hw_id=str(hw_id),
                    applied=patch_result.failed_count == 0,
                    verified=patch_result.failed_count == 0 and patch_result.verified_count == patch_result.applied_count,
                    result=patch_result,
                )
            )
        except requests.RequestException as exc:
            results.append(
                Px4ParamPatchJobDroneResult(
                    hw_id=str(hw_id),
                    applied=False,
                    verified=False,
                    error=str(exc),
                )
            )
        except Exception as exc:
            results.append(
                Px4ParamPatchJobDroneResult(
                    hw_id=str(hw_id),
                    applied=False,
                    verified=False,
                    error=str(exc),
                )
            )

    completed_targets = sum(1 for result in results if result.error is None)
    failed_targets = sum(1 for result in results if result.error is not None or not result.applied)
    if failed_targets == 0:
        status = "completed"
    elif completed_targets == 0:
        status = "failed"
    else:
        status = "partial"

    job = Px4ParamPatchJobResponse(
        job_id=f"px4-patch-{uuid.uuid4().hex[:12]}",
        source=request.source,
        status=status,
        verify_readback=request.verify_readback,
        total_targets=len(request.hw_ids),
        completed_targets=completed_targets,
        failed_targets=failed_targets,
        results=results,
        created_at=created_at,
        completed_at=int(time.time() * 1000),
    )
    save_patch_job(job)
    return job
