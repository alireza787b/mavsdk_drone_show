import json
import os

import pytest

from src.action_result_protocol import (
    ACTION_RESULT_SENTINEL,
    COMPACTION_MARKER_KEY,
    MAX_RESULT_BYTES,
    MAX_MAPPING_ITEMS,
    ActionResultProtocolError,
    decode_terminal_result,
    emit_terminal_result,
    encode_terminal_result,
    extract_terminal_result,
    format_legacy_diagnostics,
    make_terminal_result,
    read_bounded_result_fd,
)


def _failure_result():
    return make_terminal_result(
        success=False,
        code="PX4_COMMAND_DENIED",
        phase="vehicle_command",
        operator_message="PX4 rejected arm: Resolve system health failures first.",
        retryable=False,
        evidence={"action": "test", "mavsdk_result": "COMMAND_DENIED"},
        final_vehicle_state={"armed": False},
    )


@pytest.mark.parametrize("success", [False, True])
def test_safety_facts_appended_after_mapping_cap_survive_initial_sanitization(success):
    safety_facts = {
        "armed": True, "landed_state": "IN_AIR", "relative_altitude_m": -10.0,
        "recovery_action": None if success else "land",
        "recovery_status": "not_required" if success else "land_recovery_unconfirmed",
        "complete": True, "fresh": True, "connection_live": True, "field_errors": {},
        "target_altitude_m": 10.0, "minimum_confirmed_altitude_m": 8.0,
        "absolute_altitude_m": 110.0, "baseline_absolute_altitude_m": 100.0,
        "observed_climb_m": 10.0, "flight_mode": "HOLD", "outcome": "held",
    }
    state = {f"diagnostic_{index}": "optional" for index in range(MAX_MAPPING_ITEMS + 4)}
    state.update(safety_facts)
    result = make_terminal_result(success=success, code="ACTION_COMPLETED" if success else "ACTION_EXECUTION_FAILED",
        phase="completed" if success else "execution", operator_message="Terminal safety facts retained.",
        final_vehicle_state=state)

    assert len(result.final_vehicle_state) <= MAX_MAPPING_ITEMS
    assert result.final_vehicle_state == safety_facts
    payload = encode_terminal_result(result)
    assert len(payload) <= MAX_RESULT_BYTES
    parsed = decode_terminal_result(payload)
    assert parsed.final_vehicle_state == safety_facts


def _verbose_vehicle_state(*, landed_state="LANDING", relative_altitude_m=8.0):
    def field(source, value):
        return {
            "source": source,
            "received_at_ms": 1_785_733_383_634,
            "receipt_age_ms": 401,
            "source_timestamp_ms": None,
            "source_age_ms": None,
            "source_time_boot_ms": None,
            "receipt_freshness": "fresh",
            "source_freshness": "unknown",
            "freshness": "fresh",
            "error": None,
            "stale_reason": None,
            "value": value,
        }

    return {
        "schema_version": 1,
        "source": "mavsdk.telemetry",
        "observed_at_ms": 1_785_733_384_035,
        "fresh": True,
        "complete": True,
        "connection_live": True,
        "connection_interrupted": False,
        "source_boot_reset": False,
        "armed": True,
        "landed_state": landed_state,
        "relative_altitude_m": relative_altitude_m,
        "field_errors": {},
        "connection": field("mavsdk.core.connection_state", True),
        "fields": {
            "armed": field("mavsdk.telemetry.armed", True),
            "landed_state": field(
                "mavsdk.telemetry.landed_state",
                landed_state,
            ),
            "relative_altitude_m": field(
                "mavsdk.telemetry.position.relative_altitude_m",
                relative_altitude_m,
            ),
        },
        "recovery_action": "land",
        "recovery_status": "land_recovery_started",
    }


def _oversized_takeoff_failure_result():
    completion_state = _verbose_vehicle_state(
        landed_state="IN_AIR",
        relative_altitude_m=8.2,
    )
    initial_cleanup_state = _verbose_vehicle_state(
        landed_state="IN_AIR",
        relative_altitude_m=8.4,
    )
    final_state = _verbose_vehicle_state()
    return make_terminal_result(
        success=False,
        code="TAKEOFF_FINAL_STATE_UNAVAILABLE",
        phase="state_verification",
        operator_message=(
            "Takeoff reached the altitude threshold, but a connected, fresh and "
            "internally consistent final airborne snapshot was not confirmed. "
            "LAND recovery was initiated."
        ),
        retryable=False,
        evidence={
            "action": "takeoff",
            "exception_type": "ActionSafetyError",
            "evidence": {"observation": completion_state},
            "transaction": {
                "cleanup": "failed_takeoff",
                "takeoff_command_may_have_started": True,
                "initial_state": initial_cleanup_state,
                "land_command_attempted": True,
                "final_state": final_state,
                "cleanup_confirmed": True,
            },
        },
        final_vehicle_state=final_state,
    )


