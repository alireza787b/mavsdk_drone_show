"""Offline parameter review/receipt safety tests; no real discovery or vehicles."""

from __future__ import annotations

import copy
import json
import time
from types import SimpleNamespace

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from api_routes.px4_params import create_px4_params_router
from px4_param_job_models import JobRequest, ReviewRequest
from px4_param_journal import ParamJobConflict
from px4_param_jobs import ParamJobUnavailable, Px4ParamJobEngine
from src.drone_api_routes import DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE


ENTRY = {"component_id": 1, "name": "GF_ACTION", "value_type": "int", "value": 2}


class FakeVehicleTransport:
    def __init__(self):
        self.values = {"1": 1, "2": 1}
        self.patch_calls = []
        self.snapshot_calls = 0
        self.refresh_failure = False
        self.timeout_after_write = False
        self.readback_unavailable = False
        self.mismatch = False
        self.snapshot_identity = None
        self.before_write = None

    def __call__(self, method, url, *, timeout_sec, payload):
        assert method == "post"
        assert 0 < timeout_sec <= 60
        hw_id = "2" if "127.0.0.2" in url else "1"
        if url.endswith(DRONE_PX4_PARAMS_PATCH_APPLY_ROUTE):
            self.patch_calls.append(copy.deepcopy(payload))
            assert payload["expected_hw_id"] == hw_id
            assert payload["operation_id"]
            if self.before_write:
                self.before_write(payload)
            for entry in payload["entries"]:
                if self.values[hw_id] != entry["expected_current_value"]:
                    response = requests.Response()
                    response.status_code = 409
                    raise requests.HTTPError("Native expected value changed", response=response)
            for entry in payload["entries"]:
                self.values[hw_id] = entry["value"]
            if self.timeout_after_write:
                raise requests.Timeout("Response lost after the aircraft acknowledged a write")
            verified = not (self.readback_unavailable or self.mismatch)
            outcome = "verified" if verified else "written_unverified" if self.readback_unavailable else "verification_failed"
            return {
                "operation_id": payload["operation_id"], "source": payload["source"],
                "applied_count": len(payload["entries"]), "failed_count": 0,
                "verified_count": len(payload["entries"]) if verified else 0,
                "results": [{
                    "component_id": entry["component_id"], "name": entry["name"],
                    "value_type": entry["value_type"], "requested_value": entry["value"],
                    "applied": True, "verified": verified, "outcome": outcome,
                    "write_acknowledged": True,
                    "readback_status": "matched" if verified else "unavailable" if self.readback_unavailable else "mismatch",
                    "actual_value": entry["value"] if verified else None,
                    "error": "readback unavailable" if self.readback_unavailable else None,
                } for entry in payload["entries"]], "timestamp": int(time.time() * 1000),
            }
        self.snapshot_calls += 1
        if self.refresh_failure and self.patch_calls:
            raise requests.Timeout("Full snapshot refresh unavailable")
        return {
            "snapshot": {
                "snapshot_id": f"snapshot-{hw_id}-{self.snapshot_calls}",
                "hw_id": self.snapshot_identity or hw_id, "component_id": 1,
                "px4_docs_version": "main", "total_params": 1,
                "created_at": int(time.time() * 1000), "stale_after_ms": 60_000,
            },
            "rows": [{"component_id": 1, "name": "GF_ACTION", "value_type": "int", "value": self.values[hw_id]}],
        }


@pytest.fixture
def engine(tmp_path):
    config = [{"hw_id": 1, "ip": "127.0.0.1"}, {"hw_id": 2, "ip": "127.0.0.2"}]
    deps = SimpleNamespace(
        Params=SimpleNamespace(
            GCS_COMMAND_STATE_DIR=str(tmp_path), runtime_mode="sitl", sim_mode=True,
            gcs_api_port=5030, drone_api_port=7070, PX4_PARAMETER_DEFAULT_COMPONENT_ID=1,
            PX4_PARAMETER_HTTP_TIMEOUT_SEC=1,
        ), load_config=lambda: config, log_system_error=lambda *args: None,
    )
    transport = FakeVehicleTransport()
    instance = Px4ParamJobEngine(deps, transport=transport)
    yield instance, transport, deps, config
    if not instance._stop.is_set():
        instance.close()


def prepare(instance, hw_ids=None):
    return instance.prepare(ReviewRequest(hw_ids=hw_ids or ["1"], entries=[ENTRY]))


def request_for(review, key="request-one"):
    return JobRequest(review_id=review.review_id, review_hash=review.review_hash, idempotency_key=key)


