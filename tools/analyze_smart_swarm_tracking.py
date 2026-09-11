#!/usr/bin/env python3
"""Rehearse and plot the two-drone Smart Swarm field workflow in SITL.

The validator deliberately mirrors the first field test: H1 is the leader, H2 is
assigned six metres north in NED, both take off, Smart Swarm acquires the offset,
H1 makes repeated northward jogs, the pair is recovered with Hold, and both land. It uses the
same guarded command API as the dashboard and the follower's real high-rate
Smart Swarm WebSocket path.

The tool fails closed outside reconciled SITL, accepts API credentials only from
a file, never commits its temporary swarm configuration, and restores the full
configuration after the fleet is grounded.
"""

from __future__ import annotations

import argparse
import asyncio
import copy
import csv
import json
import math
import os
import sys
import time
import uuid
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

from src.enums import Mission  # noqa: E402
from src.params import Params  # noqa: E402
from src.gcs_api_routes import (  # noqa: E402
    GCS_COMMANDS_ROUTE,
    GCS_CONFIG_SWARM_ROUTE,
    GCS_FLEET_TELEMETRY_ROUTE,
    GCS_COMMAND_STATUS_ROUTE_TEMPLATE,
)
from tools.runtime_validation_support import (  # noqa: E402
    ValidationApiClient,
    fetch_and_require_sitl_runtime,
    write_json_report,
)

PRECISION_MOVE = Mission.PRECISION_MOVE.value
TAKEOFF = Mission.TAKE_OFF.value
SMART_SWARM = Mission.SMART_SWARM.value
HOLD = Mission.HOLD.value
LAND = Mission.LAND.value

DEFAULT_CAPTURE_HORIZONTAL_M = float(getattr(Params, "SMART_SWARM_CAPTURE_HORIZONTAL_M", 2.0))
DEFAULT_CAPTURE_VERTICAL_M = float(getattr(Params, "SMART_SWARM_CAPTURE_VERTICAL_M", 1.5))
DEFAULT_CAPTURE_STABLE_SEC = float(getattr(Params, "SMART_SWARM_CAPTURE_STABLE_SEC", 1.0))
DEFAULT_STREAM_MAX_AGE_MS = int(
    max(1.0, float(getattr(Params, "SMART_SWARM_SOURCE_MAX_AGE_SEC", 0.75))) * 1000
)


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
    expected_up: float
    actual_n: float
    actual_e: float
    actual_up: float
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
        "actual_n": follower_n,
        "actual_e": follower_e,
        "horizontal_error": math.hypot(follower_n - expected_n, follower_e - expected_e),
        "expected_altitude_delta": expected_altitude,
        "actual_altitude_delta": altitude_delta,
        "altitude_error": abs(altitude_delta - expected_altitude),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rehearse the two-drone Smart Swarm field workflow in SITL.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5030", help="GCS API base URL")
    parser.add_argument(
        "--api-token-file",
        type=Path,
        default=None,
        help="Optional file containing the GCS bearer token (raw token arguments are not supported)",
    )
    parser.add_argument("--leader-id", type=int, default=1, help="Leader drone ID to move")
    parser.add_argument("--follower-id", type=int, default=2, help="Follower drone ID to track")
    parser.add_argument("--north-offset-m", type=float, default=6.0, help="Follower NED north offset from leader")
    parser.add_argument("--formation-horizontal-tolerance", type=float, default=1.5)
    parser.add_argument("--formation-altitude-tolerance", type=float, default=0.6)
    parser.add_argument("--stability-samples", type=int, default=3)
    parser.add_argument("--max-smart-swarm-velocity", type=float, default=3.0)
    parser.add_argument("--takeoff-min-gain", type=float, default=4.0)
    parser.add_argument("--sample-rate-hz", type=float, default=10.0)
    parser.add_argument("--stream-max-age-ms", type=int, default=DEFAULT_STREAM_MAX_AGE_MS)
    parser.add_argument("--stream-min-advances", type=int, default=3)
    parser.add_argument("--stream-timeout-sec", type=float, default=15.0)
    parser.add_argument("--jog-north-m", type=float, default=1.0, help="Small H1 northward field-rehearsal jog")
    parser.add_argument("--repeat-jogs", type=int, default=2, help="Exercise leader motion ownership repeatedly")
    parser.add_argument("--jog-position-tolerance", type=float, default=0.75)
    parser.add_argument("--post-command-settle-sec", type=float, default=3.0)
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for JSON/CSV/plots")
    return parser.parse_args()


