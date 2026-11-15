"""One supervisory state owner per aircraft, with bounded stream/HTTP recovery.

The node's state WebSocket is preferred only after a valid, identity-matching
sample. HTTP remains sequential and independent while a stream is connecting,
unsupported or silent. Transport receipt never rewrites native sample clocks.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import random

import aiohttp
import httpx

from mds_logging import get_logger
from src.drone_api_routes import DRONE_STATE_ROUTE, DRONE_WS_STATE_ROUTE


logger = get_logger('telemetry')


class _InvalidTelemetry(ValueError):
    pass


def _identity(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    text = str(value).strip()
    return str(int(text)) if text.isdecimal() else text or None


def _valid_sample(data, expected_hw_id, *, stream):
    if not isinstance(data, dict) or not data or 'error' in data:
        raise _InvalidTelemetry('Drone telemetry must be a state object, not an error receipt')
    identity = data.get('hw_id', data.get('hw_ID'))
    if identity is None:
        # Older HTTP nodes omitted hw_id. Keep their configured endpoint binding,
        # but do not promote an unidentified WebSocket to the primary transport.
        if stream or 'hw_id' in data or 'hw_ID' in data:
            raise _InvalidTelemetry('Drone telemetry hardware identity is missing')
    elif _identity(identity) != _identity(expected_hw_id):
        raise _InvalidTelemetry(f'Drone telemetry hardware identity does not match H{expected_hw_id}')
    for name in ('update_time', 'timestamp'):
        value = data.get(name)
        if isinstance(value, bool):
            continue
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(timestamp) and timestamp > 0:
            return data
    raise _InvalidTelemetry('Drone telemetry has no valid sample timestamp')


@dataclass
class _PeerState:
    stream_valid: bool = False
    stream_revision: int = 0
    changed: asyncio.Event = field(default_factory=asyncio.Event)


class FleetTelemetryPoller:
    def __init__(self, params, targets, publish, *, client=None, ws_connect=None):
        self.params, self.targets, self.publish = params, targets, publish
        self.client = client
        self.limit = max(1, int(getattr(params, 'GCS_FLEET_RPC_CONCURRENCY', 48)))
        self.slots = asyncio.Semaphore(self.limit)
        # Handshake attempts must not occupy the HTTP pool or hold capacity for
        # the lifetime of a connected stream. Active sockets are roster-bounded.
        self.probes = asyncio.Semaphore(self.limit)
        self.interval = max(0.01, float(params.telem_poll_interval))
        self.request_timeout = float(params.GCS_TELEMETRY_REQUEST_TIMEOUT_SEC)
        self.connect_timeout = max(0.01, float(getattr(params, 'GCS_TELEMETRY_WS_CONNECT_TIMEOUT_SEC', 2.0)))
        self.idle_timeout = max(0.01, float(getattr(params, 'GCS_TELEMETRY_WS_IDLE_TIMEOUT_SEC', 3.0)))
        self.ws_connect = ws_connect

    def current(self):
        by_id = {_identity(d['hw_id']): d for d in self.targets()}
        return {(hw_id, d['ip']): d for hw_id, d in by_id.items()}

    def _publish(self, key, data, error=None):
        # A removed/reassigned endpoint's late reply cannot overwrite its
        # replacement. Resolve mutable slot/config metadata at publication time.
        current = self.current().get(key)
        if current is not None:
            self.publish(current, data, error)

    def _retry_delay(self, failures, *, base=None):
        delay = min(30.0, (self.interval if base is None else base) * 2 ** min(failures, 5))
        return min(30.0, delay * random.uniform(0.8, 1.2))

    @staticmethod
    async def _wait_for_change(state, delay=None):
        try:
            await asyncio.wait_for(state.changed.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        finally:
            state.changed.clear()

    async def _http_worker(self, key, drone, state):
        failures = 0
        while key in self.current():
            if state.stream_valid:
                failures = 0
                await self._wait_for_change(state)
                continue
            data, error = None, None
            revision = state.stream_revision
            try:
                async with self.slots:
                    async with asyncio.timeout(self.request_timeout):
                        response = await self.client.get(
                            f"http://{drone['ip']}:{self.params.drone_api_port}{DRONE_STATE_ROUTE}",
                            timeout=self.request_timeout,
                        )
                    response.raise_for_status()
                    data = _valid_sample(response.json(), key[0], stream=False)
                failures = 0
            except (httpx.HTTPError, TimeoutError, ValueError) as exc:
                failures += 1
                error = f'Unable to obtain valid drone telemetry: {exc or type(exc).__name__}'
            # A fallback started before stream takeover may finish later. It
            # cannot overwrite either a newer stream sample or its failure state.
            if state.stream_valid or revision != state.stream_revision:
                failures = 0
                continue
            self._publish(key, data if error is None else None, error)
            await self._wait_for_change(state, self.interval if not failures else self._retry_delay(failures))

    async def _stream_worker(self, key, drone, state):
        failures = 0
        last_issue = None
        loop = asyncio.get_running_loop()
        while key in self.current():
            socket = None
            retry_delay = None
            try:
                async with self.probes:
                    socket = await asyncio.wait_for(self.ws_connect(
                        f"http://{drone['ip']}:{self.params.drone_api_port}{DRONE_WS_STATE_ROUTE}",
                        max_msg_size=1024 * 1024,
                    ), timeout=self.connect_timeout)
                deadline = loop.time() + self.idle_timeout
                while key in self.current():
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise TimeoutError('No valid drone state before stream idle deadline')
                    try:
                        payload = await asyncio.wait_for(socket.receive_json(), timeout=remaining)
                    except ValueError:
                        # Bad JSON/frames do not keep an otherwise dead stream
                        # alive. Only accepted state moves the valid-data clock.
                        continue
                    except TypeError as exc:
                        raise _InvalidTelemetry('Drone state stream closed without a state sample') from exc
                    data = _valid_sample(payload, key[0], stream=True)
                    deadline = loop.time() + self.idle_timeout
                    failures = 0
                    last_issue = None
                    state.stream_revision += 1
                    state.stream_valid = True
                    state.changed.set()
                    self._publish(key, data)
            except (aiohttp.ClientError, OSError, TimeoutError, _InvalidTelemetry) as exc:
                failures += 1
                # HTTP-only old companions need bounded capability probes, not
                # a tight handshake/error loop. HTTP continues independently.
                if isinstance(exc, aiohttp.WSServerHandshakeError) and exc.status in (404, 405, 426):
                    retry_delay = 30.0
                issue = f'{type(exc).__name__}: {exc}'
                if issue != last_issue:
                    report = logger.warning if isinstance(exc, _InvalidTelemetry) else logger.debug
                    report('H%s state stream unavailable; HTTP fallback remains active: %s', key[0], issue)
                    last_issue = issue
            finally:
                state.stream_valid = False
                state.changed.set()
                if socket is not None:
                    try:
                        await asyncio.wait_for(socket.close(), timeout=1.0)
                    except (aiohttp.ClientError, OSError, TimeoutError):
                        pass
            if key not in self.current():
                return
            await asyncio.sleep(retry_delay if retry_delay is not None else self._retry_delay(failures, base=1.0))

    async def _worker(self, key, drone):
        state = _PeerState()
        tasks = [asyncio.create_task(self._stream_worker(key, drone, state)),
                 asyncio.create_task(self._http_worker(key, drone, state))]
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        workers = {}
        owned = self.client is None
        ws_session = None
        if owned:
            self.client = httpx.AsyncClient(
                limits=httpx.Limits(max_connections=self.limit, max_keepalive_connections=self.limit),
                trust_env=False,
            )
        if self.ws_connect is None:
            # One socket per configured aircraft, with separately bounded probe
            # concurrency. A permanent connection must not exhaust a global
            # connector limit and prevent the remainder of a 100+ fleet joining.
            ws_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=0), trust_env=False)
            self.ws_connect = ws_session.ws_connect
        try:
            while True:
                targets = self.current()
                removed = [key for key in workers if key not in targets]
                for key in removed:
                    workers[key].cancel()
                if removed:
                    await asyncio.gather(*(workers.pop(key) for key in removed), return_exceptions=True)
                for key, drone in targets.items():
                    if key not in workers:
                        workers[key] = asyncio.create_task(self._worker(key, drone))
                    elif workers[key].done():
                        # Surface programmer/callback failures rather than
                        # silently abandoning an aircraft's monitoring task.
                        workers[key].result()
                        workers[key] = asyncio.create_task(self._worker(key, drone))
                await asyncio.sleep(min(0.25, self.interval))
        finally:
            for task in workers.values():
                task.cancel()
            await asyncio.gather(*workers.values(), return_exceptions=True)
            if ws_session is not None:
                await ws_session.close()
                self.ws_connect = None
            if owned:
                await self.client.aclose()
                self.client = None
