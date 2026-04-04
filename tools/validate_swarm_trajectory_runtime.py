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
import bisect
import csv
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.error
import urllib.parse
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
    from src.drone_api_routes import DRONE_LIVE_ARMABILITY_ROUTE
    from src.gcs_api_routes import (
        GCS_SWARM_TRAJECTORY_PROCESS_ROUTE,
        GCS_SWARM_TRAJECTORY_STATUS_ROUTE,
    )
    from src.live_armability_utils import calculate_live_armability_request_timeout
    from src.params import Params
    from tools.runtime_validation_support import write_json_report
except Exception:  # pragma: no cover - validator fallback only
    USING_FALLBACK_TIMEOUT_PARAMS = True
    DRONE_LIVE_ARMABILITY_ROUTE = "/api/v1/preflight/armability"

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
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC = 5.0
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC = 2.0

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

    def calculate_live_armability_request_timeout(*, params=Params):
        connect_timeout = max(
            0.1,
            float(getattr(params, "LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC", 5.0)),
        )
        probe_timeout = max(
            0.1,
            float(getattr(params, "LIVE_ARMABILITY_PROBE_TIMEOUT_SEC", 6.0)),
        )
        http_buffer_sec = max(
            0.5,
            float(getattr(params, "LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC", 2.0)),
        )
        return connect_timeout + probe_timeout + http_buffer_sec

    GCS_SWARM_TRAJECTORY_STATUS_ROUTE = "/api/v1/swarm-trajectories/status"
    GCS_SWARM_TRAJECTORY_PROCESS_ROUTE = "/api/v1/swarm-trajectories/process"

    def write_json_report(path, payload):  # pragma: no cover - fallback only
        return None


SWARM_TRAJECTORY = 4
LAND = 101
TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout", "superseded"}


def log(message: str) -> None:
    print(message, flush=True)


def decode_http_error_detail(exc: urllib.error.HTTPError) -> str:
    """Return the most useful detail embedded in an HTTP error body."""
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
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

    def get_telemetry(self) -> dict[str, dict]:
        payload = self.get_json("/api/v1/fleet/telemetry")
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def get_swarm_assignments(self) -> list[dict]:
        payload = self.get_json("/api/v1/config/swarm")
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
        response = self.post_json("/api/v1/commands", payload)
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


def wait_api_ready(client: ApiClient, timeout: int = 60) -> dict:
    def _ready():
        try:
            return client.get_json("/api/v1/system/health")
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


