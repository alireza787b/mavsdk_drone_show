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
const nameSuffix = process.env.MDS_OVERVIEW_NAME_SUFFIX || '';
// 720x480 CSS pixels at scale 2 exercises a 1440x960-equivalent 200% reflow.
const reflow = process.argv.includes('--zoom-reflow');
const height = reflow ? 480 : 960;
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
      console.log(JSON.stringify({ status: 'checking', count, width, height, theme, reflow }));
      const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: reflow ? 2 : 1, hasTouch: width <= 768 });
      const page = await context.newPage();
      const errors = [], writes = [], reads = {};
      let stale = false;
      const fleet = Array.from({ length: count }, (_, i) => ({ hw_id: String(i + 1), pos_id: i + 1, callsign: `AIRCRAFT-${String(i + 1).padStart(2, '0')}${nameSuffix}` }));
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
          // Presence requires a heartbeat receipt, never a telemetry timestamp.
          presence: { heartbeat_received_at_gcs_ms: Date.now() - (stale || !allLive && i === count - 1 && count > 1 ? 80000 : 1000) },
          is_armed: false, landed_state: 1, gps_fix_type: 4, satellites_visible: 17, global_position_valid: true,
          flight_mode: 50593792, readiness_status: 'ready', is_ready_to_arm: true, preflight_blockers: [],
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
          'access-control-expose-headers': 'x-mds-server-time',
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
      const rail = page.locator('.fleet-action-rail[aria-label="Selected aircraft actions"]');
      const scope = rail.getByRole('button', { name: 'Choose command aircraft', exact: true });
      const show = page.getByRole('combobox', { name: 'Show aircraft', exact: true });
      const commandCount = async expected => {
        await page.waitForFunction(expected => document.querySelector('[aria-label="Choose command aircraft"]')?.getAttribute('data-recipient-count') === String(expected), expected);
        assert.equal(await scope.getAttribute('data-recipient-count'), String(expected));
      };
      const openPicker = async () => {
        await scope.click();
        const dialog = page.getByRole('dialog', { name: 'Command aircraft', exact: true });
        await dialog.waitFor();
        const bounds = await dialog.boundingBox();
        assert(bounds && bounds.x >= -2 && bounds.x + bounds.width <= width + 2
          && bounds.y >= -2 && bounds.y + bounds.height <= height + 2, 'Command aircraft picker must remain inside the viewport');
        const search = dialog.getByRole('searchbox', { name: 'Find command aircraft', exact: true });
        assert(await search.evaluate(input => input === document.activeElement), 'Picker starts on search, not Apply');
        const row = dialog.locator('.aircraft-choice-row').first();
        if (await row.count()) assert(await row.evaluate(element => {
          const box = element.querySelector('input').getBoundingClientRect();
          const name = element.querySelector('strong').getBoundingClientRect();
          return getComputedStyle(element).display === 'flex' && box.width <= 22 && name.left > box.right;
        }), 'Controlled aircraft rows keep checkbox and identity aligned');
        return dialog;
      };
      const applyPicker = async (dialog, expected) => {
        await dialog.getByRole('button', { name: `Use ${expected} aircraft`, exact: true }).click();
        await dialog.waitFor({ state: 'hidden' });
        await commandCount(expected);
      };
      const selectAll = async () => {
        const dialog = await openPicker();
        const all = dialog.getByRole('button', { name: 'All configured', exact: true, includeHidden: true });
        if (!await all.isVisible()) {
          await dialog.locator('summary[aria-label="More command aircraft options"]').click();
        }
        await all.click();
        await applyPicker(dialog, count);
      };
      const includeName = id => `Include ${fleet[Number(id) - 1].callsign} (H${id})`;
      const assertRecipients = async ids => {
        const dialog = await openPicker();
        const boxes = dialog.getByRole('checkbox', { name: /^Include / });
        assert.equal(await boxes.count(), count, 'Picker includes the configured roster, not only displayed aircraft');
        const checked = await boxes.evaluateAll(nodes => nodes.filter(node => node.checked).map(node => node.getAttribute('aria-label')).sort());
        assert.deepEqual(checked, ids.map(includeName).sort());
        await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
      };
      const initialCount = allLive || count === 1 ? count : count - 1;
      await commandCount(initialCount);
      assert.equal(await page.locator('.fleet-aircraft input[type="checkbox"]').count(), 0, 'Aircraft cards inspect; they never edit recipients');
      assert.equal(await page.locator('.fleet-aircraft__recipient').count(), initialCount);
      await assertRecipients(fleet.slice(0, initialCount).map(item => item.hw_id));
      const available = await openPicker();
      // Native keyboard traversal wraps inside the modal in both directions.
      const firstFocus = available.getByRole('button', { name: 'Close confirmation dialog', exact: true });
      const apply = available.getByRole('button', { name: `Use ${initialCount} aircraft`, exact: true });
      await apply.focus();
      await page.keyboard.press('Tab');
      assert(await firstFocus.evaluate(button => button === document.activeElement), 'Tab wraps inside picker');
      await page.keyboard.press('Shift+Tab');
      assert(await apply.evaluate(button => button === document.activeElement), 'Shift+Tab wraps inside picker');
      await available.getByRole('button', { name: 'Use available now', exact: true }).click();
      if (count === 3 && [390, 1440].includes(width) && output) await available.screenshot({ path: path.join(output, `command-aircraft-${width}-${theme}.png`) });
      await applyPicker(available, initialCount);
      // Available is a one-time default snapshot. Broader scope is deliberate.
      await selectAll();
      await show.selectOption('all');
      assert.equal(await page.locator('.fleet-aircraft').count(), count);
      const cancelled = await openPicker();
      await cancelled.getByRole('checkbox', { name: includeName('1'), exact: true }).uncheck();
      await cancelled.getByRole('button', { name: 'Cancel', exact: true }).click();
      assert(await scope.evaluate(button => button === document.activeElement), 'Cancel restores recipient-control focus');
      await commandCount(count);
      const guide = await page.locator('.route-docs-shortcut a').boundingBox();
      const alerts = await page.locator('.fleet-alerts__trigger').boundingBox();
      assert(guide && guide.width >= 44 && guide.height >= 44, 'Page guide must retain a touch-sized target');
      assert(alerts && !(guide.x < alerts.x + alerts.width && guide.x + guide.width > alerts.x
        && guide.y < alerts.y + alerts.height && guide.y + guide.height > alerts.y), 'Page guide must not overlap Alerts');
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
      await page.getByRole('dialog', { name: fleet[0].callsign, exact: true }).waitFor();
      await commandCount(count);
      if (count === 3 && width === 1440 && output) await page.screenshot({ path: path.join(output, `inspector-${theme}.png`) });
      await page.getByRole('button', { name: 'Close aircraft details' }).click();
      await page.getByRole('dialog', { name: fleet[0].callsign, exact: true }).waitFor({ state: 'hidden' });
      await page.getByRole('searchbox', { name: 'Find aircraft' }).fill('AIRCRAFT-01');
      try { await page.waitForFunction(() => document.querySelectorAll('.fleet-aircraft').length === 1); }
      catch (error) {
        if (output) await page.screenshot({ path: path.join(output, `search-failure-${count}-${width}-${theme}.png`) });
        throw new Error(`${error.message}\n${JSON.stringify({ query: await page.getByRole('searchbox', { name: 'Find aircraft' }).inputValue(),
          cards: await page.locator('.fleet-aircraft__identity').allTextContents(), errors })}`);
      }
      assert.equal(await page.locator('.fleet-aircraft').count(), 1);
      if (count > 1) {
        const hidden = rail.getByRole('button', { name: `Show ${count - 1} command aircraft outside this view`, exact: true });
        await hidden.waitFor();
        await commandCount(count);
        await hidden.click();
        await page.waitForFunction(count => document.querySelectorAll('.fleet-aircraft').length === count, count);
        assert.equal(await page.locator('.fleet-aircraft').count(), count, 'Show hidden recipients changes display only');
        await commandCount(count);
      } else await page.getByRole('searchbox', { name: 'Find aircraft' }).fill('');
      if (count > 1) {
        const picker = await openPicker();
        await picker.getByRole('searchbox', { name: 'Find command aircraft', exact: true }).fill(fleet[count - 1].callsign);
        await picker.getByRole('checkbox', { name: includeName(String(count)), exact: true }).uncheck();
        await applyPicker(picker, count - 1);
        await rail.getByRole('button', { name: 'Takeoff', exact: true }).click();
        const review = page.getByRole('dialog', { name: 'Takeoff', exact: true });
        await review.waitFor();
        const reviewed = review.getByRole('checkbox', { name: /^Include / });
        assert.equal(await reviewed.count(), count - 1, 'Takeoff owns the exact initiating recipient snapshot');
        assert.deepEqual(await reviewed.evaluateAll(nodes => nodes.map(node => node.getAttribute('aria-label')).sort()), fleet.slice(0, count - 1).map(item => includeName(item.hw_id)).sort());
        // Takeoff-local exclusions do not edit Overview's saved command scope.
        await reviewed.first().uncheck();
        await commandCount(count - 1);
        await reviewed.first().check();
        if (count === 3 && width === 1440 && output) await review.screenshot({ path: path.join(output, `takeoff-review-${theme}.png`) });
        await review.getByRole('button', { name: 'Close confirmation dialog' }).click();
        await assertRecipients(fleet.slice(0, count - 1).map(item => item.hw_id));
        await selectAll();
      }
      await page.getByRole('button', { name: 'List', exact: true }).click();
      await page.locator('.fleet-board--list').waitFor();
      await page.getByRole('button', { name: 'Board', exact: true }).click();
      if (count === 3 && width === 1440) {
        await page.getByRole('button', { name: 'Map', exact: true }).click();
        await page.locator('.leaflet-container').waitFor();
        if (!allLive) {
          await page.getByRole('button', { name: /without current position/ }).waitFor();
          await rail.getByRole('button', { name: 'Show 1 command aircraft outside this map', exact: true }).waitFor();
        }
        if (output) await page.screenshot({ path: path.join(output, `overview-map-${theme}.png`) });
        if (!allLive) {
          await rail.getByRole('button', { name: 'Show 1 command aircraft outside this map', exact: true }).click();
          await page.locator('.fleet-aircraft').first().waitFor();
          await commandCount(count);
          assert.equal(await page.locator('.fleet-aircraft__recipient').count(), count);
          await page.getByRole('button', { name: 'Map', exact: true }).click();
          await page.getByRole('button', { name: /without current position/ }).click();
          await page.locator('.fleet-board--list').waitFor();
          assert.equal(await page.locator('.fleet-aircraft').count(), 1, 'Unmapped lookup shows the missing-position aircraft');
          await commandCount(count);
        }
        await page.getByRole('button', { name: 'Board', exact: true }).click();
        await show.selectOption('all');
        assert.equal(await page.locator('.fleet-aircraft__recipient').count(), count);
        await assertRecipients(fleet.map(item => item.hw_id));
      }
      await page.evaluate(() => window.scrollTo(0, 0));
      if (allLive) await show.selectOption('available');
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
        if (allLive) {
          // Beginner guide retains one consistent full-fleet scenario. The
          // reduced-roster Takeoff proof above is not its illustrative step.
          await rail.getByRole('button', { name: 'Takeoff', exact: true }).click();
          const takeoff = page.getByRole('dialog', { name: 'Takeoff', exact: true });
          await takeoff.getByText('Ready', { exact: true }).nth(count - 1).waitFor();
          await takeoff.screenshot({ path: path.join(output, `takeoff-review-${theme}.png`) });
          await takeoff.getByRole('button', { name: 'Close confirmation dialog' }).click();
        }
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
          const picker = await openPicker();
          const elapsed = await picker.getByRole('checkbox', { name: includeName('1'), exact: true }).evaluate(input => new Promise(resolve => {
            const started = performance.now();
            input.click();
            requestAnimationFrame(() => resolve(performance.now() - started));
          }));
          interactions.push(elapsed);
          await picker.getByRole('checkbox', { name: includeName('1'), exact: true }).check();
          assert.equal(await picker.getByRole('checkbox', { name: /^Include / }).count(), 100);
          await applyPicker(picker, 100);
          assert.equal(await page.locator('.fleet-aircraft__recipient').count(), 100);
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
        const picker = await openPicker();
        await picker.getByRole('button', { name: 'Clear command aircraft', exact: true }).click();
        await applyPicker(picker, 0);
        await page.reload();
        await page.locator('.fleet-aircraft').first().waitFor();
        await commandCount(0);
        assert.equal(await page.locator('.fleet-aircraft__recipient').count(), 0, 'Empty selection must restore');
        await selectAll();
        await show.selectOption('all');
        await rail.getByRole('button', { name: 'Return', exact: true }).click();
        const review = page.getByRole('dialog', { name: 'Return', exact: true });
        await review.waitFor();
        const frozenNames = await review.locator('.fleet-review-targets li').allTextContents();
        assert.equal(frozenNames.length, count);
        stale = true;
        await page.waitForFunction(count => {
          const cards = [...document.querySelectorAll('.fleet-aircraft')];
          return cards.length === count && cards.every(node => node.dataset.current === 'false');
        }, count);
        assert.deepEqual(await review.locator('.fleet-review-targets li').allTextContents(), frozenNames, 'Link loss cannot retarget the frozen review');
        await commandCount(count);
        await review.getByRole('button', { name: 'Close confirmation dialog' }).click();
        assert.equal(await page.locator('.fleet-aircraft__recipient').count(), count, 'Link loss cannot retarget Overview');
        await assertRecipients(fleet.map(item => item.hw_id));
        if (output) await page.screenshot({ path: path.join(output, 'overview-link-loss.png'), fullPage: true });
      }
      assert.deepEqual(writes, [], 'Read-only acceptance must never dispatch');
      assert.deepEqual(errors, []);
      results.push({ count, width, height, theme, allLive, reflow, longNames: Boolean(nameSuffix), overflow, reads, writes: writes.length, errors, soak });
      await context.close();
    }
  } finally { await browser.close(); }
  const report = { status: 'passed', scenarios: results.length, results };
  if (output) fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ status: report.status, scenarios: report.scenarios }));
}
run().catch(error => { console.error(error); process.exitCode = 1; });
