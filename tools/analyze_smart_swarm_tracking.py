#!/usr/bin/env python3
"""
Capture and plot Smart Swarm follower tracking against expected formation offsets.

The tool uses the same command/API path the dashboard uses:
- TAKEOFF
- SMART_SWARM
- leader PRECISION_MOVE commands in NED and BODY frames
- LAND

High-rate leader/follower state is sampled from each drone's dedicated Smart Swarm
WebSocket so the resulting plots reflect the runtime transport path, not the lower-rate
operator telemetry aggregate.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import aiohttp
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing Python dependency 'aiohttp'. Run this tool from the project venv "
        "(for example `venv/bin/python3 tools/analyze_smart_swarm_tracking.py ...`) "
        "or install requirements.txt into the active interpreter."
    ) from exc

try:
    import matplotlib
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Missing Python dependency 'matplotlib'. Run this tool from the project venv "
        "(for example `venv/bin/python3 tools/analyze_smart_swarm_tracking.py ...`) "
        "or install requirements.txt into the active interpreter."
    ) from exc

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PRECISION_MOVE = 112
TAKEOFF = 10
SMART_SWARM = 2
LAND = 101


@dataclass
class TrackingSample:
    stage: str
    sample_time_s: float
    leader_seq: int
    follower_seq: int
    leader_yaw_deg: float
    assignment_frame: str
    expected_n: float
    expected_e: float
    expected_d: float
    actual_n: float
    actual_e: float
    actual_d: float
    horizontal_error: float
    altitude_error: float
    leader_sample_age_ms: int
    follower_sample_age_ms: int
    leader_world_n: float
    leader_world_e: float
    leader_world_d: float
    follower_world_n: float
    follower_world_e: float
    follower_world_d: float
    expected_world_n: float
    expected_world_e: float
    expected_world_d: float


def log(message: str) -> None:
    print(message, flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


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
            float(leader.get("yaw_deg", leader.get("yaw", 0.0)) or 0.0),
        )
    else:
        expected_n, expected_e = float(entry["offset_x"]), float(entry["offset_y"])

    altitude_delta = float(follower["position_alt"]) - float(leader["position_alt"])
    expected_altitude = float(entry.get("offset_z", 0.0))
    return {
        "expected_n": expected_n,
        "expected_e": expected_e,
        "horizontal_error": math.hypot(follower_n - expected_n, follower_e - expected_e),
        "expected_altitude_delta": expected_altitude,
        "altitude_error": abs(altitude_delta - expected_altitude),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Smart Swarm follower tracking quality.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5030", help="GCS API base URL")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=[1, 2, 3, 4], help="Drone IDs to use for the cluster")
    parser.add_argument("--leader-id", type=int, default=1, help="Leader drone ID to move")
    parser.add_argument("--follower-id", type=int, default=2, help="Follower drone ID to track")
    parser.add_argument("--spacing-m", type=float, default=6.0, help="Body-frame lateral spacing for demo followers")
    parser.add_argument("--formation-horizontal-tolerance", type=float, default=1.5)
    parser.add_argument("--formation-altitude-tolerance", type=float, default=0.6)
    parser.add_argument("--stability-samples", type=int, default=3)
    parser.add_argument("--max-smart-swarm-velocity", type=float, default=3.0)
    parser.add_argument("--takeoff-min-gain", type=float, default=4.0)
    parser.add_argument("--sample-rate-hz", type=float, default=10.0)
    parser.add_argument("--jog-step-m", type=float, default=1.0, help="Distance for each repeated jog-like precision-move step")
    parser.add_argument("--pre-jog-settle-sec", type=float, default=4.0, help="Extra dwell after formation lock before leader jogs start")
    parser.add_argument("--post-command-settle-sec", type=float, default=3.0, help="Observe formation for this long after each leader command")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for JSON/CSV/plots")
    return parser.parse_args()


def build_demo_swarm_assignments(ids: list[int], spacing_m: float) -> dict[int, dict[str, Any]]:
    selected = sorted({int(drone_id) for drone_id in ids})
    require(len(selected) >= 3, "Tracking analysis requires at least three drones.")
    leader_id = int(selected[0])
    follower_offsets = [
        {"follow": leader_id, "offset_x": 0.0, "offset_y": spacing_m, "offset_z": 0.0, "frame": "body"},
        {"follow": leader_id, "offset_x": 0.0, "offset_y": -spacing_m, "offset_z": 0.0, "frame": "body"},
        {"follow": leader_id, "offset_x": -spacing_m, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
        {"follow": leader_id, "offset_x": spacing_m, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"},
    ]
    assignments: dict[int, dict[str, Any]] = {
        leader_id: {"follow": 0, "offset_x": 0.0, "offset_y": 0.0, "offset_z": 0.0, "frame": "body"}
    }
    for index, drone_id in enumerate(selected[1:]):
        assignments[int(drone_id)] = dict(follower_offsets[index % len(follower_offsets)])
    return assignments


def canonical_assignment(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "follow": int(entry.get("follow", 0) or 0),
        "offset_x": float(entry.get("offset_x", 0.0) or 0.0),
        "offset_y": float(entry.get("offset_y", 0.0) or 0.0),
        "offset_z": float(entry.get("offset_z", 0.0) or 0.0),
        "frame": str(entry.get("frame", "body") or "body").lower(),
    }


def assignment_patch_payload(entry: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "follow": int(entry.get("follow", 0) or 0),
    }

    if "offset_x" in entry:
        payload["offset_x"] = float(entry.get("offset_x", 0.0) or 0.0)
    if "offset_y" in entry:
        payload["offset_y"] = float(entry.get("offset_y", 0.0) or 0.0)
    if "offset_z" in entry:
        payload["offset_z"] = float(entry.get("offset_z", 0.0) or 0.0)
    if "frame" in entry and entry.get("frame") is not None:
        payload["frame"] = str(entry.get("frame", "body") or "body").lower()

    return payload


def assignment_semantic_snapshot(assignments: list[dict[str, Any]], ids) -> dict[int, dict[str, Any]]:
    id_set = {int(idx) for idx in ids}
    return {
        int(entry["hw_id"]): canonical_assignment(entry)
        for entry in assignments
        if int(entry["hw_id"]) in id_set
    }


def assignment_payload_snapshot(assignments: list[dict[str, Any]], ids) -> dict[int, dict[str, Any]]:
    id_set = {int(idx) for idx in ids}
    return {
        int(entry["hw_id"]): assignment_patch_payload(entry)
        for entry in assignments
        if int(entry["hw_id"]) in id_set
    }


def apply_assignments(client: Any, expected_assignments: dict[int, dict[str, Any]], *, timeout: int = 30) -> list[int]:
    expected_semantic = {
        int(hw_id): canonical_assignment(entry)
        for hw_id, entry in expected_assignments.items()
    }
    current_assignments = assignment_semantic_snapshot(client.get_swarm(), expected_assignments.keys())
    changed_ids: list[int] = []

    for hw_id, expected in expected_assignments.items():
        if current_assignments.get(int(hw_id)) == expected_semantic[int(hw_id)]:
            continue
        client.patch_json(
            f"/api/v1/config/swarm/assignments/{int(hw_id)}",
            assignment_patch_payload(expected),
        )
        changed_ids.append(int(hw_id))

    if not changed_ids:
        return []

    deadline = time.time() + timeout
    while time.time() < deadline:
        current = assignment_semantic_snapshot(client.get_swarm(), expected_assignments.keys())
        if all(current.get(int(hw_id)) == expected_semantic[int(hw_id)] for hw_id in expected_assignments):
            return changed_ids
        time.sleep(1.0)
    raise RuntimeError(f"Timed out applying swarm assignments for drones {changed_ids}")


def build_precision_move_payload(frame: str, *, north: float = 0.0, east: float = 0.0, forward: float = 0.0, right: float = 0.0, up: float = 0.0) -> dict[str, Any]:
    translation: dict[str, float]
    if frame == "body":
        translation = {"forward": float(forward), "right": float(right), "up": float(up)}
    else:
        translation = {"north": float(north), "east": float(east), "up": float(up)}

    return {
        "precision_move": {
            "frame": frame,
            "translation_m": translation,
            "yaw": {"mode": "hold_current"},
            "speed_m_s": 1.0,
            "timeout_sec": 90.0,
        }
    }


def build_live_jog_sequence(step_m: float) -> list[tuple[str, dict[str, Any]]]:
    step = float(step_m)
    return [
        ("jog_body_forward_1", build_precision_move_payload("body", forward=step)),
        ("jog_body_forward_2", build_precision_move_payload("body", forward=step)),
        ("jog_body_right_1", build_precision_move_payload("body", right=step)),
        ("jog_ned_north_1", build_precision_move_payload("ned", north=step)),
        ("jog_ned_east_1", build_precision_move_payload("ned", east=step)),
    ]


def compute_tracking_sample(
    stage: str,
    leader_state: dict[str, Any],
    follower_state: dict[str, Any],
    assignment: dict[str, Any],
    sample_time_s: float,
    reference_origin: dict[str, float],
) -> TrackingSample:
    actual_n, actual_e = latlon_to_ne(
        follower_state["position_lat"],
        follower_state["position_long"],
        leader_state["position_lat"],
        leader_state["position_long"],
    )
    result = formation_error(leader_state, follower_state, assignment)
    actual_d = float(follower_state["position_alt"]) - float(leader_state["position_alt"])
    leader_world_n, leader_world_e = latlon_to_ne(
        leader_state["position_lat"],
        leader_state["position_long"],
        reference_origin["lat"],
        reference_origin["lon"],
    )
    follower_world_n, follower_world_e = latlon_to_ne(
        follower_state["position_lat"],
        follower_state["position_long"],
        reference_origin["lat"],
        reference_origin["lon"],
    )
    leader_world_d = float(reference_origin["alt"]) - float(leader_state["position_alt"])
    follower_world_d = float(reference_origin["alt"]) - float(follower_state["position_alt"])
    expected_world_n = leader_world_n + float(result["expected_n"])
    expected_world_e = leader_world_e + float(result["expected_e"])
    expected_world_d = leader_world_d + float(result["expected_altitude_delta"])
    return TrackingSample(
        stage=stage,
        sample_time_s=sample_time_s,
        leader_seq=int(leader_state.get("stream_seq", 0) or 0),
        follower_seq=int(follower_state.get("stream_seq", 0) or 0),
        leader_yaw_deg=float(leader_state.get("yaw_deg", leader_state.get("yaw", 0.0)) or 0.0),
        assignment_frame=str(assignment.get("frame", "body")),
        expected_n=float(result["expected_n"]),
        expected_e=float(result["expected_e"]),
        expected_d=float(result["expected_altitude_delta"]),
        actual_n=float(actual_n),
        actual_e=float(actual_e),
        actual_d=float(actual_d),
        horizontal_error=float(result["horizontal_error"]),
        altitude_error=float(result["altitude_error"]),
        leader_sample_age_ms=int(leader_state.get("sample_age_ms", 0) or 0),
        follower_sample_age_ms=int(follower_state.get("sample_age_ms", 0) or 0),
        leader_world_n=float(leader_world_n),
        leader_world_e=float(leader_world_e),
        leader_world_d=float(leader_world_d),
        follower_world_n=float(follower_world_n),
        follower_world_e=float(follower_world_e),
        follower_world_d=float(follower_world_d),
        expected_world_n=float(expected_world_n),
        expected_world_e=float(expected_world_e),
        expected_world_d=float(expected_world_d),
    )


async def stream_swarm_state(ip: str, sink: dict[str, Any], key: str, stop_event: asyncio.Event) -> None:
    drone_api_port = int(os.getenv("MDS_DRONE_API_PORT", "7070"))
    url = f"ws://{ip}:{drone_api_port}/ws/swarm-state"
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=5, sock_read=None)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.ws_connect(url, heartbeat=15) as websocket:
            while not stop_event.is_set():
                message = await websocket.receive()
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = message.json()
                    if isinstance(payload, dict) and not payload.get("error"):
                        sink[key] = payload
                elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    return
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError(f"Swarm-state websocket error for {key}: {websocket.exception()}")


async def collect_tracking_samples(
    *,
    sample_rate_hz: float,
    stage_ref: dict[str, str],
    leader_key: str,
    follower_key: str,
    latest_states: dict[str, Any],
    assignment_ref: dict[str, Any],
    reference_origin: dict[str, float],
    stop_event: asyncio.Event,
    records: list[TrackingSample],
) -> None:
    interval = 1.0 / max(1.0, float(sample_rate_hz))
    while not stop_event.is_set():
        leader_state = latest_states.get(leader_key)
        follower_state = latest_states.get(follower_key)
        if leader_state and follower_state:
            records.append(
                compute_tracking_sample(
                    stage=stage_ref["name"],
                    leader_state=leader_state,
                    follower_state=follower_state,
                    assignment=assignment_ref["value"],
                    sample_time_s=time.monotonic(),
                    reference_origin=reference_origin,
                )
            )
        await asyncio.sleep(interval)


def write_tracking_csv(path: Path, records: list[TrackingSample]) -> None:
    if not records:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(asdict(records[0]).keys()))
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def plot_tracking(records: list[TrackingSample], output_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not records:
        return {}

    base_time = records[0].sample_time_s
    times = [record.sample_time_s - base_time for record in records]
    stage_order = list(dict.fromkeys(record.stage for record in records))
    cmap = plt.get_cmap("tab10")
    stage_colors = {
        stage: cmap(index % 10)
        for index, stage in enumerate(stage_order)
    }

    def stage_boundaries():
        last_stage = records[0].stage
        for index, record in enumerate(records[1:], start=1):
            if record.stage != last_stage:
                yield times[index], record.stage
                last_stage = record.stage

    paths: dict[str, str] = {}

    fig, axes = plt.subplots(4, 1, figsize=(12, 13), sharex=True)
    axes[0].plot(times, [record.actual_n for record in records], label="actual N", linewidth=1.8)
    axes[0].plot(times, [record.expected_n for record in records], label="expected N", linestyle="--", linewidth=1.2)
    axes[0].set_ylabel("North error frame (m)")
    axes[0].legend(loc="upper right")

    axes[1].plot(times, [record.actual_e for record in records], label="actual E", linewidth=1.8)
    axes[1].plot(times, [record.expected_e for record in records], label="expected E", linestyle="--", linewidth=1.2)
    axes[1].set_ylabel("East error frame (m)")
    axes[1].legend(loc="upper right")

    axes[2].plot(times, [record.actual_d for record in records], label="actual D", linewidth=1.8)
    axes[2].plot(times, [record.expected_d for record in records], label="expected D", linestyle="--", linewidth=1.2)
    axes[2].set_ylabel("Down delta (m)")
    axes[2].legend(loc="upper right")

    axes[3].plot(times, [record.horizontal_error for record in records], label="horizontal error", linewidth=1.8)
    axes[3].plot(times, [record.altitude_error for record in records], label="altitude error", linewidth=1.4)
    axes[3].set_ylabel("Error (m)")
    axes[3].set_xlabel("Time (s)")
    axes[3].legend(loc="upper right")

    for axis in axes:
        axis.grid(True, alpha=0.25)
        for boundary_time, stage_name in stage_boundaries():
            axis.axvline(boundary_time, color="#6b7280", linestyle=":", linewidth=0.8, alpha=0.7)
            axis.text(boundary_time + 0.15, axis.get_ylim()[1] * 0.92, stage_name, rotation=90, fontsize=8, va="top")

    fig.tight_layout()
    tracking_path = output_dir / "smart_swarm_tracking_timeseries.png"
    fig.savefig(tracking_path, dpi=180)
    plt.close(fig)
    paths["timeseries"] = str(tracking_path)

    fig, ax = plt.subplots(figsize=(8, 8))
    for index, stage in enumerate(stage_order):
        stage_records = [record for record in records if record.stage == stage]
        label_actual = "actual follower track" if index == 0 else None
        label_expected = "expected follower track" if index == 0 else None
        ax.plot(
            [record.actual_e for record in stage_records],
            [record.actual_n for record in stage_records],
            linewidth=1.8,
            color="#2563eb",
            label=label_actual,
        )
        ax.plot(
            [record.expected_e for record in stage_records],
            [record.expected_n for record in stage_records],
            linestyle="--",
            linewidth=1.2,
            color=stage_colors[stage],
            label=stage if index > 0 else f"{stage} (expected)",
        )
        ax.scatter(
            [stage_records[0].actual_e, stage_records[-1].actual_e],
            [stage_records[0].actual_n, stage_records[-1].actual_n],
            s=18,
            alpha=0.85,
            color=stage_colors[stage],
            marker="o",
        )
    ax.set_xlabel("East (m)")
    ax.set_ylabel("North (m)")
    ax.set_title("Follower Relative Track vs Expected Offset")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    path_relative = output_dir / "smart_swarm_tracking_relative.png"
    fig.savefig(path_relative, dpi=180)
    plt.close(fig)
    paths["relative"] = str(path_relative)

    fig, ax = plt.subplots(figsize=(9, 8))
    ax.plot(
        [record.leader_world_e for record in records],
        [record.leader_world_n for record in records],
        label="leader path",
        linewidth=1.8,
        color="#111827",
    )
    ax.plot(
        [record.expected_world_e for record in records],
        [record.expected_world_n for record in records],
        label="expected follower path",
        linestyle="--",
        linewidth=1.4,
        color="#f97316",
    )
    ax.plot(
        [record.follower_world_e for record in records],
        [record.follower_world_n for record in records],
        label="actual follower path",
        linewidth=1.8,
        color="#2563eb",
    )
    ax.scatter(records[0].leader_world_e, records[0].leader_world_n, color="#111827", marker="o", s=40, label="leader start")
    ax.scatter(records[-1].leader_world_e, records[-1].leader_world_n, color="#111827", marker="X", s=60, label="leader end")
    ax.scatter(records[0].follower_world_e, records[0].follower_world_n, color="#2563eb", marker="o", s=40, label="follower start")
    ax.scatter(records[-1].follower_world_e, records[-1].follower_world_n, color="#2563eb", marker="X", s=60, label="follower end")
    ax.set_xlabel("East from initial leader origin (m)")
    ax.set_ylabel("North from initial leader origin (m)")
    ax.set_title("Leader Path vs Follower Expected/Actual Path")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best")
    fig.tight_layout()
    path_overlay = output_dir / "smart_swarm_tracking_overlay.png"
    fig.savefig(path_overlay, dpi=180)
    plt.close(fig)
    paths["overlay"] = str(path_overlay)

    fig = plt.figure(figsize=(10, 8))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(
        [record.leader_world_e for record in records],
        [record.leader_world_n for record in records],
        [record.leader_world_d for record in records],
        label="leader",
        linewidth=1.5,
        color="#111827",
    )
    ax.plot(
        [record.follower_world_e for record in records],
        [record.follower_world_n for record in records],
        [record.follower_world_d for record in records],
        label="actual follower",
        linewidth=1.8,
        color="#2563eb",
    )
    ax.plot(
        [record.expected_world_e for record in records],
        [record.expected_world_n for record in records],
        [record.expected_world_d for record in records],
        label="expected follower",
        linestyle="--",
        linewidth=1.2,
        color="#f97316",
    )
    ax.set_xlabel("East from initial leader origin (m)")
    ax.set_ylabel("North from initial leader origin (m)")
    ax.set_zlabel("Down (m)")
    ax.set_title("Leader + Follower 3D Track")
    ax.legend(loc="best")
    fig.tight_layout()
    path_3d = output_dir / "smart_swarm_tracking_3d.png"
    fig.savefig(path_3d, dpi=180)
    plt.close(fig)
    paths["plot_3d"] = str(path_3d)

    return paths


def restore_swarm_resource(client: Any, original_swarm_resource: dict[str, Any], *, timeout: int = 30) -> list[int]:
    client.put_json("/api/v1/config/swarm", original_swarm_resource)
    deadline = time.time() + timeout
    while time.time() < deadline:
        current_swarm = client.get_swarm_resource()
        if current_swarm == original_swarm_resource:
            return sorted(int(entry.get("hw_id", 0)) for entry in original_swarm_resource["assignments"])
        time.sleep(1.0)
    raise RuntimeError("Timed out restoring original swarm resource")


async def main_async() -> int:
    from tools.validate_actions_runtime import ApiClient as BaseApiClient
    from tools.validate_smart_swarm_runtime import (
        build_clusters,
        cluster_assignments,
        require_full_acceptance,
        require_full_execution,
        wait_altitude,
        wait_api_ready,
        wait_fleet_ready,
        wait_for_command,
        wait_formation,
        wait_idle_reset,
        wait_mission,
    )

    class ApiClient(BaseApiClient):
        def put_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            import urllib.request

            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="PUT",
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)

        def patch_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
            import urllib.request

            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}{path}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="PATCH",
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)

        def get_swarm_resource(self) -> dict[str, Any]:
            payload = self.get_json("/api/v1/config/swarm")
            require(isinstance(payload, dict) and isinstance(payload.get("assignments"), list), f"Unexpected swarm payload: {payload!r}")
            return payload

        def get_swarm(self) -> list[dict[str, Any]]:
            return self.get_swarm_resource()["assignments"]

        def update_assignment(self, hw_id: int, **kwargs: Any) -> dict[str, Any]:
            payload = {
                key: value
                for key, value in kwargs.items()
                if key in {"follow", "offset_x", "offset_y", "offset_z", "frame"} and value is not None
            }
            response = self.patch_json(f"/api/v1/config/swarm/assignments/{int(hw_id)}", payload)
            return response.get("assignment") or payload

    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = ApiClient(args.base_url)
    ids = sorted({int(drone_id) for drone_id in args.drone_ids})
    leader_id = int(args.leader_id)
    follower_id = int(args.follower_id)
    require(leader_id in ids, f"Leader {leader_id} must be included in --drone-ids")
    require(follower_id in ids and follower_id != leader_id, f"Follower {follower_id} must be included in --drone-ids and differ from leader")

    results: dict[str, Any] = {
        "base_url": args.base_url,
        "drone_ids": ids,
        "leader_id": leader_id,
        "follower_id": follower_id,
    }
    original_assignments: dict[int, dict] | None = None
    original_swarm_resource: dict[str, Any] | None = None

    try:
        results["health"] = wait_api_ready(client, timeout=60)
        telemetry = wait_fleet_ready(client, ids, timeout=120)
        log(f"BASELINE READY: {ids}")
        results["baseline_telemetry"] = telemetry
        base_altitudes = {str(drone_id): telemetry[str(drone_id)]["position_alt"] for drone_id in ids}
        results["base_altitudes"] = base_altitudes

        swarm_resource = client.get_swarm_resource()
        swarm = swarm_resource["assignments"]
        original_swarm_resource = json.loads(json.dumps(swarm_resource))
        original_assignments = assignment_payload_snapshot(swarm, ids)
        results["original_assignments"] = original_assignments

        demo_assignments = build_demo_swarm_assignments(ids, args.spacing_m)
        changed_ids = apply_assignments(client, demo_assignments, timeout=30)
        log(f"APPLIED DEMO ASSIGNMENTS: changed={changed_ids}")
        results["applied_assignments"] = demo_assignments
        results["assignment_changes"] = changed_ids

        cluster = build_clusters(client.get_swarm(), set(ids))[0]
        require(sorted(cluster) == ids, f"Expected one cluster {ids}, got {cluster}")

        command = client.submit_command(TAKEOFF, ids, "Smart Swarm Tracking Analysis Takeoff")
        log(f"TAKEOFF START: ids={ids}")
        takeoff_status = wait_for_command(client, command["command_id"], terminal=True, timeout=180)
        require(takeoff_status["status"] == "completed", f"Takeoff failed: {takeoff_status}")
        require_full_acceptance(takeoff_status, len(ids), "Tracking analysis takeoff")
        require_full_execution(takeoff_status, len(ids), "Tracking analysis takeoff")
        results["takeoff"] = takeoff_status
        wait_altitude(client, ids, base_altitudes, args.takeoff_min_gain)

        command = client.submit_command(SMART_SWARM, ids, "Smart Swarm Tracking Analysis Start")
        log(f"SMART SWARM START: ids={ids}")
        swarm_start = wait_for_command(client, command["command_id"], desired_phase="in_progress", timeout=90)
        require_full_acceptance(swarm_start, len(ids), "Tracking analysis Smart Swarm start")
        wait_mission(client, ids, SMART_SWARM, timeout=60)
        assignments = cluster_assignments(client.get_swarm(), ids)
        tracked_assignment = next(entry for entry in assignments if int(entry["hw_id"]) == follower_id)
        results["initial_formation"] = wait_formation(
            client,
            assignments,
            ids,
            horizontal_tolerance=args.formation_horizontal_tolerance,
            altitude_tolerance=args.formation_altitude_tolerance,
            minimum_timeout=45,
            stability_samples=args.stability_samples,
            max_velocity=args.max_smart_swarm_velocity,
        )
        results["pre_jog_settle_sec"] = float(args.pre_jog_settle_sec)

        latest_states: dict[str, Any] = {}
        stop_event = asyncio.Event()
        stage_ref = {"name": "steady"}
        assignment_ref = {"value": tracked_assignment}
        records: list[TrackingSample] = []

        tracked_ips = client.get_telemetry()
        leader_ip = tracked_ips[str(leader_id)]["ip"]
        follower_ip = tracked_ips[str(follower_id)]["ip"]
        leader_reference = {
            "lat": float(telemetry[str(leader_id)]["position_lat"]),
            "lon": float(telemetry[str(leader_id)]["position_long"]),
            "alt": float(telemetry[str(leader_id)]["position_alt"]),
        }
        results["leader_reference_origin"] = leader_reference

        stream_tasks = [
            asyncio.create_task(stream_swarm_state(leader_ip, latest_states, "leader", stop_event)),
            asyncio.create_task(stream_swarm_state(follower_ip, latest_states, "follower", stop_event)),
            asyncio.create_task(
                collect_tracking_samples(
                    sample_rate_hz=args.sample_rate_hz,
                    stage_ref=stage_ref,
                    leader_key="leader",
                    follower_key="follower",
                    latest_states=latest_states,
                    assignment_ref=assignment_ref,
                    reference_origin=leader_reference,
                    stop_event=stop_event,
                    records=records,
                )
            ),
        ]

        await asyncio.sleep(max(0.0, float(args.pre_jog_settle_sec)))

        move_sequence = build_live_jog_sequence(args.jog_step_m)

        results["moves"] = []
        for stage_name, payload in move_sequence:
            stage_ref["name"] = stage_name
            log(f"MOVE START: {stage_name} payload={payload}")
            command = client.submit_command(
                PRECISION_MOVE,
                [leader_id],
                f"Smart Swarm Tracking {stage_name}",
                extra_fields=payload,
            )
            status = wait_for_command(client, command["command_id"], terminal=True, timeout=180)
            require(status["status"] == "completed", f"{stage_name} failed: {status}")
            require_full_acceptance(status, 1, stage_name)
            require_full_execution(status, 1, stage_name)
            results["moves"].append({"stage": stage_name, "status": status, "payload": payload})
            await asyncio.sleep(max(0.5, float(args.post_command_settle_sec)))

        stage_ref["name"] = "land"
        log(f"LAND START: ids={ids}")
        command = client.submit_command(LAND, ids, "Smart Swarm Tracking Analysis Land")
        land_status = wait_for_command(client, command["command_id"], terminal=True, timeout=240)
        require(land_status["status"] == "completed", f"Land failed: {land_status}")
        require_full_acceptance(land_status, len(ids), "Tracking analysis land")
        require_full_execution(land_status, len(ids), "Tracking analysis land")
        wait_idle_reset(client, ids, timeout=240)
        results["land"] = land_status

        stop_event.set()
        await asyncio.gather(*stream_tasks, return_exceptions=True)

        csv_path = output_dir / "smart_swarm_tracking_samples.csv"
        write_tracking_csv(csv_path, records)
        plot_paths = plot_tracking(records, output_dir)

        results["record_count"] = len(records)
        results["csv"] = str(csv_path)
        results["plots"] = plot_paths
        if records:
            results["max_horizontal_error_m"] = max(record.horizontal_error for record in records)
            results["max_altitude_error_m"] = max(record.altitude_error for record in records)
            results["mean_horizontal_error_m"] = sum(record.horizontal_error for record in records) / len(records)
            stage_metrics = {}
            for stage in dict.fromkeys(record.stage for record in records):
                stage_records = [record for record in records if record.stage == stage]
                stage_metrics[stage] = {
                    "samples": len(stage_records),
                    "mean_horizontal_error_m": sum(record.horizontal_error for record in stage_records) / len(stage_records),
                    "max_horizontal_error_m": max(record.horizontal_error for record in stage_records),
                    "mean_altitude_error_m": sum(record.altitude_error for record in stage_records) / len(stage_records),
                    "max_altitude_error_m": max(record.altitude_error for record in stage_records),
                }
            results["stage_metrics"] = stage_metrics
        results["result"] = "PASS"
    except Exception as exc:
        results["result"] = "FAIL"
        results["error"] = str(exc)
        raise
    finally:
        if original_swarm_resource is not None:
            try:
                restored_ids = restore_swarm_resource(client, original_swarm_resource, timeout=30)
                results["restored_assignment_ids"] = restored_ids
            except Exception as restore_exc:
                results["restore_error"] = str(restore_exc)

        summary_path = output_dir / "smart_swarm_tracking_summary.json"
        summary_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="utf-8")
        log(json.dumps(results, indent=2, sort_keys=True))

    return 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
