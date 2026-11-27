"""Bounded aircraft diagnostics, source identity and loss of observation."""
import threading
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import TypeAdapter

from smart_swarm_src import link_evidence
from src.smart_swarm_contract import OptionalSwarmLinkObservation, SwarmLinkObservation


def test_summary_uses_native_age_and_expires_without_updates(monkeypatch):
    clock = SimpleNamespace(now=42.0, utc_ms=1800000000000)
    monkeypatch.setattr(link_evidence, "time", SimpleNamespace(
        monotonic=lambda: clock.now, time_ns=lambda: clock.utc_ms * 1000000))
    sink = Mock()
    observer = link_evidence.LinkEvidence("command-2", logger=sink)
    leader = {"update_time": 41.9, "attitude_update_time": 41.8, "transport": "ws",
              "received_at_ms": clock.utc_ms}
    own = {"updated_monotonic": 41.95, "yaw_updated_monotonic": "unavailable"}

    def fields():
        return observer.fields(hw_id=2, leader_hw_id=1, leader=leader, own=own,
                               source_limit=.75, hard_limit=2)

    try:
        observer.sample_accepted(40.8)
        observer.sample_accepted(42.0)
        observer.transport_event("fallback_attempt")
        observer.transport_event("ws_TimeoutError")
        observer.transport_event("malformed_sample")
        observer.setpoint_sent(.014)
        first = observer.summary(fields)
        assert (first["position_age_ms"], first["heading_age_ms"]) == (100, 200)
        assert (first["own_position_age_ms"], first["own_heading_age_ms"]) == (50, None)
        assert first["state"] == "fresh"
        assert first["accepted"] == 2 and first["rejected"] == 1
        assert first["fallback_attempts"] == 1 and first["last_transport_error"] == "ws_TimeoutError"
        assert first["max_gap_ms"] == 1200 and first["max_setpoint_send_ms"] == 14
        clock.now += 1
        observer.setpoint_sent(.080)
        assert fields()["setpoint_count"] == 2
        assert fields()["max_setpoint_gap_ms"] == 1000 and fields()["max_setpoint_send_ms"] == 80
        assert fields()["state"] == "delayed"
        assert observer.summary(fields) is first
        clock.now += 5
        clock.utc_ms += 6000
        second = observer.summary(fields)
        assert second["state"] == "missing" and second["max_gap_ms"] == 6000
        assert second["last_accepted_at_ms"] == first["last_accepted_at_ms"]
        assert second["observed_at_ms"] > first["observed_at_ms"]
        fence = dict(hw_id=2, follow=1, session_id="command-2", now_ms=clock.utc_ms)
        assert SwarmLinkObservation.current(second, **fence) == second
        for change in (dict(hw_id=3), dict(follow=4), dict(session_id="old"),
                       dict(now_ms=second["valid_until_ms"]), dict(now_ms=second["observed_at_ms"] - 1)):
            assert SwarmLinkObservation.current(second, **(fence | change)) is None
        assert TypeAdapter(OptionalSwarmLinkObservation).validate_python({**second, "schema_version": 8}) is None
        assert TypeAdapter(OptionalSwarmLinkObservation).validate_python(second).hw_id == "2"
        observer.reset_target()
        assert observer.latest is None and observer.accepted == 0 and observer.last_transport_error is None
    finally:
        observer.close()
    assert [call.kwargs["extra"]["mds_extra"]["event_sequence"] for call in sink.info.call_args_list] == [1, 2]


def test_stalled_sink_yields_recorded_gap_without_blocking_producer():
    entered, release = threading.Event(), threading.Event()
    rows = []

    def slow_sink(*args, extra):
        entered.set()
        release.wait(timeout=5)
        rows.append(extra["mds_extra"])

    observer = link_evidence.LinkEvidence("active", logger=SimpleNamespace(info=slow_sink), queue_size=1)
    try:
        observer.emit("session_start", {"hw_id": "1"})
        assert entered.wait(timeout=2)
        observer.emit("mode_requested", {"hw_id": "1"})
        observer.emit("mode_result", {"hw_id": "1"})
        observer.emit("session_end", {"hw_id": "1"})
    finally:
        release.set()
        observer.close()
    assert [row["event"] for row in rows] == ["session_start", "mode_requested", "coverage_gap"]
    assert rows[-1]["dropped"] == 2 and rows[-1]["event_sequence"] == 4


