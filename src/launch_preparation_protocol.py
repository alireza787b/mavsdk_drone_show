"""Typed command-bound launch prepare/commit protocol.

The node issues an opaque, one-use token only after a live armability probe.
The token is bound to the exact command and target plus a canonical digest of
every immutable payload field.  Expiry is measured exclusively with the
issuing node's monotonic clock, so no GCS/node wall-clock synchronization is
required.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, Mapping, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from src.command_contract import DroneCommandRequest
from src.command_execution_contract import (
    mission_requires_launch_armability_probe,
    mission_requires_strict_sync_dispatch,
)
from src.live_armability_contract import LaunchReadinessObservation
from src.drone_api_routes import DRONE_LAUNCH_PREPARATION_ROUTE


LAUNCH_PREPARATION_TOKEN_HEADER = "X-MDS-Launch-Preparation"
LAUNCH_PREPARATION_SCHEMA_VERSION = 1


def _canonical_nonblank(value: Any, *, field_name: str, max_length: int) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a canonical non-blank string")
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds {max_length} characters")
    return value


def canonical_node_command(command: DroneCommandRequest | Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical snake-case command representation used for binding."""

    parsed = (
        command
        if isinstance(command, DroneCommandRequest)
        else DroneCommandRequest.model_validate(command)
    )
    payload = parsed.model_dump(mode="json", exclude_none=True)
    # Round-trip through the canonical JSON encoder now.  This rejects NaN and
    # other values that could otherwise fingerprint differently at dispatch.
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return json.loads(encoded)


