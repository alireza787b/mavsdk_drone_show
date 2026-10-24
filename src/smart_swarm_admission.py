"""One read-only Start decision shared by node admission and operator review.

This is neither a flight authority lease nor a reservation. The mission runtime
still samples PX4 and coordinates required roles before follower engagement.
"""
from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

from src.command_admission import AirborneAdmissionStatus, evaluate_cached_airborne_admission
from src.enums import CommandErrorCode, Mission, State
from src.px4_flight_modes import decode_px4_custom_mode, describe_px4_custom_mode


class SmartSwarmStartAdmission(BaseModel):
    hw_id: str
    status: Literal['ready', 'waiting', 'blocked', 'unknown']
    reason_code: str
    message: str
    observed_at_ms: int
    valid_for_ms: int = Field(default=0, ge=0)
    error_code: str | None = None


def evaluate_smart_swarm_start_admission(drone_config, *, max_age_sec, now_ms=None):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    hw_id = str(getattr(drone_config, 'hw_id', ''))

    def result(status, reason, message, error=CommandErrorCode.INVALID_STATE.value, valid=0):
        return SmartSwarmStartAdmission(hw_id=hw_id, status=status, reason_code=reason,
            message=message, observed_at_ms=now_ms, valid_for_ms=valid, error_code=error)

    if drone_config.state in {State.MISSION_READY.value, State.MISSION_EXECUTING.value}:
        if drone_config.mission == Mission.TAKE_OFF.value:
            return result('waiting', 'finishing_takeoff', 'Finishing takeoff', CommandErrorCode.ALREADY_EXECUTING.value)
        return result('blocked', 'mission_active', 'Another action is active', CommandErrorCode.ALREADY_EXECUTING.value)

    airborne = evaluate_cached_airborne_admission(drone_config, max_age_sec=max_age_sec, now_ms=now_ms)
    if not airborne.accepted:
        missing = airborne.status not in {AirborneAdmissionStatus.DISARMED, AirborneAdmissionStatus.NOT_AIRBORNE}
        not_armed = airborne.status in {AirborneAdmissionStatus.DISARMED, AirborneAdmissionStatus.ARMED_UNAVAILABLE,
            AirborneAdmissionStatus.HEARTBEAT_UNAVAILABLE, AirborneAdmissionStatus.HEARTBEAT_STALE}
        return result('unknown' if missing else 'blocked', airborne.status.value,
            'Checking aircraft' if missing else 'Aircraft not airborne',
            CommandErrorCode.NOT_ARMED.value if not_armed else CommandErrorCode.INVALID_STATE.value)

    try:
        main, sub = decode_px4_custom_mode(drone_config.custom_mode)
    except (TypeError, ValueError, OverflowError):
        main, sub = 0, 0
    if main == 0:
        return result('unknown', 'mode_unavailable', 'Checking aircraft mode')
    # Match the runtime's takeover boundary. Do not pre-empt native recovery,
    # or mistake an autonomous climb for a completed manual/QGC Take Off.
    if main == 4 and sub in {2, 10}:
        return result('waiting', 'finishing_takeoff', 'Finishing takeoff')
    if (main == 4 and sub in {5, 6, 9, 20}) or main == 10:
        return result('blocked', 'recovery_active', f'PX4 {describe_px4_custom_mode(drone_config.custom_mode)} active')
    remaining = max(0, int(float(max_age_sec) * 1000) - max(airborne.heartbeat_age_ms or 0, airborne.altitude_age_ms or 0))
    if not remaining:
        return result('unknown', 'evidence_expired', 'Checking aircraft')
    return result('ready', 'ready', 'Ready', error=None, valid=remaining)
