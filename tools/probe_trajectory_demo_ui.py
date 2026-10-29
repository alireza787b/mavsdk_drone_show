#!/usr/bin/env python3
"""Review real generated package data in Chrome with aircraft explicitly offline.

The supplied JSON contains canonical workspace/origin/fleet-config reads. Browser
API writes remain blocked; this verifies loaded assets and UI, not flight.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome
from probe_drone_show_operator_ui import install_browser_mock, full_screenshot, layout


def demo_fixtures(evidence):
    workspace = evidence['workspace']
    status = workspace['status']
    fleet = [dict(hw_id=str(row['hw_id']), name=row.get('callsign') or row.get('name') or f"H{row['hw_id']}",
                  telemetry_fresh=False, ready_to_arm=False, armed=False, landed_state=None,
                  state='Offline', readiness_summary='Offline') for row in evidence['fleet_config']]
    clusters = status['clusters']
    base = '/api/v1/swarm-trajectories'
    return {
        base + '/workspace': workspace,
        base + '/operation': dict(state='idle', phase='idle', fleet=fleet, timestamp=int(time.time() * 1000)),
        base + '/formation': {**workspace['formation'], 'success': True},
        base + '/status': dict(success=True, status=status),
        base + '/validate': workspace['validation'],
        base + '/preview': workspace['preview'],
        base + '/leaders': dict(success=True, leaders=status['expected_top_leaders'],
            hierarchies={str(row['leader_id']): len(row['follower_ids']) for row in clusters},
            follower_details={str(row['leader_id']): row['follower_ids'] for row in clusters},
            simulation_mode=workspace['simulation_mode']),
        '/api/v1/origin': evidence['origin'],
        '/api/v1/config/fleet': evidence['fleet_config'],
        '/api/v1/config/gcs': dict(git_auto_push=False),
        '/api/v1/swarm/runtime/sequential-return': None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--package-file', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    evidence = json.loads(args.package_file.read_text())
    validation = evidence['workspace']['validation']
    assert validation['ready'] and not any(validation[key] for key in ('blockers', 'warnings', 'advisories'))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, viewport in enumerate(('desktop', 'mobile')):
        with tempfile.TemporaryDirectory(prefix='mds-demo-browser-') as profile:
            process = launch_chrome('/usr/bin/google-chrome', 9860 + index, viewport, Path(profile))
            client = None
            try:
                wait_for_chrome(9860 + index)
                client = CDPClient(open_page_target(9860 + index))
                client.command('Page.enable'); client.command('Runtime.enable')
                width, height = (320, 844) if viewport == 'mobile' else (1440, 960)
                client.command('Emulation.setDeviceMetricsOverride', dict(width=width, height=height,
                               deviceScaleFactor=1, mobile=viewport == 'mobile'))
                client.command('Page.addScriptToEvaluateOnNewDocument', {'source':
                    "localStorage.setItem('drone-dashboard-theme', 'dark');"})
                install_browser_mock(client, extra_fixtures=demo_fixtures(evidence))
                client.navigate(args.base_url.rstrip('/') + '/swarm-trajectory')
                client.wait_for("Boolean(document.querySelector('.trajectory-route-review'))", timeout_s=30)
                assert client.evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Start mission').disabled"), 'Offline aircraft were made launch-ready'
                assert client.evaluate("document.querySelector('.trajectory-console__status').textContent.includes('Package ready')"), 'Loaded package is not ready'
                client.wait_for("Boolean(document.querySelector('.trajectory-route-review__map .leaflet-overlay-pane path') || document.querySelector('.trajectory-route-review__map--3d canvas'))", timeout_s=20)
                full_screenshot(client, args.output_dir / f'{viewport}-operate.png')
                client.evaluate("[...document.querySelectorAll('.trajectory-console__tabs button')].find(b=>b.textContent==='Plan').click()")
                client.wait_for("Boolean(document.querySelector('.swarm-workflow-tab'))", timeout_s=20)
                client.evaluate("[...document.querySelectorAll('.swarm-workflow-tab')].find(b=>b.textContent.includes('Review')).click()")
                client.wait_for("Boolean(document.querySelector('.trajectory-route-review__map .leaflet-overlay-pane path'))", timeout_s=20)
                assert client.evaluate(f"document.querySelectorAll('.trajectory-route-review__aircraft input:checked').length === {len(validation['expected_drone_ids'])}"), 'Demo review does not show its complete formation'
                assert not client.evaluate("document.body.textContent.includes('Outside mission (')"), 'Stale outputs remain in the demo'
                assert layout(client)['documentWidth'] <= width + 2, layout(client)
                assert not client.evaluate('window.__mdsProbeWrites'), 'Demo review attempted an API write'
                assert not client.runtime_exceptions, client.runtime_exceptions
                full_screenshot(client, args.output_dir / f'{viewport}-review.png')
                results.append(dict(viewport=viewport, package_ready=True, aircraft_offline=True,
                                    aircraft_count=len(validation['expected_drone_ids']), writes=0))
            except Exception:
                if client:
                    full_screenshot(client, args.output_dir / f'{viewport}-failed.png')
                raise
            finally:
                if client:
                    try: client.command('Browser.close')
                    except Exception: pass
                    client.close()
                if process.poll() is None: process.terminate()
                process.wait(timeout=15)
    (args.output_dir / 'summary.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results))


if __name__ == '__main__':
    main()
