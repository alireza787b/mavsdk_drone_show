"""Read-only PX4 Events report on the shared telemetry path, never admission."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationError


class Px4PreflightProblem(BaseModel):
    message: str = Field(min_length=1, max_length=512)
    severity: Literal['EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG']
    description: str = Field(default='', max_length=4096)


class Px4PreflightReport(BaseModel):
    source: Literal['px4_events']
    mode: str = Field(min_length=1, max_length=96)
    custom_mode: int = Field(strict=True, gt=0, le=0xFFFFFFFF)
    can_arm: bool = Field(strict=True)
    mode_problems: Annotated[list[Px4PreflightProblem], Field(max_length=128)]
    remaining_valid_ms: int = Field(strict=True, gt=0, le=5000)


class FleetPx4PreflightReport(Px4PreflightReport):
    expires_at_gcs_ms: int = Field(strict=True, gt=0)


def current_preflight_report(state: dict) -> Px4PreflightReport | None:
    """Validate the producer's observation without certifying transport freshness."""
    if state.get('telemetry_available') is not True or state.get('is_armed') is not False:
        return None
    if type(state.get('landed_state')) is not int or state['landed_state'] != 1:
        return None
    try:
        report = Px4PreflightReport.model_validate(state.get('px4_arming_report'))
    except ValidationError:
        return None
    if type(state.get('flight_mode')) is not int or state['flight_mode'] != report.custom_mode:
        return None
    return report


def relay_preflight_report(state: dict, *, node_sent_at_ms: int | None,
                           received_at_ms: int) -> FleetPx4PreflightReport | None:
    """Convert a node lease once; refuse unsynchronized or expired evidence."""
    report = current_preflight_report(state)
    if report is None or node_sent_at_ms is None or node_sent_at_ms > received_at_ms:
        return None
    expires_at = node_sent_at_ms + report.remaining_valid_ms
    if expires_at <= received_at_ms:
        return None
    return FleetPx4PreflightReport(**report.model_dump(), expires_at_gcs_ms=expires_at)