def test_terminal_result_round_trip_preserves_required_schema():
    result = _failure_result()

    parsed = decode_terminal_result(encode_terminal_result(result))

    assert parsed == result
    assert set(json.loads(encode_terminal_result(result))) == {
        "schema_version",
        "success",
        "code",
        "phase",
        "operator_message",
        "retryable",
        "evidence",
        "final_vehicle_state",
    }
    assert COMPACTION_MARKER_KEY not in parsed.evidence


def test_oversized_optional_detail_is_compacted_without_losing_terminal_truth():
    result = _oversized_takeoff_failure_result()

    payload = encode_terminal_result(result)
    parsed = decode_terminal_result(payload)

    assert len(payload) <= MAX_RESULT_BYTES
    assert parsed.success is False
    assert parsed.code == result.code
    assert parsed.phase == result.phase
    assert parsed.operator_message == result.operator_message
    assert parsed.retryable is False
    assert parsed.evidence[COMPACTION_MARKER_KEY]["compacted"] is True
    assert parsed.evidence[COMPACTION_MARKER_KEY]["wire_limit_bytes"] == MAX_RESULT_BYTES
    assert parsed.evidence["transaction"]["cleanup_confirmed"] is True
    assert parsed.evidence["transaction"]["land_command_attempted"] is True
    assert parsed.final_vehicle_state["armed"] is True
    assert parsed.final_vehicle_state["landed_state"] == "LANDING"
    assert parsed.final_vehicle_state["relative_altitude_m"] == pytest.approx(8.0)
    assert parsed.final_vehicle_state["recovery_action"] == "land"
    assert parsed.final_vehicle_state["recovery_status"] == "land_recovery_started"


def test_oversized_result_emits_one_decodable_dedicated_payload(monkeypatch):
    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("MDS_ACTION_RESULT_FD", str(write_fd))

    emit_terminal_result(_oversized_takeoff_failure_result())
    payload = read_bounded_result_fd(read_fd)
    parsed = decode_terminal_result(payload)

    assert len(payload) <= MAX_RESULT_BYTES
    assert parsed.code == "TAKEOFF_FINAL_STATE_UNAVAILABLE"
    assert parsed.evidence[COMPACTION_MARKER_KEY]["compacted"] is True


def test_multibyte_operator_message_is_fitted_by_actual_utf8_bytes():
    message = "🚁" * 500
    result = make_terminal_result(
        success=False,
        code="ACTION_FAILED",
        phase="execution",
        operator_message=message,
        evidence={"action": "takeoff"},
    )

    payload = encode_terminal_result(result)
    parsed = decode_terminal_result(payload)

    assert len(payload) <= MAX_RESULT_BYTES
    assert parsed.operator_message == message
    assert COMPACTION_MARKER_KEY not in parsed.evidence


def test_dedicated_result_is_preferred_over_stderr_and_compatibility_stdout():
    authoritative = _failure_result()
    misleading = make_terminal_result(
        success=False,
        code="ACTION_FAILED",
        phase="execution",
        operator_message="Misleading compatibility result.",
        retryable=False,
    )
    stdout = ACTION_RESULT_SENTINEL.encode() + encode_terminal_result(misleading)

    parsed = extract_terminal_result(
        dedicated_payload=encode_terminal_result(authoritative),
        stdout=stdout,
    )

    assert parsed == authoritative


def test_duplicate_compatibility_results_are_rejected():
    line = ACTION_RESULT_SENTINEL.encode() + encode_terminal_result(_failure_result())

    assert extract_terminal_result(dedicated_payload=None, stdout=line + line) is None


def test_oversized_and_extra_field_payloads_are_rejected():
    with pytest.raises(ActionResultProtocolError, match="oversized"):
        decode_terminal_result(b"x" * (MAX_RESULT_BYTES + 1))

    document = json.loads(encode_terminal_result(_failure_result()))
    document["unexpected"] = "field"
    with pytest.raises(ActionResultProtocolError, match="fields"):
        decode_terminal_result(json.dumps(document))


def test_operator_text_and_legacy_diagnostics_are_sanitized_and_labelled():
    result = make_terminal_result(
        success=False,
        code="ACTION_FAILED",
        phase="execution",
        operator_message="bad\x1b[31m\nmessage",
        evidence={"raw": "value\x00with\ncontrols"},
    )
    diagnostics = format_legacy_diagnostics(
        stdout=b"vehicle command denied\n",
        stderr=b"SPI device unavailable\x1b[31m\n",
    )

    assert "\n" not in result.operator_message
    assert "\x1b" not in result.operator_message
    assert "Legacy stdout (diagnostic only)" in diagnostics
    assert "Legacy stderr (diagnostic only)" in diagnostics


def test_emit_uses_dedicated_fd_and_reader_is_bounded(monkeypatch):
    read_fd, write_fd = os.pipe()
    monkeypatch.setenv("MDS_ACTION_RESULT_FD", str(write_fd))

    emit_terminal_result(_failure_result())
    payload = read_bounded_result_fd(read_fd)

    assert decode_terminal_result(payload) == _failure_result()
