"""Lifespan-owned background orchestration for tracked command submission.

The HTTP layer durably commits a tracker identity first, then hands readiness
and dispatch I/O to this process-local coordinator. This keeps the operator
request responsive without pretending that queued work has reached a drone.

Coordinator tasks are intentionally not replayed after restart. The durable
tracker reconciles an interrupted pre-dispatch task as definitely unsent and
an interrupted post-dispatch task as per-target delivery unknown. Replaying a
fan-out automatically would violate command idempotency and flight safety.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional


class CommandSubmissionCapacityError(RuntimeError):
    """Raised before tracker creation when the appropriate lane is full."""


class CommandSubmissionUnavailableError(RuntimeError):
    """Raised while the lifespan service is stopped or shutting down."""


@dataclass(frozen=True)
class SubmissionReservation:
    """One bounded admission slot reserved before tracker creation."""

    token: str
    recovery: bool


@dataclass
class _ActiveSubmission:
    task: asyncio.Task
    recovery: bool


FailureHandler = Callable[[str], Awaitable[None]]
OperationFactory = Callable[[], Awaitable[None]]
LogHandler = Callable[[str], None]


class CommandSubmissionCoordinator:
    """Own bounded routine/recovery command preparation tasks for one lifespan."""

    def __init__(self, params) -> None:
        self._routine_limit = max(
            1,
            int(getattr(params, "GCS_COMMAND_SUBMISSION_CONCURRENCY", 32)),
        )
        self._recovery_limit = max(
            1,
            int(getattr(params, "GCS_COMMAND_RECOVERY_SUBMISSION_CONCURRENCY", 8)),
        )
        self._shutdown_grace_sec = max(
            0.0,
            min(
                float(getattr(params, "GCS_COMMAND_SUBMISSION_SHUTDOWN_GRACE_SEC", 5.0)),
                30.0,
            ),
        )
        self._accepting = False
        self._reservations: Dict[str, SubmissionReservation] = {}
        self._active: Dict[str, _ActiveSubmission] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            self._accepting = True

    async def reserve(self, *, recovery: bool) -> SubmissionReservation:
        """Reserve capacity before creating a tracker record."""
        async with self._lock:
            if not self._accepting:
                raise CommandSubmissionUnavailableError(
                    "Command submission service is not accepting new work"
                )

            active_count = sum(
                1 for item in self._active.values() if item.recovery is recovery
            )
            reserved_count = sum(
                1 for item in self._reservations.values() if item.recovery is recovery
            )
            limit = self._recovery_limit if recovery else self._routine_limit
            if active_count + reserved_count >= limit:
                lane = "recovery" if recovery else "routine"
                raise CommandSubmissionCapacityError(
                    f"The {lane} command preparation lane is at its bounded capacity "
                    f"({limit}); no tracker record or drone command was created"
                )

            reservation = SubmissionReservation(
                token=uuid.uuid4().hex,
                recovery=recovery,
            )
            self._reservations[reservation.token] = reservation
            return reservation

    async def release(self, reservation: SubmissionReservation) -> None:
        """Release a reservation when validation/replay ends before launch."""
        async with self._lock:
            self._reservations.pop(reservation.token, None)

    async def launch(
        self,
        reservation: SubmissionReservation,
        *,
        command_id: str,
        operation_factory: OperationFactory,
        on_failure: FailureHandler,
        log_error: Optional[LogHandler] = None,
    ) -> None:
        """Convert one reservation into an owned task without awaiting its I/O."""
        async with self._lock:
            owned = self._reservations.pop(reservation.token, None)
            if owned != reservation:
                raise CommandSubmissionUnavailableError(
                    "Command submission reservation is no longer valid"
                )
            if not self._accepting:
                raise CommandSubmissionUnavailableError(
                    "Command submission service stopped before work could start"
                )
            if command_id in self._active:
                raise RuntimeError(f"Command {command_id} already has an active submission task")

            task = asyncio.create_task(
                self._run_owned_operation(
                    command_id=command_id,
                    operation_factory=operation_factory,
                    on_failure=on_failure,
                    log_error=log_error,
                ),
                name=f"mds-command-submit-{command_id[:8]}",
            )
            self._active[command_id] = _ActiveSubmission(
                task=task,
                recovery=reservation.recovery,
            )
            task.add_done_callback(
                lambda completed, owned_id=command_id: self._retire_done_task(
                    owned_id,
                    completed,
                )
            )

    async def _run_owned_operation(
        self,
        *,
        command_id: str,
        operation_factory: OperationFactory,
        on_failure: FailureHandler,
        log_error: Optional[LogHandler],
    ) -> None:
        try:
            await operation_factory()
        except asyncio.CancelledError:
            await asyncio.shield(
                on_failure(
                    "GCS shutdown interrupted command preparation before dispatch completed"
                )
            )
            raise
        except Exception as exc:
            message = f"Command preparation failed before completion: {exc}"
            if log_error is not None:
                log_error(message)
            await on_failure(message)

    def _retire_done_task(self, command_id: str, completed: asyncio.Task) -> None:
        current = self._active.get(command_id)
        if current is not None and current.task is completed:
            self._active.pop(command_id, None)

    async def stop(self) -> None:
        """Stop admission, briefly drain work, then cancel and terminalize it."""
        async with self._lock:
            self._accepting = False
            self._reservations.clear()
            tasks = [entry.task for entry in self._active.values() if not entry.task.done()]

        if tasks:
            done, pending = await asyncio.wait(tasks, timeout=self._shutdown_grace_sec)
            del done
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        async with self._lock:
            self._active.clear()

    async def counts(self) -> dict[str, int]:
        """Return low-cardinality diagnostics without exposing command payloads."""
        async with self._lock:
            return {
                "routine_active": sum(
                    1 for item in self._active.values() if not item.recovery
                ),
                "recovery_active": sum(
                    1 for item in self._active.values() if item.recovery
                ),
                "reserved": len(self._reservations),
            }


__all__ = [
    "CommandSubmissionCapacityError",
    "CommandSubmissionCoordinator",
    "CommandSubmissionUnavailableError",
    "SubmissionReservation",
]
