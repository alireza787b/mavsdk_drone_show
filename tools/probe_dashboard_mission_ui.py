#!/usr/bin/env python3
"""Headless browser probe for mission-planning dashboard surfaces.

This probe is intentionally lightweight and stdlib-first apart from the
`websocket-client` package already used by local validation environments. It is
meant for deployed or dev-server dashboards where Jest coverage is not enough:

- sidebar collapse tooltip behavior
- QuickScout route and Leaflet fallback map rendering
- Swarm Trajectory route, embedded map editor, and waypoint click insertion
- Advanced Route Editor compatibility label
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

try:
    import websocket
except ImportError as exc:  # pragma: no cover - host dependency check
    raise SystemExit("Missing dependency: websocket-client") from exc


@dataclass
class ProbeStep:
    name: str
    passed: bool
    detail: str = ""
    screenshot: str | None = None


@dataclass
class ProbeReport:
    base_url: str
    viewport: str
    steps: list[ProbeStep] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    runtime_exceptions: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(step.passed for step in self.steps) and not self.runtime_exceptions


class CDPClient:
    def __init__(self, websocket_url: str) -> None:
        self.ws = websocket.create_connection(websocket_url, timeout=10)
        self.next_id = 0
        self.console_errors: list[str] = []
        self.runtime_exceptions: list[str] = []

    def close(self) -> None:
        self.ws.close()

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.next_id += 1
        message_id = self.next_id
        self.ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            raw = self.ws.recv()
            message = json.loads(raw)
            if "method" in message:
                self._handle_event(message)
                continue
            if message.get("id") != message_id:
                continue
            if "error" in message:
                raise RuntimeError(f"CDP {method} failed: {message['error']}")
            return message.get("result", {})

    def drain_events(self, timeout_s: float = 0.25) -> None:
        original_timeout = self.ws.gettimeout()
        self.ws.settimeout(timeout_s)
        try:
            while True:
                try:
                    message = json.loads(self.ws.recv())
                except Exception:
                    break
                if "method" in message:
                    self._handle_event(message)
        finally:
            self.ws.settimeout(original_timeout)

    def evaluate(self, expression: str) -> Any:
        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("text") or details.get("exception", {}).get("description") or "Runtime exception"
            raise RuntimeError(text)
        return result.get("result", {}).get("value")

    def wait_for(self, expression: str, *, timeout_s: float = 12.0, interval_s: float = 0.25) -> Any:
        deadline = time.time() + timeout_s
        last_value = None
        while time.time() < deadline:
            try:
                last_value = self.evaluate(expression)
            except Exception as exc:
                last_value = str(exc)
            if last_value:
                return last_value
            time.sleep(interval_s)
        raise RuntimeError(f"Timed out waiting for expression: {expression}. Last value: {last_value!r}")

    def navigate(self, url: str) -> None:
        self.command("Page.navigate", {"url": url})
        self.wait_for("document.readyState === 'complete' || document.readyState === 'interactive'", timeout_s=20)
        self.wait_for("Boolean(document.body && document.body.innerText.length > 0)", timeout_s=20)
        time.sleep(0.8)
        self.drain_events()

    def screenshot(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.command("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": False})
        path.write_bytes(base64.b64decode(payload["data"]))

    def click_center(self, selector: str) -> dict[str, float]:
        rect = self.wait_for(
            f"""(() => {{
              const el = document.querySelector({json.dumps(selector)});
              if (!el) return null;
              let r = el.getBoundingClientRect();
              if (r.bottom < 0 || r.top > window.innerHeight || r.right < 0 || r.left > window.innerWidth) {{
                el.scrollIntoView({{ block: 'center', inline: 'center' }});
                r = el.getBoundingClientRect();
              }}
              if (r.width < 20 || r.height < 20) return null;
              return {{x: r.left + r.width / 2, y: r.top + r.height / 2, width: r.width, height: r.height}};
            }})()""",
            timeout_s=20,
        )
        self.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": rect["x"], "y": rect["y"]})
        self.command("Input.dispatchMouseEvent", {"type": "mousePressed", "x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1})
        self.command("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": rect["x"], "y": rect["y"], "button": "left", "clickCount": 1})
        time.sleep(0.4)
        self.drain_events()
        return rect

    def hover_center(self, selector: str, text_filter: str | None = None) -> dict[str, float]:
        filter_js = ""
        if text_filter:
            filter_js = f".find((el) => (el.getAttribute('aria-label') || el.textContent || '').trim() === {json.dumps(text_filter)})"
        else:
            filter_js = "[0]"
        rect = self.wait_for(
            f"""(() => {{
              const el = Array.from(document.querySelectorAll({json.dumps(selector)})){filter_js};
              if (!el) return null;
              const r = el.getBoundingClientRect();
              if (r.width < 10 || r.height < 10) return null;
              return {{x: r.left + r.width / 2, y: r.top + r.height / 2, width: r.width, height: r.height}};
            }})()""",
            timeout_s=15,
        )
        self.command("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": rect["x"], "y": rect["y"]})
        self.evaluate(
            f"""(() => {{
              const el = Array.from(document.querySelectorAll({json.dumps(selector)})){filter_js};
              if (!el) return false;
              const r = el.getBoundingClientRect();
              const eventInit = {{
                bubbles: true,
                cancelable: true,
                clientX: r.left + r.width / 2,
                clientY: r.top + r.height / 2,
                view: window
              }};
              el.dispatchEvent(new MouseEvent('mousemove', eventInit));
              el.dispatchEvent(new MouseEvent('mouseover', eventInit));
              el.dispatchEvent(new MouseEvent('mouseenter', {{ ...eventInit, bubbles: false }}));
              const PointerCtor = window.PointerEvent || MouseEvent;
              el.dispatchEvent(new PointerCtor('pointermove', eventInit));
              el.dispatchEvent(new PointerCtor('pointerover', eventInit));
              el.dispatchEvent(new PointerCtor('pointerenter', {{ ...eventInit, bubbles: false }}));
              if (typeof el.focus === 'function') {{
                el.focus({{ preventScroll: true }});
              }}
              return true;
            }})()"""
        )
        time.sleep(0.4)
        self.drain_events()
        return rect

    def _handle_event(self, message: dict[str, Any]) -> None:
        method = message.get("method")
        params = message.get("params", {})
        if method == "Runtime.exceptionThrown":
            details = params.get("exceptionDetails", {})
            text = details.get("text") or details.get("exception", {}).get("description") or "Runtime exception"
            self.runtime_exceptions.append(str(text))
        elif method == "Log.entryAdded":
            entry = params.get("entry", {})
            if entry.get("level") in {"error", "warning"}:
                self.console_errors.append(str(entry.get("text", "")))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:3030", help="Dashboard base URL")
    parser.add_argument("--chrome-binary", default=None, help="Chrome/Chromium binary path")
    parser.add_argument("--debug-port", type=int, default=9223, help="Chrome remote debugging port")
    parser.add_argument("--viewport", choices=("desktop", "mobile"), default="desktop")
    parser.add_argument("--json-output", type=Path, help="Write JSON report")
    parser.add_argument("--screenshot-dir", type=Path, help="Directory for screenshots")
    parser.add_argument("--keep-chrome", action="store_true", help="Leave Chrome running for debugging")
    return parser


def resolve_chrome(binary: str | None) -> str:
    if binary:
        return binary
    for candidate in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise SystemExit("Chrome/Chromium binary not found")


def http_json(url: str, *, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def wait_for_chrome(port: int, timeout_s: float = 15.0) -> None:
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/json/version"
    while time.time() < deadline:
        try:
            http_json(url)
            return
        except Exception:
            time.sleep(0.2)
    raise RuntimeError(f"Chrome did not open CDP port {port}")


def open_page_target(port: int) -> str:
    encoded = urllib.parse.quote("about:blank", safe="")
    url = f"http://127.0.0.1:{port}/json/new?{encoded}"
    try:
        payload = http_json(url, method="PUT")
    except urllib.error.HTTPError:
        payload = http_json(url, method="GET")
    websocket_url = payload.get("webSocketDebuggerUrl")
    if not websocket_url:
        raise RuntimeError("Chrome did not return a page websocket URL")
    return websocket_url


def launch_chrome(chrome_binary: str, port: int, viewport: str, user_data_dir: Path) -> subprocess.Popen:
    width, height = (390, 844) if viewport == "mobile" else (1440, 960)
    command = [
        chrome_binary,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-background-networking",
        "--remote-allow-origins=*",
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        f"--window-size={width},{height}",
        "about:blank",
    ]
    return subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def route_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def add_step(report: ProbeReport, step: ProbeStep) -> None:
    report.steps.append(step)
    status = "PASS" if step.passed else "FAIL"
    print(f"{status}: {step.name} {step.detail}".strip(), flush=True)


def capture_step(cdp: CDPClient, screenshot_dir: Path | None, name: str) -> str | None:
    if not screenshot_dir:
        return None
    path = screenshot_dir / f"{name}.png"
    cdp.screenshot(path)
    return str(path)


def set_leaflet_preference(cdp: CDPClient, base_url: str) -> None:
    cdp.navigate(route_url(base_url, "/"))
    cdp.evaluate("localStorage.setItem('mds_map_provider', 'leaflet'); true")


def probe_sidebar(cdp: CDPClient, report: ProbeReport, base_url: str, screenshot_dir: Path | None) -> None:
    cdp.navigate(route_url(base_url, "/"))
    collapsed = cdp.evaluate("""(() => {
      const button = document.querySelector('button.sidebar-toggle');
      if (!button) return false;
      const label = button.getAttribute('aria-label') || '';
      if (label.includes('Collapse')) button.click();
      return Boolean(document.querySelector('.modern-sidebar-wrapper.collapsed'));
    })()""")
    if not collapsed:
        cdp.wait_for("Boolean(document.querySelector('.modern-sidebar-wrapper.collapsed'))", timeout_s=5)
    cdp.wait_for(
        "Boolean(document.querySelector('.nav-item.collapsed[aria-label=\"QuickScout SAR\"]'))",
        timeout_s=5,
    )
    cdp.wait_for(
        """(() => {
          const el = document.querySelector('.nav-item.collapsed[aria-label="QuickScout SAR"]');
          if (!el) return false;
          const r = el.getBoundingClientRect();
          return r.left >= 0 && r.left < 90 && r.width > 20 && r.width < 90;
        })()""",
        timeout_s=5,
    )
    cdp.hover_center(".nav-item.collapsed", "QuickScout SAR")
    tooltip_text = cdp.wait_for(
        "(() => { const el = document.querySelector('.nav-tooltip'); return el ? el.textContent.trim() : ''; })()",
        timeout_s=5,
    )
    add_step(
        report,
        ProbeStep(
            name="sidebar_collapsed_tooltip",
            passed=tooltip_text == "QuickScout SAR",
            detail=f"tooltip={tooltip_text!r}",
            screenshot=capture_step(cdp, screenshot_dir, "sidebar-collapsed-tooltip"),
        ),
    )


def probe_mobile_navigation(cdp: CDPClient, report: ProbeReport, base_url: str, screenshot_dir: Path | None) -> None:
    cdp.navigate(route_url(base_url, "/"))
    cdp.wait_for("Boolean(document.querySelector('.mobile-sidebar-toggle'))", timeout_s=8)
    cdp.click_center(".mobile-sidebar-toggle")
    cdp.wait_for("Boolean(document.querySelector('.modern-sidebar-wrapper.mobile.mobile-open'))", timeout_s=8)
    nav_text = cdp.evaluate(
        "(() => document.querySelector('.modern-sidebar-wrapper.mobile.mobile-open')?.innerText || '')()"
    )
    overflow_ok = cdp.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth + 2"
    )
    checks = [
        "QuickScout SAR" in nav_text,
        "Swarm Trajectory" in nav_text,
        "Advanced Route Editor" in nav_text,
        bool(overflow_ok),
    ]
    add_step(
        report,
        ProbeStep(
            name="mobile_navigation_menu",
            passed=all(checks),
            detail=f"checks={checks}",
            screenshot=capture_step(cdp, screenshot_dir, "mobile-navigation-menu"),
        ),
    )


def probe_quickscout(cdp: CDPClient, report: ProbeReport, base_url: str, screenshot_dir: Path | None) -> None:
    cdp.navigate(route_url(base_url, "/quickscout"))
    text = cdp.evaluate("document.body.innerText")
    map_ready = cdp.wait_for(
        "(() => { const el = document.querySelector('.leaflet-container, .mapboxgl-map'); if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 200 && r.height > 180; })()",
        timeout_s=20,
    )
    checks = [
        "QuickScout" in text,
        "Live GPS" in text,
        "Origin Slots" in text,
        bool(map_ready),
        bool(cdp.evaluate("Boolean(document.querySelector('.leaflet-container'))")),
    ]
    add_step(
        report,
        ProbeStep(
            name="quickscout_leaflet_workspace",
            passed=all(checks),
            detail=f"checks={checks}",
            screenshot=capture_step(cdp, screenshot_dir, "quickscout-leaflet-workspace"),
        ),
    )


def probe_swarm_trajectory(cdp: CDPClient, report: ProbeReport, base_url: str, screenshot_dir: Path | None) -> None:
    cdp.navigate(route_url(base_url, "/swarm-trajectory"))
    text = cdp.evaluate("document.body.innerText")
    map_ready = cdp.wait_for(
        "(() => { const el = document.querySelector('.swarm-route-map-editor .leaflet-container, .swarm-route-map-editor .mapboxgl-map'); if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 200 && r.height > 180; })()",
        timeout_s=20,
    )
    before = cdp.evaluate("(() => { const m = document.body.innerText.match(/(\\d+) waypoints?/); return m ? Number(m[1]) : null; })()")
    cdp.click_center(".swarm-route-map-editor__map")
    after = cdp.wait_for(
        f"(() => {{ const m = document.body.innerText.match(/(\\d+) waypoints?/); return m ? Number(m[1]) > {int(before or 0)} : false; }})()",
        timeout_s=8,
    )
    checks = [
        "Swarm Trajectory" in text,
        "Leader route map" in text,
        "Advanced processing" in text,
        bool(map_ready),
        bool(after),
    ]
    add_step(
        report,
        ProbeStep(
            name="swarm_trajectory_map_waypoint",
            passed=all(checks),
            detail=f"checks={checks} before={before}",
            screenshot=capture_step(cdp, screenshot_dir, "swarm-trajectory-map-waypoint"),
        ),
    )


def probe_advanced_route_editor(cdp: CDPClient, report: ProbeReport, base_url: str, screenshot_dir: Path | None) -> None:
    cdp.navigate(route_url(base_url, "/trajectory-planning"))
    text = cdp.evaluate("document.body.innerText")
    add_step(
        report,
        ProbeStep(
            name="advanced_route_editor_label",
            passed="Advanced Route Editor" in text,
            detail="compatibility route retains advanced label",
            screenshot=capture_step(cdp, screenshot_dir, "advanced-route-editor"),
        ),
    )


def run(args: argparse.Namespace) -> ProbeReport:
    chrome = resolve_chrome(args.chrome_binary)
    screenshot_dir = args.screenshot_dir
    report = ProbeReport(base_url=args.base_url, viewport=args.viewport)

    with tempfile.TemporaryDirectory(prefix="mds-dashboard-probe-", ignore_cleanup_errors=True) as tmp:
        user_data_dir = Path(tmp) / "chrome"
        chrome_process = launch_chrome(chrome, args.debug_port, args.viewport, user_data_dir)
        cdp: CDPClient | None = None
        try:
            wait_for_chrome(args.debug_port)
            cdp = CDPClient(open_page_target(args.debug_port))
            width, height = (390, 844) if args.viewport == "mobile" else (1440, 960)
            cdp.command("Page.enable")
            cdp.command("Runtime.enable")
            cdp.command("Log.enable")
            cdp.command(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": width,
                    "height": height,
                    "deviceScaleFactor": 1,
                    "mobile": args.viewport == "mobile",
                },
            )
            set_leaflet_preference(cdp, args.base_url)
            if args.viewport == "mobile":
                probe_mobile_navigation(cdp, report, args.base_url, screenshot_dir)
            else:
                probe_sidebar(cdp, report, args.base_url, screenshot_dir)
            probe_quickscout(cdp, report, args.base_url, screenshot_dir)
            probe_swarm_trajectory(cdp, report, args.base_url, screenshot_dir)
            probe_advanced_route_editor(cdp, report, args.base_url, screenshot_dir)
            cdp.drain_events()
            report.console_errors.extend(cdp.console_errors)
            report.runtime_exceptions.extend(cdp.runtime_exceptions)
        finally:
            if cdp:
                cdp.close()
            if not args.keep_chrome:
                chrome_process.terminate()
                try:
                    chrome_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    chrome_process.kill()
    return report


def main() -> int:
    args = build_parser().parse_args()
    report = run(args)
    payload = {
        **asdict(report),
        "passed": report.passed,
    }
    if args.json_output:
        output = args.json_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
