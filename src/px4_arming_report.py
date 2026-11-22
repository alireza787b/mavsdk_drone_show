"""Companion-owned PX4 Events arming evidence on the existing local MAVLink route."""

from dataclasses import dataclass
import hashlib
import json
import logging
import struct
import time
from uuid import uuid4

from pymavlink import mavutil

from src.px4_event_metadata import EventMetadata
from src.px4_flight_modes import PX4_TAKEOFF_CUSTOM_MODE, describe_px4_custom_mode

LOG = logging.getLogger(__name__)
VALID_MS = 5000
REFRESH_SECONDS = 3
SEVERITIES = ('EMERGENCY', 'ALERT', 'CRITICAL', 'ERROR', 'WARNING', 'NOTICE', 'INFO', 'DEBUG')

# MAVLink common.xml wire order and CRC extras. The pinned pymavlink dialect
# returns these newer MAVLink 2 messages as UNKNOWN. Decode only these messages.
WIRE = {
    397: (struct.Struct('<II100s'), 182),     # COMPONENT_METADATA
    410: (struct.Struct('<IIHBBB40s'), 160),  # EVENT
    411: (struct.Struct('<HB'), 106),       # CURRENT_EVENT_SEQUENCE
    413: (struct.Struct('<HHBBB'), 77),     # RESPONSE_EVENT_ERROR
}


def decode_event_frame(raw):
    if len(raw) < 12 or raw[0] != 253 or raw[2] & ~1:
        return None
    msg_id = int.from_bytes(raw[7:10], 'little')
    if msg_id not in WIRE:
        return None
    layout, extra = WIRE[msg_id]
    end = 10 + raw[1]
    if end + 2 > len(raw) or raw[1] > layout.size:
        return None
    checksum = mavutil.x25crc(bytes(raw[1:end]) + bytes([extra])).crc
    if checksum != int.from_bytes(raw[end:end + 2], 'little'):
        return None
    return msg_id, (raw[5], raw[6]), layout.unpack(bytes(raw[10:end]).ljust(layout.size, b'\0'))


@dataclass(frozen=True)
class CompletedReport:
    observed_ms: int
    number: int
    mode: int
    can_arm: int
    problems: tuple


