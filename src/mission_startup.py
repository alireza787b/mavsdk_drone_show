import asyncio
import logging
import time

from mavsdk.action import ActionError

from src.live_armability_utils import calculate_live_armability_request_timeout
from src.params import Params


def summarize_offboard_health(health, require_global_position: bool) -> dict:
    """Return a deterministic health summary for mission startup decisions."""
    state = {
        "armable": bool(getattr(health, "is_armable", False)),
        "global_position_ok": bool(getattr(health, "is_global_position_ok", False)),
        "home_position_ok": bool(getattr(health, "is_home_position_ok", False)),
        "local_position_ok": bool(getattr(health, "is_local_position_ok", False)),
        "gyro_ok": bool(getattr(health, "is_gyrometer_calibration_ok", False)),
        "accel_ok": bool(getattr(health, "is_accelerometer_calibration_ok", False)),
        "mag_ok": bool(getattr(health, "is_magnetometer_calibration_ok", False)),
    }

    blockers = []
    if not state["armable"]:
        blockers.append("PX4 armability")
    if require_global_position and not state["global_position_ok"]:
        blockers.append("global position")
    if require_global_position and not state["home_position_ok"]:
        blockers.append("home position")

    state["ready"] = not blockers
    state["blockers"] = blockers
    state["summary"] = (
        "ready for mission startup"
        if state["ready"]
        else "waiting for " + ", ".join(blockers)
    )
    return state


async def probe_offboard_armability(
    drone,
    *,
    require_global_position: bool,
    timeout: float | None = None,
    logger: logging.Logger | None = None,
):
    """
    Sample MAVSDK health until the vehicle is armable or the wait budget expires.

    Used by both mission startup and operator-facing launch probes so both paths
    share the same armability definition.
    """
    logger = logger or logging.getLogger(__name__)
    wait_timeout = float(timeout or getattr(Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 15.0))
    sample_timeout = float(getattr(Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.5))
    stable_samples = max(1, int(getattr(Params, "OFFBOARD_ARM_HEALTH_STABLE_SAMPLES", 1)))

    deadline = time.monotonic() + wait_timeout
    consecutive_ready = 0
    last_summary = None
    last_state = None
    health_iter = None

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            elapsed_sec = wait_timeout
            if last_state is None:
                return {
                    "ready": False,
                    "summary": "waiting for health samples",
                    "blockers": ["health stream"],
                    "armable": False,
                    "global_position_ok": False,
                    "home_position_ok": False,
                    "local_position_ok": False,
                    "gyro_ok": False,
                    "accel_ok": False,
                    "mag_ok": False,
                    "timed_out": True,
                    "elapsed_sec": elapsed_sec,
                    "require_global_position": require_global_position,
                }

            return {
                **last_state,
                "timed_out": True,
                "elapsed_sec": elapsed_sec,
                "require_global_position": require_global_position,
            }

        if health_iter is None:
            health_iter = drone.telemetry.health().__aiter__()

        try:
            health = await asyncio.wait_for(health_iter.__anext__(), timeout=min(sample_timeout, remaining))
        except asyncio.TimeoutError:
            continue
        except StopAsyncIteration:
            logger.warning("Mission startup health stream ended; resubscribing while readiness wait remains active.")
            health_iter = None
            await asyncio.sleep(min(0.1, remaining))
            continue

        state = summarize_offboard_health(health, require_global_position=require_global_position)
        elapsed_sec = wait_timeout - max(0.0, deadline - time.monotonic())
        last_state = {
            **state,
            "timed_out": False,
            "elapsed_sec": elapsed_sec,
            "require_global_position": require_global_position,
        }

        if state["summary"] != last_summary:
            logger.info(
                "Mission startup health: %s (armable=%s, global=%s, home=%s, local=%s, gyro=%s, accel=%s, mag=%s)",
                state["summary"],
                state["armable"],
                state["global_position_ok"],
                state["home_position_ok"],
                state["local_position_ok"],
                state["gyro_ok"],
                state["accel_ok"],
                state["mag_ok"],
            )
            last_summary = state["summary"]

        if state["ready"]:
            consecutive_ready += 1
            if consecutive_ready >= stable_samples:
                logger.info("Mission startup health confirmed after %.1fs.", elapsed_sec)
                return last_state
        else:
            consecutive_ready = 0


async def wait_until_offboard_armable(
    drone,
    *,
    require_global_position: bool,
    timeout: float | None = None,
    logger: logging.Logger | None = None,
):
    """
    Wait until MAVSDK reports the vehicle is actually armable for mission startup.

    Earlier pre-flight checks already cover GPS/home readiness. This gate closes the gap
    where PX4 can still transiently deny arming while SITL or hardware settles.
    """
    logger = logger or logging.getLogger(__name__)
    result = await probe_offboard_armability(
        drone,
        require_global_position=require_global_position,
        timeout=timeout,
        logger=logger,
    )
    if not result["ready"]:
        raise TimeoutError(
            "Timed out waiting for MAVSDK pre-arm health to become ready. "
            f"Last health state: {result.get('summary', 'no health samples received')}"
        )

    return result


async def arm_with_preflight_gate(
    drone,
    *,
    require_global_position: bool,
    logger: logging.Logger | None = None,
):
    """
    Wait for armability, then arm with bounded retries on transient denials.
    """
    logger = logger or logging.getLogger(__name__)
    max_attempts = max(1, int(getattr(Params, "OFFBOARD_ARM_MAX_ATTEMPTS", 3)))
    retry_delay = float(getattr(Params, "OFFBOARD_ARM_RETRY_DELAY_SEC", 2.0))

    last_error = None
    for attempt in range(1, max_attempts + 1):
        await wait_until_offboard_armable(
            drone,
            require_global_position=require_global_position,
            logger=logger,
        )
        try:
            logger.info("Arming the drone (attempt %d/%d).", attempt, max_attempts)
            await drone.action.arm()
            return
        except ActionError as exc:
            last_error = exc
            message = str(exc)
            denied = "denied" in message.lower()
            logger.warning("Arm attempt %d/%d failed: %s", attempt, max_attempts, message)
            if attempt >= max_attempts or not denied:
                raise
            await asyncio.sleep(retry_delay)

    if last_error:
        raise last_error
