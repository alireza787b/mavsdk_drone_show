import asyncio
import contextlib
import logging
import math
import time
import uuid
from collections import deque

from mavsdk.action import ActionError

from src.action_safety import (
    SAFETY_EVIDENCE_VALIDITY_MS,
    SafetyFieldEvidence,
    SafetySnapshot,
    SafetyStreamSpec,
    observe_safety_snapshot,
)
from src.params import Params


_DEFAULT_LAUNCH_BATTERY_MIN_REMAINING_PERCENT = 30.0
_STATUS_TEXT_MAX_ITEMS = 8
_STATUS_TEXT_MAX_CHARS = 240
_STATUS_TEXT_PRE_DENIAL_MS = 2_000
_STATUS_TEXT_POST_DENIAL_SEC = 0.25


class LaunchPreflightError(RuntimeError):
    """Typed mission-startup failure with bounded, time-correlated evidence."""

    def __init__(self, *, observation: dict | None, evidence: list[dict] | None = None):
        self.code = "ARM_COMMAND_DENIED"
        self.phase = "arming"
        self.observation = dict(observation or {})
        self.evidence = [dict(item) for item in (evidence or [])]

        message = "PX4 denied the arm command during mission startup."
        if self.evidence:
            evidence_summary = " | ".join(
                f"{item['severity']}: {item['text']}" for item in self.evidence[-3:]
            )
            message += f" Correlated PX4 status text: {evidence_summary}."
        else:
            message += " No correlated PX4 status text was captured."
        message += " The specific failing PX4 health item is unknown."
        super().__init__(message)


class LaunchReadinessError(TimeoutError):
    """Typed pre-arm readiness failure that preserves the sampled evidence."""

    def __init__(self, result: dict):
        self.phase = "preflight"
        self.observation = dict(result.get("observation") or {})
        self.battery = dict(result.get("battery") or {})
        self.blockers = list(result.get("blockers") or [])
        self.timed_out = bool(result.get("timed_out", False))

        battery = self.battery
        if not battery.get("sample_received") or battery.get("remaining_percent") is None:
            self.code = "BATTERY_TELEMETRY_UNAVAILABLE"
        elif not battery.get("fresh"):
            self.code = "BATTERY_TELEMETRY_STALE"
        elif not battery.get("reserve_ok"):
            self.code = "BATTERY_RESERVE_LOW"
        else:
            self.code = "PX4_HEALTH_NOT_READY"

        summary = str(result.get("summary") or "launch readiness unavailable")
        if self.code == "PX4_HEALTH_NOT_READY" and self.timed_out:
            message = f"Timed out waiting for MAVSDK pre-arm health to become ready. Last health state: {summary}"
        else:
            message = f"Launch readiness blocked: {summary}"
        super().__init__(message)


def _wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _finite_float(value) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _launch_battery_minimum_percent(logger: logging.Logger) -> float:
    configured = _finite_float(
        getattr(
            Params,
            "LAUNCH_BATTERY_MIN_REMAINING_PERCENT",
            _DEFAULT_LAUNCH_BATTERY_MIN_REMAINING_PERCENT,
        )
    )
    if configured is None or not 0.0 <= configured <= 100.0:
        logger.warning(
            "Invalid launch battery reserve threshold %r; using %.1f%%.",
            configured,
            _DEFAULT_LAUNCH_BATTERY_MIN_REMAINING_PERCENT,
        )
        return _DEFAULT_LAUNCH_BATTERY_MIN_REMAINING_PERCENT
    return configured


def _normalize_remaining_percent(value) -> float | None:
    """Validate MAVSDK Telemetry.Battery percentage points at the SDK boundary.

    MAVSDK 3.x documents and emits ``remaining_percent`` in the 0..100 range.
    This boundary is intentionally strict: values outside that range are
    malformed and fraction-looking values are not guessed or rescaled. Internal
    policy and operator evidence use the same 0..100 percentage-point unit.
    """
    remaining_percent = _finite_float(value)
    if remaining_percent is None or not 0.0 <= remaining_percent <= 100.0:
        return None
    return remaining_percent


