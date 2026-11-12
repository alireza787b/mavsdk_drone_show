#!/usr/bin/env node
/* Run only on the approved validation host against its real built UI.
 * MDS_UI_FIXTURE_ONLY=1 MDS_UI_BASE=http://127.0.0.1:3039
 * MDS_UI_EVIDENCE=/tmp/logs-ui MDS_PLAYWRIGHT_MODULE=/path/to/playwright-core
 * MDS_CHROMIUM_EXECUTABLE=/path/to/chromium node tools/validate_logs_workspace_ui.cjs
 * All GCS requests are synthetic. Native EventSource uses a private loopback
 * fixture server so a quiet Connected stream is genuinely kept open.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const http = require('node:http');
assert.equal(process.env.MDS_UI_FIXTURE_ONLY, '1', 'Refusing to run without MDS_UI_FIXTURE_ONLY=1');
const base = new URL(process.env.MDS_UI_BASE || 'http://127.0.0.1:3039');
assert(['http:', 'https:'].includes(base.protocol) && base.port !== '5030', 'Use the built UI origin, not the GCS');
const origin = base.origin;
const out = process.env.MDS_UI_EVIDENCE ? path.resolve(process.env.MDS_UI_EVIDENCE) : fs.mkdtempSync(path.join(os.tmpdir(), 'mds-logs-ui-'));
fs.mkdirSync(out, { recursive: true });
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const fleet = Array.from({ length: 100 }, (_, index) => ({ hw_id: String(index + 1), pos_id: String(index + 1),
  callsign: index === 0 ? 'ALPHA' : index === 1 ? 'BRAVO' : `AIRCRAFT ${String(index + 1).padStart(3, '0')}`, ip: `192.0.2.${index + 1}` }));
const summary = { schema_version: '1.0', parsed: true, parser: { status: 'ok', topics_present: ['vehicle_command'], observability_warnings: ['Selected-topic duration is a lower bound.'] },
  duration_sec: 42, duration_evidence: { source: 'requested_topic_timestamps', lower_bound: true, timestamp_scan_complete: false },
  commands: { vehicle_command: { samples: 3 }, vehicle_command_ack: null }, source: { date_utc: null, size_bytes: 512 }, raw_content_included: false };
const headers = now => ({ 'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true',
  'access-control-allow-methods': 'GET, POST, DELETE, OPTIONS', 'access-control-allow-headers': 'Content-Type, X-CSRF-Token, Last-Event-ID',
  'access-control-expose-headers': 'X-MDS-Server-Time, Content-Disposition, X-MDS-Export-Records, X-MDS-Export-Skipped, X-MDS-Export-Scope', 'x-mds-server-time': String(now) });

async function fixtures(context, page, state) {
  const subscribers = new Map(), counters = new Map();
  const emit = (source, message, named = null) => {
    const sequence = (counters.get(source) || 0) + (named ? 0 : 1); counters.set(source, sequence);
    for (const response of subscribers.get(source) || []) {
      if (named) response.write(`event: ${named}\ndata: ${JSON.stringify(message)}\n\n`);
      else response.write(`id: fixture-${source}:${sequence}\ndata: ${JSON.stringify({ ts: new Date().toISOString(), level: 'WARNING', component: 'coordinator', source: source === 'GCS' ? 'gcs' : 'drone', drone_id: source === 'GCS' ? null : Number(source.slice(1)), session_id: 's_20261112_100000', msg: message })}\n\n`);
    }
  };
  const server = http.createServer((request, response) => {
    if (request.method !== 'GET' || !request.url.startsWith('/stream')) { response.writeHead(404); response.end(); return; }
    const source = new URL(request.url, 'http://fixture').searchParams.get('source') || 'GCS';
    response.writeHead(200, { ...headers(Date.now()), 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' });
    response.flushHeaders();
    if (!subscribers.has(source)) subscribers.set(source, new Set()); subscribers.get(source).add(response);
    emit(source, { state: 'connected', epoch: `fixture-${source}`, coverage: 'retained_buffer', history_complete: false, retained_count: 3 }, 'status');
    emit(source, `${source} source event`); emit(source, 'Repeated warning'); emit(source, 'Repeated warning');
    const timer = setInterval(() => emit(source, { state: 'connected', heartbeat: true, epoch: `fixture-${source}`, coverage: 'live_only', history_complete: false }, 'status'), 2000);
    request.on('close', () => { clearInterval(timer); subscribers.get(source)?.delete(response); });
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const streamOrigin = `http://127.0.0.1:${server.address().port}`;
  assert.equal(typeof context.routeWebSocket, 'function', 'Playwright routeWebSocket support is required');
  await context.routeWebSocket(/.*/, socket => socket.close({ code: 1000, reason: 'Fixture only' }));
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), pathname = url.pathname, method = request.method(), now = Date.now();
    if (url.port === '5030' || pathname.startsWith('/api/')) {
      state.requests.push({ method, path: pathname });
      const cors = { ...headers(now), 'access-control-allow-headers': request.headers()['access-control-request-headers'] || 'Content-Type, X-CSRF-Token, Last-Event-ID' };
      const reply = (body, status = 200, extra = {}) => route.fulfill({ status, headers: { ...cors, ...extra }, json: body });
      if (method === 'OPTIONS') return route.fulfill({ status: 204, headers: cors });
      const match = pathname.match(/^\/api\/logs\/drone\/([^/]+)(\/.*)$/);
      const droneId = match ? decodeURIComponent(match[1]) : null, source = droneId ? `H${droneId}` : 'GCS';
      const endpoint = match ? match[2] : pathname.startsWith('/api/logs') ? pathname.slice('/api/logs'.length) : null;
      try {
        if (method === 'GET' && endpoint === '/stream') return route.continue({ url: `${streamOrigin}/stream?source=${encodeURIComponent(source)}` });
        if (method === 'GET' && endpoint === '/sources') return reply({ components: { coordinator: { category: 'gcs' } } });
        if (method === 'GET' && endpoint === '/sessions') return reply({ sessions: [{ session_id: 's_20261112_100000', size_bytes: 60000, modified: now / 1000 }] });
        if (method === 'GET' && endpoint?.startsWith('/sessions/')) {
          let entries = Array.from({ length: 600 }, (_, index) => ({ ts: new Date(Date.UTC(2026, 10, 12, 23, 59, 58) + index * 100).toISOString(), level: 'WARNING', component: 'coordinator', source: source === 'GCS' ? 'gcs' : 'drone', drone_id: droneId ? Number(droneId) : null, session_id: 's_20261112_100000', msg: `${source} historical ${index}${index % 5 === 0 ? ' needle' : ''}`, _offset: index * 100 }));
          if (url.searchParams.get('search')) entries = entries.filter(entry => entry.msg.includes(url.searchParams.get('search')));
          if (url.searchParams.get('since')) entries = entries.filter(entry => entry.ts > url.searchParams.get('since'));
          if (url.searchParams.get('until')) entries = entries.filter(entry => entry.ts <= url.searchParams.get('until'));
          const cursor = Number(url.searchParams.get('cursor') || 0), limit = Number(url.searchParams.get('limit') || 500), page = entries.slice(cursor, cursor + limit);
          return reply({ schema_version: '1.1', session_id: 's_20261112_100000', lines: page.map(({ _offset, ...entry }) => entry), count: page.length, entry_offsets: page.map(entry => entry._offset), snapshot_id: `fixture-${source}`, has_more: cursor + limit < entries.length, next_cursor: cursor + limit < entries.length ? String(cursor + limit) : null,
            coverage: { byte_start: cursor * 100, byte_end: Math.min(cursor + limit, entries.length) * 100, snapshot_size_bytes: 60000, source_size_bytes: 60000, malformed_records: 1, oversized_records: 0, incomplete_records: 0 } });
        }
        if (method === 'POST' && endpoint === '/export') {
          const body = request.postDataJSON(); state.exports.push({ droneId, ...body });
          return route.fulfill({ status: 200, headers: { ...cors, 'content-type': 'application/x-ndjson', 'content-disposition': 'attachment; filename="example-session.jsonl"', 'x-mds-export-records': '600', 'x-mds-export-skipped': '1', 'x-mds-export-scope': body.filters ? 'filtered' : 'whole_sessions' }, body: '{"msg":"Synthetic exported record"}\n' });
        }
        if (method === 'GET' && endpoint === '/ulog/policy') return reply({ policy: { storage_mode: 'file_backed', supported: true, download_supported: true, erase_all_supported: true, single_delete_supported: false, download_requires_disarmed: true, erase_requires_disarmed: true } });
        if (method === 'GET' && endpoint === '/ulog/files') return reply({ files: [{ id: 7, date_utc: '2026-11-12T10:00:00Z', size_bytes: 512 }], ulog_capability: { available: true } });
        if (method === 'GET' && endpoint === '/ulog/files/7/summary') return reply({ ...summary, hw_id: droneId, log_id: 7, timestamp: now });
        if (method === 'POST' && endpoint === '/ulog/summary') { state.uploads += 1; assert(request.headers()['content-type'].includes('multipart/form-data')); return reply(summary); }
        if (method === 'POST' && endpoint === '/ulog/files/7/download') {
          const body = request.postDataJSON(); assert(body.request_id);
          assert(!state.receipts.has(body.request_id), 'No automatic create replay');
          assert(await page.evaluate(id => Object.keys(localStorage).some(key => key.startsWith('mds:ulog-transfers:') && JSON.parse(localStorage.getItem(key)).some(record => record.requestId === id)), body.request_id), 'Recovery identity must precede native create');
          state.creates += 1;
          const job = { job_id: `fixture-signed-${source}-${state.creates}`, hw_id: droneId, log_id: 7, size_bytes: 512, status: 'ready', progress: 1, created_at: now, updated_at: now, expires_at: now + 60000, download_filename: `example-H${droneId}-7.ulg` };
          state.receipts.set(body.request_id, job); state.jobs.set(job.job_id, job);
          if (state.loseNextCreate) { state.loseNextCreate = false; return reply({ detail: { request_id: body.request_id, creation_status: 'unknown', message: 'Synthetic create response lost.' } }, 503); }
          return reply({ request_id: body.request_id, job, timestamp: now });
        }
        if (method === 'GET' && endpoint?.startsWith('/ulog/download-requests/')) {
          state.lookups += 1; const id = decodeURIComponent(endpoint.split('/').pop()), job = state.receipts.get(id);
          return reply({ request_id: id, status: job ? 'accepted' : 'unknown', job: job || null, error: job ? null : 'Unconfirmed', timestamp: now });
        }
        if (method === 'GET' && endpoint?.match(/^\/ulog\/downloads\/[^/]+\/content$/)) {
          state.contentGets += 1;
          return route.fulfill({ status: 200, headers: { ...cors, 'content-type': 'application/octet-stream', 'content-disposition': `attachment; filename="example-H${droneId}-7.ulg"` }, body: Buffer.concat([Buffer.from([85, 76, 111, 103, 1, 18, 53, 1]), Buffer.alloc(504)]) });
        }
        if (method === 'GET' && endpoint?.startsWith('/ulog/downloads/')) return reply({ job: state.jobs.get(decodeURIComponent(endpoint.split('/').pop())), timestamp: now });
        if (method !== 'GET' && method !== 'HEAD') { state.violations.push(`${method} ${pathname}`); return reply({ detail: 'Unexpected fixture mutation blocked' }, 409); }
        if (pathname === '/api/v1/auth/status') return reply({ authenticated: true, dashboard_auth_enabled: false, api_auth_enabled: false, role: state.role, user: { id: 'fixture-operator', username: 'Operator', role: state.role } });
        if (pathname === '/api/v1/system/runtime-status') return reply({ mode: 'sitl', configured_mode: 'sitl', restart_required: false });
        if (pathname === '/api/v1/config/fleet') return reply(state.emptyRoster ? [] : fleet);
        if (pathname === '/api/v1/fleet/telemetry') return reply({ telemetry: state.emptyRoster ? {} : Object.fromEntries(fleet.map(drone => [drone.hw_id, { ...drone, telemetry_available: true, update_time: now / 1000, heartbeat_last_seen: now / 1000, is_armed: false, landed_state: 1 }])), timestamp: now, display_policy: { stale_sec: 10, available_sec: 60 } });
        if (pathname === '/api/v1/git/status') return reply({ total_drones: 100, needs_sync_count: 0, unknown_count: 0 });
        if (pathname.includes('/commands/')) return reply({ commands: [] });
        return reply({});
      } catch (error) { state.fixtureErrors.push(error.stack); return reply({ detail: 'Fixture assertion failed' }, 500); }
    }
    if (url.hostname === 'fonts.googleapis.com') return route.fulfill({ contentType: 'text/css', body: '/* Fixture-only system fonts */' });
    if (url.origin !== origin || !['GET', 'HEAD'].includes(method)) { state.violations.push(`${method} ${url.origin}${pathname}`); return route.abort(); }
    if (request.isNavigationRequest() && pathname !== '/') { const response = await route.fetch({ url: `${origin}/` }); return route.fulfill({ response }); }
    return route.continue();
  });
  return { emit, close: async () => { server.closeAllConnections?.(); for (const set of subscribers.values()) for (const response of set) response.end(); await new Promise(resolve => server.close(resolve)); } };
}

