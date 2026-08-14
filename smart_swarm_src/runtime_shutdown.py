"""Cooperative process shutdown for the Smart Swarm runtime.

This module owns only process-signal and resource-lifecycle policy. Vehicle
commands and task registries remain in ``smart_swarm.py`` and are supplied as
callbacks, avoiding a circular dependency with the flight runtime.
"""

from __future__ import annotations

import asyncio
import signal
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional


@dataclass(frozen=True)
class VehicleHandoffResult:
    """Outcome of the explicit Offboard-to-HOLD shutdown handoff."""

    offboard_stop_completed: bool
    hold_requested: bool

    @property
    def completed(self) -> bool:
        # A PX4-accepted HOLD is the authoritative mode handoff and is also
        # valid when Offboard was already inactive. The separate stop field
        # preserves truthful diagnostics for the preceding best-effort RPC.
        return self.hold_requested


@dataclass
class ShutdownSignalState:
    """First cooperative process signal observed by the runtime."""

    received_signal: Optional[str] = None


def resolve_shutdown_budget_sec(manager_grace_sec: float) -> float:
    """Reserve interpreter teardown time inside the manager's normal grace."""
    try:
        manager_grace = float(manager_grace_sec)
    except (TypeError, ValueError):
        manager_grace = 5.0
    manager_grace = max(0.1, min(manager_grace, 30.0))
    interpreter_reserve = min(0.5, manager_grace * 0.1)
    return max(0.05, manager_grace - interpreter_reserve)


class SmartSwarmRuntimeLifecycle:
    """Own process resources and perform one bounded, idempotent shutdown."""

    def __init__(
        self,
        logger,
        *,
        cancel_follower_tasks: Callable[[object], Awaitable[None]],
        vehicle_handoff: Callable[..., Awaitable[VehicleHandoffResult]],
        stop_mavsdk_server: Callable[..., None],
        manager_grace_sec: float = 5.0,
        shutdown_budget_sec: Optional[float] = None,
    ):
        self.logger = logger
        self.drone = None
        self.mavsdk_server = None
        self.swarm_update_task = None
        self._cancel_follower_tasks = cancel_follower_tasks
        self._vehicle_handoff = vehicle_handoff
        self._stop_mavsdk_server = stop_mavsdk_server
        self.shutdown_budget_sec = (
            resolve_shutdown_budget_sec(manager_grace_sec)
            if shutdown_budget_sec is None
            else max(0.05, float(shutdown_budget_sec))
        )
        self._shutdown_task = None

    async def shutdown(self, reason: str) -> bool:
        """Stop command producers, leave Offboard, request HOLD, and exit."""
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._shutdown_once(reason))
        return await asyncio.shield(self._shutdown_task)

    async def _shutdown_once(self, reason: str) -> bool:
        deadline = asyncio.get_running_loop().time() + self.shutdown_budget_sec
        clean = True
        handoff = None
        self.logger.warning(
            "Smart Swarm cooperative shutdown started (%s; budget=%.2fs).",
            reason,
            self.shutdown_budget_sec,
        )

        update_task = self.swarm_update_task
        if update_task is not None:
            if not update_task.done():
                update_task.cancel()
            try:
                await asyncio.wait_for(
                    update_task,
                    timeout=min(0.5, self.shutdown_budget_sec * 0.1),
                )
            except asyncio.CancelledError:
                pass
            except asyncio.TimeoutError:
                clean = False
                self.logger.error(
                    "Smart Swarm configuration task did not stop within the shutdown budget."
                )
            except Exception:
                clean = False
                self.logger.exception(
                    "Smart Swarm configuration task failed during shutdown."
                )

        follower_cancel_budget = min(0.5, self.shutdown_budget_sec * 0.1)
        try:
            await asyncio.wait_for(
                self._cancel_follower_tasks(self.logger),
                timeout=follower_cancel_budget,
            )
        except asyncio.TimeoutError:
            clean = False
            self.logger.error(
                "Follower tasks did not finish cancellation within %.2fs; "
                "continuing with the explicit PX4 safety handoff.",
                follower_cancel_budget,
            )
        except Exception:
            clean = False
            self.logger.exception(
                "Follower task cancellation failed; continuing with the explicit PX4 safety handoff."
            )

        if self.drone is not None:
            remaining = max(0.02, deadline - asyncio.get_running_loop().time())
            server_reserve = min(0.5, remaining * 0.15)
            operation_timeout = max(0.01, (remaining - server_reserve) / 2.0)
            handoff = await self._vehicle_handoff(
                self.drone,
                reason=f"Smart Swarm shutdown: {reason}",
                operation_timeout_sec=operation_timeout,
            )
            clean = clean and handoff.completed
            if not handoff.completed:
                self.logger.error(
                    "Smart Swarm shutdown handoff was incomplete "
                    "(offboard_stopped=%s, hold_requested=%s).",
                    handoff.offboard_stop_completed,
                    handoff.hold_requested,
                )

        if self.mavsdk_server is not None:
            remaining = max(0.01, deadline - asyncio.get_running_loop().time())
            try:
                self._stop_mavsdk_server(
                    self.mavsdk_server,
                    timeout_sec=min(0.5, remaining),
                )
            except Exception:
                clean = False
                self.logger.exception("Failed to stop the Smart Swarm MAVSDK server.")

        if clean:
            if handoff is None:
                self.logger.info(
                    "Smart Swarm cooperative shutdown completed before vehicle control "
                    "was established (%s).",
                    reason,
                )
            elif handoff.offboard_stop_completed:
                self.logger.info(
                    "Smart Swarm cooperative shutdown completed: setpoint tasks stopped, "
                    "Offboard stopped, and PX4 HOLD was requested (%s).",
                    reason,
                )
            else:
                self.logger.warning(
                    "Smart Swarm cooperative shutdown completed with PX4 HOLD accepted; "
                    "the preceding Offboard-stop RPC was not independently confirmed (%s).",
                    reason,
                )
        else:
            self.logger.critical(
                "Smart Swarm cooperative shutdown was incomplete (%s); the owning "
                "process manager or recovery command must complete vehicle safety handling.",
                reason,
            )
        return clean


def install_shutdown_signal_handlers(loop, process_task, logger):
    """Install first-signal cooperative cancellation for the Linux runtime."""
    state = ShutdownSignalState()
    installed_signals = []

    def request_shutdown(received_signal):
        if state.received_signal is not None:
            logger.warning(
                "Ignoring repeated %s while Smart Swarm safety cleanup is in progress.",
                received_signal.name,
            )
            return
        state.received_signal = received_signal.name
        logger.warning(
            "Received %s; stopping Smart Swarm cooperatively before process exit.",
            received_signal.name,
        )
        if process_task is not None:
            process_task.cancel()

    for handled_signal in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(
                handled_signal,
                request_shutdown,
                handled_signal,
            )
            installed_signals.append(handled_signal)
        except (NotImplementedError, RuntimeError, ValueError):
            logger.debug(
                "Event loop signal handlers are unavailable for %s.",
                handled_signal.name,
            )

    return state, installed_signals
