#!/usr/bin/env python3
"""Fixture-only browser review. No credentials, nodes or command submissions."""
import argparse
from contextlib import closing
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome
from probe_drone_show_operator_ui import install_browser_mock


def fixtures():
    members = [
        dict(hw_id=str(i), callsign=name, follow="0" if i == 1 else "1", frame="ned",
             offset_x=i * 6, offset_y=0, offset_z=0, available=True, armed=False,
             landed_state=1, readiness_status="warning" if i == 2 else "ready",
             readiness_summary="PX4 status unavailable" if i == 2 else "No MDS telemetry flags")
        for i, name in [(1, "Scout"), (2, "Wing")]
    ]
    denied = dict(message="Heading estimate unstable")
    now = int(time.time() * 1000)
    fleet = [dict(hw_id=i, pos_id=i, callsign=name, update_time=now / 1000,
                  heartbeat_last_seen=now / 1000, preflight_last_update=now, telemetry_available=True,
                  is_armed=False, landed_state=1, flight_mode=0x03040000, battery_remaining_percent=80,
                  battery_voltage=15.8, gps_fix_type=3, satellites_visible=18, readiness_status="warning",
                  preflight_warnings=[dict(source="mds_observation", message="PX4 status unavailable", timestamp=now)])
             for i, name in [(1, "Scout"), (2, "Wing")]]
    return {
        "/api/v1/fleet/telemetry": {"telemetry": {str(row["hw_id"]): row for row in fleet}},
        "/api/v1/config/fleet": fleet,
        "/api/v1/swarm/runtime/preview": dict(runtime_mode="SITL", revision="alert-review",
            clusters=[dict(cluster_id="1", members=members, partial_exclusion_hw_ids=[])],
            start_admissions={"1": dict(hw_id="1", status="ready", valid_for_ms=5000),
                              "2": dict(hw_id="2", status="blocked", message="Aircraft not airborne")}),
        "/api/v1/swarm/runtime/sequential-return": None,
        "/api/v1/commands/takeoff-readiness": dict(ready=False, valid_for_ms=5000, targets=[
            dict(hw_id="1", status="blocked", reason="Heading estimate unstable",
                 coordinated_takeoff_supported=True,
                 px4_arming_report=dict(mode="Position", can_arm_or_run=False, mode_problems=[denied], all_problems=[denied])),
            dict(hw_id="2", status="ready", coordinated_takeoff_supported=True),
        ]),
    }


def case(base, directory, theme, width, index):
    with TemporaryDirectory(prefix="mds-alert-chrome-", ignore_cleanup_errors=True) as profile:
        port = 9871 + index
        chrome = launch_chrome("/usr/bin/google-chrome", port, "mobile" if width == 390 else "desktop", Path(profile))
        try:
            wait_for_chrome(port)
            with closing(CDPClient(open_page_target(port))) as page:
                page.command("Page.enable")
                page.command("Runtime.enable")
                page.command("Network.enable")
                page.command("Network.setBlockedURLs", {"urls": ["*://127.0.0.1:39082/*", "*://100.*/*", "*catchadrone*"]})
                page.command("Emulation.setDeviceMetricsOverride", dict(width=width, height=880,
                    deviceScaleFactor=1, mobile=width == 390))
                page.command("Page.addScriptToEvaluateOnNewDocument", {"source":
                    f"localStorage.setItem('drone-dashboard-theme', {json.dumps(theme)});"})
                install_browser_mock(page, extra_fixtures=fixtures())
                page.navigate(base)
                fleet_flag = '.fleet-alerts button.alert-annunciator.tone-warning'
                page.wait_for(f"Boolean(document.querySelector({json.dumps(fleet_flag)}))")
                page.evaluate(f"document.querySelector({json.dumps(fleet_flag)}).click()")
                page.wait_for("document.querySelector('.fleet-alerts__dialog')?.textContent.includes('PX4 status unavailable')")
                page.screenshot(directory / f"{theme}-{width}-overview.png")
                page.navigate(f"{base}/swarm-design")
                cluster_flag = '.swarm-ops button.alert-annunciator.tone-warning'
                try:
                    page.wait_for(f"Boolean(document.querySelector({json.dumps(cluster_flag)}))")
                except RuntimeError:
                    print(page.evaluate("document.body.innerText.slice(0, 2400)"), flush=True)
                    print(page.runtime_exceptions, flush=True)
                    raise
                page.evaluate(f"document.querySelector({json.dumps(cluster_flag)}).click()")
                page.wait_for("document.querySelector('.alert-deck__sheet')?.textContent.includes('PX4 status unavailable')")
                page.screenshot(directory / f"{theme}-{width}-swarm.png")
                page.evaluate("[...document.querySelectorAll('.swarm-ops button')].find(b=>b.textContent.trim()==='Takeoff').click()")
                flag = '.takeoff-review [aria-label="Warning: 1"]'
                page.wait_for(f"Boolean(document.querySelector({json.dumps(flag)}))")
                if width == 390:
                    point = page.evaluate(f"(() => {{ const r = document.querySelector({json.dumps(flag)}).getBoundingClientRect();"
                        "return {x:r.x+r.width/2,y:r.y+r.height/2}; })()")
                    page.command("Input.dispatchTouchEvent", dict(type="touchStart", touchPoints=[point]))
                    page.command("Input.dispatchTouchEvent", dict(type="touchEnd", touchPoints=[]))
                else:
                    page.evaluate(f"document.querySelector({json.dumps(flag)}).focus()")
                    assert page.evaluate(f"document.activeElement === document.querySelector({json.dumps(flag)})")
                    page.command("Input.dispatchKeyEvent", dict(type="rawKeyDown", key=" ", code="Space", windowsVirtualKeyCode=32))
                    page.command("Input.dispatchKeyEvent", dict(type="keyUp", key=" ", code="Space", windowsVirtualKeyCode=32))
                page.wait_for("document.querySelector('.takeoff-review .alert-deck__sheet')?.textContent.includes('Heading estimate unstable')")
                assert page.evaluate(r"""(() => {
                  const icon = document.querySelector('.takeoff-review .alert-annunciator.tone-danger svg');
                  const token = document.createElement('span');
                  token.style.color = 'var(--color-danger)';
                  icon.closest('.takeoff-review').append(token);
                  const correct = getComputedStyle(icon).color === getComputedStyle(token).color;
                  token.remove();
                  return correct;
                })()""")
                assert page.evaluate("document.querySelectorAll('.takeoff-review .alert-deck__row').length === 1")
                assert page.evaluate("Array.from(document.querySelectorAll('.takeoff-review__member input')).every(i=>i.checked)")
                assert page.evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent.includes('Arm & take off')).disabled")
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
                assert page.evaluate("window.__mdsProbeWrites.length === 0")
                page.screenshot(directory / f"{theme}-{width}-takeoff.png")
                print(f"PASS {theme} {width}px: alert disclosure; duplicate suppressed; advisory stayed passive; zero writes", flush=True)
        finally:
            chrome.terminate()
            chrome.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    if not args.base_url.startswith("http://127.0.0.1:"):
        parser.error("Serve the preview on loopback.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for idx, (theme, width) in enumerate((theme, width) for width in (1440, 820, 390) for theme in ("dark", "light")):
        case(args.base_url.rstrip("/"), args.output_dir, theme, width, idx)


if __name__ == "__main__":
    main()
