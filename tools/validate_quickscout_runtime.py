#!/usr/bin/env python3
"""Validate the QuickScout workflow against a live GCS/SITL stack.

This validator intentionally starts narrow and deterministic:

1. Wait for a clean ready/idle fleet baseline
2. Plan a single-drone last-known-point QuickScout mission from live telemetry
3. Launch the mission and confirm the selected aircraft climbs and begins searching
4. Pause into HOLD and confirm the mission enters the holding phase
5. Confirm direct resume is rejected with explicit replan guidance
6. Abort with return-home and confirm the fleet returns to a clean idle baseline

The validator also confirms that non-target drones stay idle throughout the
drill and that no active commands remain at the end.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

try:
    from src.gcs_api_routes import (
        GCS_ACTIVE_COMMANDS_ROUTE,
        GCS_COMMAND_STATUS_ROUTE_TEMPLATE,
        GCS_FLEET_TELEMETRY_ROUTE,
        GCS_SYSTEM_HEALTH_ROUTE,
    )
    from src.params import Params
    from tools.runtime_validation_support import normalize_drone_ids, parse_csv_drone_ids, write_json_report
except Exception:  # pragma: no cover - fallback only
    class _FallbackParams:
        TELEMETRY_POLLING_TIMEOUT = 10
        heartbeat_interval = 10

    Params = _FallbackParams()
    GCS_SYSTEM_HEALTH_ROUTE = "/api/v1/system/health"
    GCS_FLEET_TELEMETRY_ROUTE = "/api/v1/fleet/telemetry"
    GCS_ACTIVE_COMMANDS_ROUTE = "/api/v1/commands/active"
    GCS_COMMAND_STATUS_ROUTE_TEMPLATE = "/api/v1/commands/{command_id}"

    def normalize_drone_ids(ids):
        normalized = sorted({int(drone_id) for drone_id in ids})
        if not normalized:
            raise RuntimeError("No drone IDs supplied.")
        return normalized

    def parse_csv_drone_ids(raw):
        return normalize_drone_ids(int(part.strip()) for part in str(raw).split(",") if part.strip())

    def write_json_report(path, payload):
        if path is None:
            return
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


COMMAND_HEARTBEAT_GRACE_SECONDS = max(
    getattr(Params, "TELEMETRY_POLLING_TIMEOUT", 10),
    getattr(Params, "heartbeat_interval", 10) * 2,
)
TERMINAL_COMMAND_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout", "superseded"}


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
        query: dict[str, Any] | list[tuple[str, Any]] | None = None,
        payload: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        encoded_query = ""
        if query:
            encoded_query = "?" + urllib.parse.urlencode(query, doseq=True)
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}{encoded_query}",
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

    def post_json(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        query: dict[str, Any] | list[tuple[str, Any]] | None = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        return self.request_json("POST", path, query=query, payload=payload, timeout=timeout)

    def get_telemetry(self) -> dict[str, dict[str, Any]]:
        payload = self.get_json(GCS_FLEET_TELEMETRY_ROUTE)
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}


def wait_for(predicate, *, label: str, timeout: int = 90, interval: float = 1.0):
    deadline = time.time() + timeout
    last_value = None
    while time.time() < deadline:
        last_value = predicate()
        if last_value:
            log(f"READY: {label}")
            return last_value
        time.sleep(interval)
    raise RuntimeError(f"Timed out waiting for {label}. Last value: {last_value!r}")


def _telemetry_has_ids(telemetry: dict[str, dict[str, Any]], ids: list[int]) -> bool:
    return all(str(idx) in telemetry for idx in ids)


def _is_idle_baseline_row(row: dict[str, Any]) -> bool:
    heartbeat_last_seen = row.get("heartbeat_last_seen")
    has_recent_heartbeat = False
    if heartbeat_last_seen is not None:
        try:
            heartbeat_age = time.time() - (float(heartbeat_last_seen) / 1000.0)
            has_recent_heartbeat = heartbeat_age <= COMMAND_HEARTBEAT_GRACE_SECONDS
        except (TypeError, ValueError):
            has_recent_heartbeat = False

    mission = int(row.get("mission", 0) or 0)
    state = int(row.get("state", 0) or 0)
    home_position_set = row.get("home_position_set")
    return (
        row.get("update_time") is not None
        and bool(row.get("is_ready_to_arm"))
        and row.get("readiness_status") == "ready"
        and not bool(row.get("is_armed"))
        and mission == 0
        and state == 0
        and (home_position_set is None or bool(home_position_set))
        and has_recent_heartbeat
    )


def _is_idle_reset_row(row: dict[str, Any]) -> bool:
    mission = int(row.get("mission", 0) or 0)
    state = int(row.get("state", 0) or 0)
    return not bool(row.get("is_armed")) and mission == 0 and state == 0


def _is_airborne_row(row: dict[str, Any], baseline_altitude: float, *, min_gain: float) -> bool:
    try:
        altitude = float(row.get("position_alt", 0.0))
    except (TypeError, ValueError):
        return False
    return bool(row.get("is_armed")) and altitude >= (baseline_altitude + min_gain)


def resolve_selected_ids(args: argparse.Namespace) -> list[int]:
    if args.drone_ids:
        return normalize_drone_ids(args.drone_ids)
    if args.drones:
        return parse_csv_drone_ids(args.drones)
    return [1, 2, 3]


def select_primary_target(telemetry: dict[str, dict[str, Any]], selected_ids: list[int]) -> tuple[int, dict[str, Any]]:
    for drone_id in selected_ids:
        row = telemetry.get(str(drone_id)) or {}
        if row.get("position_lat") is None or row.get("position_long") is None:
            continue
        if row.get("pos_id") is None:
            continue
        return drone_id, row
    raise RuntimeError(f"No selected drone has live GPS + pos_id telemetry: {selected_ids}")


def build_last_known_point_request(
    row: dict[str, Any],
    *,
    pos_id: int,
    radius_m: float,
    altitude_gain_m: float,
    sweep_width_m: float,
    overlap_percent: float,
    cruise_speed_ms: float,
    survey_speed_ms: float,
) -> dict[str, Any]:
    current_alt_msl = float(row.get("position_alt", 0.0) or 0.0)
    cruise_altitude_msl = max(20.0, current_alt_msl + float(altitude_gain_m))
    return {
        "mission_template": "last_known_point",
        "search_area": {
            "type": "point",
            "center": {
                "lat": float(row["position_lat"]),
                "lng": float(row["position_long"]),
            },
            "radius_m": float(radius_m),
        },
        "survey_config": {
            "algorithm": "boustrophedon",
            "sweep_width_m": float(sweep_width_m),
            "overlap_percent": float(overlap_percent),
            "cruise_altitude_msl": cruise_altitude_msl,
            "survey_altitude_agl": float(altitude_gain_m),
            "cruise_speed_ms": float(cruise_speed_ms),
            "survey_speed_ms": float(survey_speed_ms),
            "use_terrain_following": False,
            "camera_interval_s": 2.0,
        },
        "pos_ids": [int(pos_id)],
        "mission_label": "QuickScout Runtime Validator",
        "mission_profile": "runtime_last_known_point",
        "mission_brief": "Runtime validator search package",
        "return_behavior": "return_home",
    }


def wait_api_ready(client: ApiClient, timeout: int = 60) -> dict[str, Any]:
    def _ready():
        try:
            return client.get_json(GCS_SYSTEM_HEALTH_ROUTE)
        except Exception:
            return False

    return wait_for(_ready, label="GCS API health endpoint", timeout=timeout, interval=2.0)


def wait_fleet_ready(client: ApiClient, ids: list[int], timeout: int = 120) -> dict[str, dict[str, Any]]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_idle_baseline_row(row) for row in rows.values()):
            return False
        return rows

    return wait_for(_ready, label=f"drones {ids} ready, idle, and launchable", timeout=timeout, interval=2.0)


def wait_idle_subset(client: ApiClient, ids: list[int], timeout: int = 240) -> dict[str, dict[str, Any]]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_idle_reset_row(row) for row in rows.values()):
            return False
        return rows

    return wait_for(_ready, label=f"drones {ids} disarmed and idle", timeout=timeout, interval=2.0)


def wait_non_targets_idle(client: ApiClient, ids: list[int], timeout: int = 120) -> dict[str, dict[str, Any]]:
    if not ids:
        return {}

    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_idle_baseline_row(row) for row in rows.values()):
            return False
        return rows

    return wait_for(_ready, label=f"non-target drones {ids} remain idle", timeout=timeout, interval=2.0)


def wait_target_airborne(
    client: ApiClient,
    target_id: int,
    *,
    baseline_altitude: float,
    min_gain: float,
    timeout: int = 180,
) -> dict[str, Any]:
    def _ready():
        telemetry = client.get_telemetry()
        row = telemetry.get(str(target_id))
        if row is None:
            return False
        if not _is_airborne_row(row, baseline_altitude, min_gain=min_gain):
            return False
        return row

    return wait_for(
        _ready,
        label=f"drone {target_id} airborne with +{min_gain:.1f}m gain",
        timeout=timeout,
        interval=2.0,
    )


def wait_active_commands_clear(client: ApiClient, timeout: int = 120) -> dict[str, Any]:
    def _ready():
        payload = client.get_json(GCS_ACTIVE_COMMANDS_ROUTE)
        return payload if int(payload.get("total", 0) or 0) == 0 else False

    return wait_for(_ready, label="no active commands", timeout=timeout, interval=2.0)


def wait_status_phase(
    client: ApiClient,
    mission_id: str,
    desired_phases: set[str],
    *,
    timeout: int = 120,
    interval: float = 2.0,
) -> dict[str, Any]:
    last = None

    def _ready():
        nonlocal last
        status = client.get_json(f"/api/sar/mission/{mission_id}/status")
        last = status
        return status if str(status.get("operation_phase") or "") in desired_phases else False

    try:
        return wait_for(
            _ready,
            label=f"QuickScout phase {'/'.join(sorted(desired_phases))} for mission {mission_id}",
            timeout=timeout,
            interval=interval,
        )
    except Exception as exc:
        raise RuntimeError(
            f"{exc}. Last QuickScout status: {json.dumps(last or {}, indent=2)}"
        ) from exc


def wait_command_terminal(client: ApiClient, command_id: str, *, timeout: int = 240) -> dict[str, Any]:
    last = None

    def _ready():
        nonlocal last
        status = client.get_json(GCS_COMMAND_STATUS_ROUTE_TEMPLATE.format(command_id=command_id))
        last = status
        return status if str(status.get("status") or "").lower() in TERMINAL_COMMAND_STATUSES else False

    try:
        return wait_for(_ready, label=f"command {command_id} terminal", timeout=timeout, interval=1.0)
    except Exception as exc:
        raise RuntimeError(
            f"{exc}. Last command status: {json.dumps(last or {}, indent=2)}"
        ) from exc


def require_command_success(status: dict[str, Any], *, expected_accepts: int, expected_successes: int, label: str) -> None:
    acks = status.get("acks") or {}
    executions = status.get("executions") or {}
    accepted = int(acks.get("accepted", 0) or 0)
    succeeded = int(executions.get("succeeded", 0) or 0)
    require(
        accepted == expected_accepts,
        f"{label} acceptance mismatch. Expected {expected_accepts}, got {accepted}: {json.dumps(status, indent=2)}",
    )
    require(
        succeeded == expected_successes,
        f"{label} execution mismatch. Expected {expected_successes}, got {succeeded}: {json.dumps(status, indent=2)}",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate QuickScout against a live GCS/SITL runtime.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="GCS API base URL")
    parser.add_argument("--drones", default=None, help="Comma-separated drone hardware IDs to observe")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=None, help="Space-separated drone hardware IDs to observe")
    parser.add_argument("--point-radius-m", type=float, default=120.0, help="Last-known-point search radius in metres")
    parser.add_argument("--altitude-gain-m", type=float, default=20.0, help="Requested survey altitude gain used in the planning payload")
    parser.add_argument("--airborne-min-gain", type=float, default=6.0, help="Minimum observed altitude gain required after launch")
    parser.add_argument("--sweep-width-m", type=float, default=25.0, help="Sweep width used for the runtime search package")
    parser.add_argument("--overlap-percent", type=float, default=20.0, help="Sweep overlap percentage for the runtime search package")
    parser.add_argument("--cruise-speed-ms", type=float, default=8.0, help="Cruise speed used in the runtime search package")
    parser.add_argument("--survey-speed-ms", type=float, default=4.0, help="Survey speed used in the runtime search package")
    parser.add_argument("--min-estimated-coverage-s", type=float, default=90.0, help="Minimum planned duration required before launch")
    parser.add_argument("--abort-return-behavior", default="return_home", choices=["return_home", "land_current", "hold_position"], help="Mission-end command issued during the abort drill")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional path to write the final validation summary JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selected_ids = resolve_selected_ids(args)
    client = ApiClient(args.base_url)

    artifacts: dict[str, Any] = {
        "selected_drone_ids": selected_ids,
        "base_url": args.base_url,
        "stages": {},
    }

    health = wait_api_ready(client)
    artifacts["stages"]["health"] = health

    baseline_rows = wait_fleet_ready(client, selected_ids)
    artifacts["stages"]["baseline_ready"] = baseline_rows

    target_id, target_row = select_primary_target(baseline_rows, selected_ids)
    target_pos_id = int(target_row["pos_id"])
    baseline_altitude = float(target_row.get("position_alt", 0.0) or 0.0)
    non_target_ids = [drone_id for drone_id in selected_ids if drone_id != target_id]

    plan_request = build_last_known_point_request(
        target_row,
        pos_id=target_pos_id,
        radius_m=args.point_radius_m,
        altitude_gain_m=args.altitude_gain_m,
        sweep_width_m=args.sweep_width_m,
        overlap_percent=args.overlap_percent,
        cruise_speed_ms=args.cruise_speed_ms,
        survey_speed_ms=args.survey_speed_ms,
    )
    artifacts["stages"]["plan_request"] = plan_request
    log(f"PLANNING QuickScout runtime mission for hw_id={target_id} pos_id={target_pos_id}")
    plan_response = client.post_json("/api/sar/mission/plan", plan_request)
    artifacts["stages"]["plan_response"] = plan_response
    mission_id = str(plan_response["mission_id"])
    require(
        float(plan_response.get("estimated_coverage_time_s", 0.0) or 0.0) >= float(args.min_estimated_coverage_s),
        f"QuickScout runtime plan is too short for a meaningful live drill: {plan_response.get('estimated_coverage_time_s')}s",
    )

    workspace = client.get_json(f"/api/sar/mission/{mission_id}/workspace")
    artifacts["stages"]["workspace"] = workspace
    operation = workspace.get("operation") or {}
    plans = operation.get("plans") or []
    require(operation.get("mission_template") == "last_known_point", "Workspace did not persist the last_known_point template")
    require(operation.get("pos_ids") == [target_pos_id], f"Workspace target pos_ids mismatch: {operation.get('pos_ids')}")
    require(len(plans) == 1, f"Expected exactly one QuickScout plan for runtime validation, got {len(plans)}")
    require(int(plans[0].get("pos_id", -1)) == target_pos_id, f"QuickScout plan pos_id mismatch: {plans[0]}")
    target_hw_id = str(plans[0].get("hw_id"))
    require(target_hw_id == str(target_id), f"QuickScout plan hw_id mismatch. Expected {target_id}, got {target_hw_id}")

    log(f"LAUNCHING QuickScout mission {mission_id} on hw_id={target_hw_id}")
    launch_response = client.post_json("/api/sar/mission/launch", query={"mission_id": mission_id})
    artifacts["stages"]["launch_response"] = launch_response
    require(bool(launch_response.get("success")), f"QuickScout launch did not succeed: {json.dumps(launch_response, indent=2)}")
    require(target_hw_id in {str(hw_id) for hw_id in launch_response.get("launched_hw_ids", [])}, f"Target hw_id {target_hw_id} was not launched")

    searching_status = wait_status_phase(client, mission_id, {"searching", "launch_partial"})
    artifacts["stages"]["searching_status"] = searching_status

    airborne_row = wait_target_airborne(
        client,
        target_id,
        baseline_altitude=baseline_altitude,
        min_gain=args.airborne_min_gain,
    )
    artifacts["stages"]["target_airborne"] = airborne_row

    if non_target_ids:
        artifacts["stages"]["non_target_idle_after_launch"] = wait_non_targets_idle(client, non_target_ids)

    pause_response = client.post_json(
        f"/api/sar/mission/{mission_id}/pause",
        query=[("pos_ids", target_pos_id)],
    )
    artifacts["stages"]["pause_response"] = pause_response
    require(bool(pause_response.get("success")), f"QuickScout pause was not accepted: {json.dumps(pause_response, indent=2)}")
    require(
        str(target_hw_id) in {str(hw_id) for hw_id in pause_response.get("accepted_hw_ids", [])},
        f"Pause did not target the launched drone: {json.dumps(pause_response, indent=2)}",
    )
    pause_command = pause_response.get("command") or {}
    pause_command_id = pause_command.get("command_id")
    require(pause_command_id, "Pause response did not include a tracked command_id")
    pause_command_status = wait_command_terminal(client, pause_command_id, timeout=180)
    artifacts["stages"]["pause_command_status"] = pause_command_status
    require_command_success(pause_command_status, expected_accepts=1, expected_successes=1, label="QuickScout pause")

    holding_status = wait_status_phase(client, mission_id, {"holding"}, timeout=90)
    artifacts["stages"]["holding_status"] = holding_status
    require(
        str((holding_status.get("control_availability") or {}).get("replan_enabled")).lower() == "true",
        "Holding status did not expose replan guidance",
    )

    resume_response = client.post_json(
        f"/api/sar/mission/{mission_id}/resume",
        query=[("pos_ids", target_pos_id)],
    )
    artifacts["stages"]["resume_response"] = resume_response
    require(resume_response.get("success") is False, "QuickScout resume unexpectedly succeeded")
    require(resume_response.get("effect") == "replan_required", f"Unexpected resume effect: {resume_response}")
    require(resume_response.get("state_changed") is False, f"Resume unexpectedly changed mission state: {resume_response}")

    holding_status_after_resume = client.get_json(f"/api/sar/mission/{mission_id}/status")
    artifacts["stages"]["holding_status_after_resume"] = holding_status_after_resume
    require(
        holding_status_after_resume.get("operation_phase") == "holding",
        f"Mission left holding after resume rejection: {json.dumps(holding_status_after_resume, indent=2)}",
    )

    abort_response = client.post_json(
        f"/api/sar/mission/{mission_id}/abort",
        query=[
            ("pos_ids", target_pos_id),
            ("return_behavior", args.abort_return_behavior),
        ],
    )
    artifacts["stages"]["abort_response"] = abort_response
    require(bool(abort_response.get("success")), f"QuickScout abort was not accepted: {json.dumps(abort_response, indent=2)}")
    abort_command = abort_response.get("command") or {}
    abort_command_id = abort_command.get("command_id")
    require(abort_command_id, "Abort response did not include a tracked command_id")
    abort_command_status = wait_command_terminal(client, abort_command_id, timeout=420)
    artifacts["stages"]["abort_command_status"] = abort_command_status
    require_command_success(abort_command_status, expected_accepts=1, expected_successes=1, label="QuickScout abort")

    return_status = wait_status_phase(client, mission_id, {"return_commanded", "aborted"}, timeout=60)
    artifacts["stages"]["return_commanded_status"] = return_status

    final_idle = wait_idle_subset(client, selected_ids, timeout=420)
    artifacts["stages"]["final_idle"] = final_idle
    final_ready = wait_fleet_ready(client, selected_ids, timeout=240)
    artifacts["stages"]["final_ready"] = final_ready
    active_commands = wait_active_commands_clear(client, timeout=180)
    artifacts["stages"]["active_commands"] = active_commands

    write_json_report(args.json_output, artifacts)
    log("QuickScout runtime validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
