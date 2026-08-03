"""Reusable asynchronous FleetRPC test double.

Command submission tests should depend on the same service boundary as the
application.  Keeping one fake here prevents deleted synchronous transport
functions from reappearing as fixture-only compatibility seams.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


class FakeFleetRPC:
    """Record FleetRPC calls and return configurable typed fleet outcomes."""

    def __init__(
        self,
        *,
        dispatch_impl: Callable[..., Any] | None = None,
        preparation_impl: Callable[..., Any] | None = None,
    ) -> None:
        self._dispatch_impl = dispatch_impl
        self._preparation_impl = preparation_impl
        self.dispatch_calls: list[dict[str, Any]] = []
        self.preparation_calls: list[dict[str, Any]] = []

    @staticmethod
    async def _resolve(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    async def dispatch(
        self,
        drones: list[dict[str, Any]],
        command_data: dict[str, Any],
        *,
        callback_capabilities: dict[str, str] | None = None,
        per_target_payloads: dict[str, dict[str, Any]] | None = None,
        launch_preparation_tokens: dict[str, str] | None = None,
        operation_deadline_sec: float | None = None,
    ) -> dict[str, Any]:
        call = {
            "drones": list(drones),
            "command_data": dict(command_data),
            "callback_capabilities": dict(callback_capabilities or {}),
            "per_target_payloads": (
                {hw_id: dict(payload) for hw_id, payload in per_target_payloads.items()}
                if per_target_payloads is not None
                else None
            ),
            "launch_preparation_tokens": dict(launch_preparation_tokens or {}),
            "operation_deadline_sec": operation_deadline_sec,
        }
        self.dispatch_calls.append(call)
        if self._dispatch_impl is not None:
            return await self._resolve(
                self._dispatch_impl(
                    drones,
                    command_data,
                    callback_capabilities=callback_capabilities,
                    per_target_payloads=per_target_payloads,
                    launch_preparation_tokens=launch_preparation_tokens,
                    operation_deadline_sec=operation_deadline_sec,
                )
            )

        results = {
            str(drone["hw_id"]): {
                "success": True,
                "category": "accepted",
                "delivery_state": "accepted",
            }
            for drone in drones
        }
        accepted = len(results)
        return {
            "success": accepted,
            "offline": 0,
            "rejected": 0,
            "errors": 0,
            "failed": 0,
            "unavailable": 0,
            "total": accepted,
            "result_summary": f"{accepted} accepted",
            "results": results,
        }

    async def prepare_launch(
        self,
        drones: list[dict[str, Any]],
        command_data: dict[str, Any],
        *,
        callback_capabilities: dict[str, str],
        per_target_payloads: dict[str, dict[str, Any]] | None = None,
        require_global_position: bool = True,
        request_timeout_sec: float | None = None,
        operation_deadline_sec: float | None = None,
    ) -> dict[str, Any]:
        call = {
            "drones": list(drones),
            "command_data": dict(command_data),
            "callback_capabilities": dict(callback_capabilities),
            "per_target_payloads": (
                {hw_id: dict(payload) for hw_id, payload in per_target_payloads.items()}
                if per_target_payloads is not None
                else None
            ),
            "require_global_position": require_global_position,
            "request_timeout_sec": request_timeout_sec,
            "operation_deadline_sec": operation_deadline_sec,
        }
        self.preparation_calls.append(call)
        if self._preparation_impl is not None:
            return await self._resolve(
                self._preparation_impl(
                    drones,
                    command_data,
                    callback_capabilities=callback_capabilities,
                    per_target_payloads=per_target_payloads,
                    require_global_position=require_global_position,
                    request_timeout_sec=request_timeout_sec,
                    operation_deadline_sec=operation_deadline_sec,
                )
            )

        results = {
            str(drone["hw_id"]): {
                "drone_id": str(drone["hw_id"]),
                "success": True,
                "ready": True,
                "summary": "Ready for launch",
                "category": "ready",
                "prepare_state": "ready",
            }
            for drone in drones
        }
        return {
            "all_prepared": True,
            "blocked_ids": [],
            "unavailable_ids": [],
            "preparation_tokens": {
                str(drone["hw_id"]): f"prepare-{drone['hw_id']}-" + ("x" * 48)
                for drone in drones
            },
            "results": results,
        }


__all__ = ["FakeFleetRPC"]
