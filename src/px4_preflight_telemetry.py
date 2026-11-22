"""Typed PX4 Events observations shared by the companion and GCS."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError

from src.px4_flight_modes import PX4_TAKEOFF_CUSTOM_MODE

REPORT_KEYS = ('px4_arming_report', 'px4_takeoff_arming_report')


class Px4PreflightProblem(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    severity: Literal['EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG']
    description: str = Field(default='', max_length=4096)


class Px4Verdict(BaseModel):
    source: Literal['px4_events']
    mode: str = Field(min_length=1, max_length=96)
    custom_mode: int = Field(strict=True, gt=0, le=0xFFFFFFFF)
    can_arm: bool = Field(strict=True)
    revision: str = Field(pattern=r'^[0-9a-f]{24}$')


class Px4PreflightReport(Px4Verdict):
    mode_problems: Annotated[list[Px4PreflightProblem], Field(max_length=24)] | None = None
    remaining_valid_ms: int = Field(strict=True, gt=0, le=5000)
    sample: int = Field(strict=True, gt=0)


class FleetPx4PreflightReport(Px4Verdict):
    expires_at_gcs_ms: int = Field(strict=True, gt=0)
    expires_at_gcs_monotonic_ms: int = Field(strict=True, gt=0)


def current_preflight_report(state, key='px4_arming_report'):
    """Validate a disarmed observation and its exact requested mode."""
    if state.get('telemetry_available') is not True or state.get('is_armed') is not False:
        return None
    if type(state.get('landed_state')) is not int or state['landed_state'] != 1:
        return None
    expected = state.get('flight_mode') if key == REPORT_KEYS[0] else PX4_TAKEOFF_CUSTOM_MODE
    try:
        report = Px4PreflightReport.model_validate(state.get(key))
    except ValidationError:
        return None
    return report if type(expected) is int and report.custom_mode == expected else None
