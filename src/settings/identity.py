"""Canonical node identity helpers."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .runtime import get_node_identity_path, preload_local_env

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NodeIdentityInfo:
    """Resolved node identity and provenance."""

    hw_id: Optional[int]
    source: str
    node_uuid: Optional[str] = None
    path: Optional[str] = None


def _coerce_hw_id(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_node_identity(path: str | Path | None = None) -> dict[str, Any] | None:
    preload_local_env()

    identity_path = Path(path) if path is not None else get_node_identity_path()
    if not identity_path.exists():
        return None

    try:
        with identity_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as exc:  # pragma: no cover - defensive logging path
        logger.warning("Failed to read node identity manifest %s: %s", identity_path, exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("Node identity manifest %s did not contain an object payload", identity_path)
        return None

    return payload


def resolve_hw_id_info(hw_id: Optional[int] = None) -> NodeIdentityInfo:
    """
    Resolve canonical hardware identity.

    Priority:
    1. explicit argument
    2. MDS_HW_ID env/local.env
    3. /etc/mds/node_identity.json
    """

    preload_local_env()

    resolved_explicit = _coerce_hw_id(hw_id)
    if hw_id is not None:
        if resolved_explicit is None:
            logger.error("Provided hw_id is not a valid integer: %r", hw_id)
            return NodeIdentityInfo(hw_id=None, source="explicit-invalid")
        return NodeIdentityInfo(hw_id=resolved_explicit, source="explicit")

    env_hw_id = _coerce_hw_id(os.environ.get("MDS_HW_ID"))
    if env_hw_id is not None:
        return NodeIdentityInfo(hw_id=env_hw_id, source="env:MDS_HW_ID")

    raw_env_hw_id = os.environ.get("MDS_HW_ID")
    if raw_env_hw_id:
        logger.error("MDS_HW_ID is not a valid integer: %s", raw_env_hw_id)

    manifest = load_node_identity()
    if manifest is not None:
        manifest_hw_id = _coerce_hw_id(manifest.get("hw_id"))
        if manifest_hw_id is not None:
            return NodeIdentityInfo(
                hw_id=manifest_hw_id,
                source="file:node_identity",
                node_uuid=manifest.get("node_uuid"),
                path=str(get_node_identity_path()),
            )
        if manifest.get("hw_id") not in (None, ""):
            logger.error("node_identity.json hw_id is not a valid integer: %r", manifest.get("hw_id"))

    logger.error(
        "Hardware ID not found. Checked MDS_HW_ID and node identity manifest at %s",
        get_node_identity_path(),
    )
    return NodeIdentityInfo(hw_id=None, source="missing")


def resolve_hw_id(hw_id: Optional[int] = None) -> Optional[int]:
    """Return just the resolved hardware ID integer."""
    return resolve_hw_id_info(hw_id).hw_id
