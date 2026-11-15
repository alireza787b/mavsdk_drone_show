"""Disposable communication evidence tooling; never connects to a real fleet."""
import csv
import json

import pytest

from tools.validate_communications_runtime import (
    ValidationOptions, distribution, native_sample, percentile, run_validation, write_evidence,
)


def test_options_bound_network_fanout_and_process_lifetime():
    ValidationOptions().validate()
    for kwargs in ({"aircraft": 201}, {"clients": 11}, {"interval": 0.001}, {"total_timeout": 181}):
        with pytest.raises(ValueError):
            ValidationOptions(**kwargs).validate()


def test_percentiles_are_exact_and_empty_evidence_stays_unknown():
    assert percentile([], 0.95) is None
    assert percentile(list(range(1, 101)), 0.95) == 95
    assert distribution([20, 10, 30]) == {"count": 3, "min": 10, "p50": 20, "p95": 30, "max": 30}


def test_synthetic_state_is_explicitly_non_flying_and_identity_bound():
    sample = native_sample(42)
    assert sample["hw_id"] == "42" and sample["ip"] == "127.0.0.42"
    assert sample["is_armed"] is False and sample["landed_state"] is None
    assert sample["timestamp"] == sample["update_time"]


def test_evidence_records_failure_and_separates_bounded_timeseries(tmp_path):
    result = {"success": False, "failure": "Injected fault", "samples": [{
        "elapsed_sec": 1, "phase": "fault", "client": 0, "aircraft": 2,
        "sample_age_min_ms": 10, "sample_age_p95_ms": 20, "payload_bytes": 100,
        "sequence": 1, "stream_id": "epoch",
    }]}
    write_evidence(result, tmp_path)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary == {"success": False, "failure": "Injected fault"}
    with (tmp_path / "samples.csv").open() as source:
        samples = list(csv.DictReader(source))
    assert samples[0]["sample_age_p95_ms"] == "20"


@pytest.mark.asyncio
async def test_small_real_http_ws_harness_proves_faults_and_cleanup(monkeypatch):
    monkeypatch.setenv("MDS_AUTH_ENABLED", "true")
    monkeypatch.setenv("MDS_API_AUTH_ENABLED", "true")
    result = await run_validation(ValidationOptions(aircraft=8, clients=2,
        baseline_seconds=0.15, steady_seconds=0.15, interval=0.05, total_timeout=45))
    assert result["success"], result
    assert result["checks"]["concurrent_pooled_http_connections"] == 8
    assert result["checks"]["simultaneous_companion_websockets"] == 8
    assert result["checks"]["delayed_old_http_fenced"]
    assert result["checks"]["silent_ws_http_healthy"]
    assert result["checks"]["dropped_ws_http_healthy"]
    assert result["checks"]["future_schema_rejected"]
    assert result["checks"]["publisher_epoch_reconnect"]
    assert result["checks"]["shutdown_clean"]
    assert result["max_pending_per_subscriber"] <= 1
    assert result["samples"]
    import os
    assert os.environ["MDS_AUTH_ENABLED"] == "true"
    assert os.environ["MDS_API_AUTH_ENABLED"] == "true"
