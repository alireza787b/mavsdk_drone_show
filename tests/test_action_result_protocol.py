import json
import os

import pytest

from src.action_result_protocol import (
    ACTION_RESULT_SENTINEL,
    MAX_RESULT_BYTES,
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