def await_terminal(instance, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        receipt = instance.get_job(job_id)
        if receipt.terminal:
            return receipt
        time.sleep(0.01)
    pytest.fail("Bounded fake-vehicle parameter job did not finish")


def test_prepare_is_exact_read_only_per_target_review(engine):
    instance, transport, _, _ = engine
    review = instance.prepare(ReviewRequest(hw_ids=["1"], excluded_hw_ids=["2"], entries=[ENTRY]))
    assert not review.blocked
    assert not transport.patch_calls
    assert review.excluded_hw_ids == ["2"]
    change = review.targets[0].changes[0]
    assert (change.current_value, change.desired_value) == (1, 2)
    assert change.reboot_required is None
    assert instance.get_review(review.review_id) == review


@pytest.mark.parametrize("desired,current,unchanged", [(0.1, 0.10000000149011612, True), (1e-7, 0.0, False)])
def test_review_float_differences_follow_native_wire_identity(engine, desired, current, unchanged):
    instance, transport, _, _ = engine
    def snapshot(*args, **kwargs):
        response = transport(*args, **kwargs)
        response["rows"][0].update(value_type="float", value=current)
        return response
    instance._transport = snapshot
    review = instance.prepare(ReviewRequest(hw_ids=["1"], entries=[{**ENTRY, "value_type": "float", "value": desired}]))
    assert review.targets[0].unchanged_count == int(unchanged)
    assert len(review.targets[0].changes) == int(not unchanged)
    assert not transport.patch_calls


@pytest.mark.parametrize("actual,outcome", [(None, "written_unverified"), (1, "verification_failed")])
def test_verification_requires_matching_readback_not_only_native_boolean(engine, actual, outcome):
    instance, transport, _, _ = engine
    def misreported(*args, **kwargs):
        response = transport(*args, **kwargs)
        if "results" in response:
            response["results"][0]["actual_value"] = actual
        return response
    instance._transport = misreported
    job = instance.submit(request_for(prepare(instance)))
    receipt = await_terminal(instance, job.job_id)
    assert receipt.results[0].applied
    assert not receipt.results[0].verified
    assert receipt.results[0].outcome == outcome


def test_review_lifetime_starts_after_preparation_not_snapshot_display_staleness(engine, monkeypatch):
    import px4_param_jobs

    instance, transport, deps, _ = engine
    deps.Params.PX4_PARAMETER_REVIEW_MAX_AGE_SEC = 300
    clock = {"now": int(time.time() * 1000)}
    monkeypatch.setattr(px4_param_jobs, "_now", lambda: clock["now"])
    original_wait = px4_param_jobs.wait

    def preparation_took_time(futures, *, timeout):
        result = original_wait(futures, timeout=timeout)
        clock["now"] += 55_000
        return result

    monkeypatch.setattr(px4_param_jobs, "wait", preparation_took_time)
    review = prepare(instance)
    assert not review.blocked
    assert review.created_at == clock["now"]
    assert review.expires_at - review.created_at == 300_000
    clock["now"] += 120_000
    stored = instance.journal.get_review(review.review_id)
    assert instance._check_review(stored, review.review_hash).review_id == review.review_id
    assert not transport.patch_calls


def test_snapshot_already_stale_at_read_still_blocks_preparation(engine):
    instance, transport, _, _ = engine
    def stale_snapshot(*args, **kwargs):
        response = transport(*args, **kwargs)
        response["snapshot"]["created_at"] -= 90_000
        return response
    instance._transport = stale_snapshot
    review = prepare(instance)
    assert review.blocked and "stale" in review.targets[0].blockers[0]
    assert not transport.patch_calls


@pytest.mark.parametrize("seconds", [0, -1, 3601, float("nan"), float("inf")])
def test_invalid_review_lifetime_rejected_before_vehicle_access(engine, seconds):
    instance, transport, deps, _ = engine
    deps.Params.PX4_PARAMETER_REVIEW_MAX_AGE_SEC = seconds
    with pytest.raises(ParamJobUnavailable, match="lifetime"):
        prepare(instance)
    assert not transport.snapshot_calls and not transport.patch_calls


def test_identity_mismatch_blocks_review_without_any_write(engine):
    instance, transport, _, _ = engine
    transport.snapshot_identity = "wrong-aircraft"
    review = prepare(instance)
    assert review.blocked
    assert "identity" in review.targets[0].blockers[0]
    with pytest.raises(ParamJobConflict):
        instance.submit(request_for(review))
    assert not transport.patch_calls


def test_receipt_is_durable_before_write_and_replay_is_same_job(engine):
    instance, transport, _, _ = engine
    review = prepare(instance)
    def assert_receipt_exists(payload):
        job = instance.find_request("request-one")
        assert job is not None
        assert job.results[0].outcome == "running"
        assert payload["entries"][0]["expected_current_value"] == 1
    transport.before_write = assert_receipt_exists
    accepted = instance.submit(request_for(review))
    terminal = await_terminal(instance, accepted.job_id)
    assert terminal.status == "completed" and terminal.results[0].verified
    assert instance.submit(request_for(review)).job_id == accepted.job_id
    assert len(transport.patch_calls) == 1
    assert instance.find_request("request-one").job_id == accepted.job_id


def test_changed_request_cannot_reuse_idempotency_key(engine):
    instance, transport, _, _ = engine
    first = prepare(instance)
    accepted = instance.submit(request_for(first))
    await_terminal(instance, accepted.job_id)
    second = prepare(instance)
    with pytest.raises(ParamJobConflict, match="Idempotency"):
        instance.submit(request_for(second))
    assert len(transport.patch_calls) == 1


def test_concurrent_external_edit_rejected_by_native_preconditions(engine):
    instance, transport, _, _ = engine
    review = prepare(instance)
    transport.values["1"] = 3
    job = await_terminal(instance, instance.submit(request_for(review)).job_id)
    assert job.status == "failed" and job.results[0].outcome == "rejected"
    assert transport.values["1"] == 3


def test_snapshot_refresh_failure_preserves_verified_write(engine):
    instance, transport, _, _ = engine
    review = prepare(instance)
    transport.refresh_failure = True
    job = await_terminal(instance, instance.submit(request_for(review)).job_id)
    assert job.status == "completed" and job.results[0].verified
    assert "refresh unavailable" in job.results[0].snapshot_refresh_error
    assert job.results[0].result.results[0].write_acknowledged


@pytest.mark.parametrize("kind", ["unavailable", "mismatch"])
def test_readback_failure_is_not_unqualified_success(engine, kind):
    instance, transport, _, _ = engine
    review = prepare(instance)
    transport.readback_unavailable = kind == "unavailable"
    transport.mismatch = kind == "mismatch"
    job = await_terminal(instance, instance.submit(request_for(review)).job_id)
    assert job.status == "partial"
    assert job.results[0].applied and not job.results[0].verified
    assert job.results[0].outcome == ("written_unverified" if kind == "unavailable" else "verification_failed")


def test_response_loss_is_unknown_and_never_automatically_replayed(engine):
    instance, transport, deps, _ = engine
    review = prepare(instance)
    transport.timeout_after_write = True
    accepted = instance.submit(request_for(review))
    job = await_terminal(instance, accepted.job_id)
    assert job.status == "unknown" and job.unknown_targets == 1
    assert transport.values["1"] == 2
    instance.close()
    reopened = Px4ParamJobEngine(deps, transport=transport)
    try:
        assert reopened.get_job(job.job_id).status == "unknown"
        assert reopened.submit(request_for(review)).job_id == job.job_id
        assert len(transport.patch_calls) == 1
    finally:
        reopened.close()


def test_restart_fences_queued_and_inflight_work_without_replay(engine, monkeypatch):
    instance, transport, deps, _ = engine
    review = prepare(instance)
    monkeypatch.setattr(instance, "_start_worker", lambda: None)
    accepted = instance.submit(request_for(review))
    payload = instance.journal.get_job(accepted.job_id)
    payload["status"] = "running"
    payload["results"][0]["outcome"] = "running"
    instance.journal.save_job(payload, "test_inflight")
    instance.close()
    reopened = Px4ParamJobEngine(deps, transport=transport)
    try:
        receipt = reopened.get_job(accepted.job_id)
        assert receipt.terminal and receipt.status == "unknown"
        assert not transport.patch_calls
    finally:
        reopened.close()


def test_expired_review_and_changed_endpoint_reject_before_write(engine, monkeypatch):
    instance, transport, _, config = engine
    review = prepare(instance)
    config[0]["ip"] = "127.0.0.9"
    with pytest.raises(ParamJobConflict, match="configuration"):
        instance.submit(request_for(review))
    config[0]["ip"] = "127.0.0.1"
    monkeypatch.setattr("px4_param_jobs._now", lambda: review.expires_at + 1)
    with pytest.raises(ParamJobConflict, match="expired"):
        instance.submit(request_for(review))
    assert not transport.patch_calls


def test_review_is_bound_to_runtime_and_mode(engine):
    instance, transport, deps, _ = engine
    review = prepare(instance)
    deps.Params.runtime_mode = "real"
    with pytest.raises(ParamJobConflict, match="Runtime mode"):
        instance.submit(request_for(review))
    assert not transport.patch_calls


def test_legacy_request_uses_same_review_and_receipt_engine(engine):
    instance, transport, _, _ = engine
    accepted = instance.submit(JobRequest(hw_ids=["1"], entries=[ENTRY], idempotency_key="legacy-key"))
    terminal = await_terminal(instance, accepted.job_id)
    assert terminal.review_id and terminal.status == "completed"
    assert transport.patch_calls[0]["entries"][0]["expected_current_value"] == 1


def test_mixed_review_and_legacy_overrides_are_invalid():
    with pytest.raises(ValidationError, match="immutable"):
        JobRequest(review_id="review", review_hash="hash", idempotency_key="request-one", hw_ids=["1"], entries=[ENTRY])
    with pytest.raises(ValidationError, match="readback"):
        JobRequest(review_id="review", review_hash="hash", idempotency_key="request-one", verify_readback=False)


def test_duplicate_targets_and_parameters_are_invalid():
    with pytest.raises(ValidationError, match="unique"):
        ReviewRequest(hw_ids=["1", "1"], entries=[ENTRY])
    with pytest.raises(ValidationError, match="duplicate"):
        ReviewRequest(hw_ids=["1"], entries=[ENTRY, ENTRY])


def test_full_qgc_sized_review_is_not_truncated_by_request_schema():
    entries = [{**ENTRY, "name": f"TEST_{index}"} for index in range(2000)]
    assert len(ReviewRequest(hw_ids=["1"], entries=entries).entries) == 2000


def test_unsupported_component_rejected_before_snapshot_or_write(engine):
    instance, transport, _, _ = engine
    with pytest.raises(ParamJobConflict, match="component"):
        instance.prepare(ReviewRequest(hw_ids=["1"], entries=[{**ENTRY, "component_id": 2}]))
    assert not transport.snapshot_calls and not transport.patch_calls


def test_storage_admission_fails_closed_but_old_receipt_stays_readable(engine):
    instance, transport, _, _ = engine
    first = prepare(instance)
    receipt = await_terminal(instance, instance.submit(request_for(first)).job_id)
    next_review = prepare(instance)
    instance.journal.max_bytes = 1
    with pytest.raises(ParamJobConflict, match="capacity"):
        instance.submit(request_for(next_review, "next-request"))
    assert instance.get_job(receipt.job_id).terminal
    assert instance.find_request("request-one").job_id == receipt.job_id
    assert instance.find_request("next-request") is None
    assert len(transport.patch_calls) == 1


def test_profile_content_drift_invalidates_review(engine, tmp_path):
    instance, transport, deps, _ = engine
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile_path = profile_dir / "baseline.json"
    payload = {"profile_id": "baseline", "name": "Baseline", "entries": [ENTRY]}
    profile_path.write_text(json.dumps(payload))
    deps.Params.PX4_PARAMETER_PROFILE_DIR = str(profile_dir)
    review = instance.prepare(ReviewRequest(
        hw_ids=["1"], entries=[ENTRY], source="mds_profile", profile_id="baseline",
    ))
    assert review.profile_hash
    payload["description"] = "A different reviewed policy"
    profile_path.write_text(json.dumps(payload))
    with pytest.raises(ParamJobConflict, match="profile changed"):
        instance.submit(request_for(review))
    assert not transport.patch_calls


def test_unchanged_target_has_no_mutation_and_explicit_outcome(engine):
    instance, transport, _, _ = engine
    transport.values["1"] = 2
    review = prepare(instance)
    assert not review.targets[0].changes and review.targets[0].unchanged_count == 1
    job = await_terminal(instance, instance.submit(request_for(review)).job_id)
    assert job.status == "completed" and job.results[0].outcome == "unchanged"
    assert job.results[0].verified and not job.results[0].applied
    assert not transport.patch_calls


def test_routes_accept_receipt_and_lookup_by_request_identity(engine, monkeypatch):
    instance, transport, deps, _ = engine
    monkeypatch.setattr("api_routes.px4_params.get_px4_param_engine", lambda ignored: instance)
    app = FastAPI()
    app.include_router(create_px4_params_router(deps))
    base = "/api/v1/px4-params"
    with TestClient(app) as client:
        review_response = client.post(base + "/reviews", json={"hw_ids": ["1"], "entries": [ENTRY]})
        assert review_response.status_code == 200
        review = review_response.json()
        response = client.post(base + "/patch-jobs", json={
            "review_id": review["review_id"], "review_hash": review["review_hash"], "idempotency_key": "route-request",
        })
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        await_terminal(instance, job_id)
        lookup = client.get(base + "/patch-jobs/by-idempotency/route-request")
        assert lookup.status_code == 200 and lookup.json()["job_id"] == job_id
        assert client.get(base + "/patch-jobs/" + job_id).json()["terminal"]
        assert client.post(base + "/patch-jobs", json={
            "review_id": review["review_id"], "review_hash": review["review_hash"],
            "idempotency_key": "mixed-request", "hw_ids": ["2"], "entries": [ENTRY],
        }).status_code == 422
    assert len(transport.patch_calls) == 1
