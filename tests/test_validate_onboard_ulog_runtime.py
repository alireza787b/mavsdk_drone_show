import hashlib
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
import urllib.error

import pytest

from tools.validate_onboard_ulog_runtime import download_ulog_evidence
from tools import validate_onboard_ulog_runtime as validator


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {"content-length": str(len(body))}
    def read(self, size=-1):
        assert 0 < size <= 256 * 1024, "Validator must never read the full raw file into memory"
        return super().read(size)


def test_complete_stream_has_header_size_and_checksum_evidence(monkeypatch):
    body = b"ULog\x01\x12\x35" + b"\x01" + b"\0" * 8 + b"x" * 600000
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(body))
    evidence, _ = download_ulog_evidence("http://127.0.0.1", "/content", expected_size=len(body))
    assert evidence["sha256"] == hashlib.sha256(body).hexdigest()
    assert evidence["bytes"] == len(body) and evidence["ulog_header_verified"]


@pytest.mark.parametrize("body,expected", [(b"wrong header and enough bytes", 28),
    (b"ULog\x01\x12\x35\x01" + b"\0" * 8, 100)])
def test_nonempty_or_staged_ready_is_not_transfer_integrity(monkeypatch, body, expected):
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: Response(body))
    with pytest.raises(RuntimeError):
        download_ulog_evidence("http://127.0.0.1", "/content", expected_size=expected)


def test_armed_denial_requires_native_conflict_evidence(monkeypatch):
    def reject(*_args, **_kwargs):
        raise urllib.error.HTTPError("http://lab", 409, "Conflict", {}, io.BytesIO(b'{"detail":"vehicle armed"}'))
    monkeypatch.setattr("urllib.request.urlopen", reject)
    assert validator.require_armed_denial("http://lab", "/ulog/erase-all")["http_status"] == 409


def test_accepted_armed_operation_is_not_a_successful_guard_check(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: io.BytesIO(b'{"status":"accepted"}'))
    with pytest.raises(RuntimeError, match="not denied"):
        validator.require_armed_denial("http://lab", "/ulog/erase-all")


def test_validator_failure_lands_only_attempted_sitl_target_and_writes_partial_report(monkeypatch):
    args = SimpleNamespace(base_url="http://lab", drone_ids=[1], drones=None, takeoff_min_gain=4,
                           list_timeout_sec=60, job_timeout_sec=120, json_output="unused")
    client = Mock()
    client.submit_command.return_value = {"command_id": "cleanup-land"}
    reports = []

    def failed_run(_client, _args, results):
        results["takeoff_attempted"] = True
        raise RuntimeError("injected transfer failure")

    monkeypatch.setattr(validator, "parse_args", lambda: args)
    monkeypatch.setattr(validator, "ApiClient", lambda _url: client)
    monkeypatch.setattr(validator, "run_validation", failed_run)
    monkeypatch.setattr(validator, "wait_for_command", lambda *_args, **_kwargs: {"status": "completed"})
    monkeypatch.setattr(validator, "require_full_acceptance", lambda *_args: None)
    monkeypatch.setattr(validator, "require_full_execution", lambda *_args: None)
    monkeypatch.setattr(validator, "wait_idle_subset", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(validator, "write_json_report", lambda _path, result: reports.append(json.loads(json.dumps(result))))
    with pytest.raises(RuntimeError, match="injected transfer failure"):
        validator.main()
    assert client.submit_command.call_args.args[1] == [1]
    assert reports[0]["status"] == "failed"
    assert reports[0]["land_confirmed"] is True
    assert reports[0]["failure_land_cleanup"]["status"] == "completed"
