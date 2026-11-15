/* Browser-only observation fault fixture. All API/WS traffic is intercepted;
 * never dispatches a command or alters a live GCS. Run against a served build. */
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MDS_OVERVIEW_URL || 'http://127.0.0.1:3038';
const output = process.env.MDS_OVERVIEW_OUTPUT;

async function run() {
  if (output) fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.MDS_CHROMIUM_PATH ? { executablePath: process.env.MDS_CHROMIUM_PATH } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const results = [];
  const pendingTimers = new Set();
  try {
    for (const width of [390, 1440]) for (const theme of ['dark', 'light']) {
      const context = await browser.newContext({ viewport: { width, height: 960 } });
      const page = await context.newPage();
      const errors = [], writes = [], timers = new Set();
      let sockets = 0, activeSockets = 0, maxSockets = 0, telemetryReads = 0;
      let stalled = false, generation = 0;
      const fleet = [1, 2, 3].map(id => ({ hw_id: String(id), pos_id: id, callsign: `AIRCRAFT-${id}` }));
      const telemetry = () => Object.fromEntries(fleet.map((drone, i) => [drone.hw_id, {
        ...drone, update_time: Date.now() / 1000, telemetry_available: true,
        presence: { heartbeat_received_at_gcs_ms: Date.now() },
        is_armed: false, landed_state: 1, gps_fix_type: 4, satellites_visible: 17,
        global_position_valid: true, flight_mode: 50593792, readiness_status: 'ready',
        is_ready_to_arm: true, preflight_blockers: [], position_lat: 35.7 + i * .00003,
        position_long: 51.4 + i * .00002, position_alt: 1200,
        battery_remaining_percent: 83, battery_voltage: 15.8, battery_charge_state: 1,
      }]));
      const envelope = () => ({ protocol_version: 1, stream_id: 'browser-fixture',
        sequence: ++generation, published_at_ms: Date.now(), delivery: 'latest_snapshot',
        type: 'telemetry', timestamp: Date.now(), data: telemetry() });
      page.on('pageerror', error => errors.push(error.message));
      await page.routeWebSocket('**/*', socket => {
        sockets += 1; activeSockets += 1; maxSockets = Math.max(maxSockets, activeSockets);
        const send = () => { if (!stalled) socket.send(JSON.stringify(envelope())); };
        const timer = setInterval(send, 500); timers.add(timer); pendingTimers.add(timer); send();
        socket.onClose(() => { clearInterval(timer); timers.delete(timer); pendingTimers.delete(timer); activeSockets -= 1; });
      });
      await page.route('**/*', route => {
        const request = route.request(), url = new URL(request.url());
        if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
          writes.push(url.pathname);
          return route.fulfill({ status: 409, json: { detail: 'Read-only observation fixture' } });
        }
        if (!url.pathname.startsWith('/api/')) return route.continue();
        let json;
        if (url.pathname.includes('/auth')) json = { dashboard_auth_enabled: false, api_auth_enabled: false, authenticated: true };
        else if (url.pathname === '/api/v1/config/fleet') json = fleet;
        else if (url.pathname === '/api/v1/config/swarm') json = { version: 1, assignments: fleet.map((d, i) => ({ hw_id: d.hw_id, follow: i ? '1' : '0', offset_x: i ? -5 : 0, offset_y: i * 3, offset_z: 0, frame: 'ned' })) };
        else if (url.pathname.includes('/system/runtime-status')) json = { mode: 'real', configured_mode: 'real', restart_required: false };
        else if (url.pathname.includes('/node-boot-status')) json = { nodes: {} };
        else if (url.pathname === '/api/v1/fleet/telemetry') {
          telemetryReads += 1;
          const frame = envelope(); json = { ...frame, telemetry: frame.data };
        }
        else if (url.pathname.includes('/commands/')) json = { commands: [] };
        else if (url.pathname.includes('git')) json = { needs_sync_count: 0, unknown_count: 0, git_status: {} };
        else return route.fulfill({ status: 503, json: { detail: 'No read fixture' } });
        return route.fulfill({ status: 200, json, headers: {
          'access-control-allow-origin': new URL(base).origin, 'access-control-allow-credentials': 'true',
          'access-control-expose-headers': 'x-mds-server-time', 'x-mds-server-time': String(Date.now()),
        } });
      });
      await page.addInitScript(theme => localStorage.setItem('drone-dashboard-theme', theme), theme);
      await page.goto(base + '/');
      await page.locator('.fleet-aircraft').first().waitFor();
      await page.waitForTimeout(1600);
      assert.equal(activeSockets, 1, 'Authenticated shell has one fleet subscription');
      const healthyReads = telemetryReads;
      await page.waitForTimeout(1600);
      assert.equal(telemetryReads, healthyReads, 'Healthy WS suppresses duplicate HTTP acquisition');
      // Initial unknown -> effective runtime is a deliberate protected-context
      // reset. Only navigation within that settled context must reuse its owner.
      const settledSockets = sockets;
      if (width <= 960) await page.getByRole('button', { name: 'Open navigation menu' }).click();
      await page.locator('a[href="/globe-view"]').first().click();
      await page.waitForURL('**/globe-view');
      await page.waitForTimeout(1200);
      assert.equal(activeSockets, 1, 'Globe shares the shell observation owner');
      assert.equal(sockets, settledSockets, 'Route navigation does not reconnect fleet telemetry');
      const beforeStall = telemetryReads;
      stalled = true;
      await page.waitForTimeout(6200);
      assert(telemetryReads > beforeStall, 'Silent open WS falls back to HTTP');
      stalled = false;
      await page.waitForTimeout(2000);
      assert.equal(activeSockets, 1, 'Recovery leaves exactly one active fleet socket');
      const recoveredReads = telemetryReads;
      await page.waitForTimeout(1800);
      assert.equal(telemetryReads, recoveredReads, 'Recovered WS suppresses fallback again');
      assert.equal(maxSockets, 1, 'No overlapping fleet sockets');
      assert.deepEqual(writes, [], 'Observation/navigation never submits a command');
      assert.deepEqual(errors, [], 'No browser runtime errors');
      if (output) await page.screenshot({ path: path.join(output, `shared-observation-${width}-${theme}.png`) });
      results.push({ width, theme, settledSockets, sockets, maxSockets, telemetryReads, writes: writes.length, errors });
      for (const timer of timers) { clearInterval(timer); pendingTimers.delete(timer); }
      await context.close();
    }
  } finally { for (const timer of pendingTimers) clearInterval(timer); await browser.close(); }
  const summary = { status: 'passed', scope: 'intercepted browser observation fixture, not native flight or radio performance', results };
  if (output) fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(summary, null, 2) + '\n');
  console.log(JSON.stringify(summary));
}
run().catch(error => { console.error(error); process.exitCode = 1; });
