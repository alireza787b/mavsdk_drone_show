#!/usr/bin/env python3
"""Read-only trajectory workspace screenshots with explicit mocked SITL evidence.

All API writes are blocked in the browser. These are UI fixtures, not flight proof.
"""
import argparse
import base64
import json
from pathlib import Path
import tempfile
import time

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome
from probe_drone_show_operator_ui import install_browser_mock, full_screenshot, layout


def guide_screenshot(client, selector, output, max_height=1100):
    """Capture the real UI section at documentation size; no image recoloring."""
    # Allow the actual route-entry transition to settle before measuring its box.
    time.sleep(.4)
    bounds = client.evaluate(f"(() => {{const r=document.querySelector({json.dumps(selector)}).getBoundingClientRect(); return {{x:r.left+scrollX,y:r.top+scrollY,width:r.width,height:r.height}};}})()")
    width = client.evaluate('document.documentElement.scrollWidth')
    bounds['x'] = max(0, bounds['x']-12)
    bounds['y'] = max(0, bounds['y']-12)
    bounds['width'] = min(width-bounds['x'], bounds['width']+24)
    bounds['height'] += 24
    bounds['height'] = min(bounds['height'], max_height)
    bounds['scale'] = min(1, 960 / bounds['width'])
    result = client.command('Page.captureScreenshot', dict(format='png', captureBeyondViewport=True,
                                                         fromSurface=True, clip=bounds))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(base64.b64decode(result['data']))


def capture_operator_guide(client, output, count):
    """Read-only setup/review plus explicitly simulated active mission evidence."""
    client.evaluate("document.querySelector('.trajectory-formation').open = true")
    guide_screenshot(client, '.trajectory-formation', output/'01-formation.png')
    client.evaluate("document.querySelector('.trajectory-formation').open = false")
    guide_screenshot(client, '.swarm-route-authoring', output/'02-route.png')
    for tab, filename in [('Generate', '03-process.png'), ('Review', '04-review.png')]:
        client.evaluate(f"[...document.querySelectorAll('.swarm-workflow-tab')].find(b=>b.textContent.includes({json.dumps(tab)})).click()")
        client.wait_for(f"Boolean(document.querySelector('.swarm-panel.is-active'))", timeout_s=5)
        guide_screenshot(client, '.swarm-panel.is-active', output/filename)
    client.evaluate("[...document.querySelectorAll('.trajectory-console__tabs button')].find(b=>b.textContent==='Operate').click()")
    client.wait_for("Boolean(document.querySelector('.trajectory-console__command-rail'))", timeout_s=10)
    client.evaluate("[...document.querySelectorAll('.trajectory-console__command-rail button')].find(b=>b.textContent.trim()==='Start mission').click()")
    client.wait_for("Boolean(document.querySelector('[role=dialog]'))", timeout_s=5)
    guide_screenshot(client, '[role=dialog]', output/'05-start-review.png')
    client.evaluate("document.querySelector('[data-dialog-cancel]').click()")
    operation = fixtures(count)['/api/v1/swarm-trajectories/operation']
    operation.update(state='active', phase='trajectory', command_id='ui-guide-run',
                     operation_target_ids=[str(i) for i in range(1, count+1)])
    for aircraft in operation['fleet']:
        aircraft.update(armed=True, landed_state=2, state='Offboard', ready_to_arm=False,
                        trajectory_execution=dict(command_id='ui-guide-run', fresh=True, phase='trajectory',
                                                  trajectory_time_s=35, duration_s=90))
    client.evaluate("window.__mdsExtraFixtures['/api/v1/swarm-trajectories/operation'] = " + json.dumps(operation))
    client.wait_for("document.querySelector('.trajectory-console__status').textContent.includes('Mission active')", timeout_s=10)
    assert client.evaluate("[...document.querySelectorAll('.trajectory-console__command-rail button')].find(b=>b.textContent.trim()==='Start mission').disabled"), 'Active mission still permits a second Start'
    guide_screenshot(client, '.trajectory-console', output/'06-monitor.png')
    client.evaluate("[...document.querySelectorAll('.trajectory-console__command-rail button')].find(b=>b.textContent.trim()==='Immediate Return').click()")
    client.wait_for("Boolean(document.querySelector('[role=dialog]'))", timeout_s=5)
    guide_screenshot(client, '[role=dialog]', output/'07-return-review.png')
    client.evaluate("document.querySelector('[data-dialog-cancel]').click()")


