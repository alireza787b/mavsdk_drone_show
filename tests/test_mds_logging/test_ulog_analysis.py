import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest
from pydantic import ValidationError

from mds_logging.api_schemas import UlogDerivedSummary
from mds_logging.ulog_analysis import (
    UlogSummaryError,
    UlogSummaryTimeoutError,
    _joint_finite_sample_arrays,
    _run_summary_subprocess,
    _summarize_local_position,
    _summarize_setpoint,
    _worker_environment,
    summarize_ulog_file_async,
    summarize_ulog_file_with_timeout,
)


def _dataset(**data):
    return SimpleNamespace(data=data)


def test_local_position_uses_one_validity_mask_for_coordinates_and_timestamp():
    dataset = _dataset(
        timestamp=np.array([100, 101, np.nan, 103, 104]),
        x=np.array([0.0, 1.0, 2.0, np.nan, 4.0]),
        y=np.array([0.0, np.nan, 20.0, 3.0, 4.0]),
        z=np.array([0.0, -1.0, -2.0, -3.0, -4.0]),
    )

    summary = _summarize_local_position(dataset)

    assert summary == {
        "samples": 2,
        "x_range_m": {"min": 0.0, "max": 4.0, "final": 4.0},
        "y_range_m": {"min": 0.0, "max": 4.0, "final": 4.0},
        "relative_altitude_range_m": {"min": -0.0, "max": 4.0, "final": 4.0},
        "max_horizontal_distance_from_start_m": 5.657,
        "final_relative_position_m": {
            "north": 4.0,
            "east": 4.0,
            "up": 4.0,
        },
    }


def test_setpoint_ranges_only_include_jointly_valid_samples():
    dataset = _dataset(
        timestamp_sample=np.array([10, 11, 12, 13, 14]),
        **{
            "position[0]": np.array([0.0, 1.0, 2.0, np.nan, 4.0]),
            "position[1]": np.array([0.0, np.nan, 20.0, 3.0, 4.0]),
            "position[2]": np.array([0.0, -1.0, np.nan, -3.0, -4.0]),
        },
    )

    summary = _summarize_setpoint(dataset)

    assert summary == {
        "samples": 2,
        "north_m_range": {"min": 0.0, "max": 4.0, "final": 4.0},
        "east_m_range": {"min": 0.0, "max": 4.0, "final": 4.0},
        "down_m_range": {"min": -4.0, "max": 0.0, "final": -4.0},
    }


def test_joint_sample_arrays_keep_timestamp_correlated_with_coordinates():
    samples = _joint_finite_sample_arrays(
        {
            "timestamp": [100, 101, 102, 103],
            "x": [0.0, np.nan, 2.0, 3.0],
            "y": [0.0, 1.0, np.nan, 3.0],
            "z": [0.0, 1.0, 2.0, 3.0],
        },
        ("x", "y", "z"),
    )

    assert samples["timestamp"].tolist() == [100.0, 103.0]
    assert samples["x"].tolist() == [0.0, 3.0]
    assert samples["y"].tolist() == [0.0, 3.0]
    assert samples["z"].tolist() == [0.0, 3.0]


@pytest.mark.asyncio
async def test_async_summary_runs_in_bounded_worker(tmp_path, monkeypatch):
    path = tmp_path / "flight.ulg"
    path.write_bytes(b"ulog")
    caller_thread = threading.get_ident()
    parser_threads = []

    def fake_summary(_path, **_kwargs):
        parser_threads.append(threading.get_ident())
        return {"parsed": True}

    monkeypatch.setattr(
        "mds_logging.ulog_analysis._run_summary_subprocess",
        fake_summary,
    )

    result = await summarize_ulog_file_async(path, timeout_seconds=1.0)

    assert result == {"parsed": True}
    assert parser_threads and parser_threads[0] != caller_thread


@pytest.mark.asyncio
async def test_async_summary_times_out_without_blocking_caller(tmp_path, monkeypatch):
    path = tmp_path / "slow.ulg"
    path.write_bytes(b"ulog")

    def slow_summary(_path, **_kwargs):
        time.sleep(0.05)
        return {"parsed": True}

    monkeypatch.setattr(
        "mds_logging.ulog_analysis._run_summary_subprocess",
        slow_summary,
    )
    monkeypatch.setattr("mds_logging.ulog_analysis._ULOG_SUMMARY_WORKER_GRACE_SECONDS", 0.0)

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        await summarize_ulog_file_async(path, timeout_seconds=0.005)
    assert time.monotonic() - started < 0.04


