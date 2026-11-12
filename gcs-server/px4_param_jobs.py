"""Immutable reviews and bounded, durable PX4 parameter job orchestration."""

from __future__ import annotations

import hashlib
import math
import queue
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Any, Callable

import requests

import px4_param_store as snapshots
from px4_param_job_models import (
    JobRequest, JobResponse, JobTargetResult, ReviewChange, ReviewRequest,
    ReviewResponse, ReviewTarget,
)
from px4_param_journal import ParamJobConflict, ParamJobJournal, canonical_json
from src.drone_api_routes import (
    DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE, DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE,
)
from src.px4_param_models import Px4ParamPatchApplyResponse, Px4ParamSnapshotResponse
from src.px4_param_values import parameter_values_match


def _now() -> int:
    return int(time.time() * 1000)


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _entry_payload(entry: Any) -> dict[str, Any]:
    value = entry.model_dump(mode="json") if hasattr(entry, "model_dump") else entry
    return {key: value[key] for key in ("component_id", "name", "value_type", "value")}


def _sorted_entries(entries: list[Any]) -> list[dict[str, Any]]:
    return sorted((_entry_payload(entry) for entry in entries), key=lambda e: (e["component_id"], e["name"]))


def runtime_binding(deps: Any) -> str:
    params = deps.Params
    return _digest({
        "mode": str(getattr(params, "runtime_mode", "unknown")),
        "sim_mode": getattr(params, "sim_mode", None),
        "gcs_port": getattr(params, "gcs_api_port", None),
        "repository": str(Path(__file__).resolve().parents[1]),
    })[:32]


class ParamJobUnavailable(RuntimeError):
    pass


