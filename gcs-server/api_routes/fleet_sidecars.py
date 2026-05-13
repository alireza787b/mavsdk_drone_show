"""Fleet Ops sidecar profile-control routes.

Fleet Ops owns drone-side sidecars, profile posture, dry-run reconciliation,
and policy previews.  GCS Runtime remains host-only.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field


SIDECAR_SCHEMA = "mds.sidecar_profile.v1"
HASH_SEMANTICS = "sha256:canonical-sanitized-payload:12"
FLEET_OPS_MUTATION_TOKEN_ENV = "MDS_FLEET_OPS_MUTATION_TOKEN"
SIDECAR_PROFILE_TOKEN_ENV = "MDS_SIDECAR_PROFILE_TOKEN"
JOB_TTL_MS = 5 * 60 * 1000
POLICY_MODES = {"observe", "local", "fleet-merge", "fleet-strict"}
RECONCILE_MODES = {"fleet-merge", "fleet-strict"}
DRIFT_STATES = {
    "in_sync",
    "local_extra",
    "missing_fleet_baseline",
    "outdated",
    "unmanaged",
    "unreachable",
}

SIDECARS = {
    "smart-wifi-manager": {
        "runtime_key": "connectivity_runtime",
        "dashboard_port": 9080,
        "baseline_paths": (
            "config/fleet-profiles/smart-wifi-manager/config.json",
            "fleet_profiles/smart-wifi-manager/config.json",
            "deployment/connectivity/smart-wifi-manager/profile.json",
        ),
        "default_mode": "fleet-merge",
    },
    "mavlink-anywhere": {
        "runtime_key": "mavlink_runtime",
        "dashboard_port": 9070,
        "baseline_paths": (
            "config/fleet-profiles/mavlink-anywhere/profile.json",
            "fleet_profiles/mavlink-anywhere/profile.json",
            "deployment/mavlink-anywhere/profile.json",
        ),
        "default_mode": "local",
    },
}

_jobs: dict[str, dict[str, Any]] = {}


class PromoteDraftRequest(BaseModel):
    model_config = {"extra": "forbid"}

    node_id: str


class ReconcileDryRunRequest(BaseModel):
    model_config = {"extra": "forbid"}

    node_ids: list[str] = Field(default_factory=list)
    mode: str = "fleet-merge"


class FleetActionConfirmation(BaseModel):
    model_config = {"extra": "forbid"}

    operator: str | None = None
    acknowledged_risks: bool = False
    advanced_strict_ack: bool = False
    confirmation_token: str | None = None


class ReconcileApplyRequest(BaseModel):
    model_config = {"extra": "forbid"}

    dry_run_id: str
    confirmation: FleetActionConfirmation


class PolicyDryRunRequest(BaseModel):
    model_config = {"extra": "forbid"}

    node_ids: list[str] = Field(default_factory=list)
    mode: str


def create_fleet_sidecars_router(deps: Any) -> APIRouter:
    router = APIRouter(prefix="/api/v1/fleet/sidecars", tags=["Fleet Ops Sidecars"])

    @router.get("")
    async def list_sidecars() -> dict[str, Any]:
        return {
            "schema": SIDECAR_SCHEMA,
            "modes": sorted(POLICY_MODES),
            "drift_states": sorted(DRIFT_STATES),
            "hash_semantics": HASH_SEMANTICS,
            "sidecars": {
                key: _build_sidecar_table(deps, key)
                for key in SIDECARS
            },
            "timestamp": int(time.time() * 1000),
        }

    @router.get("/jobs/{job_id}")
    async def get_job(job_id: str) -> dict[str, Any]:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return _public_job(job, include_confirmation_token=False)

    @router.get("/{sidecar}")
    async def get_sidecar_table(sidecar: str) -> dict[str, Any]:
        _require_sidecar(sidecar)
        return _build_sidecar_table(deps, sidecar)

    @router.get("/{sidecar}/baseline")
    async def get_sidecar_baseline(sidecar: str) -> dict[str, Any]:
        _require_sidecar(sidecar)
        return _load_baseline_summary(deps, sidecar)

    @router.get("/{sidecar}/nodes/{hw_id}")
    async def get_sidecar_node(sidecar: str, hw_id: str) -> dict[str, Any]:
        _require_sidecar(sidecar)
        row = _node_row(deps, sidecar, hw_id)
        if row is None:
            raise HTTPException(status_code=404, detail="node not found")
        return row

    @router.post("/{sidecar}/promote-draft")
    async def promote_reference_draft(sidecar: str, request: PromoteDraftRequest, http_request: Request) -> dict[str, Any]:
        _require_sidecar(sidecar)
        _require_mutation_authority(http_request)
        node = _node_row(deps, sidecar, request.node_id)
        if not node:
            raise HTTPException(status_code=404, detail="node not found")
        result = _post_sidecar(deps, sidecar, node, "promote-reference-draft", {})
        return {
            "schema": SIDECAR_SCHEMA,
            "sidecar": sidecar,
            "node_id": request.node_id,
            "draft": _sanitize_public_value(result),
            "mutated_repo_baseline": False,
        }

    @router.post("/{sidecar}/reconcile/dry-run")
    async def dry_run_reconcile(sidecar: str, request: ReconcileDryRunRequest, http_request: Request) -> dict[str, Any]:
        _require_sidecar(sidecar)
        _require_mutation_authority(http_request)
        _validate_mode(request.mode)
        _validate_reconcile_mode(request.mode)
        baseline = _load_baseline_config(deps, sidecar)
        if not baseline:
            raise HTTPException(status_code=400, detail="fleet baseline is not configured")
        node_ids = _require_selected_node_ids(request.node_ids)
        job_id = f"dryrun-{uuid.uuid4().hex[:12]}"
        node_results: dict[str, Any] = {}
        for node_id in node_ids:
            node = _node_row(deps, sidecar, node_id)
            if not node:
                node_results[str(node_id)] = {"ok": False, "error": "node not found"}
                continue
            try:
                payload = {"mode": request.mode, "dry_run": True, "baseline": baseline}
                node_results[str(node_id)] = {
                    "ok": True,
                    "result": _post_sidecar(deps, sidecar, node, "import", payload),
                }
            except HTTPException as exc:
                node_results[str(node_id)] = {"ok": False, "error": exc.detail}
        job = {
            "schema": SIDECAR_SCHEMA,
            "job_id": job_id,
            "sidecar": sidecar,
            "kind": "reconcile-dry-run",
            "mode": request.mode,
            "node_ids": node_ids,
            "baseline_hash": _sanitized_hash(sidecar, baseline),
            "results": node_results,
            "created_at": int(time.time() * 1000),
            "applied": False,
        }
        job["confirmation_token"] = _job_confirmation_token(job)
        _jobs[job_id] = job
        return _public_job(job, include_confirmation_token=True)

    @router.post("/{sidecar}/reconcile/apply")
    async def apply_reconcile(sidecar: str, request: ReconcileApplyRequest, http_request: Request) -> dict[str, Any]:
        _require_sidecar(sidecar)
        _require_mutation_authority(http_request)
        job = _jobs.get(request.dry_run_id)
        if not job or job.get("sidecar") != sidecar or job.get("kind") != "reconcile-dry-run":
            raise HTTPException(status_code=404, detail="dry-run job not found")
        _validate_reconcile_mode(str(job.get("mode") or ""))
        _validate_job_confirmation(job, request.confirmation)
        current_baseline = _load_baseline_config(deps, sidecar)
        if not current_baseline or _sanitized_hash(sidecar, current_baseline) != job.get("baseline_hash"):
            raise HTTPException(status_code=409, detail="fleet baseline changed since dry-run; run a new dry-run")

        apply_results: dict[str, Any] = {}
        for node_id, node_result in job.get("results", {}).items():
            if not node_result.get("ok"):
                apply_results[node_id] = {"ok": False, "error": node_result.get("error", "dry-run failed")}
                continue
            dry_run = node_result.get("result", {})
            node = _node_row(deps, sidecar, node_id)
            if not node:
                apply_results[node_id] = {"ok": False, "error": "node not found"}
                continue
            payload = {
                "dry_run_id": dry_run.get("dry_run_id"),
                "confirmation": {
                    "operator": request.confirmation.operator,
                    "acknowledged_risks": True,
                    "advanced_strict_ack": request.confirmation.advanced_strict_ack,
                    "token": dry_run.get("confirmation_token"),
                },
            }
            try:
                apply_results[node_id] = {
                    "ok": True,
                    "result": _post_sidecar(deps, sidecar, node, "apply", payload),
                }
            except HTTPException as exc:
                apply_results[node_id] = {"ok": False, "error": exc.detail}
        job["applied"] = True
        job["applied_at"] = int(time.time() * 1000)
        job["apply_results"] = apply_results
        return {
            "schema": SIDECAR_SCHEMA,
            "job_id": request.dry_run_id,
            "sidecar": sidecar,
            "applied": True,
            "results": _sanitize_public_value(apply_results),
        }

    @router.post("/{sidecar}/policy/dry-run")
    async def dry_run_policy(sidecar: str, request: PolicyDryRunRequest, http_request: Request) -> dict[str, Any]:
        _require_sidecar(sidecar)
        _require_mutation_authority(http_request)
        _validate_mode(request.mode)
        node_ids = _require_selected_node_ids(request.node_ids)
        job_id = f"policy-{uuid.uuid4().hex[:12]}"
        job = {
            "schema": SIDECAR_SCHEMA,
            "job_id": job_id,
            "sidecar": sidecar,
            "kind": "policy-dry-run",
            "mode": request.mode,
            "node_ids": node_ids,
            "requires_confirmation": True,
            "requires_advanced_confirmation": request.mode == "fleet-strict",
            "created_at": int(time.time() * 1000),
            "applied": False,
        }
        job["confirmation_token"] = _job_confirmation_token(job)
        _jobs[job_id] = job
        return _public_job(job, include_confirmation_token=True)

    @router.post("/{sidecar}/policy/apply")
    async def apply_policy(sidecar: str, request: ReconcileApplyRequest, http_request: Request) -> dict[str, Any]:
        _require_sidecar(sidecar)
        _require_mutation_authority(http_request)
        job = _jobs.get(request.dry_run_id)
        if not job or job.get("kind") != "policy-dry-run" or job.get("sidecar") != sidecar:
            raise HTTPException(status_code=404, detail="policy dry-run job not found")
        _validate_job_confirmation(job, request.confirmation)
        policy_state = _load_policy_state(deps, sidecar)
        node_modes = policy_state.setdefault("node_modes", {})
        for node_id in job.get("node_ids", []):
            node_modes[str(node_id)] = {
                "mode": job.get("mode"),
                "updated_at": int(time.time() * 1000),
                "operator": request.confirmation.operator,
            }
        _save_policy_state(deps, sidecar, policy_state)
        job["applied"] = True
        job["applied_at"] = int(time.time() * 1000)
        return {
            "schema": SIDECAR_SCHEMA,
            "job_id": request.dry_run_id,
            "sidecar": sidecar,
            "applied": True,
            "mode": job.get("mode"),
            "node_ids": job.get("node_ids", []),
        }

    return router


def _require_sidecar(sidecar: str) -> None:
    if sidecar not in SIDECARS:
        raise HTTPException(status_code=404, detail="unsupported sidecar")


def _validate_mode(mode: str) -> None:
    if mode not in POLICY_MODES:
        raise HTTPException(status_code=400, detail="invalid sidecar mode")


def _validate_reconcile_mode(mode: str) -> None:
    if mode not in RECONCILE_MODES:
        raise HTTPException(
            status_code=400,
            detail="reconcile is only available for fleet-merge or fleet-strict modes; observe/local are inspect-only",
        )


def _require_selected_node_ids(node_ids: list[str]) -> list[str]:
    normalized = [str(node_id).strip() for node_id in (node_ids or []) if str(node_id).strip()]
    if not normalized:
        raise HTTPException(status_code=400, detail="select at least one node explicitly")
    return list(dict.fromkeys(normalized))


def _require_mutation_authority(request: Request) -> None:
    expected = os.environ.get(FLEET_OPS_MUTATION_TOKEN_ENV, "").strip()
    if not expected:
        return
    supplied = request.headers.get("x-fleet-ops-token", "").strip()
    auth_header = request.headers.get("authorization", "").strip()
    if not supplied and auth_header.lower().startswith("bearer "):
        supplied = auth_header[7:].strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid Fleet Ops mutation token")


def _validate_job_confirmation(job: dict[str, Any], confirmation: FleetActionConfirmation) -> None:
    if job.get("applied"):
        raise HTTPException(status_code=409, detail="dry-run job was already applied")
    try:
        age_ms = int(time.time() * 1000) - int(job.get("created_at"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="dry-run job timestamp is invalid; run a new dry-run")
    if age_ms < 0 or age_ms > JOB_TTL_MS:
        raise HTTPException(status_code=409, detail="dry-run job expired; run a new dry-run")
    if not confirmation.acknowledged_risks:
        raise HTTPException(status_code=400, detail="acknowledged_risks is required")
    if job.get("mode") == "fleet-strict" and not confirmation.advanced_strict_ack:
        raise HTTPException(status_code=400, detail="fleet-strict requires advanced confirmation")
    if not _confirmation_token_matches(job, confirmation.confirmation_token):
        raise HTTPException(status_code=400, detail="dry-run confirmation token is required")


def _job_confirmation_token(job: dict[str, Any]) -> str:
    seed = json.dumps(
        {
            "job_id": job.get("job_id"),
            "sidecar": job.get("sidecar"),
            "kind": job.get("kind"),
            "mode": job.get("mode"),
            "node_ids": job.get("node_ids", []),
            "baseline_hash": job.get("baseline_hash"),
            "created_at": job.get("created_at"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]


def _confirmation_token_matches(job: dict[str, Any], supplied: str | None) -> bool:
    expected = str(job.get("confirmation_token") or "")
    return bool(expected and supplied and hmac.compare_digest(str(supplied).strip(), expected))


def _public_job(job: dict[str, Any], *, include_confirmation_token: bool) -> dict[str, Any]:
    top_level_token = job.get("confirmation_token") if include_confirmation_token else None
    payload = deepcopy(job)
    payload.pop("confirmation_token", None)
    for node_result in (payload.get("results") or {}).values():
        if isinstance(node_result, dict):
            result = node_result.get("result")
            if isinstance(result, dict):
                result.pop("confirmation_token", None)
    payload = _sanitize_public_value(payload)
    if top_level_token:
        payload["confirmation_token"] = top_level_token
    return payload


def _git_snapshot(deps: Any) -> dict[str, dict[str, Any]]:
    lock = getattr(deps, "data_lock_git_status", None)
    data = getattr(deps, "git_status_data_all_drones", {})
    if lock:
        with lock:
            return deepcopy(data)
    return deepcopy(data)


def _node_row(deps: Any, sidecar: str, hw_id: str) -> dict[str, Any] | None:
    for row in _build_sidecar_table(deps, sidecar)["rows"]:
        if str(row.get("hw_id")) == str(hw_id):
            return row
    return None


def _build_sidecar_table(deps: Any, sidecar: str) -> dict[str, Any]:
    definition = SIDECARS[sidecar]
    runtime_key = definition["runtime_key"]
    git_data = _git_snapshot(deps)
    heartbeats = _safe_heartbeats(deps)
    policy_state = _load_policy_state(deps, sidecar)
    rows = []
    for drone in deps.load_config():
        hw_id = str(drone.get("hw_id"))
        raw_status = git_data.get(hw_id, {})
        runtime = raw_status.get(runtime_key) if isinstance(raw_status.get(runtime_key), dict) else {}
        policy_mode = ((policy_state.get("node_modes") or {}).get(hw_id) or {}).get("mode")
        heartbeat = heartbeats.get(hw_id, {})
        dashboard = _dashboard_for_node(sidecar, drone, runtime)
        profile_summary = runtime.get("profile_summary") if isinstance(runtime.get("profile_summary"), dict) else {}
        profile_details = _runtime_profile_details(sidecar, profile_summary)
        rows.append(
            {
                "hw_id": hw_id,
                "pos_id": drone.get("pos_id"),
                "ip": drone.get("ip"),
                "presence": _presence(deps, heartbeat),
                "service_state": runtime.get("service_state")
                or runtime.get("service_status")
                or runtime.get("router_service_status")
                or runtime.get("status")
                or ("unreachable" if not runtime else "unknown"),
                "installed_ref": runtime.get("installed_ref") or runtime.get("ref"),
                "mode": _normalize_sidecar_mode(
                    policy_mode
                    or runtime.get("mode")
                    or runtime.get("management_mode")
                    or definition["default_mode"],
                    default=definition["default_mode"],
                    sidecar=sidecar,
                ),
                "profile_source": runtime.get("profile_source") or profile_summary.get("source"),
                "desired_hash": runtime.get("desired_hash") or runtime.get("desired_config_hash"),
                "applied_hash": runtime.get("applied_hash") or runtime.get("applied_config_hash"),
                "local_hash": runtime.get("local_hash") or runtime.get("profile_hash") or runtime.get("applied_hash"),
                "drift_state": _normalize_drift_state(runtime.get("drift_state"), runtime),
                "profile_count": _profile_count_from_runtime(sidecar, runtime),
                "dashboard": dashboard,
                "last_apply_result": _sanitize_public_value(runtime.get("last_apply_result")),
                "profile_summary": _sanitize_public_value(profile_summary),
                "profiles": profile_details["profiles"],
                "endpoints": profile_details["endpoints"],
                "sources": profile_details["sources"],
                "operator_state": _sanitize_public_value(runtime.get("operator_state")),
            }
        )
    return {
        "schema": SIDECAR_SCHEMA,
        "sidecar": sidecar,
        "hash_semantics": HASH_SEMANTICS,
        "rows": rows,
        "baseline": _load_baseline_summary(deps, sidecar),
        "timestamp": int(time.time() * 1000),
    }


def _normalize_sidecar_mode(mode: Any, *, default: str, sidecar: str) -> str:
    normalized = str(mode or "").strip().lower()
    aliases = {
        "manage": "fleet-merge",
        "managed": "fleet-merge",
        "manual": "local",
        "disabled": "observe",
        "none": "observe",
    }
    normalized = aliases.get(normalized, normalized)
    return normalized if normalized in POLICY_MODES else default


def _normalize_drift_state(state: Any, runtime: dict[str, Any]) -> str:
    normalized = str(state or "").strip().lower()
    if normalized in DRIFT_STATES:
        return normalized
    if not runtime:
        return "unreachable"
    if runtime.get("config_hash_match") is True:
        return "in_sync"
    if runtime.get("config_hash_match") is False:
        return "outdated"
    return "unmanaged"


def _profile_count_from_runtime(sidecar: str, runtime: dict[str, Any]) -> int:
    summary = runtime.get("profile_summary") if isinstance(runtime.get("profile_summary"), dict) else {}
    for key in ("profile_count", "network_count", "endpoint_count"):
        try:
            value = int(summary.get(key))
        except (TypeError, ValueError):
            continue
        return max(0, value)
    if sidecar == "smart-wifi-manager" and runtime.get("profile_present"):
        return 1
    return 0


def _runtime_profile_details(sidecar: str, profile_summary: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    profiles: list[dict[str, Any]] = []
    endpoints: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    if sidecar == "smart-wifi-manager":
        raw_profiles = profile_summary.get("profiles") if isinstance(profile_summary.get("profiles"), list) else []
        profiles = [item for item in _sanitize_public_value(raw_profiles) if isinstance(item, dict)]
    elif sidecar == "mavlink-anywhere":
        raw_endpoints = profile_summary.get("endpoints") if isinstance(profile_summary.get("endpoints"), list) else []
        raw_sources = profile_summary.get("sources") if isinstance(profile_summary.get("sources"), list) else []
        endpoints = [item for item in _sanitize_public_value(raw_endpoints) if isinstance(item, dict)]
        sources = [item for item in _sanitize_public_value(raw_sources) if isinstance(item, dict)]
    return {"profiles": profiles, "endpoints": endpoints, "sources": sources}


def _safe_heartbeats(deps: Any) -> dict[str, Any]:
    getter = getattr(deps, "get_all_heartbeats", None)
    if not callable(getter):
        return {}
    try:
        heartbeats = getter() or {}
    except Exception:
        return {}
    if isinstance(heartbeats, dict):
        return {str(key): value for key, value in heartbeats.items() if isinstance(value, dict)}
    return {}


def _policy_state_path(deps: Any, sidecar: str) -> Path:
    return Path(deps.BASE_DIR) / "data" / "fleet-sidecar-policy" / f"{sidecar}.json"


def _load_policy_state(deps: Any, sidecar: str) -> dict[str, Any]:
    path = _policy_state_path(deps, sidecar)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": SIDECAR_SCHEMA, "sidecar": sidecar, "node_modes": {}}
    return payload if isinstance(payload, dict) else {"schema": SIDECAR_SCHEMA, "sidecar": sidecar, "node_modes": {}}


def _save_policy_state(deps: Any, sidecar: str, payload: dict[str, Any]) -> None:
    path = _policy_state_path(deps, sidecar)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["schema"] = SIDECAR_SCHEMA
    payload["sidecar"] = sidecar
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, path)


def _presence(deps: Any, heartbeat: dict[str, Any]) -> dict[str, Any]:
    timestamp_ms = heartbeat.get("timestamp") or heartbeat.get("last_heartbeat")
    if not timestamp_ms:
        return {"state": "unknown", "last_seen_ms": None, "fresh": False}
    now = time.time()
    try:
        age_seconds = max(0.0, now - (float(timestamp_ms) / 1000.0))
    except (TypeError, ValueError):
        return {"state": "unknown", "last_seen_ms": None, "fresh": False}
    timeout = float(getattr(deps.Params, "TELEMETRY_POLLING_TIMEOUT", 5) or 5)
    online = age_seconds < timeout
    return {
        "state": "online" if online else "offline",
        "last_seen_ms": int(float(timestamp_ms)),
        "age_seconds": round(age_seconds, 1),
        "fresh": online,
    }


def _dashboard_for_node(sidecar: str, drone: dict[str, Any], runtime: dict[str, Any]) -> dict[str, Any]:
    dashboard_url = runtime.get("dashboard_url")
    access_mode = runtime.get("dashboard_access_mode")
    listen = runtime.get("dashboard_listen")
    port = _port_from_listen(listen) or SIDECARS[sidecar]["dashboard_port"]
    ip = drone.get("ip")
    return {
        "port": port,
        "url": dashboard_url or (f"http://{ip}:{port}/" if ip and access_mode == "direct" else None),
        "access_mode": access_mode or ("direct" if ip else "not_reported"),
        "listen": listen,
    }


def _port_from_listen(listen: Any) -> int | None:
    text = str(listen or "").strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    if ":" in text:
        tail = text.rsplit(":", 1)[-1]
        if tail.isdigit():
            return int(tail)
    return None


def _baseline_path(deps: Any, sidecar: str) -> Path | None:
    repo_root = Path(deps.BASE_DIR).resolve()
    for relative_path in SIDECARS[sidecar]["baseline_paths"]:
        candidate = (repo_root / relative_path).resolve()
        if candidate.exists():
            return candidate
    return None


def _load_baseline_config(deps: Any, sidecar: str) -> dict[str, Any] | None:
    path = _baseline_path(deps, sidecar)
    if not path:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _load_baseline_summary(deps: Any, sidecar: str) -> dict[str, Any]:
    path = _baseline_path(deps, sidecar)
    payload = _load_baseline_config(deps, sidecar)
    if not path or payload is None:
        return {
            "schema": SIDECAR_SCHEMA,
            "sidecar": sidecar,
            "present": False,
            "path": None,
            "hash": None,
            "hash_semantics": HASH_SEMANTICS,
            "profile_count": 0,
            "profiles": [],
            "endpoints": [],
        }
    redacted = _redacted_profile_config(payload)
    profiles = redacted.get("profiles", [])
    endpoints = redacted.get("endpoints", [])
    if sidecar == "smart-wifi-manager":
        profiles = _smart_wifi_public_profiles(payload)
    if sidecar == "mavlink-anywhere":
        endpoints = _mavlink_policy_endpoints(redacted)
    return {
        "schema": SIDECAR_SCHEMA,
        "sidecar": sidecar,
        "present": True,
        "path": str(path.relative_to(Path(deps.BASE_DIR).resolve())),
        "hash": _sanitized_hash(sidecar, payload),
        "hash_semantics": HASH_SEMANTICS,
        "profile_count": _baseline_profile_count(sidecar, payload),
        "profiles": profiles,
        "endpoints": endpoints,
        "mode": _normalize_sidecar_mode(payload.get("mode"), default=SIDECARS[sidecar]["default_mode"], sidecar=sidecar),
    }


def _redacted_profile_config(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = deepcopy(payload)
    _redact_secret_fields(redacted)
    return redacted


def _sanitize_public_value(value: Any) -> Any:
    secret_keys = {"password", "passphrase", "psk", "secret", "token", "api_key", "private_key", "confirmation_token"}
    external_secret_keys = {"password_file", "passphrase_file", "secret_file", "token_file", "api_key_file", "private_key_file"}
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, raw_value in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in external_secret_keys:
                sanitized[key] = "external file"
            elif normalized in secret_keys or any(marker in normalized for marker in ("password", "private_key", "api_key")):
                sanitized[key] = "redacted" if str(raw_value or "").strip() else "missing"
            else:
                sanitized[key] = _sanitize_public_value(raw_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_public_value(item) for item in value]
    if isinstance(value, str):
        return _sanitize_secret_text(value)
    return value


def _sanitize_secret_text(text: str) -> str:
    sanitized = re.sub(
        r'(?i)("?(?:password|passphrase|psk|secret|token|api_key|private_key|confirmation_token)"?\s*[:=]\s*)("[^"]*"|\'[^\']*\'|[^\s,}]+)',
        r"\1redacted",
        text,
    )
    sanitized = re.sub(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", "redacted-private-key", sanitized, flags=re.S)
    return sanitized


def _smart_wifi_public_profiles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    for profile in payload.get("profiles", []) or []:
        if not isinstance(profile, dict):
            continue
        redacted = deepcopy(profile)
        _redact_secret_fields(redacted)
        profiles.append(
            {
                "id": str(profile.get("id") or profile.get("ssid") or "").strip(),
                "ssid": str(profile.get("ssid") or "").strip(),
                "priority": int(profile.get("priority") or 0),
                "connection_name": str(profile.get("connection_name") or "").strip(),
                "autoconnect": bool(profile.get("autoconnect", True)),
                "disabled": bool(profile.get("disabled", False)),
                "notes": str(profile.get("notes") or "").strip(),
                "secret_status": redacted.get("secret_status", "missing"),
            }
        )
    profiles.sort(key=lambda item: (item["id"].lower(), item["ssid"].lower()))
    return profiles


def _redact_secret_fields(value: Any) -> Any:
    secret_keys = {"password", "passphrase", "psk", "secret", "token", "api_key", "private_key"}
    external_secret_keys = {"password_file", "passphrase_file", "secret_file", "token_file", "api_key_file", "private_key_file"}
    if isinstance(value, dict):
        for key, raw_value in list(value.items()):
            normalized = key.lower().replace("-", "_")
            if normalized in external_secret_keys:
                value[key] = ""
                value["secret_status"] = "external file"
            elif normalized in secret_keys:
                value[key] = ""
                value["secret_status"] = "stored" if str(raw_value or "").strip() else "missing"
            else:
                _redact_secret_fields(raw_value)
        value.setdefault("secret_status", "missing")
    elif isinstance(value, list):
        for item in value:
            _redact_secret_fields(item)
    return value


def _sanitized_hash(sidecar: str, payload: dict[str, Any]) -> str:
    if sidecar == "smart-wifi-manager":
        sanitized = _smart_wifi_canonical_payload(payload)
    elif sidecar == "mavlink-anywhere":
        sanitized = _mavlink_canonical_payload(payload)
    else:
        sanitized = _redacted_profile_config(payload)
    canonical = json.dumps(sanitized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]


def _smart_wifi_canonical_payload(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "version": int(config.get("version") or 1),
        "mode": _normalize_sidecar_mode(config.get("mode"), default="fleet-merge", sidecar="smart-wifi-manager"),
        "interface": str(config.get("interface") or ""),
        "scan_interval_sec": int(config.get("scan_interval_sec") or 0),
        "signal_switch_threshold": int(config.get("signal_switch_threshold") or 0),
        "connect_timeout_sec": int(config.get("connect_timeout_sec") or 0),
        "cooldown_sec": int(config.get("cooldown_sec") or 0),
        "allow_open_networks": bool(config.get("allow_open_networks", False)),
        "profiles": _smart_wifi_public_profiles(config),
    }


def _baseline_profile_count(sidecar: str, payload: dict[str, Any]) -> int:
    if sidecar == "mavlink-anywhere":
        return len(_mavlink_policy_endpoints(payload))
    return len(payload.get("profiles", []) or [])


def _mavlink_policy_endpoints(profile: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints = profile.get("endpoints", []) or []
    result = []
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            continue
        endpoint_type = str(endpoint.get("type") or "")
        mode = str(endpoint.get("mode") or "").lower()
        name = str(endpoint.get("name") or "")
        if endpoint_type == "UartEndpoint":
            continue
        if endpoint_type == "UdpEndpoint" and mode == "server" and name == "input":
            continue
        result.append(endpoint)
    return result


def _mavlink_canonical_payload(profile: dict[str, Any]) -> dict[str, Any]:
    endpoints = []
    for endpoint in _mavlink_policy_endpoints(profile):
        endpoints.append(
            {
                "name": str(endpoint.get("name") or ""),
                "type": str(endpoint.get("type") or ""),
                "mode": str(endpoint.get("mode") or "").lower(),
                "address": str(endpoint.get("address") or ""),
                "port": int(endpoint.get("port") or 0),
                "category": str(endpoint.get("category") or ""),
                "enabled": bool(endpoint.get("enabled", True)),
            }
        )
    endpoints.sort(key=lambda item: item["name"].lower())
    return {
        "general": profile.get("general") or {},
        "endpoints": endpoints,
    }


def _drone_api_port(deps: Any) -> int:
    try:
        return int(getattr(getattr(deps, "Params", object()), "drone_api_port", 7070) or 7070)
    except (TypeError, ValueError):
        return 7070


def _sidecar_api_payload(sidecar: str, payload: dict[str, Any]) -> dict[str, Any]:
    if sidecar != "smart-wifi-manager":
        return payload
    translated = deepcopy(payload)
    def service_mode(value: Any) -> str:
        mode = str(value or "")
        return {
            "observe": "observe",
            "local": "manage",
            "fleet-merge": "manage",
            "fleet-strict": "manage",
        }.get(mode, mode)

    baseline = translated.get("baseline")
    if isinstance(baseline, dict) and "mode" in baseline:
        baseline["mode"] = service_mode(baseline.get("mode"))
    return translated


def _post_sidecar(deps: Any, sidecar: str, node: dict[str, Any], action: str, payload: dict[str, Any]) -> dict[str, Any]:
    ip = node.get("ip")
    if not ip:
        raise HTTPException(status_code=400, detail="node ip is not configured")

    sidecar_payload = _sidecar_api_payload(sidecar, payload)
    proxy_url = f"http://{ip}:{_drone_api_port(deps)}/api/v1/sidecars/{sidecar}/profiles/{action}"
    try:
        response = requests.post(proxy_url, json=sidecar_payload, timeout=90 if action == "apply" else 10)
        if response.status_code != 404:
            if response.status_code >= 400:
                raise HTTPException(status_code=response.status_code, detail=_sidecar_error_detail(response))
            try:
                return response.json()
            except ValueError as exc:
                raise HTTPException(status_code=502, detail="sidecar proxy returned non-json response") from exc
    except requests.RequestException:
        pass

    port = ((node.get("dashboard") or {}).get("port")) or SIDECARS[sidecar]["dashboard_port"]
    url = f"http://{ip}:{port}/api/v1/profiles/{action}"
    headers = {}
    token = os.environ.get(SIDECAR_PROFILE_TOKEN_ENV, "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.post(url, json=sidecar_payload, headers=headers, timeout=8)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"sidecar request failed: {exc}") from exc
    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail=_sidecar_error_detail(response))
    try:
        data = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="sidecar returned non-json response") from exc
    return data


def _sidecar_error_detail(response: requests.Response) -> Any:
    try:
        payload = response.json()
    except ValueError:
        return f"sidecar returned HTTP {response.status_code}"
    return _sanitize_public_value(payload)
