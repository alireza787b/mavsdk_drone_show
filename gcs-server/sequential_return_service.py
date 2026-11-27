"""GCS-owned, interval-based RTL dispatch using the existing command lifecycle.

This scheduler spaces commands, not trajectories or completed landings. It never
resumes a queue after a server restart or changes aircraft parameters/topology.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from command_submission import submit_tracked_command
from schemas import SubmitCommandRequest
from src.enums import Mission
from src.px4_flight_modes import describe_px4_custom_mode
from swarm_return_scope import omitted_followers
from mds_logging import get_logger

logger = get_logger("sequential_return")
ACTIVE_STATES = {"holding", "dispatching", "waiting"}
CONFIRMATION_POLL_SEC = 0.25


def hold_receipt_targets(job, status):
    """Project authenticated reports onto the reviewed targets in their original order."""
    if status is None:
        return None, None
    results = status.get("executions", {}).get("details", {})
    late = status.get("late_reports", {}).get("executions", {}).get("details", {})
    confirmed, pending = [], []
    for hw_id in job["target_drone_ids"]:
        result = results.get(hw_id) or late.get(hw_id) or {}
        (confirmed if result.get("success") is True else pending).append(hw_id)
    return confirmed, pending


def heartbeat_timestamp_ms(state):
    try:
        return float(state.get("heartbeat_timestamp_ms") or 0)
    except (TypeError, ValueError):
        return 0


def command_failure_reason(status):
    """Name failed targets without hiding them behind an aggregate count."""
    reasons = []
    for hw_id, ack in status.get("acks", {}).get("details", {}).items():
        category = ack.get("category") or ack.get("status")
        if category in {"offline", "rejected", "error"}:
            reason = "unavailable" if category == "offline" else ack.get("message") or category
            reasons.append(f"Drone {hw_id}: {str(reason)[:200]}")
    if reasons:
        return "; ".join(reasons[:3]) + (f"; +{len(reasons)-3} aircraft" if len(reasons) > 3 else "")
    return status.get("error_summary") or "Aircraft command not confirmed"


class SequentialReturnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    target_drone_ids: list[str] = Field(min_length=1, max_length=100)
    delay_sec: float = Field(default=10, ge=1, le=300)
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("target_drone_ids")
    @classmethod
    def validate_targets(cls, values):
        if any(not value.isdecimal() or int(value) <= 0 for value in values):
            raise ValueError("Target IDs must be positive hardware IDs")
        normalized = [str(int(value)) for value in values]
        if len(set(normalized)) != len(normalized):
            raise ValueError("Target IDs must be unique")
        return normalized


class SequentialReturnService:
    def __init__(self, deps):
        self.deps = deps
        self.path = Path(deps.Params.GCS_COMMAND_STATE_DIR) / "sequential-return.json"
        self.jobs = {}
        self.task = None
        self.lock = asyncio.Lock()
        self._hold_status = None
        if self.path.exists():
            self.jobs = json.loads(self.path.read_text())
            for job in self.jobs.values():
                if job["state"] in ACTIVE_STATES:
                    message = "GCS restarted; remaining RTL commands were cancelled."
                    job.update(state="interrupted", next_hw_id=None, next_dispatch_at_ms=None,
                               message=self._interruption_message(job, message))
            self._save()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.jobs, allow_nan=False))
        temporary.replace(self.path)

    def _update(self, job, **values):
        job.update(values, updated_at_ms=int(time.time() * 1000))
        self._save()

    def latest(self):
        return copy.deepcopy(next(reversed(self.jobs.values()), None))

    def get(self, return_id):
        if return_id not in self.jobs:
            raise HTTPException(404, "Sequential return not found")
        return copy.deepcopy(self.jobs[return_id])

    async def observe(self, job):
        """Add current tracker evidence to a detached job snapshot without changing the job."""
        if job is None:
            return None
        tracker = self.deps.get_command_tracker()
        command_id = job.get("hold_command_id")
        hold_key = self._command_key(job, "hold") if not command_id and job["state"] not in ACTIVE_STATES else None
        dispatch_ids = [entry["command_id"] for entry in job["commands"] if not entry.get("dispatch_started_at_ms")]
        status, submitted = await tracker.get_recovery_progress(command_id, idempotency_key=hold_key,
                                                              dispatch_ids=dispatch_ids)
        if status:
            job["hold_command_id"] = status["command_id"]
        dispatch_known = len(submitted) == len(dispatch_ids) and not job.get("uncertain_dispatch_hw_id")
        job["rtl_dispatched_count"] = (
            len(job["commands"]) - len(dispatch_ids) + sum(at is not None for at in submitted.values())
            if dispatch_known else None
        )
        stored = job.get("hold_confirmation", {})
        confirmed, pending = hold_receipt_targets(job, status)
        job["hold_confirmation"] = dict(
            deadline_at_ms=stored.get("deadline_at_ms") or (status or {}).get("timeout_at"),
            stopped_at_ms=stored.get("stopped_at_ms"),
            confirmed_at_stop=stored.get("confirmed_at_stop"),
            pending_at_stop=stored.get("pending_at_stop"),
            confirmed_now=confirmed,
            pending_now=pending,
        )
        if job["state"] in ACTIVE_STATES:
            job["uncertain_dispatch_hw_id"] = None
        return job

    def _stop(self, job, state, message):
        stopped_at = int(time.time() * 1000)
        confirmed, pending = hold_receipt_targets(job, self._hold_status)
        deadline = (self._hold_status or {}).get("timeout_at")
        self._update(job, state=state, next_hw_id=None, next_dispatch_at_ms=None, message=message,
                     hold_confirmation=dict(deadline_at_ms=deadline, stopped_at_ms=stopped_at,
                                            confirmed_at_stop=confirmed, pending_at_stop=pending))
        logger.warning(
            "Sequential return %s stopped: %s (state=%s, hold_command_id=%s, "
            "hold_deadline_ms=%s, hold_confirmed=%s/%d, rtl_receipts=%d, uncertain_rtl_target=%s)",
            job["return_id"], message, state, job["hold_command_id"], deadline,
            None if confirmed is None else len(confirmed), len(job["target_drone_ids"]),
            len(job["commands"]), job.get("uncertain_dispatch_hw_id"),
        )

    @staticmethod
    def _interruption_message(job, message):
        uncertain_target = job.get("uncertain_dispatch_hw_id")
        if uncertain_target:
            return f"{message.rstrip('.')}. Drone {uncertain_target}: RTL submission was in progress and may still be delivered."
        return message

    async def start(self, request):
        async with self.lock:
            for job in self.jobs.values():
                if job["idempotency_key"] == request.idempotency_key:
                    if (job["target_drone_ids"] != request.target_drone_ids
                            or job["delay_sec"] != request.delay_sec):
                        raise HTTPException(409, "This return request already has a different order or interval")
                    return copy.deepcopy(job)
            if any(job["state"] in ACTIVE_STATES for job in self.jobs.values()):
                raise HTTPException(409, "A sequential return is already running")
            known = {str(item["hw_id"]) for item in self.deps.load_config()}
            if not set(request.target_drone_ids) <= known:
                raise HTTPException(409, "Return targets changed; review the selected drones")
            await self._check_followers(request.target_drone_ids)
            # Bound durable UI history, preserving the active job and retry identity.
            while len(self.jobs) >= 100:
                self.jobs.pop(next(iter(self.jobs)))
            return_id = str(uuid.uuid4())
            job = dict(return_id=return_id, **request.model_dump(), state="holding",
                       message="Stopping following and establishing Hold", hold_command_id=None,
                       commands=[], next_hw_id=None, next_dispatch_at_ms=None, uncertain_dispatch_hw_id=None,
                       created_at_ms=int(time.time() * 1000))
            self.jobs[return_id] = job
            self._hold_status = None
            self._update(job)
            self.task = asyncio.create_task(self._run(job), name=f"sequential-return-{return_id}")
            logger.info("Sequential return %s: order=%s interval=%ss", return_id,
                        request.target_drone_ids, request.delay_sec)
            return copy.deepcopy(job)

    async def _cancel(self, job, message):
        self._stop(job, "cancelled", self._interruption_message(job, message))
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def cancel(self, return_id):
        async with self.lock:
            job = self.jobs.get(return_id)
            if job is None:
                raise HTTPException(404, "Sequential return not found")
            if job["state"] in ACTIVE_STATES:
                await self._cancel(job, "Remaining RTL commands cancelled. Issued commands continue.")
            return copy.deepcopy(job)

    async def close(self):
        for job in self.jobs.values():
            if job["state"] in ACTIVE_STATES:
                message = "GCS stopped; remaining RTL commands were cancelled."
                self._stop(job, "interrupted", self._interruption_message(job, message))
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def supersede(self, targets):
        """An explicit newer flight command takes ownership of the target set."""
        targets = set(targets)
        async with self.lock:
            for job in self.jobs.values():
                if job["state"] in ACTIVE_STATES and targets.intersection(job["target_drone_ids"]):
                    await self._cancel(job, "A newer command covers these aircraft. Remaining RTL commands cancelled.")
                    return

    def owns_current_task(self):
        return asyncio.current_task() is self.task

    @staticmethod
    def _command_key(job, suffix):
        return f"sequential-return:{job['return_id']}:{suffix}"

    async def _command(self, job, mission, targets, suffix):
        receipt = await submit_tracked_command(self.deps, SubmitCommandRequest(
            mission_type=mission.value, trigger_time=0, target_drone_ids=targets,
            idempotency_key=self._command_key(job, suffix),
            operator_label="Sequential Return · Hold" if mission == Mission.HOLD else "Sequential Return · RTL",
        ))
        return receipt.command_id

    async def _check_followers(self, targets):
        commands = await self.deps.get_command_tracker().get_active_commands()
        missing = omitted_followers(commands, targets)
        if missing:
            names = ', '.join(missing[:3]) + (f' +{len(missing)-3}' if len(missing) > 3 else '')
            raise HTTPException(409, f"Include following aircraft {names} in To, or use Hold all before returning their leader")

    async def _wait_command(self, job, command, *, remaining_targets):
        # The explicitly timed mode waits for the start of RTL, not for landing.
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            for waiting_id in remaining_targets:
                self._check_waiting_drone(waiting_id)
            status, _ = await self.deps.get_command_tracker().get_recovery_progress(command["command_id"])
            if status:
                if status.get("submitted_at") is not None and not command.get("dispatch_started_at_ms"):
                    command["dispatch_started_at_ms"] = status["submitted_at"]
                    self._update(job)
                if status.get("status") == "completed":
                    return
                if status.get("phase") == "terminal":
                    raise RuntimeError(command_failure_reason(status))
                acks = status.get("acks", {})
                if any(acks.get(key, 0) for key in ("rejected", "offline", "errors")):
                    raise RuntimeError(command_failure_reason(status))
                if status.get("execution_started_at"):
                    # A subprocess starting is not proof that PX4 accepted RTL.
                    state, mode, fresh = self._telemetry(command["hw_id"])
                    if fresh and state.get("is_armed") is True and mode == "RETURN":
                        return
            await asyncio.sleep(CONFIRMATION_POLL_SEC)
        raise RuntimeError("Aircraft command confirmation timed out; remaining RTL commands stopped")

    async def _wait_hold(self, job):
        tracker = self.deps.get_command_tracker()
        command_id = job["hold_command_id"]
        hold_seen_at = {}
        loop = asyncio.get_running_loop()
        deadline_at_ms = None
        deadline = None
        while True:
            status, _ = await tracker.get_recovery_progress(command_id)
            if status is None:
                raise RuntimeError("Hold command tracking is unavailable")
            self._hold_status = status
            now_ms = int(time.time() * 1000)
            tracked_deadline = status.get("timeout_at")
            if tracked_deadline != deadline_at_ms:
                deadline_at_ms = tracked_deadline
                deadline = loop.time() + (deadline_at_ms - now_ms) / 1000 if deadline_at_ms else None
                logger.info("Sequential return %s tracking Hold command %s (deadline_ms=%s)",
                            job["return_id"], command_id, deadline_at_ms)
            submitted_at = status.get("submitted_at")
            ready = self._observe_hold_telemetry(job, hold_seen_at, submitted_at)
            if status.get("status") == "completed":
                completed_at = status.get("completed_at")
                if not deadline_at_ms or not completed_at:
                    raise RuntimeError("Hold confirmation timing is unavailable")
                if completed_at > deadline_at_ms:
                    raise RuntimeError("Hold result arrived after its tracked confirmation deadline")
                logger.info("Sequential return %s observed confirmed Hold %s (completed_at_ms=%s)",
                            job["return_id"], command_id, completed_at)
                break
            if status.get("phase") == "terminal":
                raise RuntimeError(command_failure_reason(status))
            acks = status.get("acks", {})
            if any(acks.get(key, 0) for key in ("rejected", "offline", "errors")):
                raise RuntimeError(command_failure_reason(status))
            if deadline is None:
                raise RuntimeError("Hold confirmation deadline is unavailable")
            if now_ms >= deadline_at_ms or loop.time() >= deadline:
                raise RuntimeError("The confirmation deadline expired")
            await asyncio.sleep(min(CONFIRMATION_POLL_SEC, max(0, deadline - loop.time())))

        # Allow the ordinary telemetry cache to catch up with the confirmed Hold.
        telemetry_deadline = loop.time() + 5
        while not ready:
            if loop.time() >= telemetry_deadline:
                for hw_id in job["target_drone_ids"]:
                    self._check_waiting_drone(hw_id)
                raise RuntimeError("A fresh flight-controller heartbeat after Hold submission was not confirmed")
            await asyncio.sleep(CONFIRMATION_POLL_SEC)
            ready = self._observe_hold_telemetry(job, hold_seen_at, submitted_at)

    def _observe_hold_telemetry(self, job, hold_seen_at, submitted_at):
        ready = True
        for hw_id in job["target_drone_ids"]:
            state, mode, fresh = self._telemetry(hw_id)
            armed = state.get("is_armed")
            armed_hold = fresh and armed is True and mode == "HOLD"
            timestamp = heartbeat_timestamp_ms(state)
            ready = ready and armed_hold and (not submitted_at or timestamp >= submitted_at)
            if not fresh or not submitted_at or timestamp < submitted_at:
                continue
            previous_hold = hold_seen_at.get(hw_id, 0)
            if armed_hold:
                hold_seen_at[hw_id] = max(previous_hold, timestamp)
            elif timestamp > previous_hold and (
                armed is False
                or (previous_hold and mode not in {"NONE", "HOLD", ""} and not mode.startswith("UNKNOWN"))
            ):
                raise RuntimeError(f"Drone {hw_id}: left armed Hold or disarmed; remaining RTL commands stopped")
        return ready

    def _telemetry(self, hw_id):
        with self.deps.telemetry_lock:
            state = dict(self.deps.telemetry_data_all_drones.get(hw_id)
                         or self.deps.telemetry_data_all_drones.get(int(hw_id)) or {})
        age = time.time() * 1000 - heartbeat_timestamp_ms(state)
        mode = state.get("flight_mode")
        try:
            mode = describe_px4_custom_mode(int(mode)).upper()
        except (ValueError, TypeError):
            mode = str(mode).upper()
        return state, mode, state.get("telemetry_available") is not False and 0 <= age <= 5000

    def _check_waiting_drone(self, hw_id):
        # Do not override a pilot/failsafe mode change during the waiting period.
        state, mode, fresh = self._telemetry(hw_id)
        if not fresh:
            raise RuntimeError(f"Drone {hw_id}: fresh flight-controller heartbeat unavailable; remaining RTL commands stopped")
        if state.get("is_armed") is not True or mode != "HOLD":
            raise RuntimeError(f"Drone {hw_id}: no longer in armed Hold; remaining RTL commands stopped")

    async def _run(self, job):
        try:
            command_id = await self._command(job, Mission.HOLD, job["target_drone_ids"], "hold")
            self._update(job, hold_command_id=command_id)
            await self._wait_hold(job)
            previous_dispatch = None
            for index, hw_id in enumerate(job["target_drone_ids"]):
                if previous_dispatch is not None:
                    remaining = max(0, previous_dispatch + job["delay_sec"] - asyncio.get_running_loop().time())
                    self._update(job, state="waiting", next_hw_id=hw_id,
                                 next_dispatch_at_ms=int(time.time() * 1000 + remaining * 1000),
                                 message=f"Drone {hw_id} waiting for RTL")
                    deadline = previous_dispatch + job["delay_sec"]
                    while True:
                        for waiting_id in job["target_drone_ids"][index:]:
                            self._check_waiting_drone(waiting_id)
                        remaining = deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            break
                        await asyncio.sleep(min(CONFIRMATION_POLL_SEC, remaining))
                # Recheck pending/active followers before each RTL: the scope
                # may have acquired newer tracked work during the interval.
                await self._check_followers(job["target_drone_ids"])
                for waiting_id in job["target_drone_ids"][index:]:
                    self._check_waiting_drone(waiting_id)
                self._update(job, state="dispatching", next_hw_id=hw_id, next_dispatch_at_ms=None,
                             message=f"Sending RTL to drone {hw_id}", uncertain_dispatch_hw_id=hw_id)
                command_id = await self._command(job, Mission.RETURN_RTL, [hw_id], hw_id)
                previous_dispatch = asyncio.get_running_loop().time()
                command = dict(hw_id=hw_id, command_id=command_id, dispatched_at_ms=int(time.time() * 1000))
                job["commands"].append(command)
                self._update(job, uncertain_dispatch_hw_id=None)
                await self._wait_command(job, command, remaining_targets=job["target_drone_ids"][index + 1:])
            self._update(job, state="dispatched", next_hw_id=None, next_dispatch_at_ms=None,
                         message="All RTL commands started. Monitor each aircraft through landing.")
            logger.info("Sequential return %s: all RTL commands started", job["return_id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = str(exc.detail if isinstance(exc, HTTPException) else exc)
            if job["state"] == "holding":
                prefix = "" if (self._hold_status or {}).get("status") == "completed" else "Hold not confirmed: "
                detail = f"{prefix}{detail.rstrip('.')}. No RTL commands sent."
            self._stop(job, "failed", self._interruption_message(job, detail))
