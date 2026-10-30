#!/usr/bin/env python3
"""Capture shared Takeoff UI using browser-only simulated command responses.

All API requests are intercepted. No flight command reaches a server or aircraft.
The screenshots are operator-guide fixtures, not SITL or hardware flight proof.
"""
import argparse
import base64
import json
from pathlib import Path
import tempfile
import time

from probe_dashboard_mission_ui import CDPClient, launch_chrome, open_page_target, wait_for_chrome
from probe_drone_show_operator_ui import install_browser_mock, layout
from probe_trajectory_workspace_ui import guide_screenshot


def fixtures():
    members = [dict(hw_id=str(index), follow='0' if index == 1 else '1', available=True,
                    armed=False, landed_state=1, frame='ned', offset_x=0 if index == 1 else 6,
                    callsign='Scout' if index == 1 else 'Wing') for index in (1, 2)]
    return {
        '/api/v1/swarm/runtime/preview': dict(runtime_mode='SITL', revision='ui-demo',
            clusters=[dict(cluster_id='1', members=members, partial_exclusion_hw_ids=[])]),
        '/api/v1/swarm/runtime/sequential-return': None,
        '/api/v1/commands/takeoff-readiness': dict(ready=True, valid_for_ms=5000,
            targets=[dict(hw_id=member['hw_id'], status='ready', reason='Ready', valid_for_ms=5000,
                          coordinated_takeoff_supported=True) for member in members]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for index, (theme, viewport) in enumerate((('dark', 'desktop'), ('light', 'desktop'), ('dark', 'mobile'), ('light', 'mobile'))):
        with tempfile.TemporaryDirectory(prefix='mds-takeoff-ui-', ignore_cleanup_errors=True) as profile:
            port = 9871 + index
            process = launch_chrome('/usr/bin/google-chrome', port, viewport, Path(profile))
            client = None
            try:
                wait_for_chrome(port)
                client = CDPClient(open_page_target(port))
                client.command('Page.enable'); client.command('Runtime.enable')
                width, height = (390, 844) if viewport == 'mobile' else (1440, 960)
                client.command('Emulation.setDeviceMetricsOverride', dict(width=width, height=height, deviceScaleFactor=1, mobile=viewport == 'mobile'))
                client.command('Page.addScriptToEvaluateOnNewDocument', {'source':
                    f"localStorage.setItem('drone-dashboard-theme', {json.dumps(theme)});"})
                install_browser_mock(client, extra_fixtures=fixtures())
                # Exact command/cancel POSTs get browser-local responses; every
                # other write remains rejected by the underlying mock harness.
                client.command('Page.addScriptToEvaluateOnNewDocument', {'source': r'''(() => {
                  window.__takeoffSimulatedWrites=[];
                  const BaseXHR=window.XMLHttpRequest;
                  window.XMLHttpRequest=class extends BaseXHR {
                    send(body) {
                      const path=new URL(this.url,location.href).pathname;
                      if(String(this.method).toUpperCase()==='POST' && ['/api/v1/commands','/api/v1/commands/ui-takeoff-1/cancel-launch'].includes(path)) {
                        window.__takeoffSimulatedWrites.push({path,payload:JSON.parse(body||'{}')});
                        const cancel=path.endsWith('/cancel-launch');
                        const value=cancel ? {coordinated_takeoff:{phase:'aborted',armed_count:0,total:2,reason:'Launch cancelled',targets:{'1':{state:'disarmed'},'2':{state:'disarmed'}}}}
                          : {accepted_for_tracking:true,command_id:'ui-takeoff-1',mission_type:10,target_drones:['1','2'],timestamp:Date.now()};
                        if(cancel) window.__mdsExtraFixtures['/api/v1/commands/ui-takeoff-1']={...window.__mdsExtraFixtures['/api/v1/commands/ui-takeoff-1'],phase:'terminal',outcome:'cancelled',coordinated_takeoff:value.coordinated_takeoff,
                          executions:{expected:2,received:2,succeeded:0,failed:2,details:Object.fromEntries(['1','2'].map(id=>[id,{outcome:'failed',action_result:{success:false,final_vehicle_state:{armed:false,recovery_status:'safe_disarmed_confirmed'}}}]))}};
                        setTimeout(()=>{this.readyState=4;this.status=200;this.statusText='OK';this.responseText=JSON.stringify(value);this.response=this.responseType==='json'?value:this.responseText;this.responseURL=this.url;this.onreadystatechange?.();this.onload?.();this.onloadend?.();},0);
                        return;
                      }
                      return super.send(body);
                    }
                  };
                })();'''})
                client.navigate(args.base_url.rstrip('/') + '/swarm-design')
                client.wait_for("Boolean(document.querySelector('.swarm-ops select')?.value)", timeout_s=30)
                client.evaluate("[...document.querySelectorAll('.swarm-ops button')].find(b=>b.textContent.trim()==='Takeoff').click()")
                client.wait_for("[...document.querySelectorAll('[role=dialog] button')].some(b=>b.textContent.startsWith('Arm & take off')&&!b.disabled)", timeout_s=15)
                assert client.evaluate("document.querySelector('.takeoff-review__modes input').checked")
                assert client.evaluate("[...document.querySelectorAll('.takeoff-review__member input')].every(c=>c.checked)")
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-01-ready.png')
                client.evaluate("document.querySelector('.takeoff-review__modes input').focus()")
                client.command('Input.dispatchKeyEvent', dict(type='keyDown', key='ArrowRight', code='ArrowRight', windowsVirtualKeyCode=39))
                client.command('Input.dispatchKeyEvent', dict(type='keyUp', key='ArrowRight', code='ArrowRight', windowsVirtualKeyCode=39))
                client.wait_for("document.querySelectorAll('.takeoff-review__modes input')[1].checked", timeout_s=3)
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-07-independent.png')
                client.evaluate("document.activeElement.blur()")
                client.evaluate("document.querySelector('.takeoff-review__modes input').click()")
                client.evaluate("window.__mdsExtraFixtures['/api/v1/commands/takeoff-readiness'].valid_for_ms=0; window.__mdsExtraFixtures['/api/v1/commands/takeoff-readiness'].targets[1]={hw_id:'2',status:'blocked',valid_for_ms:0,reason:'Heading estimate unstable',coordinated_takeoff_supported:true}")
                client.wait_for("document.querySelector('.takeoff-review').textContent.includes('Heading estimate unstable')", timeout_s=8)
                assert client.evaluate("[...document.querySelectorAll('[role=dialog] button')].find(b=>b.textContent.startsWith('Arm & take off')).disabled")
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-02-blocked.png')
                client.evaluate("document.querySelectorAll('.takeoff-review__member input')[1].click()")
                client.wait_for("[...document.querySelectorAll('[role=dialog] button')].some(b=>b.textContent==='Arm & take off · 1 aircraft'&&!b.disabled)", timeout_s=8)
                assert client.evaluate("document.querySelector('.takeoff-review__selection').textContent.includes('1 of 2')")
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-05-selection.png')
                client.evaluate("document.querySelectorAll('.takeoff-review__member input')[0].click()")
                assert client.evaluate("[...document.querySelectorAll('[role=dialog] button')].find(b=>b.textContent.startsWith('Arm & take off')).disabled")
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-06-none.png')
                client.evaluate("window.__mdsExtraFixtures['/api/v1/commands/takeoff-readiness'].valid_for_ms=5000; window.__mdsExtraFixtures['/api/v1/commands/takeoff-readiness'].targets[1]={hw_id:'2',status:'ready',valid_for_ms:5000,coordinated_takeoff_supported:true}; [...document.querySelectorAll('.takeoff-review__bulk button')].find(b=>b.textContent==='Select all').click()")
                client.wait_for("[...document.querySelectorAll('[role=dialog] button')].some(b=>b.textContent==='Arm & take off · 2 aircraft'&&!b.disabled)", timeout_s=8)
                status = dict(command_id='ui-takeoff-1', mission_type=10, target_drones=['1', '2'], phase='executing',
                    outcome=None, observed_at=int(time.time()*1000), timeout_at=int(time.time()*1000)+60000,
                    acks=dict(expected=2, received=2, accepted=2), executions=dict(expected=2, succeeded=0, failed=0),
                    coordinated_takeoff=dict(phase='arming', armed_count=1, total=2,
                        targets={'1': dict(state='armed'), '2': dict(state='arming')}))
                client.evaluate("window.__mdsExtraFixtures['/api/v1/commands/ui-takeoff-1']="+json.dumps(status))
                client.click_center('[role=dialog] .operator-confirm-dialog__actions button:last-child')
                client.wait_for("document.querySelector('.takeoff-review__progress')?.textContent==='Arming 1/2'", timeout_s=10)
                assert client.evaluate("[...document.querySelectorAll('.takeoff-review__member input')].every(c=>c.disabled)")
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-03-arming.png')
                client.evaluate("[...document.querySelectorAll('[role=dialog] button')].find(b=>b.textContent==='Cancel launch').click()")
                client.wait_for("document.querySelector('.takeoff-review__progress')?.textContent==='Launch cancelled'", timeout_s=8)
                guide_screenshot(client, '[role=dialog]', args.output_dir/f'{theme}-{viewport}-04-cancelled.png')
                writes = client.evaluate('window.__takeoffSimulatedWrites')
                assert len(writes) == 2 and writes[0]['payload']['takeoff_mode'] == 'coordinated', writes
                assert not client.evaluate('window.__mdsProbeWrites'), 'Unexpected API write attempted'
                assert not client.runtime_exceptions, client.runtime_exceptions
                assert layout(client)['documentWidth'] <= width + 2, layout(client)
                results.append(dict(theme=theme, viewport=viewport, simulated_posts=2, external_api_writes=0,
                                    ready=True, independent=True, keyboard=True, blocked=True, selection=True, none=True, arming=True, cancelled=True))
            finally:
                if client:
                    try: client.command('Browser.close')
                    except Exception: pass
                    client.close()
                if process.poll() is None: process.terminate()
                process.wait(timeout=15)
    (args.output_dir/'summary.json').write_text(json.dumps(results, indent=2))
    capture_combined_guide(args.output_dir)
    print(json.dumps(results))


def capture_combined_guide(output):
    """Capture an HTML contact sheet of unmodified UI screenshots, not AI mockups."""
    cards = [
        ('01-ready', '1 · Review height and preselected aircraft'),
        ('07-independent', '2 · Launch mode is a separate choice'),
        ('05-selection', '3 · Excluded aircraft remain visible'),
        ('06-none', '4 · No selection, no launch'),
        ('02-blocked', '5 · A selected blocker prevents launch'),
        ('03-arming', '6 · Confirm once; selection is locked'),
        ('04-cancelled', '7 · Cancellation requires disarm evidence'),
    ]
    figures = ''.join(f'<figure><figcaption>{title}</figcaption><img src="data:image/png;base64,'
        + base64.b64encode((output/f'dark-desktop-{name}.png').read_bytes()).decode('ascii')
        + '"></figure>' for name, title in cards)
    page = '''<style>body{margin:0;background:#080f17;color:#e6edf4;font:16px system-ui}
    main{width:1280px;padding:24px;box-sizing:border-box}header{display:flex;align-items:baseline;
    justify-content:space-between;margin:0 0 20px}h1{font-size:26px;margin:0}header span{color:#acbccc}
    section{display:grid;grid-template-columns:1fr 1fr;gap:20px}figure{margin:0;min-width:0}
    figcaption{font-size:17px;margin:0 0 8px}img{display:block;width:100%;height:auto}</style>
    <main id="takeoff-guide"><header><h1>Takeoff · Review → Arm → Launch</h1>
    <span>Simulated UI guide · not flight evidence</span></header><section>''' + figures + '</section></main>'
    with tempfile.TemporaryDirectory(prefix='mds-takeoff-guide-') as profile:
        process = launch_chrome('/usr/bin/google-chrome', 9879, 'desktop', Path(profile))
        client = None
        try:
            wait_for_chrome(9879)
            client = CDPClient(open_page_target(9879))
            client.command('Page.enable'); client.command('Runtime.enable')
            client.command('Emulation.setDeviceMetricsOverride', dict(width=1280, height=2000, deviceScaleFactor=1, mobile=False))
            client.command('Page.navigate', {'url': 'about:blank'})
            client.wait_for("document.readyState==='complete'&&Boolean(document.body)", timeout_s=10)
            client.evaluate('document.body.innerHTML=' + json.dumps(page))
            client.wait_for("[...document.images].every(i=>i.complete&&i.naturalWidth>0)", timeout_s=10)
            bounds = client.evaluate("(()=>{const r=document.querySelector('main').getBoundingClientRect();return {x:0,y:0,width:r.width,height:r.height,scale:1}})()")
            capture = client.command('Page.captureScreenshot', dict(format='png', captureBeyondViewport=True, fromSurface=True, clip=bounds))
            (output/'takeoff-workflow-combined.png').write_bytes(base64.b64decode(capture['data']))
        finally:
            if client:
                try: client.command('Browser.close')
                except Exception: pass
                client.close()
            if process.poll() is None: process.terminate()
            process.wait(timeout=15)


if __name__ == '__main__':
    main()
