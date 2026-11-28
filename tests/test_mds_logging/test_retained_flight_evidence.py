from types import SimpleNamespace

import numpy as np
import pytest

from mds_logging.ulog_timeline import build_ulog_timeline


def dataset(name, index, times, **columns):
    return SimpleNamespace(name=name, multi_id=index, data={"timestamp": np.asarray(times),
                           **{key: np.asarray(value) for key, value in columns.items()}})


def test_timeline_preserves_sources_instances_counter_resets_and_unknown_utc():
    recording = SimpleNamespace(start_timestamp=1_000_000, msg_info_dict={}, data_list=[
        dataset("vehicle_status", 0, [1_100_000, 1_200_000, 3_000_000], nav_state=[14, 14, 5]),
        dataset("action_request", 0, [2_900_000], action=[5], source=[1], mode=[5]),
        dataset("telemetry_status", 0, [1_000_000, 7_000_000], rx_message_lost_count=[100, 101]),
        dataset("telemetry_status", 1, [1_000_000, 7_000_000], rx_message_lost_count=[23, 2]),
        dataset("vehicle_command", 0, [900_000, 2_000_000], command=[20, 176], param2=[0, 4], param3=[0, 3]),
        dataset("failsafe_flags", 0, [1_020_000, 2_000_000], offboard_control_signal_lost=[0, 1]),
    ])
    envelope = SimpleNamespace(complete=True, last_data_timestamp_us=7_000_000)
    timeline = build_ulog_timeline(recording, envelope)
    assert timeline["start_utc_ms"] is None and all(e["utc_ms"] is None for e in timeline["events"])
    assert [r["label"] for r in timeline["events"] if r["source"] == "PX4 mode"] == ["Offboard", "Return"]
    assert [r["label"] for r in timeline["events"] if r["source"] == "PX4 action"] == ["RC switch requested Return"]
    assert [r["label"] for r in timeline["events"] if r["source"] == "PX4 command"] == ["Hold requested"]
    by_instance = {r["instance"]: r["metrics"] for r in timeline["events"] if r["source"] == "MAVLink"}
    assert by_instance[0] == {"rx_message_lost_count_delta": 1, "interval_ms": 6000}
    assert by_instance[1] == {"counter_reset": True, "interval_ms": 6000}
    recording.msg_info_dict["boot_time_utc_us"] = 1_780_000_000_000_000
    aligned = build_ulog_timeline(recording, envelope)
    assert aligned["end_utc_ms"] == 1_780_000_007_000
    assert all(e["utc_ms"] == aligned["start_utc_ms"] + e["elapsed_ms"] for e in aligned["events"])
    envelope.complete = False
    assert build_ulog_timeline(recording, envelope)["end_utc_ms"] is None


@pytest.mark.parametrize('boot', [None, 1_780_000_000_000_000])
def test_native_mode_activation_is_not_request_ack_or_status_publication_time(boot):
    recording = SimpleNamespace(start_timestamp=1_000_000, msg_info_dict={'boot_time_utc_us': boot}, data_list=[
        dataset('vehicle_command_ack', 0, [1_030_000], command=[176], result=[0]),
        dataset('vehicle_status', 0, [1_020_000, 1_130_000, 1_140_000, 1_160_000],
                nav_state=[14, 4, 4, 5], nav_state_timestamp=[0, 1_091_345, 1_091_345, 1_170_000]),
    ])
    rows = build_ulog_timeline(recording, SimpleNamespace(complete=True, last_data_timestamp_us=1_160_000))['events']
    hold, = [e for e in rows if e['label'] == 'Hold']
    assert hold['elapsed_ms'] == 130
    assert hold['metrics']['mode_activated_boot_us'] == 1_091_345
    assert hold['metrics'].get('mode_activated_utc_ms') == ((boot + 1_091_345) // 1000 if boot else None)
    assert all('mode_activated_boot_us' not in r['metrics'] for r in rows if r is not hold)


@pytest.mark.asyncio
async def test_no_fabricated_companion_evidence_for_unaligned_or_old_logs(monkeypatch):
    import log_proxy
    from ulog_companion_evidence import collect_companion_evidence

    assert (await collect_companion_evidence("1", {})).status == "unavailable"

    async def inventory(_ip):
        return {"sessions": [{"session_id": "s_20261001_000000", "modified": 1_800_000_000}]}

    async def old(_ip, _session, **kwargs):
        raise log_proxy.DroneProxyResponseError(409, "older companion")

    monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda _: "192.0.2.5")
    monkeypatch.setattr(log_proxy, "fetch_drone_sessions", inventory)
    monkeypatch.setattr(log_proxy, "fetch_drone_session_content", old)
    result = await collect_companion_evidence("1", {"start_utc_ms": 1_799_999_900_000,
                                                         "end_utc_ms": 1_799_999_925_000})
    assert result.status == "unavailable" and "older" in result.reason and result.events == []


def test_periodic_samples_cannot_displace_command_evidence():
    from mds_logging.api_schemas import CompanionEvidenceEvent
    from ulog_companion_evidence import _MAX_EVENTS, _retained_rows

    sample = CompanionEvidenceEvent(utc_ms=0, kind="sample", source="Companion Wi-Fi", label="Aircraft Wi-Fi",
                                    session_id="s_20260101_010101")
    rows = [sample.model_copy(update={"utc_ms": t}) for t in range(350)]
    decision = sample.model_copy(update={"utc_ms": 153, "kind": "event", "label": "Hold decision"})
    rows.append(decision)
    selected = _retained_rows(rows)
    assert len(selected) == _MAX_EVENTS and decision in selected
    assert selected[0].utc_ms == 0 and selected[-1].utc_ms == 349


@pytest.mark.asyncio
async def test_reassignment_keeps_partial_page_without_replaying_cursor_to_a_different_node(monkeypatch):
    import log_proxy
    from ulog_companion_evidence import collect_companion_evidence

    start = 1_799_999_900_000
    session = "s_20261001_000000"
    hosts = iter(["192.0.2.5", "192.0.2.5", "192.0.2.55"])
    monkeypatch.setattr(log_proxy, "resolve_drone_ip", lambda _: next(hosts))

    async def sessions(_ip):
        return {"sessions": [{"session_id": session, "modified": start / 1000 + 1}]}

    async def page(ip, file_session, **query):
        assert ip == "192.0.2.5" and file_session == session and query["cursor"] is None
        row = {"session_id": session, "component": "smart_swarm.link", "extra": {"schema_version": 1,
               "session_id": "one", "hw_id": "5", "event": "hold_decision", "observed_at_ms": start}}
        return {"session_id": session, "schema_version": "1.1", "lines": [row], "has_more": True,
                "next_cursor": "first-node-cursor"}

    monkeypatch.setattr(log_proxy, "fetch_drone_sessions", sessions)
    monkeypatch.setattr(log_proxy, "fetch_drone_session_content", page)
    saved = await collect_companion_evidence("5", {"start_utc_ms": start, "end_utc_ms": start + 1000})
    assert saved.status == "partial" and "address changed" in saved.reason
    assert [r.label for r in saved.events] == ["Hold decision"]