def _battery_from_evidence(
    evidence: SafetyFieldEvidence | None,
    *,
    minimum_percent: float,
) -> dict:
    """Normalize one typed safety field at the MAVSDK battery boundary."""

    sample = evidence.value if evidence is not None else None
    sample_received = sample is not None
    remaining_percent = _normalize_remaining_percent(
        getattr(sample, "remaining_percent", None) if sample_received else None
    )
    voltage_v = _finite_float(
        getattr(sample, "voltage_v", None) if sample_received else None
    )
    if voltage_v is not None and voltage_v <= 0.0:
        voltage_v = None
    fresh = bool(evidence is not None and evidence.usable)
    reserve_ok = bool(
        remaining_percent is not None and remaining_percent >= minimum_percent
    )

    blockers: list[str] = []
    if not sample_received:
        blockers.append("battery telemetry unavailable")
    elif remaining_percent is None:
        blockers.append("battery remaining estimate unavailable")
    elif not fresh:
        blockers.append("battery telemetry stale or connection continuity unknown")
    elif not reserve_ok:
        blockers.append(
            f"battery reserve {remaining_percent:.1f}% below minimum {minimum_percent:.1f}%"
        )

    received_at_ms = int(evidence.received_at_ms or 0) if evidence is not None else 0
    return {
        "source": "mavsdk.telemetry.battery",
        "sample_received": sample_received,
        "observed_at_ms": received_at_ms,
        "valid_until_ms": (
            received_at_ms + SAFETY_EVIDENCE_VALIDITY_MS if fresh else 0
        ),
        "age_ms": evidence.receipt_age_ms if evidence is not None else None,
        "source_age_ms": evidence.source_age_ms if evidence is not None else None,
        "source_freshness": (
            evidence.source_freshness.value if evidence is not None else "unknown"
        ),
        "fresh": fresh,
        "voltage_v": voltage_v,
        "remaining_percent": remaining_percent,
        "minimum_remaining_percent": minimum_percent,
        "reserve_ok": reserve_ok,
        "ready": bool(sample_received and remaining_percent is not None and fresh and reserve_ok),
        "blockers": blockers,
        "error": evidence.error if evidence is not None else "battery field unavailable",
        "evidence": evidence.as_dict(include_value=False) if evidence is not None else None,
    }


def _readiness_from_snapshot(
    snapshot: SafetySnapshot,
    *,
    require_global_position: bool,
    minimum_battery_percent: float,
    timed_out: bool,
    elapsed_sec: float,
) -> dict:
    """Build the existing live-armability envelope from the safety SSOT."""

    health_evidence = snapshot.fields.get("health")
    battery_evidence = snapshot.fields.get("battery")
    health_sample = health_evidence.value if health_evidence is not None else None
    health_sample_received = health_sample is not None
    if health_sample_received:
        health_state = summarize_offboard_health(
            health_sample,
            require_global_position=require_global_position,
        )
    else:
        health_state = {
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
        }

    health_fresh = bool(health_evidence is not None and health_evidence.usable)
    health_ready = bool(health_state["ready"] and health_fresh)
    health_blockers = list(health_state["blockers"])
    if health_sample_received and not health_fresh:
        health_blockers.append("health telemetry stale or connection continuity unknown")

    battery = _battery_from_evidence(
        battery_evidence,
        minimum_percent=minimum_battery_percent,
    )
    blockers: list[str] = []
    if snapshot.connection_live is not True:
        blockers.append("vehicle connection")
    elif snapshot.connection_interrupted:
        blockers.append("vehicle connection changed during readiness sampling")
    elif not snapshot.connection.usable:
        blockers.append("vehicle connection evidence stale or unknown")
    if snapshot.source_boot_reset:
        blockers.append("autopilot restarted during readiness sampling")
    blockers.extend(health_blockers)
    blockers.extend(battery["blockers"])
    blockers = list(dict.fromkeys(blockers))

    combined_ready = bool(snapshot.complete and health_ready and battery["ready"])
    if combined_ready:
        voltage_label = (
            f", {battery['voltage_v']:.2f} V"
            if battery["voltage_v"] is not None
            else ""
        )
        summary = (
            "ready for mission startup "
            f"(battery {battery['remaining_percent']:.1f}%{voltage_label}; "
            f"minimum {battery['minimum_remaining_percent']:.1f}%)"
        )
    else:
        summary = "waiting for " + ", ".join(blockers or ["launch readiness evidence"])

    validity_candidates = [
        int(field.received_at_ms or 0) + SAFETY_EVIDENCE_VALIDITY_MS
        for field in (snapshot.connection, health_evidence, battery_evidence)
        if field is not None and field.usable and field.received_at_ms
    ]
    valid_until_ms = min(validity_candidates) if len(validity_candidates) == 3 else 0
    checks = {
        "connection_live": snapshot.connection_live is True,
        "connection_fresh": snapshot.connection.usable,
        "connection_continuous": not snapshot.connection_interrupted,
        "source_boot_stable": not snapshot.source_boot_reset,
        "health_sample_received": health_sample_received,
        "health_fresh": health_fresh,
        "armable": bool(health_state.get("armable", False)),
        "global_position_ok": bool(health_state.get("global_position_ok", False)),
        "home_position_ok": bool(health_state.get("home_position_ok", False)),
        "local_position_ok": bool(health_state.get("local_position_ok", False)),
        "gyro_ok": bool(health_state.get("gyro_ok", False)),
        "accel_ok": bool(health_state.get("accel_ok", False)),
        "mag_ok": bool(health_state.get("mag_ok", False)),
        "battery_sample_received": bool(battery.get("sample_received", False)),
        "battery_remaining_available": battery.get("remaining_percent") is not None,
        "battery_fresh": bool(battery.get("fresh", False)),
        "battery_reserve_ok": bool(battery.get("reserve_ok", False)),
    }
    observation = {
        "schema_version": 1,
        "observation_id": f"safety-{snapshot.observed_at_ms}-{uuid.uuid4().hex}",
        "source": "mavsdk.connected_safety_snapshot",
        "observed_at_ms": snapshot.observed_at_ms,
        "valid_until_ms": valid_until_ms,
        "require_global_position": require_global_position,
        "ready": combined_ready,
        "blockers": blockers,
        "checks": checks,
        "battery": dict(battery),
        "safety_snapshot": snapshot.as_dict(),
    }
    return {
        **health_state,
        "timed_out": timed_out,
        "elapsed_sec": elapsed_sec,
        "require_global_position": require_global_position,
        "health_ready": health_ready,
        "health_age_ms": (
            health_evidence.receipt_age_ms if health_evidence is not None else None
        ),
        "ready": combined_ready,
        "summary": summary,
        "blockers": blockers,
        "battery": dict(battery),
        "observation": observation,
    }


