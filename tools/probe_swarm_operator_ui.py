#!/usr/bin/env python3
"""Read/review-only desktop/mobile Swarm UI evidence; never confirms flight actions."""
from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--chrome', default='/usr/bin/google-chrome')
    parser.add_argument('--api-port', type=int, help='Isolated validation API override (this browser only)')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, viewport in enumerate(('desktop', 'mobile')):
        with tempfile.TemporaryDirectory(prefix='mds-swarm-ui-', ignore_cleanup_errors=True) as profile:
            port = 9351 + index
            process = launch_chrome(args.chrome, port, viewport, Path(profile))
            client = None
            try:
                wait_for_chrome(port)
                client = CDPClient(open_page_target(port))
                client.command('Page.enable')
                client.command('Runtime.enable')
                if viewport == 'mobile':
                    client.command('Emulation.setDeviceMetricsOverride', dict(width=390, height=844,
                                                                           deviceScaleFactor=1, mobile=True))
                if args.api_port:
                    # Route only this browser to the isolated backend. No
                    # production runtime/configuration or files are modified.
                    client.command('Page.addScriptToEvaluateOnNewDocument', {'source': f'''
                      const originalOpen = XMLHttpRequest.prototype.open;
                      XMLHttpRequest.prototype.open = function(method, url, ...rest) {{
                        return originalOpen.call(this, method, String(url).replace(':5030/', ':{args.api_port}/'), ...rest);
                      }};
                    '''})
                client.command('Page.navigate', {'url': args.base_url.rstrip('/') + '/swarm-design'})
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    if client.evaluate("Boolean(document.querySelector('.swarm-ops select')?.value)"):
                        break
                    time.sleep(0.3)
                assert client.evaluate("Boolean(document.querySelector('.swarm-ops select')?.value)"), 'Saved cluster not loaded'
                assert client.evaluate("[...document.querySelectorAll('[role=tab]')].some(b => b.textContent === 'Operate' && b.getAttribute('aria-selected') === 'true')"), 'Operate is not default'
                overflow = client.evaluate('document.documentElement.scrollWidth > innerWidth + 1')
                assert not overflow, f'{viewport}: horizontal overflow'
                client.screenshot(args.output_dir / f'{viewport}-operate.png')
                for label, name in [('Takeoff', 'takeoff'), ('Start Swarm', 'start'), ('Return', 'return')]:
                    clicked = client.evaluate(f"(() => {{ const b = [...document.querySelectorAll('.swarm-ops button')].find(b => b.textContent.trim() === {json.dumps(label)}); if (!b || b.disabled) return false; b.click(); return true; }})()")
                    assert clicked, f'{label}: control unavailable'
                    time.sleep(0.3)
                    assert client.evaluate("Boolean(document.querySelector('[role=dialog]'))"), f'{label}: review missing'
                    client.screenshot(args.output_dir / f'{viewport}-{name}-review.png')
                    client.evaluate("[...document.querySelectorAll('[role=dialog] button')].find(b => b.textContent.trim() === 'Cancel').click()")
                    time.sleep(0.15)
                assert not client.runtime_exceptions, client.runtime_exceptions
                results.append({'viewport': viewport, 'passed': True, 'horizontal_overflow': overflow,
                                'flight_commands_sent': 0})
            finally:
                if client:
                    try:
                        client.command('Browser.close')
                    except Exception:
                        pass  # Chrome may close the socket before replying.
                    client.close()
                process.terminate()
                process.wait(timeout=15)
    (args.output_dir / 'ui-summary.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
