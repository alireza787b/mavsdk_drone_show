"""Deterministic test coordinators for tracked command submission."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from command_submission_coordinator import SubmissionReservation


@dataclass
class _DeferredOperation:
    operation_factory: Callable[[], Awaitable[None]]
    on_failure: Callable[[str], Awaitable[None]]
    log_error: Callable[[str], None] | None


class DeferredSubmissionCoordinator:
    """Capture owned work so route tests can advance it explicitly."""

    def __init__(self) -> None:
        self.operations: dict[str, _DeferredOperation] = {}
        self._reservation_count = 0

    async def reserve(self, *, recovery: bool) -> SubmissionReservation:
        token = f"test-{self._reservation_count}"
        self._reservation_count += 1
        return SubmissionReservation(token=token, recovery=recovery)

    async def release(self, reservation: SubmissionReservation) -> None:
        del reservation

    async def launch(
        self,
        reservation: SubmissionReservation,
        *,
        command_id: str,
        operation_factory: Callable[[], Awaitable[None]],
        on_failure: Callable[[str], Awaitable[None]],
        log_error: Callable[[str], None] | None = None,
    ) -> None:
        del reservation
        self.operations[command_id] = _DeferredOperation(
            operation_factory=operation_factory,
            on_failure=on_failure,
            log_error=log_error,
        )

    async def run(self, command_id: str) -> None:
        operation = self.operations.pop(command_id)
        try:
            await operation.operation_factory()
        except Exception as exc:
            message = f"Command preparation failed before completion: {exc}"
            if operation.log_error is not None:
                operation.log_error(message)
            await operation.on_failure(message)

    async def run_all(self) -> None:
        for command_id in list(self.operations):
            await self.run(command_id)


class InlineSubmissionCoordinator(DeferredSubmissionCoordinator):
    """Run submitted work before returning to a service-level test."""

    async def launch(self, reservation: SubmissionReservation, **kwargs) -> None:
        command_id = kwargs["command_id"]
        await super().launch(reservation, **kwargs)
        await self.run(command_id)


__all__ = ["DeferredSubmissionCoordinator", "InlineSubmissionCoordinator"]
