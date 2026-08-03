"""Validation for heterogeneous per-target command payload fragments.

The public command model remains one command with one target set. Internal
mission orchestrators may supply a typed fragment per exact hardware ID when
the mission data differs by aircraft. The transport never accepts protected
identity, timing, or callback fields from those fragments.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from src.enums import Mission, resolve_executable_mission


_PROTECTED_FIELDS = frozenset(
    {
        "mission_type",
        "trigger_time",
        "command_id",
        "target_hw_id",
        "command_report_capability",
    }
)


def validate_per_target_payloads(
    mission: Mission,
    target_hw_ids: Sequence[str],
    payloads: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]] | None:
    """Return a detached canonical payload map or raise before tracker creation."""

    if payloads is None:
        return None
    if resolve_executable_mission(mission) != Mission.QUICKSCOUT:
        raise ValueError("per-target payloads are supported only for QUICKSCOUT")
    if not isinstance(payloads, Mapping):
        raise ValueError("per_target_payloads must be a mapping keyed by hardware ID")

    expected = list(target_hw_ids)
    if not expected:
        raise ValueError("per-target payloads require explicit target hardware IDs")
    if any(type(hw_id) is not str or not hw_id or hw_id != hw_id.strip() for hw_id in expected):
        raise ValueError("per-target payload target IDs must be canonical non-blank strings")

    supplied_keys = list(payloads.keys())
    if any(type(hw_id) is not str or not hw_id or hw_id != hw_id.strip() for hw_id in supplied_keys):
        raise ValueError("per-target payload keys must be canonical non-blank strings")
    if set(supplied_keys) != set(expected) or len(supplied_keys) != len(expected):
        raise ValueError("per-target payload keys must exactly match the command target set")

    normalized: dict[str, dict[str, Any]] = {}
    for hw_id in expected:
        fragment = payloads[hw_id]
        if not isinstance(fragment, Mapping):
            raise ValueError(f"per-target payload for {hw_id} must be an object")
        fragment_copy = dict(fragment)
        protected = sorted(_PROTECTED_FIELDS.intersection(fragment_copy))
        if protected:
            raise ValueError(
                f"per-target payload for {hw_id} cannot override protected field(s): "
                + ", ".join(protected)
            )
        if set(fragment_copy) != {"waypoints"}:
            raise ValueError(
                f"QuickScout per-target payload for {hw_id} must contain only waypoints"
            )
        waypoints = fragment_copy.get("waypoints")
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError(f"QuickScout per-target waypoints for {hw_id} must be a non-empty array")
        if any(not isinstance(waypoint, Mapping) for waypoint in waypoints):
            raise ValueError(f"QuickScout per-target waypoints for {hw_id} must contain objects")
        # JSON serialization is part of the dispatch/idempotency contract. Fail
        # now rather than after the command has crossed the tracker boundary.
        try:
            encoded = json.dumps(fragment_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"per-target payload for {hw_id} is not JSON serializable") from exc
        normalized[hw_id] = json.loads(encoded)
    return normalized


def per_target_payload_digests(payloads: Mapping[str, Mapping[str, Any]] | None) -> dict[str, str]:
    """Return compact audit fingerprints without storing full mission assets in tracker state."""

    if not payloads:
        return {}
    return {
        hw_id: hashlib.sha256(
            json.dumps(fragment, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        for hw_id, fragment in payloads.items()
    }


__all__ = ["per_target_payload_digests", "validate_per_target_payloads"]
