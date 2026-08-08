"""Shared command request models for GCS submit and drone dispatch contracts."""

from __future__ import annotations

import math
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.enums import Mission, resolve_executable_mission


class CommandOrigin(BaseModel):
    """Origin payload attached to commands that carry launch-frame context."""

    model_config = ConfigDict(extra="forbid")

    lat: float = Field(..., ge=-90, le=90, description="Origin latitude")
    lon: float = Field(..., ge=-180, le=180, description="Origin longitude")
    alt: float = Field(0.0, description="Origin altitude (m MSL)")
    timestamp: Optional[int | str] = Field(None, description="Origin timestamp")
    source: Optional[str] = Field(None, description="Origin source label")


class GroundTestSafetyMode(str, Enum):
    """How the operator satisfied the Arm/Disarm Ground Test safety gate."""

    OPERATOR_ACKNOWLEDGED = "operator_acknowledged"
    SITL_NOT_APPLICABLE = "sitl_not_applicable"


class GroundTestSafetyAcknowledgement(BaseModel):
    """Typed, auditable safety acknowledgement for the motor-arm ground test.

    Real-aircraft execution requires each physical condition to be explicitly
    true.  SITL does not silently inherit that assertion: callers must use the
    distinct ``sitl_not_applicable`` mode, which the runtime verifies against
    its own configured mode before any arm command is allowed.
    """

    model_config = ConfigDict(extra="forbid")

    mode: GroundTestSafetyMode = Field(
        ...,
        description="Real-aircraft operator acknowledgement or explicit SITL exemption",
    )
    props_removed: Optional[bool] = Field(
        None,
        strict=True,
        description="Operator confirms all propellers are removed",
    )
    airframe_secured: Optional[bool] = Field(
        None,
        strict=True,
        description="Operator confirms the airframe is physically secured",
    )
    area_clear: Optional[bool] = Field(
        None,
        strict=True,
        description="Operator confirms the motor test area is clear",
    )

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> "GroundTestSafetyAcknowledgement":
        conditions = {
            "props_removed": self.props_removed,
            "airframe_secured": self.airframe_secured,
            "area_clear": self.area_clear,
        }
        if self.mode == GroundTestSafetyMode.OPERATOR_ACKNOWLEDGED:
            missing = [name for name, value in conditions.items() if value is not True]
            if missing:
                raise ValueError(
                    "operator_acknowledged requires props_removed, "
                    "airframe_secured, and area_clear to all be true"
                )
            return self

        if any(value is not None for value in conditions.values()):
            raise ValueError(
                "sitl_not_applicable must omit real-aircraft safety condition fields"
            )
        return self

    def validate_for_runtime(self, *, sim_mode: bool) -> None:
        """Fail closed when the acknowledgement does not match runtime truth."""
        expected_mode = (
            GroundTestSafetyMode.SITL_NOT_APPLICABLE
            if sim_mode
            else GroundTestSafetyMode.OPERATOR_ACKNOWLEDGED
        )
        if self.mode != expected_mode:
            if sim_mode:
                raise ValueError(
                    "SITL Arm/Disarm Ground Test requires mode=sitl_not_applicable"
                )
            raise ValueError(
                "Real-aircraft Arm/Disarm Ground Test requires explicit confirmation "
                "that propellers are removed, the airframe is secured, and the area is clear"
            )

    @classmethod
    def from_action_payload(
        cls,
        payload: Optional[Dict[str, Any]],
    ) -> "GroundTestSafetyAcknowledgement":
        """Load the canonical acknowledgement from an actions.py request payload."""
        if not isinstance(payload, dict):
            raise ValueError("ground_test_safety acknowledgement is required")
        acknowledgement = payload.get("ground_test_safety")
        if not isinstance(acknowledgement, dict):
            raise ValueError("ground_test_safety acknowledgement is required")
        return cls.model_validate(acknowledgement)


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
        allow_inf_nan=False,
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
        if not math.isfinite(float(self.degrees)):
            raise ValueError("yaw.degrees must be a finite number")

        return self


