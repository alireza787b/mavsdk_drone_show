#!/usr/bin/env python3
"""
Deterministic mixed-mode runtime validation for the SITL fleet.

This validator exercises a higher-value operator chain than the standalone
mission-family validators:

1. Wait for a clean ready baseline
2. Patch the selected drones into one deterministic Smart Swarm cluster
3. TAKEOFF the full cluster
4. Start Smart Swarm on the full cluster and verify formation
5. Reassign one follower in flight and verify the updated formation
6. Generate/process a short Swarm Trajectory profile for the leader only
7. Override just the leader into Swarm Trajectory while followers remain in
   Smart Swarm
8. Interrupt the leader with HOLD, then dispatch PRECISION_MOVE to that leader
9. Verify followers reform around the leader after both overrides
10. LAND the cluster, restore swarm assignments, restore trajectory sources

This validates the real mixed-mode command/override contract we expect from a
dashboard operator:

- one live cluster
- shared command pipeline
- leader mission supersession
- follower persistence in Smart Swarm
- runtime config mutation and recovery
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.gcs_api_routes import (
    GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE,
    GCS_CONFIG_SWARM_ROUTE,
)
from tools.runtime_validation_support import normalize_drone_ids, parse_csv_drone_ids, write_json_report
from tools.validate_actions_runtime import (
    ApiClient as BaseApiClient,
    HOLD,
    LAND,
    PRECISION_MOVE,
    TAKEOFF,
    _is_safe_interrupted_terminal_status,
    command_summary,
    get_local_snapshots,
    require,
    require_full_acceptance,
    require_full_execution,
    wait_altitude_gain,
    wait_api_ready,
    wait_fleet_ready,
    wait_for,
    wait_for_command,
    wait_for_live_launch_readiness,
    wait_hold_ready,
    wait_idle_subset,
    wait_local_position_offset_at_least,
    wait_precision_move_settle,
)
from tools.validate_smart_swarm_runtime import (
    SMART_SWARM,
    assignment_snapshot,
    build_clusters,
    cluster_assignments,
    restore_assignments,
    wait_formation,
    wait_mission,
)
from tools.validate_swarm_trajectory_runtime import (
    GCS_SWARM_TRAJECTORY_PROCESS_ROUTE,
    GCS_SWARM_TRAJECTORY_STATUS_ROUTE,
    SWARM_TRAJECTORY,
    recommend_short_profile_entry_delay,
    restore_raw_profiles,
    snapshot_raw_profiles,
    write_short_validation_profiles,
)


class ApiClient(BaseApiClient):
    """Action-validator client plus the swarm patch surface required here."""

    def patch_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')}") from exc

    def get_swarm(self) -> list[dict[str, Any]]:
        payload = self.get_json(GCS_CONFIG_SWARM_ROUTE)
        if isinstance(payload, dict) and "assignments" in payload:
            payload = payload["assignments"]
        require(isinstance(payload, list), f"Unexpected swarm payload: {payload!r}")
        return payload

    def update_assignment(self, hw_id: int, **kwargs: Any) -> dict[str, Any]:
        payload = {
            key: value
            for key, value in kwargs.items()
            if key in {"follow", "offset_x", "offset_y", "offset_z", "frame"} and value is not None
        }
        response = self.patch_json(
            GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE.format(hw_id=int(hw_id)),
            payload,
        )
        return response.get("assignment") or payload


def resolve_selected_ids(args: argparse.Namespace) -> list[int]:
    if args.drone_ids:
        return normalize_drone_ids(args.drone_ids)
    if args.drones:
        return parse_csv_drone_ids(args.drones)
    return normalize_drone_ids([1, 2, 3])


def build_demo_swarm_assignments(ids: list[int], *, spacing_m: float) -> dict[int, dict[str, Any]]:
    selected = normalize_drone_ids(ids)
    require(len(selected) >= 3, "Integrated mixed-mode validation requires at least three drones.")

    leader_id = int(selected[0])
    offsets = [
        (0.0, spacing_m),
        (0.0, -spacing_m),
        (-spacing_m, 0.0),
        (spacing_m, 0.0),
        (-spacing_m, spacing_m),
        (-spacing_m, -spacing_m),
    ]

    assignments: dict[int, dict[str, Any]] = {
        leader_id: {
            "follow": 0,
            "offset_x": 0.0,
            "offset_y": 0.0,
            "offset_z": 0.0,
            "frame": "body",
        }
    }

    for index, drone_id in enumerate(selected[1:]):
        forward_m, right_m = offsets[index % len(offsets)]
        ring_scale = 1 + (index // len(offsets))
        assignments[int(drone_id)] = {
            "follow": leader_id,
            "offset_x": round(forward_m * ring_scale, 2),
            "offset_y": round(right_m * ring_scale, 2),
            "offset_z": 0.0,
            "frame": "body",
        }

    return assignments


def build_reassignment_patch(ids: list[int], *, reassign_offset_m: float) -> tuple[int, dict[str, Any]]:
    selected = normalize_drone_ids(ids)
    require(len(selected) >= 3, "Integrated mixed-mode validation requires at least three drones.")
    leader_id = int(selected[0])
    follower_id = int(selected[-1])
    patch = {
        "follow": leader_id,
        "offset_x": float(reassign_offset_m),
        "offset_y": float(reassign_offset_m),
        "offset_z": 0.0,
        "frame": "ned",
    }
    return follower_id, patch


def apply_assignments(
    client: ApiClient,
    expected_assignments: dict[int, dict[str, Any]],
    *,
    timeout: int = 30,
) -> list[int]:
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

    wait_for(_ready, label=f"swarm assignments applied for drones {changed_ids}", timeout=timeout, interval=1.0)
    return changed_ids


def wait_active_missions(
    client: ApiClient,
    *,
    leader_id: int,
    follower_ids: list[int],
    timeout: int = 90,
) -> dict[str, dict[str, Any]]:
    def _ready():
        telemetry = client.get_telemetry()
        required_ids = [leader_id, *follower_ids]
        if not all(str(drone_id) in telemetry for drone_id in required_ids):
            return False

        leader = telemetry[str(leader_id)]
        if int(leader.get("mission", 0) or 0) != SWARM_TRAJECTORY or int(leader.get("state", 0) or 0) != 2 or not bool(leader.get("is_armed")):
            return False

        for follower_id in follower_ids:
            follower = telemetry[str(follower_id)]
            if int(follower.get("mission", 0) or 0) != SMART_SWARM or int(follower.get("state", 0) or 0) != 2 or not bool(follower.get("is_armed")):
                return False

        return {str(drone_id): telemetry[str(drone_id)] for drone_id in required_ids}

    return wait_for(
        _ready,
        label=f"leader {leader_id} in Swarm Trajectory while followers {follower_ids} remain in Smart Swarm",
        timeout=timeout,
        interval=1.0,
    )


def wait_followers_remain_in_swarm(
    client: ApiClient,
    follower_ids: list[int],
    *,
    timeout: int = 60,
) -> dict[str, dict[str, Any]]:
    def _ready():
        telemetry = client.get_telemetry()
        if not all(str(drone_id) in telemetry for drone_id in follower_ids):
            return False

        for follower_id in follower_ids:
            follower = telemetry[str(follower_id)]
            if int(follower.get("mission", 0) or 0) != SMART_SWARM or int(follower.get("state", 0) or 0) != 2 or not bool(follower.get("is_armed")):
                return False
        return {str(drone_id): telemetry[str(drone_id)] for drone_id in follower_ids}

    return wait_for(
        _ready,
        label=f"followers {follower_ids} remain active in Smart Swarm",
        timeout=timeout,
        interval=1.0,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate integrated mixed-mode runtime behavior against a live GCS/SITL stack.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5030", help="GCS API base URL")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Runtime repo root used for short-profile trajectory staging")
    parser.add_argument("--drones", default=None, help="Comma-separated drone hardware IDs to validate")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=None, help="Space-separated drone hardware IDs to validate")
    parser.add_argument("--takeoff-min-gain", type=float, default=4.0, help="Minimum altitude gain required after TAKEOFF")
    parser.add_argument("--formation-horizontal-tolerance", type=float, default=8.0, help="Allowed follower horizontal error during mixed-mode tracking")
    parser.add_argument("--formation-altitude-tolerance", type=float, default=2.0, help="Allowed follower altitude error during mixed-mode tracking")
    parser.add_argument("--formation-min-timeout", type=int, default=45, help="Minimum time budget for each formation settle gate")
    parser.add_argument("--max-smart-swarm-velocity", type=float, default=3.0, help="Expected Smart Swarm max velocity used for timeout sizing")
    parser.add_argument("--stability-samples", type=int, default=2, help="Consecutive in-tolerance samples required for formation gates")
    parser.add_argument("--follower-spacing-m", type=float, default=8.0, help="Deterministic initial body-frame follower spacing around the leader")
    parser.add_argument("--reassign-offset-m", type=float, default=6.0, help="NED offset applied during the in-flight follower reassignment drill")
    parser.add_argument("--trajectory-altitude-gain", type=float, default=12.0, help="Relative mission altitude for the generated leader trajectory")
    parser.add_argument("--trajectory-entry-delay", type=float, default=8.0, help="Default route-entry time before the helper adjusts it for formation requirements")
    parser.add_argument("--trajectory-leg-duration", type=float, default=14.0, help="Per-leg duration for the generated leader trajectory")
    parser.add_argument("--precision-move-north", type=float, default=4.0, help="Leader precision-move north offset in metres")
    parser.add_argument("--precision-move-east", type=float, default=2.0, help="Leader precision-move east offset in metres")
    parser.add_argument("--precision-move-up", type=float, default=0.5, help="Leader precision-move up offset in metres")
    parser.add_argument("--precision-move-speed", type=float, default=1.0, help="Leader precision-move speed in metres per second")
    parser.add_argument("--precision-move-tolerance", type=float, default=0.9, help="Leader precision-move settle tolerance in metres")
    parser.add_argument("--precision-move-start-threshold", type=float, default=1.0, help="Leader minimum displacement before treating Precision Move as active")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional path to write the final validation summary JSON")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ids = resolve_selected_ids(args)
    client = ApiClient(args.base_url)
    leader_id = int(ids[0])
    follower_ids = [int(drone_id) for drone_id in ids[1:]]

    results: dict[str, Any] = {
        "base_url": args.base_url,
        "repo_root": str(args.repo_root),
        "drone_ids": ids,
        "leader_id": leader_id,
        "follower_ids": follower_ids,
    }

    original_assignments: dict[int, dict[str, Any]] | None = None
    raw_profile_snapshot: dict[str, Any] | None = None
    exit_code = 0

    try:
        results["health"] = wait_api_ready(client, timeout=60)
        baseline = wait_fleet_ready(client, ids, timeout=120)
        baseline_altitudes = {str(idx): float(baseline[str(idx)]["position_alt"]) for idx in ids}
        results["baseline_telemetry"] = baseline
        results["baseline_altitudes"] = baseline_altitudes
        results["live_launch_readiness"] = wait_for_live_launch_readiness(client, ids, timeout=90)

        swarm = client.get_swarm()
        original_assignments = assignment_snapshot(swarm, ids)
        require(
            len(original_assignments) == len(ids),
            f"Missing saved swarm assignments for selected drones {ids}: {json.dumps(original_assignments, indent=2)}",
        )
        results["original_assignments"] = original_assignments

        target_assignments = build_demo_swarm_assignments(ids, spacing_m=float(args.follower_spacing_m))
        changed_ids = apply_assignments(client, target_assignments)
        results["target_assignments"] = target_assignments
        results["assignment_patch_ids"] = changed_ids
        clusters = build_clusters(client.get_swarm(), set(ids))
        require(clusters == [ids], f"Expected one deterministic cluster {ids}, got {clusters}")
        results["clusters"] = clusters

        takeoff = client.submit_command(TAKEOFF, ids, "Integrated Validation Takeoff")
        takeoff_status = wait_for_command(client, takeoff["command_id"], terminal=True, timeout=150)
        require(takeoff_status["status"] == "completed", f"Takeoff failed: {command_summary(takeoff_status)}")
        require_full_acceptance(takeoff_status, len(ids), "Integrated Takeoff")
        require_full_execution(takeoff_status, len(ids), "Integrated Takeoff")
        results["takeoff"] = command_summary(takeoff_status)
        wait_altitude_gain(client, ids, baseline_altitudes, args.takeoff_min_gain, timeout=120)

        smart_swarm = client.submit_command(SMART_SWARM, ids, "Integrated Validation Smart Swarm Start")
        smart_swarm_status = wait_for_command(client, smart_swarm["command_id"], desired_phase="in_progress", timeout=60)
        require_full_acceptance(smart_swarm_status, len(ids), "Integrated Smart Swarm start")
        wait_mission(client, ids, SMART_SWARM, timeout=60)

        current_assignments = cluster_assignments(client.get_swarm(), ids)
        results["initial_formation"] = wait_formation(
            client,
            current_assignments,
            ids,
            horizontal_tolerance=float(args.formation_horizontal_tolerance),
            altitude_tolerance=float(args.formation_altitude_tolerance),
            minimum_timeout=int(args.formation_min_timeout),
            stability_samples=int(args.stability_samples),
            max_velocity=float(args.max_smart_swarm_velocity),
        )

        reassign_target_id, reassign_patch = build_reassignment_patch(ids, reassign_offset_m=float(args.reassign_offset_m))
        client.update_assignment(reassign_target_id, **reassign_patch)
        wait_for(
            lambda: assignment_snapshot(client.get_swarm(), [reassign_target_id]).get(reassign_target_id) == reassign_patch,
            label=f"follower {reassign_target_id} reassignment saved",
            timeout=20,
            interval=1.0,
        )
        current_assignments = cluster_assignments(client.get_swarm(), ids)
        results["reassignment"] = {
            "target_hw_id": reassign_target_id,
            "patch": reassign_patch,
            "formation": wait_formation(
                client,
                current_assignments,
                ids,
                horizontal_tolerance=float(args.formation_horizontal_tolerance),
                altitude_tolerance=float(args.formation_altitude_tolerance),
                minimum_timeout=int(args.formation_min_timeout),
                stability_samples=int(args.stability_samples),
                max_velocity=float(args.max_smart_swarm_velocity),
            ),
        }

        max_offset = max(
            math.hypot(float(assignment.get("offset_x", 0.0) or 0.0), float(assignment.get("offset_y", 0.0) or 0.0))
            for assignment in current_assignments
            if int(assignment.get("follow", 0) or 0) > 0
        )
        entry_delay_s = recommend_short_profile_entry_delay(
            default_entry_delay_s=float(args.trajectory_entry_delay),
            relative_altitude_m=float(args.trajectory_altitude_gain),
            max_horizontal_offset_m=max_offset,
        )
        raw_profile_snapshot = snapshot_raw_profiles(args.repo_root, [leader_id])
        results["raw_profile_snapshot"] = raw_profile_snapshot
        prepared_profiles = write_short_validation_profiles(
            args.repo_root,
            baseline,
            [leader_id],
            relative_altitude_m=float(args.trajectory_altitude_gain),
            entry_delay_s=entry_delay_s,
            leg_duration_s=float(args.trajectory_leg_duration),
        )
        results["prepared_short_profiles"] = prepared_profiles
        results["prepared_entry_delay_s"] = entry_delay_s

        status_before = client.get_json(GCS_SWARM_TRAJECTORY_STATUS_ROUTE)
        results["trajectory_status_before"] = status_before
        process_result = client.post_json(
            GCS_SWARM_TRAJECTORY_PROCESS_ROUTE,
            {"force_clear": False, "auto_reload": True},
        )
        require(process_result.get("success") is True, f"Swarm Trajectory processing failed: {process_result}")
        results["trajectory_process_result"] = process_result
        status_after = client.get_json(GCS_SWARM_TRAJECTORY_STATUS_ROUTE)
        require(status_after.get("success") is True, f"Swarm Trajectory status failed: {status_after}")
        require(
            status_after["status"]["cluster_summary"]["all_clusters_ready"] is True,
            f"Swarm Trajectory cluster processing not ready: {status_after}",
        )
        results["trajectory_status_after"] = status_after

        trajectory = client.submit_command(
            SWARM_TRAJECTORY,
            [leader_id],
            "Integrated Validation Leader Trajectory",
            trigger_time=0,
        )
        trajectory_in_progress = wait_for_command(  # command tracker gate
            client,
            trajectory["command_id"],
            desired_phase="in_progress",
            timeout=120,
        )
        results["leader_trajectory_start"] = command_summary(trajectory_in_progress)

        results["mixed_mode_active"] = wait_active_missions(
            client,
            leader_id=leader_id,
            follower_ids=follower_ids,
            timeout=120,
        )
        current_assignments = cluster_assignments(client.get_swarm(), ids)
        results["mixed_mode_formation"] = wait_formation(
            client,
            current_assignments,
            ids,
            horizontal_tolerance=float(args.formation_horizontal_tolerance),
            altitude_tolerance=float(args.formation_altitude_tolerance),
            minimum_timeout=int(args.formation_min_timeout),
            stability_samples=int(args.stability_samples),
            max_velocity=float(args.max_smart_swarm_velocity),
        )

        leader_hold = client.submit_command(HOLD, [leader_id], "Integrated Validation Leader Hold Override")
        leader_hold_status = wait_for_command(client, leader_hold["command_id"], terminal=True, timeout=120)
        require(leader_hold_status["status"] == "completed", f"Leader HOLD failed: {command_summary(leader_hold_status)}")
        require_full_acceptance(leader_hold_status, 1, "Integrated leader HOLD")
        require_full_execution(leader_hold_status, 1, "Integrated leader HOLD")
        results["leader_hold"] = command_summary(leader_hold_status)

        interrupted_trajectory = wait_for_command(client, trajectory["command_id"], terminal=True, timeout=120)
        require(
            _is_safe_interrupted_terminal_status(interrupted_trajectory),
            f"Leader trajectory did not end safely after HOLD override: {command_summary(interrupted_trajectory)}",
        )
        results["leader_trajectory_terminal"] = command_summary(interrupted_trajectory)
        results["post_hold_leader"] = wait_hold_ready(client, [leader_id], baseline_altitudes, args.takeoff_min_gain, timeout=120)
        results["post_hold_followers"] = wait_followers_remain_in_swarm(client, follower_ids, timeout=60)

        precision_start = get_local_snapshots(client, client.get_telemetry(), [leader_id])
        precision_move_payload = {
            "frame": "ned",
            "translation_m": {
                "north": float(args.precision_move_north),
                "east": float(args.precision_move_east),
                "up": float(args.precision_move_up),
            },
            "yaw": {
                "mode": "hold_current",
            },
            "speed_m_s": float(args.precision_move_speed),
            "timeout_sec": 90.0,
        }
        precision_move = client.submit_command(
            PRECISION_MOVE,
            [leader_id],
            "Integrated Validation Leader Precision Move",
            extra_fields={"precision_move": precision_move_payload},
        )
        results["precision_move_start_displacement"] = wait_local_position_offset_at_least(
            client,
            client.get_telemetry(),
            [leader_id],
            precision_start,
            min_horizontal_delta_m=float(args.precision_move_start_threshold),
            timeout=90,
        )
        precision_move_status = wait_for_command(client, precision_move["command_id"], terminal=True, timeout=180)
        require(precision_move_status["status"] == "completed", f"Leader Precision Move failed: {command_summary(precision_move_status)}")
        require_full_acceptance(precision_move_status, 1, "Integrated leader Precision Move")
        require_full_execution(precision_move_status, 1, "Integrated leader Precision Move")
        results["leader_precision_move"] = command_summary(precision_move_status)
        results["precision_move_end"] = wait_precision_move_settle(
            client,
            client.get_telemetry(),
            [leader_id],
            precision_start,
            north_m=float(args.precision_move_north),
            east_m=float(args.precision_move_east),
            up_m=float(args.precision_move_up),
            tolerance_m=float(args.precision_move_tolerance),
            timeout=90,
        )
        current_assignments = cluster_assignments(client.get_swarm(), ids)
        results["post_precision_move_followers"] = wait_followers_remain_in_swarm(client, follower_ids, timeout=60)
        results["post_precision_move_formation"] = wait_formation(
            client,
            current_assignments,
            ids,
            horizontal_tolerance=float(args.formation_horizontal_tolerance),
            altitude_tolerance=float(args.formation_altitude_tolerance),
            minimum_timeout=int(args.formation_min_timeout),
            stability_samples=int(args.stability_samples),
            max_velocity=float(args.max_smart_swarm_velocity),
        )

        land = client.submit_command(LAND, ids, "Integrated Validation Land Cluster")
        land_status = wait_for_command(client, land["command_id"], terminal=True, timeout=240)
        require(land_status["status"] == "completed", f"Integrated LAND failed: {command_summary(land_status)}")
        require_full_acceptance(land_status, len(ids), "Integrated LAND")
        require_full_execution(land_status, len(ids), "Integrated LAND")
        results["land"] = command_summary(land_status)
        results["final_telemetry"] = wait_idle_subset(client, ids, timeout=240)
        results["result"] = "PASS"
    except Exception as exc:
        exit_code = 1
        results["result"] = "FAIL"
        results["error"] = str(exc)
        try:
            telemetry = client.get_telemetry()
            armed_ids = [drone_id for drone_id in ids if telemetry.get(str(drone_id), {}).get("is_armed")]
            if armed_ids:
                cleanup_land = client.submit_command(LAND, armed_ids, "Integrated Validation Cleanup Land")
                cleanup_status = wait_for_command(client, cleanup_land["command_id"], terminal=True, timeout=240)
                results["cleanup"] = {
                    "land": command_summary(cleanup_status),
                    "telemetry": wait_idle_subset(client, ids, timeout=240),
                }
            else:
                results["cleanup"] = {"status": "not_needed"}
        except Exception as cleanup_exc:
            results["cleanup"] = {"status": "failed", "error": str(cleanup_exc)}
    finally:
        if original_assignments is not None:
            try:
                restored_ids = restore_assignments(client, original_assignments, timeout=30)
                if restored_ids:
                    results.setdefault("post_cleanup", {})["restored_assignments"] = restored_ids
            except Exception as exc:
                results.setdefault("post_cleanup", {})["restore_assignments_error"] = str(exc)

        if raw_profile_snapshot is not None:
            try:
                results.setdefault("post_cleanup", {})["restore_raw_profiles"] = restore_raw_profiles(raw_profile_snapshot)
            except Exception as exc:
                results.setdefault("post_cleanup", {})["restore_raw_profiles_error"] = str(exc)

    write_json_report(args.json_output, results)
    print(json.dumps(results, indent=2, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
