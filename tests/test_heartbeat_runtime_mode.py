from types import SimpleNamespace

import heartbeat as heartbeat_module


def _reset_heartbeat_state():
    heartbeat_module.last_heartbeats.clear()
    heartbeat_module.network_info_from_heartbeats.clear()
    heartbeat_module._missing_runtime_mode_notice_keys.clear()
    heartbeat_module._runtime_mode_mismatch_notice_keys.clear()


def test_handle_heartbeat_post_accepts_matching_runtime_mode(monkeypatch):
    _reset_heartbeat_state()
    monkeypatch.setattr(
        heartbeat_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="real", sim_mode=False, source="env:MDS_MODE"),
    )

    result = heartbeat_module.handle_heartbeat_post(
        pos_id=1,
        hw_id="101",
        ip="100.64.0.10",
        timestamp=1700000000000,
        network_info={"wifi": {"ssid": "demo"}},
        runtime_mode="real",
    )

    assert result["accepted"] is True
    assert heartbeat_module.last_heartbeats["101"]["runtime_mode"] == "real"
    assert heartbeat_module.network_info_from_heartbeats["101"]["runtime_mode"] == "real"


def test_handle_heartbeat_post_ignores_mismatched_runtime_mode(monkeypatch):
    _reset_heartbeat_state()
    monkeypatch.setattr(
        heartbeat_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="real", sim_mode=False, source="env:MDS_MODE"),
    )

    result = heartbeat_module.handle_heartbeat_post(
        pos_id=1,
        hw_id="101",
        ip="172.18.0.20",
        timestamp=1700000000000,
        runtime_mode="sitl",
    )

    assert result["accepted"] is False
    assert result["current_mode"] == "real"
    assert heartbeat_module.last_heartbeats == {}


def test_handle_heartbeat_post_rejects_missing_runtime_mode(monkeypatch):
    _reset_heartbeat_state()
    monkeypatch.setattr(
        heartbeat_module,
        "resolve_runtime_mode",
        lambda: SimpleNamespace(mode="sitl", sim_mode=True, source="env:MDS_MODE"),
    )

    result = heartbeat_module.handle_heartbeat_post(
        pos_id=2,
        hw_id="202",
        ip="172.18.0.21",
        timestamp=1700000000000,
        runtime_mode=None,
    )

    assert result["accepted"] is False
    assert heartbeat_module.last_heartbeats == {}
