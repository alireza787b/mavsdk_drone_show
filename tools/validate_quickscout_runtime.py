#!/usr/bin/env python3
"""Validate the QuickScout workflow against a live GCS/SITL stack.

The validator supports both:

1. the stable single-drone last-known-point drill
2. a broader multi-drone launch drill using the same mission template

In both cases it validates the same operator-facing lifecycle:

1. Wait for a clean ready/idle fleet baseline
2. Plan a QuickScout mission from live telemetry
3. Launch the mission and confirm the targeted aircraft climb and begin searching
4. Pause into HOLD and confirm the mission enters the holding phase
5. Create/update a finding and validate the mission handoff bundle
6. Confirm direct resume is rejected with explicit replan guidance
7. Abort and confirm the fleet returns to a clean idle baseline

For partial-fleet drills it also confirms that non-target drones remain idle.
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
    from src.drone_api_routes import DRONE_LIVE_ARMABILITY_ROUTE
    from src.live_armability_utils import calculate_live_armability_request_timeout
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
        drone_api_port = 7070
        LIVE_ARMABILITY_PROBE_CONNECT_TIMEOUT_SEC = 5.0
        LIVE_ARMABILITY_PROBE_TIMEOUT_SEC = 6.0
        LIVE_ARMABILITY_PROBE_HTTP_BUFFER_SEC = 2.0

    Params = _FallbackParams()
    DRONE_LIVE_ARMABILITY_ROUTE = "/api/v1/preflight/armability"
    GCS_SYSTEM_HEALTH_ROUTE = "/api/v1/system/health"
    GCS_FLEET_TELEMETRY_ROUTE = "/api/v1/fleet/telemetry"
    GCS_ACTIVE_COMMANDS_ROUTE = "/api/v1/commands/active"
    GCS_COMMAND_STATUS_ROUTE_TEMPLATE = "/api/v1/commands/{command_id}"

    def calculate_live_armability_request_timeout(*, params):
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


def select_target_drones(
    telemetry: dict[str, dict[str, Any]],
    selected_ids: list[int],
    *,
    target_count: int,
) -> list[tuple[int, dict[str, Any]]]:
    if target_count <= 0:
        raise RuntimeError(f"Target count must be positive, got {target_count}")

    targets: list[tuple[int, dict[str, Any]]] = []
    for drone_id in selected_ids:
        row = telemetry.get(str(drone_id)) or {}
        if row.get("position_lat") is None or row.get("position_long") is None:
            continue
        if row.get("pos_id") is None:
            continue
        targets.append((drone_id, row))
        if len(targets) >= target_count:
            return targets

    raise RuntimeError(
        f"Only {len(targets)} selected drone(s) had live GPS + pos_id telemetry; "
        f"needed {target_count} from {selected_ids}"
    )


def build_last_known_point_request(
    target_rows: list[dict[str, Any]],
    *,
    pos_ids: list[int],
    radius_m: float,
    altitude_gain_m: float,
    sweep_width_m: float,
    overlap_percent: float,
    cruise_speed_ms: float,
    survey_speed_ms: float,
) -> dict[str, Any]:
    require(bool(target_rows), "At least one target row is required for QuickScout plan construction")
    require(
        len(target_rows) == len(pos_ids),
        f"Target row / pos_id mismatch: {len(target_rows)} rows for {len(pos_ids)} pos_ids",
    )
    center_lat = sum(float(row["position_lat"]) for row in target_rows) / len(target_rows)
    center_lng = sum(float(row["position_long"]) for row in target_rows) / len(target_rows)
    current_alt_msl = max(float(row.get("position_alt", 0.0) or 0.0) for row in target_rows)
    cruise_altitude_msl = max(20.0, current_alt_msl + float(altitude_gain_m))
    return {
        "mission_template": "last_known_point",
        "search_area": {
            "type": "point",
            "center": {
                "lat": center_lat,
                "lng": center_lng,
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
        "pos_ids": [int(pos_id) for pos_id in pos_ids],
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
        conflicts = detect_foreign_active_commands(
            client.get_json(GCS_ACTIVE_COMMANDS_ROUTE),
            allowed_command_ids=set(),
            watch_drone_ids=ids,
        )
        if conflicts:
            raise RuntimeError(
                "Detected foreign active command(s) targeting non-target drones during QuickScout validation: "
                f"{json.dumps(conflicts, indent=2)}"
            )
        telemetry = client.get_telemetry()
        if not _telemetry_has_ids(telemetry, ids):
            return False
        rows = {str(idx): telemetry[str(idx)] for idx in ids}
        if not all(_is_idle_baseline_row(row) for row in rows.values()):
            return False
        return rows

    return wait_for(_ready, label=f"non-target drones {ids} remain idle", timeout=timeout, interval=2.0)


def _probe_drone_live_armability(row: dict[str, Any]) -> dict[str, Any] | None:
    ip = str(row.get("ip") or "").strip()
    if not ip:
        return None

    query = urllib.parse.urlencode({"require_global_position": "true"})
    request = urllib.request.Request(
        f"http://{ip}:{int(getattr(Params, 'drone_api_port', 7070))}{DRONE_LIVE_ARMABILITY_ROUTE}?{query}",
        method="GET",
    )
    timeout = float(calculate_live_armability_request_timeout(params=Params))

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
            return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def wait_targets_launch_probe_ready(
    client: ApiClient,
    target_ids: list[int],
    *,
    timeout: int = 120,
    interval: float = 2.0,
) -> dict[str, dict[str, Any]]:
    def _ready():
        telemetry = client.get_telemetry()
        probe_results: dict[str, dict[str, Any]] = {}

        for target_id in target_ids:
            row = telemetry.get(str(target_id))
            if row is None:
                return False
            probe_payload = _probe_drone_live_armability(row)
            if not probe_payload:
                return False
            if not bool(probe_payload.get("success")) or not bool(probe_payload.get("ready")):
                return False
            probe_results[str(target_id)] = probe_payload

        return probe_results

    return wait_for(
        _ready,
        label=f"drones {target_ids} live launch-probe ready",
        timeout=timeout,
        interval=interval,
    )


def wait_target_airborne(
    client: ApiClient,
    target_id: int,
    *,
    baseline_altitude: float,
    min_gain: float,
    timeout: int = 180,
    allowed_command_ids: set[str] | None = None,
) -> dict[str, Any]:
    def _ready():
        conflicts = detect_foreign_active_commands(
            client.get_json(GCS_ACTIVE_COMMANDS_ROUTE),
            allowed_command_ids=allowed_command_ids or set(),
            watch_drone_ids=[target_id],
        )
        if conflicts:
            raise RuntimeError(
                "Detected foreign active command(s) targeting the QuickScout target drone during airborne wait: "
                f"{json.dumps(conflicts, indent=2)}"
            )
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


def wait_targets_airborne(
    client: ApiClient,
    target_ids: list[int],
    *,
    baseline_altitudes: dict[int, float],
    min_gain: float,
    timeout: int = 180,
    allowed_command_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    def _ready():
        conflicts = detect_foreign_active_commands(
            client.get_json(GCS_ACTIVE_COMMANDS_ROUTE),
            allowed_command_ids=allowed_command_ids or set(),
            watch_drone_ids=target_ids,
        )
        if conflicts:
            raise RuntimeError(
                "Detected foreign active command(s) targeting QuickScout launch drones during airborne wait: "
                f"{json.dumps(conflicts, indent=2)}"
            )
        telemetry = client.get_telemetry()
        rows: dict[str, dict[str, Any]] = {}
        for target_id in target_ids:
            row = telemetry.get(str(target_id))
            if row is None:
                return False
            if not _is_airborne_row(row, baseline_altitudes[target_id], min_gain=min_gain):
                return False
            rows[str(target_id)] = row
        return rows

    return wait_for(
        _ready,
        label=f"drones {target_ids} airborne with +{min_gain:.1f}m gain",
        timeout=timeout,
        interval=2.0,
    )


def wait_active_commands_clear(client: ApiClient, timeout: int = 120) -> dict[str, Any]:
    def _ready():
        payload = client.get_json(GCS_ACTIVE_COMMANDS_ROUTE)
        return payload if int(payload.get("total", 0) or 0) == 0 else False

    return wait_for(_ready, label="no active commands", timeout=timeout, interval=2.0)


def detect_foreign_active_commands(
    payload: dict[str, Any],
    *,
    allowed_command_ids: set[str],
    watch_drone_ids: list[int],
) -> list[dict[str, Any]]:
    watched = {str(drone_id) for drone_id in watch_drone_ids}
    if not watched:
        return []

    conflicts: list[dict[str, Any]] = []
    for command in payload.get("commands", []):
        command_id = str(command.get("command_id") or "")
        if command_id and command_id in allowed_command_ids:
            continue

        target_drones = [str(drone_id) for drone_id in command.get("target_drones") or []]
        if not watched.intersection(target_drones):
            continue

        conflicts.append(
            {
                "command_id": command_id or None,
                "mission_name": command.get("mission_name"),
                "mission_type": command.get("mission_type"),
                "status": command.get("status"),
                "phase": command.get("phase"),
                "target_drones": target_drones,
            }
        )

    return conflicts


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


def validate_findings_and_handoff(
    client: ApiClient,
    mission_id: str,
    *,
    reference_row: dict[str, Any],
) -> dict[str, Any]:
    lat = float(reference_row["position_lat"])
    lng = float(reference_row["position_long"])
    reported_by_drone = str(reference_row.get("hw_id") or reference_row.get("hw_ID") or "")

    finding = client.post_json(
        "/api/sar/findings",
        payload={
            "lat": lat,
            "lng": lng,
            "summary": "Runtime validator contact",
            "type": "clue",
            "priority": "high",
            "source": "operator_mark",
            "notes": "Created by QuickScout runtime validator.",
            "evidence_refs": ["img://runtime-validator-contact"],
        },
        query={"mission_id": mission_id},
    )
    finding_id = str(finding.get("id") or "")
    require(finding_id, f"QuickScout finding creation did not return an id: {json.dumps(finding, indent=2)}")

    updated_finding = client.request_json(
        "PATCH",
        f"/api/sar/findings/{urllib.parse.quote(finding_id, safe='')}",
        payload={
            "status": "confirmed",
            "reported_by_drone": reported_by_drone or None,
            "notes": "Validator confirmed the contact and attached a handoff reference.",
            "evidence_refs": [
                "img://runtime-validator-contact",
                "report://runtime-validator-brief",
            ],
        },
    )
    require(
        (updated_finding.get("status") or "") == "confirmed",
        f"QuickScout finding update did not persist confirmation: {json.dumps(updated_finding, indent=2)}",
    )

    handoff = client.get_json(f"/api/sar/mission/{mission_id}/handoff")
    require(
        int(handoff.get("finding_count", 0) or 0) >= 1,
        f"QuickScout handoff did not include findings: {json.dumps(handoff, indent=2)}",
    )
    require(
        int(handoff.get("confirmed_finding_count", 0) or 0) >= 1,
        f"QuickScout handoff did not include a confirmed finding: {json.dumps(handoff, indent=2)}",
    )
    require(
        int(handoff.get("evidence_ref_count", 0) or 0) >= 2,
        f"QuickScout handoff did not persist evidence refs: {json.dumps(handoff, indent=2)}",
    )
    require(
        "Runtime validator contact" in str(handoff.get("brief_text") or ""),
        f"QuickScout handoff brief did not mention the validated finding: {json.dumps(handoff, indent=2)}",
    )

    return {
        "finding": finding,
        "updated_finding": updated_finding,
        "handoff": handoff,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate QuickScout against a live GCS/SITL runtime.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="GCS API base URL")
    parser.add_argument("--drones", default=None, help="Comma-separated drone hardware IDs to observe")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=None, help="Space-separated drone hardware IDs to observe")
    parser.add_argument("--launch-drone-count", type=int, default=1, help="How many selected drones to include in the QuickScout launch package")
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
    require(
        1 <= int(args.launch_drone_count) <= len(selected_ids),
        f"--launch-drone-count must be between 1 and {len(selected_ids)} for selected fleet {selected_ids}",
    )
    client = ApiClient(args.base_url)

    artifacts: dict[str, Any] = {
        "selected_drone_ids": selected_ids,
        "launch_drone_count": int(args.launch_drone_count),
        "base_url": args.base_url,
        "stages": {},
    }

    health = wait_api_ready(client)
    artifacts["stages"]["health"] = health

    baseline_rows = wait_fleet_ready(client, selected_ids)
    artifacts["stages"]["baseline_ready"] = baseline_rows

    target_rows = select_target_drones(
        baseline_rows,
        selected_ids,
        target_count=int(args.launch_drone_count),
    )
    target_ids = [drone_id for drone_id, _ in target_rows]
    target_pos_ids = [int(row["pos_id"]) for _, row in target_rows]
    target_row_payloads = [row for _, row in target_rows]
    baseline_altitudes = {
        drone_id: float(row.get("position_alt", 0.0) or 0.0)
        for drone_id, row in target_rows
    }
    non_target_ids = [drone_id for drone_id in selected_ids if drone_id not in set(target_ids)]
    artifacts["stages"]["targets"] = {
        "target_drone_ids": target_ids,
        "target_pos_ids": target_pos_ids,
    }
    artifacts["stages"]["launch_probe_ready"] = wait_targets_launch_probe_ready(client, target_ids)

    plan_request = build_last_known_point_request(
        target_row_payloads,
        pos_ids=target_pos_ids,
        radius_m=args.point_radius_m,
        altitude_gain_m=args.altitude_gain_m,
        sweep_width_m=args.sweep_width_m,
        overlap_percent=args.overlap_percent,
        cruise_speed_ms=args.cruise_speed_ms,
        survey_speed_ms=args.survey_speed_ms,
    )
    artifacts["stages"]["plan_request"] = plan_request
    log(
        "PLANNING QuickScout runtime mission for "
        f"hw_ids={target_ids} pos_ids={target_pos_ids}"
    )
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
    require(
        sorted(int(pos_id) for pos_id in operation.get("pos_ids") or []) == sorted(target_pos_ids),
        f"Workspace target pos_ids mismatch: {operation.get('pos_ids')}",
    )
    require(
        len(plans) == len(target_pos_ids),
        f"Expected {len(target_pos_ids)} QuickScout plans for runtime validation, got {len(plans)}",
    )
    plan_pos_ids = sorted(int(plan.get("pos_id", -1)) for plan in plans)
    require(plan_pos_ids == sorted(target_pos_ids), f"QuickScout plan pos_ids mismatch: {plans}")
    target_hw_ids = sorted(str(plan.get("hw_id")) for plan in plans)
    require(
        target_hw_ids == sorted(str(target_id) for target_id in target_ids),
        f"QuickScout plan hw_ids mismatch. Expected {target_ids}, got {target_hw_ids}",
    )

    log(f"LAUNCHING QuickScout mission {mission_id} on hw_ids={target_hw_ids}")
    launch_response = client.post_json("/api/sar/mission/launch", query={"mission_id": mission_id})
    artifacts["stages"]["launch_response"] = launch_response
    require(bool(launch_response.get("success")), f"QuickScout launch did not succeed: {json.dumps(launch_response, indent=2)}")
    launched_hw_ids = sorted(str(hw_id) for hw_id in launch_response.get("launched_hw_ids", []))
    launch_command_ids = {
        str((submission.get("command") or {}).get("command_id"))
        for submission in launch_response.get("submissions", [])
        if (submission.get("command") or {}).get("command_id")
    }
    require(
        launched_hw_ids == target_hw_ids,
        f"QuickScout launched hw_ids mismatch. Expected {target_hw_ids}, got {launched_hw_ids}",
    )
    require(
        int(launch_response.get("drones_failed", 0) or 0) == 0,
        f"QuickScout launch reported failed drones: {json.dumps(launch_response, indent=2)}",
    )

    searching_status = wait_status_phase(client, mission_id, {"searching"})
    artifacts["stages"]["searching_status"] = searching_status

    airborne_rows = wait_targets_airborne(
        client,
        target_ids,
        baseline_altitudes=baseline_altitudes,
        min_gain=args.airborne_min_gain,
        allowed_command_ids=launch_command_ids,
    )
    artifacts["stages"]["target_airborne"] = airborne_rows

    if non_target_ids:
        artifacts["stages"]["non_target_idle_after_launch"] = wait_non_targets_idle(client, non_target_ids)

    pause_response = client.post_json(
        f"/api/sar/mission/{mission_id}/pause",
        query=[("pos_ids", pos_id) for pos_id in target_pos_ids],
    )
    artifacts["stages"]["pause_response"] = pause_response
    require(bool(pause_response.get("success")), f"QuickScout pause was not accepted: {json.dumps(pause_response, indent=2)}")
    require(
        sorted(str(hw_id) for hw_id in pause_response.get("accepted_hw_ids", [])) == target_hw_ids,
        f"Pause did not target the launched drones: {json.dumps(pause_response, indent=2)}",
    )
    pause_command = pause_response.get("command") or {}
    pause_command_id = pause_command.get("command_id")
    require(pause_command_id, "Pause response did not include a tracked command_id")
    pause_command_status = wait_command_terminal(client, pause_command_id, timeout=180)
    artifacts["stages"]["pause_command_status"] = pause_command_status
    require_command_success(
        pause_command_status,
        expected_accepts=len(target_ids),
        expected_successes=len(target_ids),
        label="QuickScout pause",
    )

    holding_status = wait_status_phase(client, mission_id, {"holding"}, timeout=90)
    artifacts["stages"]["holding_status"] = holding_status
    require(
        str((holding_status.get("control_availability") or {}).get("replan_enabled")).lower() == "true",
        "Holding status did not expose replan guidance",
    )

    artifacts["stages"]["findings_handoff"] = validate_findings_and_handoff(
        client,
        mission_id,
        reference_row=target_row_payloads[0],
    )

    resume_response = client.post_json(
        f"/api/sar/mission/{mission_id}/resume",
        query=[("pos_ids", pos_id) for pos_id in target_pos_ids],
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
        query=[*[("pos_ids", pos_id) for pos_id in target_pos_ids], ("return_behavior", args.abort_return_behavior)],
    )
    artifacts["stages"]["abort_response"] = abort_response
    require(bool(abort_response.get("success")), f"QuickScout abort was not accepted: {json.dumps(abort_response, indent=2)}")
    abort_command = abort_response.get("command") or {}
    abort_command_id = abort_command.get("command_id")
    require(abort_command_id, "Abort response did not include a tracked command_id")
    abort_command_status = wait_command_terminal(client, abort_command_id, timeout=420)
    artifacts["stages"]["abort_command_status"] = abort_command_status
    require_command_success(
        abort_command_status,
        expected_accepts=len(target_ids),
        expected_successes=len(target_ids),
        label="QuickScout abort",
    )

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
