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
from mds_logging import get_logger

logger = get_logger("sequential_return")
ACTIVE_STATES = {"holding", "dispatching", "waiting"}


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
        if self.path.exists():
            self.jobs = json.loads(self.path.read_text())
            for job in self.jobs.values():
                if job["state"] in ACTIVE_STATES:
                    job.update(state="interrupted", next_hw_id=None, next_dispatch_at_ms=None,
                               message="GCS restarted; remaining RTL commands were cancelled.")
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
            # Bound durable UI history, preserving the active job and retry identity.
            while len(self.jobs) >= 100:
                self.jobs.pop(next(iter(self.jobs)))
            return_id = str(uuid.uuid4())
            job = dict(return_id=return_id, **request.model_dump(), state="holding",
                       message="Stopping following and establishing Hold", hold_command_id=None,
                       commands=[], next_hw_id=None, next_dispatch_at_ms=None,
                       created_at_ms=int(time.time() * 1000))
            self.jobs[return_id] = job
            self._update(job)
            self.task = asyncio.create_task(self._run(job), name=f"sequential-return-{return_id}")
            logger.info("Sequential return %s: order=%s interval=%ss", return_id,
                        request.target_drone_ids, request.delay_sec)
            return copy.deepcopy(job)

    async def cancel(self, return_id):
        async with self.lock:
            job = self.jobs.get(return_id)
            if job is None:
                raise HTTPException(404, "Sequential return not found")
            if job["state"] in ACTIVE_STATES:
                self._update(job, state="cancelled", next_hw_id=None, next_dispatch_at_ms=None,
                             message="Remaining RTL commands cancelled. Issued commands continue.")
                if self.task:
                    self.task.cancel()
                    await asyncio.gather(self.task, return_exceptions=True)
            return copy.deepcopy(job)

    async def close(self):
        for job in self.jobs.values():
            if job["state"] in ACTIVE_STATES:
                self._update(job, state="interrupted", next_hw_id=None, next_dispatch_at_ms=None,
                             message="GCS stopped; remaining RTL commands were cancelled.")
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)

    async def supersede(self, targets):
        """An explicit newer flight command takes ownership of the target set."""
        for job in self.jobs.values():
            if job["state"] in ACTIVE_STATES and set(targets) & set(job["target_drone_ids"]):
                await self.cancel(job["return_id"])

    def owns_current_task(self):
        return asyncio.current_task() is self.task

    async def _command(self, job, mission, targets, suffix):
        receipt = await submit_tracked_command(self.deps, SubmitCommandRequest(
            mission_type=mission.value, trigger_time=0, target_drone_ids=targets,
            idempotency_key=f"sequential-return:{job['return_id']}:{suffix}",
            operator_label="Sequential Return · Hold" if mission == Mission.HOLD else "Sequential Return · RTL",
        ))
        return receipt.command_id

    async def _wait_command(self, command_id, *, completed=False, hw_id=None):
        # HOLD must complete, RTL only needs execution-start evidence. Never wait
        # for landing to release the next aircraft in this explicitly timed mode.
        deadline = asyncio.get_running_loop().time() + 30
        while asyncio.get_running_loop().time() < deadline:
            status = await self.deps.get_command_tracker().get_status(command_id)
            if status:
                if status.get("status") == "completed":
                    return
                if status.get("phase") == "terminal":
                    raise RuntimeError(status.get("error_summary") or "Aircraft command did not succeed")
                acks = status.get("acks", {})
                if any(acks.get(key, 0) for key in ("rejected", "offline", "errors")):
                    raise RuntimeError(status.get("error_summary") or "Aircraft did not accept the command")
                if not completed and status.get("execution_started_at"):
                    # A subprocess starting is not proof that PX4 accepted RTL.
                    state, mode, fresh = self._telemetry(hw_id)
                    if fresh and state.get("is_armed") is True and mode == "RETURN":
                        return
            await asyncio.sleep(0.25)
        raise RuntimeError("Aircraft command confirmation timed out; remaining RTL commands stopped")

    def _telemetry(self, hw_id):
        with self.deps.telemetry_lock:
            state = dict(self.deps.telemetry_data_all_drones.get(hw_id)
                         or self.deps.telemetry_data_all_drones.get(int(hw_id)) or {})
        timestamp = state.get("telemetry_timestamp_ms") or state.get("update_time") or 0
        try:
            timestamp = float(timestamp)
            if timestamp < 10_000_000_000:
                timestamp *= 1000
            age = time.time() * 1000 - timestamp
        except (TypeError, ValueError):
            age = float("inf")
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
            raise RuntimeError(f"Drone {hw_id}: telemetry unavailable; remaining RTL commands stopped")
        if state.get("is_armed") is not True or mode != "HOLD":
            raise RuntimeError(f"Drone {hw_id}: no longer in armed Hold; remaining RTL commands stopped")

    async def _run(self, job):
        try:
            command_id = await self._command(job, Mission.HOLD, job["target_drone_ids"], "hold")
            self._update(job, hold_command_id=command_id)
            await self._wait_command(command_id, completed=True)
            # Let the ordinary telemetry cache catch up with the confirmed Hold.
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                try:
                    for hw_id in job["target_drone_ids"]:
                        self._check_waiting_drone(hw_id)
                    break
                except RuntimeError:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise
                    await asyncio.sleep(0.25)
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
                        await asyncio.sleep(min(0.25, remaining))
                self._check_waiting_drone(hw_id)
                self._update(job, state="dispatching", next_hw_id=hw_id, next_dispatch_at_ms=None,
                             message=f"Sending RTL to drone {hw_id}")
                command_id = await self._command(job, Mission.RETURN_RTL, [hw_id], hw_id)
                previous_dispatch = asyncio.get_running_loop().time()
                job["commands"].append(dict(hw_id=hw_id, command_id=command_id,
                                            dispatched_at_ms=int(time.time() * 1000)))
                self._update(job)
                await self._wait_command(command_id, hw_id=hw_id)
            self._update(job, state="dispatched", next_hw_id=None, next_dispatch_at_ms=None,
                         message="All RTL commands started. Monitor each aircraft through landing.")
            logger.info("Sequential return %s: all RTL commands started", job["return_id"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            self._update(job, state="failed", next_hw_id=None, next_dispatch_at_ms=None,
                         message=str(detail))
            logger.warning("Sequential return %s stopped: %s", job["return_id"], detail)
