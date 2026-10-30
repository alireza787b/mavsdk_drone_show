"""One action's bounded armed barrier; no flight commands or persistent manager."""
from __future__ import annotations

import asyncio
import json
import math
import os
import time

import aiohttp

from src.action_safety import ActionSafetyError
from src.coordinated_takeoff_contract import TakeoffStageRequest, TakeoffStageResponse
from src.gcs_api_routes import GCS_COMMAND_REPORT_CAPABILITY_HEADER
from src.gcs_auth_client import gcs_auth_headers
from src.params import Params

TAKEOFF_CONTEXT_FD_ENV = "MDS_TAKEOFF_CONTEXT_FD"


def _failure(message):
    return ActionSafetyError(code="COORDINATED_TAKEOFF_ABORTED", phase="armed_barrier", message=message)


def load_takeoff_coordinator():
    """The parent supplies secrets through an inherited anonymous descriptor only."""
    descriptor = os.environ.pop(TAKEOFF_CONTEXT_FD_ENV, None)
    if descriptor is None:
        return None
    with os.fdopen(int(descriptor), "r") as source:
        encoded = source.read(8193)
    if len(encoded) > 8192:
        raise _failure("Coordinated takeoff context exceeds its size limit; no arm command sent.")
    context = json.loads(encoded)
    for key in ("command_id", "hw_id", "url", "capability"):
        if not isinstance(context.get(key), str) or not context[key].strip():
            raise _failure("Coordinated takeoff context is incomplete; no arm command sent.")
    if len(context["capability"]) < 43:
        raise _failure("Coordinated takeoff callback authority is missing; no arm command sent.")
    return CoordinatedTakeoffGate(context)


