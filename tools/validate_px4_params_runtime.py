#!/usr/bin/env python3
"""Validate PX4 parameter management against a live GCS/SITL stack."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.drone_api_routes import DRONE_SYSTEM_HEALTH_ROUTE
from src.px4_param_values import parameter_values_match
from src.gcs_api_routes import (
    GCS_PX4_PARAMS_DIFF_ROUTE,
    GCS_PX4_PARAMS_PATCH_JOBS_ROUTE,
    GCS_PX4_PARAMS_PATCH_JOB_ROUTE_TEMPLATE,
    GCS_PX4_PARAMS_REVIEWS_ROUTE,
    GCS_PX4_PARAMS_POLICY_ROUTE,
    GCS_PX4_PARAMS_QGC_IMPORT_ROUTE,
    GCS_PX4_PARAMS_SNAPSHOTS_ROUTE,
    GCS_FLEET_TELEMETRY_ROUTE,
    GCS_SYSTEM_HEALTH_ROUTE,
)
from tools.runtime_validation_support import (
    fetch_and_require_sitl_runtime,
    normalize_drone_ids,
    parse_csv_drone_ids,
    write_json_report,
)


DEFAULT_PARAM_NAME = "MPC_XY_VEL_MAX"


def log(message: str) -> None:
    print(message, flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def format_http_error(exc: urllib.error.HTTPError) -> str:
    try:
        raw_body = exc.read()
    except Exception:
        raw_body = b""

    detail = raw_body.decode("utf-8", errors="replace").strip() if raw_body else ""
    if detail:
        return f"HTTP {exc.code}: {detail}"
    return f"HTTP {exc.code}: {getattr(exc, 'reason', 'request failed')}"


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request_json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"} if payload is not None else {},
            method=method.upper(),
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

    def get_json(self, path: str, *, timeout: float = 20.0) -> dict[str, Any]:
        return self.request_json("GET", path, timeout=timeout)

    def get_drone_json(self, drone_ip: str, path: str, *, timeout: float = 20.0) -> dict[str, Any]:
        drone_api_port = int(os.getenv("MDS_DRONE_API_PORT", "7070"))
        try:
            with urllib.request.urlopen(f"http://{drone_ip}:{drone_api_port}{path}", timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

    def get_telemetry(self) -> dict[str, dict[str, Any]]:
        payload = self.get_json(GCS_FLEET_TELEMETRY_ROUTE)
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def post_json(self, path: str, payload: dict[str, Any], *, timeout: float = 60.0) -> dict[str, Any]:
        return self.request_json("POST", path, payload=payload, timeout=timeout)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5030")
    parser.add_argument("--drone-ids", nargs="+", type=int)
    parser.add_argument("--drones")
    parser.add_argument("--param-name", default=DEFAULT_PARAM_NAME)
    parser.add_argument("--float-delta", type=float, default=1.0)
    parser.add_argument("--json-output")
    return parser.parse_args()


def resolve_selected_ids(args: argparse.Namespace) -> list[int]:
    if args.drone_ids:
        return normalize_drone_ids(args.drone_ids)
    if args.drones:
        return parse_csv_drone_ids(args.drones)
    return [1, 2]


def wait_for_health(client: ApiClient) -> None:
    def ready():
        try:
            payload = client.get_json(GCS_SYSTEM_HEALTH_ROUTE, timeout=5.0)
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            return False
        return payload if payload.get("status") == "ok" else False
    wait_for(ready, label="GCS health", timeout=45)


def get_policy(client: ApiClient) -> dict[str, Any]:
    policy = client.get_json(GCS_PX4_PARAMS_POLICY_ROUTE)
    require(policy.get("subsystem") == "px4_params", f"Unexpected policy payload: {policy}")
    return policy


def wait_for(predicate, *, label: str, timeout: int = 90, interval: float = 1.0):
    deadline = time.time() + timeout
    last_value = None
    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            log(f"WAIT OK: {label}")
            return last_value
        time.sleep(interval)
    raise RuntimeError(f"Timed out waiting for {label}. Last value: {last_value!r}")


def _selected_drone_api_health_snapshot(client: ApiClient, drone_ids: list[int]) -> dict[str, dict[str, Any]] | bool:
    telemetry = client.get_telemetry()
    for drone_id in drone_ids:
        row = telemetry.get(str(drone_id))
        if row is None:
            return False

        drone_ip = str(row.get("ip") or "").strip()
        if not drone_ip or drone_ip.upper() == "N/A":
            return False

        try:
            health = client.get_drone_json(drone_ip, DRONE_SYSTEM_HEALTH_ROUTE, timeout=5.0)
        except (RuntimeError, urllib.error.URLError, TimeoutError):
            return False

        if health.get("status") != "ok":
            return False

    return telemetry


def wait_for_selected_drone_api_health(
    client: ApiClient,
    drone_ids: list[int],
    *,
    timeout: int = 120,
) -> dict[str, dict[str, Any]]:
    return wait_for(
        lambda: _selected_drone_api_health_snapshot(client, drone_ids),
        label=f"drone-local API health for PX4 param targets {drone_ids}",
        timeout=timeout,
        interval=2.0,
    )


def refresh_snapshots(client: ApiClient, drone_ids: list[int], *, component_id: int) -> dict[str, dict[str, Any]]:
    payload = client.post_json(
        GCS_PX4_PARAMS_SNAPSHOTS_ROUTE,
        {
            "hw_ids": [str(drone_id) for drone_id in drone_ids],
            "component_id": component_id,
        },
    )
    errors = payload.get("errors") or []
    require(not errors, f"Snapshot refresh returned errors: {errors}")
    snapshots = {
        str(snapshot["snapshot"]["hw_id"]): snapshot
        for snapshot in payload.get("snapshots", [])
    }
    require(len(snapshots) == len(drone_ids), f"Expected {len(drone_ids)} snapshots, got {list(snapshots)}")
    return snapshots


def find_param_row(snapshot: dict[str, Any], param_name: str) -> dict[str, Any]:
    normalized_name = str(param_name).strip().upper()
    for row in snapshot.get("rows", []):
        if str(row.get("name", "")).strip().upper() == normalized_name:
            return row
    raise RuntimeError(f"Parameter {normalized_name} not found in snapshot {snapshot.get('snapshot', {}).get('snapshot_id')}")


def choose_param_value(row: dict[str, Any], *, delta: float) -> int | float:
    value_type = str(row.get("value_type", "")).strip().lower()
    current_value = row.get("value")
    require(value_type in {"int", "float"}, f"Validator only supports int/float params, got {value_type!r}")

    if value_type == "int":
        base_value = int(current_value)
        candidate = base_value + max(1, int(round(delta)))
        min_value = row.get("min_value")
        max_value = row.get("max_value")
        if max_value is not None and candidate > int(max_value):
            candidate = base_value - max(1, int(round(delta)))
        if min_value is not None and candidate < int(min_value):
            raise RuntimeError(f"Unable to choose a safe integer test value for {row.get('name')}")
        require(candidate != base_value, f"Chosen integer test value for {row.get('name')} did not change")
        return candidate

    base_value = float(current_value)
    candidate = base_value + float(delta)
    min_value = row.get("min_value")
    max_value = row.get("max_value")
    if max_value is not None and candidate > float(max_value):
        candidate = base_value - float(delta)
    if min_value is not None and candidate < float(min_value):
        raise RuntimeError(f"Unable to choose a safe float test value for {row.get('name')}")
    require(not math.isclose(candidate, base_value, rel_tol=0.0, abs_tol=1e-6), f"Chosen float test value for {row.get('name')} did not change")
    return round(candidate, 6)


def build_qgc_file(*, hw_id: str, component_id: int, name: str, value: int | float, value_type: str) -> str:
    mav_type = 6 if value_type == "int" else 9
    return (
        "# QGroundControl Parameter File\n"
        "# Vehicle-Id\tComponent-Id\tName\tValue\tType\n"
        f"{hw_id}\t{component_id}\t{name}\t{value}\t{mav_type}\n"
    )


def diff_imported_patch(client: ApiClient, snapshot_id: str, import_entries: list[dict[str, Any]]) -> dict[str, Any]:
    return client.post_json(
        GCS_PX4_PARAMS_DIFF_ROUTE,
        {
            "snapshot_id": snapshot_id,
            "desired_entries": import_entries,
            "include_unchanged": False,
        },
    )


def run_patch_job(
    client: ApiClient,
    *,
    drone_ids: list[int],
    source: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    review = client.post_json(
        GCS_PX4_PARAMS_REVIEWS_ROUTE,
        {
            "hw_ids": [str(drone_id) for drone_id in drone_ids],
            "source": source,
            "verify_readback": True,
            "entries": entries,
        },
    )
    require(not review.get("blocked"), f"Parameter review was blocked: {review}")
    require(review.get("review_id") and review.get("review_hash"), "Review identity missing")
    terminal = submit_review_job(client, review)
    require(terminal.get("status") in {"completed", "partial"}, f"Unexpected patch-job status: {terminal}")
    return terminal


def submit_review_job(client: ApiClient, review: dict[str, Any]) -> dict[str, Any]:
    request = {"review_id": review["review_id"], "review_hash": review["review_hash"],
               "idempotency_key": f"sitl-param-{uuid.uuid4().hex}"}
    receipt = client.post_json(GCS_PX4_PARAMS_PATCH_JOBS_ROUTE, request)
    require(receipt.get("job_id"), f"Accepted parameter receipt missing: {receipt}")
    job_path = GCS_PX4_PARAMS_PATCH_JOB_ROUTE_TEMPLATE.format(job_id=receipt["job_id"])
    terminal = wait_for(
        lambda: (job if (job := client.get_json(job_path)).get("terminal") else None),
        label=f"parameter receipt {receipt['job_id']}", timeout=120,
    )
    # A repeated accepted request must return the same receipt, not issue a new write.
    replay = client.post_json(GCS_PX4_PARAMS_PATCH_JOBS_ROUTE, request)
    require(replay.get("job_id") == receipt["job_id"], "Idempotent replay returned a different parameter job")
    return terminal


def assert_patch_job_success(job: dict[str, Any], *, expect_targets: int) -> None:
    require(int(job.get("total_targets", 0)) == expect_targets, f"Unexpected patch-job target count: {job}")
    results = job.get("results") or []
    require(len(results) == expect_targets, f"Unexpected patch-job result count: {job}")
    for result in results:
        require(not result.get("error"), f"Patch-job result reported error: {result}")
        require(bool(result.get("applied")), f"Patch-job did not apply cleanly: {result}")
        require(bool(result.get("verified")), f"Patch-job did not verify cleanly: {result}")


def validate_snapshot_value(snapshot: dict[str, Any], *, param_name: str, expected_value: int | float) -> None:
    row = find_param_row(snapshot, param_name)
    actual_value = row.get("value")
    require(parameter_values_match(row["value_type"], expected_value, actual_value),
            f"{param_name} expected {expected_value}, got {actual_value}")


def select_baseline_rows(
    baseline_rows: dict[str, dict[str, Any]],
    drone_ids: list[int],
) -> dict[str, dict[str, Any]]:
    return {
        str(drone_id): baseline_rows[str(drone_id)]
        for drone_id in drone_ids
    }


def restore_baseline(client: ApiClient, baseline_rows: dict[str, dict[str, Any]], *,
                     drone_ids: list[int], component_id: int, param_name: str) -> list[dict[str, Any]]:
    """Best-effort every target independently, then prove actual restored values.

    This is an explicit SITL repair review, not an atomic rollback. A failed
    earlier target must not prevent attempting restoration of later targets.
    """
    evidence, errors = [], []
    for hw_id in drone_ids:
        try:
            original = baseline_rows[str(hw_id)]
            current = refresh_snapshots(client, [hw_id], component_id=component_id)[str(hw_id)]
            row = find_param_row(current, param_name)
            if parameter_values_match(original["value_type"], original["value"], row["value"]):
                evidence.append({"hw_id": str(hw_id), "outcome": "already_at_baseline",
                                 "snapshot_id": current["snapshot"]["snapshot_id"]})
                continue
            job = run_patch_job(client, drone_ids=[hw_id], source="manual", entries=[{
                "component_id": component_id, "name": param_name,
                "value_type": original["value_type"], "value": original["value"],
            }])
            assert_patch_job_success(job, expect_targets=1)
            refreshed = refresh_snapshots(client, [hw_id], component_id=component_id)[str(hw_id)]
            validate_snapshot_value(refreshed, param_name=param_name, expected_value=original["value"])
            evidence.append({"hw_id": str(hw_id), "outcome": "baseline_verified", "job_id": job["job_id"]})
        except Exception as exc:
            errors.append(f"H{hw_id}: {exc}")
    require(not errors, "Baseline restoration not confirmed: " + "; ".join(errors))
    return evidence


def main() -> int:
    args = parse_args()
    selected_ids = resolve_selected_ids(args)
    client = ApiClient(args.base_url)
    param_name = str(args.param_name).strip().upper()

    wait_for_health(client)
    target_runtime = fetch_and_require_sitl_runtime(args.base_url)
    policy = get_policy(client)
    component_id = int(policy.get("mutations", {}).get("supported_component_ids", [1])[0])
    wait_for_selected_drone_api_health(client, selected_ids)

    snapshots = refresh_snapshots(client, selected_ids, component_id=component_id)
    baseline_rows = {
        hw_id: find_param_row(snapshot, param_name)
        for hw_id, snapshot in snapshots.items()
    }

    primary_hw_id = str(selected_ids[0])
    primary_row = baseline_rows[primary_hw_id]
    single_value = choose_param_value(primary_row, delta=args.float_delta)

    log(f"Using parameter {param_name} for validation on targets {selected_ids}")

    qgc_import = client.post_json(
        GCS_PX4_PARAMS_QGC_IMPORT_ROUTE,
        {
            "content": build_qgc_file(
                hw_id=primary_hw_id,
                component_id=component_id,
                name=param_name,
                value=single_value,
                value_type=primary_row["value_type"],
            )
        },
    )
    require(int(qgc_import.get("total_entries", 0)) == 1, f"Unexpected QGC import payload: {qgc_import}")

    diff_response = diff_imported_patch(client, snapshots[primary_hw_id]["snapshot"]["snapshot_id"], qgc_import["entries"])
    require(int(diff_response.get("total_changed", 0)) >= 1, f"Expected at least one changed row, got: {diff_response}")

    batch_rows = select_baseline_rows(baseline_rows, selected_ids)
    batch_value = choose_param_value(batch_rows[str(selected_ids[-1])], delta=args.float_delta + 0.5)
    mutation_error = None
    restoration = []
    try:
        single_job = run_patch_job(client, drone_ids=[int(primary_hw_id)], source="qgc_import", entries=qgc_import["entries"])
        assert_patch_job_success(single_job, expect_targets=1)
        refreshed_primary = refresh_snapshots(client, [int(primary_hw_id)], component_id=component_id)[primary_hw_id]
        validate_snapshot_value(refreshed_primary, param_name=param_name, expected_value=single_value)
        batch_job = run_patch_job(client, drone_ids=selected_ids, source="manual", entries=[{
            "component_id": component_id, "name": param_name,
            "value_type": primary_row["value_type"], "value": batch_value,
        }])
        assert_patch_job_success(batch_job, expect_targets=len(selected_ids))
        refreshed_batch = refresh_snapshots(client, selected_ids, component_id=component_id)
        for hw_id in refreshed_batch:
            validate_snapshot_value(refreshed_batch[hw_id], param_name=param_name, expected_value=batch_value)
        # Simulate another operator changing the aircraft after review. A stale
        # proposal must be rejected natively, not silently overwrite that value.
        stale_entry = {"component_id": component_id, "name": param_name,
                       "value_type": primary_row["value_type"], "value": single_value}
        stale_review = client.post_json(GCS_PX4_PARAMS_REVIEWS_ROUTE, {
            "hw_ids": [primary_hw_id], "source": "manual", "verify_readback": True,
            "entries": [stale_entry],
        })
        require(not stale_review.get("blocked"), f"Conflict-test preparation failed: {stale_review}")
        interference_value = choose_param_value({**primary_row, "value": batch_value}, delta=0.25)
        external_change = run_patch_job(client, drone_ids=[int(primary_hw_id)], source="manual", entries=[{
            **stale_entry, "value": interference_value,
        }])
        assert_patch_job_success(external_change, expect_targets=1)
        rejected = submit_review_job(client, stale_review)
        require(rejected.get("status") == "failed" and rejected.get("failed_targets") == 1,
                f"Stale expected values were not rejected: {rejected}")
        require(all(not item.get("applied") for item in rejected.get("results", [])),
                f"A stale review reported a write: {rejected}")
        unchanged = refresh_snapshots(client, [int(primary_hw_id)], component_id=component_id)[primary_hw_id]
        validate_snapshot_value(unchanged, param_name=param_name, expected_value=interference_value)
    except Exception as exc:
        mutation_error = exc
    finally:
        try:
            restoration = restore_baseline(client, batch_rows, drone_ids=selected_ids,
                                           component_id=component_id, param_name=param_name)
        except Exception as restore_error:
            raise RuntimeError(f"Validation error: {mutation_error}; restoration error: {restore_error}") from restore_error
    if mutation_error:
        raise mutation_error

    report = {
        "success": True,
        "base_url": args.base_url,
        "target_runtime": target_runtime,
        "drone_ids": selected_ids,
        "param_name": param_name,
        "single_target": primary_hw_id,
        "single_test_value": single_value,
        "batch_test_value": batch_value,
        "restoration": restoration,
        "idempotent_receipt_replay_checked": True,
        "stale_review_native_rejection_checked": True,
        "policy": {
            "docs_version": policy.get("docs", {}).get("version"),
            "require_disarmed": policy.get("mutations", {}).get("require_disarmed"),
        },
    }
    write_json_report(args.json_output, report)
    log("PX4 parameter runtime validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
