"""Read firmware-owned PX4 Events definitions with a bounded MAVLink FTP client."""

import json
import logging
import lzma
import secrets
import struct
import time
import zlib

from src.vendor.libevents_parse.parser import Parser

LOG = logging.getLogger(__name__)
HEADER = struct.Struct('<HBBBBBBI')
MAX_FILE = 1024 * 1024
FTP_PAYLOAD_SIZE = 251
READ_SIZE = FTP_PAYLOAD_SIZE - HEADER.size
COMPONENT_METADATA_ID = 397
META_EVENTS = 4
OPEN_READ, READ, TERMINATE = 4, 5, 1
ACK = 128


def _metadata_path(uri):
    if not isinstance(uri, str) or not uri.startswith('mftp://'):
        raise ValueError('Expected a flight-controller metadata URI')
    path = uri.removeprefix('mftp://')
    # The standard permits a component qualifier. This observer only trusts
    # definitions served by its bound autopilot component.
    if not path or ':' in path or '\0' in path or '..' in path.split('/') or len(path.encode()) > READ_SIZE:
        raise ValueError('Invalid flight-controller metadata path')
    return path


def _document(data, path, expected_crc):
    def crc(payload):
        return zlib.crc32(payload, 0xffffffff) ^ 0xffffffff

    wire_crc = crc(data)
    if path.endswith(('.xz', '.lzma')):
        decoder = lzma.LZMADecompressor(memlimit=80 * 1024 * 1024)
        data = decoder.decompress(data, max_length=MAX_FILE)
        if not decoder.eof:
            raise ValueError('PX4 metadata exceeded its size limit')
    # COMPONENT_METADATA on PX4 reports the general JSON checksum before
    # compression. The nested Events metadata advertises the file checksum.
    if expected_crc and expected_crc not in (wire_crc, crc(data)):
        raise ValueError(f'PX4 metadata checksum mismatch for {path}')
    return json.loads(data)


class EventMetadata:
    def __init__(self):
        self.reset()

    def reset(self):
        self.parser = None
        self.groups = {}
        self.stage = None
        self.request = None
        self.session = None
        self.next_request = 0.
        self.sequence = secrets.randbits(16)
        self.contents = bytearray()
        self.size = 0

    def tick(self, mav, source, now):
        if now < self.next_request:
            return
        if self.request is not None:
            self.terminate(mav, source)
        self.stage = 'general'
        self.next_request = now + 8
        mav.mav.command_long_send(*source, 512, 0, COMPONENT_METADATA_ID, 0, 0, 0, 0, 0, 0)

    def _send(self, mav, source, opcode, *, size=0, data=b'', offset=0):
        self.sequence = (self.sequence + 1) % 65536
        packet = HEADER.pack(self.sequence, self.session or 0, opcode, size, 0, 0, 0, offset) + data
        mav.mav.file_transfer_protocol_send(0, *source, packet.ljust(FTP_PAYLOAD_SIZE, b'\0'))
        if opcode != TERMINATE:
            self.request = (opcode, offset)
            self.next_request = time.monotonic() + 2

    def terminate(self, mav, source):
        if self.session is not None:
            self._send(mav, source, TERMINATE)
        self.request = self.session = None

    def _open(self, uri, crc, mav, source):
        self.path = _metadata_path(uri)
        self.crc = crc
        self.contents.clear()
        data = self.path.encode()
        self._send(mav, source, OPEN_READ, size=len(data), data=data)

    def announcement(self, _boot_ms, crc, uri, source, mav):
        if self.stage != 'general' or self.request is not None or self.parser is not None:
            return
        try:
            self._open(uri.split(b'\0', 1)[0].decode(), crc, mav, source)
        except ValueError as exc:
            LOG.debug('PX4 Events metadata unavailable: %s', exc)

    def ftp_reply(self, msg, source, mav):
        if self.request is None or (msg.target_system, msg.target_component) != (mav.mav.srcSystem, mav.mav.srcComponent):
            return
        payload = bytes(msg.payload)
        if len(payload) < HEADER.size:
            return
        seq, session, opcode, size, req_op, _, _, offset = HEADER.unpack_from(payload)
        if self.request != (req_op, offset) or seq != (self.sequence + 1) % 65536 or size > READ_SIZE:
            return
        self.sequence = seq
        try:
            if opcode != ACK:
                raise ValueError(f'MAVFTP metadata read failed ({opcode})')
            data = payload[HEADER.size:HEADER.size + size].ljust(size, b'\0')
            if req_op == OPEN_READ:
                self.session = session
                self.size = struct.unpack('<I', data)[0]
                if not 0 < self.size < MAX_FILE:
                    raise ValueError('PX4 metadata exceeds the size limit')
            elif session != self.session or not size or len(self.contents) + size > self.size:
                raise ValueError('MAVFTP metadata response is inconsistent')
            else:
                self.contents.extend(data)
            if len(self.contents) == self.size:
                self.terminate(mav, source)
                self._loaded(source, mav)
            else:
                remaining = min(READ_SIZE, self.size - len(self.contents))
                self._send(mav, source, READ, size=remaining, offset=len(self.contents))
        except (ValueError, KeyError, TypeError, RuntimeError, struct.error, lzma.LZMAError) as exc:
            self.terminate(mav, source)
            self.next_request = time.monotonic() + 15
            LOG.debug('PX4 Events metadata unavailable: %s', exc)

    def _loaded(self, source, mav):
        document = _document(bytes(self.contents), self.path, self.crc)
        if self.stage == 'general':
            if document.get('version') != 1:
                raise ValueError('Unsupported PX4 component metadata version')
            entries = [entry for entry in document['metadataTypes'] if entry.get('type') == META_EVENTS]
            if len(entries) != 1:
                raise ValueError('PX4 component has no unique Events definition')
            self.stage = 'events'
            self._open(entries[0]['uri'], entries[0].get('fileCrc', 0), mav, source)
            return
        component = document['components'][str(source[1])]
        groups = {}
        for group, modes in component['navigation_mode_groups']['groups'].items():
            index = int(group)
            if not 0 <= index < 64:
                raise ValueError('Invalid PX4 Events mode group')
            for mode in modes:
                if type(mode) is not int or mode in groups:
                    raise ValueError('Ambiguous PX4 Events mode mapping')
                groups[mode] = index
        parser = Parser()
        parser.load_definitions(document)
        self.groups = groups
        self.contents.clear()
        self.parser = parser
        LOG.info('Native PX4 Events definitions loaded for system %s component %s', *source)