class CoordinatedTakeoffGate:
    def __init__(self, context):
        self.context = context
        self.sequence = 0
        self.challenge = None
        self.deadline = None
        self.lease_seconds = None
        self.released = False
        self.latest_observation = None
        self.sampler = None

    async def prepare(self, drone):
        if self.sampler is not None:
            snapshot = await self.sampler.observe()
            if not snapshot.complete:
                raise _failure("Native state subscriptions are unavailable; no arm command sent.")
        # Read the actual vehicle setting. Never extend/disable PX4 auto-disarm.
        try:
            timeout = float(await asyncio.wait_for(drone.param.get_param_float("COM_DISARM_PRFLT"), timeout=2))
        except Exception as exc:
            raise _failure("Cannot read PX4 ground auto-disarm timeout; no arm command sent.") from exc
        if not math.isfinite(timeout):
            raise _failure("PX4 ground auto-disarm timeout is invalid; no arm command sent.")
        self.lease_seconds = float(Params.COORDINATED_TAKEOFF_ARM_BARRIER_TIMEOUT_SEC)
        if timeout > 0:
            self.lease_seconds = min(self.lease_seconds, timeout - float(Params.COORDINATED_TAKEOFF_RELEASE_GUARD_SEC))
        if self.lease_seconds <= float(Params.COORDINATED_TAKEOFF_RELEASE_DELAY_SEC):
            raise _failure("PX4 ground auto-disarm window is too short for coordinated takeoff; no arm command sent.")
        # The default landed-state stream is 1 Hz. Re-sampling it cannot support
        # a sub-second barrier/clock check. Request the local SDK state cadence
        # explicitly rather than weakening freshness or raising flight limits.
        try:
            await asyncio.wait_for(asyncio.gather(
                drone.telemetry.set_rate_landed_state(Params.COORDINATED_TAKEOFF_STATE_RATE_HZ),
                drone.telemetry.set_rate_position(Params.COORDINATED_TAKEOFF_STATE_RATE_HZ),
            ), timeout=2)
        except Exception as exc:
            raise _failure("Cannot establish local takeoff state updates; no arm command sent.") from exc

    async def arm(self, operation):
        # Timeout begins at the first actual arm attempt, not during health checks.
        # asyncio.timeout is 3.11+, but the stock aircraft image uses 3.10.
        loop = asyncio.get_running_loop()
        expiry_handle = None
        expired = False

        def expire():
            nonlocal expired
            expired = True
            operation_task.cancel()

        def arm_attempt():
            nonlocal expiry_handle
            if self.deadline is None:
                self.deadline = time.monotonic() + self.lease_seconds
                expiry_handle = loop.call_at(loop.time() + self.lease_seconds, expire)

        operation_task = asyncio.create_task(operation(arm_attempt))
        try:
            await operation_task
            if expired:
                raise _failure("Coordinated arming window expired; takeoff was not released.")
        except asyncio.CancelledError as exc:
            if not expired:
                raise
            raise _failure("Coordinated arming window expired; takeoff was not released.") from exc
        finally:
            if expiry_handle is not None:
                expiry_handle.cancel()

    def remaining(self):
        return max(0.0, (self.deadline or time.monotonic()) - time.monotonic())

    async def bounded(self, awaitable):
        try:
            return await asyncio.wait_for(awaitable, timeout=self.remaining())
        except asyncio.TimeoutError as exc:
            raise _failure("Coordinated armed-wait lease expired; takeoff was not released.") from exc

    async def report(self, state, observation, *, reason=None):
        payload = TakeoffStageRequest(
            command_id=self.context["command_id"], hw_id=self.context["hw_id"], sequence=self.sequence,
            state=state, armed=getattr(observation, "armed", None) is True,
            landed_state=observation.landed_state if getattr(observation, "landed_state", None) in {"ON_GROUND", "TAKING_OFF", "IN_AIR"} else "UNKNOWN",
            lease_remaining_ms=int(self.remaining() * 1000), challenge=self.challenge, reason=reason,
        )
        self.sequence += 1
        headers = gcs_auth_headers({GCS_COMMAND_REPORT_CAPABILITY_HEADER: self.context["capability"]})
        timeout = min(0.8, self.remaining()) if state == "armed_ready" else 0.8
        if timeout <= 0:
            raise _failure("Coordinated armed-wait lease expired.")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(self.context["url"], json=payload.model_dump(exclude_none=True), headers=headers) as response:
                response.raise_for_status()
                result = TakeoffStageResponse.model_validate(await response.json())
        if result.decision == "release" and self.challenge is None:
            raise _failure("Coordinated takeoff release lacks a prior causal readiness challenge.")
        if result.decision != "abort" and not result.challenge:
            raise _failure("Coordinated takeoff response lacks readiness challenge authority.")
        self.challenge = result.challenge
        return result

    async def wait_for_release(self, drone, observe):
        release_time = None
        last_response = None
        wall_anchor, mono_anchor = time.time(), time.monotonic()
        tolerance = float(Params.COORDINATED_TAKEOFF_CLOCK_TOLERANCE_SEC)
        while True:
            observation = await self.bounded(self.sampler.observe() if self.sampler is not None else observe(drone))
            self.latest_observation = observation
            if not observation.complete or observation.armed is not True or not observation.on_ground:
                raise _failure("Fresh armed/on-ground confirmation was lost; takeoff was not released.")
            now, mono = time.time(), time.monotonic()
            if abs((now - wall_anchor) - (mono - mono_anchor)) > tolerance:
                raise _failure("Aircraft clock changed during coordinated takeoff; takeoff was not released.")
            if release_time is not None and now >= release_time:
                if now - release_time > tolerance or mono - last_response > tolerance or self.remaining() <= 0:
                    raise _failure("Coordinated takeoff release arrived too late; no takeoff command sent.")
                self.released = True
                return observation
            sent_wall, sent_mono = time.time(), time.monotonic()
            try:
                result = await self.bounded(self.report("armed_ready", observation))
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                raise _failure("Coordinated takeoff connection or response failed; takeoff was not released.") from exc
            received_wall, received_mono = time.time(), time.monotonic()
            rtt = received_mono - sent_mono
            if rtt > tolerance or abs((received_wall - sent_wall) - rtt) > tolerance:
                raise _failure("Coordinated takeoff timing could not be confirmed; takeoff was not released.")
            if result.decision == "abort":
                raise _failure(result.reason or "Coordinated takeoff was cancelled.")
            if release_time is not None and result.decision != "release":
                raise _failure("Coordinated takeoff release was revoked.")
            if result.server_time_unix_ms is None or abs(result.server_time_unix_ms / 1000 - (sent_wall + received_wall) / 2) > tolerance:
                raise _failure("Aircraft and GCS clocks are not aligned for coordinated takeoff.")
            last_response = received_mono
            if result.decision == "release":
                proposed = result.release_at_unix_ms / 1000
                if (release_time is not None and proposed != release_time) or (release_time is None and proposed <= received_wall):
                    raise _failure("Coordinated takeoff release changed or was already expired.")
                if proposed - received_wall >= self.remaining():
                    raise _failure("Coordinated takeoff release exceeds the aircraft armed-wait lease.")
                release_time = proposed
            await self.bounded(asyncio.sleep(min(float(Params.COORDINATED_TAKEOFF_REPORT_INTERVAL_SEC),
                max(0, release_time - time.time()) if release_time is not None else 1)))
