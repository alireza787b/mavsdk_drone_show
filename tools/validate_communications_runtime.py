#!/usr/bin/env python3
"""Bounded, disposable real-network communications acceptance (no PX4/actuation).

Creates loopback-only synthetic companions, the production FleetTelemetryPoller
and LatestObservationPublisher, and real HTTP/WebSocket clients. It never loads
deployment configuration, starts an aircraft or touches host network settings.
The CLI process caps address space at 512 MiB by default. JSON payload counts
exclude TCP/HTTP/WS framing and must not be presented as radio-link throughput.

Example (run on the designated validation host):
  python tools/validate_communications_runtime.py --output-dir /tmp/comms-evidence
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import os
import resource
import socket
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for location in (REPO_ROOT, REPO_ROOT / "gcs-server"):
    if str(location) not in sys.path:
        sys.path.insert(0, str(location))


@dataclass(frozen=True)
class ValidationOptions:
    aircraft: int = 100
    clients: int = 5
    baseline_seconds: float = 2.0
    steady_seconds: float = 3.0
    interval: float = 0.1
    total_timeout: float = 60.0

    def validate(self):
        if not 2 <= self.aircraft <= 200 or not 2 <= self.clients <= 10:
            raise ValueError("Use 2..200 synthetic aircraft and 2..10 clients")
        if not 0.05 <= self.interval <= 1 or not 0.1 <= self.baseline_seconds <= 15 or not 0.1 <= self.steady_seconds <= 15:
            raise ValueError("Intervals/durations exceed the bounded harness limits")
        if not 10 <= self.total_timeout <= 180:
            raise ValueError("The total deadline must be 10..180 seconds")


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(len(ordered) * fraction) - 1))]


def distribution(values):
    return {"count": len(values), "min": min(values) if values else None,
            "p50": percentile(values, 0.5), "p95": percentile(values, 0.95),
            "max": max(values) if values else None}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


async def wait_until(predicate, *, timeout=8.0, description="condition"):
    try:
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.02)
    except TimeoutError as exc:
        raise TimeoutError(f"Timed out waiting for {description}") from exc


async def bounded_close(ws, *, code=1001):
    try:
        await asyncio.wait_for(ws.close(code=code), timeout=1)
    except (TimeoutError, ConnectionError, RuntimeError):
        pass


def native_sample(hw_id):
    """A synthetic FC sample, dated only at its synthetic source."""
    now = int(time.time() * 1000)
    return {
        "hw_id": str(hw_id), "pos_id": hw_id, "state": 0, "mission": 0, "last_mission": 0,
        "position_lat": 35 + hw_id * 0.00001, "position_long": -120, "position_alt": 120,
        "velocity_north": 0, "velocity_east": 0, "velocity_down": 0, "yaw": 0,
        "battery_voltage": 16, "follow_mode": 0, "update_time": now, "timestamp": now,
        "flight_mode": 65536, "base_mode": 0, "system_status": 3,
        "is_armed": False, "is_ready_to_arm": False, "landed_state": None,
        "hdop": 0.8, "vdop": 1, "gps_fix_type": 3, "satellites_visible": 12,
        "ip": f"127.0.0.{hw_id}", "telemetry_available": True,
    }


class SyntheticCompanions:
    def __init__(self, options):
        self.options = options
        self.modes = defaultdict(lambda: "http_only")
        self.counts = Counter()
        self.connections = {}
        self.active_http = self.max_http = 0
        self.max_ws = 0
        self.http_gate = asyncio.Event()
        self.fence_armed = False
        self.old_http_entered = asyncio.Event()
        self.old_http_release = asyncio.Event()
        self.old_http_completed = asyncio.Event()
        self.runner = None

    @staticmethod
    def identity(request):
        return int(request.transport.get_extra_info("sockname")[0].rsplit(".", 1)[1])

    async def state(self, request):
        from aiohttp import web
        hw_id = self.identity(request)
        self.active_http += 1
        self.max_http = max(self.max_http, self.active_http)
        data = {**native_sample(hw_id), "_transport": "http"}
        delayed = hw_id == 1 and self.fence_armed
        if delayed:
            self.fence_armed = False
            data["_delayed_http"] = True
            self.old_http_entered.set()
        try:
            await self.http_gate.wait()
            if delayed:
                await self.old_http_release.wait()
            await asyncio.sleep(0.02)
            encoded = json.dumps(data, separators=(",", ":"))
            self.counts["http_requests"] += 1
            self.counts["http_payload_bytes"] += len(encoded.encode())
            if delayed:
                self.old_http_completed.set()
            return web.Response(text=encoded, content_type="application/json")
        finally:
            self.active_http -= 1

    async def state_stream(self, request):
        from aiohttp import web
        hw_id = self.identity(request)
        self.counts["ws_probes"] += 1
        if self.modes[hw_id] == "http_only":
            raise web.HTTPNotFound()
        if self.modes[hw_id] == "drop":
            raise web.HTTPServiceUnavailable()
        ws = web.WebSocketResponse(heartbeat=2)
        await ws.prepare(request)
        self.connections[hw_id] = ws
        self.max_ws = max(self.max_ws, len(self.connections))
        try:
            if hw_id == 1 and not self.old_http_release.is_set():
                await asyncio.wait_for(self.old_http_entered.wait(), 5)
            while not ws.closed:
                if self.modes[hw_id] == "drop":
                    await ws.close(code=1012)
                    break
                if self.modes[hw_id] != "silent":
                    data = {**native_sample(hw_id), "_transport": "ws"}
                    encoded = json.dumps(data, separators=(",", ":"))
                    await ws.send_str(encoded)
                    self.counts["ws_messages"] += 1
                    self.counts["ws_payload_bytes"] += len(encoded.encode())
                await asyncio.sleep(self.options.interval)
        except (ConnectionError, RuntimeError):
            pass
        finally:
            if self.connections.get(hw_id) is ws:
                self.connections.pop(hw_id, None)
        return ws

    async def start(self):
        from aiohttp import web
        from src.drone_api_routes import DRONE_STATE_ROUTE, DRONE_WS_STATE_ROUTE
        app = web.Application()
        app.router.add_get(DRONE_STATE_ROUTE, self.state)
        app.router.add_get(DRONE_WS_STATE_ROUTE, self.state_stream)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=1)
        await self.runner.setup()
        first = web.TCPSite(self.runner, "127.0.0.1", 0)
        await first.start()
        self.port = first._server.sockets[0].getsockname()[1]
        for hw_id in range(2, self.options.aircraft + 1):
            await web.TCPSite(self.runner, f"127.0.0.{hw_id}", self.port).start()

    async def close(self):
        self.http_gate.set()
        self.old_http_release.set()
        await asyncio.gather(*(bounded_close(ws) for ws in list(self.connections.values())), return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()


class AiohttpObservationSocket:
    """ASGI-shaped adapter: exercises the production publication/cleanup loop."""
    def __init__(self, request, ws, counts):
        self.request, self.ws, self.counts = request, ws, counts
        self.query_params = request.query
        self.headers, self.cookies = request.headers, request.cookies
        self.client = SimpleNamespace(host="127.0.0.1")
        self.url = SimpleNamespace(path="/ws/telemetry", scheme="ws", hostname="127.0.0.1", port=None)

    async def receive(self):
        from aiohttp import WSMsgType
        message = await self.ws.receive()
        if message.type in {WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.CLOSING, WSMsgType.ERROR}:
            return {"type": "websocket.disconnect"}
        return {"type": "websocket.receive", "text": message.data}

    async def send_text(self, encoded):
        await self.ws.send_str(encoded)
        self.counts["fleet_ws_messages"] += 1
        self.counts["fleet_ws_payload_bytes"] += len(encoded.encode())

    async def close(self, code=1000, reason=""):
        self.counts[f"close_{code}"] += 1
        await self.ws.close(code=code, message=reason.encode())


class FleetObservationFixture:
    def __init__(self, options, rows):
        from observation_stream import LatestObservationPublisher
        from schemas import TelemetryResponse
        from overview_display_policy import resolve_overview_display_policy
        self.options, self.rows = options, rows
        self.counts = Counter()
        self.sockets = set()
        self.publishers = []
        self.inject_schema_once = False
        self.runner = None
        def build():
            self.counts["fleet_builds"] += 1
            return TelemetryResponse(telemetry=dict(self.rows), total_drones=len(self.rows),
                online_drones=len(self.rows), timestamp=int(time.time() * 1000),
                display_policy=resolve_overview_display_policy(None)).model_dump(mode="json")
        self.factory = lambda: LatestObservationPublisher(build,
            lambda body: {"type": "telemetry", "timestamp": body["timestamp"], "data": body["telemetry"]},
            interval=options.interval, modern_fields=lambda body: {"display_policy": body["display_policy"]})
        self.new_epoch()

    def new_epoch(self):
        self.publisher = self.factory()
        self.publishers.append(self.publisher)

    async def telemetry(self, request):
        from aiohttp import web
        self.counts["fleet_http_requests"] += 1
        encoded = json.dumps(self.publisher.current().http_body(), separators=(",", ":"))
        self.counts["fleet_http_payload_bytes"] += len(encoded.encode())
        return web.Response(text=encoded, content_type="application/json")

    async def telemetry_stream(self, request):
        from aiohttp import web
        from observation_stream import serve_observations
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self.sockets.add(ws)
        # A slow subscriber negotiates a bounded slower delivery cadence,
        # exercising latest-only coalescing without relying on platform-specific
        # TCP autotuning to fill buffers within an arbitrary short test window.
        interval = max(0.4, self.options.interval * 5) if request.query.get("slow") == "1" else self.options.interval
        try:
            if self.inject_schema_once and request.query.get("client") == "0":
                self.inject_schema_once = False
                invalid = json.loads(self.publisher.current().versioned_json)
                invalid["protocol_version"] = 2
                await ws.send_json(invalid)
                self.counts["injected_schema_frames"] += 1
            await serve_observations(AiohttpObservationSocket(request, ws, self.counts), self.publisher,
                interval=interval, auth_context={"kind": "disabled"})
        finally:
            self.sockets.discard(ws)
        return ws

    async def start(self):
        from aiohttp import web
        app = web.Application()
        app.router.add_get("/api/v1/fleet/telemetry", self.telemetry)
        app.router.add_get("/ws/telemetry", self.telemetry_stream)
        self.runner = web.AppRunner(app, access_log=None, shutdown_timeout=1)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"

    async def close(self):
        await asyncio.gather(*(bounded_close(ws) for ws in list(self.sockets)), return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()


class FleetClient:
    def __init__(self, index, session, fixture, samples, phase):
        self.index, self.session, self.fixture = index, session, fixture
        self.samples, self.phase = samples, phase
        self.counts = Counter()
        self.epochs = set()
        self.cursor = None
        self.ws = None
        self.running = True
        self.slow = False

    async def run(self):
        from aiohttp import ClientError, WSMsgType
        from pydantic import ValidationError
        from schemas import TelemetrySnapshotStreamMessage
        while self.running:
            try:
                url = f"{self.fixture.base}/ws/telemetry?protocol_version=1&client={self.index}&slow={int(self.slow)}"
                async with self.session.ws_connect(url, max_msg_size=8 * 1024 * 1024) as ws:
                    self.ws = ws
                    self.counts["connections"] += 1
                    while self.running:
                        if self.slow:
                            await asyncio.sleep(max(0.4, self.fixture.options.interval * 5))
                        message = await ws.receive(timeout=3)
                        if message.type != WSMsgType.TEXT:
                            break
                        self.counts["payload_bytes"] += len(message.data.encode())
                        try:
                            value = json.loads(message.data)
                            TelemetrySnapshotStreamMessage.model_validate(value)
                        except (ValueError, ValidationError):
                            self.counts["invalid_frames"] += 1
                            continue
                        previous = self.cursor
                        cursor = (value["stream_id"], value["sequence"])
                        if previous and previous[0] == cursor[0]:
                            require(cursor[1] >= previous[1], "A same-epoch observation regressed")
                            self.counts["coalesced_generations"] += max(0, cursor[1] - previous[1] - 1)
                        self.cursor = cursor
                        self.epochs.add(cursor[0])
                        self.counts["valid_frames"] += 1
                        now_ms = int(time.time() * 1000)
                        ages = [now_ms - row["timestamp"] for row in value["data"].values()]
                        self.samples.append({"elapsed_sec": time.monotonic() - self.phase["started"],
                            "phase": self.phase["name"], "client": self.index, "aircraft": len(ages),
                            "sample_age_min_ms": min(ages) if ages else 0,
                            "sample_age_p95_ms": percentile(ages, 0.95) if ages else 0,
                            "payload_bytes": len(message.data.encode()), "sequence": cursor[1],
                            "stream_id": cursor[0]})
            except (ClientError, TimeoutError, ConnectionError):
                self.counts["transport_failures"] += 1
            finally:
                self.ws = None
            if self.running:
                await asyncio.sleep(0.05)


def cpu_seconds():
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return usage.ru_utime + usage.ru_stime


async def run_validation(options: ValidationOptions) -> dict[str, Any]:
    """Run isolated network evidence; safe to import without starting anything."""
    import aiohttp
    from fleet_telemetry import FleetTelemetryPoller
    options.validate()
    # Only this disposable harness process uses the open lab observation posture.
    # Preserve any caller's environment (including when called by pytest).
    auth_names = ("MDS_AUTH_ENABLED", "MDS_API_AUTH_ENABLED")
    auth_before = {name: os.environ.get(name) for name in auth_names}
    for name in auth_names:
        os.environ[name] = "false"
    source = SyntheticCompanions(options)
    rows, samples, phases, checks = {}, [], [], {}
    phase = {"name": "warmup", "started": time.monotonic()}
    fixture = FleetObservationFixture(options, rows)
    tasks, clients = [], []
    publications = Counter()
    published_by_node = Counter()
    old_http_published = []
    max_pending = peak_tasks = 0
    poller_task = None
    session = None
    failure = None
    background_failures = []
    def publish(drone, data, error):
        hw_id = str(drone["hw_id"])
        if data is not None:
            rows[hw_id] = data
            publications[data.get("_transport", "unknown")] += 1
            published_by_node[(hw_id, data.get("_transport"))] += 1
            if data.get("_delayed_http"):
                old_http_published.append(hw_id)
        else:
            publications["errors"] += 1
    def start_poller():
        params = SimpleNamespace(drone_api_port=source.port, telem_poll_interval=options.interval,
            GCS_FLEET_RPC_CONCURRENCY=options.aircraft, GCS_TELEMETRY_REQUEST_TIMEOUT_SEC=3,
            GCS_TELEMETRY_WS_CONNECT_TIMEOUT_SEC=2, GCS_TELEMETRY_WS_IDLE_TIMEOUT_SEC=0.35)
        return asyncio.create_task(FleetTelemetryPoller(params,
            lambda: [{"hw_id": str(i), "ip": f"127.0.0.{i}"} for i in range(1, options.aircraft + 1)], publish).run())
    async def measure(name, seconds):
        nonlocal max_pending, peak_tasks
        phase["name"] = name
        started, cpu = time.monotonic(), cpu_seconds()
        before_source, before_fixture = source.counts.copy(), fixture.counts.copy()
        until = started + seconds
        while time.monotonic() < until:
            for task in [*tasks, poller_task]:
                if task is not None and task.done() and not task.cancelled() and task.exception() is not None:
                    raise RuntimeError(f"Communications background task failed: {task.exception()}")
            max_pending = max(max_pending, *(q.qsize() for p in fixture.publishers for q in p.queues), 0)
            peak_tasks = max(peak_tasks, len(asyncio.all_tasks()))
            await asyncio.sleep(0.02)
        elapsed = time.monotonic() - started
        phases.append({"name": name, "duration_sec": elapsed, "cpu_seconds": cpu_seconds() - cpu,
            "source_counts": dict(source.counts - before_source), "fleet_counts": dict(fixture.counts - before_fixture)})
    try:
        async with asyncio.timeout(options.total_timeout):
            await source.start()
            await fixture.start()
            session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=options.clients + 4), trust_env=False)
            clients = [FleetClient(i, session, fixture, samples, phase) for i in range(options.clients)]
            tasks = [asyncio.create_task(client.run()) for client in clients]
            poller_task = start_poller()
            await wait_until(lambda: source.active_http == options.aircraft, description="all concurrent HTTP requests")
            checks["concurrent_pooled_http_connections"] = source.max_http
            source.http_gate.set()
            await wait_until(lambda: len(rows) == options.aircraft and all(c.counts["valid_frames"] for c in clients))
            await measure("http_only_baseline", options.baseline_seconds)
            poller_task.cancel()
            await asyncio.gather(poller_task, return_exceptions=True)
            for hw_id in range(1, options.aircraft + 1):
                source.modes[hw_id] = "normal"
            source.fence_armed = True
            poller_task = start_poller()
            await wait_until(lambda: len(source.connections) == options.aircraft and published_by_node[("1", "ws")] > 0)
            source.old_http_release.set()
            await wait_until(source.old_http_completed.is_set)
            await asyncio.sleep(0.1)
            require(not old_http_published, "A delayed old HTTP response overwrote newer WebSocket evidence")
            checks["delayed_old_http_fenced"] = True
            require(source.max_ws == options.aircraft, "Not all companion sockets joined")
            checks["simultaneous_companion_websockets"] = source.max_ws
            await measure("ws_preferred_healthy", options.steady_seconds)

            # A slow real reader requests slower delivery. Intermediate state
            # coalesces instead of becoming a replay backlog. Separate publisher
            # tests inject a blocked write to prove the send deadline itself.
            slow = clients[-1]
            slow.slow = True
            await slow.ws.close()
            await wait_until(lambda: slow.counts["connections"] >= 2)
            await measure("slow_consumer", max(2.0, options.steady_seconds))
            await wait_until(lambda: slow.counts["coalesced_generations"] > 0 or fixture.counts["close_1013"] > 0,
                timeout=8, description="slow consumer backpressure")
            checks["slow_consumer_coalesced_or_bounded_close"] = (
                slow.counts["coalesced_generations"] > 0 or fixture.counts["close_1013"] > 0)
            require(checks["slow_consumer_coalesced_or_bounded_close"], "Slow consumer did not exercise bounded backpressure")

            phase["name"] = "silent_and_dropped_companion_ws"
            before_http = {i: published_by_node[(str(i), "http")] for i in (1, 2)}
            source.modes[1], source.modes[2] = "silent", "drop"
            if 2 in source.connections:
                await source.connections[2].close(code=1012)
            await wait_until(lambda: all(published_by_node[(str(i), "http")] > before_http[i] for i in (1, 2)))
            checks["silent_ws_http_healthy"] = True
            checks["dropped_ws_http_healthy"] = True
            await measure("silent_and_dropped_companion_ws", 0.5)
            before_ws = {i: published_by_node[(str(i), "ws")] for i in (1, 2)}
            source.modes[1] = source.modes[2] = "normal"
            await wait_until(lambda: all(published_by_node[(str(i), "ws")] > before_ws[i] for i in (1, 2)), timeout=10)
            checks["companion_stream_recovery"] = True

            # Real fleet HTTP remains available while clients reconnect. The
            # typed validator rejects an intentionally injected future schema.
            first = clients[0]
            fixture.inject_schema_once = True
            await first.ws.close()
            await wait_until(lambda: first.counts["invalid_frames"] >= 1 and first.ws is not None)
            async with session.get(f"{fixture.base}/api/v1/fleet/telemetry?protocol_version=1") as response:
                body = await response.json()
                require(response.status == 200 and len(body["telemetry"]) == options.aircraft, "HTTP snapshot was not healthy during reconnect")
            checks["future_schema_rejected"] = True
            checks["fleet_drop_reconnect_http_healthy"] = True
            previous_epoch = fixture.publisher.stream_id
            fixture.new_epoch()
            await asyncio.gather(*(bounded_close(ws, code=1012) for ws in list(fixture.sockets)))
            await wait_until(lambda: all(fixture.publisher.stream_id in c.epochs for c in clients), timeout=10)
            require(fixture.publisher.stream_id != previous_epoch, "Publisher epoch failed to change")
            checks["publisher_epoch_reconnect"] = True
            await measure("recovered_new_epoch", 0.5)
            require(max_pending <= 1, "Observation backlog exceeded its one-slot bound")
            checks["latest_only_backlog"] = True
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        for client in clients:
            client.running = False
        await asyncio.gather(*(bounded_close(c.ws) for c in clients if c.ws is not None), return_exceptions=True)
        for task in tasks:
            task.cancel()
        if tasks:
            outcomes = await asyncio.gather(*tasks, return_exceptions=True)
            background_failures.extend(str(value) for value in outcomes if isinstance(value, Exception))
        if poller_task:
            poller_task.cancel()
            outcomes = await asyncio.gather(poller_task, return_exceptions=True)
            background_failures.extend(str(value) for value in outcomes if isinstance(value, Exception))
        if session:
            await session.close()
        await fixture.close()
        await source.close()
        for name, previous in auth_before.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    checks["shutdown_clean"] = (not source.connections and not fixture.sockets
        and all(not p.queues and p.task is None for p in fixture.publishers)
        and all(task.done() for task in tasks) and (poller_task is None or poller_task.done()))
    if not checks["shutdown_clean"] and failure is None:
        failure = "Disposable communications resources did not shut down cleanly"
    if background_failures and failure is None:
        failure = "; ".join(background_failures)
    for item in phases:
        matching = [s["sample_age_p95_ms"] for s in samples if s["phase"] == item["name"] and s["client"] != options.clients - 1]
        item["fast_client_source_age_p95_ms"] = distribution(matching)
    return {
        "schema_version": 1, "success": failure is None, "failure": failure,
        "background_failures": background_failures,
        "scope": "Disposable loopback synthetic state only; no PX4, commands, auth qualification, browser or radio-throughput clearance",
        "options": options.__dict__, "checks": checks, "phases": phases,
        "source_totals": dict(source.counts), "fleet_totals": dict(fixture.counts),
        "client_totals": [dict(c.counts) for c in clients], "accepted_publications": dict(publications),
        "max_pending_per_subscriber": max_pending, "peak_async_tasks": peak_tasks,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024,
        "elapsed_sec": time.monotonic() - phase["started"], "samples": samples,
    }


def write_evidence(result, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = result["samples"]
    summary = {key: value for key, value in result.items() if key != "samples"}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    with (output_dir / "samples.csv").open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=("elapsed_sec", "phase", "client", "aircraft",
            "sample_age_min_ms", "sample_age_p95_ms", "payload_bytes", "sequence", "stream_id"))
        writer.writeheader()
        writer.writerows(samples)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--aircraft", type=int, default=100)
    parser.add_argument("--clients", type=int, default=5)
    parser.add_argument("--baseline-seconds", type=float, default=2)
    parser.add_argument("--steady-seconds", type=float, default=3)
    parser.add_argument("--total-timeout", type=float, default=60)
    parser.add_argument("--memory-limit-mb", type=int, default=512)
    args = parser.parse_args(argv)
    options = ValidationOptions(args.aircraft, args.clients, args.baseline_seconds, args.steady_seconds,
        total_timeout=args.total_timeout)
    options.validate()
    if not 128 <= args.memory_limit_mb <= 512:
        parser.error("Use a 128..512 MiB process memory limit")
    cap = args.memory_limit_mb * 1024 * 1024
    _, hard = resource.getrlimit(resource.RLIMIT_AS)
    resource.setrlimit(resource.RLIMIT_AS, (min(cap, hard) if hard != resource.RLIM_INFINITY else cap, hard))
    result = asyncio.run(run_validation(options))
    write_evidence(result, args.output_dir)
    print(json.dumps({"success": result["success"], "failure": result["failure"],
        "elapsed_sec": result["elapsed_sec"], "peak_rss_mib": result["peak_rss_mib"],
        "output_dir": str(Path(args.output_dir).resolve())}, sort_keys=True), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
