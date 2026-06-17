"""Shared support helpers for runtime validation tooling."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable

from src.gcs_api_routes import GCS_SYSTEM_RUNTIME_STATUS_ROUTE


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def normalize_drone_ids(ids: Iterable[int]) -> list[int]:
    """Return sorted unique hardware IDs."""
    normalized = sorted({int(drone_id) for drone_id in ids})
    require(normalized, "No drone IDs supplied.")
    return normalized


def contiguous_fleet_reset_parameters(drone_ids: Iterable[int]) -> dict[str, int]:
    """Return the canonical contiguous-fleet reset parameters."""
    selected_ids = normalize_drone_ids(drone_ids)
    expected_ids = list(range(selected_ids[0], selected_ids[0] + len(selected_ids)))
    require(
        selected_ids == expected_ids,
        f"SITL reset only supports contiguous drone IDs today, got {selected_ids}",
    )
    return {
        "target_count": len(selected_ids),
        "start_id": selected_ids[0],
        "start_ip": selected_ids[0] + 1,
    }


def parse_csv_drone_ids(raw: str) -> list[int]:
    ids = [int(part.strip()) for part in str(raw).split(",") if part.strip()]
    return normalize_drone_ids(ids)


def build_sitl_reset_command(drone_ids: Iterable[int]) -> list[str]:
    """Build the contiguous-fleet recreate command used for clean SITL resets."""
    params = contiguous_fleet_reset_parameters(drone_ids)

    command = ["bash", "multiple_sitl/create_dockers.sh", str(params["target_count"])]
    if params["start_id"] != 1:
        command.extend(["--start-id", str(params["start_id"]), "--start-ip", str(params["start_ip"])])
    return command


def require_sitl_runtime_status(payload: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless the target process and configured runtime are SITL."""

    mode = str(payload.get("mode") or "").strip().lower()
    configured_mode = str(payload.get("configured_mode") or "").strip().lower()
    configured_sim_mode = payload.get("configured_sim_mode")
    restart_required = bool(payload.get("restart_required"))
    require(mode == "sitl", f"Refusing SITL validation against target runtime mode {mode or 'unknown'}")
    require(
        configured_mode == "sitl" and configured_sim_mode is True,
        "Refusing SITL validation because the configured runtime is not canonical SITL",
    )
    require(
        not restart_required,
        "Refusing SITL validation because the configured and running runtime modes are not reconciled",
    )
    return payload


def fetch_and_require_sitl_runtime(base_url: str, *, timeout_sec: float = 5.0) -> dict[str, Any]:
    """Read and validate the target runtime identity before test-side mutations."""

    url = f"{str(base_url).rstrip('/')}{GCS_SYSTEM_RUNTIME_STATUS_ROUTE}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise RuntimeError(f"Cannot verify SITL target identity at {url}: {exc}") from exc
    require(isinstance(payload, dict), "SITL runtime-status response must be a JSON object")
    return require_sitl_runtime_status(payload)


def write_json_report(path: Path | str | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