def immutable_command_payload_sha256(
    command: DroneCommandRequest | Mapping[str, Any],
) -> str:
    """Digest every canonical command field except the governed trigger slot.

    ``trigger_time`` is excluded because strict-sync commands requested with
    zero receive one shared future trigger only after every target prepares.
    The token record separately enforces the only permitted transition.
    """

    canonical = canonical_node_command(command)
    canonical.pop("trigger_time", None)
    encoded = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class LaunchPreparationRequest(BaseModel):
    """Exact per-node command proposed for launch preparation."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = LAUNCH_PREPARATION_SCHEMA_VERSION
    command: DroneCommandRequest
    require_global_position: StrictBool = True

    @field_validator("command", mode="before")
    @classmethod
    def _require_canonical_command_keys(cls, value: Any) -> Any:
        if type(value) is not dict:
            raise ValueError("command must be a JSON object")
        canonical_fields = set(DroneCommandRequest.model_fields)
        noncanonical = sorted(set(value) - canonical_fields)
        if noncanonical:
            raise ValueError(
                "launch preparation accepts canonical command fields only; "
                f"unexpected field(s): {', '.join(noncanonical)}"
            )
        return value

    @model_validator(mode="after")
    def _validate_binding(self) -> "LaunchPreparationRequest":
        command = self.command
        if not mission_requires_launch_armability_probe(command.mission_type):
            raise ValueError("only launch-armability missions may be prepared")
        _canonical_nonblank(command.command_id, field_name="command_id", max_length=200)
        _canonical_nonblank(command.target_hw_id, field_name="target_hw_id", max_length=64)
        _canonical_nonblank(
            command.command_report_capability,
            field_name="command_report_capability",
            max_length=200,
        )
        return self


class LaunchPreparationResponse(BaseModel):
    """Strict node result; the token is present only for ``prepared`` status."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = LAUNCH_PREPARATION_SCHEMA_VERSION
    status: Literal["prepared", "rejected"]
    command_id: StrictStr = Field(..., min_length=1, max_length=200)
    target_hw_id: StrictStr = Field(..., min_length=1, max_length=64)
    mission_type: StrictInt
    immutable_payload_sha256: StrictStr = Field(
        ...,
        pattern=r"^[0-9a-f]{64}$",
    )
    ready: StrictBool
    summary: StrictStr = Field(..., min_length=1, max_length=500)
    observation: Optional[LaunchReadinessObservation] = None
    preparation_token: Optional[StrictStr] = Field(
        None,
        min_length=43,
        max_length=200,
        repr=False,
    )
    token_ttl_ms: StrictInt = Field(..., ge=0)
    server_processing_ms: StrictInt = Field(..., ge=0)
    error_code: Optional[StrictStr] = Field(None, max_length=64)
    error_detail: Optional[StrictStr] = Field(None, max_length=500)

    @field_validator("command_id", "target_hw_id", "summary")
    @classmethod
    def _canonical_text(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("trust-bearing text fields must not have surrounding whitespace")
        return value

    @model_validator(mode="after")
    def _validate_status(self) -> "LaunchPreparationResponse":
        if self.status == "prepared":
            if not self.ready or self.observation is None or not self.observation.ready:
                raise ValueError("prepared status requires a ready observation")
            if self.preparation_token is None or self.token_ttl_ms <= 0:
                raise ValueError("prepared status requires a positive one-use token lease")
            if self.error_code is not None or self.error_detail is not None:
                raise ValueError("prepared status cannot carry rejection fields")
        else:
            if self.ready or self.preparation_token is not None or self.token_ttl_ms != 0:
                raise ValueError("rejected status cannot carry launch authority")
        return self


@dataclass(frozen=True)
class LaunchPreparationBinding:
    command_id: str
    target_hw_id: str
    mission_type: int
    immutable_payload_sha256: str
    requested_trigger_time: int
    allow_post_barrier_trigger: bool

    @classmethod
    def from_command(
        cls,
        command: DroneCommandRequest | Mapping[str, Any],
    ) -> "LaunchPreparationBinding":
        canonical = canonical_node_command(command)
        command_id = _canonical_nonblank(
            canonical.get("command_id"), field_name="command_id", max_length=200
        )
        target_hw_id = _canonical_nonblank(
            canonical.get("target_hw_id"), field_name="target_hw_id", max_length=64
        )
        mission_type = canonical.get("mission_type")
        trigger_time = canonical.get("trigger_time", 0)
        if type(mission_type) is not int:
            raise ValueError("mission_type must be an integer")
        if not mission_requires_launch_armability_probe(mission_type):
            raise ValueError("mission does not use launch preparation")
        if type(trigger_time) is not int or trigger_time < 0:
            raise ValueError("trigger_time must be a non-negative integer")
        return cls(
            command_id=command_id,
            target_hw_id=target_hw_id,
            mission_type=mission_type,
            immutable_payload_sha256=immutable_command_payload_sha256(canonical),
            requested_trigger_time=trigger_time,
            allow_post_barrier_trigger=(
                trigger_time == 0
                and mission_requires_strict_sync_dispatch(mission_type)
            ),
        )


class LaunchPreparationConsumeStatus(str, Enum):
    CONSUMED = "consumed"
    MISSING = "missing"
    EXPIRED = "expired"
    REPLAYED = "replayed"
    MISMATCH = "mismatch"


@dataclass(frozen=True)
class LaunchPreparationConsumeResult:
    status: LaunchPreparationConsumeStatus
    detail: str

    @property
    def consumed(self) -> bool:
        return self.status is LaunchPreparationConsumeStatus.CONSUMED


@dataclass(frozen=True)
class _StoredPreparation:
    binding: LaunchPreparationBinding
    expires_at_monotonic: float
    latest_post_barrier_trigger_time: float


def calculate_launch_preparation_token_ttl_sec(*, params: Any) -> float:
    """Derive a conservative lease from the existing bounded fleet budgets."""

    def bounded_seconds(name: str, *, default: float, minimum: float) -> float:
        raw = getattr(params, name, default)
        # Runtime settings are normalized before service construction. Refuse
        # booleans, strings, Mock objects, NaN, and infinities here instead of
        # granting a surprising long-lived token from arbitrary coercion.
        if type(raw) not in {int, float}:
            return default
        parsed = float(raw)
        if not math.isfinite(parsed):
            return default
        return max(minimum, parsed)

    prepare = bounded_seconds(
        "GCS_FLEET_PREPARE_DEADLINE_SEC",
        default=30.0,
        minimum=1.0,
    )
    dispatch = bounded_seconds(
        "GCS_FLEET_DISPATCH_DEADLINE_SEC",
        default=15.0,
        minimum=1.0,
    )
    request = bounded_seconds(
        "GCS_COMMAND_HTTP_TIMEOUT_SEC",
        default=5.0,
        minimum=0.2,
    )
    # The first node prepared must survive the rest of the barrier and the
    # complete bounded commit fan-out.  A second prepare budget provides room
    # for realistic scheduler/transport variance without creating a long-lived
    # authority token.
    return max(60.0, (2.0 * prepare) + dispatch + request + 10.0)


class LaunchPreparationStore:
    """Thread-safe, bounded, one-use preparation tokens for one node process."""

    def __init__(
        self,
        *,
        ttl_sec: float,
        max_records: int = 256,
        monotonic: Any = time.monotonic,
        wall_clock: Any = time.time,
        minimum_post_barrier_lead_sec: float = 0.0,
    ) -> None:
        if type(ttl_sec) not in {int, float} or not math.isfinite(float(ttl_sec)):
            raise ValueError("ttl_sec must be a finite number")
        if float(ttl_sec) < 1.0:
            raise ValueError("ttl_sec must be at least one second")
        if type(max_records) is not int or max_records < 1:
            raise ValueError("max_records must be a positive integer")
        if (
            type(minimum_post_barrier_lead_sec) not in {int, float}
            or not math.isfinite(float(minimum_post_barrier_lead_sec))
            or float(minimum_post_barrier_lead_sec) < 0.0
        ):
            raise ValueError(
                "minimum_post_barrier_lead_sec must be a finite non-negative number"
            )
        if not callable(monotonic) or not callable(wall_clock):
            raise ValueError("launch preparation clocks must be callable")

        self._ttl_sec = float(ttl_sec)
        self._max_records = max_records
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self._minimum_post_barrier_lead_sec = float(
            minimum_post_barrier_lead_sec
        )
        self._lock = threading.Lock()
        self._active: OrderedDict[str, _StoredPreparation] = OrderedDict()
        self._consumed: OrderedDict[str, float] = OrderedDict()

    @staticmethod
    def _token_digest(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _prune_locked(self, now: float) -> None:
        for digest, record in tuple(self._active.items()):
            if now >= record.expires_at_monotonic:
                self._active.pop(digest, None)
        for digest, expires_at in tuple(self._consumed.items()):
            if now >= expires_at:
                self._consumed.pop(digest, None)
        while len(self._consumed) > self._max_records:
            # A forgotten replay marker still fails closed as ``missing``;
            # bounding this history is more important than retaining its more
            # specific diagnostic under sustained malformed/replayed traffic.
            self._consumed.popitem(last=False)

    def issue(self, binding: LaunchPreparationBinding) -> tuple[str, int]:
        now = float(self._monotonic())
        wall_now = float(self._wall_clock())
        expires_at = now + self._ttl_sec
        with self._lock:
            self._prune_locked(now)
            if len(self._active) >= self._max_records:
                raise RuntimeError("launch preparation token store is at capacity")
            while True:
                token = secrets.token_urlsafe(32)
                digest = self._token_digest(token)
                if digest not in self._active and digest not in self._consumed:
                    break
            self._active[digest] = _StoredPreparation(
                binding=binding,
                expires_at_monotonic=expires_at,
                # A zero-trigger strict-sync preparation authorizes the GCS to
                # choose one post-barrier trigger, not an arbitrary future
                # schedule. Bound that choice to the same short lease as the
                # preparation authority.
                latest_post_barrier_trigger_time=wall_now + self._ttl_sec,
            )
        return token, max(1, int(self._ttl_sec * 1_000))

    def consume(
        self,
        token: Any,
        command: DroneCommandRequest | Mapping[str, Any],
    ) -> LaunchPreparationConsumeResult:
        if (
            type(token) is not str
            or not token
            or token != token.strip()
            or len(token) > 200
        ):
            return LaunchPreparationConsumeResult(
                LaunchPreparationConsumeStatus.MISSING,
                "A canonical launch preparation token is required",
            )

        digest = self._token_digest(token)
        now = float(self._monotonic())
        with self._lock:
            # Inspect the addressed record before generic pruning so an exact
            # expired token remains distinguishable from an unknown token.
            record = self._active.pop(digest, None)
            if record is None:
                replay_expiry = self._consumed.get(digest)
                self._prune_locked(now)
                if replay_expiry is not None and now < replay_expiry:
                    return LaunchPreparationConsumeResult(
                        LaunchPreparationConsumeStatus.REPLAYED,
                        "The launch preparation token was already consumed",
                    )
                return LaunchPreparationConsumeResult(
                    LaunchPreparationConsumeStatus.MISSING,
                    "The launch preparation token is unknown to this node process",
                )
            # Every addressed attempt consumes the token atomically, including
            # an expired or mismatched commit. A corrected commit must prepare
            # again and can never reuse stale authority.
            self._consumed[digest] = record.expires_at_monotonic
            self._prune_locked(now)

        if now >= record.expires_at_monotonic:
            return LaunchPreparationConsumeResult(
                LaunchPreparationConsumeStatus.EXPIRED,
                "The launch preparation token expired before commit",
            )
        try:
            requested = LaunchPreparationBinding.from_command(command)
        except (TypeError, ValueError) as exc:
            return LaunchPreparationConsumeResult(
                LaunchPreparationConsumeStatus.MISMATCH,
                f"The committed command is not a valid prepared launch: {exc}",
            )

        expected = record.binding
        immutable_match = hmac.compare_digest(
            expected.immutable_payload_sha256,
            requested.immutable_payload_sha256,
        )
        identity_match = (
            expected.command_id == requested.command_id
            and expected.target_hw_id == requested.target_hw_id
            and expected.mission_type == requested.mission_type
            and immutable_match
        )
        trigger_match = requested.requested_trigger_time == expected.requested_trigger_time
        if (
            expected.allow_post_barrier_trigger
            and expected.requested_trigger_time == 0
            and requested.requested_trigger_time > 0
        ):
            trigger_match = True

        if not identity_match or not trigger_match:
            return LaunchPreparationConsumeResult(
                LaunchPreparationConsumeStatus.MISMATCH,
                "The launch commit does not match the command, target, payload, or governed trigger prepared by this token",
            )
        if (
            mission_requires_strict_sync_dispatch(expected.mission_type)
            and requested.requested_trigger_time > 0
            and requested.requested_trigger_time
            <= float(self._wall_clock()) + self._minimum_post_barrier_lead_sec
        ):
            return LaunchPreparationConsumeResult(
                LaunchPreparationConsumeStatus.MISMATCH,
                "The synchronized launch trigger is no longer safely in the future for this node",
            )
        if (
            expected.allow_post_barrier_trigger
            and requested.requested_trigger_time
            > record.latest_post_barrier_trigger_time
        ):
            return LaunchPreparationConsumeResult(
                LaunchPreparationConsumeStatus.MISMATCH,
                "The synchronized launch trigger is outside this preparation lease",
            )
        return LaunchPreparationConsumeResult(
            LaunchPreparationConsumeStatus.CONSUMED,
            "Launch preparation token consumed",
        )


__all__ = [
    "DRONE_LAUNCH_PREPARATION_ROUTE",
    "LAUNCH_PREPARATION_SCHEMA_VERSION",
    "LAUNCH_PREPARATION_TOKEN_HEADER",
    "LaunchPreparationBinding",
    "LaunchPreparationConsumeResult",
    "LaunchPreparationConsumeStatus",
    "LaunchPreparationRequest",
    "LaunchPreparationResponse",
    "LaunchPreparationStore",
    "calculate_launch_preparation_token_ttl_sec",
    "canonical_node_command",
    "immutable_command_payload_sha256",
]