def _sanitize_status_text(value, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "\u2026"


def _status_text_evidence(status_text) -> dict | None:
    text = _sanitize_status_text(getattr(status_text, "text", ""), limit=_STATUS_TEXT_MAX_CHARS)
    if not text:
        return None

    raw_severity = getattr(status_text, "type", "UNKNOWN")
    severity = _sanitize_status_text(
        getattr(raw_severity, "name", raw_severity),
        limit=32,
    ).upper() or "UNKNOWN"
    return {
        "observed_at_ms": _wall_clock_ms(),
        "severity": severity,
        "text": text,
    }


async def _capture_status_text(drone, evidence_ring: deque, logger: logging.Logger) -> None:
    """Best-effort per-launch capture; evidence never participates in readiness."""
    try:
        async for status_text in drone.telemetry.status_text():
            evidence = _status_text_evidence(status_text)
            if evidence is not None:
                evidence_ring.append(evidence)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("Mission startup status-text capture unavailable: %s", exc)


def _is_command_denied(exc: Exception) -> bool:
    result = getattr(getattr(exc, "_result", None), "result", None)
    result_name = getattr(result, "name", result)
    return "denied" in f"{result_name or ''} {exc}".lower()


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
    Sample connection-bound MAVSDK health and battery evidence until launch
    readiness is proven or the shared wait budget expires.

    Used by both mission startup and operator-facing launch probes so both paths
    share the same armability definition.
    """
    logger = logger or logging.getLogger(__name__)
    wait_timeout = float(timeout or getattr(Params, "OFFBOARD_ARM_HEALTH_TIMEOUT_SEC", 15.0))
    sample_timeout = float(getattr(Params, "OFFBOARD_ARM_HEALTH_POLL_SEC", 0.5))
    stable_samples = max(1, int(getattr(Params, "OFFBOARD_ARM_HEALTH_STABLE_SAMPLES", 1)))
    minimum_battery_percent = _launch_battery_minimum_percent(logger)

    deadline = time.monotonic() + wait_timeout
    consecutive_ready = 0
    last_summary = None
    last_result = None
    field_specs = {
        "health": SafetyStreamSpec(
            source="mavsdk.telemetry.health",
            stream_factory=drone.telemetry.health,
        ),
        "battery": SafetyStreamSpec(
            source="mavsdk.telemetry.battery",
            stream_factory=drone.telemetry.battery,
        ),
    }

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if last_result is not None:
                result = dict(last_result)
                result["timed_out"] = True
                result["elapsed_sec"] = wait_timeout
                return result
            # A positive wait budget always enters the loop once, but retain a
            # deterministic fail-closed result for defensive callers.
            snapshot = SafetySnapshot.from_values(
                armed=None,
                landed_state=None,
                relative_altitude_m=None,
                connection_live=None,
            )
            snapshot = SafetySnapshot(
                observed_at_ms=snapshot.observed_at_ms,
                connection=snapshot.connection,
                fields={},
                required_fields=("health", "battery"),
                observation_error="launch-readiness deadline expired before sampling",
            )
            return _readiness_from_snapshot(
                snapshot,
                require_global_position=require_global_position,
                minimum_battery_percent=minimum_battery_percent,
                timed_out=True,
                elapsed_sec=wait_timeout,
            )

        snapshot = await observe_safety_snapshot(
            drone,
            field_specs=field_specs,
            timeout=min(max(0.001, sample_timeout), remaining),
        )
        elapsed_sec = wait_timeout - max(0.0, deadline - time.monotonic())
        result = _readiness_from_snapshot(
            snapshot,
            require_global_position=require_global_position,
            minimum_battery_percent=minimum_battery_percent,
            timed_out=False,
            elapsed_sec=elapsed_sec,
        )
        last_result = result

        if result["summary"] != last_summary:
            logger.info(
                "Mission startup launch readiness: %s (connected=%s, armable=%s, "
                "battery_remaining=%s%%, battery_source_age=%sms).",
                result["summary"],
                snapshot.connection_live,
                result["armable"],
                (
                    f"{result['battery']['remaining_percent']:.1f}"
                    if result["battery"].get("remaining_percent") is not None
                    else "unavailable"
                ),
                result["battery"].get("source_age_ms"),
            )
            last_summary = result["summary"]

        if result["ready"]:
            consecutive_ready += 1
            if consecutive_ready >= stable_samples:
                return result
        else:
            consecutive_ready = 0
            if (
                result["health_ready"]
                and snapshot.connection_live is True
                and not snapshot.connection_interrupted
                and result["battery"].get("sample_received")
            ):
                # A current low/invalid battery estimate is an actionable
                # blocker, not a condition improved by replaying the same
                # observation until the full health timeout.
                return result

        # A disconnected current-state sample can return immediately. Avoid a
        # hot retry loop while preserving the shared monotonic deadline.
        remaining = deadline - time.monotonic()
        if remaining > 0 and snapshot.connection_live is not True:
            await asyncio.sleep(min(sample_timeout, remaining))


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
        raise LaunchReadinessError(result)

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
    arm_action_timeout = max(1.0, float(getattr(Params, "OFFBOARD_ARM_ACTION_TIMEOUT_SEC", 15.0)))

    status_text_ring = deque(maxlen=_STATUS_TEXT_MAX_ITEMS)
    denial_evidence = deque(maxlen=_STATUS_TEXT_MAX_ITEMS)
    status_text_task = asyncio.create_task(_capture_status_text(drone, status_text_ring, logger))
    last_error = None
    try:
        for attempt in range(1, max_attempts + 1):
            health_result = await wait_until_offboard_armable(
                drone,
                require_global_position=require_global_position,
                logger=logger,
            )
            observation = health_result.get("observation", {}) if isinstance(health_result, dict) else {}
            attempt_started_ms = _wall_clock_ms()
            try:
                logger.info("Arming the drone (attempt %d/%d).", attempt, max_attempts)
                await asyncio.wait_for(drone.action.arm(), timeout=arm_action_timeout)
                return
            except asyncio.TimeoutError as exc:
                last_error = exc
                logger.warning(
                    "Arm attempt %d/%d timed out after %.1fs.",
                    attempt,
                    max_attempts,
                    arm_action_timeout,
                )
                if attempt >= max_attempts:
                    raise TimeoutError(
                        f"Arm command timed out after {arm_action_timeout:.1f}s."
                    ) from exc
                await asyncio.sleep(retry_delay)
            except ActionError as exc:
                last_error = exc
                message = str(exc)
                denied = _is_command_denied(exc)
                denied_at_ms = _wall_clock_ms()
                logger.warning("Arm attempt %d/%d failed: %s", attempt, max_attempts, message)
                if not denied:
                    raise

                # PX4 STATUSTEXT commonly follows the command acknowledgement by a
                # few milliseconds. Give that diagnostic stream a small bounded
                # grace period, then retain only evidence near this arm attempt.
                await asyncio.sleep(_STATUS_TEXT_POST_DENIAL_SEC)
                window_start_ms = attempt_started_ms - _STATUS_TEXT_PRE_DENIAL_MS
                window_end_ms = denied_at_ms + int(_STATUS_TEXT_POST_DENIAL_SEC * 1_000) + 100
                for item in status_text_ring:
                    if window_start_ms <= item["observed_at_ms"] <= window_end_ms:
                        if item not in denial_evidence:
                            denial_evidence.append(dict(item))

                if attempt >= max_attempts:
                    raise LaunchPreflightError(
                        observation=observation,
                        evidence=list(denial_evidence),
                    ) from exc
                await asyncio.sleep(retry_delay)

        if last_error:
            raise last_error
    finally:
        status_text_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await status_text_task