async function openDetails(locator) { if (!(await locator.evaluate(element => element.open))) await locator.locator(':scope > summary').click(); }
async function clickAction(page, name) {
  let button = page.getByRole('button', { name, exact: true });
  if (!(await button.count())) { await page.locator('.operator-page-action-bar__overflow > summary').first().click(); button = page.getByRole('button', { name, exact: true }); }
  await button.click();
}
async function source(page, id) {
  await page.getByRole('button', { name: 'Choose log source', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Choose log source' });
  await dialog.getByRole('searchbox', { name: 'Find log source' }).fill(id === '1' ? 'ALPHA' : 'BRAVO');
  await dialog.getByRole('radio', { name: new RegExp(`H${id}\\b`) }).check();
  await dialog.getByRole('button', { name: 'Use source' }).click();
}

async function scenario(browser, width, theme) {
  const state = { requests: [], violations: [], fixtureErrors: [], errors: [], consoleErrors: [], receipts: new Map(), jobs: new Map(), creates: 0, lookups: 0, contentGets: 0, exports: [], uploads: 0, role: 'admin', emptyRoster: false };
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 900 : 1000 }, colorScheme: theme, deviceScaleFactor: 1, serviceWorkers: 'block', acceptDownloads: true });
  await context.addInitScript(value => { localStorage.setItem('drone-dashboard-theme', value); localStorage.setItem('mds:gcs-runtime-mode', 'sitl'); }, theme);
  const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on('pageerror', error => state.errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error' && !(message.location().url.includes('/download') && /503/.test(message.text()))) state.consoleErrors.push(message.text()); });
  const fixture = await fixtures(context, page, state), screenshots = [];
  const capture = async name => {
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name}: document overflow at ${width}`);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), theme);
    const filename = `${name}-${width}-${theme}.png`; screenshots.push(filename); await page.screenshot({ path: path.join(out, filename), fullPage: true });
  };
  try {
    await page.goto(`${origin}/logs`); await page.getByRole('heading', { name: 'Logs', exact: true }).waitFor();
    await page.getByText('Connected', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Inspect record GCS source event' }).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Inspect record Repeated warning', exact: true }).count(), 2, 'Identical repeated warnings are real distinct events');
    await capture('guide-01-live');
    await page.getByRole('button', { name: 'Inspect record GCS source event' }).click(); await capture('record-inspector'); await page.keyboard.press('Escape');
    await page.getByRole('button', { name: 'Freeze view' }).click(); fixture.emit('GCS', 'Arrived while frozen');
    await page.getByText(/1 pending/).waitFor(); assert.equal(await page.getByRole('button', { name: 'Inspect record Arrived while frozen' }).count(), 0);
    await page.getByRole('button', { name: 'Follow latest' }).click(); await page.getByRole('button', { name: 'Inspect record Arrived while frozen' }).waitFor();
    fixture.emit('GCS', { reason: 'retention', coverage: 'partial', history_complete: false, lost_count: 2 }, 'gap');
    await page.getByText(/Source coverage gaps/).waitFor(); await capture('live-gap');
    await page.getByRole('tab', { name: 'Sessions', exact: true }).click(); await page.getByText('500 shown · page 1', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Next page' }).click(); await page.getByText('100 shown · page 2', { exact: true }).waitFor();
    await capture('guide-02-sessions');
    await clickAction(page, 'Export');
    const exportDialog = page.getByRole('dialog', { name: 'Export GCS sessions' }); await exportDialog.waitFor(); await capture('guide-03-export');
    const download = page.waitForEvent('download'); await exportDialog.getByRole('button', { name: 'Prepare export' }).click(); await download;
    await exportDialog.getByText(/export coverage is incomplete/).waitFor(); assert.equal(state.exports[0].filters, undefined, 'Whole-session export is not the first loaded page');
    await exportDialog.getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('tab', { name: 'Flight logs', exact: true }).click(); await source(page, '1');
    await page.getByRole('button', { name: 'Inspect flight log 7' }).waitFor(); await capture('guide-04-inventory');
    await page.getByRole('button', { name: 'Inspect flight log 7' }).click(); let fileDialog = page.getByRole('dialog', { name: 'Flight log 7' });
    await fileDialog.getByRole('button', { name: 'Summary', exact: true }).click(); await fileDialog.getByText('42 s · partial / lower bound').waitFor();
    assert.equal(await fileDialog.getByText('Acknowledgment samples').evaluate(element => element.nextElementSibling.textContent), 'Unknown'); await capture('guide-05-summary');
    await fileDialog.getByRole('button', { name: 'Prepare download' }).click(); await openDetails(page.locator('.logs-transfer-activity'));
    await page.getByRole('link', { name: 'Save file' }).waitFor(); assert.equal(state.contentGets, 0, 'Ready does not automatically fetch content'); await capture('guide-06-ready-save');
    const rawDownload = page.waitForEvent('download'); await page.getByRole('link', { name: 'Save file' }).click(); await rawDownload;
    await page.getByText(/Browser download requested · local save is not verified/).waitFor(); assert.equal(state.contentGets, 1);
    await source(page, '2'); await page.getByRole('button', { name: 'Inspect flight log 7' }).click(); state.loseNextCreate = true;
    await page.getByRole('dialog').getByRole('button', { name: 'Prepare download' }).click(); await page.getByText(/Outcome unconfirmed: Synthetic create response lost/).waitFor();
    const creates = state.creates; await page.reload(); await page.getByRole('heading', { name: 'Logs', exact: true }).waitFor();
    const recovery = page.locator('.logs-transfer-row').first(); await recovery.getByRole('button', { name: 'Check receipt' }).click(); await recovery.getByRole('link', { name: 'Save file' }).waitFor();
    assert.equal(state.creates, creates, 'Reload recovery must not create again'); assert(state.lookups > 0); await capture('transfer-recovered');
    await page.getByRole('tab', { name: 'Flight logs', exact: true }).click();
    await page.getByLabel('Open local ULog file').setInputFiles({ name: 'example.ulg', mimeType: 'application/octet-stream', buffer: Buffer.from('ULog fixture') });
    await page.getByRole('dialog', { name: 'Local flight log' }).waitFor(); await capture('local-summary'); await page.keyboard.press('Escape');
    state.role = 'viewer'; state.emptyRoster = true; await page.reload(); await page.getByRole('heading', { name: 'Logs', exact: true }).waitFor();
    await page.getByRole('tab', { name: 'Flight logs', exact: true }).click(); await page.getByRole('button', { name: 'Choose log source' }).click();
    await page.getByText('No configured aircraft.', { exact: true }).waitFor(); assert(await page.getByRole('dialog').getByRole('button', { name: 'Use source' }).isDisabled());
    await capture('no-aircraft'); await page.keyboard.press('Escape'); assert.equal(await page.getByRole('button', { name: 'Erase onboard logs', exact: true }).count(), 0);
    assert.deepEqual(state.violations, []); assert.deepEqual(state.fixtureErrors, []); assert.deepEqual(state.errors, []); assert.deepEqual(state.consoleErrors, []);
    return { width, theme, passed: true, creates: state.creates, receiptLookups: state.lookups, contentGets: state.contentGets, uploads: state.uploads, screenshots };
  } catch (error) {
    await page.screenshot({ path: path.join(out, `failure-${width}-${theme}.png`), fullPage: true }).catch(() => {});
    fs.writeFileSync(path.join(out, `failure-${width}-${theme}.json`), JSON.stringify({ error: error.stack, ...state, receipts: [...state.receipts], jobs: [...state.jobs] }, null, 2)); throw error;
  } finally { await context.close(); await fixture.close(); }
}

async function main() {
  const browser = await chromium.launch({ headless: true, ...(process.env.MDS_CHROMIUM_EXECUTABLE ? { executablePath: process.env.MDS_CHROMIUM_EXECUTABLE } : {}), args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const results = [];
    for (const width of [1440, 900, 390]) for (const theme of ['dark', 'light']) { results.push(await scenario(browser, width, theme)); console.log(JSON.stringify({ width, theme, passed: true })); }
    fs.writeFileSync(path.join(out, 'browser-results.json'), JSON.stringify({ fixtureOnly: true, scope: 'Built UI with synthetic backend/native EventSource and system fonts; not flight clearance or proof of real-byte persistence.', results }, null, 2));
    console.log(JSON.stringify({ passed: true, evidence: out, scenarios: results.length }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
