#!/usr/bin/env python3
"""
End-to-end Mission Config / origin validation for SITL fleets.

This validator exercises the saved configuration surfaces used by the operator
configuration workflows rather than mission execution alone:

1. Wait for the GCS API and inspect current runtime policy
2. Snapshot fleet config, swarm config, and origin state
3. Validate a deliberate fleet collision payload via the validation-only route
4. Save safe metadata-only fleet config edits and confirm round-trip preserve of
   custom fields
5. Save a safe full swarm-config mutation, then patch one assignment and confirm
   both canonical write paths round-trip correctly
6. Compute origin from live telemetry, persist a near-equivalent origin update,
   and confirm the canonical read/bootstrap/global-origin/deviations surfaces
7. Restore the original state and verify cleanup

This validator is intentionally conservative:

- it forces `commit=false` on temporary fleet/swarm config mutations so a live
  GCS with git auto-push enabled does not create accidental commits
- it restores exact origin-file presence/content on disk so hosts that relied on
  packaged SITL default origin do not keep an unintended local override
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.runtime_validation_support import normalize_drone_ids, parse_csv_drone_ids, write_json_report

try:
    from src.gcs_api_routes import (
        GCS_CONFIG_FLEET_ROUTE,
        GCS_CONFIG_FLEET_VALIDATION_ROUTE,
        GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE,
        GCS_CONFIG_SWARM_ROUTE,
        GCS_FLEET_TELEMETRY_ROUTE,
        GCS_NAVIGATION_GLOBAL_ORIGIN_ROUTE,
        GCS_ORIGIN_BOOTSTRAP_ROUTE,
        GCS_ORIGIN_COMPUTE_ROUTE,
        GCS_ORIGIN_DEVIATIONS_ROUTE,
        GCS_ORIGIN_ROUTE,
        GCS_SYSTEM_GCS_CONFIG_ROUTE,
        GCS_SYSTEM_HEALTH_ROUTE,
    )
except Exception:  # pragma: no cover - fallback only
    GCS_SYSTEM_HEALTH_ROUTE = "/api/v1/system/health"
    GCS_SYSTEM_GCS_CONFIG_ROUTE = "/api/v1/system/gcs-config"
    GCS_CONFIG_FLEET_ROUTE = "/api/v1/config/fleet"
    GCS_CONFIG_FLEET_VALIDATION_ROUTE = "/api/v1/config/fleet/validation"
    GCS_CONFIG_SWARM_ROUTE = "/api/v1/config/swarm"
    GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE = "/api/v1/config/swarm/assignments/{hw_id}"
    GCS_FLEET_TELEMETRY_ROUTE = "/api/v1/fleet/telemetry"
    GCS_ORIGIN_ROUTE = "/api/v1/origin"
    GCS_ORIGIN_BOOTSTRAP_ROUTE = "/api/v1/origin/bootstrap"
    GCS_ORIGIN_COMPUTE_ROUTE = "/api/v1/origin/compute"
    GCS_ORIGIN_DEVIATIONS_ROUTE = "/api/v1/origin/deviations"
    GCS_NAVIGATION_GLOBAL_ORIGIN_ROUTE = "/api/v1/navigation/global-origin"


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

    def get_json(self, path: str) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.base_url}{path}", timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

    def post_json(self, path: str, payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
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

    def put_json(self, path: str, payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(format_http_error(exc)) from exc

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
            raise RuntimeError(format_http_error(exc)) from exc

    def get_fleet_config(self) -> list[dict[str, Any]]:
        payload = self.get_json(GCS_CONFIG_FLEET_ROUTE)
        require(isinstance(payload, list), f"Unexpected fleet-config payload: {type(payload).__name__}")
        return payload

    def validate_fleet_config(self, payload: list[dict[str, Any]]) -> dict[str, Any]:
        return self.post_json(GCS_CONFIG_FLEET_VALIDATION_ROUTE, payload)

    def put_fleet_config(self, payload: list[dict[str, Any]], *, commit: bool = False) -> dict[str, Any]:
        commit_value = "true" if commit else "false"
        return self.put_json(f"{GCS_CONFIG_FLEET_ROUTE}?commit={commit_value}", payload)

    def get_swarm_config(self) -> dict[str, Any]:
        payload = self.get_json(GCS_CONFIG_SWARM_ROUTE)
        require(isinstance(payload, dict) and isinstance(payload.get("assignments"), list), "Unexpected swarm-config payload")
        return payload

    def put_swarm_config(self, payload: dict[str, Any], *, commit: bool = False) -> dict[str, Any]:
        commit_value = "true" if commit else "false"
        return self.put_json(f"{GCS_CONFIG_SWARM_ROUTE}?commit={commit_value}", payload)

    def patch_swarm_assignment(self, hw_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        return self.patch_json(GCS_CONFIG_SWARM_ASSIGNMENT_ROUTE_TEMPLATE.format(hw_id=int(hw_id)), payload)

    def get_telemetry(self) -> dict[str, dict[str, Any]]:
        payload = self.get_json(GCS_FLEET_TELEMETRY_ROUTE)
        telemetry = payload.get("telemetry", {})
        return {str(key): value for key, value in telemetry.items()}

    def get_origin(self) -> dict[str, Any]:
        return self.get_json(GCS_ORIGIN_ROUTE)

    def put_origin(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.put_json(GCS_ORIGIN_ROUTE, payload)

    def get_origin_bootstrap(self) -> dict[str, Any]:
        return self.get_json(GCS_ORIGIN_BOOTSTRAP_ROUTE)

    def get_global_origin(self) -> dict[str, Any]:
        return self.get_json(GCS_NAVIGATION_GLOBAL_ORIGIN_ROUTE)

    def compute_origin(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.post_json(GCS_ORIGIN_COMPUTE_ROUTE, payload)

    def get_origin_deviations(self) -> dict[str, Any]:
        return self.get_json(GCS_ORIGIN_DEVIATIONS_ROUTE)

    def get_gcs_config(self) -> dict[str, Any]:
        return self.get_json(GCS_SYSTEM_GCS_CONFIG_ROUTE)


def wait_for(predicate, *, label: str, timeout: int = 60, interval: float = 1.0):
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
            return client.get_json(GCS_SYSTEM_HEALTH_ROUTE)
        except Exception:
            return False

    return wait_for(_ready, label="GCS API health endpoint", timeout=timeout, interval=2.0)


def fleet_by_hw_id(entries: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for entry in entries:
        try:
            hw_id = int(entry.get("hw_id"))
        except (TypeError, ValueError):
            continue
        result[hw_id] = entry
    return result


def swarm_assignments_by_hw_id(payload: dict[str, Any] | list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    assignments = payload if isinstance(payload, list) else payload.get("assignments", [])
    result: dict[int, dict[str, Any]] = {}
    for entry in assignments:
        try:
            hw_id = int(entry.get("hw_id"))
        except (TypeError, ValueError):
            continue
        result[hw_id] = entry
    return result


def build_collision_validation_payload(entries: list[dict[str, Any]], selected_ids: list[int]) -> list[dict[str, Any]] | None:
    if len(selected_ids) < 2:
        return None

    cloned = copy.deepcopy(entries)
    index_by_hw = {
        int(entry.get("hw_id")): index
        for index, entry in enumerate(cloned)
        if entry.get("hw_id") is not None
    }
    first_id, second_id = selected_ids[:2]
    if first_id not in index_by_hw or second_id not in index_by_hw:
        return None

    first_pos_id = int(cloned[index_by_hw[first_id]].get("pos_id", first_id))
    cloned[index_by_hw[second_id]]["pos_id"] = first_pos_id
    return cloned


def build_fleet_metadata_update(entries: list[dict[str, Any]], selected_ids: list[int], *, suffix: str) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    cloned = copy.deepcopy(entries)
    index_by_hw = {
        int(entry.get("hw_id")): index
        for index, entry in enumerate(cloned)
        if entry.get("hw_id") is not None
    }
    expected: dict[int, dict[str, Any]] = {}
    for hw_id in selected_ids:
        index = index_by_hw.get(int(hw_id))
        if index is None:
            continue
        entry = cloned[index]
        base_callsign = str(entry.get("callsign") or f"SITL-{int(hw_id):02d}")
        callsign = f"{base_callsign}{suffix}"
        notes = f"sitl-config-validator:{int(hw_id)}"
        maintenance_tag = f"sitl-{int(hw_id)}-config"
        entry["callsign"] = callsign
        entry["notes"] = notes
        entry["maintenance_tag"] = maintenance_tag
        expected[int(hw_id)] = {
            "callsign": callsign,
            "notes": notes,
            "maintenance_tag": maintenance_tag,
        }
    return cloned, expected


def build_slot_reassignment_update(
    entries: list[dict[str, Any]],
    selected_ids: list[int],
) -> tuple[list[dict[str, Any]] | None, dict[int, int], tuple[int, int] | None]:
    cloned = copy.deepcopy(entries)
    index_by_hw = {
        int(entry.get("hw_id")): index
        for index, entry in enumerate(cloned)
        if entry.get("hw_id") is not None
    }

    candidate_ids = [int(hw_id) for hw_id in selected_ids if int(hw_id) in index_by_hw]
    for first_id in candidate_ids:
        for second_id in candidate_ids:
            if second_id == first_id:
                continue
            first_index = index_by_hw[first_id]
            second_index = index_by_hw[second_id]
            first_pos = int(cloned[first_index].get("pos_id", first_id))
            second_pos = int(cloned[second_index].get("pos_id", second_id))
            if first_pos == second_pos:
                continue
            cloned[first_index]["pos_id"] = second_pos
            cloned[second_index]["pos_id"] = first_pos
            return cloned, {first_id: second_pos, second_id: first_pos}, (first_id, second_id)

    return None, {}, None


def select_swarm_target(assignments: dict[int, dict[str, Any]], selected_ids: list[int]) -> int:
    for hw_id in selected_ids:
        entry = assignments.get(int(hw_id))
        if entry and int(entry.get("follow", 0) or 0) > 0:
            return int(hw_id)
    for hw_id in selected_ids:
        if int(hw_id) in assignments:
            return int(hw_id)
    raise RuntimeError(f"No saved swarm assignment found for selected drones {selected_ids}")


def build_swarm_put_update(payload: dict[str, Any], *, target_hw_id: int, offset_delta: float) -> tuple[dict[str, Any], dict[str, Any]]:
    cloned = copy.deepcopy(payload)
    assignments = cloned.get("assignments", [])
    for entry in assignments:
        if int(entry.get("hw_id", 0)) != int(target_hw_id):
            continue
        entry["offset_x"] = float(entry.get("offset_x", 0.0) or 0.0) + float(offset_delta)
        entry["offset_z"] = float(entry.get("offset_z", 0.0) or 0.0) + 0.25
        return cloned, copy.deepcopy(entry)
    raise RuntimeError(f"Failed to find swarm assignment for hw_id={target_hw_id}")


def build_swarm_patch_update(current_assignment: dict[str, Any], *, patch_delta: float) -> tuple[dict[str, Any], dict[str, Any]]:
    updated = copy.deepcopy(current_assignment)
    updated["offset_y"] = float(updated.get("offset_y", 0.0) or 0.0) + float(patch_delta)
    patch_payload = {
        "offset_y": updated["offset_y"],
        "offset_z": updated.get("offset_z", 0.0),
    }
    return patch_payload, updated


def select_origin_compute_source(
    *,
    selected_ids: list[int],
    fleet_entries: list[dict[str, Any]],
    telemetry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    fleet_index = fleet_by_hw_id(fleet_entries)
    for hw_id in selected_ids:
        entry = fleet_index.get(int(hw_id))
        row = telemetry.get(str(hw_id))
        if not entry or not row:
            continue
        lat = row.get("position_lat")
        lon = row.get("position_long")
        if lat in (None, "") or lon in (None, ""):
            continue
        return {
            "hw_id": int(hw_id),
            "pos_id": int(entry.get("pos_id", hw_id)),
            "current_lat": float(lat),
            "current_lon": float(lon),
        }
    raise RuntimeError(f"No telemetry-backed origin-compute source found for drones {selected_ids}")


def load_origin_file_snapshot(repo_root: Path) -> dict[str, Any]:
    origin_path = repo_root / "data" / "origin.json"
    if not origin_path.exists():
        return {"exists": False, "path": str(origin_path), "content": None}
    return {
        "exists": True,
        "path": str(origin_path),
        "content": origin_path.read_text(encoding="utf-8"),
    }


def restore_origin_file_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    origin_path = Path(snapshot["path"])
    origin_path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.get("exists"):
        origin_path.write_text(str(snapshot.get("content") or ""), encoding="utf-8")
        return {"status": "restored_file", "path": str(origin_path)}
    if origin_path.exists():
        origin_path.unlink()
        return {"status": "removed_override", "path": str(origin_path)}
    return {"status": "already_absent", "path": str(origin_path)}


def resolve_selected_ids(args: argparse.Namespace) -> list[int]:
    if getattr(args, "drone_ids", None):
        return normalize_drone_ids(args.drone_ids)
    if getattr(args, "drones", None):
        return parse_csv_drone_ids(args.drones)
    return [1, 2, 3]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Mission Config, swarm config, and origin runtime workflows.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5030", help="GCS API base URL")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help="Runtime repo root used to preserve exact origin-file state")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional JSON report output path")
    parser.add_argument("--drone-ids", nargs="+", type=int, default=[1, 2, 3], help="Selected hardware IDs to validate")
    parser.add_argument("--drones", default=None, help="Fallback CSV drone selection argument")
    parser.add_argument("--metadata-suffix", default="-CFG", help="Suffix appended to temporary validator callsigns")
    parser.add_argument("--origin-altitude-delta", type=float, default=0.5, help="Temporary origin altitude delta used while validating origin write/read routes")
    parser.add_argument("--swarm-put-offset-delta", type=float, default=1.25, help="Offset delta used for the full swarm-config PUT mutation")
    parser.add_argument("--swarm-patch-offset-delta", type=float, default=2.0, help="Offset delta used for the assignment PATCH mutation")
    args = parser.parse_args()
    args.repo_root = args.repo_root.resolve()
    args.drone_ids = resolve_selected_ids(args)
    args.json_output = args.json_output.resolve() if args.json_output is not None else None
    return args


def main() -> int:
    args = parse_args()
    client = ApiClient(args.base_url)

    results: dict[str, Any] = {
        "base_url": args.base_url,
        "repo_root": str(args.repo_root),
        "drone_ids": args.drone_ids,
        "result": "FAIL",
    }

    original_fleet: list[dict[str, Any]] | None = None
    original_swarm: dict[str, Any] | None = None
    original_origin_file: dict[str, Any] | None = None

    try:
        results["health"] = wait_api_ready(client)
        gcs_config = client.get_gcs_config()
        results["gcs_config"] = gcs_config
        if gcs_config.get("git_auto_push"):
            results["git_auto_push_bypassed"] = True

        original_fleet = client.get_fleet_config()
        original_swarm = client.get_swarm_config()
        original_origin = client.get_origin()
        original_origin_file = load_origin_file_snapshot(args.repo_root)

        results["original_origin"] = original_origin
        results["origin_file_snapshot"] = {
            "exists": bool(original_origin_file["exists"]),
            "path": original_origin_file["path"],
        }

        fleet_index = fleet_by_hw_id(original_fleet)
        require(
            all(int(hw_id) in fleet_index for hw_id in args.drone_ids),
            f"Fleet config does not contain all selected drones {args.drone_ids}",
        )

        collision_payload = build_collision_validation_payload(original_fleet, args.drone_ids)
        if collision_payload is not None:
            collision_report = client.validate_fleet_config(collision_payload)
            results["validation_only_collision"] = collision_report
            summary = collision_report.get("summary") or {}
            require(
                int(summary.get("duplicates_count", 0) or 0) >= 1,
                "Validation-only collision payload did not report a duplicate pos_id warning",
            )

        mutated_fleet, expected_metadata = build_fleet_metadata_update(
            original_fleet,
            args.drone_ids,
            suffix=args.metadata_suffix,
        )
        save_fleet_result = client.put_fleet_config(mutated_fleet, commit=False)
        results["fleet_save"] = save_fleet_result
        roundtrip_fleet = fleet_by_hw_id(client.get_fleet_config())
        for hw_id, expected in expected_metadata.items():
            row = roundtrip_fleet.get(int(hw_id))
            require(row is not None, f"Round-trip fleet config missing hw_id={hw_id}")
            for key, value in expected.items():
                require(row.get(key) == value, f"Fleet config did not preserve {key} for hw_id={hw_id}")
        results["fleet_roundtrip"] = {str(hw_id): expected for hw_id, expected in expected_metadata.items()}

        slot_reassignment_payload, swapped_slots, swapped_pair = build_slot_reassignment_update(
            mutated_fleet,
            args.drone_ids,
        )
        if slot_reassignment_payload is not None and swapped_pair is not None:
            original_swarm_by_hw = swarm_assignments_by_hw_id(original_swarm)
            slot_reassignment_result = client.put_fleet_config(slot_reassignment_payload, commit=False)
            results["slot_reassignment"] = {
                "save": slot_reassignment_result,
                "pair": {"hw_ids": list(swapped_pair)},
                "swapped_slots": {str(hw_id): pos_id for hw_id, pos_id in swapped_slots.items()},
            }

            swapped_fleet = fleet_by_hw_id(client.get_fleet_config())
            for hw_id, expected_pos_id in swapped_slots.items():
                row = swapped_fleet.get(int(hw_id))
                require(row is not None, f"Slot reassignment round-trip missing hw_id={hw_id}")
                require(
                    int(row.get("pos_id", 0)) == int(expected_pos_id),
                    f"Slot reassignment did not persist pos_id for hw_id={hw_id}",
                )

            swapped_swarm = swarm_assignments_by_hw_id(client.get_swarm_config())
            for hw_id in args.drone_ids:
                require(
                    swapped_swarm.get(int(hw_id)) == original_swarm_by_hw.get(int(hw_id)),
                    f"Smart Swarm follow ownership drifted during slot reassignment for hw_id={hw_id}",
                )

        swarm_target_hw_id = select_swarm_target(swarm_assignments_by_hw_id(original_swarm), args.drone_ids)
        mutated_swarm_payload, expected_swarm_put = build_swarm_put_update(
            original_swarm,
            target_hw_id=swarm_target_hw_id,
            offset_delta=args.swarm_put_offset_delta,
        )
        put_swarm_result = client.put_swarm_config(mutated_swarm_payload, commit=False)
        results["swarm_put"] = put_swarm_result

        current_swarm = client.get_swarm_config()
        current_assignment = swarm_assignments_by_hw_id(current_swarm)[swarm_target_hw_id]
        require(
            float(current_assignment.get("offset_x", 0.0) or 0.0) == float(expected_swarm_put["offset_x"]),
            f"Swarm config PUT did not update offset_x for hw_id={swarm_target_hw_id}",
        )

        patch_payload, expected_swarm_patch = build_swarm_patch_update(
            current_assignment,
            patch_delta=args.swarm_patch_offset_delta,
        )
        patch_result = client.patch_swarm_assignment(swarm_target_hw_id, patch_payload)
        results["swarm_patch"] = patch_result

        patched_swarm = client.get_swarm_config()
        patched_assignment = swarm_assignments_by_hw_id(patched_swarm)[swarm_target_hw_id]
        require(
            float(patched_assignment.get("offset_y", 0.0) or 0.0) == float(expected_swarm_patch["offset_y"]),
            f"Swarm config PATCH did not update offset_y for hw_id={swarm_target_hw_id}",
        )
        results["swarm_roundtrip"] = {
            "target_hw_id": swarm_target_hw_id,
            "after_put": expected_swarm_put,
            "after_patch": expected_swarm_patch,
        }

        telemetry = client.get_telemetry()
        origin_compute_source = select_origin_compute_source(
            selected_ids=args.drone_ids,
            fleet_entries=original_fleet,
            telemetry=telemetry,
        )
        results["origin_compute_source"] = origin_compute_source

        compute_result = client.compute_origin(
            {
                "current_lat": origin_compute_source["current_lat"],
                "current_lon": origin_compute_source["current_lon"],
                "pos_id": origin_compute_source["pos_id"],
            }
        )
        results["origin_compute"] = compute_result
        require(compute_result.get("status") == "success", f"Origin compute failed: {compute_result}")

        temp_origin_payload = {
            "lat": float(compute_result["lat"]),
            "lon": float(compute_result["lon"]),
            "alt": float(original_origin.get("alt", 0.0) or 0.0) + float(args.origin_altitude_delta),
            "alt_source": "validator",
        }
        saved_origin = client.put_origin(temp_origin_payload)
        bootstrap_origin = client.get_origin_bootstrap()
        global_origin = client.get_global_origin()
        deviations = client.get_origin_deviations()

        require(float(saved_origin["lat"]) == float(temp_origin_payload["lat"]), "Saved origin lat mismatch")
        require(float(saved_origin["lon"]) == float(temp_origin_payload["lon"]), "Saved origin lon mismatch")
        require(float(saved_origin["alt"]) == float(temp_origin_payload["alt"]), "Saved origin alt mismatch")
        require(float(bootstrap_origin["lat"]) == float(temp_origin_payload["lat"]), "Bootstrap origin lat mismatch")
        require(float(global_origin["latitude"]) == float(temp_origin_payload["lat"]), "Global origin latitude mismatch")
        require(bool(global_origin.get("has_origin")), "Global origin should report has_origin=true")

        deviation_payload = deviations.get("deviations", {}) if isinstance(deviations, dict) else {}
        require(
            all(str(hw_id) in deviation_payload or int(hw_id) in deviation_payload for hw_id in args.drone_ids),
            f"Origin deviations missing selected drone IDs {args.drone_ids}",
        )
        results["origin_roundtrip"] = {
            "saved": saved_origin,
            "bootstrap": bootstrap_origin,
            "global_origin": global_origin,
        }
        results["origin_deviations_keys"] = sorted(str(key) for key in deviation_payload.keys())

        results["result"] = "PASS"
        return 0
    except Exception as exc:
        results["error"] = str(exc)
        return 1
    finally:
        cleanup: dict[str, Any] = {"steps": []}

        if original_fleet is not None:
            try:
                cleanup["steps"].append({"fleet_restore": client.put_fleet_config(original_fleet, commit=False)})
            except Exception as exc:
                cleanup.setdefault("errors", []).append(f"fleet_restore: {exc}")

        if original_swarm is not None:
            try:
                cleanup["steps"].append({"swarm_restore": client.put_swarm_config(original_swarm, commit=False)})
            except Exception as exc:
                cleanup.setdefault("errors", []).append(f"swarm_restore: {exc}")

        if original_origin_file is not None:
            try:
                cleanup["steps"].append({"origin_file_restore": restore_origin_file_snapshot(original_origin_file)})
            except Exception as exc:
                cleanup.setdefault("errors", []).append(f"origin_restore: {exc}")

        try:
            if original_fleet is not None:
                restored_fleet = fleet_by_hw_id(client.get_fleet_config())
                original_fleet_index = fleet_by_hw_id(original_fleet)
                for hw_id in args.drone_ids:
                    require(
                        restored_fleet.get(int(hw_id)) == original_fleet_index.get(int(hw_id)),
                        f"Fleet restore mismatch for hw_id={hw_id}",
                    )
            if original_swarm is not None:
                restored_swarm = swarm_assignments_by_hw_id(client.get_swarm_config())
                original_swarm_index = swarm_assignments_by_hw_id(original_swarm)
                for hw_id in args.drone_ids:
                    require(
                        restored_swarm.get(int(hw_id)) == original_swarm_index.get(int(hw_id)),
                        f"Swarm restore mismatch for hw_id={hw_id}",
                    )
            if original_origin_file is not None:
                cleanup["restored_origin"] = client.get_origin()
        except Exception as exc:
            cleanup.setdefault("errors", []).append(f"post_restore_verify: {exc}")

        results["cleanup"] = cleanup
        if cleanup.get("errors"):
            results["result"] = "FAIL"
        write_json_report(args.json_output, results)


if __name__ == "__main__":
    raise SystemExit(main())