def test_sync_summary_timeout_uses_same_bounded_pool(tmp_path, monkeypatch):
    path = tmp_path / "slow-sync.ulg"
    path.write_bytes(b"ulog")

    def slow_summary(_path, **_kwargs):
        time.sleep(0.05)
        return {"parsed": True}

    monkeypatch.setattr(
        "mds_logging.ulog_analysis._run_summary_subprocess",
        slow_summary,
    )
    monkeypatch.setattr("mds_logging.ulog_analysis._ULOG_SUMMARY_WORKER_GRACE_SECONDS", 0.0)

    started = time.monotonic()
    with pytest.raises(TimeoutError, match="timed out"):
        summarize_ulog_file_with_timeout(path, timeout_seconds=0.005)
    assert time.monotonic() - started < 0.04


def test_subprocess_timeout_terminates_parser_worker(tmp_path, monkeypatch):
    path = tmp_path / "stalled.ulg"
    path.write_bytes(b"ulog")

    class FakeProcess:
        returncode = None

        def __init__(self):
            self.terminated = False

        def communicate(self, _payload, timeout):
            raise __import__("subprocess").TimeoutExpired("ulog-worker", timeout)

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout):
            return self.returncode

    process = FakeProcess()
    popen_kwargs = {}

    def fake_popen(*_args, **kwargs):
        popen_kwargs.update(kwargs)
        return process

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-worker")
    monkeypatch.setenv("MDS_AUTH_SESSION_SECRET", "must-not-reach-worker")
    monkeypatch.setattr(
        "mds_logging.ulog_analysis.subprocess.Popen",
        fake_popen,
    )

    with pytest.raises(UlogSummaryTimeoutError, match="timed out"):
        _run_summary_subprocess(
            path,
            source_metadata={},
            max_bytes=1024,
            timeout_seconds=0.01,
        )

    assert process.terminated is True
    assert popen_kwargs["close_fds"] is True
    assert popen_kwargs["start_new_session"] is True
    assert "OPENAI_API_KEY" not in popen_kwargs["env"]
    assert "MDS_AUTH_SESSION_SECRET" not in popen_kwargs["env"]


def test_worker_environment_is_minimal_and_contains_resource_contract(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("HOME", "/secret-home")

    environment = _worker_environment("/srv/mds")

    assert environment["PYTHONPATH"] == "/srv/mds"
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["MDS_ULOG_SUMMARY_MAX_MEMORY_MB"]
    assert environment["MDS_ULOG_SUMMARY_MAX_CPU_SEC"]
    assert environment["MDS_ULOG_SUMMARY_MAX_OUTPUT_BYTES"]
    assert environment["MDS_ULOG_SUMMARY_MAX_OPEN_FILES"]
    assert "OPENAI_API_KEY" not in environment
    assert "HOME" not in environment


def test_summary_queue_rejects_excess_work_without_growing(monkeypatch):
    import mds_logging.ulog_analysis as analysis

    class FullSlots:
        def acquire(self, *, blocking):
            assert blocking is False
            return False

    monkeypatch.setattr(analysis, "_ULOG_SUMMARY_EXECUTOR", object())
    monkeypatch.setattr(analysis, "_ULOG_SUMMARY_SLOTS", FullSlots())

    with pytest.raises(UlogSummaryError) as error:
        analysis._submit_summary_operation(lambda: {"parsed": True})

    assert error.value.code == "ulog_summary_busy"
    assert error.value.http_status == 429


def test_derived_summary_schema_rejects_unknown_or_oversized_nested_evidence():
    with pytest.raises(ValidationError):
        UlogDerivedSummary.model_validate(
            {
                "source": {"source_kind": "uploaded_file", "unexpected": "raw"},
                "parser": {"status": "ok"},
                "parsed": True,
            }
        )

    with pytest.raises(ValidationError):
        UlogDerivedSummary.model_validate(
            {
                "source": {"source_kind": "uploaded_file"},
                "parser": {
                    "status": "ok",
                    "topics_present": [f"topic-{index}" for index in range(33)],
                },
                "parsed": True,
            }
        )


def test_real_parser_worker_returns_typed_error_for_malformed_ulog(tmp_path):
    path = tmp_path / "malformed.ulg"
    path.write_bytes(b"not-a-valid-ulog")

    with pytest.raises(UlogSummaryError) as error:
        _run_summary_subprocess(
            path,
            source_metadata={"source_kind": "test"},
            max_bytes=1024,
            timeout_seconds=10.0,
        )

    assert error.value.code == "ulog_summary_parse_failed"
    assert error.value.http_status == 422
