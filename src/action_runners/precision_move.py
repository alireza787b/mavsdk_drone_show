"""Precision Move action runner using local-frame MAVSDK offboard control."""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import dataclass
from typing import Any

import requests

from src.action_runners.base import ActionExecutionContext, ActionInvocation
from src.command_contract import (
    PrecisionMoveFrame,
    PrecisionMoveHoldMode,
    PrecisionMoveRequest,
    PrecisionMoveYawMode,
)
from src.drone_api_routes import DRONE_LOCAL_POSITION_ROUTE, DRONE_NAVIGATION_HOME_ROUTE, DRONE_STATE_ROUTE
from src.params import Params


LOCAL_API_TIMEOUT_SEC = 1.0
AIRBORNE_MIN_RELATIVE_ALTITUDE_M = 0.3


@dataclass(frozen=True)
class LocalMoveSnapshot:
    north_m: float
    east_m: float
    down_m: float
    yaw_deg: float
    is_armed: bool
    telemetry_available: bool
    flight_mode: str | None


@dataclass(frozen=True)
class PrecisionMoveTarget:
    north_m: float
    east_m: float
    down_m: float
    yaw_deg: float


def _normalize_heading_deg(value: float) -> float:
    return float(value) % 360.0


def _signed_heading_error_deg(target_deg: float, current_deg: float) -> float:
    return ((target_deg - current_deg + 180.0) % 360.0) - 180.0


def _body_to_ned_translation(forward_m: float, right_m: float, heading_deg: float) -> tuple[float, float]:
    heading_rad = math.radians(_normalize_heading_deg(heading_deg))
    north_m = (forward_m * math.cos(heading_rad)) - (right_m * math.sin(heading_rad))
    east_m = (forward_m * math.sin(heading_rad)) + (right_m * math.cos(heading_rad))
    return north_m, east_m


def normalize_heading_deg(value: float) -> float:
    return _normalize_heading_deg(value)


def shortest_heading_error_deg(current_deg: float, target_deg: float) -> float:
    return _signed_heading_error_deg(target_deg, current_deg)


def body_translation_to_ned(*, forward_m: float, right_m: float, up_m: float, yaw_deg: float) -> tuple[float, float, float]:
    north_m, east_m = _body_to_ned_translation(forward_m, right_m, yaw_deg)
    return north_m, east_m, up_m