class Px4ParamJobEngine:
    """One GCS owns dispatch. Restart recovery never replays accepted writes."""

    def __init__(self, deps: Any, *, transport: Callable[..., dict[str, Any]] | None = None) -> None:
        self.deps = deps
        self.binding = runtime_binding(deps)
        state_dir = getattr(deps.Params, "GCS_COMMAND_STATE_DIR", None)
        if not isinstance(state_dir, str) or not state_dir:
            raise ParamJobUnavailable("Durable parameter receipt storage is not configured")
        self.journal = ParamJobJournal(
            state_dir, self.binding,
            max_bytes=int(getattr(deps.Params, "PX4_PARAMETER_STATE_MAX_BYTES", 64 * 1024 * 1024)),
        )
        self._transport = transport or snapshots._request_json
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=8)
        self._submit_lock = threading.Lock()
        self._read_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="px4-parameter-reads")
        self._prepare_slots = threading.BoundedSemaphore(2)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _ensure_runtime(self) -> None:
        if runtime_binding(self.deps) != self.binding:
            raise ParamJobConflict("Runtime mode/deployment changed; prepare a new parameter review")
        if self._stop.is_set():
            raise ParamJobUnavailable("Parameter job engine is shutting down")

    def _timeout(self) -> float:
        return min(60.0, max(0.5, float(getattr(self.deps.Params, "PX4_PARAMETER_HTTP_TIMEOUT_SEC", 20.0))))

    def _review_max_age_ms(self) -> int:
        raw = getattr(self.deps.Params, "PX4_PARAMETER_REVIEW_MAX_AGE_SEC", 300.0)
        try:
            seconds = float(raw)
        except (TypeError, ValueError):
            raise ParamJobUnavailable("Parameter review lifetime must be between 1 and 3600 seconds") from None
        if isinstance(raw, bool) or not math.isfinite(seconds) or not 1 <= seconds <= 3600:
            raise ParamJobUnavailable("Parameter review lifetime must be between 1 and 3600 seconds")
        return int(seconds * 1000)

    def _config(self) -> dict[str, dict[str, Any]]:
        return {str(drone["hw_id"]): drone for drone in self.deps.load_config()}

    def _endpoint(self, drone: dict[str, Any]) -> str:
        ip = str(drone.get("ip", "")).strip()
        if not ip:
            raise ParamJobConflict("Target drone has no configured IP")
        port = int(getattr(self.deps.Params, "drone_api_port", 7070))
        return f"http://{ip}:{port}"

    def _read_snapshot(self, endpoint: str, hw_id: str, component_id: int) -> Px4ParamSnapshotResponse:
        payload = self._transport(
            "post", endpoint + DRONE_PX4_PARAMS_SNAPSHOT_REFRESH_ROUTE,
            timeout_sec=self._timeout(), payload={"component_id": component_id},
        )
        snapshot = Px4ParamSnapshotResponse.model_validate(payload)
        if snapshot.snapshot.hw_id != hw_id or snapshot.snapshot.component_id != component_id:
            raise ParamJobConflict("Snapshot aircraft/component identity does not match the requested target")
        if any(row.component_id != component_id for row in snapshot.rows):
            raise ParamJobConflict("Snapshot contains rows from an unexpected component")
        keys = [(row.component_id, row.name) for row in snapshot.rows]
        if len(keys) != len(set(keys)):
            raise ParamJobConflict("Snapshot contains duplicate parameter keys")
        snapshots.save_snapshot(snapshot)
        return snapshot

    def _profile(self, profile_id: str) -> tuple[str, list[dict[str, Any]]]:
        if not re.fullmatch(r"[A-Za-z0-9_.:-]+", profile_id):
            raise ParamJobConflict("Invalid profile identifier")
        profile = snapshots.get_repo_profile(self.deps.Params, profile_id)
        if profile is None:
            raise ParamJobConflict("Selected repository profile no longer exists")
        content = profile.model_dump(mode="json")
        content.pop("updated_at", None)
        content["entries"] = _sorted_entries(profile.entries)
        return _digest(content), content["entries"]

    def _prepare_target(self, hw_id: str, component_id: int, entries: list[dict[str, Any]], config: dict[str, Any]):
        target = ReviewTarget(hw_id=hw_id, component_id=component_id)
        dispatch = None
        try:
            if hw_id not in config:
                raise ParamJobConflict("Target drone not found in config")
            endpoint = self._endpoint(config[hw_id])
            snapshot = self._read_snapshot(endpoint, hw_id, component_id)
            target.snapshot_id = snapshot.snapshot.snapshot_id
            if snapshot.snapshot.stale_after_ms <= 0:
                raise ParamJobConflict("Snapshot has no valid freshness interval")
            if snapshot.snapshot.created_at + snapshot.snapshot.stale_after_ms <= _now():
                raise ParamJobConflict("Snapshot is already stale; refresh before preparing a review")
            rows = {(row.component_id, row.name): row for row in snapshot.rows}
            native_entries = []
            for entry in entries:
                row = rows.get((entry["component_id"], entry["name"]))
                if row is None:
                    target.blockers.append(f"{entry['name']}: parameter is missing from the target")
                    continue
                if row.value_type.value != entry["value_type"]:
                    target.blockers.append(f"{entry['name']}: parameter type does not match the target")
                    continue
                if not row.writable:
                    target.blockers.append(f"{entry['name']}: target reports parameter as read-only")
                    continue
                if parameter_values_match(entry["value_type"], entry["value"], row.value):
                    target.unchanged_count += 1
                    continue
                target.changes.append(ReviewChange(
                    name=row.name, component_id=row.component_id, value_type=row.value_type,
                    current_value=row.value, desired_value=entry["value"], changed=True,
                    reboot_required=row.reboot_required,
                    metadata_sources=[source.value for source in row.metadata_sources],
                ))
                native_entries.append({**entry, "expected_current_value": row.value})
            dispatch = {"endpoint": endpoint, "component_id": component_id, "entries": native_entries}
        except Exception as exc:
            target.blockers.append((str(exc) or exc.__class__.__name__)[:2048])
        return target, dispatch

    def prepare(self, request: ReviewRequest) -> ReviewResponse:
        if not self._prepare_slots.acquire(blocking=False):
            raise ParamJobUnavailable("Parameter review preparation is busy; no review or write was accepted")
        try:
            return self._prepare(request)
        finally:
            self._prepare_slots.release()

    def _prepare(self, request: ReviewRequest) -> ReviewResponse:
        self._ensure_runtime()
        review_max_age_ms = self._review_max_age_ms()
        entries = _sorted_entries(request.entries)
        if len(canonical_json(entries).encode("utf-8")) > 2 * 1024 * 1024:
            raise ParamJobConflict("Parameter review payload is too large; use a smaller explicit patch")
        components = {entry["component_id"] for entry in entries}
        supported = int(getattr(self.deps.Params, "PX4_PARAMETER_DEFAULT_COMPONENT_ID", 1))
        if components != {supported}:
            raise ParamJobConflict("Review must use the supported PX4 component only")
        profile_hash = None
        if request.profile_id is not None:
            profile_hash, profile_entries = self._profile(request.profile_id)
            if profile_entries != entries or (request.profile_hash and request.profile_hash != profile_hash):
                raise ParamJobConflict("Profile content changed or does not match the requested entries")
        elif request.source.value == "mds_profile":
            # Old typed-patch callers are supported, but never masquerade as a
            # reviewed named repository profile without its identity/hash.
            profile_hash = _digest(entries)

        config = self._config()
        targets: list[ReviewTarget] = []
        dispatch: dict[str, Any] = {}
        futures = {
            hw_id: self._read_pool.submit(self._prepare_target, hw_id, supported, entries, config)
            for hw_id in request.hw_ids
        }
        # Read-only preparation has one explicit deadline, not N serial HTTP
        # timeouts. Every unresolved target stays visible and blocks acceptance.
        done, _ = wait(futures.values(), timeout=60.0)
        for hw_id, future in futures.items():
            if future not in done:
                future.cancel()
                target = ReviewTarget(hw_id=hw_id, component_id=supported,
                                      blockers=["Snapshot did not finish within the 60-second review window"])
                target_dispatch = None
            else:
                target, target_dispatch = future.result()
            targets.append(target)
            if target_dispatch is not None:
                dispatch[hw_id] = target_dispatch

        created_at = _now()
        # Display freshness and confirmation lifetime are different contracts.
        # Native expected-current checks remain mandatory at actual execution.
        expires_at = created_at + review_max_age_ms
        review = ReviewResponse(
            review_id=f"px4-review-{uuid.uuid4().hex}", review_hash="", runtime_binding=self.binding,
            hw_ids=request.hw_ids, excluded_hw_ids=request.excluded_hw_ids, source=request.source,
            verify_readback=True, profile_id=request.profile_id, profile_hash=profile_hash,
            targets=targets, blocked=any(target.blockers for target in targets),
            created_at=created_at, expires_at=expires_at,
        )
        if request.excluded_hw_ids:
            review.warnings.append("Explicitly excluded aircraft are not part of this apply operation")
        review.review_hash = _digest({"review": review.model_dump(mode="json"), "dispatch": dispatch})
        self.journal.save_review(review.model_dump(mode="json"), dispatch)
        return review

    def get_review(self, review_id: str) -> ReviewResponse | None:
        self._ensure_runtime()
        stored = self.journal.get_review(review_id)
        return ReviewResponse.model_validate(stored["review"]) if stored else None

    def _check_review(self, stored: dict[str, Any], review_hash: str) -> ReviewResponse:
        review = ReviewResponse.model_validate(stored["review"])
        if review.review_hash != review_hash:
            raise ParamJobConflict("Review hash does not match the immutable reviewed content")
        if review.runtime_binding != self.binding or review.blocked or review.expires_at <= _now():
            raise ParamJobConflict("Review is blocked, expired, or belongs to a different runtime")
        if review.profile_id and self._profile(review.profile_id)[0] != review.profile_hash:
            raise ParamJobConflict("Repository profile changed after review")
        config = self._config()
        for hw_id in review.hw_ids:
            if hw_id not in config or self._endpoint(config[hw_id]) != stored["dispatch"][hw_id]["endpoint"]:
                raise ParamJobConflict("Target configuration changed after review")
        return review

    def submit(self, request: JobRequest) -> JobResponse:
        self._ensure_runtime()
        key = request.idempotency_key or f"legacy-{uuid.uuid4().hex}"
        request_payload = request.model_dump(mode="json", exclude={"idempotency_key"})
        fingerprint = _digest({"runtime_binding": self.binding, "request": request_payload})
        with self._submit_lock:
            existing = self.journal.find_request(key, fingerprint)
            if existing:
                return JobResponse.model_validate(existing)
            if self._queue.full():
                raise ParamJobUnavailable("Parameter job queue is full; no job was accepted")
            if request.review_id:
                stored = self.journal.get_review(request.review_id)
                if stored is None:
                    raise ParamJobConflict("Parameter review was not found")
                review = self._check_review(stored, request.review_hash or "")
            else:
                review = self.prepare(ReviewRequest(
                    hw_ids=request.hw_ids, entries=request.entries, source=request.source,
                    verify_readback=request.verify_readback,
                ))
                stored = self.journal.get_review(review.review_id)
                review = self._check_review(stored, review.review_hash)
            now = _now()
            job = JobResponse(
                job_id=f"px4-patch-{uuid.uuid4().hex}", review_id=review.review_id,
                review_hash=review.review_hash, idempotency_key=key, runtime_binding=self.binding,
                source=review.source, status="queued", total_targets=len(review.hw_ids),
                results=[JobTargetResult(hw_id=hw_id) for hw_id in review.hw_ids],
                created_at=now, updated_at=now,
            )
            accepted, created = self.journal.accept(job.model_dump(mode="json"), fingerprint)
            if created:
                # This point is after the FULL-synchronous commit; no worker can
                # see an operation before its stable receipt exists on disk.
                self._queue.put_nowait(job.job_id)
                self._start_worker()
            return JobResponse.model_validate(accepted)

    def get_job(self, job_id: str) -> JobResponse | None:
        self._ensure_runtime()
        payload = self.journal.get_job(job_id)
        return JobResponse.model_validate(payload) if payload else None

    def find_request(self, key: str) -> JobResponse | None:
        self._ensure_runtime()
        payload = self.journal.find_request(key)
        return JobResponse.model_validate(payload) if payload else None

    def _start_worker(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._work, name="px4-parameter-jobs", daemon=True)
            self._thread.start()

    def _work(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    job_id = self._queue.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    if job_id is not None:
                        self._execute(job_id)
                except Exception as exc:
                    # A journal/storage failure must never trigger a retry.
                    self.deps.log_system_error(f"PX4 parameter job stopped: {exc}", "px4_params")
                finally:
                    self._queue.task_done()
        finally:
            self.journal.close()

    def _save(self, job: JobResponse, kind: str) -> None:
        job.updated_at = _now()
        self.journal.save_job(job.model_dump(mode="json"), kind)

    def _execute(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if job is None or job.terminal:
            return
        stored = self.journal.get_review(job.review_id)
        try:
            self._ensure_runtime()
            self._check_review(stored, job.review_hash)
        except Exception as exc:
            for target in job.results:
                target.outcome, target.error = "rejected", str(exc)[:2048]
            self._finish(job)
            return
        job.status = "running"
        self._save(job, "started")
        for target in job.results:
            dispatch = stored["dispatch"][target.hw_id]
            if not dispatch["entries"]:
                target.outcome, target.verified = "unchanged", True
                self._save(job, "target_unchanged")
                continue
            try:
                self._ensure_runtime()
                self._check_review(stored, job.review_hash)
            except Exception as exc:
                target.outcome, target.error = "not_attempted", str(exc)[:2048]
                self._save(job, "target_not_attempted")
                continue
            target.outcome = "running"
            self._save(job, "target_dispatching")
            payload = {
                "operation_id": f"{job.job_id}-{_digest(target.hw_id)[:12]}",
                "expected_hw_id": target.hw_id, "source": job.source.value,
                "verify_readback": True, "entries": dispatch["entries"],
            }
            try:
                raw = self._transport(
                    "post", dispatch["endpoint"] + DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE,
                    timeout_sec=self._timeout(), payload=payload,
                )
                result = Px4ParamPatchApplyResponse.model_validate(raw)
                if result.operation_id != payload["operation_id"]:
                    raise ValueError("Native patch response operation identity does not match this receipt")
                if result.source != job.source:
                    raise ValueError("Native patch response source does not match this receipt")
                self._record_result(target, result, dispatch["entries"])
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                target.outcome = "rejected" if code in {400, 401, 403, 404, 409, 422} else "unknown"
                target.error = (str(exc) or "Target request failed")[:2048]
            except Exception as exc:
                target.outcome, target.error = "unknown", (str(exc) or exc.__class__.__name__)[:2048]
            self._save(job, "target_result")
            # Snapshot refresh is optional follow-up evidence. Its failure never
            # erases an acknowledged write or a successful targeted readback.
            if target.result is not None and not self._stop.is_set():
                try:
                    self._read_snapshot(dispatch["endpoint"], target.hw_id, dispatch["component_id"])
                except Exception as exc:
                    target.snapshot_refresh_error = (str(exc) or exc.__class__.__name__)[:2048]
                self._save(job, "target_refresh")
        self._finish(job)

    @staticmethod
    def _record_result(target: JobTargetResult, response: Px4ParamPatchApplyResponse, entries: list[dict[str, Any]]) -> None:
        result = response.model_dump(mode="json")
        rows = result["results"]
        for row in rows:
            if row.get("error"):
                row["error"] = str(row["error"])[:2048]
        expected = {(entry["component_id"], entry["name"]): entry for entry in entries}
        observed = {(row.get("component_id", 1), row["name"]): row for row in rows}
        if len(rows) != len(expected) or set(observed) != set(expected):
            raise ValueError("Native patch response does not match the exact reviewed parameter keys")
        for key, row in observed.items():
            entry = expected[key]
            if row["value_type"] != entry["value_type"] or row["requested_value"] != entry["value"]:
                raise ValueError("Native patch response does not match the reviewed type/value")
            actual = row.get("actual_value")
            if row["verified"] and (not row["applied"] or not parameter_values_match(
                    entry["value_type"], entry["value"], actual)):
                # A reported boolean is not readback evidence. Keep known write
                # acknowledgement without turning absent/mismatched data green.
                missing = actual is None
                row.update(verified=False,
                           readback_status="unavailable" if missing else "mismatch",
                           outcome=("written_unverified" if missing else "verification_failed") if row["applied"] else "unknown",
                           error="Native verification was not supported by matching readback evidence")
            value_budget = max(4096, len(str(entry["value"])), len(str(entry["expected_current_value"])))
            if isinstance(actual, str) and len(actual) > value_budget:
                row.update(actual_value=None, verified=False, readback_status="unavailable",
                           outcome="written_unverified" if row["applied"] else "unknown",
                           error="Readback evidence exceeded the bounded receipt field capacity")
        result["verified_count"] = sum(bool(row["verified"]) for row in rows)
        target.result = Px4ParamPatchApplyResponse.model_validate(result)
        outcomes = {row.get("outcome") for row in rows}
        target.applied = all(bool(row["applied"]) for row in rows)
        target.verified = all(bool(row["verified"]) for row in rows)
        if target.verified:
            target.outcome = "verified"
        elif "unknown" in outcomes:
            target.outcome = "unknown"
        elif "verification_failed" in outcomes:
            target.outcome = "verification_failed"
        elif any(bool(row["applied"]) for row in rows):
            target.outcome = "written_unverified"
        else:
            target.outcome = "rejected"
        errors = [row["error"] for row in rows if row.get("error")]
        target.error = "; ".join(errors)[:2048] if errors else None

    def _finish(self, job: JobResponse) -> None:
        job.terminal = True
        job.completed_at = _now()
        job.completed_targets = len(job.results)
        job.unknown_targets = sum(target.outcome == "unknown" for target in job.results)
        job.failed_targets = sum(not target.verified for target in job.results)
        if job.unknown_targets:
            job.status = "unknown"
        elif all(target.verified for target in job.results):
            job.status = "completed"
        elif any(target.applied or target.verified for target in job.results):
            job.status = "partial"
        else:
            job.status = "failed"
        self._save(job, "finished")

    def close(self) -> None:
        self._stop.set()
        self._read_pool.shutdown(wait=False, cancel_futures=True)
        if self._thread is None:
            self.journal.close()
        else:
            self._thread.join(timeout=1.0)


_ENGINES: dict[tuple[str, str], Px4ParamJobEngine] = {}
_ENGINES_LOCK = threading.Lock()


def get_px4_param_engine(deps: Any) -> Px4ParamJobEngine:
    key = (str(getattr(deps.Params, "GCS_COMMAND_STATE_DIR", "")), runtime_binding(deps))
    with _ENGINES_LOCK:
        if key not in _ENGINES:
            _ENGINES[key] = Px4ParamJobEngine(deps)
        return _ENGINES[key]


def close_px4_param_engine(deps: Any) -> None:
    key = (str(getattr(deps.Params, "GCS_COMMAND_STATE_DIR", "")), runtime_binding(deps))
    with _ENGINES_LOCK:
        engine = _ENGINES.pop(key, None)
    if engine is not None:
        engine.close()
