"""Shared command request models for GCS submit and drone dispatch contracts."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

try:
    from src.enums import Mission
except ImportError:  # pragma: no cover - compatibility for direct src-path imports
    from enums import Mission


class CommandOrigin(BaseModel):
    """Origin payload attached to commands that carry launch-frame context."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90, description="Origin latitude")
    lon: float = Field(..., ge=-180, le=180, description="Origin longitude")
    alt: float = Field(0.0, description="Origin altitude (m MSL)")
    timestamp: Optional[int | str] = Field(None, description="Origin timestamp")
    source: Optional[str] = Field(None, description="Origin source label")


class DroneCommandRequest(BaseModel):
    """Canonical per-drone command payload sent from the GCS to a drone."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    mission_type: int = Field(
        ...,
        validation_alias=AliasChoices("mission_type", "missionType"),
        description="Mission code resolved to an integer value",
    )
    trigger_time: int = Field(
        0,
        ge=0,
        validation_alias=AliasChoices("trigger_time", "triggerTime"),
        description="Scheduled trigger time as Unix epoch seconds (0 = immediate)",
    )
    command_id: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("command_id", "commandId"),
        description="GCS command tracking ID",
    )
    auto_global_origin: Optional[bool] = Field(
        None,
        description="Whether the GCS should attach the active saved origin automatically",
    )
    use_global_setpoints: Optional[bool] = Field(
        None,
        description="Whether mission setpoints should use the global frame",
    )
    origin: Optional[CommandOrigin] = Field(
        None,
        description="Origin payload attached to the command when relevant",
    )
    takeoff_altitude: Optional[float] = Field(
        None,
        gt=0,
        description="Takeoff altitude override in meters",
    )
    update_branch: Optional[str] = Field(
        None,
        min_length=1,
        description="Git branch requested for UPDATE_CODE",
    )
    reboot_after_params: Optional[bool] = Field(
        None,
        description="Whether APPLY_COMMON_PARAMS should reboot the vehicle computer after completion",
    )
    mission_id: Optional[str] = Field(
        None,
        min_length=1,
        description="Mission identifier for QuickScout or future mission families",
    )
    return_behavior: Optional[str] = Field(
        None,
        min_length=1,
        description="Requested mission end behavior for QuickScout or future mission families",
    )
    waypoints: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="QuickScout or mission-specific waypoint payload",
    )

    @field_validator("mission_type", mode="before")
    @classmethod
    def _normalize_mission_type(cls, value: Any) -> int:
        if value in (None, ""):
            raise ValueError("mission_type is required")

        if isinstance(value, Mission):
            return value.value

        if isinstance(value, str):
            normalized = value.strip()
            if not normalized:
                raise ValueError("mission_type is required")

            try:
                return int(normalized)
            except ValueError:
                mission_name = normalized.upper()
                if mission_name in Mission.__members__:
                    return Mission[mission_name].value
                raise ValueError("mission_type must be a valid mission code or mission name") from None

        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("mission_type must be a valid mission code or mission name") from exc


class SubmitCommandRequest(DroneCommandRequest):
    """Canonical GCS command-submit payload."""

    operator_label: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("operator_label", "operatorLabel"),
        description="Short operator-facing label for dashboard feedback and audit trails",
    )
    target_drone_ids: Optional[List[str]] = Field(
        None,
        validation_alias=AliasChoices("target_drone_ids", "target_drones", "targetDrones"),
        description="Explicit target hardware IDs or position IDs (None = all configured drones)",
    )

    @field_validator("target_drone_ids", mode="before")
    @classmethod
    def _normalize_target_drones(cls, value: Any) -> Optional[List[str]]:
        if value in (None, []):
            return None

        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple, set)):
            raise ValueError("target_drone_ids must be an array of drone identifiers")

        normalized = [
            str(target_id).strip()
            for target_id in value
            if target_id not in (None, "")
        ]
        return normalized or None

    def to_drone_payload(self, *, command_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the drone-dispatch payload without GCS-only fields."""
        payload = self.model_dump(exclude_none=True)
        payload.pop("target_drone_ids", None)
        payload.pop("operator_label", None)
        if command_id is not None:
            payload["command_id"] = command_id
        return payload
