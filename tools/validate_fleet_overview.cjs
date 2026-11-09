/* Isolated served-build acceptance. All API traffic is fulfilled in-browser;
 * no write, WebSocket or synthetic aircraft can reach a real GCS. Run on the
 * validation host, with MDS_PLAYWRIGHT_MODULE and MDS_CHROMIUM_PATH as needed. */
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MDS_OVERVIEW_URL || 'http://127.0.0.1:3038';
const output = process.env.MDS_OVERVIEW_OUTPUT;
const counts = (process.env.MDS_OVERVIEW_COUNTS || '1,3,20,100').split(',').map(Number);
const widths = (process.env.MDS_OVERVIEW_WIDTHS || '390,768,900,1440').split(',').map(Number);
const themes = (process.env.MDS_OVERVIEW_THEMES || 'dark,light').split(',');
const soakIndex = process.argv.indexOf('--soak-seconds');
const soakSeconds = soakIndex < 0 ? 0 : Number(process.argv[soakIndex + 1]);
assert(Number.isFinite(soakSeconds) && soakSeconds >= 0 && soakSeconds <= 3600, 'Use --soak-seconds 0..3600');
const allLive = process.argv.includes('--all-live');

async function run() {
  if (output) fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true,
    ...(process.env.MDS_CHROMIUM_PATH ? { executablePath: process.env.MDS_CHROMIUM_PATH } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const results = [];
  try {
    for (const count of counts) for (const width of widths) for (const theme of themes) {
      const context = await browser.newContext({ viewport: { width, height: 960 }, hasTouch: width <= 768 });
      const page = await context.newPage();
      const errors = [], writes = [], reads = {};
      let stale = false;
      const fleet = Array.from({ length: count }, (_, i) => ({ hw_id: String(i + 1), pos_id: i + 1, callsign: `AIRCRAFT-${String(i + 1).padStart(2, '0')}` }));
      const assignments = fleet.map((d, i) => ({ hw_id: d.hw_id, follow: i ? '1' : '0', offset_x: i ? -5 : 0, offset_y: i * 3, offset_z: 0, frame: 'ned' }));
      page.on('pageerror', error => errors.push(error.message));
      await page.routeWebSocket('**/*', socket => socket.close());
      await page.route('**/*', route => {
        const req = route.request(), url = new URL(req.url());
        if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method())) {
          writes.push({ method: req.method(), path: url.pathname });
          return route.fulfill({ status: 409, json: { detail: 'Read-only fixture: no dispatch' } });
        }
        if (url.port !== '5030' && !url.pathname.startsWith('/api/')) return route.continue();
        reads[url.pathname] = (reads[url.pathname] || 0) + 1;
        let json;
        if (url.pathname.includes('/auth')) json = { dashboard_auth_enabled: false, api_auth_enabled: false, authenticated: true };
        else if (url.pathname === '/api/v1/config/fleet') json = fleet;
        else if (url.pathname === '/api/v1/config/swarm') json = { version: 1, assignments };
        else if (url.pathname === '/api/v1/system/runtime-status') json = { mode: 'real', configured_mode: 'real', restart_required: false };
        else if (url.pathname === '/api/v1/fleet/node-boot-status') json = { nodes: {} };
        else if (url.pathname === '/api/v1/fleet/telemetry') json = Object.fromEntries(fleet.map((d, i) => [d.hw_id, {
          ...d, update_time: Date.now() / 1000 - (stale || !allLive && i === count - 1 && count > 1 ? 80 : 0), telemetry_available: true,
          is_armed: false, landed_state: 1, gps_fix_type: 4, satellites_visible: 17, global_position_valid: true,
          position_lat: 35.7 + i * .00003, position_long: 51.4 + i * .00002, position_alt: 1200,
          battery_remaining_percent: i === count - 1 ? 26 : 83, battery_voltage: 15.8,
        }]));
        else if (url.pathname.includes('/commands/active') || url.pathname.includes('/commands/recent')) json = { commands: [] };
        else if (url.pathname.includes('git')) json = { gcs_status: { commit: '1234567890', status: 'clean' }, git_status: {} };
        else if (url.pathname.includes('/health')) json = { status: 'healthy' };
        else if (url.pathname.includes('/takeoff-readiness')) json = { targets: url.searchParams.getAll('target_drone_ids').map(id => ({ hw_id: id, status: 'ready', coordinated_takeoff_supported: true })), server_processing_ms: 0 };
        else return route.fulfill({ status: 503, json: { detail: 'No fixture for this read' } });
        return route.fulfill({ status: 200, json, headers: {
          'access-control-allow-origin': new URL(base).origin, 'access-control-allow-credentials': 'true',
          'access-control-allow-headers': req.headers()['access-control-request-headers'] || 'Content-Type',
          'access-control-allow-methods': 'GET,HEAD,OPTIONS', 'x-mds-server-time': String(Date.now()),
        } });
      });
      await page.addInitScript(theme => { localStorage.setItem('drone-dashboard-theme', theme); }, theme);
      await page.goto(base + '/');
      try { await page.locator('.fleet-aircraft').first().waitFor(); }
      catch (error) {
        if (output) await page.screenshot({ path: path.join(output, 'startup-failure.png'), fullPage: true });
        throw new Error(`${error.message}\n${JSON.stringify({ errors, reads, text: (await page.locator('body').innerText()).slice(0, 1800) })}`);
      }
      await page.evaluate(theme => { document.documentElement.dataset.theme = theme; document.documentElement.classList.toggle('theme-dark', theme === 'dark'); document.documentElement.classList.toggle('theme-light', theme === 'light'); }, theme);
      const boxes = page.getByRole('checkbox', { name: /^Select / });
      await page.waitForFunction(count => document.querySelectorAll('.fleet-aircraft input:checked').length === count, count);
      assert.equal(await boxes.count(), count);
      if (width <= 960) {
        const navigation = page.locator('.modern-sidebar-wrapper');
        await page.getByRole('button', { name: 'Open navigation menu' }).click();
        await page.waitForTimeout(250);
        const bounds = await navigation.boundingBox();
        assert(bounds.x >= -2 && bounds.x + bounds.width <= width + 2, 'Mobile navigation must be fully inside viewport');
        await page.getByRole('button', { name: 'Close navigation menu' }).click();
      }
      const first = page.getByRole('button', { name: /^Inspect AIRCRAFT-01/ });
      await first.click();
      await page.getByRole('dialog', { name: 'AIRCRAFT-01' }).waitFor();
      assert.equal(await boxes.count(), count);
      if (count === 3 && width === 1440 && output) await page.screenshot({ path: path.join(output, `inspector-${theme}.png`) });
      await page.getByRole('button', { name: 'Close aircraft details' }).click();
      await page.getByRole('searchbox', { name: 'Find aircraft' }).fill('AIRCRAFT-01');
      assert.equal(await page.locator('.fleet-aircraft').count(), 1);
      if (count > 1) await page.getByText(`${count} selected · ${count - 1} hidden`, { exact: true }).waitFor();
      await page.getByRole('searchbox', { name: 'Find aircraft' }).fill('');
      if (count > 1) {
        await boxes.last().uncheck();
        await page.getByRole('button', { name: 'Takeoff', exact: true }).click();
        const review = page.getByRole('dialog', { name: 'Takeoff', exact: true });
        await review.waitFor();
        assert.equal(await review.getByRole('checkbox').count(), count - 1);
        if (count === 3 && width === 1440 && output) await review.screenshot({ path: path.join(output, `takeoff-review-${theme}.png`) });
        await page.getByRole('button', { name: 'Close confirmation dialog' }).click();
        await boxes.last().check();
      }
      await page.getByRole('button', { name: 'List', exact: true }).click();
      await page.locator('.fleet-board--list').waitFor();
      await page.getByRole('button', { name: 'Board', exact: true }).click();
      if (count === 3 && width === 1440) {
        await page.getByRole('button', { name: 'Map', exact: true }).click();
        await page.locator('.leaflet-container').waitFor();
        if (!allLive) await page.getByRole('button', { name: /without current position/ }).waitFor();
        if (output) await page.screenshot({ path: path.join(output, `overview-map-${theme}.png`) });
        await page.getByRole('button', { name: 'Board', exact: true }).click();
        assert.equal(await page.locator('.fleet-aircraft input:checked').count(), count);
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      const overflow = await page.evaluate(() => {
        const navigation = document.querySelector('.modern-sidebar-wrapper').getBoundingClientRect();
        return { width: innerWidth, scroll: document.documentElement.scrollWidth, scrollX, navLeft: navigation.left, navRight: navigation.right };
      });
      assert(overflow.scroll <= overflow.width + 2, `Horizontal overflow: ${JSON.stringify(overflow)}`);
      if (width > 960) assert(Math.abs(overflow.navLeft) < 2, `Desktop navigation shifted: ${JSON.stringify(overflow)}`);
      if (output) await page.screenshot({ path: path.join(output, `overview-${count}-${width}-${theme}.png`) });
      if (count === 3 && width === 1440 && output) {
        await page.getByRole('button', { name: 'Return', exact: true }).click();
        const review = page.getByRole('dialog', { name: 'Return', exact: true });
        await review.waitFor();
        await review.screenshot({ path: path.join(output, `return-review-${theme}.png`) });
        await page.getByRole('button', { name: 'Close confirmation dialog' }).click();
      }
      let soak = null;
      if (soakSeconds && count === 100 && width === 1440 && theme === 'dark') {
        const cdp = await context.newCDPSession(page);
        const heap = async () => {
          await cdp.send('HeapProfiler.collectGarbage');
          const data = await cdp.send('Runtime.getHeapUsage');
          return data.usedSize;
        };
        const startHeap = await heap(), startedAt = Date.now(), interactions = [];
        const deadline = startedAt + soakSeconds * 1000;
        while (Date.now() < deadline) {
          await page.waitForTimeout(Math.min(30000, deadline - Date.now()));
          await page.getByRole('button', { name: 'List', exact: true }).click();
          await page.getByRole('button', { name: 'Board', exact: true }).click();
          await first.click();
          await page.getByRole('button', { name: 'Close aircraft details' }).click();
          const elapsed = await page.evaluate(() => new Promise(resolve => {
            const input = document.querySelector('.fleet-aircraft input');
            const started = performance.now();
            input.click();
            requestAnimationFrame(() => resolve(performance.now() - started));
          }));
          interactions.push(elapsed);
          await boxes.first().check();
          assert.equal(await boxes.count(), 100);
          assert.equal(await page.locator('.fleet-aircraft input:checked').count(), 100);
          assert.deepEqual(errors, []);
          assert.deepEqual(writes, []);
        }
        const endHeap = await heap();
        interactions.sort((a, b) => a - b);
        soak = { seconds: Math.round((Date.now() - startedAt) / 1000), startHeap, endHeap,
          selectionP95Ms: interactions[Math.max(0, Math.ceil(interactions.length * .95) - 1)] ?? null,
          samples: interactions.length };
        assert(endHeap <= startHeap * 2 + 20 * 1024 * 1024, `Unbounded retained heap: ${JSON.stringify(soak)}`);
        console.log(JSON.stringify({ status: 'soak-passed', ...soak }));
      }
      if (count === 3 && width === 1440 && theme === 'dark') {
        await page.getByRole('button', { name: 'None', exact: true }).click();
        await page.reload();
        await page.locator('.fleet-aircraft').first().waitFor();
        assert.equal(await page.locator('.fleet-aircraft input:checked').count(), 0, 'Empty selection must restore');
        await page.getByRole('button', { name: 'All', exact: true }).click();
        stale = true;
        await page.waitForFunction(() => [...document.querySelectorAll('.fleet-aircraft')].every(node => node.dataset.current === 'false'));
        assert.equal(await page.locator('.fleet-aircraft input:checked').count(), count, 'Link loss cannot retarget');
        if (output) await page.screenshot({ path: path.join(output, 'overview-link-loss.png'), fullPage: true });
      }
      assert.deepEqual(writes, [], 'Read-only acceptance must never dispatch');
      assert.deepEqual(errors, []);
      results.push({ count, width, theme, allLive, overflow, reads, writes: writes.length, errors, soak });
      await context.close();
    }
  } finally { await browser.close(); }
  const report = { status: 'passed', scenarios: results.length, results };
  if (output) fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: report.status, scenarios: report.scenarios }));
}
run().catch(error => { console.error(error); process.exitCode = 1; });