def fixtures(count):
    members = [dict(hw_id=i, follow=0 if i == 1 else 1, offset_x=(i-1)*6,
                    offset_y=0, offset_z=0, frame='ned') for i in range(1, count+1)]
    cluster = dict(leader_id=1, follower_ids=list(range(2, count+1)), state='ready', ready=True,
                   follower_count=count-1, expected_drone_count=count, processed_drone_count=count,
                   leader_uploaded=True, leader_processed=True, issues=[], advisories=[])
    stats = dict(available=True, drone_count=count, drone_ids=list(range(1,count+1)), mission_clock_s=90)
    status = dict(has_results=True, processed_trajectories=count, processed_drones=stats['drone_ids'],
                  processed_leaders=[1], uploaded_leaders=[1], clusters=[cluster], package_stats=stats,
                  cluster_summary=dict(cluster_count=1, ready_cluster_count=1, overall_state='ready'),
                  session=dict(exists=True, session_id='ui-fixture', total_drones=count, processed_leaders=[1]))
    validation = dict(success=True, ready=True, blockers=[], warnings=[], advisories=[])
    preview = dict(success=True, drones=[dict(drone_id=i, role='leader' if i==1 else 'follower',
        global_coordinates_available=True, points=[dict(lat=48.0+(i-1)*.00006, lng=2.0, alt_msl=120, time_s=0),
        dict(lat=48.001+(i-1)*.00006, lng=2.002, alt_msl=120, time_s=90)]) for i in range(1,count+1)])
    formation = dict(success=True, assignments=members, revision='a'*64, saved=True)
    fleet = [dict(hw_id=str(i), name=f'Aircraft {i}', telemetry_fresh=True, ready_to_arm=True,
                  armed=False, landed_state=1, state='Hold', readiness_summary='Ready', battery_percent=92)
             for i in range(1,count+1)]
    operation = dict(state='idle', phase='idle', fleet=fleet, timestamp=int(time.time()*1000))
    base = '/api/v1/swarm-trajectories'
    return {base+'/workspace': dict(status=status, validation=validation, preview=preview, formation=formation,
        simulation_mode=True, launch_identity=dict(revision='ui-fixture', files={str(i): 'a'*64 for i in range(1,count+1)})),
        base+'/operation': operation, base+'/formation': formation, base+'/status': dict(success=True, status=status),
        base+'/leaders': dict(success=True, leaders=[1], hierarchies={1: count-1}, follower_details={1: list(range(2,count+1))}, simulation_mode=True),
        base+'/validate': validation, base+'/preview': preview,
        '/api/v1/swarm/runtime/sequential-return': None, '/api/v1/config/gcs': dict(git_auto_push=False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--fleet-size', type=int, default=2)
    parser.add_argument('--capture-guide', action='store_true', help='Capture read-only operator steps for the dark desktop case')
    args = parser.parse_args()
    if not 1 <= args.fleet_size <= 100:
        raise SystemExit('Fleet size must be 1..100')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, (theme, viewport) in enumerate([(t,v) for t in ('dark','light') for v in ('desktop','mobile')]):
        with tempfile.TemporaryDirectory(prefix='mds-trajectory-ui-', ignore_cleanup_errors=True) as profile:
            process = launch_chrome('/usr/bin/google-chrome', 9811+index, viewport, Path(profile))
            client = None
            try:
                wait_for_chrome(9811+index)
                client = CDPClient(open_page_target(9811+index))
                client.command('Page.enable'); client.command('Runtime.enable')
                width,height = (390,844) if viewport=='mobile' else (1440,960)
                client.command('Emulation.setDeviceMetricsOverride', dict(width=width,height=height,deviceScaleFactor=1,mobile=viewport=='mobile'))
                draft = [dict(id=f'ui-wp-{i}', name=f'Waypoint {i+1}', latitude=48+i*.001,
                              longitude=2+i*.002, altitude=120, timeFromStart=i*90,
                              timingMode='manual_time', headingMode='manual', heading=0,
                              altitudeReference='msl', terrainAccurate=False)
                         for i in range(2)]
                client.command('Page.addScriptToEvaluateOnNewDocument', {'source':
                    f"localStorage.setItem('drone-dashboard-theme', {json.dumps(theme)});"
                    f"localStorage.setItem('mds.trajectory.draft.v1.sitl.1', {json.dumps(json.dumps(draft))});"})
                install_browser_mock(client, extra_fixtures=fixtures(args.fleet_size))
                client.navigate(args.base_url.rstrip('/')+'/swarm-trajectory')
                client.wait_for("Boolean(document.querySelector('.trajectory-console__command-rail'))", timeout_s=30)
                client.wait_for("[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Start mission' && !b.disabled)", timeout_s=15)
                time.sleep(.3)
                metrics = layout(client)
                assert metrics['documentWidth'] <= metrics['viewport'] + 2, metrics
                prefix = f'{theme}-{viewport}'
                full_screenshot(client, args.output_dir/f'{prefix}-operate.png')
                client.evaluate("[...document.querySelectorAll('.trajectory-console__command-rail button')].find(b=>b.textContent.trim()==='Start mission').click()")
                client.wait_for("Boolean(document.querySelector('[role=dialog]'))", timeout_s=5)
                assert client.evaluate("document.querySelector('[role=dialog]').textContent.includes('Launch from the ground')"), 'Review has no operator context'
                full_screenshot(client, args.output_dir/f'{prefix}-start-review.png')
                client.evaluate("document.querySelector('[data-dialog-cancel]').click()")
                client.evaluate("[...document.querySelectorAll('.trajectory-console__tabs button')].find(b=>b.textContent==='Plan').click()")
                client.wait_for("Boolean(document.querySelector('.trajectory-planning--embedded .waypoint-panel'))", timeout_s=20)
                assert client.evaluate("getComputedStyle(document.querySelector('.waypoint-panel .waypoint-actions')).display === 'flex'"), 'Waypoint panel stylesheet is missing'
                assert not client.evaluate("document.querySelector('.waypoint-compact-summary__hint, .waypoint-brief-grid')"), 'Repeated authoring guidance remains in waypoint cards'
                assert client.evaluate("document.querySelector('.trajectory-header .header-left').getBoundingClientRect().bottom <= document.querySelector('.trajectory-brief').getBoundingClientRect().top + 2"), 'Search overlaps route metrics'
                assert client.evaluate("[...document.querySelectorAll('.trajectory-toolbar button')].every(b=>{const r=b.getBoundingClientRect(), p=b.closest('.trajectory-toolbar').getBoundingClientRect(); return r.left >= p.left-2 && r.right <= p.right+2;})"), 'Route controls overlap the waypoint panel'
                assert client.evaluate("document.querySelector('#trajectory-leader').value === '1'"), 'Wrong leader draft'
                assert not client.evaluate("[...document.querySelectorAll('.sidebar-nav a')].some(a=>a.textContent.trim()==='Route Editor')"), 'Duplicate editor navigation'
                plan_metrics = layout(client)
                assert plan_metrics['documentWidth'] <= plan_metrics['viewport'] + 2, plan_metrics
                assert client.evaluate("[...document.querySelectorAll('.swarm-workflow-tab')].every(b=>{const r=b.getBoundingClientRect(),p=b.parentElement.getBoundingClientRect();return r.left>=p.left-1 && r.right<=p.right+1})"), 'A planning stage is hidden beyond the tab row'
                full_screenshot(client, args.output_dir/f'{prefix}-plan.png')
                # The skin must cover every stage, not only the entry screen.
                client.evaluate("document.querySelector('.trajectory-toolbar .save-btn').click()")
                client.wait_for("Boolean(document.querySelector('.trajectory-library-dialog'))", timeout_s=5)
                assert client.evaluate("parseFloat(getComputedStyle(document.querySelector('.trajectory-library-dialog')).borderTopLeftRadius) <= 2"), 'Library dialog still uses the legacy card skin'
                client.evaluate("[...document.querySelectorAll('.trajectory-library-dialog button')].find(b=>b.textContent.trim()==='Cancel').click()")
                tab_layouts = {}
                for tab in ('Uploads', 'Generate', 'Review'):
                    client.evaluate(f"[...document.querySelectorAll('.swarm-workflow-tab')].find(b=>b.textContent.includes({json.dumps(tab)})).click()")
                    client.wait_for("Boolean(document.querySelector('.swarm-panel.is-active'))", timeout_s=5)
                    tab_metrics = layout(client)
                    assert tab_metrics['documentWidth'] <= tab_metrics['viewport'] + 2, (tab, tab_metrics)
                    assert client.evaluate("[...document.querySelectorAll('.swarm-panel.is-active button')].every(b=>parseFloat(getComputedStyle(b).borderTopLeftRadius)<=2)"), f'{tab} still has legacy rounded controls'
                    full_screenshot(client, args.output_dir/f'{prefix}-{tab.lower()}.png')
                    tab_layouts[tab] = tab_metrics
                client.wait_for("Boolean(document.querySelector('.trajectory-route-review__map .leaflet-overlay-pane path'))", timeout_s=10)
                assert client.evaluate(f"document.querySelectorAll('.trajectory-route-review__aircraft input:checked').length === {args.fleet_size}"), 'Preview hides assigned aircraft'
                assert client.evaluate("getComputedStyle(document.querySelector('.trajectory-route-review__aircraft')).display === 'flex' && parseFloat(getComputedStyle(document.querySelector('.trajectory-route-review__aircraft input')).height) <= 20"), 'Global console fields distort route checkboxes'
                path_count = client.evaluate("document.querySelectorAll('.trajectory-route-review__map .leaflet-overlay-pane path').length")
                client.evaluate("document.querySelector('.trajectory-route-review__aircraft input').click()")
                assert client.evaluate("document.querySelectorAll('.trajectory-route-review__map .leaflet-overlay-pane path').length") < path_count, 'Legend does not hide map paths'
                client.evaluate("document.querySelector('.trajectory-route-review__aircraft input').click()")
                client.evaluate("[...document.querySelectorAll('.trajectory-route-review button')].find(b=>b.textContent.trim()==='Overview').click()")
                assert client.evaluate("[...document.querySelectorAll('.trajectory-route-review polyline')].every(p=>p.getAttribute('vector-effect')==='non-scaling-stroke' && parseFloat(p.getAttribute('stroke-width'))<=2)"), 'Overview has inflated route strokes'
                client.evaluate("[...document.querySelectorAll('.trajectory-route-review button')].find(b=>b.textContent.trim()==='Map').click()")
                client.evaluate("[...document.querySelectorAll('.swarm-workflow-tab')].find(b=>b.textContent.includes('Route')).click()")
                if args.capture_guide and theme == 'dark' and viewport == 'desktop':
                    capture_operator_guide(client, args.output_dir/'guide', args.fleet_size)
                assert not client.evaluate('window.__mdsProbeWrites'), 'Review unexpectedly attempted a write'
                assert not client.runtime_exceptions, client.runtime_exceptions
                client.navigate(args.base_url.rstrip('/')+'/trajectory-planning')
                client.wait_for("location.pathname === '/swarm-trajectory' && location.search === '?tab=plan'", timeout_s=15)
                client.wait_for("Boolean(document.querySelector('.trajectory-planning--embedded'))", timeout_s=20)
                assert not client.evaluate('window.__mdsProbeWrites'), 'Legacy redirect unexpectedly attempted a write'
                results.append(dict(theme=theme, viewport=viewport, layout=metrics, plan_layout=plan_metrics,
                                    writes=0, fixture_aircraft=args.fleet_size, legacy_redirect=True,
                                    tab_layouts=tab_layouts, interactive_review=True))
            except Exception:
                if client:
                    print(json.dumps({'case': f'{theme}-{viewport}', 'runtime_errors': client.runtime_exceptions,
                        'visible_text': client.evaluate("document.body.innerText.slice(0, 1200)")}))
                    full_screenshot(client, args.output_dir/f'{theme}-{viewport}-failed.png')
                raise
            finally:
                if client:
                    try:
                        client.command('Browser.close')
                    except Exception:
                        pass
                    client.close()
                if process.poll() is None:
                    process.terminate()
                process.wait(timeout=15)
    (args.output_dir/'summary.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))


if __name__ == '__main__':
    main()