def _local_get_json(route: str, timeout: float = LOCAL_API_TIMEOUT_SEC) -> dict[str, Any]:
    response = requests.get(f"http://127.0.0.1:{Params.drone_api_port}{route}", timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Local API route {route} did not return an object payload")
    return payload


def _read_local_move_snapshot(timeout: float = LOCAL_API_TIMEOUT_SEC) -> LocalMoveSnapshot:
    drone_state = _local_get_json(DRONE_STATE_ROUTE, timeout=timeout)
    local_position = _local_get_json(DRONE_LOCAL_POSITION_ROUTE, timeout=timeout)

    time_boot_ms = int(local_position.get("time_boot_ms", 0) or 0)
    if time_boot_ms <= 0:
        raise ValueError("LOCAL_POSITION_NED is unavailable")

    return LocalMoveSnapshot(
        north_m=float(local_position["x"]),
        east_m=float(local_position["y"]),
        down_m=float(local_position["z"]),
        yaw_deg=_normalize_heading_deg(float(drone_state.get("yaw", 0.0))),
        is_armed=bool(drone_state.get("is_armed")),
        telemetry_available=bool(drone_state.get("telemetry_available", True)),
        flight_mode=str(drone_state.get("flight_mode")) if drone_state.get("flight_mode") is not None else None,
    )


def _read_local_relative_altitude(timeout: float = LOCAL_API_TIMEOUT_SEC) -> float | None:
    try:
        drone_state = _local_get_json(DRONE_STATE_ROUTE, timeout=timeout)
        home_position = _local_get_json(DRONE_NAVIGATION_HOME_ROUTE, timeout=timeout)
        current_altitude = float(drone_state["position_alt"])
        home_altitude = float(home_position["altitude"])
    except (KeyError, TypeError, ValueError, requests.RequestException):
        return None

    return current_altitude - home_altitude


def _resolve_request(invocation: ActionInvocation) -> PrecisionMoveRequest:
    if not invocation.request_payload:
        raise ValueError("precision_move action requires --request-json or --request-file")
    return PrecisionMoveRequest.from_action_payload(invocation.request_payload)


def _resolve_target_translation(request: PrecisionMoveRequest, heading_deg: float) -> tuple[float, float, float]:
    translation = request.translation_m
    if request.frame == PrecisionMoveFrame.BODY:
        north_m, east_m = _body_to_ned_translation(
            float(translation.get("forward", 0.0)),
            float(translation.get("right", 0.0)),
            heading_deg,
        )
        up_m = float(translation.get("up", 0.0))
        return north_m, east_m, up_m

    return (
        float(translation.get("north", 0.0)),
        float(translation.get("east", 0.0)),
        float(translation.get("up", 0.0)),
    )


def _resolve_target_yaw_deg(request: PrecisionMoveRequest, current_yaw_deg: float) -> float:
    if request.yaw.mode == PrecisionMoveYawMode.HOLD_CURRENT:
        return _normalize_heading_deg(current_yaw_deg)
    if request.yaw.mode == PrecisionMoveYawMode.RELATIVE_DELTA:
        return _normalize_heading_deg(current_yaw_deg + float(request.yaw.degrees or 0.0))
    return _normalize_heading_deg(float(request.yaw.degrees or 0.0))


def _build_target(
    request: PrecisionMoveRequest,
    *,
    current_north_m: float,
    current_east_m: float,
    current_down_m: float,
    current_yaw_deg: float,
) -> PrecisionMoveTarget:
    translation_north_m, translation_east_m, translation_up_m = _resolve_target_translation(request, current_yaw_deg)
    target_yaw_deg = _resolve_target_yaw_deg(request, current_yaw_deg)
    return PrecisionMoveTarget(
        north_m=current_north_m + translation_north_m,
        east_m=current_east_m + translation_east_m,
        down_m=current_down_m - translation_up_m,
        yaw_deg=target_yaw_deg,
    )


def _build_velocity_vector(
    north_error_m: float,
    east_error_m: float,
    down_error_m: float,
    max_speed_m_s: float,
) -> tuple[float, float, float]:
    distance_m = math.sqrt((north_error_m ** 2) + (east_error_m ** 2) + (down_error_m ** 2))
    if distance_m <= 1e-9:
        return 0.0, 0.0, 0.0

    commanded_speed = min(max_speed_m_s, max(0.2, distance_m))
    scale = commanded_speed / distance_m
    return (
        north_error_m * scale,
        east_error_m * scale,
        down_error_m * scale,
    )


def _load_offboard_types():
    from mavsdk.offboard import OffboardError, PositionNedYaw, VelocityNedYaw

    return OffboardError, PositionNedYaw, VelocityNedYaw


async def _start_offboard_with_retry(
    drone: Any,
    *,
    north_m: float,
    east_m: float,
    down_m: float,
    yaw_deg: float,
    logger: Any,
) -> None:
    offboard_error_cls, position_cls, velocity_cls = _load_offboard_types()
    max_attempts = max(1, int(getattr(Params, "OFFBOARD_START_MAX_ATTEMPTS", 3)))
    retry_delay_sec = max(0.1, float(getattr(Params, "OFFBOARD_START_RETRY_DELAY_SEC", 1.0)))

    initial_position = position_cls(north_m, east_m, down_m, yaw_deg)
    initial_velocity = velocity_cls(0.0, 0.0, 0.0, yaw_deg)
    await drone.offboard.set_position_velocity_ned(initial_position, initial_velocity)

    for attempt in range(1, max_attempts + 1):
        try:
            await drone.offboard.start()
            return
        except offboard_error_cls as exc:
            logger.warning("Offboard start attempt %s/%s failed: %s", attempt, max_attempts, exc)
            if attempt >= max_attempts:
                raise
            await drone.offboard.set_position_velocity_ned(initial_position, initial_velocity)
            await asyncio.sleep(retry_delay_sec)


async def _wait_until_hold_mode(drone: Any, timeout_sec: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_sec
    async for mode in drone.telemetry.flight_mode():
        mode_name = getattr(mode, "name", str(mode))
        if str(mode_name).upper() == "HOLD":
            return
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for PX4 Hold mode after precision move completion")


async def _safe_stop_offboard(drone: Any, logger: Any) -> None:
    try:
        await drone.offboard.stop()
    except Exception as exc:
        logger.warning("Offboard stop after precision move did not succeed cleanly: %s", exc)


async def precision_move(context: ActionExecutionContext, invocation: ActionInvocation) -> None:
    """Execute a local relative move and then hand control to PX4 Hold."""
    request = _resolve_request(invocation)
    logger = context.logger
    drone = context.drone
    if drone is None:
        raise ValueError("precision_move requires an active MAVSDK drone connection")

    start_snapshot = _read_local_move_snapshot()
    if not start_snapshot.telemetry_available:
        raise ValueError("precision_move requires fresh local telemetry")
    if not start_snapshot.is_armed:
        raise ValueError("precision_move requires the drone to be armed and airborne")

    relative_altitude_m = _read_local_relative_altitude()
    if relative_altitude_m is not None and relative_altitude_m <= AIRBORNE_MIN_RELATIVE_ALTITUDE_M:
        raise ValueError(
            f"precision_move requires the drone to be airborne (relative altitude={relative_altitude_m:.2f}m)"
        )

    translation_north_m, translation_east_m, translation_up_m = _resolve_target_translation(
        request,
        start_snapshot.yaw_deg,
    )
    total_translation_m = math.sqrt(
        (translation_north_m ** 2) + (translation_east_m ** 2) + (translation_up_m ** 2)
    )
    max_translation_m = float(getattr(Params, "PRECISION_MOVE_MAX_TRANSLATION_M", 100.0))
    if total_translation_m > max_translation_m:
        raise ValueError(
            f"precision_move translation {total_translation_m:.2f}m exceeds configured max {max_translation_m:.2f}m"
        )

    target = _build_target(
        request,
        current_north_m=start_snapshot.north_m,
        current_east_m=start_snapshot.east_m,
        current_down_m=start_snapshot.down_m,
        current_yaw_deg=start_snapshot.yaw_deg,
    )

    max_speed_m_s = min(
        float(request.speed_m_s or getattr(Params, "PRECISION_MOVE_DEFAULT_SPEED_MPS", 1.0)),
        float(getattr(Params, "PRECISION_MOVE_MAX_SPEED_MPS", 5.0)),
    )
    position_tolerance_m = max(
        float(request.position_tolerance_m or getattr(Params, "PRECISION_MOVE_DEFAULT_POSITION_TOLERANCE_M", 0.15)),
        float(getattr(Params, "PRECISION_MOVE_MIN_POSITION_TOLERANCE_M", 0.05)),
    )
    yaw_tolerance_deg = float(
        request.yaw_tolerance_deg or getattr(Params, "PRECISION_MOVE_DEFAULT_YAW_TOLERANCE_DEG", 5.0)
    )
    settle_time_sec = float(request.settle_time_sec or getattr(Params, "PRECISION_MOVE_DEFAULT_SETTLE_TIME_SEC", 1.0))
    timeout_sec = min(
        float(request.timeout_sec or getattr(Params, "PRECISION_MOVE_DEFAULT_TIMEOUT_SEC", 30.0)),
        float(getattr(Params, "PRECISION_MOVE_MAX_TIMEOUT_SEC", 180.0)),
    )
    control_rate_hz = max(2.0, float(getattr(Params, "PRECISION_MOVE_CONTROL_RATE_HZ", 10.0)))
    control_period_sec = 1.0 / control_rate_hz

    logger.info(
        "Starting precision move: frame=%s translation=(N %.2f, E %.2f, U %.2f) target_yaw=%.1f speed=%.2f",
        request.frame.value,
        translation_north_m,
        translation_east_m,
        translation_up_m,
        target.yaw_deg,
        max_speed_m_s,
    )

    settle_started_at: float | None = None
    deadline = time.monotonic() + timeout_sec
    offboard_started = False

    try:
        await _start_offboard_with_retry(
            drone,
            north_m=start_snapshot.north_m,
            east_m=start_snapshot.east_m,
            down_m=start_snapshot.down_m,
            yaw_deg=start_snapshot.yaw_deg,
            logger=logger,
        )
        offboard_started = True

        _, position_cls, velocity_cls = _load_offboard_types()
        while time.monotonic() < deadline:
            snapshot = _read_local_move_snapshot()
            north_error_m = target.north_m - snapshot.north_m
            east_error_m = target.east_m - snapshot.east_m
            down_error_m = target.down_m - snapshot.down_m
            position_error_m = math.sqrt(
                (north_error_m ** 2) + (east_error_m ** 2) + (down_error_m ** 2)
            )
            yaw_error_deg = abs(_signed_heading_error_deg(target.yaw_deg, snapshot.yaw_deg))

            velocity_vector = _build_velocity_vector(
                north_error_m,
                east_error_m,
                down_error_m,
                max_speed_m_s,
            )
            await drone.offboard.set_position_velocity_ned(
                position_cls(target.north_m, target.east_m, target.down_m, target.yaw_deg),
                velocity_cls(*velocity_vector, target.yaw_deg),
            )

            if position_error_m <= position_tolerance_m and yaw_error_deg <= yaw_tolerance_deg:
                if settle_started_at is None:
                    settle_started_at = time.monotonic()
                elif (time.monotonic() - settle_started_at) >= settle_time_sec:
                    break
            else:
                settle_started_at = None

            await asyncio.sleep(control_period_sec)
        else:
            raise TimeoutError("precision_move timed out before converging within tolerance")

        await drone.offboard.set_position_velocity_ned(
            position_cls(target.north_m, target.east_m, target.down_m, target.yaw_deg),
            velocity_cls(0.0, 0.0, 0.0, target.yaw_deg),
        )
        await asyncio.sleep(min(0.25, control_period_sec))

        if request.hold_mode == PrecisionMoveHoldMode.PX4_HOLD:
            await _safe_stop_offboard(drone, logger)
            offboard_started = False
            await _wait_until_hold_mode(drone)

        logger.info(
            "Precision move completed: target=(N %.2f, E %.2f, D %.2f) yaw=%.1f",
            target.north_m,
            target.east_m,
            target.down_m,
            target.yaw_deg,
        )
        return
    except Exception:
        if offboard_started:
            await _safe_stop_offboard(drone, logger)
        raise
