"""Typed action-runner primitives shared by CLI, DroneSetup, and future MCP tooling."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


ActionRunner = Callable[["ActionExecutionContext", "ActionInvocation"], Awaitable[bool]]


@dataclass(frozen=True)
class ActionInvocation:
    """Normalized action request passed into a runner."""

    action: str
    altitude: Optional[float] = None
    parameters: Optional[dict[str, str]] = None
    branch: Optional[str] = None
    reboot_after: bool = False
    request_payload: Optional[dict[str, Any]] = None


@dataclass
class ActionExecutionContext:
    """Runtime context available to action runners."""

    drone: Any
    hw_id: Optional[str]
    logger: Any
    grpc_port: Optional[int] = None
    udp_port: Optional[int] = None
    mavsdk_server: Any = None


@dataclass(frozen=True)
class ActionSpec:
    """Registry record for a named action runner."""

    name: str
    runner: ActionRunner
    requires_connection: bool = True
    description: str = ""


def load_request_payload(
    request_json: Optional[str] = None,
    request_file: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Load an optional structured action payload from inline JSON or a file."""

    if request_json and request_file:
        raise ValueError("request_json and request_file are mutually exclusive")

    if request_json:
        payload = json.loads(request_json)
    elif request_file:
        payload = json.loads(Path(request_file).read_text(encoding="utf-8"))
    else:
        return None

    if not isinstance(payload, dict):
        raise ValueError("Structured action payload must be a JSON object")

    return payload