class Px4ArmingObserver:
    def __init__(self, hw_id):
        self.identity = uuid4().hex
        self.generation = 0
        self.number = 0
        self.metadata = EventMetadata()
        self.last_sequence = self.report = self.pending = self.last_boot_ms = self.telemetry_boot_ms = None
        self.heartbeat_at = self.ground_at = None
        self.armed = None
        self.mode = 0
        self.refresh_at = 0.
        self.interval = REFRESH_SECONDS + (int(hashlib.sha256(str(hw_id).encode()).hexdigest()[:2], 16) / 255 - .5) / 2

    def invalidate(self, *, disconnected=False):
        self.pending = self.report = None
        self.generation += 1
        if disconnected:
            self.last_sequence = self.last_boot_ms = self.telemetry_boot_ms = None
            self.heartbeat_at = self.ground_at = None
            self.armed = None
            self.metadata.reset()

    def observe_boot_time(self, boot_ms):
        if type(boot_ms) is not int or not 0 <= boot_ms < 2**32:
            return
        last = self.telemetry_boot_ms
        if last is not None and 2000 < (last - boot_ms) % 2**32 < 2**31:
            self.invalidate(disconnected=True)
        self.telemetry_boot_ms = boot_ms

    def heartbeat(self, mode, armed):
        now = time.monotonic()
        if self.heartbeat_at is not None and now - self.heartbeat_at >= 5:
            self.invalidate(disconnected=True)
        if mode != self.mode or armed != self.armed:
            self.invalidate()
        self.mode, self.armed, self.heartbeat_at = mode, armed, now

    def landed(self, on_ground):
        if not on_ground:
            if self.ground_at is not None:
                self.invalidate()
            self.ground_at = None
            return
        self.ground_at = time.monotonic()

    def _grounded(self, now):
        return (self.armed is False and self.mode > 0 and self.ground_at is not None
                and self.heartbeat_at is not None and 0 <= now - self.ground_at < 5
                and 0 <= now - self.heartbeat_at < 5)

    def tick(self, mav, source):
        now = time.monotonic()
        if self.heartbeat_at is not None and now - self.heartbeat_at >= 5:
            self.invalidate(disconnected=True)
        if not self._grounded(now):
            return
        if self.metadata.parser is None:
            self.metadata.tick(mav, source, now)
        elif now >= self.refresh_at:
            self.refresh_at = now + self.interval
            mav.mav.command_long_send(*source, 401, 0, 0, 0, 0, 0, 0, 0, 0)

    def observe(self, msg, source, mav):
        if msg.get_type() == 'FILE_TRANSFER_PROTOCOL':
            self.metadata.ftp_reply(msg, source, mav)
            return
        frame = decode_event_frame(msg.get_msgbuf())
        if frame is None or frame[1] != source:
            return
        message_id, _, values = frame
        if message_id == 397:
            self.metadata.announcement(*values, source, mav)
        elif message_id == 411:
            sequence, flags = values
            if flags & 1:
                self.invalidate(disconnected=True)
                return
            if self.last_sequence is not None and 0 < (sequence - self.last_sequence) % 65536 < 32768:
                self.invalidate()
                self.last_sequence = sequence
        elif message_id == 413:
            if values[2:4] == (mav.mav.srcSystem, mav.mav.srcComponent):
                self.invalidate()
        elif message_id == 410:
            self._event(values, mav)

    def _event(self, values, mav):
        event_id, boot_ms, sequence, destination_component, destination_system, levels, arguments = values
        if destination_system not in (0, mav.mav.srcSystem) or destination_component not in (0, mav.mav.srcComponent):
            return
        if self.last_sequence is not None:
            distance = (sequence - self.last_sequence) % 65536
            backwards_boot = ((self.last_boot_ms - boot_ms) % (1 << 32)
                              if self.last_boot_ms is not None else 0)
            if 5000 < backwards_boot < (1 << 31) and boot_ms < 10000:
                self.invalidate(disconnected=True)
                return
            if distance == 0 or distance >= 32768 or 0 < backwards_boot < (1 << 31):
                return
            if distance != 1:
                self.invalidate()
        self.last_sequence, self.last_boot_ms = sequence, boot_ms
        now = time.monotonic()
        if self.metadata.parser is None or not self._grounded(now):
            return
        try:
            parsed = self.metadata.parser.parse(event_id, arguments)
            if parsed is None:
                if self.pending is not None:
                    self.invalidate()
                return
            self._consume(parsed, levels & 15, int(now * 1000))
        except (ValueError, TypeError, KeyError, IndexError, AttributeError, struct.error) as exc:
            LOG.debug('Invalid PX4 Events report: %s', exc)
            self.invalidate()

    def _consume(self, event, level, now_ms):
        group, kind = event.group(), event.type()
        if (group, kind) == ('arming_check', 'summary'):
            # PX4 currently emits one complete report as chunk zero followed
            # by its reasons and matching health summary.
            chunk, _, _, can_arm, _ = (event.argument_value(i) for i in range(5))
            self.pending = (can_arm, [], now_ms) if chunk == 0 else None
        elif (group, kind) == ('health', 'summary'):
            if self.pending is not None and event.argument_value(0) == 0 and now_ms - self.pending[2] < 1000:
                bits, reasons, _ = self.pending
                self.number += 1
                self.report = CompletedReport(now_ms, self.number, self.mode, bits, tuple(reasons))
            self.pending = None
        elif self.pending is not None and group in ('arming_check', 'health') and level < len(SEVERITIES):
            message = event.message().strip()[:512]
            if message and len(self.pending[1]) < 24:
                self.pending[1].append((event.argument_value(0), message, event.description()[:1024], SEVERITIES[level]))

    def snapshot(self, current_mode, *, now=None):
        now = time.monotonic() if now is None else now
        epoch = f'{self.identity}:{self.generation}'
        report = self.report
        if report is None or report.mode != current_mode or not self._grounded(now):
            return epoch, []
        remaining = report.observed_ms + VALID_MS - int(now * 1000)
        if remaining <= 0:
            return epoch, []
        reports = []
        for mode in dict.fromkeys((current_mode, PX4_TAKEOFF_CUSTOM_MODE)):
            group = self.metadata.groups.get(mode)
            if group is None:
                continue
            verdict = bool(report.can_arm & (1 << group))
            reasons = [dict(message=text, description=detail, severity=severity)
                       for mask, text, detail, severity in report.problems if mask & (1 << group)]
            revision = hashlib.sha256(json.dumps([mode, verdict, reasons], ensure_ascii=False).encode()).hexdigest()[:24]
            reports.append(dict(source='px4_events', mode=describe_px4_custom_mode(mode),
                custom_mode=mode, can_arm=verdict, mode_problems=reasons, remaining_valid_ms=remaining,
                sample=report.number, revision=revision))
        current_epoch = f'{self.identity}:{self.generation}'
        return (epoch, reports) if epoch == current_epoch else (current_epoch, [])
