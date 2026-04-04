#!/usr/bin/env python3
"""
End-to-end action/control validation for SITL fleets.

This validator covers the operator-facing control actions that are not specific
to a mission-planning domain:

1. Wait for the GCS API and selected drones to reach a clean idle baseline
2. Probe live launch readiness on the selected drones
3. Dispatch TAKEOFF to the selected fleet and confirm climb
4. Dispatch HOLD to the selected fleet and confirm they remain airborne
5. Dispatch RETURN_RTL to one drone (or the full fleet when only one drone is selected)
6. Confirm non-target drones remain airborne after the targeted RTL override
7. Dispatch LAND to the remaining drones and verify the fleet returns idle

This validator intentionally exercises:

- action command acceptance / execution tracking
- per-drone targeting
- mid-air override behavior
- clean return-to-idle after standalone actions
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

USING_FALLBACK_TIMEOUT_PARAMS = False

try:
    from src.drone_api_routes import DRONE_LIVE_ARMABILITY_ROUTE
    from src.flight_timeout_utils import calculate_land_disarm_timeout, calculate_rtl_completion_timeout
    from src.gcs_api_routes import (
        GCS_COMMAND_STATUS_ROUTE_TEMPLATE,
        GCS_COMMANDS_ROUTE,
        GCS_FLEET_TELEMETRY_ROUTE,
        GCS_SYSTEM_HEALTH_ROUTE,
    )
    from src.live_armability_utils import calculate_live_armability_request_timeout
    from src.params import Params
    from tools.runtime_validation_support import normalize_drone_ids, parse_csv_drone_ids, write_json_report
except Exception:  # pragma: no cover - fallback only
    USING_FALLBACK_TIMEOUT_PARAMS = True

    class _FallbackParams:
        TELEMETRY_POLLING_TIMEOUT = 10
        heartbeat_interval = 10
        LAND_ACTION_MIN_DISARM_WAIT_SEC = 45
        LAND_ACTION_ASSUMED_DESCENT_RATE_MPS = 2.5
        LAND_ACTION_DISARM_BUFFER_SEC = 30
        LAND_ACTION_MAX_DISARM_WAIT_SEC = 900
        RTL_ACTION_COMPLETION_TIMEOUT = 300
        RTL_ACTION_COMPLETION_BUFFER_SEC = 120
        RTL_ACTION_COMPLETION_MAX_TIMEOUT = 1200
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC = 5.0
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC = 2.0

    Params = _FallbackParams()
    DRONE_LIVE_ARMABILITY_ROUTE = "/api/v1/preflight/armability"
    GCS_SYSTEM_HEALTH_ROUTE = "/api/v1/system/health"
    GCS_FLEET_TELEMETRY_ROUTE = "/api/v1/fleet/telemetry"
    GCS_COMMANDS_ROUTE = "/api/v1/commands"
    GCS_COMMAND_STATUS_ROUTE_TEMPLATE = "/api/v1/commands/{command_id}"

    def normalize_drone_ids(ids):
        normalized = sorted({int(drone_id) for drone_id in ids})
        if not normalized:
            raise RuntimeError("No drone IDs supplied.")
        return normalized

    def parse_csv_drone_ids(raw):
        ids = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
        return normalize_drone_ids(ids)

    def write_json_report(path, payload):
        if path is None:
            return
        report_path = Path(path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def calculate_land_disarm_timeout(relative_altitude_m, *, params=Params):
        minimum_wait = int(getattr(params, "LAND_ACTION_MIN_DISARM_WAIT_SEC", 45))
        if relative_altitude_m is None:
            return minimum_wait
        altitude_m = max(0.0, float(relative_altitude_m))
        descent_rate = max(0.1, float(getattr(params, "LAND_ACTION_ASSUMED_DESCENT_RATE_MPS", 2.5)))
        buffer_sec = max(0, int(getattr(params, "LAND_ACTION_DISARM_BUFFER_SEC", 30)))
        maximum_wait = max(minimum_wait, int(getattr(params, "LAND_ACTION_MAX_DISARM_WAIT_SEC", 900)))
        return max(minimum_wait, min(maximum_wait, int(math.ceil(minimum_wait + (altitude_m / descent_rate) + buffer_sec))))

    def calculate_rtl_completion_timeout(relative_altitude_m, *, params=Params):
        base_timeout = int(getattr(params, "RTL_ACTION_COMPLETION_TIMEOUT", 300))
        rtl_buffer_sec = max(0, int(getattr(params, "RTL_ACTION_COMPLETION_BUFFER_SEC", 120)))
        maximum_timeout = max(base_timeout, int(getattr(params, "RTL_ACTION_COMPLETION_MAX_TIMEOUT", 1200)))
        landing_timeout = calculate_land_disarm_timeout(relative_altitude_m, params=params)
        estimated_wait = landing_timeout + rtl_buffer_sec
        return max(base_timeout, min(maximum_timeout, estimated_wait))

    def calculate_live_armability_request_timeout(*, params=Params):
        connect_timeout = max(0.1, float(getattr(params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0)))
        probe_timeout = max(0.1, float(getattr(params, "LIVE_ARMABILITY_PROBE_TIMEOUT_SEC", 6.0)))
        http_buffer_sec = max(0.5, float(getattr(params, "LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC", 2.0)))
        return connect_timeout + probe_timeout + http_buffer_sec


TAKEOFF = 10
LAND = 101
HOLD = 102
RETURN_RTL = 104
TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout", "superseded"}
COMMAND_HEARTBEAT_GRACE_SECONDS = max(
    getattr(Params, "TELEMETRY_POLLING_TIMEOUT", 10),
    getattr(Params, "heartbeat_interval", 10) * 2,
)


def log(message: str) -> None:
    print(message, flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def decode_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw_body = exc.read()
    except Exception:
        raw_body = b""

    if not raw_body:
        return str(getattr(exc, "reason", "") or f"HTTP {getattr(exc, 'code', 'error')}")

    body_text = raw_body.decode("utf-8", errors="replace").strip()
    if not body_text:
        return str(getattr(exc, "reason", "") or f"HTTP {getattr(exc, 'code', 'error')}")

    try:
        payload = json.loads(body_text)
    except Exception:
        return body_text

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("error") or payload.get("message")
        if detail not in (None, ""):
            return str(detail)
    return body_text


def format_http_error(exc: urllib.error.HTTPError) -> str:
    return f"HTTP {exc.code}: {decode_http_error_detail(exc)}"


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get_json(self, path: str) -> dict:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=20) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

    def post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

    def get_telemetry(self) -> dict[str, dict]:
        payload = self.get_json(GCS_FLEET_TELEMETRY_ROUTE)
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def submit_command(self, mission_type: int, target_ids: list[int], operator_label: str, *, trigger_time: int = 0) -> dict:
        payload = {
            "mission_type": int(mission_type),
            "target_drone_ids": [str(target_id) for target_id in target_ids],
            "trigger_time": int(trigger_time),
            "operator_label": operator_label,
        }
        response = self.post_json(GCS_COMMANDS_ROUTE, payload)
        log(f"COMMAND {operator_label}: id={response['command_id']} targets={target_ids}")
        return response

    def probe_live_armability(self, drone_ip: str, *, require_global_position: bool = True) -> dict:
        timeout = calculate_live_armability_request_timeout(params=Params)
        query = urllib.parse.urlencode(
            {"require_global_position": str(bool(require_global_position)).lower()}
        )
        path = f"http://{drone_ip}:7070{DRONE_LIVE_ARMABILITY_ROUTE}?{query}"
        try:
            with urllib.request.urlopen(path, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc


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


def command_summary(status: dict) -> dict:
    acks = status.get("acks") or {}
    executions = status.get("executions") or {}
    progress = status.get("progress") or {}
    return {
        "status": status.get("status"),
        "phase": status.get("phase"),
        "outcome": status.get("outcome"),
        "progress": {
            "stage": progress.get("stage"),
            "label": progress.get("label"),
            "active": progress.get("active"),
            "remaining": progress.get("remaining"),
            "message": progress.get("message"),
        },
        "acks": {
            "expected": acks.get("expected"),
            "accepted": acks.get("accepted"),
            "offline": acks.get("offline"),
            "rejected": acks.get("rejected"),
            "errors": acks.get("errors"),
        },
        "executions": {
            "expected": executions.get("expected"),
            "received": executions.get("received"),
            "started": executions.get("started"),
            "active": executions.get("active"),
            "succeeded": executions.get("succeeded"),
            "failed": executions.get("failed"),
        },
    }


def require_full_acceptance(status: dict, expected_count: int, label: str) -> None:
    accepted = int((status.get("acks") or {}).get("accepted", 0) or 0)
    require(
        accepted == expected_count,
        f"{label} acceptance mismatch. Expected {expected_count}, got {accepted}: "
        f"{json.dumps(command_summary(status), indent=2)}",
    )


def require_full_execution(status: dict, expected_count: int, label: str) -> None:
    succeeded = int((status.get("executions") or {}).get("succeeded", 0) or 0)
    require(
        succeeded == expected_count,
        f"{label} execution mismatch. Expected {expected_count}, got {succeeded}: "
        f"{json.dumps(command_summary(status), indent=2)}",
    )


def _telemetry_has_ids(telemetry: dict[str, dict], ids: list[int]) -> bool:
    return all(str(idx) in telemetry for idx in ids)


def _is_idle_baseline_row(row: dict) -> bool:
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


def _is_idle_reset_row(row: dict) -> bool:
    mission = int(row.get("mission", 0) or 0)
    state = int(row.get("state", 0) or 0)
    return not bool(row.get("is_armed")) and mission == 0 and state == 0


def _is_airborne_row(row: dict, baseline_altitude: float, *, min_gain: float) -> bool:
    try:
        altitude = float(row.get("position_alt", 0.0))
    except (TypeError, ValueError):
        return False
    return bool(row.get("is_armed")) and altitude >= (baseline_altitude + min_gain)


def choose_override_targets(ids: list[int]) -> tuple[list[int], list[int]]:
    selected = normalize_drone_ids(ids)
    if len(selected) == 1:
        return selected, []
    return [selected[0]], selected[1:]


def wait_api_ready(client: ApiClient, timeout: int = 60):
    def _ready():
        try:
            return client.get_json(GCS_SYSTEM_HEALTH_ROUTE)
        except Exception:
            return False

    return wait_for(_ready, label="GCS API health endpoint", timeout=timeout, interval=2.0)


def wait_for_command(
    client: ApiClient,
    command_id: str,
    *,
    desired_phase: str | None = None,
    terminal: bool = False,
    timeout: int = 90,
) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = client.get_json(GCS_COMMAND_STATUS_ROUTE_TEMPLATE.format(command_id=command_id))
        last = status
        state = status.get("status")
        phase = status.get("phase")
        if terminal and state in TERMINAL_STATUSES:
            log(f"COMMAND {command_id} terminal: {command_summary(status)}")
            return status
        if desired_phase and phase == desired_phase:
            log(f"COMMAND {command_id} reached phase={phase}: {command_summary(status)}")
            return status
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for command {command_id}. Last status: {command_summary(last or {})}")


def wait_fleet_ready(client: ApiClient, ids: list[int], timeout: int = 120) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_idle_baseline_row(row) for row in rows.values()):
            return False
        return rows

    return wait_for(_ready, label=f"drones {ids} ready, idle, and launchable", timeout=timeout, interval=2.0)


def wait_idle_subset(client: ApiClient, ids: list[int], timeout: int = 240) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_idle_reset_row(row) for row in rows.values()):
            return False
        return rows

    return wait_for(_ready, label=f"drones {ids} disarmed and idle", timeout=timeout, interval=2.0)


def wait_altitude_gain(client: ApiClient, ids: list[int], baseline_altitudes: dict[str, float], min_gain: float, timeout: int = 120) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_airborne_row(rows[str(idx)], baseline_altitudes[str(idx)], min_gain=min_gain) for idx in ids):
            return False
        return rows

    return wait_for(_ready, label=f"drones {ids} airborne with +{min_gain}m gain", timeout=timeout, interval=2.0)


def wait_hold_ready(client: ApiClient, ids: list[int], baseline_altitudes: dict[str, float], min_gain: float, timeout: int = 90) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        for idx in ids:
            row = rows[str(idx)]
            if not _is_airborne_row(row, baseline_altitudes[str(idx)], min_gain=min_gain):
                return False
            if int(row.get("mission", 0) or 0) != HOLD:
                return False
        return rows

    return wait_for(_ready, label=f"drones {ids} holding airborne", timeout=timeout, interval=1.0)


def wait_remaining_airborne(
    client: ApiClient,
    ids: list[int],
    baseline_altitudes: dict[str, float],
    *,
    min_gain: float,
    timeout: int = 45,
) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_airborne_row(rows[str(idx)], baseline_altitudes[str(idx)], min_gain=min_gain) for idx in ids):
            return False
        return rows

    return wait_for(_ready, label=f"non-target drones {ids} remain airborne", timeout=timeout, interval=1.0)


def wait_for_live_launch_readiness(client: ApiClient, ids: list[int], timeout: int = 90) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False

        probe_results: dict[str, dict] = {}
        for idx in ids:
            row = telemetry[str(idx)]
            drone_ip = str(row.get("ip") or "").strip()
            if not drone_ip:
                return False
            probe = client.probe_live_armability(drone_ip, require_global_position=True)
            if not probe.get("ready"):
                return False
            probe_results[str(idx)] = probe
        return probe_results

    return wait_for(_ready, label=f"live launch readiness for drones {ids}", timeout=timeout, interval=2.0)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate standalone action/control commands against a live GCS/SITL stack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="GCS API base URL")
    parser.add_argument("--drones", default=None, help="Comma-separated drone hardware IDs to validate")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=None, help="Space-separated drone hardware IDs to validate")
    parser.add_argument("--takeoff-min-gain", type=float, default=4.0, help="Minimum altitude gain required after TAKEOFF")
    parser.add_argument("--post-rtl-airborne-gain", type=float, default=2.0, help="Minimum residual altitude gain required when checking that non-target drones stayed airborne after RTL override")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional path to write the final validation summary JSON")
    return parser.parse_args()


def resolve_selected_ids(args: argparse.Namespace) -> list[int]:
    if args.drone_ids:
        return normalize_drone_ids(args.drone_ids)
    if args.drones:
        return parse_csv_drone_ids(args.drones)
    return normalize_drone_ids([1, 2, 3])


def main() -> int:
    args = parse_args()
    ids = resolve_selected_ids(args)
    client = ApiClient(args.base_url)
    results: dict[str, Any] = {
        "base_url": args.base_url,
        "drone_ids": ids,
        "takeoff_min_gain": float(args.takeoff_min_gain),
        "post_rtl_airborne_gain": float(args.post_rtl_airborne_gain),
    }

    try:
        results["health"] = wait_api_ready(client, timeout=60)
        baseline = wait_fleet_ready(client, ids, timeout=120)
        baseline_altitudes = {str(idx): float(baseline[str(idx)]["position_alt"]) for idx in ids}
        results["baseline_telemetry"] = baseline
        results["baseline_altitudes"] = baseline_altitudes

        results["live_launch_readiness"] = wait_for_live_launch_readiness(client, ids, timeout=90)

        takeoff = client.submit_command(TAKEOFF, ids, "SITL Actions Validation Takeoff")
        takeoff_status = wait_for_command(client, takeoff["command_id"], terminal=True, timeout=150)
        require(takeoff_status["status"] == "completed", f"Takeoff failed: {command_summary(takeoff_status)}")
        require_full_acceptance(takeoff_status, len(ids), "Takeoff")
        require_full_execution(takeoff_status, len(ids), "Takeoff")
        results["takeoff"] = command_summary(takeoff_status)

        airborne = wait_altitude_gain(client, ids, baseline_altitudes, args.takeoff_min_gain, timeout=120)
        results["post_takeoff_telemetry"] = airborne

        hold = client.submit_command(HOLD, ids, "SITL Actions Validation Hold")
        hold_status = wait_for_command(client, hold["command_id"], terminal=True, timeout=120)
        require(hold_status["status"] == "completed", f"Hold failed: {command_summary(hold_status)}")
        require_full_acceptance(hold_status, len(ids), "Hold")
        require_full_execution(hold_status, len(ids), "Hold")
        results["hold"] = command_summary(hold_status)

        hold_rows = wait_hold_ready(client, ids, baseline_altitudes, args.post_rtl_airborne_gain, timeout=60)
        results["post_hold_telemetry"] = hold_rows

        rtl_targets, land_targets = choose_override_targets(ids)
        results["override_plan"] = {
            "rtl_targets": rtl_targets,
            "land_targets": land_targets,
        }

        rtl = client.submit_command(RETURN_RTL, rtl_targets, "SITL Actions Validation RTL Override")
        rtl_relative_altitude = max(
            max(0.0, float(client.get_telemetry()[str(idx)]["position_alt"]) - baseline_altitudes[str(idx)])
            for idx in rtl_targets
        )
        rtl_timeout = max(180, calculate_rtl_completion_timeout(rtl_relative_altitude, params=Params) + 60)
        rtl_status = wait_for_command(client, rtl["command_id"], terminal=True, timeout=rtl_timeout)
        require(rtl_status["status"] == "completed", f"RTL failed: {command_summary(rtl_status)}")
        require_full_acceptance(rtl_status, len(rtl_targets), "RTL")
        require_full_execution(rtl_status, len(rtl_targets), "RTL")
        results["rtl"] = command_summary(rtl_status)
        results["rtl_timeout_sec"] = rtl_timeout

        results["post_rtl_targets_idle"] = wait_idle_subset(client, rtl_targets, timeout=rtl_timeout)

        if land_targets:
            remaining_airborne = wait_remaining_airborne(
                client,
                land_targets,
                baseline_altitudes,
                min_gain=args.post_rtl_airborne_gain,
                timeout=45,
            )
            results["post_rtl_non_target_telemetry"] = remaining_airborne

            land = client.submit_command(LAND, land_targets, "SITL Actions Validation Land Remaining")
            land_relative_altitude = max(
                max(0.0, float(client.get_telemetry()[str(idx)]["position_alt"]) - baseline_altitudes[str(idx)])
                for idx in land_targets
            )
            land_timeout = max(180, calculate_land_disarm_timeout(land_relative_altitude, params=Params) + 60)
            land_status = wait_for_command(client, land["command_id"], terminal=True, timeout=land_timeout)
            require(land_status["status"] == "completed", f"Land failed: {command_summary(land_status)}")
            require_full_acceptance(land_status, len(land_targets), "Land")
            require_full_execution(land_status, len(land_targets), "Land")
            results["land"] = command_summary(land_status)
            results["land_timeout_sec"] = land_timeout

        results["final_telemetry"] = wait_idle_subset(client, ids, timeout=240)
        results["result"] = "PASS"
        write_json_report(args.json_output, results)
        print(json.dumps(results, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        results["result"] = "FAIL"
        results["error"] = str(exc)
        write_json_report(args.json_output, results)
        print(json.dumps(results, indent=2, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