class PrecisionMoveRequest(BaseModel):
    """Relative local move request executed from the drone's current local state."""

    model_config = ConfigDict(extra="forbid")

    frame: PrecisionMoveFrame = Field(..., description="Translation input frame")
    translation_m: Dict[str, float] = Field(
        ...,
        description="Translation vector in metres. Keys depend on the selected frame.",
    )
    yaw: PrecisionMoveYaw = Field(
        default_factory=PrecisionMoveYaw,
        description="Yaw target to apply during the move",
    )
    speed_m_s: Optional[float] = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description="Requested approach speed in metres per second",
    )
    position_tolerance_m: Optional[float] = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description="Position tolerance for convergence",
    )
    yaw_tolerance_deg: Optional[float] = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description="Yaw tolerance for convergence",
    )
    settle_time_sec: Optional[float] = Field(
        None,
        gt=0,
        allow_inf_nan=False,
        description="Time the drone must remain within tolerance before success",
    )
    timeout_sec: Optional[float] = Field(
        None,
        gt=0,
        allow_inf_nan=False,
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
                parsed = float(raw_value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"translation_m.{normalized_key} must be numeric") from exc
            if not math.isfinite(parsed):
                raise ValueError(f"translation_m.{normalized_key} must be a finite number")
            normalized[normalized_key] = parsed

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

        nested_payload = payload.get("precision_move")
        candidate = nested_payload if isinstance(nested_payload, dict) else payload
        return cls.model_validate(candidate)


class CommandPayloadRequest(BaseModel):
    """Mission payload shared by operator submission and node dispatch."""

    model_config = ConfigDict(extra="forbid")

    mission_type: int = Field(
        ...,
        description="Mission code resolved to an integer value",
    )
    trigger_time: int = Field(
        0,
        ge=0,
        strict=True,
        description="Scheduled trigger time as Unix epoch seconds (0 = immediate)",
    )
    command_id: Optional[str] = Field(
        None,
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
    ground_test_safety: Optional[GroundTestSafetyAcknowledgement] = Field(
        None,
        description="Required physical-safety acknowledgement for Mission.TEST",
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
        description="Typed relative-move payload for PRECISION_MOVE",
    )

    @field_validator("mission_type", mode="before")
    @classmethod
    def _normalize_mission_type(cls, value: Any) -> int:
        if value in (None, ""):
            raise ValueError("mission_type is required")
        mission = resolve_executable_mission(value)
        if mission is None:
            raise ValueError("mission_type must identify an executable mission")
        return mission.value

    @model_validator(mode="after")
    def _validate_mission_payload(self) -> "CommandPayloadRequest":
        if self.mission_type == Mission.TEST.value:
            if self.ground_test_safety is None:
                raise ValueError(
                    "ground_test_safety acknowledgement is required for Mission.TEST"
                )
        elif self.ground_test_safety is not None:
            raise ValueError(
                "ground_test_safety is only valid for Mission.TEST"
            )

        if self.mission_type == Mission.PRECISION_MOVE.value:
            if self.trigger_time != 0:
                raise ValueError("PRECISION_MOVE currently supports only immediate execution (trigger_time=0)")
            if self.precision_move is None:
                raise ValueError("precision_move payload is required for PRECISION_MOVE")
        elif self.precision_move is not None:
            raise ValueError("precision_move payload is only valid for PRECISION_MOVE")

        return self


class DroneCommandRequest(CommandPayloadRequest):
    """Canonical GCS-to-node command envelope.

    ``target_hw_id`` binds the logical target selected by the GCS to the node
    that receives the request. It remains optional during rolling upgrades so
    updated nodes can accept an older GCS; every updated GCS supplies it and
    verifies the returned node identity.
    """

    target_hw_id: Optional[str] = Field(
        None,
        min_length=1,
        description="Hardware ID this per-node dispatch is intended for",
    )
    command_report_capability: Optional[str] = Field(
        None,
        min_length=43,
        max_length=200,
        description=(
            "Opaque per-command/per-target capability used only to authenticate "
            "execution callbacks to the GCS"
        ),
        repr=False,
    )

    @field_validator("target_hw_id", mode="before")
    @classmethod
    def _normalize_target_hw_id(cls, value: Any) -> Any:
        if value is None:
            return None
        normalized = str(value).strip()
        if not normalized:
            raise ValueError("target_hw_id must not be blank")
        return normalized

    @field_validator("command_report_capability", mode="before")
    @classmethod
    def _normalize_command_report_capability(cls, value: Any) -> Any:
        # Optional only for the nodes-first mixed-version rollout: updated
        # nodes can still receive an old-GCS request.  An updated GCS always
        # sends this field and rejects every callback that does not prove it.
        if value is None:
            return None
        if type(value) is not str or not value or value != value.strip():
            raise ValueError("command_report_capability must be an opaque non-blank string")
        return value

    @model_validator(mode="after")
    def _validate_command_report_binding(self) -> "DroneCommandRequest":
        """Separate the rolling-upgrade shim from the trusted v2 envelope.

        A nodes-first rollout requires updated nodes to accept an older GCS,
        which supplies no callback capability. Once a capability is supplied,
        the command must also carry the exact command and target identities
        that scope it; partial v2 envelopes fail closed.
        """
        if self.command_report_capability is None:
            return self
        if self.command_id is None or not str(self.command_id).strip():
            raise ValueError("command_report_capability requires command_id")
        if self.target_hw_id is None:
            raise ValueError("command_report_capability requires target_hw_id")
        return self


def normalize_explicit_target_hw_ids(value: Any) -> Optional[List[str]]:
    """Validate an ordered, explicit hardware-ID target set.

    ``None`` remains useful while a non-executable draft is gathering missing
    arguments. Executable submit requests add their own rule requiring either
    this non-empty set or the explicit whole-fleet scope.
    """

    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("target_drone_ids must be a JSON array of hardware ID strings")
    if not value:
        raise ValueError("target_drone_ids must contain at least one hardware ID")

    normalized: List[str] = []
    for target_id in value:
        if type(target_id) is not str:
            raise ValueError("target_drone_ids entries must be hardware ID strings")
        if not target_id or target_id != target_id.strip():
            raise ValueError(
                "target_drone_ids entries must be non-blank canonical hardware ID strings"
            )
        normalized.append(target_id)

    if len(set(normalized)) != len(normalized):
        raise ValueError("target_drone_ids must not contain duplicate hardware IDs")
    return normalized


class SubmitCommandRequest(CommandPayloadRequest):
    """Canonical public GCS command-submit payload.

    Target selection is deliberately explicit: callers either provide one or
    more hardware IDs or opt in to the whole fleet with ``target_scope=all``.
    An omitted or empty target can therefore never broaden into a fleet-wide
    command by accident.
    """

    idempotency_key: Optional[str] = Field(
        None,
        min_length=1,
        max_length=200,
        description="Client-supplied replay key used to make command submission idempotent across retries",
    )
    operator_label: Optional[str] = Field(
        None,
        description="Short operator-facing label for dashboard feedback and audit trails",
    )
    target_drone_ids: Optional[List[str]] = Field(
        None,
        description="One or more explicit target hardware IDs",
    )
    target_scope: Optional[Literal["all"]] = Field(
        None,
        description="Explicit opt-in to target every configured drone",
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_legacy_submit_envelope(cls, value: Any) -> Any:
        """Keep compatibility spellings out of the executable public boundary."""
        if not isinstance(value, dict):
            return value

        unsupported = sorted(
            key
            for key in (
                "missionType",
                "triggerTime",
                "command_id",
                "commandId",
                "target_drones",
                "targetDrones",
                "targetScope",
                "idempotencyKey",
                "client_command_id",
                "clientCommandId",
                "operatorLabel",
            )
            if key in value
        )
        if unsupported:
            raise ValueError(
                "Unsupported command-submit field(s): "
                + ", ".join(unsupported)
                + ". Use the canonical snake_case contract."
            )
        return value

    @field_validator("target_drone_ids", mode="before")
    @classmethod
    def _normalize_target_drones(cls, value: Any) -> Optional[List[str]]:
        return normalize_explicit_target_hw_ids(value)

    @model_validator(mode="after")
    def _validate_target_selection(self) -> "SubmitCommandRequest":
        if self.target_drone_ids is not None and self.target_scope is not None:
            raise ValueError("Use target_drone_ids or target_scope, not both")
        if self.target_drone_ids is None and self.target_scope != "all":
            raise ValueError(
                "Command target is required; use target_scope='all' for the whole fleet"
            )
        return self

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
        payload.pop("target_scope", None)
        payload.pop("operator_label", None)
        if command_id is not None:
            payload["command_id"] = command_id
        return payload
