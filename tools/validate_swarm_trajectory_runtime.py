#!/usr/bin/env python3
"""
End-to-end Swarm Trajectory runtime validation for SITL fleets.

This validator exercises the operator-facing Swarm Trajectory workflow:

1. Wait for the GCS API and a clean idle baseline
2. Reprocess uploaded leader trajectories so session truth matches the current swarm config
3. Dispatch Mission Type 4 (Swarm Trajectory) to the requested drones
4. Confirm all drones enter mission execution and climb away from their baseline altitude
5. Sample follower geometry in flight against the configured swarm offsets
6. Wait for mission completion and return-to-idle

If anything fails after launch, the validator attempts a fleet LAND cleanup before exiting.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

USING_FALLBACK_TIMEOUT_PARAMS = False

try:
    from src.flight_timeout_utils import (
        calculate_land_disarm_timeout,
        calculate_swarm_rtl_completion_timeout,
    )
    from src.params import Params
except Exception:  # pragma: no cover - validator fallback only
    USING_FALLBACK_TIMEOUT_PARAMS = True

    class _FallbackParams:
        SWARM_TRAJECTORY_END_BEHAVIOR = "return_home"
        SWARM_TRAJECTORY_RTL_COMPLETION_TIMEOUT = 600
        SWARM_TRAJECTORY_RTL_COMPLETION_BUFFER_SEC = 180
        SWARM_TRAJECTORY_RTL_COMPLETION_MAX_TIMEOUT = 1800
        LANDING_TIMEOUT = 10
        LAND_ACTION_MIN_DISARM_WAIT_SEC = 45
        LAND_ACTION_ASSUMED_DESCENT_RATE_MPS = 2.5
        LAND_ACTION_DISARM_BUFFER_SEC = 30
        LAND_ACTION_MAX_DISARM_WAIT_SEC = 900
        CONTROLLED_LANDING_TIMEOUT = 7

    Params = _FallbackParams()

    def calculate_land_disarm_timeout(relative_altitude_m, *, params=Params):
        minimum_wait = int(getattr(params, "LAND_ACTION_MIN_DISARM_WAIT_SEC", 45))
        if relative_altitude_m is None:
            return minimum_wait
        altitude_m = max(0.0, float(relative_altitude_m))
        descent_rate = max(0.1, float(getattr(params, "LAND_ACTION_ASSUMED_DESCENT_RATE_MPS", 2.5)))
        buffer_sec = max(0, int(getattr(params, "LAND_ACTION_DISARM_BUFFER_SEC", 30)))
        maximum_wait = max(minimum_wait, int(getattr(params, "LAND_ACTION_MAX_DISARM_WAIT_SEC", 900)))
        return max(minimum_wait, min(maximum_wait, int(math.ceil(minimum_wait + (altitude_m / descent_rate) + buffer_sec))))

    def calculate_swarm_rtl_completion_timeout(relative_altitude_m, *, params=Params):
        base_timeout = int(getattr(params, "SWARM_TRAJECTORY_RTL_COMPLETION_TIMEOUT", 600))
        rtl_buffer_sec = max(0, int(getattr(params, "SWARM_TRAJECTORY_RTL_COMPLETION_BUFFER_SEC", 180)))
        maximum_timeout = max(
            base_timeout,
            int(getattr(params, "SWARM_TRAJECTORY_RTL_COMPLETION_MAX_TIMEOUT", 1800)),
        )
        landing_timeout = calculate_land_disarm_timeout(relative_altitude_m, params=params)
        estimated_wait = landing_timeout + rtl_buffer_sec
        return max(base_timeout, min(maximum_timeout, estimated_wait))


SWARM_TRAJECTORY = 4
LAND = 101
TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout", "superseded"}


def log(message: str) -> None:
    print(message, flush=True)


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=20) as response:
            return json.load(response)

    def post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    def get_telemetry(self) -> dict[str, dict]:
        payload = self.get_json("/api/telemetry")
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def get_swarm_assignments(self) -> list[dict]:
        payload = self.get_json("/get-swarm-data")
        if isinstance(payload, dict) and "assignments" in payload:
            payload = payload["assignments"]
        return payload

    def submit_command(
        self,
        mission_type: int,
        target_ids: Iterable[int],
        operator_label: str,
        *,
        trigger_time: int = 0,
        **extra: Any,
    ) -> dict:
        payload = {
            "missionType": str(mission_type),
            "target_drones": [str(target_id) for target_id in target_ids],
            "triggerTime": str(trigger_time),
            "operatorLabel": operator_label,
            **extra,
        }
        response = self.post_json("/submit_command", payload)
        log(f"COMMAND {operator_label}: {response['command_id']} submitted={response.get('submitted_count')}")
        return response


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def wait_for(predicate, *, label: str, timeout: int, interval: float = 1.0):
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
    return {
        "status": status.get("status"),
        "phase": status.get("phase"),
        "outcome": status.get("outcome"),
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


def wait_api_ready(client: ApiClient, timeout: int = 60) -> dict:
    def _ready():
        try:
            return client.get_json("/health")
        except urllib.error.URLError:
            return False

    return wait_for(_ready, label="GCS API health", timeout=timeout, interval=2.0)


def idle_row(row: dict) -> bool:
    mission = int(row.get("mission", 0) or 0)
    state = int(row.get("state", 0) or 0)
    return (
        row.get("readiness_status") == "ready"
        and not bool(row.get("is_armed"))
        and mission == 0
        and state == 0
    )


def wait_for_idle(client: ApiClient, ids: list[int], timeout: int = 180) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in ids):
            return False
        if all(idle_row(telemetry[str(idx)]) for idx in ids):
            return telemetry
        return False

    return wait_for(_ready, label=f"idle baseline for drones {ids}", timeout=timeout, interval=2.0)


def wait_for_command(
    client: ApiClient,
    command_id: str,
    *,
    desired_phase: str | None = None,
    terminal: bool = False,
    timeout: int = 120,
) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = client.get_json(f"/command/{command_id}")
        last = status
        phase = status.get("phase")
        state = status.get("status")
        if desired_phase and phase == desired_phase:
            log(f"COMMAND {command_id} phase={phase}: {command_summary(status)}")
            return status
        if terminal and state in TERMINAL_STATUSES:
            log(f"COMMAND {command_id} terminal: {command_summary(status)}")
            return status
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for command {command_id}. Last status: {command_summary(last or {})}")


def wait_for_executing(client: ApiClient, ids: list[int], timeout: int = 120) -> dict[str, dict]:
    def _executing():
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in ids):
            return False
        for idx in ids:
            row = telemetry[str(idx)]
            mission = int(row.get("mission", 0) or 0)
            state = int(row.get("state", 0) or 0)
            if mission != SWARM_TRAJECTORY or state != 2 or not bool(row.get("is_armed")):
                return False
        return telemetry

    return wait_for(_executing, label=f"mission executing for drones {ids}", timeout=timeout, interval=1.0)


def wait_for_altitude_gain(client: ApiClient, baselines: dict[int, float], min_gain: float, timeout: int = 90) -> dict[str, dict]:
    def _airborne():
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in baselines):
            return False
        for idx, baseline in baselines.items():
            current = telemetry[str(idx)].get("position_alt")
            if current is None:
                return False
            try:
                gain = float(current) - float(baseline)
            except (TypeError, ValueError):
                return False
            if gain < min_gain:
                return False
        return telemetry

    return wait_for(
        _airborne,
        label=f"all drones reaching +{min_gain:.1f}m relative altitude",
        timeout=timeout,
        interval=1.0,
    )


def latlon_to_ne(lat_deg: float, lon_deg: float, ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float]:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(ref_lat_deg))
    north = (lat_deg - ref_lat_deg) * lat_scale
    east = (lon_deg - ref_lon_deg) * lon_scale
    return north, east


def body_to_ne(offset_forward: float, offset_right: float, yaw_deg: float) -> tuple[float, float]:
    yaw = math.radians(yaw_deg)
    north = offset_forward * math.cos(yaw) - offset_right * math.sin(yaw)
    east = offset_forward * math.sin(yaw) + offset_right * math.cos(yaw)
    return north, east


def ne_to_latlon(north_m: float, east_m: float, ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float]:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * max(0.01, math.cos(math.radians(ref_lat_deg)))
    latitude = ref_lat_deg + (north_m / lat_scale)
    longitude = ref_lon_deg + (east_m / lon_scale)
    return latitude, longitude


def follower_expectations(assignments: list[dict], *, active_ids: Iterable[int] | None = None) -> dict[int, dict]:
    active_set = {int(drone_id) for drone_id in active_ids} if active_ids is not None else None
    expectations: dict[int, dict] = {}
    for assignment in assignments:
        hw_id = int(assignment["hw_id"])
        follow = int(assignment.get("follow", 0) or 0)
        if follow == 0:
            continue
        if active_set is not None and hw_id not in active_set:
            continue
        expectations[hw_id] = {
            "leader_id": follow,
            "offset_x": float(assignment.get("offset_x", 0.0) or 0.0),
            "offset_y": float(assignment.get("offset_y", 0.0) or 0.0),
            "offset_z": float(assignment.get("offset_z", 0.0) or 0.0),
            "frame": str(assignment.get("frame", "ned") or "ned").lower(),
        }
    return expectations


def follower_scope_issues(expectations: dict[int, dict], *, active_ids: Iterable[int]) -> list[dict]:
    active_set = {int(drone_id) for drone_id in active_ids}
    issues: list[dict] = []
    for follower_id, expectation in expectations.items():
        leader_id = int(expectation["leader_id"])
        if leader_id not in active_set:
            issues.append(
                {
                    "follower_id": follower_id,
                    "leader_id": leader_id,
                    "issue": "leader_not_in_active_mission_set",
                }
            )
    return issues


def selected_top_leaders(assignments: list[dict], *, active_ids: Iterable[int]) -> list[int]:
    active_set = {int(drone_id) for drone_id in active_ids}
    leaders: list[int] = []
    for assignment in assignments:
        hw_id = int(assignment["hw_id"])
        if hw_id not in active_set:
            continue
        follow = int(assignment.get("follow", 0) or 0)
        if follow == 0:
            leaders.append(hw_id)
    return sorted(leaders)


def build_short_validation_profile_rows(
    leader_id: int,
    telemetry_row: dict[str, Any],
    *,
    relative_altitude_m: float,
    entry_delay_s: float,
    leg_duration_s: float,
) -> list[dict[str, Any]]:
    ref_lat = float(telemetry_row["position_lat"])
    ref_lon = float(telemetry_row["position_long"])
    base_alt = float(telemetry_row["position_alt"])
    mission_alt = round(base_alt + relative_altitude_m, 2)
    offsets = [
        (18.0, 0.0),
        (36.0, 18.0),
        (18.0, 36.0),
    ]

    rows: list[dict[str, Any]] = []
    previous_offset: tuple[float, float] | None = None
    previous_time: float | None = None

    for index, (north_m, east_m) in enumerate(offsets, start=1):
        latitude, longitude = ne_to_latlon(north_m, east_m, ref_lat, ref_lon)
        time_from_start = round(entry_delay_s + ((index - 1) * leg_duration_s), 1)

        if previous_offset is None or previous_time is None:
            estimated_speed = 0.0
            heading_mode = "manual"
            heading_deg = 0.0
        else:
            delta_north = north_m - previous_offset[0]
            delta_east = east_m - previous_offset[1]
            leg_distance = math.hypot(delta_north, delta_east)
            leg_seconds = max(0.1, time_from_start - previous_time)
            estimated_speed = round(leg_distance / leg_seconds, 1)
            heading_mode = "auto"
            heading_deg = 0.0

        rows.append(
            {
                "Name": f"Leader {leader_id} WP {index}",
                "Latitude": round(latitude, 8),
                "Longitude": round(longitude, 8),
                "Altitude_MSL_m": mission_alt,
                "TimeFromStart_s": time_from_start,
                "EstimatedSpeed_ms": estimated_speed,
                "Heading_deg": heading_deg,
                "HeadingMode": heading_mode,
            }
        )

        previous_offset = (north_m, east_m)
        previous_time = time_from_start

    return rows


def write_short_validation_profiles(
    repo_root: Path,
    idle_telemetry: dict[str, dict[str, Any]],
    leader_ids: Iterable[int],
    *,
    relative_altitude_m: float,
    entry_delay_s: float,
    leg_duration_s: float,
) -> list[dict[str, Any]]:
    raw_dir = repo_root / "shapes_sitl" / "swarm_trajectory" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[dict[str, Any]] = []

    fieldnames = [
        "Name",
        "Latitude",
        "Longitude",
        "Altitude_MSL_m",
        "TimeFromStart_s",
        "EstimatedSpeed_ms",
        "Heading_deg",
        "HeadingMode",
    ]

    for leader_id in leader_ids:
        telemetry_row = idle_telemetry[str(leader_id)]
        rows = build_short_validation_profile_rows(
            leader_id,
            telemetry_row,
            relative_altitude_m=relative_altitude_m,
            entry_delay_s=entry_delay_s,
            leg_duration_s=leg_duration_s,
        )
        csv_path = raw_dir / f"Drone {leader_id}.csv"
        with csv_path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        prepared.append(
            {
                "leader_id": leader_id,
                "path": str(csv_path),
                "waypoint_count": len(rows),
                "duration_sec": rows[-1]["TimeFromStart_s"] if rows else 0.0,
                "mission_altitude_msl": rows[0]["Altitude_MSL_m"] if rows else None,
            }
        )

    return prepared


def evaluate_formation_snapshot(
    telemetry: dict[str, dict],
    expectations: dict[int, dict],
    *,
    horiz_tolerance: float,
    vert_tolerance: float,
) -> tuple[bool, list[dict]]:
    diagnostics: list[dict] = []
    overall_ok = True

    for follower_id, expectation in expectations.items():
        leader_id = expectation["leader_id"]
        follower = telemetry.get(str(follower_id))
        leader = telemetry.get(str(leader_id))
        if not follower or not leader:
            overall_ok = False
            diagnostics.append({
                "follower_id": follower_id,
                "leader_id": leader_id,
                "status": "missing_telemetry",
            })
            continue

        actual_n, actual_e = latlon_to_ne(
            float(follower["position_lat"]),
            float(follower["position_long"]),
            float(leader["position_lat"]),
            float(leader["position_long"]),
        )
        actual_alt_delta = float(follower["position_alt"]) - float(leader["position_alt"])

        if expectation["frame"] == "body":
            expected_n, expected_e = body_to_ne(
                expectation["offset_x"],
                expectation["offset_y"],
                float(leader.get("yaw", 0.0) or 0.0),
            )
        else:
            expected_n, expected_e = expectation["offset_x"], expectation["offset_y"]

        expected_alt_delta = -expectation["offset_z"]
        horizontal_error = math.hypot(actual_n - expected_n, actual_e - expected_e)
        vertical_error = abs(actual_alt_delta - expected_alt_delta)
        ok = horizontal_error <= horiz_tolerance and vertical_error <= vert_tolerance
        overall_ok = overall_ok and ok

        diagnostics.append({
            "follower_id": follower_id,
            "leader_id": leader_id,
            "frame": expectation["frame"],
            "expected_north_m": round(expected_n, 2),
            "expected_east_m": round(expected_e, 2),
            "actual_north_m": round(actual_n, 2),
            "actual_east_m": round(actual_e, 2),
            "expected_alt_delta_m": round(expected_alt_delta, 2),
            "actual_alt_delta_m": round(actual_alt_delta, 2),
            "horizontal_error_m": round(horizontal_error, 2),
            "vertical_error_m": round(vertical_error, 2),
            "ok": ok,
        })

    return overall_ok, diagnostics


def wait_for_formation(
    client: ApiClient,
    expectations: dict[int, dict],
    *,
    horiz_tolerance: float,
    vert_tolerance: float,
    timeout: int = 120,
) -> dict:
    last_diagnostics: list[dict] | None = None

    def _formed():
        nonlocal last_diagnostics
        telemetry = client.get_telemetry()
        ok, diagnostics = evaluate_formation_snapshot(
            telemetry,
            expectations,
            horiz_tolerance=horiz_tolerance,
            vert_tolerance=vert_tolerance,
        )
        last_diagnostics = diagnostics
        if ok:
            return {
                "telemetry": telemetry,
                "diagnostics": diagnostics,
            }
        return False

    try:
        return wait_for(_formed, label="follower geometry within tolerance", timeout=timeout, interval=2.0)
    except Exception as exc:
        raise RuntimeError(
            f"Formation did not converge within tolerance. Last diagnostics: {json.dumps(last_diagnostics or [], indent=2)}"
        ) from exc


def max_processed_duration_seconds(repo_root: Path, *, drone_ids: Iterable[int] | None = None) -> float:
    processed_dir = repo_root / "shapes_sitl" / "swarm_trajectory" / "processed"
    allowed_names = None
    if drone_ids is not None:
        allowed_names = {f"Drone {int(drone_id)}.csv" for drone_id in drone_ids}
    durations: list[float] = []
    for csv_path in sorted(processed_dir.glob("Drone *.csv")):
        if allowed_names is not None and csv_path.name not in allowed_names:
            continue
        last_t = None
        with csv_path.open() as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                if "t" in row and row["t"] not in (None, ""):
                    last_t = float(row["t"])
        if last_t is not None:
            durations.append(last_t)
    return max(durations) if durations else 0.0


def max_processed_relative_altitude_m(
    repo_root: Path,
    baselines: dict[int, float],
    *,
    drone_ids: Iterable[int] | None = None,
) -> float | None:
    """
    Estimate the highest mission-relative altitude from processed leader/follower CSVs.

    Validator completion should budget from the actual peak path altitude, not the
    much earlier formation snapshot altitude. Otherwise long, high-area trajectories
    can still be descending correctly when the validator times out and triggers
    unnecessary cleanup.
    """
    processed_dir = repo_root / "shapes_sitl" / "swarm_trajectory" / "processed"
    selected_ids = [int(drone_id) for drone_id in (drone_ids or baselines.keys())]
    max_relative_altitudes: list[float] = []

    for drone_id in selected_ids:
        baseline = baselines.get(drone_id)
        if baseline is None:
            continue
        csv_path = processed_dir / f"Drone {drone_id}.csv"
        if not csv_path.exists():
            continue
        with csv_path.open() as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                alt_value = row.get("alt")
                if alt_value in (None, ""):
                    continue
                try:
                    relative_altitude = max(0.0, float(alt_value) - float(baseline))
                except (TypeError, ValueError):
                    continue
                max_relative_altitudes.append(relative_altitude)

    return max(max_relative_altitudes) if max_relative_altitudes else None


def estimate_command_completion_timeout(
    duration_sec: float,
    end_behavior: str | None = None,
    *,
    relative_altitude_m: float | None = None,
) -> int:
    """
    Estimate a realistic validator timeout for Swarm Trajectory completion.

    The validator starts its terminal wait after the formation gate, not at the
    original dispatch timestamp, so it must budget for the full remaining path
    plus any end-behavior completion window.
    """
    duration_sec = max(0.0, float(duration_sec or 0.0))
    behavior = str(end_behavior or getattr(Params, "SWARM_TRAJECTORY_END_BEHAVIOR", "return_home")).lower()
    base_buffer_sec = 180

    if behavior == "return_home":
        rtl_timeout = calculate_swarm_rtl_completion_timeout(relative_altitude_m)
        return max(300, int(math.ceil(duration_sec + rtl_timeout + base_buffer_sec)))

    if behavior == "land_current":
        landing_timeout = max(
            calculate_land_disarm_timeout(relative_altitude_m),
            int(getattr(Params, "CONTROLLED_LANDING_TIMEOUT", 7)),
        )
        return max(300, int(math.ceil(duration_sec + landing_timeout + base_buffer_sec)))

    return max(300, int(math.ceil(duration_sec + base_buffer_sec)))


def cleanup_land(client: ApiClient, ids: list[int], label: str, baselines: dict[int, float] | None = None) -> None:
    telemetry = client.get_telemetry()
    armed_ids = [idx for idx in ids if telemetry.get(str(idx), {}).get("is_armed")]
    if not armed_ids:
        return
    relative_altitudes = []
    if baselines:
        for idx in armed_ids:
            current_altitude = telemetry.get(str(idx), {}).get("position_alt")
            baseline_altitude = baselines.get(idx)
            try:
                relative_altitudes.append(max(0.0, float(current_altitude) - float(baseline_altitude)))
            except (TypeError, ValueError):
                continue
    max_relative_altitude = max(relative_altitudes) if relative_altitudes else None
    cleanup_timeout = max(180, calculate_land_disarm_timeout(max_relative_altitude) + 60)
    log(f"CLEANUP: landing armed drones {armed_ids}")
    response = client.submit_command(LAND, armed_ids, label, trigger_time=0)
    status = wait_for_command(client, response["command_id"], terminal=True, timeout=cleanup_timeout)
    log(f"CLEANUP RESULT: {command_summary(status)}")
    wait_for_idle(client, ids, timeout=cleanup_timeout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Swarm Trajectory runtime behavior against a live GCS API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Base URL of the GCS API")
    parser.add_argument("--repo-root", type=Path, default=Path("/root/mavsdk_drone_show"), help="Repository root on the runtime host")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=[1, 2, 3, 4, 5], help="Drone IDs to include in validation")
    parser.add_argument("--horiz-tolerance", type=float, default=18.0, help="Allowed horizontal formation error in meters")
    parser.add_argument("--vert-tolerance", type=float, default=8.0, help="Allowed vertical formation error in meters")
    parser.add_argument("--min-altitude-gain", type=float, default=2.0, help="Required altitude gain before geometry sampling")
    parser.add_argument("--formation-timeout", type=int, default=120, help="Seconds to wait for formation convergence")
    parser.add_argument(
        "--prepare-short-profile",
        action="store_true",
        help="Overwrite the selected top-leader raw CSVs with a short deterministic validation route before processing",
    )
    parser.add_argument(
        "--short-profile-altitude-gain",
        type=float,
        default=12.0,
        help="Relative mission altitude, in meters above the idle baseline, for generated short validation profiles",
    )
    parser.add_argument(
        "--short-profile-entry-delay",
        type=float,
        default=8.0,
        help="Route-entry time in seconds after mission start for the first generated validation waypoint",
    )
    parser.add_argument(
        "--short-profile-leg-duration",
        type=float,
        default=10.0,
        help="Per-leg duration in seconds for generated short validation waypoints",
    )
    args = parser.parse_args()

    client = ApiClient(args.base_url)
    results: dict[str, Any] = {}
    command_id: str | None = None

    try:
        results["health"] = wait_api_ready(client)
        baseline = wait_for_idle(client, args.drone_ids, timeout=180)
        results["baseline_ids"] = sorted(int(key) for key in baseline.keys())
        baselines = {idx: float(baseline[str(idx)]["position_alt"]) for idx in args.drone_ids}

        assignments = client.get_swarm_assignments()
        if args.prepare_short_profile:
            leader_ids = selected_top_leaders(assignments, active_ids=args.drone_ids)
            require(leader_ids, f"No top leaders found inside selected mission set {args.drone_ids}")
            prepared = write_short_validation_profiles(
                args.repo_root,
                baseline,
                leader_ids,
                relative_altitude_m=args.short_profile_altitude_gain,
                entry_delay_s=args.short_profile_entry_delay,
                leg_duration_s=args.short_profile_leg_duration,
            )
            log(f"Prepared short validation profiles for leaders {leader_ids}")
            results["prepared_short_profiles"] = prepared

        status_before = client.get_json("/api/swarm/trajectory/status")
        require(status_before.get("success") is True, f"Status unavailable: {status_before}")
        results["status_before"] = status_before["status"]

        process_result = client.post_json(
            "/api/swarm/trajectory/process",
            {"force_clear": False, "auto_reload": True},
        )
        require(process_result.get("success") is True, f"Processing failed: {process_result}")
        results["process_result"] = process_result

        status_after = client.get_json("/api/swarm/trajectory/status")
        require(status_after.get("success") is True, f"Status unavailable after processing: {status_after}")
        require(status_after["status"]["cluster_summary"]["all_clusters_ready"] is True, f"Clusters not ready: {status_after}")
        results["status_after"] = status_after["status"]

        expectations = follower_expectations(assignments, active_ids=args.drone_ids)
        scope_issues = follower_scope_issues(expectations, active_ids=args.drone_ids)
        require(not scope_issues, f"Selected mission set has followers without their leaders: {scope_issues}")
        results["assignments"] = expectations
        results["assignment_scope_issues"] = scope_issues

        response = client.submit_command(
            SWARM_TRAJECTORY,
            args.drone_ids,
            "Swarm Trajectory Validation",
            trigger_time=0,
        )
        command_id = response["command_id"]
        results["dispatch"] = response

        wait_for_command(client, command_id, desired_phase="in_progress", timeout=120)
        wait_for_executing(client, args.drone_ids, timeout=180)
        wait_for_altitude_gain(client, baselines, min_gain=args.min_altitude_gain, timeout=120)

        formation_relative_altitude = max(
            max(0.0, float(client.get_telemetry()[str(idx)]["position_alt"]) - float(baselines[idx]))
            for idx in args.drone_ids
        )
        if expectations:
            formation = wait_for_formation(
                client,
                expectations,
                horiz_tolerance=args.horiz_tolerance,
                vert_tolerance=args.vert_tolerance,
                timeout=args.formation_timeout,
            )
            results["formation"] = formation["diagnostics"]
            formation_relative_altitude = max(
                max(0.0, float(formation["telemetry"][str(idx)]["position_alt"]) - float(baselines[idx]))
                for idx in args.drone_ids
            )
        else:
            log("No follower assignments in the selected mission set; skipping formation convergence gate.")
            results["formation"] = []
            results["formation_skipped"] = True
        results["formation_max_relative_altitude_m"] = formation_relative_altitude

        duration = max_processed_duration_seconds(args.repo_root, drone_ids=args.drone_ids)
        processed_relative_altitude = max_processed_relative_altitude_m(
            args.repo_root,
            baselines,
            drone_ids=args.drone_ids,
        )
        end_behavior = getattr(Params, "SWARM_TRAJECTORY_END_BEHAVIOR", "return_home")
        timeout_relative_altitude = formation_relative_altitude
        if processed_relative_altitude is not None:
            timeout_relative_altitude = max(timeout_relative_altitude, processed_relative_altitude)
        mission_timeout = estimate_command_completion_timeout(
            duration,
            end_behavior=end_behavior,
            relative_altitude_m=timeout_relative_altitude,
        )
        results["expected_duration_sec"] = duration
        results["end_behavior"] = end_behavior
        results["processed_max_relative_altitude_m"] = processed_relative_altitude
        results["timeout_relative_altitude_m"] = timeout_relative_altitude
        results["mission_timeout_sec"] = mission_timeout

        status = wait_for_command(client, command_id, terminal=True, timeout=mission_timeout)
        require(status.get("outcome") == "completed", f"Mission did not complete cleanly: {command_summary(status)}")
        results["command_result"] = command_summary(status)

        wait_for_idle(client, args.drone_ids, timeout=240)
        results["result"] = "PASS"

        print(json.dumps(results, indent=2))
        return 0
    except Exception as exc:
        results["result"] = "FAIL"
        results["error"] = str(exc)
        print(json.dumps(results, indent=2))
        try:
            cleanup_land(client, args.drone_ids, "Swarm Trajectory Validation Cleanup Land", baselines if "baselines" in locals() else None)
        except Exception as cleanup_exc:
            log(f"CLEANUP ERROR: {cleanup_exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
