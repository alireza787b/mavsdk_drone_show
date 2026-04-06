"""Shared command request models for GCS submit and drone dispatch contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

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


class PrecisionMoveFrame(str, Enum):
    BODY = "body"
    NED = "ned"


class PrecisionMoveYawMode(str, Enum):
    HOLD_CURRENT = "hold_current"
    ABSOLUTE_HEADING = "absolute_heading"
    RELATIVE_DELTA = "relative_delta"


class PrecisionMoveHoldMode(str, Enum):
    PX4_HOLD = "px4_hold"


class PrecisionMoveYaw(BaseModel):
    """Yaw target for local precision-move actions."""

    model_config = ConfigDict(extra="forbid")

    mode: PrecisionMoveYawMode = Field(
        default=PrecisionMoveYawMode.HOLD_CURRENT,
        description="Yaw control mode to apply during the move",
    )
    degrees: Optional[float] = Field(
        None,
        description="Yaw target in degrees. Meaning depends on mode.",
    )

    @model_validator(mode="after")
    def _validate_mode(self) -> "PrecisionMoveYaw":
        if self.mode == PrecisionMoveYawMode.HOLD_CURRENT:
            if self.degrees not in (None, 0, 0.0):
                raise ValueError("yaw.degrees must be omitted for hold_current mode")
            self.degrees = None
            return self

        if self.degrees is None:
            raise ValueError("yaw.degrees is required unless yaw.mode is hold_current")

        return self


class PrecisionMoveRequest(BaseModel):
    """Relative local move request executed from the drone's current local state."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    frame: PrecisionMoveFrame = Field(..., description="Translation input frame")
    translation_m: Dict[str, float] = Field(
        ...,
        validation_alias=AliasChoices("translation_m", "translationM"),
        description="Translation vector in metres. Keys depend on the selected frame.",
    )
    yaw: PrecisionMoveYaw = Field(
        default_factory=PrecisionMoveYaw,
        description="Yaw target to apply during the move",
    )
    speed_m_s: Optional[float] = Field(
        None,
        gt=0,
        description="Requested approach speed in metres per second",
    )
    position_tolerance_m: Optional[float] = Field(
        None,
        gt=0,
        description="Position tolerance for convergence",
    )
    yaw_tolerance_deg: Optional[float] = Field(
        None,
        gt=0,
        description="Yaw tolerance for convergence",
    )
    settle_time_sec: Optional[float] = Field(
        None,
        gt=0,
        description="Time the drone must remain within tolerance before success",
    )
    timeout_sec: Optional[float] = Field(
        None,
        gt=0,
        description="Execution timeout budget",
    )
    hold_mode: PrecisionMoveHoldMode = Field(
        default=PrecisionMoveHoldMode.PX4_HOLD,
        description="Mode to enter after convergence",
    )

    @field_validator("frame", mode="before")
    @classmethod
    def _normalize_frame(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("translation_m", mode="before")
    @classmethod
    def _validate_translation_payload(cls, value: Any) -> Dict[str, float]:
        if not isinstance(value, dict) or not value:
            raise ValueError("translation_m must be a non-empty object")

        normalized: Dict[str, float] = {}
        for key, raw_value in value.items():
            normalized_key = str(key).strip().lower()
            if not normalized_key:
                raise ValueError("translation_m contains a blank key")
            try:
                normalized[normalized_key] = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"translation_m.{normalized_key} must be numeric") from exc

        return normalized

    @model_validator(mode="after")
    def _validate_shape(self) -> "PrecisionMoveRequest":
        allowed_keys = (
            {"forward", "right", "up"}
            if self.frame == PrecisionMoveFrame.BODY
            else {"north", "east", "up"}
        )
        unexpected_keys = set(self.translation_m.keys()) - allowed_keys
        if unexpected_keys:
            expected = ", ".join(sorted(allowed_keys))
            raise ValueError(
                f"translation_m keys {sorted(unexpected_keys)} are invalid for frame={self.frame.value}; "
                f"expected only {expected}"
            )

        normalized_translation = {
            key: float(self.translation_m.get(key, 0.0))
            for key in sorted(allowed_keys)
        }
        self.translation_m = normalized_translation

        has_non_zero_translation = any(abs(component) > 1e-9 for component in normalized_translation.values())
        if not has_non_zero_translation:
            if self.yaw.mode == PrecisionMoveYawMode.HOLD_CURRENT:
                raise ValueError("precision_move must include a translation or a yaw target")
            if (
                self.yaw.mode == PrecisionMoveYawMode.RELATIVE_DELTA
                and abs(float(self.yaw.degrees or 0.0)) <= 1e-9
            ):
                raise ValueError("precision_move relative yaw-only requests must use a non-zero yaw delta")

        return self

    @classmethod
    def from_action_payload(cls, payload: Dict[str, Any]) -> "PrecisionMoveRequest":
        """Accept either a bare payload or a command-style wrapper with precision_move."""
        if not isinstance(payload, dict):
            raise ValueError("precision move action payload must be a JSON object")

        nested_payload = payload.get("precision_move", payload.get("precisionMove"))
        candidate = nested_payload if isinstance(nested_payload, dict) else payload
        return cls.model_validate(candidate)


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
    precision_move: Optional[PrecisionMoveRequest] = Field(
        None,
        validation_alias=AliasChoices("precision_move", "precisionMove"),
        description="Typed relative-move payload for PRECISION_MOVE",
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

    @model_validator(mode="after")
    def _validate_mission_payload(self) -> "DroneCommandRequest":
        if self.mission_type == Mission.PRECISION_MOVE.value:
            if self.trigger_time != 0:
                raise ValueError("PRECISION_MOVE currently supports only immediate execution (trigger_time=0)")
            if self.precision_move is None:
                raise ValueError("precision_move payload is required for PRECISION_MOVE")
        elif self.precision_move is not None:
            raise ValueError("precision_move payload is only valid for PRECISION_MOVE")

        return self


class SubmitCommandRequest(DroneCommandRequest):
    """Canonical GCS command-submit payload."""

    idempotency_key: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("idempotency_key", "idempotencyKey", "client_command_id", "clientCommandId"),
        min_length=1,
        max_length=200,
        description="Client-supplied replay key used to make command submission idempotent across retries",
    )
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

    @field_validator("idempotency_key", mode="before")
    @classmethod
    def _normalize_idempotency_key(cls, value: Any) -> Optional[str]:
        if value in (None, ""):
            return None

        normalized = str(value).strip()
        if not normalized:
            raise ValueError("idempotency_key must not be blank")
        return normalized

    def to_drone_payload(self, *, command_id: Optional[str] = None) -> Dict[str, Any]:
        """Return the drone-dispatch payload without GCS-only fields."""
        payload = self.model_dump(exclude_none=True)
        payload.pop("idempotency_key", None)
        payload.pop("target_drone_ids", None)
        payload.pop("operator_label", None)
        if command_id is not None:
            payload["command_id"] = command_id
        return payload
