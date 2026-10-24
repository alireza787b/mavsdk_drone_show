"""Control release is bounded ownership evidence, never terminal success."""
import json
import os

import pytest

from src.control_release_protocol import (
    CONTROL_RELEASE_COMMAND_ENV, CONTROL_RELEASE_FD_ENV, CONTROL_RELEASE_OWNER_ENV,
    MAX_CONTROL_RELEASE_BYTES, ControlReleaseResult, decode_control_release,
    emit_control_release,
)


def release_result(**changes):
    return ControlReleaseResult(**{
        "command_id": "swarm-old", "ownership_token": "owner-old", "hw_id": "2",
        "producers_stopped": True, "offboard_stop_completed": True,
        "hold_accepted": True, "observed_mode": "OFFBOARD",
        "external_control_preserved": False, **changes,
    })


def test_release_does_not_assert_held_or_terminal_success():
    result = release_result()
    decoded = decode_control_release(result.model_dump_json().encode() + b"\n")
    assert decoded.released
    assert decoded.observed_mode == "OFFBOARD"
    assert "success" not in decoded.model_dump()
    assert not release_result(producers_stopped=False).released
    assert not release_result(hold_accepted=False).released
    assert release_result(hold_accepted=False, external_control_preserved=True).released


@pytest.mark.parametrize("change", [
    {"kind": "terminal_result"}, {"success": True}, {"producers_stopped": 1},
    {"schema_version": True},
    {"hold_accepted": "true"}, {"ownership_token": ""}, {"observed_mode": "x" * 65},
])
def test_release_rejects_invalid_typed_evidence(change):
    document = {**release_result().model_dump(), **change}
    with pytest.raises(ValueError):
        decode_control_release(json.dumps(document).encode() + b"\n")


@pytest.mark.parametrize("payload", [b"{}", b"{}\n{}\n", b"x" * (MAX_CONTROL_RELEASE_BYTES + 1)])
def test_release_rejects_partial_multiple_and_oversized_messages(payload):
    with pytest.raises(ValueError):
        decode_control_release(payload)


def _emit(monkeypatch, write_fd):
    monkeypatch.setenv(CONTROL_RELEASE_FD_ENV, str(write_fd))
    monkeypatch.setenv(CONTROL_RELEASE_OWNER_ENV, "owner-old")
    monkeypatch.setenv(CONTROL_RELEASE_COMMAND_ENV, "swarm-old")
    return emit_control_release(hw_id="2", producers_stopped=True,
                                offboard_stop_completed=True, hold_accepted=True,
                                observed_mode=None, external_control_preserved=False)


def test_release_uses_dedicated_fd_once(monkeypatch, capsys):
    read_fd, write_fd = os.pipe()
    try:
        assert _emit(monkeypatch, write_fd)
        result = decode_control_release(os.read(read_fd, MAX_CONTROL_RELEASE_BYTES + 1))
        assert result.ownership_token == "owner-old"
        assert result.observed_mode is None
        assert os.read(read_fd, 1) == b""
        assert not emit_control_release(hw_id="2", producers_stopped=True,
                                        offboard_stop_completed=True, hold_accepted=True,
                                        observed_mode=None, external_control_preserved=False)
        assert capsys.readouterr().out == ""
    finally:
        os.close(read_fd)


def test_full_release_pipe_fails_closed_without_blocking(monkeypatch):
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    try:
        while True:
            try:
                os.write(write_fd, b"x" * 4096)
            except BlockingIOError:
                break
        assert not _emit(monkeypatch, write_fd)
    finally:
        os.close(read_fd)