@pytest.mark.parametrize(("wifi", "active", "status", "percent"), [
    ({"signal_strength_percent": 0, "ssid": "private", "interface": "wlan0"}, [], "reported", 0),
    ({"signal_strength_percent": 101}, [], "unavailable", None),
    ({"signal_strength_percent": "Unknown"}, [], "unavailable", None),
    ({}, [], "unavailable", None),
    ({"signal_strength_percent": 90}, [{"type": "wifi"}, {"type": "wifi"}], "ambiguous", None),
])
def test_network_receipt_uses_existing_measurement_with_no_ssid(monkeypatch, wifi, active, status, percent):
    from src import heartbeat_sender

    sink = Mock()
    monkeypatch.setattr(heartbeat_sender, "swarm_link_logger", sink)
    heartbeat_sender.HeartbeatSender._log_swarm_network(
        "2", {"session_id": "run"}, {"timestamp": 1000, "wifi": wifi, "active_links": active})
    row = sink.info.call_args.kwargs["extra"]["mds_extra"]
    assert row["event"] == "network_observation" and row["session_id"] == "run"
    assert row["wifi_status"] == status and row.get("wifi_signal_percent") == percent
    assert row["wifi_observed_at_ms"] == 1000 and "private" not in repr(row)


def test_aircraft_runtime_assignment_survives_normal_telemetry_and_preview(tmp_path, monkeypatch):
    import time
    from tests.test_drone_communicator import build_drone_config
    from src.drone_communicator import DroneCommunicator
    from src.swarm_runtime_state import write_runtime_swarm_assignment
    from smart_swarm_service import build_preview

    observer = link_evidence.LinkEvidence("active-command", logger=Mock())
    now = time.time_ns() // 1_000_000
    try:
        seen = observer.fields(hw_id=3, leader_hw_id=1, leader={}, own={}, source_limit=.75, hard_limit=2)
    finally:
        observer.close()
    monkeypatch.setenv("MDS_SWARM_RUNTIME_ASSIGNMENT_PATH", str(tmp_path / "assignment.json"))
    write_runtime_swarm_assignment({"hw_id": 3, "follow": 1, "session_id": "active-command",
                                    "active": True, "link_observation": seen})
    config = build_drone_config(follow_value=1)
    config.last_update_timestamp = now / 1000
    config.telemetry_timestamp_ms = now
    node = DroneCommunicator(drone_config=config, params=SimpleNamespace(
        enable_udp_telemetry=False, enable_default_subscriptions=False), drones={})
    node._refresh_runtime_swarm_assignment()
    receiver = node.get_drone_state()
    assert receiver["link_observation"] == seen and receiver["follow_mode"] == 1
    receiver["current_command_id"] = "active-command"
    deps = SimpleNamespace(telemetry_lock=threading.Lock(), telemetry_data_all_drones={"3": receiver},
                           load_swarm=lambda: [{"hw_id": 1, "follow": 0}, {"hw_id": 3, "follow": 1}])

    def member():
        return build_preview(deps)["clusters"][0]["members"][1]

    assert member()["link_observation"] == seen
    receiver["current_command_id"] = "different-command"
    assert member()["link_observation"] is None
    receiver.update(current_command_id="active-command", telemetry_available=False)
    assert member()["available"] is False and member()["link_observation"] is None


def test_writer_recovery_marks_unwritten_records():
    accepted = []

    def recovered_sink(_, event, *, extra):
        if event == "mode_requested":
            raise OSError("simulated full volume")
        accepted.append(extra["mds_extra"])

    observer = link_evidence.LinkEvidence("command", logger=SimpleNamespace(info=recovered_sink))
    observer.emit("mode_requested", {"hw_id": "3"})
    observer.emit("mode_result", {"hw_id": "3"})
    observer.close()
    assert len(accepted) == 1 and accepted[0]["dropped_before"] == 1
