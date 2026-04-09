"""GCS-side PX4 parameter snapshot orchestration."""

from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from src.drone_api_routes import DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE
from src.drone_api_routes import DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE
from src.px4_param_models import (
    Px4ParamDiffEntry,
    Px4ParamDiffRequest,
    Px4ParamDiffResponse,
    Px4ParamFleetSnapshotError,
    Px4ParamFleetSnapshotRequest,
    Px4ParamFleetSnapshotResponse,
    Px4ParamImportRequest,
    Px4ParamImportResponse,
    Px4ParamImportWarning,
    Px4ParamPatchApplyResponse,
    Px4ParamPatchEntry,
    Px4ParamPatchJobDroneResult,
    Px4ParamPatchJobRequest,
    Px4ParamPatchJobResponse,
    Px4ParamPolicyResponse,
    Px4ParamProfileListResponse,
    Px4ParamProfileResponse,
    Px4ParamProfileSummary,
    Px4ParamSnapshotResponse,
    Px4ParamSnapshotRowsResponse,
)
from src.px4_params.service import Px4ParamService


_SNAPSHOT_STORE: dict[str, Px4ParamSnapshotResponse] = {}
_SNAPSHOT_STORE_LOCK = threading.Lock()
_PATCH_JOB_STORE: dict[str, Px4ParamPatchJobResponse] = {}
_PATCH_JOB_STORE_LOCK = threading.Lock()
_MAV_PARAM_INT_TYPES = {1, 2, 3, 4, 5, 6, 7, 8}
_MAV_PARAM_FLOAT_TYPES = {9, 10}


def build_px4_param_policy_payload(params: Any) -> Px4ParamPolicyResponse:
    return Px4ParamService(params, hw_id="gcs").build_policy()


def _resolve_profile_dir(params: Any) -> Path:
    configured = getattr(params, "PX4_PARAMETER_PROFILE_DIR", "profiles/px4_params")
    path = Path(str(configured))
    if path.is_absolute():
        return path
    return Path(__file__).resolve().parents[1] / path


