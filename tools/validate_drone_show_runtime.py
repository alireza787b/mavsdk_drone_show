#!/usr/bin/env python3
"""
End-to-end Drone Show runtime validation for SITL fleets.

This validator exercises the operator-facing Drone Show workflow:

1. Optional fresh import of the stock SkyBrush show package
2. Readiness checks for show metadata, custom CSV metadata, and selected-fleet
   launch geometry from `/get-position-deviations`
3. Standard Drone Show in:
   - GLOBAL auto-origin mode
   - GLOBAL manual mode
   - LOCAL mode with delayed trigger
4. Custom CSV execution
5. One LOCAL-mode override drill where a single drone is landed mid-show and the
   remaining fleet is then landed explicitly

The script is intentionally conservative: it validates one clean baseline run per
mode before attempting the override drill that intentionally supersedes a live
mission.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests


SHOW_MISSION = 1
CUSTOM_SHOW_MISSION = 3
LAND = 101

TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "timeout"}


def log(message: str) -> None:
    print(message, flush=True)


@dataclass
class CommandRun:
    label: str
    command_id: str
    status: dict


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({"Accept": "application/json"})
        return session

    def _reset_session(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
        self.session = self._build_session()

    def get_json(self, path: str) -> dict:
        last_error: requests.RequestException | None = None
        for attempt in range(2):
            try:
                response = self.session.get(f"{self.base_url}{path}", timeout=20)
                response.raise_for_status()
                return response.json()
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= 1:
                    raise
                log(f"API GET retry for {path} after transport error: {exc}")
                self._reset_session()
        raise last_error or RuntimeError(f"GET failed for {path}")

    def post_json(self, path: str, payload: dict) -> dict:
        response = self.session.post(f"{self.base_url}{path}", json=payload, timeout=45)
        response.raise_for_status()
        return response.json()

    def post_file(self, path: str, file_path: Path) -> dict:
        with file_path.open("rb") as handle:
            response = self.session.post(
                f"{self.base_url}{path}",
                files={"file": (file_path.name, handle, "application/zip")},
                timeout=180,
            )
        response.raise_for_status()
        return response.json()

    def get_telemetry(self) -> dict[str, dict]:
        payload = self.get_json("/api/telemetry")
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def submit_command(
        self,
        mission_type: int,
        target_ids: Iterable[int],
        operator_label: str,
        *,
        trigger_time: int | None = None,
        **extra: Any,
    ) -> dict:
        payload = {
            "missionType": str(mission_type),
            "target_drones": [str(target_id) for target_id in target_ids],
            "triggerTime": str(trigger_time if trigger_time is not None else 0),
            "operatorLabel": operator_label,
            **extra,
        }
        response = self.post_json("/submit_command", payload)
        log(f"COMMAND {operator_label}: {response['command_id']} accepted={response.get('submitted_count')}")
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
            "started": executions.get("started"),
            "active": executions.get("active"),
            "received": executions.get("received"),
            "succeeded": executions.get("succeeded"),
            "failed": executions.get("failed"),
        },
        "error_summary": status.get("error_summary"),
    }


def wait_api_ready(client: ApiClient, timeout: int = 60) -> dict:
    def _ready():
        try:
            return client.get_json("/health")
        except requests.RequestException:
            return False

    return wait_for(_ready, label="GCS API health", timeout=timeout, interval=2.0)


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
        status = client.get_json(f"/command/{command_id}")
        last = status
        phase = status.get("phase")
        state = status.get("status")
        if desired_phase and phase == desired_phase:
            log(f"COMMAND {command_id} reached phase={phase}: {command_summary(status)}")
            return status
        if terminal and state in TERMINAL_STATUSES:
            log(f"COMMAND {command_id} terminal: {command_summary(status)}")
            return status
        time.sleep(1.0)
    raise RuntimeError(f"Timed out waiting for command {command_id}. Last status: {command_summary(last or {})}")


def build_show_zip(source_dir: Path) -> Path:
    drone_files = sorted(source_dir.glob("Drone *.csv"))
    require(drone_files, f"No Drone *.csv files found in {source_dir}")

    archive_fd, archive_path = tempfile.mkstemp(prefix="mds_show_", suffix=".zip")
    os.close(archive_fd)
    archive = Path(archive_path)

    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for csv_file in drone_files:
            bundle.write(csv_file, arcname=csv_file.name)

    return archive


def ensure_imported_show(client: ApiClient, source_dir: Path | None, expected_count: int) -> dict:
    if source_dir is not None:
        archive = build_show_zip(source_dir)
        try:
            response = client.post_file("/import-show", archive)
            log(f"IMPORT SHOW: {response.get('message', 'ok')}")
        finally:
            archive.unlink(missing_ok=True)

    show_info = client.get_json("/get-show-info")
    require(show_info.get("drone_count") == expected_count, f"Expected {expected_count} show drones, got {show_info}")
    return show_info


def ensure_custom_show_ready(client: ApiClient) -> dict:
    payload = client.get_json("/get-custom-show-info")
    require(payload.get("exists") is True, f"Custom CSV missing: {payload}")
    return payload


def idle_row(row: dict) -> bool:
    mission = int(row.get("mission", 0) or 0)
    state = int(row.get("state", 0) or 0)
    return (
        row.get("readiness_status") == "ready"
        and not bool(row.get("is_armed"))
        and mission == 0
        and state == 0
    )


def wait_for_idle(client: ApiClient, ids: list[int], timeout: int = 120) -> dict[str, dict]:
    def _ready():
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in ids):
            return False
        if all(idle_row(telemetry[str(idx)]) for idx in ids):
            return telemetry
        return False

    return wait_for(_ready, label=f"idle baseline for drones {ids}", timeout=timeout, interval=2.0)


def wait_for_pending_execution(client: ApiClient, ids: list[int], timeout: int = 30) -> dict[str, dict]:
    def _pending():
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in ids):
            return False
        for idx in ids:
            row = telemetry[str(idx)]
            mission = int(row.get("mission", 0) or 0)
            state = int(row.get("state", 0) or 0)
            if mission != SHOW_MISSION or state != 1:
                return False
        return telemetry

    return wait_for(_pending, label=f"mission-ready pending execution for drones {ids}", timeout=timeout, interval=1.0)


def wait_for_executing(client: ApiClient, ids: list[int], mission_type: int, timeout: int = 60) -> dict[str, dict]:
    def _executing():
        telemetry = client.get_telemetry()
        if not all(str(idx) in telemetry for idx in ids):
            return False
        for idx in ids:
            row = telemetry[str(idx)]
            mission = int(row.get("mission", 0) or 0)
            state = int(row.get("state", 0) or 0)
            if mission != mission_type or state != 2:
                return False
        return telemetry

    return wait_for(_executing, label=f"mission executing for drones {ids}", timeout=timeout, interval=1.0)


def wait_for_relative_altitude(client: ApiClient, target_id: int, baseline_alt: float, min_gain: float, timeout: int = 60) -> dict:
    def _airborne():
        telemetry = client.get_telemetry()
        row = telemetry.get(str(target_id))
        if not row:
            return False
        current_alt = row.get("position_alt")
        if current_alt is None:
            return False
        try:
            gain = float(current_alt) - float(baseline_alt)
        except (TypeError, ValueError):
            return False
        if gain >= min_gain:
            return row
        return False

    return wait_for(
        _airborne,
        label=f"drone {target_id} reaching +{min_gain:.1f}m relative altitude",
        timeout=timeout,
        interval=1.0,
    )


def check_deviation_signal(client: ApiClient, ids: list[int]) -> None:
    payload = client.get_json("/get-position-deviations")
    deviations = payload.get("deviations", {})
    missing = []
    blocked = []

    for drone_id in ids:
        row = deviations.get(str(drone_id)) or deviations.get(drone_id)
        if not isinstance(row, dict) or row.get("status") == "no_telemetry" or row.get("current") is None:
            missing.append(drone_id)
            continue
        if row.get("status") == "error":
            blocked.append({"drone_id": drone_id, "message": row.get("message")})

    require(not missing, f"Deviation endpoint missing live telemetry for drones {missing}: {payload.get('summary', {})}")
    require(
        not blocked,
        f"Deviation endpoint reports launch-blocking placement errors for selected drones: {blocked}",
    )


def wait_for_show_launch_ready(client: ApiClient, ids: list[int], timeout: int = 120) -> dict[str, dict]:
    deadline = time.time() + timeout
    last_error: RuntimeError | None = None

    while time.time() < deadline:
        remaining = max(1, int(deadline - time.time()))
        try:
            baseline = wait_for_idle(client, ids, timeout=min(remaining, 15))
            check_deviation_signal(client, ids)
            log(f"WAIT OK: launch-ready geometry for drones {ids}")
            return baseline
        except RuntimeError as exc:
            last_error = exc
            if time.time() >= deadline:
                break
            time.sleep(2.0)

    raise RuntimeError(
        f"Timed out waiting for launch-ready geometry for drones {ids}. Last error: {last_error}"
    )


def reset_sitl_fleet(client: ApiClient, repo_root: Path, ids: list[int], timeout: int = 180) -> dict[str, dict]:
    selected_ids = sorted({int(drone_id) for drone_id in ids})
    require(selected_ids, "No drone IDs supplied for SITL reset.")

    expected_ids = list(range(selected_ids[0], selected_ids[0] + len(selected_ids)))
    require(
        selected_ids == expected_ids,
        f"SITL reset only supports contiguous drone IDs today, got {selected_ids}",
    )

    command = ["bash", "multiple_sitl/create_dockers.sh", str(len(selected_ids))]
    if selected_ids[0] != 1:
        command.extend(["--start-id", str(selected_ids[0]), "--start-ip", str(selected_ids[0] + 1)])

    log(f"RESET SITL: {' '.join(command)} (cwd={repo_root})")
    try:
        completed = subprocess.run(
            command,
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            env=os.environ.copy(),
        )
    except subprocess.CalledProcessError as exc:
        stdout_tail = "\n".join((exc.stdout or "").splitlines()[-20:])
        stderr_tail = "\n".join((exc.stderr or "").splitlines()[-20:])
        raise RuntimeError(
            "SITL fleet reset failed.\n"
            f"stdout tail:\n{stdout_tail}\n"
            f"stderr tail:\n{stderr_tail}"
        ) from exc

    stdout_tail = "\n".join((completed.stdout or "").splitlines()[-12:])
    if stdout_tail:
        log(f"RESET SITL OUTPUT:\n{stdout_tail}")
    return wait_for_show_launch_ready(client, ids, timeout=timeout)


def submit_show_command_with_retry(
    client: ApiClient,
    mission_type: int,
    ids: list[int],
    label: str,
    *,
    readiness_timeout: int = 60,
    **kwargs: Any,
) -> dict:
    last_error: requests.HTTPError | None = None
    for attempt in range(2):
        try:
            return client.submit_command(mission_type, ids, label, **kwargs)
        except requests.HTTPError as exc:
            last_error = exc
            status_code = exc.response.status_code if exc.response is not None else None
            detail = ""
            if exc.response is not None:
                try:
                    detail = exc.response.text.strip()
                except Exception:
                    detail = ""
            if status_code != 400 or attempt >= 1:
                raise
            log(f"COMMAND {label}: retrying after HTTP 400{f' {detail}' if detail else ''}")
            wait_for_show_launch_ready(client, ids, timeout=readiness_timeout)
            time.sleep(3.0)
    raise last_error or RuntimeError(f"Failed to submit show command for {label}")


def run_show_mode(
    client: ApiClient,
    ids: list[int],
    *,
    label: str,
    auto_global_origin: bool,
    use_global_setpoints: bool,
    show_timeout: int,
    trigger_delay: int = 0,
) -> CommandRun:
    wait_for_show_launch_ready(client, ids, timeout=120)
    trigger_time = int(time.time()) + trigger_delay if trigger_delay > 0 else 0
    response = submit_show_command_with_retry(
        client,
        SHOW_MISSION,
        ids,
        label,
        trigger_time=trigger_time,
        readiness_timeout=90,
        auto_global_origin=auto_global_origin,
        use_global_setpoints=use_global_setpoints,
    )
    command_id = response["command_id"]

    if trigger_delay > 0:
        wait_for_pending_execution(client, ids, timeout=max(15, trigger_delay + 10))

    wait_for_command(client, command_id, desired_phase="in_progress", timeout=90)
    status = wait_for_command(client, command_id, terminal=True, timeout=show_timeout)
    require(status.get("outcome") == "completed", f"{label} did not complete cleanly: {command_summary(status)}")
    wait_for_idle(client, ids, timeout=120)
    return CommandRun(label=label, command_id=command_id, status=status)


def run_custom_show_mode(client: ApiClient, ids: list[int], *, label: str, timeout: int) -> CommandRun:
    wait_for_show_launch_ready(client, ids, timeout=120)
    response = submit_show_command_with_retry(
        client,
        CUSTOM_SHOW_MISSION,
        ids,
        label,
        trigger_time=0,
        readiness_timeout=90,
    )
    command_id = response["command_id"]
    wait_for_command(client, command_id, desired_phase="in_progress", timeout=90)
    status = wait_for_command(client, command_id, terminal=True, timeout=timeout)
    require(status.get("outcome") == "completed", f"{label} did not complete cleanly: {command_summary(status)}")
    wait_for_idle(client, ids, timeout=120)
    return CommandRun(label=label, command_id=command_id, status=status)


def run_override_drill(client: ApiClient, ids: list[int], *, label: str) -> dict[str, Any]:
    baseline = wait_for_show_launch_ready(client, ids, timeout=120)
    baseline_alt = float(baseline[str(ids[-1])]["position_alt"])

    response = submit_show_command_with_retry(
        client,
        SHOW_MISSION,
        ids,
        label,
        trigger_time=0,
        readiness_timeout=90,
        auto_global_origin=False,
        use_global_setpoints=False,
    )
    show_command_id = response["command_id"]

    wait_for_command(client, show_command_id, desired_phase="in_progress", timeout=90)
    wait_for_relative_altitude(client, ids[-1], baseline_alt, min_gain=4.0, timeout=60)

    singled_out = ids[-1]
    land_one = client.submit_command(LAND, [singled_out], f"{label}_land_one", trigger_time=0)
    land_one_status = wait_for_command(client, land_one["command_id"], terminal=True, timeout=120)
    require(
        land_one_status.get("outcome") in {"completed", "partial"},
        f"Single-drone land override failed: {command_summary(land_one_status)}",
    )

    def _others_still_executing():
        telemetry = client.get_telemetry()
        for idx in ids[:-1]:
            row = telemetry.get(str(idx))
            if not row:
                return False
            if int(row.get("mission", 0) or 0) != SHOW_MISSION or int(row.get("state", 0) or 0) != 2:
                return False
        singled = telemetry.get(str(singled_out))
        if not singled:
            return False
        return not bool(singled.get("is_armed")) or int(singled.get("mission", 0) or 0) != SHOW_MISSION

    wait_for(_others_still_executing, label="remaining drones continue after single-drone override", timeout=45)

    land_rest = client.submit_command(LAND, ids[:-1], f"{label}_land_rest", trigger_time=0)
    land_rest_status = wait_for_command(client, land_rest["command_id"], terminal=True, timeout=120)
    require(
        land_rest_status.get("outcome") in {"completed", "partial"},
        f"Fleet landing after override failed: {command_summary(land_rest_status)}",
    )

    show_status = wait_for_command(client, show_command_id, terminal=True, timeout=180)
    require(
        show_status.get("outcome") in {"partial", "failed", "cancelled", "superseded", "timeout", "completed"},
        f"Unexpected override-show outcome: {command_summary(show_status)}",
    )
    wait_for_idle(client, ids, timeout=180)

    return {
        "show_command": command_summary(show_status),
        "single_land": command_summary(land_one_status),
        "fleet_land": command_summary(land_rest_status),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Drone Show runtime behavior against a live GCS API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Base URL of the GCS API")
    parser.add_argument(
        "--drone-ids",
        nargs="+",
        type=int,
        default=[1, 2, 3, 4, 5],
        help="Selected live drone IDs to validate; unselected config slots may remain offline",
    )
    parser.add_argument(
        "--import-source-dir",
        type=Path,
        default=None,
        help="Optional directory of SkyBrush Drone *.csv files to zip and import before validation",
    )
    parser.add_argument(
        "--expected-show-count",
        type=int,
        default=5,
        help="Expected imported Drone Show metadata count; this remains the show package size, not the selected validation subset",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root used for SITL container recreation between mode runs",
    )
    parser.add_argument(
        "--skip-sitl-reset",
        action="store_true",
        help="Skip recreating SITL containers between internal validation runs",
    )
    args = parser.parse_args()

    client = ApiClient(args.base_url)
    results: dict[str, Any] = {
        "base_url": args.base_url,
        "drone_ids": args.drone_ids,
    }

    wait_api_ready(client)
    show_info = ensure_imported_show(client, args.import_source_dir, args.expected_show_count)
    custom_show = ensure_custom_show_ready(client)
    wait_for_show_launch_ready(client, args.drone_ids, timeout=120)

    results["show_info"] = show_info
    results["custom_show_info"] = custom_show
    results["runs"] = {}

    standard_timeout = int(max(360, (float(show_info["duration_ms"]) / 1000.0) + 150))
    custom_timeout = int(max(240, float(custom_show["duration_sec"]) + 120))

    results["runs"]["global_auto"] = command_summary(
        run_show_mode(
            client,
            args.drone_ids,
            label="codex-global_auto",
            auto_global_origin=True,
            use_global_setpoints=True,
            show_timeout=standard_timeout,
        ).status
    )
    if not args.skip_sitl_reset:
        reset_sitl_fleet(client, args.repo_root, args.drone_ids, timeout=180)
    results["runs"]["global_manual"] = command_summary(
        run_show_mode(
            client,
            args.drone_ids,
            label="codex-global_manual",
            auto_global_origin=False,
            use_global_setpoints=True,
            show_timeout=standard_timeout,
        ).status
    )
    if not args.skip_sitl_reset:
        reset_sitl_fleet(client, args.repo_root, args.drone_ids, timeout=180)
    results["runs"]["local_delayed"] = command_summary(
        run_show_mode(
            client,
            args.drone_ids,
            label="codex-local_delayed",
            auto_global_origin=False,
            use_global_setpoints=False,
            show_timeout=standard_timeout,
            trigger_delay=10,
        ).status
    )
    if not args.skip_sitl_reset:
        reset_sitl_fleet(client, args.repo_root, args.drone_ids, timeout=180)
    results["runs"]["custom_csv"] = command_summary(
        run_custom_show_mode(
            client,
            args.drone_ids,
            label="codex-custom_csv",
            timeout=custom_timeout,
        ).status
    )
    if not args.skip_sitl_reset:
        reset_sitl_fleet(client, args.repo_root, args.drone_ids, timeout=180)
    results["runs"]["override_drill"] = run_override_drill(
        client,
        args.drone_ids,
        label="codex-local_with_land_override",
    )

    log("VALIDATION COMPLETE")
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        log("Interrupted")
        raise SystemExit(130)