class FieldRehearsalClient(ValidationApiClient):
    """Authenticated GCS adapter compatible with the existing wait helpers."""

    def get_telemetry(self) -> dict[str, dict[str, Any]]:
        payload = self.get_json(GCS_FLEET_TELEMETRY_ROUTE)
        require(isinstance(payload, dict), f"Unexpected telemetry response: {payload!r}")
        telemetry = payload.get("telemetry") or {}
        require(isinstance(telemetry, dict), f"Unexpected telemetry map: {telemetry!r}")
        return {str(key): value for key, value in telemetry.items()}

    def get_swarm_resource(self) -> dict[str, Any]:
        payload = self.get_json(GCS_CONFIG_SWARM_ROUTE)
        require(
            isinstance(payload, dict) and isinstance(payload.get("assignments"), list),
            f"Unexpected swarm resource: {payload!r}",
        )
        return payload

    def get_swarm(self) -> list[dict[str, Any]]:
        return self.get_swarm_resource()["assignments"]

    def require_sitl_runtime(self) -> dict[str, Any]:
        """Re-check the execution target immediately before every mutation.

        The initial gate prevents an accidental REAL run.  Re-checking here
        also closes the less obvious race where an operator changes/restarts
        the GCS while a long rehearsal is in progress.
        """

        return fetch_and_require_sitl_runtime(self.base_url, client=self)

    def put_swarm_resource(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.require_sitl_runtime()
        response = self.put_json(f"{GCS_CONFIG_SWARM_ROUTE}?commit=false", payload)
        require(isinstance(response, dict), f"Unexpected swarm update response: {response!r}")
        return response

    def submit_command(
        self,
        mission_type: int,
        target_ids: list[int],
        operator_label: str,
        *,
        extra_fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.require_sitl_runtime()
        payload = {
            "mission_type": int(mission_type),
            "target_drone_ids": [str(target_id) for target_id in target_ids],
            "trigger_time": 0,
            "operator_label": str(operator_label),
            **(extra_fields or {}),
        }
        response = self.post_json(GCS_COMMANDS_ROUTE, payload)
        require(
            isinstance(response, dict) and response.get("command_id"),
            f"Command submission returned no command id: {response!r}",
        )
        log(f"COMMAND {operator_label}: id={response['command_id']} targets={target_ids}")
        return response

    def start_saved_swarm(self, ids):
        """Use the dashboard's session contract, not the legacy raw mission."""
        self.require_sitl_runtime()
        preview = self.get_json("/api/v1/swarm/runtime/preview")
        cluster = next((c for c in preview["clusters"]
                        if {m["hw_id"] for m in c["members"]} == {str(i) for i in ids}), None)
        require(cluster is not None, "Saved cluster differs from the test targets")
        return self.post_json("/api/v1/swarm/runtime/start", {
            "cluster_id": cluster["cluster_id"], "revision": preview["revision"],
            "idempotency_key": str(uuid.uuid4()),
        })


def build_two_drone_ned_assignments(
    leader_id: int,
    follower_id: int,
    north_offset_m: float,
) -> dict[int, dict[str, Any]]:
    """Return the exact field topology: H2 follows H1 six metres north in NED."""

    require(int(leader_id) != int(follower_id), "Leader and follower IDs must differ.")
    require(math.isfinite(float(north_offset_m)), "Follower north offset must be finite.")
    return {
        int(leader_id): {
            "follow": 0,
            "offset_x": 0.0,
            "offset_y": 0.0,
            "offset_z": 0.0,
            "frame": "ned",
        },
        int(follower_id): {
            "follow": int(leader_id),
            "offset_x": float(north_offset_m),
            "offset_y": 0.0,
            "offset_z": 0.0,
            "frame": "ned",
        },
    }


def build_temporary_swarm_resource(
    original_resource: dict[str, Any],
    replacements: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Replace selected assignments while retaining the full saved resource."""

    require(isinstance(original_resource.get("assignments"), list), "Swarm resource has no assignments list.")
    resource = copy.deepcopy(original_resource)
    remaining = {int(hw_id): canonical_assignment(entry) for hw_id, entry in replacements.items()}
    rewritten: list[dict[str, Any]] = []
    for entry in resource["assignments"]:
        hw_id = int(entry["hw_id"])
        replacement = remaining.pop(hw_id, None)
        if replacement is None:
            rewritten.append(entry)
        else:
            rewritten.append({"hw_id": hw_id, **replacement})
    rewritten.extend({"hw_id": hw_id, **entry} for hw_id, entry in sorted(remaining.items()))
    resource["assignments"] = rewritten
    return resource


def canonical_assignment(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "follow": int(entry.get("follow", 0) or 0),
        "offset_x": float(entry.get("offset_x", 0.0) or 0.0),
        "offset_y": float(entry.get("offset_y", 0.0) or 0.0),
        "offset_z": float(entry.get("offset_z", 0.0) or 0.0),
        "frame": str(entry.get("frame", "body") or "body").lower(),
    }


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


def build_staging_move(
    leader: dict[str, Any],
    follower: dict[str, Any],
    assignment: dict[str, Any],
    *,
    max_horizontal_m: float,
    max_vertical_m: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the bounded relative move that puts H2 inside capture geometry."""

    geometry = formation_error(leader, follower, assignment)
    north_m = float(geometry["expected_n"]) - float(geometry["actual_n"])
    east_m = float(geometry["expected_e"]) - float(geometry["actual_e"])
    up_m = float(geometry["expected_altitude_delta"]) - float(
        geometry["actual_altitude_delta"]
    )
    horizontal_m = math.hypot(north_m, east_m)
    require(
        horizontal_m <= float(max_horizontal_m),
        f"Refusing unsafe follower staging move of {horizontal_m:.2f}m; limit is {max_horizontal_m:.2f}m",
    )
    require(
        abs(up_m) <= float(max_vertical_m),
        f"Refusing unsafe follower staging vertical move of {up_m:.2f}m; limit is {max_vertical_m:.2f}m",
    )
    return geometry, build_precision_move_payload("ned", north=north_m, east=east_m, up=up_m)


def wait_geometry(
    client: FieldRehearsalClient,
    leader_id: int,
    follower_id: int,
    assignment: dict[str, Any],
    *,
    horizontal_tolerance: float,
    altitude_tolerance: float,
    stability_samples: int,
    timeout: float,
) -> dict[str, Any]:
    """Require stable live geometry for consecutive telemetry samples."""

    deadline = time.monotonic() + float(timeout)
    consecutive = 0
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        telemetry = client.get_telemetry()
        if str(leader_id) in telemetry and str(follower_id) in telemetry:
            last = formation_error(
                telemetry[str(leader_id)], telemetry[str(follower_id)], assignment
            )
            if (
                last["horizontal_error"] <= float(horizontal_tolerance)
                and last["altitude_error"] <= float(altitude_tolerance)
            ):
                consecutive += 1
                if consecutive >= int(stability_samples):
                    return last
            else:
                consecutive = 0
        time.sleep(0.5)
    raise RuntimeError(
        "Timed out waiting for stable two-drone geometry. "
        f"Last measurement: {json.dumps(last, sort_keys=True)}"
    )


def wait_leader_jog_displacement(
    client: FieldRehearsalClient,
    leader_id: int,
    start: dict[str, Any],
    *,
    expected_north_m: float,
    tolerance_m: float,
    timeout: float,
) -> dict[str, float]:
    """Confirm the leader's global position reflects the requested small jog."""

    deadline = time.monotonic() + float(timeout)
    last: dict[str, float] = {}
    while time.monotonic() < deadline:
        current = client.get_telemetry().get(str(leader_id))
        if current:
            actual_north_m, actual_east_m = latlon_to_ne(
                float(current["position_lat"]),
                float(current["position_long"]),
                float(start["position_lat"]),
                float(start["position_long"]),
            )
            error_m = math.hypot(
                actual_north_m - float(expected_north_m),
                actual_east_m,
            )
            last = {
                "requested_north_m": float(expected_north_m),
                "actual_north_m": actual_north_m,
                "actual_east_m": actual_east_m,
                "position_error_m": error_m,
            }
            if error_m <= float(tolerance_m):
                return last
        time.sleep(0.25)
    raise RuntimeError(
        "Leader jog did not match the requested NED move within tolerance. "
        f"Last measurement: {json.dumps(last, sort_keys=True)}"
    )


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
    actual_up = float(follower_state["position_alt"]) - float(leader_state["position_alt"])
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
    expected_world_d = leader_world_d - float(result["expected_altitude_delta"])
    return TrackingSample(
        stage=stage,
        sample_time_s=sample_time_s,
        leader_seq=int(leader_state.get("stream_seq", 0) or 0),
        follower_seq=int(follower_state.get("stream_seq", 0) or 0),
        leader_yaw_deg=float(leader_state.get("yaw_deg", leader_state.get("yaw", 0.0)) or 0.0),
        assignment_frame=str(assignment.get("frame", "body")),
        expected_n=float(result["expected_n"]),
        expected_e=float(result["expected_e"]),
        expected_up=float(result["expected_altitude_delta"]),
        actual_n=float(actual_n),
        actual_e=float(actual_e),
        actual_up=float(actual_up),
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
                try:
                    message = await asyncio.wait_for(websocket.receive(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if message.type == aiohttp.WSMsgType.TEXT:
                    payload = message.json()
                    if isinstance(payload, dict) and not payload.get("error"):
                        received_at_ms = int(time.time() * 1000)
                        normalized = dict(payload)
                        normalized["received_at_ms"] = received_at_ms
                        emitted_at_ms = int(normalized.get("emitted_at_ms", 0) or 0)
                        normalized["sample_age_ms"] = (
                            max(0, received_at_ms - emitted_at_ms) if emitted_at_ms else -1
                        )
                        sink[key] = normalized
                elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    return
                elif message.type == aiohttp.WSMsgType.ERROR:
                    raise RuntimeError(f"Swarm-state websocket error for {key}: {websocket.exception()}")


def fresh_stream_state(
    payload: Any,
    *,
    now_ms: int,
    max_age_ms: int,
) -> tuple[bool, str]:
    """Validate that one state is usable by the real Smart Swarm transport."""

    if not isinstance(payload, dict) or not payload:
        return False, "empty payload"
    if not bool(payload.get("global_position_valid")):
        return False, "global position is not valid"
    try:
        stream_seq = int(payload.get("stream_seq", 0) or 0)
        emitted_at_ms = int(payload.get("emitted_at_ms", 0) or 0)
        position = tuple(float(payload[key]) for key in ("position_lat", "position_long", "position_alt"))
    except (KeyError, TypeError, ValueError):
        return False, "required state fields are missing or invalid"
    if stream_seq <= 0:
        return False, "stream sequence has not started"
    if emitted_at_ms <= 0:
        return False, "emission timestamp is missing"
    if not all(math.isfinite(value) for value in position):
        return False, "position contains a non-finite value"
    age_ms = int(now_ms) - emitted_at_ms
    if age_ms < -int(max_age_ms):
        return False, f"emission timestamp is {abs(age_ms)}ms in the future"
    if age_ms > int(max_age_ms):
        return False, f"state is stale by {age_ms}ms"
    return True, "fresh"


async def wait_for_advancing_fresh_streams(
    latest_states: dict[str, Any],
    stream_tasks: dict[str, asyncio.Task],
    keys: list[str],
    *,
    min_advances: int,
    max_age_ms: int,
    timeout_sec: float,
) -> dict[str, Any]:
    """Require nonempty, fresh, independently advancing state from both drones."""

    advances = {key: 0 for key in keys}
    last_seq = {key: None for key in keys}
    last_reason = {key: "no sample" for key in keys}
    deadline = time.monotonic() + float(timeout_sec)
    while time.monotonic() < deadline:
        for key, task in stream_tasks.items():
            if task.done():
                if task.cancelled():
                    raise RuntimeError(f"Smart Swarm stream task for {key} was cancelled")
                exc = task.exception()
                raise RuntimeError(f"Smart Swarm stream task for {key} stopped: {exc or 'connection closed'}")

        now_ms = int(time.time() * 1000)
        for key in keys:
            payload = latest_states.get(key)
            valid, reason = fresh_stream_state(
                payload,
                now_ms=now_ms,
                max_age_ms=int(max_age_ms),
            )
            last_reason[key] = reason
            if not valid:
                continue
            seq = int(payload["stream_seq"])
            if last_seq[key] is None:
                last_seq[key] = seq
            elif seq > int(last_seq[key]):
                # Polling may legitimately observe a jump when the producer is
                # faster than this verifier. Count the proven sequence delta,
                # rather than requiring every intermediate frame to be sampled.
                advances[key] += seq - int(last_seq[key])
                last_seq[key] = seq
            elif seq < int(last_seq[key]):
                raise RuntimeError(
                    f"Smart Swarm stream sequence regressed for {key}: {seq} < {last_seq[key]}"
                )
        if all(advances[key] >= int(min_advances) for key in keys):
            return {
                key: {
                    "advances": advances[key],
                    "last_seq": last_seq[key],
                    "sample_age_ms": int(latest_states[key].get("sample_age_ms", -1)),
                }
                for key in keys
            }
        await asyncio.sleep(0.05)
    raise RuntimeError(
        "Timed out waiting for advancing fresh Smart Swarm streams: "
        f"advances={advances}, reasons={last_reason}, last_seq={last_seq}"
    )


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

    axes[2].plot(times, [record.actual_up for record in records], label="actual Up", linewidth=1.8)
    axes[2].plot(times, [record.expected_up for record in records], label="expected Up", linestyle="--", linewidth=1.2)
    axes[2].set_ylabel("Up delta (m)")
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


def put_and_wait_swarm_resource(
    client: FieldRehearsalClient,
    expected_resource: dict[str, Any],
    *,
    timeout: int = 30,
) -> list[int]:
    client.put_swarm_resource(expected_resource)
    deadline = time.time() + timeout
    while time.time() < deadline:
        current_swarm = client.get_swarm_resource()
        if current_swarm == expected_resource:
            return sorted(int(entry.get("hw_id", 0)) for entry in expected_resource["assignments"])
        time.sleep(1.0)
    raise RuntimeError("Timed out waiting for the temporary swarm resource update")


def restore_swarm_resource(
    client: FieldRehearsalClient,
    original_swarm_resource: dict[str, Any],
    *,
    timeout: int = 30,
) -> list[int]:
    """Restore the complete resource without creating a git commit."""

    return put_and_wait_swarm_resource(client, original_swarm_resource, timeout=timeout)


async def stop_async_tasks(
    stop_event: asyncio.Event,
    tasks: list[asyncio.Task],
) -> list[str]:
    """Stop stream/collector tasks without hanging on a quiet WebSocket."""

    stop_event.set()
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=2.0)
    for task in pending:
        task.cancel()
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    errors: list[str] = []
    for outcome in outcomes:
        if isinstance(outcome, asyncio.CancelledError) or outcome is None:
            continue
        if isinstance(outcome, BaseException):
            errors.append(str(outcome))
    return errors


def land_armed_targets_and_wait_idle(
    client: FieldRehearsalClient,
    ids: list[int],
    *,
    wait_for_command: Any,
    wait_idle_reset: Any,
    require_full_acceptance: Any,
    require_full_execution: Any,
    timeout: int = 240,
) -> dict[str, Any]:
    """Best-effort terminal safety action used by both success and failure paths."""

    # Never send a cleanup flight command to a target whose mode changed to
    # REAL while this SITL rehearsal was running.
    client.require_sitl_runtime()
    telemetry = client.get_telemetry()
    armed_ids = [drone_id for drone_id in ids if telemetry.get(str(drone_id), {}).get("is_armed")]
    result: dict[str, Any] = {"armed_targets": armed_ids}
    if armed_ids:
        command = client.submit_command(LAND, armed_ids, "Two-Drone Field Rehearsal Safety Land")
        status = wait_for_command(client, command["command_id"], terminal=True, timeout=timeout)
        require(status.get("status") == "completed", f"Safety LAND failed: {status}")
        require_full_acceptance(status, len(armed_ids), "Safety LAND")
        require_full_execution(status, len(armed_ids), "Safety LAND")
        result["land_command"] = status
    result["idle_telemetry"] = wait_idle_reset(client, ids, timeout=timeout)
    result["grounded_verified"] = True
    return result


async def main_async() -> int:
    from tools.validate_actions_runtime import wait_hold_ready
    from tools.validate_smart_swarm_runtime import (
        build_clusters,
        cluster_assignments,
        command_summary,
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

    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    client = FieldRehearsalClient(
        args.base_url,
        bearer_token_file=args.api_token_file,
        timeout_sec=60.0,
    )
    leader_id = int(args.leader_id)
    follower_id = int(args.follower_id)
    ids = [leader_id, follower_id]
    require(
        ids == [1, 2],
        "This field rehearsal intentionally targets H1 as leader and H2 as follower",
    )
    require(float(args.north_offset_m) > 0.0, "Follower north offset must be positive")
    require(float(args.jog_north_m) > 0.0, "Leader jog must be positive north")
    require(1 <= args.repeat_jogs <= 10, "Repeat jogs must be between 1 and 10")

    results: dict[str, Any] = {
        "base_url": args.base_url,
        "drone_ids": ids,
        "leader_id": leader_id,
        "follower_id": follower_id,
        "topology": {
            "frame": "ned",
            "follower_north_offset_m": float(args.north_offset_m),
        },
        "api_token_file_configured": args.api_token_file is not None,
    }
    original_swarm_resource: dict[str, Any] | None = None
    swarm_mutated = False
    sitl_verified = False
    grounded_verified = False
    exit_code = 1
    stop_event = asyncio.Event()
    stream_tasks: list[asyncio.Task] = []
    stream_task_map: dict[str, asyncio.Task] = {}
    records: list[TrackingSample] = []

    try:
        # Reads may retry before the safety gate, but no command/config mutation
        # occurs until the reconciled runtime identity is proven to be SITL.
        results["health"] = wait_api_ready(client, timeout=60)
        results["target_runtime"] = fetch_and_require_sitl_runtime(
            args.base_url,
            client=client,
        )
        sitl_verified = True
        telemetry = wait_fleet_ready(client, ids, timeout=120)
        log(f"BASELINE READY: {ids}")
        results["baseline_telemetry"] = telemetry
        base_altitudes = {
            str(drone_id): float(telemetry[str(drone_id)]["position_alt"])
            for drone_id in ids
        }
        results["base_altitudes"] = base_altitudes

        original_swarm_resource = copy.deepcopy(client.get_swarm_resource())
        target_assignments = build_two_drone_ned_assignments(
            leader_id,
            follower_id,
            float(args.north_offset_m),
        )
        temporary_swarm_resource = build_temporary_swarm_resource(
            original_swarm_resource,
            target_assignments,
        )
        results["original_swarm_resource"] = original_swarm_resource
        results["temporary_assignments"] = target_assignments
        if temporary_swarm_resource != original_swarm_resource:
            # Mark the resource dirty before issuing the PUT so a response or
            # verification failure still enters the restore path.
            swarm_mutated = True
            changed_resource_ids = put_and_wait_swarm_resource(
                client,
                temporary_swarm_resource,
                timeout=30,
            )
            results["temporary_resource_ids"] = changed_resource_ids
        else:
            results["temporary_resource_ids"] = []

        clusters = build_clusters(client.get_swarm(), set(ids))
        require(clusters == [ids], f"Expected one deterministic cluster {ids}, got {clusters}")
        results["clusters"] = clusters

        command = client.submit_command(TAKEOFF, ids, "Smart Swarm Tracking Analysis Takeoff")
        log(f"TAKEOFF START: ids={ids}")
        takeoff_status = wait_for_command(client, command["command_id"], terminal=True, timeout=180)
        require(
            takeoff_status["status"] == "completed",
            f"Paired takeoff failed: {command_summary(takeoff_status)}",
        )
        require_full_acceptance(takeoff_status, len(ids), "Tracking analysis takeoff")
        require_full_execution(takeoff_status, len(ids), "Tracking analysis takeoff")
        results["takeoff"] = command_summary(takeoff_status)
        results["airborne_telemetry"] = wait_altitude(
            client,
            ids,
            base_altitudes,
            args.takeoff_min_gain,
        )

        tracked_assignment = {"hw_id": follower_id, **target_assignments[follower_id]}
        initial_telemetry = client.get_telemetry()
        results["pre_swarm_geometry"] = formation_error(
            initial_telemetry[str(leader_id)], initial_telemetry[str(follower_id)],
            tracked_assignment)

        tracked_telemetry = client.get_telemetry()
        leader_ip = str(tracked_telemetry[str(leader_id)]["ip"])
        follower_ip = str(tracked_telemetry[str(follower_id)]["ip"])
        leader_reference = {
            "lat": float(tracked_telemetry[str(leader_id)]["position_lat"]),
            "lon": float(tracked_telemetry[str(leader_id)]["position_long"]),
            "alt": float(tracked_telemetry[str(leader_id)]["position_alt"]),
        }
        results["leader_reference_origin"] = leader_reference

        latest_states: dict[str, Any] = {}
        stage_ref = {"name": "staged_hold"}
        assignment_ref = {"value": tracked_assignment}
        stream_task_map = {
            "leader": asyncio.create_task(
                stream_swarm_state(leader_ip, latest_states, "leader", stop_event)
            ),
            "follower": asyncio.create_task(
                stream_swarm_state(follower_ip, latest_states, "follower", stop_event)
            ),
        }
        collector_task = asyncio.create_task(
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
        )
        stream_tasks = [*stream_task_map.values(), collector_task]
        results["pre_swarm_stream_evidence"] = await wait_for_advancing_fresh_streams(
            latest_states,
            stream_task_map,
            ["leader", "follower"],
            min_advances=int(args.stream_min_advances),
            max_age_ms=int(args.stream_max_age_ms),
            timeout_sec=float(args.stream_timeout_sec),
        )

        stage_ref["name"] = "smart_swarm_capture"
        command = await asyncio.to_thread(
            client.start_saved_swarm,
            ids,
        )
        swarm_command_id = command["command_id"]
        log(f"SMART SWARM START: ids={ids}")
        swarm_start = await asyncio.to_thread(
            wait_for_command,
            client,
            command["command_id"],
            desired_phase="in_progress",
            timeout=90,
        )
        require_full_acceptance(swarm_start, len(ids), "Tracking analysis Smart Swarm start")
        results["smart_swarm_start"] = command_summary(swarm_start)
        await asyncio.to_thread(wait_mission, client, ids, SMART_SWARM, 60)
        assignments = cluster_assignments(client.get_swarm(), ids)
        results["initial_formation"] = await asyncio.to_thread(
            wait_formation,
            client,
            assignments,
            ids,
            horizontal_tolerance=float(args.formation_horizontal_tolerance),
            altitude_tolerance=float(args.formation_altitude_tolerance),
            minimum_timeout=45,
            stability_samples=int(args.stability_samples),
            max_velocity=float(args.max_smart_swarm_velocity),
        )
        results["active_stream_evidence"] = await wait_for_advancing_fresh_streams(
            latest_states,
            stream_task_map,
            ["leader", "follower"],
            min_advances=int(args.stream_min_advances),
            max_age_ms=int(args.stream_max_age_ms),
            timeout_sec=float(args.stream_timeout_sec),
        )

        stage_ref["name"] = "leader_north_jog"
        jog_start = client.get_telemetry()[str(leader_id)]
        jog_payload = build_precision_move_payload("ned", north=float(args.jog_north_m))
        jog_command = await asyncio.to_thread(
            client.submit_command,
            PRECISION_MOVE,
            [leader_id],
            "Two-Drone Field Rehearsal Leader North Jog",
            extra_fields=jog_payload,
        )
        jog_status = await asyncio.to_thread(
            wait_for_command,
            client,
            jog_command["command_id"],
            terminal=True,
            timeout=180,
        )
        require(
            jog_status.get("status") == "completed",
            f"Leader jog failed: {command_summary(jog_status)}",
        )
        require_full_acceptance(jog_status, 1, "Leader north jog")
        require_full_execution(jog_status, 1, "Leader north jog")
        results["leader_jog"] = {
            "command": command_summary(jog_status),
            **await asyncio.to_thread(
                wait_leader_jog_displacement,
                client,
                leader_id,
                jog_start,
                expected_north_m=float(args.jog_north_m),
                tolerance_m=float(args.jog_position_tolerance),
                timeout=10,
            ),
        }
        await asyncio.to_thread(wait_mission, client, [follower_id], SMART_SWARM, 60)
        results["post_jog_formation"] = await asyncio.to_thread(
            wait_geometry,
            client,
            leader_id,
            follower_id,
            tracked_assignment,
            horizontal_tolerance=float(args.formation_horizontal_tolerance),
            altitude_tolerance=float(args.formation_altitude_tolerance),
            stability_samples=int(args.stability_samples),
            timeout=90,
        )
        await asyncio.sleep(max(0.5, float(args.post_command_settle_sec)))
        results["post_jog_stream_evidence"] = await wait_for_advancing_fresh_streams(
            latest_states,
            stream_task_map,
            ["leader", "follower"],
            min_advances=int(args.stream_min_advances),
            max_age_ms=int(args.stream_max_age_ms),
            timeout_sec=float(args.stream_timeout_sec),
        )

        results["repeated_jogs"] = []
        for jog_index in range(1, args.repeat_jogs):
            stage_ref["name"] = f"leader_north_jog_{jog_index + 1}"
            jog_command = await asyncio.to_thread(
                client.submit_command, PRECISION_MOVE, [leader_id],
                "Repeated Leader Jog", extra_fields=jog_payload)
            jog_status = await asyncio.to_thread(
                wait_for_command, client, jog_command["command_id"],
                terminal=True, timeout=180)
            require(jog_status.get("status") == "completed", "Repeated leader jog failed")
            require_full_execution(jog_status, 1, "Repeated leader jog")
            geometry = await asyncio.to_thread(
                wait_geometry, client, leader_id, follower_id, tracked_assignment,
                horizontal_tolerance=float(args.formation_horizontal_tolerance),
                altitude_tolerance=float(args.formation_altitude_tolerance),
                stability_samples=int(args.stability_samples), timeout=120)
            evidence = await wait_for_advancing_fresh_streams(
                latest_states, stream_task_map, ["leader", "follower"],
                min_advances=int(args.stream_min_advances),
                max_age_ms=int(args.stream_max_age_ms),
                timeout_sec=float(args.stream_timeout_sec))
            results["repeated_jogs"].append({"command": command_summary(jog_status),
                                             "formation": geometry, "streams": evidence})

        session_evidence = client.get_json(
            GCS_COMMAND_STATUS_ROUTE_TEMPLATE.format(command_id=swarm_command_id))
        runtime_evidence = session_evidence.get("swarm_runtime") or {}
        require(runtime_evidence.get("state") in {"active", "settling"},
                f"Following is not confirmed after leader actions: {runtime_evidence}")
        require(set(runtime_evidence.get("active_hw_ids", [])) == {str(i) for i in ids},
                "Not all swarm roles are still reporting after leader actions")
        results["post_actions_session"] = runtime_evidence

        stage_ref["name"] = "hold_recovery"
        hold_command = await asyncio.to_thread(
            client.submit_command,
            HOLD,
            ids,
            "Two-Drone Field Rehearsal Hold Recovery",
        )
        hold_status = await asyncio.to_thread(
            wait_for_command,
            client,
            hold_command["command_id"],
            terminal=True,
            timeout=120,
        )
        require(
            hold_status.get("status") == "completed",
            f"Hold recovery failed: {command_summary(hold_status)}",
        )
        require_full_acceptance(hold_status, len(ids), "Hold recovery")
        require_full_execution(hold_status, len(ids), "Hold recovery")
        results["hold_recovery"] = command_summary(hold_status)
        results["hold_telemetry"] = await asyncio.to_thread(
            wait_hold_ready,
            client,
            ids,
            base_altitudes,
            float(args.takeoff_min_gain),
            120,
        )

        stage_ref["name"] = "land"
        log(f"LAND START: ids={ids}")
        command = await asyncio.to_thread(
            client.submit_command,
            LAND,
            ids,
            "Two-Drone Field Rehearsal Land",
        )
        land_status = await asyncio.to_thread(
            wait_for_command,
            client,
            command["command_id"],
            terminal=True,
            timeout=240,
        )
        require(land_status["status"] == "completed", f"Land failed: {command_summary(land_status)}")
        require_full_acceptance(land_status, len(ids), "Tracking analysis land")
        require_full_execution(land_status, len(ids), "Tracking analysis land")
        results["land"] = command_summary(land_status)
        results["final_telemetry"] = await asyncio.to_thread(
            wait_idle_reset,
            client,
            ids,
            240,
        )
        grounded_verified = True
        results["result"] = "PASS"
        exit_code = 0
    except Exception as exc:
        results["result"] = "FAIL"
        results["error"] = str(exc)
    finally:
        # The safety action is unconditional. Configuration restoration is
        # deliberately ordered after a verified idle state.
        if sitl_verified:
            try:
                safety_cleanup = await asyncio.to_thread(
                    land_armed_targets_and_wait_idle,
                    client,
                    ids,
                    wait_for_command=wait_for_command,
                    wait_idle_reset=wait_idle_reset,
                    require_full_acceptance=require_full_acceptance,
                    require_full_execution=require_full_execution,
                    timeout=240,
                )
                results["safety_cleanup"] = safety_cleanup
                grounded_verified = bool(safety_cleanup.get("grounded_verified"))
            except Exception as cleanup_exc:
                results["safety_cleanup"] = {"grounded_verified": False, "error": str(cleanup_exc)}
                if exit_code == 0:
                    exit_code = 1
                    results["result"] = "FAIL"
                    results["error"] = f"Safety cleanup failed: {cleanup_exc}"
        else:
            results["safety_cleanup"] = {
                "status": "skipped",
                "reason": "SITL runtime identity was not verified; no command was sent",
            }

        stream_errors = await stop_async_tasks(stop_event, stream_tasks)
        results["stream_task_errors"] = stream_errors
        if stream_errors and exit_code == 0:
            exit_code = 1
            results["result"] = "FAIL"
            results["error"] = f"Smart Swarm stream task failed: {stream_errors[0]}"

        if original_swarm_resource is not None and swarm_mutated and grounded_verified:
            try:
                restored_ids = restore_swarm_resource(client, original_swarm_resource, timeout=30)
                results["restored_assignment_ids"] = restored_ids
                results["restored_swarm_resource"] = client.get_swarm_resource()
            except Exception as restore_exc:
                results["restore_error"] = str(restore_exc)
                if exit_code == 0:
                    exit_code = 1
                    results["result"] = "FAIL"
                    results["error"] = f"Swarm resource restore failed: {restore_exc}"
        elif original_swarm_resource is not None and not swarm_mutated:
            results["restored_assignment_ids"] = []
            results["restored_swarm_resource"] = original_swarm_resource
        elif original_swarm_resource is not None:
            results["restore_deferred"] = "Fleet idle state was not verified; live swarm configuration was not changed again."
            if exit_code == 0:
                exit_code = 1
                results["result"] = "FAIL"
                results["error"] = "Fleet idle state could not be verified before configuration restore"

        try:
            results["record_count"] = len(records)
            require(records, "No Smart Swarm tracking samples were captured")
            csv_path = output_dir / "smart_swarm_tracking_samples.csv"
            write_tracking_csv(csv_path, records)
            results["csv"] = str(csv_path)
            results["plots"] = plot_tracking(records, output_dir)
            results["max_horizontal_error_m"] = max(record.horizontal_error for record in records)
            results["max_altitude_error_m"] = max(record.altitude_error for record in records)
            results["mean_horizontal_error_m"] = (
                sum(record.horizontal_error for record in records) / len(records)
            )
            stage_metrics: dict[str, dict[str, Any]] = {}
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
        except Exception as artifact_exc:
            results["artifact_error"] = str(artifact_exc)
            if exit_code == 0:
                exit_code = 1
                results["result"] = "FAIL"
                results["error"] = f"Tracking artifact generation failed: {artifact_exc}"

        summary_path = output_dir / "smart_swarm_tracking_summary.json"
        results["summary"] = str(summary_path)
        write_json_report(summary_path, results)
        log(json.dumps(results, indent=2, sort_keys=True))

    return exit_code


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
