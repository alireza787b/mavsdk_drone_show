#!/usr/bin/env python3
"""Read-only Drone Show UI evidence probe for isolated SITL builds.

The probe uses Chrome DevTools Protocol directly (no Playwright install is
needed on the constrained host). API requests are intercepted in the browser:
reads receive deterministic SITL fixtures and every write is rejected and
recorded. It captures Operate, Setup, launch review, and active monitoring in
desktop/mobile and dark/light combinations.
"""

from __future__ import annotations

import argparse
import base64
import json
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome


FLEET = [
    {"hw_id": 1, "pos_id": 1, "name": "NET-LEADER", "state": "STANDBY", "armed": False, "battery_percent": 92, "telemetry_fresh": True, "ready_to_arm": True, "readiness_summary": "Ready"},
    {"hw_id": 2, "pos_id": 2, "name": "NET-FOLLOWER", "state": "STANDBY", "armed": False, "battery_percent": 88, "telemetry_fresh": True, "ready_to_arm": True, "readiness_summary": "Ready"},
]


def svg_fixture() -> tuple[int, str, str]:
    svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 500">
      <rect width="1200" height="500" fill="#17202a"/>
      <g stroke="#2f4858" stroke-width="1">{grid}</g>
      <path d="M90 400 C260 340 270 90 480 120 S680 430 900 200 S1040 90 1120 70" fill="none" stroke="#36c2a0" stroke-width="7"/>
      <path d="M90 420 C280 380 350 160 520 180 S700 410 900 250 S1030 140 1120 100" fill="none" stroke="#f3b562" stroke-width="4" stroke-dasharray="12 8"/>
      <text x="34" y="42" fill="#e9f0f5" font-family="sans-serif" font-size="24">Trajectory preview · isolated SITL fixture</text>
    </svg>""".format(grid="".join(f'<path d="M{i * 100} 0V500"/>' for i in range(13)) + "".join(f'<path d="M0 {i * 100}H1200"/>' for i in range(6)))
    return 200, "image/svg+xml", svg


def json_fixture(path: str, active: bool) -> tuple[int, str, str]:
    if "/plots/" in path:
        return svg_fixture()
    if path == "/api/v1/auth/status":
        payload = {"dashboard_auth_enabled": False, "api_auth_enabled": False, "authenticated": True, "role": "operator"}
    elif path == "/api/v1/system/runtime-status":
        payload = {"mode": "SITL", "configured_mode": "SITL", "configured_sim_mode": True, "restart_required": False}
    elif path in {"/api/v1/system/health", "/ping", "/health"}:
        payload = {"status": "healthy"}
    elif path == "/api/v1/shows/skybrush/workspace":
        payload = {"package": {"available": True, "name": "Aurora Demo / rehearsal", "revision": "sitl-fixture-01", "drone_count": 2, "position_ids": [1, 2], "duration_ms": 192000, "max_altitude": 48}, "metrics": {"performance_metrics": {"max_velocity_ms": 4.2}}, "validation": {"validation_status": "PASS"}, "plots": {"filenames": ["combined_drone_paths.jpg"]}}
    elif path == "/api/v1/shows/skybrush":
        payload = {"drone_count": 2, "duration_ms": 192000, "duration_minutes": 3, "duration_seconds": 12, "max_altitude": 48}
    elif path == "/api/v1/shows/skybrush/plots":
        payload = {"filenames": ["combined_drone_paths.jpg", "drone_1_path.jpg", "drone_2_path.jpg"]}
    elif path == "/api/v1/shows/skybrush/metrics":
        payload = {"basic_metrics": {"max_altitude_details": {"value": 48}, "min_altitude_details": {"value": 3}, "max_distance_details": {"value": 36}}, "performance_metrics": {"max_velocity_details": {"value": 4.2}}}
    elif path == "/api/v1/shows/operation/status":
        payload = {"state": "active" if active else "idle", "phase": "executing" if active else "idle", "mission_type": 300 if active else None, "timestamp": int(time.time() * 1000), "fleet": [{**drone, "state": "OFFBOARD" if active else drone["state"], "armed": active} for drone in FLEET], "operation_target_ids": [1, 2], "command_id": "probe-show-001" if active else None, "command": {"executions": {"succeeded": 1 if active else 0, "failed": 0}}}
    elif path == "/api/v1/origin":
        payload = {"lat": 48.8566, "lon": 2.3522, "alt": 42.1}
    elif path == "/api/v1/origin/deviations":
        payload = {"deviations": {"1": {"status": "ok", "horizontal_m": 0.12, "vertical_m": 0.08}, "2": {"status": "ok", "horizontal_m": 0.18, "vertical_m": 0.1}}}
    elif path == "/api/v1/config/fleet":
        payload = FLEET
    elif path == "/api/v1/config/swarm":
        payload = {"version": 1, "assignments": [{"hw_id": 1, "follow": 0, "offset_x": 0, "offset_y": 0, "offset_z": 0, "frame": "ned"}, {"hw_id": 2, "follow": 1, "offset_x": 6, "offset_y": 0, "offset_z": 0, "frame": "ned"}]}
    elif path == "/api/v1/fleet/telemetry":
        payload = {"drones": FLEET}
    elif path in {"/api/v1/fleet/heartbeats", "/api/v1/fleet/node-boot-status", "/api/v1/fleet/network-status", "/api/v1/shows/custom"}:
        payload = {"drones": []} if path != "/api/v1/shows/custom" else {"drone_count": 0}
    elif path in {"/api/v1/commands/recent", "/api/v1/commands/active"}:
        payload = {"commands": []}
    elif path == "/api/v1/git/status":
        payload = {"gcs_status": {"status": "clean", "uncommitted_changes": []}}
    else:
        payload = {}
    return 200, "application/json", json.dumps(payload)


def install_fetch_mock(client: CDPClient, active: dict[str, bool], writes: list[dict[str, str]]) -> None:
    original_handler = client._handle_event

    def handle_event(message: dict) -> None:
        if message.get("method") != "Fetch.requestPaused":
            original_handler(message)
            return
        params = message.get("params", {})
        request = params.get("request", {})
        url = urlsplit(request.get("url", ""))
        method = request.get("method", "GET").upper()
        request_id = params.get("requestId")
        if not (url.port == 5030 or url.path.startswith("/api/")):
            client.next_id += 1
            client.ws.send(json.dumps({"id": client.next_id, "method": "Fetch.continueRequest", "params": {"requestId": request_id}}))
            return
        if method not in {"GET", "HEAD", "OPTIONS"}:
            writes.append({"method": method, "path": url.path})
            status, content_type, body = 409, "application/json", json.dumps({"detail": "Probe: writes disabled"})
        else:
            status, content_type, body = json_fixture(url.path, active["value"])
        client.next_id += 1
        client.ws.send(json.dumps({"id": client.next_id, "method": "Fetch.fulfillRequest", "params": {"requestId": request_id, "responseCode": status, "responseHeaders": [{"name": "Content-Type", "value": content_type}, {"name": "Cache-Control", "value": "no-store"}], "body": base64.b64encode(body.encode()).decode()}}))

    client._handle_event = handle_event
    # Intercept every request because Chrome's URL-pattern parser is not
    # consistent across versions for wildcard ports. Non-API requests are
    # immediately continued; only the isolated GCS surface is mocked.
    client.command("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})


def install_browser_mock(client: CDPClient, fleet_size: int = 2, *, extra_fixtures: dict | None = None) -> None:
    """Mock axios' browser transports before the React bundle is evaluated.

    This avoids depending on Chrome's Fetch wildcard behavior, which changed
    between the versions installed on the VPS and the build host.
    """
    source = r'''(() => {
      window.__mdsProbeActive = false;
      window.__mdsProbeWrites = [];
      const fleet = [
        {hw_id: 1, pos_id: 1, name: 'NET-LEADER', state: 'STANDBY', armed: false, battery_percent: 92, telemetry_fresh: true, ready_to_arm: true, readiness_summary: 'Ready'},
        {hw_id: 2, pos_id: 2, name: 'NET-FOLLOWER', state: 'STANDBY', armed: false, battery_percent: 88, telemetry_fresh: true, ready_to_arm: true, readiness_summary: 'Ready'},
      ];
      const json = (value) => ({status: 200, type: 'application/json', body: JSON.stringify(value)});
      const fixture = (path) => {
        const active = Boolean(window.__mdsProbeActive);
        if (path === '/api/v1/auth/status') return json({dashboard_auth_enabled: false, api_auth_enabled: false, authenticated: true, role: 'operator'});
        if (path === '/api/v1/system/runtime-status') return json({mode: 'SITL', configured_mode: 'SITL', configured_sim_mode: true, restart_required: false});
        if (path === '/api/v1/system/health' || path === '/ping' || path === '/health') return json({status: 'healthy'});
        if (path === '/api/v1/shows/skybrush/workspace') return json({package: {available: true, name: 'Aurora Demo / rehearsal', revision: 'sitl-fixture-01', drone_count: 2, position_ids: [1, 2], duration_ms: 192000, max_altitude: 48}, metrics: {performance_metrics: {max_velocity_ms: 4.2}}, validation: {validation_status: 'PASS'}, plots: {filenames: ['combined_drone_paths.jpg']}});
        if (path === '/api/v1/shows/skybrush') return json({drone_count: 2, duration_ms: 192000, duration_minutes: 3, duration_seconds: 12, max_altitude: 48});
        if (path === '/api/v1/shows/skybrush/plots') return json({filenames: ['combined_drone_paths.jpg', 'drone_1_path.jpg', 'drone_2_path.jpg']});
        if (path === '/api/v1/shows/skybrush/metrics') return json({basic_metrics: {max_altitude_details: {value: 48}, min_altitude_details: {value: 3}, max_distance_details: {value: 36}}, performance_metrics: {max_velocity_details: {value: 4.2}}});
        if (path === '/api/v1/shows/operation/status') return json({state: active ? 'active' : 'idle', phase: active ? 'executing' : 'idle', mission_type: active ? 300 : null, timestamp: Date.now(), fleet: fleet.map(d => ({...d, state: active ? 'OFFBOARD' : d.state, armed: active})), operation_target_ids: [1, 2], command_id: active ? 'probe-show-001' : null, command: {executions: {succeeded: active ? 1 : 0, failed: 0}}});
        if (path === '/api/v1/origin') return json({lat: 48.8566, lon: 2.3522, alt: 42.1});
        if (path === '/api/v1/origin/deviations') return json({deviations: {'1': {status: 'ok', horizontal_m: 0.12, vertical_m: 0.08}, '2': {status: 'ok', horizontal_m: 0.18, vertical_m: 0.1}}});
        if (path === '/api/v1/config/fleet') return json(fleet);
        if (path === '/api/v1/config/swarm') return json({version: 1, assignments: [{hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned'}, {hw_id: 2, follow: 1, offset_x: 6, offset_y: 0, offset_z: 0, frame: 'ned'}]});
        if (path === '/api/v1/fleet/telemetry') return json({drones: fleet});
        if (path === '/api/v1/commands/recent' || path === '/api/v1/commands/active') return json({commands: []});
        if (path === '/api/v1/git/status') return json({gcs_status: {status: 'clean', uncommitted_changes: []}});
        if (path === '/api/v1/shows/custom') return json({drone_count: 0});
        return json({});
      };
      const isApi = (value) => { try { const url = new URL(value, window.location.href); return url.port === '5030' || url.pathname.startsWith('/api/'); } catch (_) { return false; } };
      const responseFor = (method, value) => {
        const url = new URL(value, window.location.href);
        if (!['GET', 'HEAD', 'OPTIONS'].includes(String(method || 'GET').toUpperCase())) { window.__mdsProbeWrites.push({method, path: url.pathname}); return {status: 409, type: 'application/json', body: JSON.stringify({detail: 'Probe: writes disabled'})}; }
        return fixture(url.pathname);
      };
      class ProbeXHR {
        constructor() { this.readyState = 0; this.status = 0; this.statusText = ''; this.responseText = ''; this.response = ''; this.responseType = ''; this.responseURL = ''; this.timeout = 0; this.withCredentials = true; this.upload = {addEventListener() {}}; }
        open(method, url) { this.method = method; this.url = url; this.readyState = 1; }
        setRequestHeader() {}
        getAllResponseHeaders() { return 'content-type: application/json\r\n'; }
        abort() { this.aborted = true; }
        send() { if (!isApi(this.url)) { this._native = new window.__mdsProbeNativeXHR(); this._native.open(this.method, this.url); this._native.send(); return; } setTimeout(() => { const result = responseFor(this.method, this.url); this.readyState = 4; this.status = result.status; this.statusText = result.status === 200 ? 'OK' : 'Conflict'; this.responseText = result.body; this.response = this.responseType === 'json' ? JSON.parse(result.body) : result.body; this.responseURL = this.url; this.onreadystatechange?.(); this.onload?.(); this.onloadend?.(); }, 0); }
      }
      window.__mdsProbeNativeXHR = window.XMLHttpRequest;
      window.XMLHttpRequest = ProbeXHR;
      const nativeFetch = window.fetch.bind(window);
      window.fetch = async (input, init = {}) => {
        const url = typeof input === 'string' ? input : input.url;
        if (!isApi(url)) return nativeFetch(input, init);
        const result = responseFor(init.method || 'GET', url);
        return new Response(result.body, {status: result.status, headers: {'Content-Type': result.type}});
      };
    })();'''
    if extra_fixtures is not None:
        source = source.replace('const fixture = (path) =>', 'const baseFixture = (path) =>')
        source = source.replace('const isApi =',
            'window.__mdsExtraFixtures = ' + json.dumps(extra_fixtures) + '; '
            'const fixture = (path) => Object.hasOwn(window.__mdsExtraFixtures, path) '
            '? json(window.__mdsExtraFixtures[path]) : baseFixture(path); const isApi =')
    if fleet_size != 2:
        source = source.replace("const json = (value)", f"fleet.splice(0, fleet.length, ...Array.from({{length: {fleet_size}}}, (_, i) => ({{...fleet[0], hw_id: i+1, pos_id: i+1, name: 'AIRCRAFT-' + (i+1)}}))); const json = (value)")
        source = source.replace("position_ids: [1, 2]", "position_ids: fleet.map(d => d.pos_id)")
        source = source.replace("drone_count: 2", "drone_count: fleet.length")
        source = source.replace("{'1': {status: 'ok', horizontal_m: 0.12, vertical_m: 0.08}, '2': {status: 'ok', horizontal_m: 0.18, vertical_m: 0.1}}", "Object.fromEntries(fleet.map(d => [d.hw_id, {status: 'ok'}]))")
    # Match the real aggregate contract, including the metrics envelope and
    # presentation variants. Do not silently test a different API shape.
    source = source.replace("metrics: {performance_metrics: {max_velocity_ms: 4.2}}", "metrics: {available: true, metrics: {performance_metrics: {max_velocity_ms: 4.2}, safety_metrics: {min_inter_drone_distance_m: 6.2, min_distance_details: {drone_1: '1', drone_2: '2', time_s: 42}}}}")
    source = source.replace("filenames: ['combined_drone_paths.jpg']", "filenames: ['combined_drone_paths.jpg'], variants: {'combined_drone_paths.jpg': {light: 'combined_drone_paths.jpg', dark: 'combined_drone_paths_dark.jpg'}}")
    source = source.replace("filenames: ['combined_drone_paths.jpg', 'drone_1_path.jpg', 'drone_2_path.jpg']", "filenames: ['combined_drone_paths.jpg', 'drone_1_path.jpg', 'drone_2_path.jpg'], variants: Object.fromEntries(['combined_drone_paths', 'drone_1_path', 'drone_2_path'].map(stem => [stem + '.jpg', {light: stem + '.jpg', dark: stem + '_dark.jpg'}]))")
    client.command("Page.addScriptToEvaluateOnNewDocument", {"source": source})


def full_screenshot(client: CDPClient, output: Path) -> None:
    metrics = client.command("Page.getLayoutMetrics").get("cssContentSize", {"width": 1440, "height": 960})
    width = max(1, min(float(metrics["width"]), 16000))
    height = max(1, min(float(metrics["height"]), 16000))
    payload = client.command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True, "fromSurface": True, "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1}})
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(payload["data"]))


def layout(client: CDPClient) -> dict:
    return client.evaluate("""(() => { const overflow = [...document.querySelectorAll('*')].filter((node) => { const r = node.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.right > innerWidth + 2; }).slice(0, 10).map((node) => ({ tag: node.tagName, className: String(node.className), right: Math.round(node.getBoundingClientRect().right) })); return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, overflow }; })()""")


def click_text(client: CDPClient, selector: str, text: str) -> bool:
    return bool(client.evaluate(f"(() => {{ const el = [...document.querySelectorAll({json.dumps(selector)})].find((node) => node.textContent.trim() === {json.dumps(text)}); if (!el) return false; el.click(); return true; }})()"))


def inject_plot_fixture(client: CDPClient, plot_dir: Path | None = None) -> None:
    """Replace mocked plot URLs with a local SVG so screenshots stay clean."""
    if plot_dir:
        images = {p.name: 'data:image/jpeg;base64,' + base64.b64encode(p.read_bytes()).decode() for p in plot_dir.glob('*.jpg')}
        client.evaluate(f"""(() => {{ const images = {json.dumps(images)}; document.querySelectorAll('img[data-show-plot]').forEach(img => {{ if (img.src.startsWith('data:')) return; const name = new URL(img.src).pathname.split('/').pop(); img.dataset.evidenceFilename = name; if (!images[name]) throw new Error('Missing evidence image: ' + name); img.src = images[name]; }}); return true; }})()""")
    else:
        client.evaluate("""(() => { const dark = document.documentElement.dataset.theme === 'dark'; const bg = dark ? '#111d2b' : '#ffffff'; const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 500"><rect width="1200" height="500" fill="${bg}"/><path d="M90 400 C260 340 270 90 480 120 S680 430 900 200 S1040 90 1120 70" fill="none" stroke="#36c2a0" stroke-width="7"/></svg>`; const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`; document.querySelectorAll('img[data-show-plot]').forEach(img => { if (!img.src.startsWith('data:')) img.dataset.evidenceFilename = new URL(img.src).pathname.split('/').pop(); img.src = src; }); return true; })()""")
    client.wait_for("[...document.querySelectorAll('img[data-show-plot]')].every(img => img.complete && img.naturalWidth > 0)", timeout_s=10)


def verify_plot_theme(client: CDPClient, theme: str) -> None:
    result = client.evaluate("""(() => { const imgs = [...document.querySelectorAll('img[data-show-plot]')]; const img = imgs[imgs.length - 1]; if (!img) return null; const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1; const ctx = canvas.getContext('2d'); ctx.drawImage(img, 5, 5, 1, 1, 0, 0, 1, 1); const pixel = [...ctx.getImageData(0,0,1,1).data]; return {name: img.dataset.evidenceFilename, filter: getComputedStyle(img).filter, pixel}; })()""")
    if not result or result['filter'] != 'none':
        raise RuntimeError(f"Missing plot or unexpected filter: {result}")
    if (theme == 'dark') != result['name'].endswith('_dark.jpg'):
        raise RuntimeError(f"Wrong plot variant for {theme}: {result}")
    brightness = sum(result['pixel'][:3]) / 3
    if (theme == 'dark' and brightness > 60) or (theme == 'light' and brightness < 220):
        raise RuntimeError(f"Incorrect plot background for {theme}: {result}")


def run_case(base_url: str, output_dir: Path, theme: str, viewport: str, chrome: str, port: int, plot_dir: Path | None = None, fleet_size: int = 2) -> dict:
    width, height = (390, 844) if viewport == "mobile" else (1440, 960)
    active = {"value": False}
    writes: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="mds-drone-show-ui-", ignore_cleanup_errors=True) as profile:
        process = launch_chrome(chrome, port, viewport, Path(profile))
        client = None
        try:
            wait_for_chrome(port)
            client = CDPClient(open_page_target(port))
            client.command("Page.enable")
            client.command("Runtime.enable")
            client.command("Log.enable")
            client.command("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1, "mobile": viewport == "mobile"})
            client.command("Page.addScriptToEvaluateOnNewDocument", {"source": f"localStorage.setItem('drone-dashboard-theme', {json.dumps(theme)});"})
            install_browser_mock(client, fleet_size)
            prefix = f"{theme}-{viewport}"
            client.navigate(f"{base_url.rstrip('/')}/drone-show?tab=operate")
            client.wait_for("Boolean(document.querySelector('.drone-show-workspace'))", timeout_s=25)
            client.wait_for("Boolean(document.querySelector('.drone-show-workspace__summary-state'))", timeout_s=25)
            time.sleep(0.6)
            inject_plot_fixture(client, plot_dir)
            verify_plot_theme(client, theme)
            operate = layout(client)
            full_screenshot(client, output_dir / f"{prefix}-operate-ready.png")
            if not click_text(client, "[role=tab]", "Design / Setup"):
                raise RuntimeError("Design / Setup tab unavailable")
            time.sleep(0.5)
            inject_plot_fixture(client, plot_dir)
            verify_plot_theme(client, theme)
            setup = layout(client)
            full_screenshot(client, output_dir / f"{prefix}-setup.png")
            client.evaluate("document.querySelector('.clickable-image')?.click(); true")
            client.wait_for("Boolean(document.querySelector('[aria-label=\"Close plot viewer\"]'))", timeout_s=5)
            inject_plot_fixture(client, plot_dir)
            verify_plot_theme(client, theme)
            full_screenshot(client, output_dir / f"{prefix}-fullscreen.png")
            client.evaluate("document.querySelector('[aria-label=\"Close plot viewer\"]')?.click(); true")
            if not click_text(client, "[role=tab]", "Operate"):
                raise RuntimeError("Operate tab unavailable")
            client.wait_for("Boolean(document.querySelector('.drone-show-workspace__action--launch'))", timeout_s=10)
            launch_probe = client.evaluate("(() => { const b = document.querySelector('.drone-show-workspace__action--launch'); if (!b) return {exists: false}; if (b.disabled) return {exists: true, disabled: true, text: b.textContent.trim()}; b.click(); return {exists: true, disabled: false, text: b.textContent.trim()}; })()")
            if not launch_probe.get("exists") or launch_probe.get("disabled"):
                raise RuntimeError(f"Launch review unavailable: {launch_probe}")
            client.wait_for("Boolean(document.querySelector('[role=dialog]'))", timeout_s=5)
            full_screenshot(client, output_dir / f"{prefix}-launch-review.png")
            client.evaluate("document.querySelector('[role=dialog] [data-dialog-cancel]')?.click(); true")
            active["value"] = True
            client.evaluate("window.__mdsProbeActive = true; true")
            client.navigate(f"{base_url.rstrip('/')}/drone-show?tab=operate")
            client.wait_for("Boolean(document.querySelector('.drone-show-workspace'))", timeout_s=25)
            time.sleep(0.6)
            inject_plot_fixture(client, plot_dir)
            verify_plot_theme(client, theme)
            monitoring = layout(client)
            full_screenshot(client, output_dir / f"{prefix}-monitoring.png")
            writes.extend(client.evaluate("window.__mdsProbeWrites || []") or [])
            ignored_console_errors = [error for error in client.console_errors if 'api.mapbox.com' in error or 'your_mapbox_token_here' in error or error == 'Failed to load resource: net::ERR_FAILED']
            console_errors = [error for error in client.console_errors if error not in ignored_console_errors]
            return {"theme": theme, "viewport": viewport, "operate": operate, "setup": setup, "monitoring": monitoring, "runtime_exceptions": client.runtime_exceptions, "console_errors": console_errors, "ignored_console_errors": ignored_console_errors, "writes": writes}
        finally:
            if client:
                try:
                    client.command("Browser.close")
                except Exception:
                    pass
                client.close()
            process.terminate()
            process.wait(timeout=15)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--chrome", default="/usr/bin/google-chrome")
    parser.add_argument("--plot-dir", type=Path, help="Use real generated theme JPEGs for screenshot and pixel assertions")
    parser.add_argument("--fleet-size", type=int, default=2, help="Synthetic aircraft count for layout stress checks (does not change the real fleet)")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    reports = []
    for index, theme in enumerate(("dark", "light")):
        for offset, viewport in enumerate(("desktop", "mobile")):
            reports.append(run_case(args.base_url, args.output_dir, theme, viewport, args.chrome, 9481 + (index * 2) + offset, args.plot_dir, args.fleet_size))
    failures = []
    for report in reports:
        case = f"{report['theme']}/{report['viewport']}"
        if report["runtime_exceptions"] or report["console_errors"]:
            failures.append({"case": case, "type": "runtime", "errors": report["runtime_exceptions"] + report["console_errors"]})
        for name in ("operate", "setup", "monitoring"):
            measurement = report[name]
            if measurement["documentWidth"] > measurement["viewport"] + 2 or measurement["overflow"]:
                failures.append({"case": case, "type": "overflow", "view": name, "measurement": measurement})
    summary = {"base_url": args.base_url, "output_dir": str(args.output_dir), "cases": len(reports), "reports": reports, "blocked_writes": [write for report in reports for write in report["writes"]], "failures": failures, "passed": not failures and not any(report["writes"] for report in reports)}
    (args.output_dir / "ui-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": summary["cases"], "passed": summary["passed"], "blocked_writes": summary["blocked_writes"], "failures": summary["failures"]}, indent=2))
    if not summary["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
