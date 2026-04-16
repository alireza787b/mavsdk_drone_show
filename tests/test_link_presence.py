import time
from unittest.mock import patch


def test_recent_link_presence_accepts_recent_telemetry_without_recent_heartbeat():
    from link_presence import get_recent_link_presence

    now = 1_700_000_000.0
    telemetry_rows = {
        "1": {
            "telemetry_available": True,
        }
    }
    telemetry_times = {"1": now - 2.0}

    with patch("link_presence.get_all_heartbeats", return_value={}):
        with patch.dict("link_presence.telemetry_data_all_drones", telemetry_rows, clear=True):
            with patch.dict("link_presence.last_telemetry_time", telemetry_times, clear=True):
                snapshot = get_recent_link_presence(["1"], now=now)

    assert snapshot["1"]["online_recent"] is True
    assert snapshot["1"]["telemetry_recent"] is True
    assert snapshot["1"]["heartbeat_recent"] is False
    assert snapshot["1"]["source"] == "telemetry"


def test_recent_link_presence_reports_stale_heartbeat_without_telemetry():
    from link_presence import get_recent_link_presence

    now = time.time()
    stale_ms = int((now - 45.0) * 1000)

    with patch("link_presence.get_all_heartbeats", return_value={"1": {"timestamp": stale_ms}}):
        with patch.dict("link_presence.telemetry_data_all_drones", {}, clear=True):
            with patch.dict("link_presence.last_telemetry_time", {}, clear=True):
                snapshot = get_recent_link_presence(["1"], now=now)

    assert snapshot["1"]["online_recent"] is False
    assert snapshot["1"]["source"] == "stale-heartbeat"
    assert "Heartbeat stale" in snapshot["1"]["reason"]
