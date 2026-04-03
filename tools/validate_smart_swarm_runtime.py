#!/usr/bin/env python3
"""
End-to-end Smart Swarm runtime validation for SITL fleets.

This script validates the operator-facing Smart Swarm workflow against the
currently saved swarm configuration:

1. Take off the requested drones
2. Start Smart Swarm per detected cluster
3. Wait for each cluster to settle into its saved formation
4. Reassign one follower in flight (when the default 5-drone demo layout exists)
5. Confirm a leader-only RTL does not kick followers out of Smart Swarm
6. Stop/land the remaining drones and verify clean disarm
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

try:
    from src.params import Params
except Exception:
    Params = None


TAKEOFF = 10
SMART_SWARM = 2
LAND = 101
HOLD = 102
RTL = 104

TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout"}
COMMAND_HEARTBEAT_GRACE_SECONDS = (
    max(Params.TELEMETRY_POLLING_TIMEOUT, Params.heartbeat_interval * 2)
    if Params is not None else 20
)


def log(message: str) -> None:
    print(message, flush=True)


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def get_json(self, path: str):
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=15) as response:
            return json.load(response)

    def post_json(self, path: str, payload):
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def patch_json(self, path: str, payload):
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def get_telemetry(self):
        payload = self.get_json("/api/telemetry")
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def get_swarm(self):
        payload = self.get_json("/api/v1/config/swarm")
        if isinstance(payload, dict) and "assignments" in payload:
            payload = payload["assignments"]
        return payload

    def submit_command(self, mission_type: int, target_ids: list[int], operator_label: str):
        payload = {
            "missionType": str(mission_type),
            "triggerTime": "0",
            "target_drones": [str(target_id) for target_id in target_ids],
            "operatorLabel": operator_label,
        }
        response = self.post_json("/api/v1/commands", payload)
        command_id = response["command_id"]
        log(f"COMMAND {operator_label}: id={command_id} targets={target_ids}")
        return command_id, response

    def update_assignment(self, hw_id: int, **kwargs):
        payload = {}
        for key in ("follow", "offset_x", "offset_y", "offset_z", "frame"):
            if key in kwargs and kwargs[key] is not None:
                payload[key] = kwargs[key]
        response = self.patch_json(f"/api/v1/config/swarm/assignments/{int(hw_id)}", payload)
        log(f"SWARM UPDATE hw_id={hw_id}: {response['assignment']}")
        return response["assignment"]


def command_summary(status: dict) -> dict:
    acks = status.get("acks") or {}
    executions = status.get("executions") or {}
    return {
        "status": status.get("status"),
        "phase": status.get("phase"),
        "outcome": status.get("outcome"),
        "acks": {
            "expected": acks.get("expected"),
            "received": acks.get("received"),
            "accepted": acks.get("accepted"),
            "offline": acks.get("offline"),
            "rejected": acks.get("rejected"),
            "errors": acks.get("errors"),
        },
        "executions": {
            "expected": executions.get("expected"),
            "received": executions.get("received"),
            "succeeded": executions.get("succeeded"),
            "failed": executions.get("failed"),
        },
    }


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


def wait_api_ready(client: ApiClient, timeout: int = 60):
    def _ready():
        try:
            return client.get_json("/health")
        except urllib.error.URLError:
            return False

    return wait_for(_ready, label="GCS API health endpoint", timeout=timeout, interval=2.0)


def wait_for_command(client: ApiClient, command_id: str, *, desired_phase: str | None = None, terminal: bool = False, timeout: int = 90):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        status = client.get_json(f"/api/v1/commands/{command_id}")
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


def snapshot(client: ApiClient, ids: list[int]) -> dict[str, dict]:
    telemetry = client.get_telemetry()
    return {str(idx): telemetry[str(idx)] for idx in ids}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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


def build_clusters(assignments: list[dict], allowed_ids: set[int]) -> list[list[int]]:
    by_hw = {int(entry["hw_id"]): entry for entry in assignments if int(entry["hw_id"]) in allowed_ids}

    def root_for(hw_id: int) -> int:
        seen = set()
        current = hw_id
        while True:
            if current in seen:
                raise RuntimeError(f"Cycle detected while deriving cluster for hw_id={hw_id}")
            seen.add(current)
            entry = by_hw.get(current)
            if not entry:
                return hw_id
            follow = int(entry.get("follow", 0) or 0)
            if follow == 0 or follow not in by_hw:
                return current
            current = follow

    grouped: dict[int, list[int]] = defaultdict(list)
    for hw_id in sorted(by_hw):
        grouped[root_for(hw_id)].append(hw_id)
    return [members for _, members in sorted(grouped.items())]


def formation_error(leader: dict, follower: dict, entry: dict) -> dict:
    follower_n, follower_e = latlon_to_ne(
        follower["position_lat"],
        follower["position_long"],
        leader["position_lat"],
        leader["position_long"],
    )
    frame = str(entry.get("frame", "ned")).lower()
    if frame == "body":
        expected_n, expected_e = body_to_ne(
            float(entry["offset_x"]),
            float(entry["offset_y"]),
            leader.get("yaw", 0.0),
        )
    else:
        expected_n, expected_e = float(entry["offset_x"]), float(entry["offset_y"])

    altitude_delta = follower["position_alt"] - leader["position_alt"]
    expected_altitude = float(entry.get("offset_z", 0.0))
    return {
        "follow": int(entry["follow"]),
        "expected_n": expected_n,
        "expected_e": expected_e,
        "actual_n": follower_n,
        "actual_e": follower_e,
        "horizontal_error": math.hypot(follower_n - expected_n, follower_e - expected_e),
        "expected_altitude_delta": expected_altitude,
        "actual_altitude_delta": altitude_delta,
        "altitude_error": abs(altitude_delta - expected_altitude),
        "frame": frame,
    }


def cluster_assignments(assignments: list[dict], ids: list[int]) -> list[dict]:
    id_set = {int(idx) for idx in ids}
    return [entry for entry in assignments if int(entry["hw_id"]) in id_set]


def canonical_assignment(entry: dict) -> dict:
    return {
        "follow": int(entry.get("follow", 0) or 0),
        "offset_x": float(entry.get("offset_x", 0.0) or 0.0),
        "offset_y": float(entry.get("offset_y", 0.0) or 0.0),
        "offset_z": float(entry.get("offset_z", 0.0) or 0.0),
        "frame": str(entry.get("frame", "body")).lower(),
    }


def assignment_snapshot(assignments: list[dict], ids) -> dict[int, dict]:
    id_set = {int(idx) for idx in ids}
    return {
        int(entry["hw_id"]): canonical_assignment(entry)
        for entry in assignments
        if int(entry["hw_id"]) in id_set
    }


def restore_assignments(client: ApiClient, expected_assignments: dict[int, dict], timeout: int = 30) -> list[int]:
    current_assignments = assignment_snapshot(client.get_swarm(), expected_assignments.keys())
    changed_ids: list[int] = []

    for hw_id, expected in expected_assignments.items():
        if current_assignments.get(int(hw_id)) == expected:
            continue
        client.update_assignment(int(hw_id), **expected)
        changed_ids.append(int(hw_id))

    if not changed_ids:
        return []

    def _ready():
        current = assignment_snapshot(client.get_swarm(), expected_assignments.keys())
        for hw_id, expected in expected_assignments.items():
            if current.get(int(hw_id)) != expected:
                return False
        return current

    wait_for(_ready, label=f"swarm config restored for drones {changed_ids}", timeout=timeout, interval=1.0)
    return changed_ids


def measure_cluster(assignments: list[dict], telemetry: dict[str, dict]) -> tuple[dict[str, dict], float]:
    errors = {}
    max_horizontal_error = 0.0
    for entry in assignments:
        follower_id = int(entry["hw_id"])
        leader_id = int(entry["follow"])
        if leader_id == 0:
            continue
        follower = telemetry[str(follower_id)]
        leader = telemetry[str(leader_id)]
        result = formation_error(leader, follower, entry)
        errors[str(follower_id)] = result
        max_horizontal_error = max(max_horizontal_error, result["horizontal_error"])
    return errors, max_horizontal_error


def formation_timeout_seconds(initial_max_error: float, max_velocity: float, minimum_timeout: int) -> int:
    if max_velocity <= 0:
        return minimum_timeout
    dynamic = int(math.ceil((initial_max_error / max_velocity) * 2.0 + 25.0))
    return max(minimum_timeout, dynamic)


def wait_altitude(client: ApiClient, ids: list[int], base_altitudes: dict[str, float], min_gain: float):
    def _ready():
        telemetry = snapshot(client, ids)
        for drone_id in ids:
            row = telemetry[str(drone_id)]
            if not row.get("is_armed"):
                return False
            if row["position_alt"] - base_altitudes[str(drone_id)] < min_gain:
                return False
        return telemetry

    return wait_for(_ready, label=f"drones {ids} armed and climbed {min_gain}m", timeout=120, interval=2.0)


def wait_fleet_ready(client: ApiClient, ids: list[int], timeout: int = 90):
    def _ready():
        try:
            telemetry = client.get_telemetry()
        except urllib.error.URLError:
            return False
        if not _telemetry_has_ids(telemetry, ids):
            return False
        for drone_id in ids:
            row = telemetry[str(drone_id)]
            if not _is_idle_baseline_row(row):
                return False
        return {str(idx): telemetry[str(idx)] for idx in ids}

    return wait_for(_ready, label=f"drones {ids} grounded, idle, and preflight ready", timeout=timeout, interval=2.0)


def wait_mission(client: ApiClient, ids: list[int], mission_type: int, timeout: int = 60):
    def _ready():
        telemetry = snapshot(client, ids)
        for drone_id in ids:
            if telemetry[str(drone_id)].get("mission") != mission_type:
                return False
        return telemetry

    return wait_for(_ready, label=f"drones {ids} mission={mission_type}", timeout=timeout, interval=1.0)


def wait_follow_mode(client: ApiClient, drone_id: int, follow_mode: int, timeout: int = 30):
    def _ready():
        telemetry = snapshot(client, [drone_id])
        row = telemetry[str(drone_id)]
        if row.get("follow_mode") != follow_mode:
            return False
        return row

    return wait_for(_ready, label=f"drone {drone_id} telemetry follow_mode={follow_mode}", timeout=timeout, interval=1.0)


def wait_swarm_update(client: ApiClient, drone_id: int, *, follow: int | None = None, frame: str | None = None, timeout: int = 20):
    def _ready():
        swarm = client.get_swarm()
        for entry in swarm:
            if int(entry["hw_id"]) != int(drone_id):
                continue
            if follow is not None and int(entry.get("follow", -1)) != int(follow):
                return False
            if frame is not None and str(entry.get("frame", "")).lower() != frame.lower():
                return False
            return entry
        return False

    return wait_for(_ready, label=f"swarm config for drone {drone_id} updated", timeout=timeout, interval=1.0)


def wait_formation(
    client: ApiClient,
    assignments: list[dict],
    ids: list[int],
    *,
    horizontal_tolerance: float,
    altitude_tolerance: float,
    minimum_timeout: int,
    stability_samples: int,
    max_velocity: float,
) -> dict[str, dict]:
    telemetry = snapshot(client, ids)
    _, initial_max_error = measure_cluster(assignments, telemetry)
    timeout = formation_timeout_seconds(initial_max_error, max_velocity, minimum_timeout)
    log(
        f"WAIT FORMATION ids={ids} initial_max_horizontal_error={initial_max_error:.1f}m "
        f"timeout={timeout}s stability_samples={stability_samples}"
    )

    deadline = time.time() + timeout
    consecutive = 0
    last_errors = {}

    while time.time() < deadline:
        telemetry = snapshot(client, ids)
        errors, max_horizontal_error = measure_cluster(assignments, telemetry)
        last_errors = errors
        if errors:
            worst_altitude_error = max(result["altitude_error"] for result in errors.values())
        else:
            worst_altitude_error = 0.0

        if (
            max_horizontal_error <= horizontal_tolerance
            and worst_altitude_error <= altitude_tolerance
        ):
            consecutive += 1
            if consecutive >= stability_samples:
                log(
                    f"WAIT OK: formation settled for {ids} "
                    f"(max_horizontal_error={max_horizontal_error:.2f}m, "
                    f"max_altitude_error={worst_altitude_error:.2f}m)"
                )
                return errors
        else:
            consecutive = 0
        time.sleep(2.0)

    raise RuntimeError(
        "Timed out waiting for formation settled for "
        f"{ids}. Last errors: {json.dumps(last_errors, indent=2)}"
    )


def wait_idle_reset(client: ApiClient, ids: list[int], timeout: int = 180):
    def _ready():
        telemetry = snapshot(client, ids)
        for drone_id in ids:
            if not _is_idle_reset_row(telemetry[str(drone_id)]):
                return False
        return telemetry

    return wait_for(_ready, label=f"drones {ids} disarmed and reset idle", timeout=timeout, interval=2.0)


def require_full_acceptance(status: dict, expected_targets: int, label: str) -> None:
    accepted = (status.get("acks") or {}).get("accepted")
    if accepted != expected_targets:
        raise RuntimeError(
            f"{label} did not reach full acceptance ({accepted}/{expected_targets}): "
            f"{json.dumps(command_summary(status), indent=2)}"
        )


def require_full_execution(status: dict, expected_targets: int, label: str) -> None:
    succeeded = (status.get("executions") or {}).get("succeeded")
    if succeeded != expected_targets:
        raise RuntimeError(
            f"{label} did not finish on all targets ({succeeded}/{expected_targets}): "
            f"{json.dumps(command_summary(status), indent=2)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Smart Swarm runtime on a live GCS/SITL stack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="GCS API base URL")
    parser.add_argument("--drones", default="1,2,3,4,5", help="Comma-separated drone hardware IDs to validate")
    parser.add_argument("--takeoff-min-gain", type=float, default=4.0, help="Minimum altitude gain required after takeoff")
    parser.add_argument("--horizontal-tolerance", type=float, default=5.0, help="Formation horizontal error tolerance in meters")
    parser.add_argument("--altitude-tolerance", type=float, default=1.5, help="Formation altitude error tolerance in meters")
    parser.add_argument("--formation-min-timeout", type=int, default=45, help="Minimum per-cluster formation settle timeout")
    parser.add_argument("--max-smart-swarm-velocity", type=float, default=3.0, help="Expected Smart Swarm max velocity used for timeout sizing")
    parser.add_argument("--stability-samples", type=int, default=3, help="Consecutive in-tolerance samples required before a cluster is considered settled")
    parser.add_argument("--skip-reassign", action="store_true", help="Skip the in-flight follower reassignment check")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = ApiClient(args.base_url)
    ids = [int(part.strip()) for part in args.drones.split(",") if part.strip()]
    require(ids, "No drone IDs supplied.")

    wait_api_ready(client, timeout=60)
    telemetry = wait_fleet_ready(client, ids, timeout=120)
    base_altitudes = {str(idx): telemetry[str(idx)]["position_alt"] for idx in ids}
    log(f"BASE ALTITUDES: {base_altitudes}")

    swarm = client.get_swarm()
    original_assignments = assignment_snapshot(swarm, ids)
    clusters = build_clusters(swarm, set(ids))
    require(clusters, "No Smart Swarm clusters found for the selected drones.")
    log(f"SMART SWARM CLUSTERS: {clusters}")

    command_id, _ = client.submit_command(TAKEOFF, ids, "Smart Swarm Validation Takeoff")
    status = wait_for_command(client, command_id, terminal=True, timeout=150)
    require(status["status"] == "completed", f"Takeoff command failed: {command_summary(status)}")
    require_full_acceptance(status, len(ids), "Takeoff")
    require_full_execution(status, len(ids), "Takeoff")
    wait_altitude(client, ids, base_altitudes, args.takeoff_min_gain)

    for cluster in clusters:
        command_id, _ = client.submit_command(SMART_SWARM, cluster, f"Start Smart Swarm Cluster {cluster[0]}")
        status = wait_for_command(client, command_id, desired_phase="in_progress", timeout=60)
        require_full_acceptance(status, len(cluster), f"Smart Swarm start for cluster {cluster}")
        wait_mission(client, cluster, SMART_SWARM, timeout=60)
        assignments = cluster_assignments(client.get_swarm(), cluster)
        errors = wait_formation(
            client,
            assignments,
            cluster,
            horizontal_tolerance=args.horizontal_tolerance,
            altitude_tolerance=args.altitude_tolerance,
            minimum_timeout=args.formation_min_timeout,
            stability_samples=args.stability_samples,
            max_velocity=args.max_smart_swarm_velocity,
        )
        log(f"FORMATION CLUSTER {cluster}: {json.dumps(errors, indent=2)}")

    leader_rtl_triggered = False

    if not args.skip_reassign and all(drone_id in ids for drone_id in (1, 2, 3)):
        client.update_assignment(3, follow=2, offset_x=8.0, offset_y=6.0, offset_z=0.0, frame="body")
        wait_swarm_update(client, 3, follow=2, frame="body", timeout=20)
        wait_follow_mode(client, 3, 2, timeout=25)
        assignments = cluster_assignments(client.get_swarm(), [1, 2, 3])
        errors = wait_formation(
            client,
            assignments,
            [1, 2, 3],
            horizontal_tolerance=args.horizontal_tolerance,
            altitude_tolerance=args.altitude_tolerance,
            minimum_timeout=args.formation_min_timeout,
            stability_samples=args.stability_samples,
            max_velocity=args.max_smart_swarm_velocity,
        )
        log(f"FORMATION AFTER DRONE-3 REASSIGN: {json.dumps(errors, indent=2)}")

        command_id, _ = client.submit_command(RTL, [1], "Leader 1 RTL override")
        status = wait_for_command(client, command_id, terminal=True, timeout=120)
        require_full_acceptance(status, 1, "Leader-only RTL")
        require_full_execution(status, 1, "Leader-only RTL")
        leader_rtl_triggered = True
        time.sleep(10.0)
        telemetry = snapshot(client, [1, 2, 3])
        require(telemetry["2"]["mission"] == SMART_SWARM, f"Drone 2 left Smart Swarm unexpectedly: {telemetry['2']}")
        require(telemetry["3"]["mission"] == SMART_SWARM, f"Drone 3 left Smart Swarm unexpectedly: {telemetry['3']}")
        log(f"POST-RTL TELEMETRY CLUSTER [1, 2, 3]: {json.dumps(telemetry, indent=2)}")

        command_id, _ = client.submit_command(HOLD, [2, 3], "Stop Smart Swarm Followers Hold")
        status = wait_for_command(client, command_id, terminal=True, timeout=120)
        require(status["status"] == "completed", f"Hold command failed: {command_summary(status)}")
        require_full_acceptance(status, 2, "Hold")
        require_full_execution(status, 2, "Hold")

    land_targets = [idx for idx in ids if idx != 1] if leader_rtl_triggered else list(ids)
    command_id, _ = client.submit_command(LAND, land_targets, "Land Remaining Smart Swarm Drones")
    status = wait_for_command(client, command_id, terminal=True, timeout=180)
    require(status["status"] == "completed", f"Land command failed: {command_summary(status)}")
    require_full_acceptance(status, len(land_targets), "Land")
    require_full_execution(status, len(land_targets), "Land")

    final_telemetry = wait_idle_reset(client, ids, timeout=240)
    restored_ids = restore_assignments(client, original_assignments, timeout=30)
    if restored_ids:
        log(f"RESTORED SWARM ASSIGNMENTS: {restored_ids}")
    final_assignments = assignment_snapshot(client.get_swarm(), ids)
    require(
        final_assignments == original_assignments,
        f"Selected swarm assignments were not restored: {json.dumps(final_assignments, indent=2)}",
    )
    log(f"FINAL TELEMETRY: {json.dumps(final_telemetry, indent=2)}")
    log(f"FINAL SWARM ASSIGNMENTS: {json.dumps(final_assignments, indent=2, sort_keys=True)}")
    log("SMART SWARM VALIDATION PASSED")


if __name__ == "__main__":
    try:
        main()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP ERROR {exc.code}: {body}", file=sys.stderr)
        raise