def probe_live_armability_for_drone(
    drone_id: int,
    drone_ip: str | None,
    *,
    require_global_position: bool = True,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Query the drone-side live armability endpoint used by launch gating."""
    normalized_id = int(drone_id)
    normalized_ip = str(drone_ip or "").strip()

    if not normalized_ip or normalized_ip.upper() == "N/A":
        return {
            "drone_id": normalized_id,
            "drone_ip": drone_ip,
            "success": False,
            "ready": False,
            "summary": "Drone IP unavailable for live armability probe",
            "category": "error",
            "details": None,
        }

    query = urllib.parse.urlencode(
        {"require_global_position": str(bool(require_global_position)).lower()}
    )
    url = f"http://{normalized_ip}:7070{DRONE_LIVE_ARMABILITY_ROUTE}?{query}"
    request_timeout = float(timeout or calculate_live_armability_request_timeout(params=Params))

    try:
        with urllib.request.urlopen(url, timeout=request_timeout) as response:
            payload = json.load(response)
        ready = bool(payload.get("ready"))
        return {
            "drone_id": normalized_id,
            "drone_ip": normalized_ip,
            "success": bool(payload.get("success", True)),
            "ready": ready,
            "summary": str(
                payload.get("summary")
                or ("ready for mission startup" if ready else "Live armability probe reported not ready")
            ),
            "category": "ready" if ready else "blocked",
            "details": payload,
        }
    except urllib.error.HTTPError as exc:
        return {
            "drone_id": normalized_id,
            "drone_ip": normalized_ip,
            "success": False,
            "ready": False,
            "summary": format_http_error(exc),
            "category": "error",
            "details": None,
        }
    except (urllib.error.URLError, TimeoutError) as exc:
        return {
            "drone_id": normalized_id,
            "drone_ip": normalized_ip,
            "success": False,
            "ready": False,
            "summary": f"Live armability probe unreachable: {exc}",
            "category": "offline",
            "details": None,
        }
    except Exception as exc:
        return {
            "drone_id": normalized_id,
            "drone_ip": normalized_ip,
            "success": False,
            "ready": False,
            "summary": f"Live armability probe failed: {exc}",
            "category": "error",
            "details": None,
        }


def collect_live_armability_results(
    client: ApiClient,
    ids: Iterable[int],
    *,
    require_global_position: bool = True,
    timeout: float | None = None,
) -> dict[str, Any]:
    """Collect per-drone live armability truth for the selected mission set."""
    telemetry = client.get_telemetry()
    target_ids = sorted({int(drone_id) for drone_id in ids})
    results: dict[str, dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=max(1, min(len(target_ids), 10))) as executor:
        future_to_id = {}

        for drone_id in target_ids:
            row = telemetry.get(str(drone_id))
            drone_ip = None if row is None else row.get("ip")
            if row is None:
                results[str(drone_id)] = {
                    "drone_id": drone_id,
                    "drone_ip": None,
                    "success": False,
                    "ready": False,
                    "summary": "No telemetry row available for live armability probe",
                    "category": "error",
                    "details": None,
                }
                continue

            future = executor.submit(
                probe_live_armability_for_drone,
                drone_id,
                drone_ip,
                require_global_position=require_global_position,
                timeout=timeout,
            )
            future_to_id[future] = drone_id

        for future in as_completed(future_to_id):
            drone_id = future_to_id[future]
            results[str(drone_id)] = future.result()

    blocked_ids = sorted(
        int(drone_id)
        for drone_id, result in results.items()
        if result.get("category") == "blocked"
    )
    unavailable_ids = sorted(
        int(drone_id)
        for drone_id, result in results.items()
        if result.get("category") in {"offline", "error"}
    )

    return {
        "all_ready": not blocked_ids and not unavailable_ids,
        "blocked_ids": blocked_ids,
        "unavailable_ids": unavailable_ids,
        "results": results,
    }


def wait_for_live_launch_readiness(client: ApiClient, ids: list[int], timeout: int = 60) -> dict[str, Any]:
    """Wait until the live launch gate agrees the selected drones are armable."""
    last_results: dict[str, Any] | None = None

    def _ready():
        nonlocal last_results
        last_results = collect_live_armability_results(client, ids)
        if last_results["all_ready"]:
            return last_results
        return False

    try:
        return wait_for(
            _ready,
            label=f"live launch armability for drones {ids}",
            timeout=timeout,
            interval=2.0,
        )
    except Exception as exc:
        raise RuntimeError(
            "Live launch readiness did not stabilize before dispatch. "
            f"Last probe results: {json.dumps(last_results or {}, indent=2)}"
        ) from exc


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
        status = client.get_json(f"/api/v1/commands/{command_id}")
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
    deadline = time.time() + timeout
    peak_gains = {int(idx): float("-inf") for idx in baselines}
    last_telemetry: dict[str, dict] | None = None

    while time.time() < deadline:
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in baselines):
            time.sleep(1.0)
            continue

        all_reached = True
        last_telemetry = telemetry
        for idx, baseline in baselines.items():
            current = telemetry[str(idx)].get("position_alt")
            if current is None:
                all_reached = False
                continue
            try:
                gain = float(current) - float(baseline)
            except (TypeError, ValueError):
                all_reached = False
                continue
            peak_gains[int(idx)] = max(peak_gains[int(idx)], gain)
            if peak_gains[int(idx)] < min_gain:
                all_reached = False

        if all_reached:
            log(f"WAIT OK: each selected drone reached +{min_gain:.1f}m relative altitude")
            return telemetry

        time.sleep(1.0)

    rounded_peaks = {
        int(idx): (None if value == float("-inf") else round(value, 2))
        for idx, value in peak_gains.items()
    }
    raise RuntimeError(
        f"Timed out waiting for each selected drone to reach +{min_gain:.1f}m relative altitude. "
        f"Peak gains: {rounded_peaks}. Last telemetry present: {last_telemetry is not None}"
    )


def latlon_to_ne(lat_deg: float, lon_deg: float, ref_lat_deg: float, ref_lon_deg: float) -> tuple[float, float]:
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(ref_lat_deg))
    north = (lat_deg - ref_lat_deg) * lat_scale
    east = (lon_deg - ref_lon_deg) * lon_scale
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


def load_processed_track(repo_root: Path, drone_id: int) -> dict[str, Any]:
    """Load one processed Drone N.csv track as mission-time samples."""
    csv_path = repo_root / "shapes_sitl" / "swarm_trajectory" / "processed" / f"Drone {int(drone_id)}.csv"
    require(csv_path.exists(), f"Missing processed track for drone {int(drone_id)}: {csv_path}")

    samples: list[dict[str, float]] = []
    with csv_path.open() as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                samples.append(
                    {
                        "t": float(row["t"]),
                        "lat": float(row["lat"]),
                        "lon": float(row["lon"]),
                        "alt": float(row["alt"]),
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue

    require(samples, f"Processed track has no usable samples for drone {int(drone_id)}: {csv_path}")
    samples.sort(key=lambda sample: sample["t"])
    times = [sample["t"] for sample in samples]
    return {
        "drone_id": int(drone_id),
        "path": str(csv_path),
        "samples": samples,
        "times": times,
        "start_t": times[0],
        "end_t": times[-1],
    }


def sample_processed_track(track: dict[str, Any], mission_elapsed_s: float) -> dict[str, float]:
    """Return the nearest processed sample for the requested mission time."""
    times = track["times"]
    samples = track["samples"]
    target_t = min(max(float(mission_elapsed_s), float(track["start_t"])), float(track["end_t"]))
    index = bisect.bisect_left(times, target_t)

    if index <= 0:
        sample = samples[0]
    elif index >= len(samples):
        sample = samples[-1]
    else:
        previous_sample = samples[index - 1]
        next_sample = samples[index]
        if abs(previous_sample["t"] - target_t) <= abs(next_sample["t"] - target_t):
            sample = previous_sample
        else:
            sample = next_sample

    return {
        **sample,
        "requested_t": float(mission_elapsed_s),
        "sample_error_s": abs(float(sample["t"]) - float(mission_elapsed_s)),
    }


def processed_formation_expectations(
    repo_root: Path,
    assignments: dict[int, dict],
) -> dict[int, dict[str, Any]]:
    """Bind each follower to authoritative processed leader/follower tracks."""
    track_cache: dict[int, dict[str, Any]] = {}
    processed: dict[int, dict[str, Any]] = {}

    for follower_id, assignment in assignments.items():
        leader_id = int(assignment["leader_id"])
        follower_track = track_cache.setdefault(int(follower_id), load_processed_track(repo_root, int(follower_id)))
        leader_track = track_cache.setdefault(leader_id, load_processed_track(repo_root, leader_id))
        start_t = max(float(follower_track["start_t"]), float(leader_track["start_t"]))
        end_t = min(float(follower_track["end_t"]), float(leader_track["end_t"]))
        require(
            end_t >= start_t,
            f"Processed track windows do not overlap for leader {leader_id} and follower {int(follower_id)}",
        )
        processed[int(follower_id)] = {
            "leader_id": leader_id,
            "follower_track": follower_track,
            "leader_track": leader_track,
            "start_t": start_t,
            "end_t": end_t,
            "window_start_s": start_t,
            "window_end_s": end_t,
        }

    return processed


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


def max_selected_horizontal_offset_m(
    assignments: list[dict],
    *,
    leader_ids: Iterable[int],
    active_ids: Iterable[int],
) -> float:
    active_set = {int(drone_id) for drone_id in active_ids}
    leader_set = {int(drone_id) for drone_id in leader_ids}
    max_offset = 0.0

    for assignment in assignments:
        follower_id = int(assignment["hw_id"])
        leader_id = int(assignment.get("follow", 0) or 0)
        if follower_id not in active_set or leader_id not in leader_set:
            continue
        offset_x = float(assignment.get("offset_x", 0.0) or 0.0)
        offset_y = float(assignment.get("offset_y", 0.0) or 0.0)
        max_offset = max(max_offset, math.hypot(offset_x, offset_y))

    return max_offset


def recommend_short_profile_entry_delay(
    *,
    default_entry_delay_s: float,
    relative_altitude_m: float,
    max_horizontal_offset_m: float,
) -> float:
    """
    Give followers enough route-entry time to climb and form before geometry checks begin.

    Short leader-only routes can otherwise end before large-offset followers ever stabilize,
    which produces misleading post-mission geometry diagnostics instead of a true runtime signal.
    """
    horizontal_formup_time = (max(20.0, float(max_horizontal_offset_m) + 20.0)) / 4.0
    vertical_climb_time = max(0.0, float(relative_altitude_m)) / 2.5
    recommended = max(float(default_entry_delay_s), horizontal_formup_time + vertical_climb_time + 4.0)
    return round(recommended, 1)


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
    expectations: dict[int, dict[str, Any]],
    *,
    mission_elapsed_s: float,
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

        if mission_elapsed_s < expectation["start_t"]:
            overall_ok = False
            diagnostics.append(
                {
                    "follower_id": follower_id,
                    "leader_id": leader_id,
                    "status": "before_processed_window",
                    "mission_elapsed_s": round(mission_elapsed_s, 2),
                    "window_start_s": round(expectation["start_t"], 2),
                    "window_end_s": round(expectation["end_t"], 2),
                }
            )
            continue

        if mission_elapsed_s > expectation["end_t"]:
            overall_ok = False
            diagnostics.append(
                {
                    "follower_id": follower_id,
                    "leader_id": leader_id,
                    "status": "after_processed_window",
                    "mission_elapsed_s": round(mission_elapsed_s, 2),
                    "window_start_s": round(expectation["start_t"], 2),
                    "window_end_s": round(expectation["end_t"], 2),
                }
            )
            continue

        actual_n, actual_e = latlon_to_ne(
            float(follower["position_lat"]),
            float(follower["position_long"]),
            float(leader["position_lat"]),
            float(leader["position_long"]),
        )
        actual_alt_delta = float(follower["position_alt"]) - float(leader["position_alt"])
        leader_sample = sample_processed_track(expectation["leader_track"], mission_elapsed_s)
        follower_sample = sample_processed_track(expectation["follower_track"], mission_elapsed_s)
        expected_n, expected_e = latlon_to_ne(
            float(follower_sample["lat"]),
            float(follower_sample["lon"]),
            float(leader_sample["lat"]),
            float(leader_sample["lon"]),
        )
        expected_alt_delta = float(follower_sample["alt"]) - float(leader_sample["alt"])
        horizontal_error = math.hypot(actual_n - expected_n, actual_e - expected_e)
        vertical_error = abs(actual_alt_delta - expected_alt_delta)
        ok = horizontal_error <= horiz_tolerance and vertical_error <= vert_tolerance
        overall_ok = overall_ok and ok

        diagnostics.append({
            "follower_id": follower_id,
            "leader_id": leader_id,
            "mission_elapsed_s": round(mission_elapsed_s, 2),
            "sampled_leader_t_s": round(float(leader_sample["t"]), 2),
            "sampled_follower_t_s": round(float(follower_sample["t"]), 2),
            "sample_t_error_s": round(
                max(float(leader_sample["sample_error_s"]), float(follower_sample["sample_error_s"])),
                2,
            ),
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
    expectations: dict[int, dict[str, Any]],
    *,
    execution_started_at_ms: int,
    horiz_tolerance: float,
    vert_tolerance: float,
    timeout: int = 120,
) -> dict:
    last_diagnostics: list[dict] | None = None
    last_state_issues: list[dict] | None = None
    consecutive_ok_samples = 0
    require(execution_started_at_ms > 0, "Missing execution_started_at_ms for formation validation")

    def _active_swarm_row(row: dict[str, Any] | None) -> bool:
        if not row:
            return False
        mission = int(row.get("mission", 0) or 0)
        state = int(row.get("state", 0) or 0)
        return mission == SWARM_TRAJECTORY and state == 2 and bool(row.get("is_armed"))

    def _formed():
        nonlocal consecutive_ok_samples, last_diagnostics, last_state_issues
        telemetry = client.get_telemetry()
        state_issues: list[dict] = []
        mission_elapsed_s = max(0.0, ((time.time() * 1000.0) - float(execution_started_at_ms)) / 1000.0)

        for follower_id, expectation in expectations.items():
            leader_id = expectation["leader_id"]
            leader = telemetry.get(str(leader_id))
            follower = telemetry.get(str(follower_id))

            if not _active_swarm_row(leader):
                state_issues.append(
                    {
                        "drone_id": leader_id,
                        "role": "leader",
                        "issue": "not_actively_executing",
                        "mission": None if leader is None else leader.get("mission"),
                        "state": None if leader is None else leader.get("state"),
                        "armed": None if leader is None else leader.get("is_armed"),
                    }
                )

            if not _active_swarm_row(follower):
                state_issues.append(
                    {
                        "drone_id": follower_id,
                        "role": "follower",
                        "issue": "not_actively_executing",
                        "mission": None if follower is None else follower.get("mission"),
                        "state": None if follower is None else follower.get("state"),
                        "armed": None if follower is None else follower.get("is_armed"),
                    }
                )

        if state_issues:
            consecutive_ok_samples = 0
            last_state_issues = state_issues
            return False

        last_state_issues = None
        ok, diagnostics = evaluate_formation_snapshot(
            telemetry,
            expectations,
            mission_elapsed_s=mission_elapsed_s,
            horiz_tolerance=horiz_tolerance,
            vert_tolerance=vert_tolerance,
        )
        last_diagnostics = diagnostics
        if ok:
            consecutive_ok_samples += 1
            if consecutive_ok_samples < 2:
                return False
            return {
                "telemetry": telemetry,
                "diagnostics": diagnostics,
            }
        consecutive_ok_samples = 0
        return False

    try:
        return wait_for(_formed, label="follower geometry within tolerance", timeout=timeout, interval=2.0)
    except Exception as exc:
        state_issue_suffix = (
            f" Last mission-state issues: {json.dumps(last_state_issues, indent=2)}"
            if last_state_issues
            else ""
        )
        raise RuntimeError(
            f"Formation did not converge within tolerance. Last diagnostics: {json.dumps(last_diagnostics or [], indent=2)}.{state_issue_suffix}"
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
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Optional path to write the final validation summary JSON",
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
            max_horizontal_offset = max_selected_horizontal_offset_m(
                assignments,
                leader_ids=leader_ids,
                active_ids=args.drone_ids,
            )
            entry_delay_s = recommend_short_profile_entry_delay(
                default_entry_delay_s=args.short_profile_entry_delay,
                relative_altitude_m=args.short_profile_altitude_gain,
                max_horizontal_offset_m=max_horizontal_offset,
            )
            prepared = write_short_validation_profiles(
                args.repo_root,
                baseline,
                leader_ids,
                relative_altitude_m=args.short_profile_altitude_gain,
                entry_delay_s=entry_delay_s,
                leg_duration_s=args.short_profile_leg_duration,
            )
            log(f"Prepared short validation profiles for leaders {leader_ids}")
            results["prepared_short_profiles"] = prepared
            results["prepared_short_profile_entry_delay_s"] = entry_delay_s
            results["prepared_short_profile_max_horizontal_offset_m"] = max_horizontal_offset

        status_before = client.get_json(GCS_SWARM_TRAJECTORY_STATUS_ROUTE)
        require(status_before.get("success") is True, f"Status unavailable: {status_before}")
        results["status_before"] = status_before["status"]

        process_result = client.post_json(
            GCS_SWARM_TRAJECTORY_PROCESS_ROUTE,
            {"force_clear": False, "auto_reload": True},
        )
        require(process_result.get("success") is True, f"Processing failed: {process_result}")
        results["process_result"] = process_result

        status_after = client.get_json(GCS_SWARM_TRAJECTORY_STATUS_ROUTE)
        require(status_after.get("success") is True, f"Status unavailable after processing: {status_after}")
        require(status_after["status"]["cluster_summary"]["all_clusters_ready"] is True, f"Clusters not ready: {status_after}")
        results["status_after"] = status_after["status"]

        expectations = follower_expectations(assignments, active_ids=args.drone_ids)
        scope_issues = follower_scope_issues(expectations, active_ids=args.drone_ids)
        require(not scope_issues, f"Selected mission set has followers without their leaders: {scope_issues}")
        results["assignments"] = expectations
        results["assignment_scope_issues"] = scope_issues
        processed_expectations = processed_formation_expectations(args.repo_root, expectations) if expectations else {}
        results["processed_assignments"] = {
            str(follower_id): {
                "leader_id": expectation["leader_id"],
                "window_start_s": expectation["start_t"],
                "window_end_s": expectation["end_t"],
                "leader_track": expectation["leader_track"]["path"],
                "follower_track": expectation["follower_track"]["path"],
            }
            for follower_id, expectation in processed_expectations.items()
        }

        live_launch_readiness = wait_for_live_launch_readiness(client, args.drone_ids, timeout=90)
        results["live_launch_readiness"] = live_launch_readiness

        response = client.submit_command(
            SWARM_TRAJECTORY,
            args.drone_ids,
            "Swarm Trajectory Validation",
            trigger_time=0,
        )
        command_id = response["command_id"]
        results["dispatch"] = response

        in_progress_status = wait_for_command(client, command_id, desired_phase="in_progress", timeout=120)
        execution_started_at_ms = int(in_progress_status.get("execution_started_at") or 0)
        require(execution_started_at_ms > 0, f"Command {command_id} never reported execution_started_at")
        results["execution_started_at_ms"] = execution_started_at_ms
        wait_for_executing(client, args.drone_ids, timeout=180)
        wait_for_altitude_gain(client, baselines, min_gain=args.min_altitude_gain, timeout=120)

        formation_relative_altitude = max(
            max(0.0, float(client.get_telemetry()[str(idx)]["position_alt"]) - float(baselines[idx]))
            for idx in args.drone_ids
        )
        if expectations:
            formation = wait_for_formation(
                client,
                processed_expectations,
                execution_started_at_ms=execution_started_at_ms,
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

        write_json_report(args.json_output, results)
        print(json.dumps(results, indent=2))
        return 0
    except Exception as exc:
        results["result"] = "FAIL"
        results["error"] = str(exc)
        write_json_report(args.json_output, results)
        print(json.dumps(results, indent=2))
        try:
            cleanup_land(client, args.drone_ids, "Swarm Trajectory Validation Cleanup Land", baselines if "baselines" in locals() else None)
        except Exception as cleanup_exc:
            log(f"CLEANUP ERROR: {cleanup_exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
