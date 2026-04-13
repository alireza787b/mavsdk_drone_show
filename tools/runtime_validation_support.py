"""Shared support helpers for runtime validation tooling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


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


def write_json_report(path: Path | str | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
