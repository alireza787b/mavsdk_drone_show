#!/usr/bin/env node
// Actual built routes/CSS with synthetic aircraft. No backend traffic is forwarded.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixtureState, installFixtures } = require('./validate_px4_parameter_workspace_ui.cjs');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
assert.equal(process.env.MDS_UI_FIXTURE_ONLY, '1');
const base = process.env.MDS_UI_BASE || 'http://127.0.0.1:3039';
const evidence = process.env.MDS_UI_EVIDENCE;
assert(evidence);
fs.mkdirSync(evidence, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.MDS_CHROMIUM_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const results = [];
  try {
    for (const width of (process.env.MDS_UI_WIDTHS || '1440,900,390').split(',').map(Number))
      for (const theme of (process.env.MDS_UI_THEMES || 'dark,light').split(',')) {
      const state = fixtureState();
      state.telemetryOverrides = Object.fromEntries(['1','2'].map((id,index) => [id, {
        gps_fix_type: 6, satellites_visible: 20, battery_remaining_percent: 83, state: 0,
        battery_voltage: 16.1, position_alt: 100, position_lat: 35.7 + index * .0001,
        position_long: 51.4, global_position_valid: true, follow_mode: index ? 1 : 0,
        heartbeat_network_info: { primary_link: { type: 'ethernet', interface: 'end0' } },
      }]));
      const context = await browser.newContext({ viewport: { width, height: width === 390 ? 760 : 1000 }, colorScheme: theme,
        hasTouch: width === 390, serviceWorkers: 'block' });
      await context.addInitScript(value => {
        localStorage.setItem('drone-dashboard-theme', value);
        localStorage.setItem('mds_map_provider', 'leaflet');
      }, theme);
      const page = await context.newPage();
      page.setDefaultTimeout(18000);
      page.on('pageerror', error => state.pageErrors.push(error.message));
      await installFixtures(context, state, page);
      const payloads = {
        '/api/v1/origin': { lat:35.7,lon:51.4,alt:100 },
        '/api/v1/fleet/network-details': [],
        '/api/v1/fleet/heartbeats': { heartbeats:[] },
        '/api/v1/fleet/enrollment/candidates': { candidates:[] },
        '/api/v1/config/fleet/trajectory-start-positions': [{ pos_id:'1',x:0,y:0 },{ pos_id:'2',x:10,y:0 }],
        '/api/v1/origin/deviations': { deviations:{},summary:{} },
        '/api/v1/shows/operation/status': { fleet:['1','2'].map(id => ({ hw_id:id,pos_id:id,name:id==='1'?'ALPHA':'BRAVO',telemetry_fresh:true,ready_to_arm:true,armed:false })),state:'idle',timestamp:Date.now() },
      };
      for (const [routePath,payload] of Object.entries(payloads)) await context.route(`**${routePath}*`, route => {
        const request=route.request();
        assert(['GET','OPTIONS'].includes(request.method()));
        return route.fulfill({ status:request.method()==='OPTIONS'?204:200,
          headers:{ 'access-control-allow-origin':new URL(base).origin,'access-control-allow-credentials':'true',
            'access-control-allow-headers':request.headers()['access-control-request-headers'] || 'Content-Type' },
          ...(request.method()==='OPTIONS'?{}:{json:payload}) });
      });
      // Offline basemap fixture: no external tile/provider traffic. This proves
      // marker/popup/control layout, not map-provider coverage.
      await context.route(/https:\/\/.*(?:arcgisonline\.com|tile\.openstreetmap\.org)\/.*/, route =>
        route.fulfill({contentType:'image/svg+xml',body:`<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="${theme==='dark'?'#172431':'#e4e9ee'}"/><path d="M0 128h256M128 0v256" stroke="${theme==='dark'?'#253646':'#cdd6de'}" fill="none"/></svg>`}));
      const capture = async name => {
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: horizontal overflow`);
        await page.screenshot({ path:path.join(evidence,`${name}-${width}-${theme}.png`) });
      };
      try {
        await page.goto(base+'/mission-config');
        await page.locator('.drone-config-card').first().waitFor();
        assert.equal(await page.locator('.initial-launch-plot').count(),0);
        await capture('assignments');
        await page.getByRole('button',{name:'Edit drone configuration',exact:true}).first().click();
        const editor=page.locator('.drone-edit-form');
        await editor.waitFor();
        for (const selector of ['input[aria-label="Hardware ID"]','input[aria-label="IP Address"]','select[aria-label="Serial Port"]']) {
          const style=await editor.locator(selector).evaluate(element => ({
            color:getComputedStyle(element).color,bg:getComputedStyle(element).backgroundColor,
            radius:getComputedStyle(element).borderTopLeftRadius,height:element.getBoundingClientRect().height,
          }));
          assert.notEqual(style.color,style.bg); assert.equal(style.radius,'2px'); assert(style.height>=44);
        }
        await capture('edit-aircraft');
        await page.getByRole('button',{name:'Cancel editing',exact:true}).click();
        await page.getByRole('link',{name:'Drone Show · launch layout ↗',exact:true}).click();
        await page.locator('#launch-geometry[open]').waitFor();
        await page.locator('#launch-geometry .js-plotly-plot').waitFor();
        await capture('show-launch-layout');
        await page.goto(base+'/globe-view');
        await page.getByRole('button',{name:'Map View',exact:true}).click();
        await page.getByRole('button',{name:'Select P1|H1 on the active view',exact:true}).click();
        const popup=page.locator('.tactical-drone-card').first();
        await popup.waitFor();
        assert.equal(await popup.evaluate(element=>getComputedStyle(element).borderTopLeftRadius),'0px');
        await popup.locator('summary').click();
        await popup.getByText('Ethernet',{exact:true}).waitFor();
        const assertInspectorBounds=async ownerSelector => {
          const bounds=await page.locator('.fleet-map-inspector').boundingBox();
          const owner=await page.locator(ownerSelector).boundingBox();
          assert(bounds.x>=owner.x && bounds.y>=owner.y && bounds.x+bounds.width<=owner.x+owner.width+1 && bounds.y+bounds.height<=owner.y+owner.height+1,'Aircraft inspector stays inside its viewport');
          const close=await page.locator('.fleet-map-inspector').getByRole('button',{name:/^Close .* summary$/}).boundingBox();
          assert(close.y>=bounds.y && close.y+close.height<=bounds.y+bounds.height,'Close stays accessible');
        };
        await assertInspectorBounds('.globe-map-container');
        await capture('map-aircraft-details');
        await page.getByRole('button',{name:'3D Scene',exact:true}).click();
        await page.locator('.scene-container .fleet-map-inspector').waitFor();
        await assertInspectorBounds('.scene-container');
        await capture('globe-aircraft-details');
        assert.deepEqual(state.pageErrors,[]);
        assert.deepEqual(state.violations,[]);
        assert.equal(state.requests.filter(request=>request.method==='POST').length,0);
        results.push({width,theme,passed:true,forwardedApiRequests:0});
        fs.writeFileSync(path.join(evidence,'configuration-surfaces-results.json'),JSON.stringify({fixtureOnly:true,results},null,2));
      } catch(error) {
        await page.screenshot({path:path.join(evidence,`failure-${width}-${theme}.png`)});
        fs.writeFileSync(path.join(evidence,`failure-${width}-${theme}.json`),JSON.stringify({message:error.message,pageErrors:state.pageErrors,violations:state.violations,text:(await page.locator('body').innerText()).slice(0,5000)},null,2));
        throw error;
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({passed:true,cases:results.length}));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
