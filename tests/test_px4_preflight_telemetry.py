import json
import lzma
import struct
from types import SimpleNamespace
import zlib

from pymavlink import mavutil
import pytest

from px4_preflight_relay import Px4PreflightRelay
from src.px4_arming_report import Px4ArmingObserver, decode_event_frame
from src.px4_flight_modes import PX4_TAKEOFF_CUSTOM_MODE as TAKEOFF_MODE
from src.px4_event_metadata import _document
from src.px4_preflight_telemetry import current_preflight_report

HOLD = 50593792


def state(*, epoch='companion:1', sample=1, sent=1000):
    return dict(telemetry_available=True, is_armed=False, landed_state=1, flight_mode=HOLD,
                px4_report_epoch=epoch, px4_node_monotonic_ms=sent,
                px4_arming_report=dict(source='px4_events', mode='Hold', custom_mode=HOLD,
                                       can_arm=False, remaining_valid_ms=4000, revision='0' * 24, sample=sample,
                                       mode_problems=[dict(message='No valid position estimate', severity='ERROR')]))


@pytest.mark.parametrize('overrides', [dict(is_armed=True), dict(is_armed=None),
    dict(landed_state=2), dict(landed_state=True), dict(telemetry_available=False), dict(flight_mode=131072)])
def test_no_verdict_without_matching_ground_state(overrides):
    assert current_preflight_report({**state(), **overrides}) is None


def test_hold_reason_and_takeoff_verdict_are_independent(monkeypatch):
    now = [1.]
    monkeypatch.setattr('src.px4_arming_report.time.monotonic', lambda: now[0])
    observer = Px4ArmingObserver(3)
    observer.metadata.groups = {HOLD: 4, TAKEOFF_MODE: 7}
    observer.heartbeat(HOLD, False)
    observer.landed(True)

    def event(group, kind, args, text=''):
        return SimpleNamespace(group=lambda: group, type=lambda: kind, argument_value=lambda i: args[i],
                               message=lambda: text, description=lambda: 'Native reason')

    observer._consume(event('arming_check','summary',[0,0,0,1 << 7,0]), 8, 1000)
    assert observer.snapshot(HOLD)[1] == []
    observer._consume(event('arming_check','',[1 << 4], 'No valid position estimate'), 3, 1000)
    observer._consume(event('health','summary',[0]), 8, 1000)
    _, reports = observer.snapshot(HOLD)
    assert reports[0]['can_arm'] is False and reports[0]['mode_problems'][0]['message'] == 'No valid position estimate'
    assert reports[1]['can_arm'] is True and reports[1]['mode_problems'] == []
    now[0] += 4.5
    observer.heartbeat(HOLD, False)
    observer.landed(True)
    assert observer.snapshot(HOLD)[1][0]['remaining_valid_ms'] == 500
    now[0] += .5
    assert observer.snapshot(HOLD)[1] == []
    observer.heartbeat(TAKEOFF_MODE, False)
    assert observer.snapshot(TAKEOFF_MODE)[1] == []


def test_companion_uses_wire_crc_and_both_px4_metadata_checksum_forms():
    data = json.dumps(dict(version=1)).encode()
    compressed = lzma.compress(data)
    for payload in (data, compressed):
        crc = zlib.crc32(payload, 0xffffffff) ^ 0xffffffff
        assert _document(compressed, 'component_general.json.xz', crc) == dict(version=1)
    body = struct.pack('<HB', 123, 1)
    header = bytes((len(body), 0, 0, 7, 1, 1)) + (411).to_bytes(3, 'little')
    crc = mavutil.x25crc(header + body + bytes([106])).crc
    wire = bytearray(b'\xfd' + header + body + crc.to_bytes(2, 'little'))
    assert decode_event_frame(wire) == (411, (1, 1), (123, 1))
    wire[10] ^= 1
    assert decode_event_frame(wire) is None


def test_relay_keeps_original_deadline_across_duplicate_frames_and_reconnect(monkeypatch):
    clock = [8000]
    monkeypatch.setattr('px4_preflight_relay.monotonic_ms', lambda: clock[0])
    relay = Px4PreflightRelay()
    relay.update(state(), earliest_send_ms=7000, received_ms=8000)
    relay.update(state(sent=1400), earliest_send_ms=7700, received_ms=8100)
    deadline, verdict, reasons = relay.snapshot()['px4_arming_report']
    assert deadline == 11000
    assert 'mode_problems' not in verdict and reasons[0]['severity'] == 'ERROR'
    relay.update(state(epoch='companion:2', sample=2, sent=1600), earliest_send_ms=7800, received_ms=8100)
    relay.update(state(sent=1500), earliest_send_ms=8000, received_ms=8500)
    assert relay.snapshot()['px4_arming_report'][0] == 11800
    clock[0] = 11800
    assert relay.snapshot() == {}


def test_late_packet_cannot_restore_an_explicit_native_invalidation(monkeypatch):
    monkeypatch.setattr('px4_preflight_relay.monotonic_ms', lambda: 1000)
    relay = Px4PreflightRelay()
    relay.update(state(), earliest_send_ms=900, received_ms=1000)
    relay.update({**state(sent=1250), 'px4_arming_report': None}, earliest_send_ms=1100, received_ms=1300)
    relay.update(state(sent=1100), earliest_send_ms=1100, received_ms=1310)
    assert relay.snapshot() == {}
    relay.update(state(sample=2, sent=1450), earliest_send_ms=None, received_ms=1500)
    assert relay.snapshot() == {}
