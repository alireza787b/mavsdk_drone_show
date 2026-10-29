#!/usr/bin/env python3
"""Read-only browser fixture for actual trajectory editor field interactions.

All network writes are intercepted by the shared probe harness. Draft changes
exist only in the temporary browser profile; this is UI evidence, not flight proof.
"""
import argparse
import json
from pathlib import Path
import tempfile
import time

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome
from probe_drone_show_operator_ui import install_browser_mock, layout
from probe_trajectory_workspace_ui import fixtures, guide_screenshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    parser.add_argument('--expect-fixed', action='store_true')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, (theme, viewport) in enumerate((('light', 'desktop'), ('dark', 'mobile'))):
        with tempfile.TemporaryDirectory(prefix='mds-editor-ui-', ignore_cleanup_errors=True) as profile:
            process = launch_chrome('/usr/bin/google-chrome', 9813 + index, viewport, Path(profile))
            client = None
            try:
                wait_for_chrome(9813 + index)
                client = CDPClient(open_page_target(9813 + index))
                client.command('Page.enable'); client.command('Runtime.enable')
                width, height = (390, 844) if viewport == 'mobile' else (1440, 960)
                client.command('Emulation.setDeviceMetricsOverride', dict(width=width, height=height, deviceScaleFactor=1, mobile=viewport == 'mobile'))
                draft = [dict(id=f'edit-wp-{i}', name=f'Waypoint {i+1}', latitude=48+i*.001,
                    longitude=2+i*.002, altitude=120, timeFromStart=10+i*90,
                    timingMode='manual_time' if i == 0 else 'auto_speed', preferredSpeed=8,
                    headingMode='manual' if i == 0 else 'auto', heading=0,
                    altitudeReference='msl', terrainAccurate=False) for i in range(3)]
                client.command('Page.addScriptToEvaluateOnNewDocument', {'source':
                    f"localStorage.setItem('drone-dashboard-theme',{json.dumps(theme)});"
                    f"localStorage.setItem('mds.trajectory.draft.v1.sitl.1',{json.dumps(json.dumps(draft))});"})
                install_browser_mock(client, extra_fixtures=fixtures(2))
                client.navigate(args.base_url.rstrip('/') + '/swarm-trajectory?tab=plan')
                client.wait_for("document.querySelectorAll('.waypoint-panel .waypoint-item').length===3", timeout_s=30)
                client.evaluate("document.querySelector('.waypoint-panel .waypoint-item .waypoint-header').click()")
                client.evaluate("[...document.querySelectorAll('.waypoint-item:first-child .detail-row')].find(r=>r.textContent.toLowerCase().includes('route entry delay')).querySelector('.detail-value.editable').click()")
                client.wait_for("Boolean(document.querySelector('.waypoint-panel .edit-input'))", timeout_s=5)
                field = client.evaluate("(() => {const e=document.querySelector('.waypoint-panel .edit-input'),p=e.closest('.waypoint-panel'),r=e.getBoundingClientRect(),q=p.getBoundingClientRect(),s=getComputedStyle(e);return {width:r.width,panelWidth:q.width,inside:r.left>=q.left&&r.right<=q.right,color:s.color,background:s.backgroundColor};})()")
                client.evaluate("(() => {const e=document.querySelector('.waypoint-panel .edit-input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(e,'90');e.dispatchEvent(new Event('input',{bubbles:true}));})()")
                client.evaluate("document.querySelector('.waypoint-panel .save-btn').click()")
                time.sleep(.3)
                delay = client.evaluate("JSON.parse(localStorage.getItem('mds.trajectory.draft.v1.sitl.1'))[0].timeFromStart")
                feedback = client.evaluate("document.querySelector('.waypoint-panel-feedback')?.textContent || ''")
                guide_screenshot(client, '.waypoint-panel', args.output_dir/f'{theme}-{viewport}-timing.png')
                if client.evaluate("Boolean(document.querySelector('.waypoint-panel .cancel-btn'))"):
                    client.evaluate("document.querySelector('.waypoint-panel .cancel-btn').click()")
                client.evaluate("[...document.querySelectorAll('.trajectory-toolbar button')].find(b=>b.dataset.help?.startsWith('Add Waypoint Mode')).click()")
                client.evaluate("document.querySelector('.trajectory-main .leaflet-container').scrollIntoView({block:'center'})")
                point = client.evaluate("""(() => {const r=document.querySelector('.trajectory-main .leaflet-container').getBoundingClientRect();
                    const top=Math.max(0,r.top),bottom=Math.min(innerHeight,r.bottom);
                    for (const fx of [.23,.71,.41]) for(const fy of [.65,.35,.8]) {const x=r.left+r.width*fx,y=top+(bottom-top)*fy,e=document.elementFromPoint(x,y);
                      if(e?.closest('.leaflet-container')&&!e.closest('.leaflet-marker-icon')) return {x,y};} return null;})()""")
                assert point, 'Map has no unobstructed visible click target'
                for event_type in ('mousePressed', 'mouseReleased'):
                    client.command('Input.dispatchMouseEvent', dict(type=event_type, x=point['x'], y=point['y'], button='left', clickCount=1))
                client.wait_for("Boolean(document.querySelector('.waypoint-modal'))", timeout_s=10)
                radio = client.evaluate("(() => {const e=document.querySelector('.waypoint-modal input[type=radio]'),r=e.getBoundingClientRect(); return {width:r.width,height:r.height};})()")
                modal = client.evaluate("(() => {const m=document.querySelector('.waypoint-modal'),f=m.querySelector('.waypoint-modal-footer'),r=m.getBoundingClientRect(),q=f.getBoundingClientRect();return {width:r.width,height:r.height,footerInside:q.bottom<=innerHeight&&q.top>=0};})()")
                client.screenshot(args.output_dir/f'{theme}-{viewport}-modal.png')
                unobstructed = client.evaluate("""(() => {const modal=document.querySelector('.waypoint-modal');
                    return [...modal.querySelectorAll('input:not(:disabled),button')].filter(e=>{const r=e.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight&&r.width>0&&r.height>0})
                    .every(e=>{const r=e.getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return hit===e||e.contains(hit);});})()""")
                client.evaluate("document.querySelector('.waypoint-modal-close').click()")
                client.evaluate("document.querySelector('.trajectory-toolbar .save-btn').click()")
                client.wait_for("Boolean(document.querySelector('.trajectory-library-dialog input'))", timeout_s=5)
                library = client.evaluate("""(() => {const e=document.querySelector('.trajectory-library-dialog input'),r=e.getBoundingClientRect(),s=getComputedStyle(e),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
                    return {unobstructed:hit===e,rootPortal:e.closest('.trajectory-dialog-host')?.parentElement===document.body,color:s.color,background:s.backgroundColor};})()""")
                client.screenshot(args.output_dir/f'{theme}-{viewport}-library.png')
                metrics = layout(client)
                blocked_requests = client.evaluate('window.__mdsProbeWrites || []')
                writes = [request for request in blocked_requests if request['path'] != '/api/v1/swarm-trajectories/elevation/batch']
                result = dict(theme=theme, viewport=viewport, field=field, delay=delay, feedback=feedback,
                    radio=radio, modal=modal, layout=metrics, writes=writes,
                    mocked_terrain_queries=len(blocked_requests)-len(writes), unobstructed=unobstructed, library=library)
                results.append(result)
                if args.expect_fixed:
                    assert delay == 90, result
                    assert field['inside'] and field['width'] >= 90, result
                    assert radio['width'] <= 24 and radio['height'] <= 24, result
                    assert modal['footerInside'], result
                    assert unobstructed, result
                    assert library['unobstructed'] and library['rootPortal'], result
                    assert metrics['documentWidth'] <= metrics['viewport'] + 2, result
                assert not writes, result
                assert not client.runtime_exceptions, client.runtime_exceptions
            except Exception:
                if client:
                    print(json.dumps(dict(case=f'{theme}-{viewport}', text=client.evaluate("document.body.innerText.slice(-1500)"),
                        map=client.evaluate("(() => {const e=document.querySelector('.leaflet-container'); if(!e)return null; const r=e.getBoundingClientRect(); return {top:r.top,height:r.height,width:r.width};})()"))))
                    guide_screenshot(client, '.trajectory-planning', args.output_dir/f'{theme}-{viewport}-failed.png')
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
    (args.output_dir/'summary.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