def _load_profile_file(profile_path: Path) -> Px4ParamProfileResponse:
    payload = json.loads(profile_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Profile {profile_path.name} must contain a JSON object")

    profile_id = str(payload.get("profile_id") or profile_path.stem).strip().lower().replace(" ", "_")
    if profile_id != profile_path.stem:
        raise ValueError(
            f"Profile id {profile_id!r} must match filename {profile_path.stem!r}"
        )

    payload = {
        **payload,
        "profile_id": profile_id,
        "updated_at": int(profile_path.stat().st_mtime * 1000),
    }
    return Px4ParamProfileResponse.model_validate(payload)


def list_repo_profiles(params: Any) -> Px4ParamProfileListResponse:
    profile_dir = _resolve_profile_dir(params)
    if not profile_dir.exists():
        return Px4ParamProfileListResponse(
            profiles=[],
            total_profiles=0,
            timestamp=int(time.time() * 1000),
        )

    profiles: list[Px4ParamProfileSummary] = []
    for profile_path in sorted(profile_dir.glob("*.json")):
        if not profile_path.is_file():
            continue
        profile = _load_profile_file(profile_path)
        profiles.append(
            Px4ParamProfileSummary(
                profile_id=profile.profile_id,
                name=profile.name,
                description=profile.description,
                source=profile.source,
                recommended_scope=profile.recommended_scope,
                tags=profile.tags,
                entry_count=len(profile.entries),
                updated_at=profile.updated_at,
            )
        )

    return Px4ParamProfileListResponse(
        profiles=profiles,
        total_profiles=len(profiles),
        timestamp=int(time.time() * 1000),
    )


def get_repo_profile(params: Any, profile_id: str) -> Px4ParamProfileResponse | None:
    normalized_profile_id = str(profile_id or "").strip().lower().replace(" ", "_")
    if not normalized_profile_id:
        return None

    profile_path = _resolve_profile_dir(params) / f"{normalized_profile_id}.json"
    if not profile_path.exists() or not profile_path.is_file():
        return None
    return _load_profile_file(profile_path)


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


def import_qgc_parameter_file(request: Px4ParamImportRequest) -> Px4ParamImportResponse:
    entries: list[Px4ParamPatchEntry] = []
    warnings: list[Px4ParamImportWarning] = []
    skipped_count = 0

    for line_number, raw_line in enumerate(str(request.content).splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = [part.strip() for part in line.split("\t")]
        if len(parts) != 5:
            parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            warnings.append(Px4ParamImportWarning(line=line_number, message="Skipping malformed parameter file row"))
            skipped_count += 1
            continue

        _, component_id_raw, name, value_raw, type_raw = parts
        try:
            component_id = int(component_id_raw)
            mav_type = int(type_raw)
        except ValueError:
            warnings.append(Px4ParamImportWarning(line=line_number, message="Skipping row with invalid component/type columns"))
            skipped_count += 1
            continue

        if mav_type in _MAV_PARAM_INT_TYPES:
            try:
                value = int(float(value_raw))
                value_type = "int"
            except ValueError:
                warnings.append(Px4ParamImportWarning(line=line_number, message=f"Skipping {name}: invalid integer value"))
                skipped_count += 1
                continue
        elif mav_type in _MAV_PARAM_FLOAT_TYPES:
            try:
                value = float(value_raw)
                value_type = "float"
            except ValueError:
                warnings.append(Px4ParamImportWarning(line=line_number, message=f"Skipping {name}: invalid float value"))
                skipped_count += 1
                continue
        else:
            warnings.append(Px4ParamImportWarning(line=line_number, message=f"Skipping {name}: unsupported MAV_PARAM_TYPE {mav_type}"))
            skipped_count += 1
            continue

        entries.append(
            Px4ParamPatchEntry(
                component_id=component_id,
                name=name,
                value_type=value_type,
                value=value,
            )
        )

    return Px4ParamImportResponse(
        source="qgc",
        entries=entries,
        warnings=warnings,
        skipped_count=skipped_count,
        total_entries=len(entries),
        timestamp=int(time.time() * 1000),
    )


def import_mds_patch(request: Px4ParamImportRequest) -> Px4ParamImportResponse:
    import json

    try:
        payload = json.loads(request.content)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid MDS patch JSON: {exc}") from exc

    raw_entries = payload.get("entries") if isinstance(payload, dict) else payload
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ValueError("MDS patch import requires a non-empty entries list")

    entries = [Px4ParamPatchEntry.model_validate(entry) for entry in raw_entries]
    return Px4ParamImportResponse(
        source="mds",
        entries=entries,
        warnings=[],
        skipped_count=0,
        total_entries=len(entries),
        timestamp=int(time.time() * 1000),
    )


def build_param_diff_response(request: Px4ParamDiffRequest) -> Px4ParamDiffResponse:
    snapshot = get_snapshot(request.snapshot_id)
    if snapshot is None:
        raise KeyError(request.snapshot_id)

    current_rows = {
        (row.component_id, row.name): row
        for row in snapshot.rows
    }
    differences = []

    for entry in request.desired_entries:
        current_row = current_rows.get((entry.component_id, entry.name))
        current_value = current_row.value if current_row else None
        changed = current_row is None or current_value != entry.value
        if changed or request.include_unchanged:
            differences.append(
                Px4ParamDiffEntry(
                    name=entry.name,
                    component_id=entry.component_id,
                    value_type=entry.value_type,
                    current_value=current_value,
                    desired_value=entry.value,
                    changed=changed,
                )
            )

    return Px4ParamDiffResponse(
        differences=differences,
        total_changed=sum(1 for difference in differences if difference.changed),
        timestamp=int(time.time() * 1000),
    )
