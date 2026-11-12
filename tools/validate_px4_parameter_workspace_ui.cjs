#!/usr/bin/env node
/* Real-built dashboard, synthetic GCS only. Never point this at aircraft.
 * Run on the approved validation host after building/serving the dashboard:
 * MDS_UI_FIXTURE_ONLY=1 MDS_UI_BASE=http://127.0.0.1:3039 \
 * MDS_UI_EVIDENCE=/tmp/px4-ui-evidence \
 * MDS_PLAYWRIGHT_MODULE=/path/to/playwright-core \
 * MDS_CHROMIUM_EXECUTABLE=/path/to/chromium \
 * node tools/validate_px4_parameter_workspace_ui.cjs
 * No authentication, parameter, command, or other backend request is forwarded.
 */
'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

assert.equal(process.env.MDS_UI_FIXTURE_ONLY, '1', 'Refusing to run without MDS_UI_FIXTURE_ONLY=1');
const base = new URL(process.env.MDS_UI_BASE || 'http://127.0.0.1:3039');
assert(['http:', 'https:'].includes(base.protocol), 'MDS_UI_BASE must be an HTTP(S) UI origin');
assert.notEqual(base.port, '5030', 'MDS_UI_BASE must serve the built UI, not the GCS');
const origin = base.origin;
const evidence = process.env.MDS_UI_EVIDENCE ? path.resolve(process.env.MDS_UI_EVIDENCE)
  : fs.mkdtempSync(path.join(os.tmpdir(), 'mds-px4-ui-'));
fs.mkdirSync(evidence, { recursive: true });
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const API = '/api/v1/px4-params';
const PARAMETER = 'MPC_XY_VEL_MAX';
const EXACT = '8.123456789';
const fleet = ['1', '2'].map(id => ({ hw_id: id, pos_id: id, callsign: id === '1' ? 'ALPHA' : 'BRAVO',
  ip: `192.0.2.${id}`, mavlink_port: '14540' }));
const entriesKey = row => `${row.component_id || 1}:${row.name}`;
const clone = value => JSON.parse(JSON.stringify(value));
const digest = value => crypto.createHash('sha256').update(JSON.stringify(value)).digest('hex');

function fixtureState() {
  const rows = [{ component_id: 1, name: PARAMETER, value_type: 'float', value: 6.123456789,
    default_value: 8, decimal_places: null, min_value: 0, max_value: 20, unit: 'm/s', writable: true,
    group: 'Multicopter Position Control', short_description: 'Horizontal velocity limit', reboot_required: false,
    metadata_authority: 'reference_only', authoritative_fields: [], metadata_sources: ['px4_docs_cache'], enum_values: [] },
  ...Array.from({ length: 2048 }, (_, index) => ({ component_id: 1, name: `TEST_${String(index).padStart(4, '0')}`,
    value_type: 'float', value: index / 10, default_value: 0, decimal_places: 2, writable: true,
    group: index < 1000 ? 'Example group A' : 'Example group B', reboot_required: null,
    metadata_authority: 'unavailable', authoritative_fields: [], metadata_sources: [], enum_values: [] }))];
  return { rows, values: new Map(fleet.map(drone => [drone.hw_id, new Map(rows.map(row => [entriesKey(row), row.value]))])),
    reviews: new Map(), jobs: new Map(), keys: new Map(), requests: [], violations: [], fixtureErrors: [],
    consoleErrors: [], expectedConsoleErrors: [], pageErrors: [], snapshots: 0, applyPosts: 0, lookupGets: 0,
    profileGets: 0, imports: 0, nextOutcome: 'verified', screenshots: [] };
}

function profile(state) {
  return { profile_id: 'sample_baseline', name: 'Sample fleet baseline', description: 'Synthetic demonstration values, not a flight recommendation.',
    source: 'repo', recommended_scope: 'selected', tags: ['example'], updated_at: Date.now(),
    entries: state.rows.slice(0, 12).map(row => ({ component_id: row.component_id, name: row.name, value_type: row.value_type, value: row.value + 1 })) };
}

function snapshot(state, id) {
  state.snapshots += 1;
  return { snapshot: { snapshot_id: `fixture-snapshot-${id}-${state.snapshots}`, hw_id: id, component_id: 1,
    px4_docs_version: 'main', total_params: state.rows.length, created_at: Date.now() - (state.snapshotAgeMs || 0), stale_after_ms: 60000,
    metadata_quality: 'reference_only', metadata_sources: ['px4_docs_cache'],
    metadata_warning: 'Reference-only defaults and descriptions; live values come from the aircraft fixture.' },
  rows: state.rows.map(row => ({ ...row, value: state.values.get(id).get(entriesKey(row)) })) };
}

function nativeResult(entry, outcome) {
  const verified = outcome === 'verified';
  return { component_id: entry.component_id, name: entry.name, value_type: entry.value_type, requested_value: entry.desired_value,
    actual_value: verified ? entry.desired_value : null, applied: verified, verified, outcome,
    write_acknowledged: verified, readback_status: verified ? 'matched' : 'unavailable',
    error_phase: verified ? null : 'write', error: verified ? null : 'Synthetic transport interruption; write outcome unconfirmed.' };
}

async function installFixtures(context, state, page) {
  assert.equal(typeof context.routeWebSocket, 'function', 'Use Playwright with routeWebSocket support; fixture isolation must cover WebSockets');
  await context.routeWebSocket(/.*/, socket => {
    state.requests.push({ method: 'WEBSOCKET_BLOCKED', path: new URL(socket.url()).pathname });
    socket.close({ code: 1000, reason: 'Fixture-only validation' });
  });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), pathname = url.pathname;
    // This branch precedes every other branch. No port-5030 request can continue
    // or use route.fetch, including unexpected requests and CORS preflights.
    if (url.port === '5030' || pathname.startsWith('/api/v1/')) {
      const now = Date.now(), method = request.method();
      const headers = { 'access-control-allow-origin': origin, 'access-control-allow-credentials': 'true',
        'access-control-allow-methods': 'GET, HEAD, POST, OPTIONS',
        'access-control-allow-headers': request.headers()['access-control-request-headers'] || 'Content-Type, X-CSRF-Token',
        'access-control-expose-headers': 'X-MDS-Server-Time', 'x-mds-server-time': String(now) };
      state.requests.push({ method, path: pathname });
      if (method === 'OPTIONS') return route.fulfill({ status: 204, headers });
      const fulfill = (body, status = 200) => route.fulfill({ status, json: body, headers });
      try {
        if (method === 'POST') {
          const body = request.postDataJSON();
          if (pathname === `${API}/snapshots`) {
            assert(body.hw_ids.every(id => state.values.has(id)), 'Snapshot only the synthetic fleet');
            if (state.failNextSnapshot) {
              state.failNextSnapshot = false;
              return fulfill({ detail: 'Synthetic aircraft unavailable.' }, 503);
            }
            return fulfill({ snapshots: body.hw_ids.map(id => snapshot(state, id)), errors: [], total_targets: body.hw_ids.length, timestamp: now });
          }
          if (pathname === `${API}/reviews`) {
            assert(body.verify_readback === true && body.hw_ids.length > 0);
            assert(body.hw_ids.every(id => state.values.has(id)), 'Review only the synthetic fleet');
            const review = { review_id: `fixture-review-${state.reviews.size + 1}`, review_hash: digest(body),
              runtime_binding: 'fixture-sitl', source: body.source, verify_readback: true, created_at: now, expires_at: now + 60000,
              hw_ids: [...body.hw_ids], excluded_hw_ids: [...(body.excluded_hw_ids || [])], blocked: false, warnings: [],
              profile_id: body.profile_id || null, profile_hash: body.profile_id ? digest(profile(state)) : null,
              targets: body.hw_ids.map(id => {
                const changes = body.entries.filter(entry => state.values.get(id).get(entriesKey(entry)) !== entry.value)
                  .map(entry => ({ component_id: entry.component_id, name: entry.name, value_type: entry.value_type,
                    current_value: state.values.get(id).get(entriesKey(entry)) ?? null, desired_value: entry.value,
                    changed: true, reboot_required: false, metadata_sources: ['px4_docs_cache'] }));
                return { hw_id: id, component_id: 1, snapshot_id: `fixture-review-snapshot-${id}-${state.reviews.size + 1}`,
                  changes, unchanged_count: body.entries.length - changes.length, blockers: [], warnings: [] };
              }) };
            state.reviews.set(review.review_id, review);
            return fulfill(review);
          }
          if (pathname === `${API}/patch-jobs`) {
            state.applyPosts += 1;
            assert.deepEqual(Object.keys(body).sort(), ['idempotency_key', 'review_hash', 'review_id']);
            const review = state.reviews.get(body.review_id);
            assert(review && review.review_hash === body.review_hash, 'Apply only an existing frozen review');
            assert(!state.keys.has(body.idempotency_key), 'The UI must not replay an apply request');
            const savedBeforeDispatch = await page.evaluate(key => Object.keys(localStorage).some(storageKey => {
              if (!storageKey.startsWith('mds:px4-parameters:')) return false;
              try { return JSON.parse(localStorage.getItem(storageKey)).some(receipt => receipt.idempotencyKey === key); } catch (_) { return false; }
            }), body.idempotency_key);
            assert(savedBeforeDispatch, 'Persist the exact recovery identity before apply');
            const lost = state.nextOutcome === 'lost'; state.nextOutcome = 'verified';
            const job = { job_id: `fixture-job-${state.jobs.size + 1}`, review_id: review.review_id, review_hash: review.review_hash,
              idempotency_key: body.idempotency_key, runtime_binding: 'fixture-sitl', source: review.source, terminal: true,
              status: lost ? 'unknown' : 'completed', verify_readback: true, total_targets: review.hw_ids.length,
              completed_targets: lost ? 0 : review.hw_ids.length, failed_targets: 0, unknown_targets: lost ? review.hw_ids.length : 0,
              created_at: now, updated_at: now, completed_at: now,
              results: review.targets.map(target => {
                if (!lost) target.changes.forEach(entry => state.values.get(target.hw_id).set(entriesKey(entry), entry.desired_value));
                return { hw_id: target.hw_id, applied: !lost, verified: !lost, outcome: lost ? 'unknown' : 'verified',
                  error: lost ? 'Synthetic write outcome unconfirmed.' : null,
                  result: { source: review.source, applied_count: lost ? 0 : target.changes.length,
                    verified_count: lost ? 0 : target.changes.length, failed_count: 0, timestamp: now,
                    results: target.changes.map(entry => nativeResult(entry, lost ? 'unknown' : 'verified')) } };
              }) };
            state.jobs.set(job.job_id, job); state.keys.set(body.idempotency_key, job.job_id);
            // Deliberately hide this accepted fixture receipt from the initial
            // response. Reload must recover by GET, never repeat the POST.
            return lost ? fulfill({ detail: 'Synthetic apply response lost after acceptance.' }, 503) : fulfill(job, 202);
          }
          if (pathname === `${API}/diff`) {
            const id = body.snapshot_id.includes('-2-') ? '2' : '1';
            const differences = body.desired_entries.map(entry => ({ ...entry, current_value: state.values.get(id).get(entriesKey(entry)),
              desired_value: entry.value, changed: state.values.get(id).get(entriesKey(entry)) !== entry.value }));
            return fulfill({ snapshot_id: body.snapshot_id, total_changed: differences.filter(entry => entry.changed).length,
              differences: body.include_unchanged ? differences : differences.filter(entry => entry.changed), timestamp: now });
          }
          if (pathname === `${API}/imports/qgc`) {
            state.imports += 1;
            const entries = [], warnings = [];
            body.content.split(/\r?\n/).forEach((line, index) => {
              if (!line.trim() || line.startsWith('#')) return;
              const [, component, name, value, type] = line.trim().split(/\s+/);
              if (!['6', '9'].includes(type)) { warnings.push({ line: index + 1, message: 'Unsupported parameter type' }); return; }
              entries.push({ component_id: Number(component), name, value_type: type === '6' ? 'int' : 'float', value: Number(value) });
            });
            return fulfill({ source: 'qgc_import', entries, warnings, total_entries: entries.length, skipped_count: warnings.length, timestamp: now });
          }
          state.violations.push(`${method} ${pathname}`);
          return fulfill({ detail: 'Fixture isolation blocked an unexpected mutation.' }, 409);
        }
        if (!['GET', 'HEAD'].includes(method)) {
          state.violations.push(`${method} ${pathname}`);
          return fulfill({ detail: 'Fixture isolation blocked an unexpected method.' }, 409);
        }
        if (pathname.startsWith(`${API}/patch-jobs/by-idempotency/`)) {
          state.lookupGets += 1;
          const key = decodeURIComponent(pathname.slice(`${API}/patch-jobs/by-idempotency/`.length));
          const job = state.jobs.get(state.keys.get(key));
          return fulfill(job || { detail: 'No fixture receipt found.' }, job ? 200 : 404);
        }
        if (pathname.startsWith(`${API}/patch-jobs/`)) {
          state.lookupGets += 1;
          const job = state.jobs.get(decodeURIComponent(pathname.slice(`${API}/patch-jobs/`.length)));
          return fulfill(job || { detail: 'No fixture job found.' }, job ? 200 : 404);
        }
        if (pathname === `${API}/policy`) return fulfill({ subsystem: 'px4_params', docs: { provider: 'px4', version: 'main' },
          metadata: {}, mutations: { require_disarmed: true, supported_component_ids: [1], supports_batch_apply: true, supports_qgc_import: true, supports_mds_profiles: true } });
        if (pathname === `${API}/profiles`) return fulfill({ profiles: [{ ...profile(state), entry_count: profile(state).entries.length }], total_profiles: 1, timestamp: now });
        if (pathname === `${API}/profiles/sample_baseline`) { state.profileGets += 1; return fulfill(profile(state)); }
        if (pathname === '/api/v1/auth/status') return fulfill({ authenticated: true, dashboard_auth_enabled: false, api_auth_enabled: false,
          user: { username: 'Operator', role: 'admin' }, role: 'admin' });
        if (pathname === '/api/v1/system/runtime-status') return fulfill({ mode: 'sitl', configured_mode: 'sitl', restart_required: false });
        if (pathname === '/api/v1/config/fleet') return fulfill(fleet);
        if (pathname === '/api/v1/config/swarm') return fulfill({ assignments: fleet.map((drone, index) => ({ hw_id: drone.hw_id, follow: index ? '1' : '0', offset_n: index ? -6 : 0, offset_e: 0, offset_alt: 0, body_coord: false })) });
        if (pathname === '/api/v1/fleet/telemetry') return fulfill({ telemetry: Object.fromEntries(fleet.map(drone => [drone.hw_id, {
          ...drone, telemetry_available: true, update_time: now / 1000, heartbeat_last_seen: now / 1000,
          is_armed: false, landed_state: 1, flight_mode: 50593792, readiness_status: 'ready', preflight_blockers: [],
        }])), timestamp: now, display_policy: { stale_sec: 10, available_sec: 60 } });
        if (pathname === '/api/v1/git/status') return fulfill({ total_drones: 2, needs_sync_count: 0, unknown_count: 0 });
        if (pathname === '/api/v1/git/info') return fulfill({ branch: 'fixture', commit: 'fixture', repo_url: '', status: 'clean' });
        if (pathname.includes('/commands/')) return fulfill({ commands: [] });
        return fulfill({}); // Read-only shell resources remain synthetic, too.
      } catch (error) {
        state.fixtureErrors.push(`${method} ${pathname}: ${error.stack}`);
        return fulfill({ detail: 'Fixture assertion failed; inspect the evidence report.' }, 500);
      }
    }
    // The real index requests Google font CSS. Keep this validator portable
    // and offline: exercise the app's system-font fallback, not a third-party
    // CDN dependency. This is not a forwarded GCS/backend request.
    if (url.hostname === 'fonts.googleapis.com' && request.method() === 'GET') {
      state.requests.push({ method: 'FONT_CSS_FIXTURE', path: pathname });
      return route.fulfill({ status: 200, contentType: 'text/css', body: '/* Fixture-only: system-font fallback. */' });
    }
    if (url.hostname === 'api.mapbox.com' && request.method() === 'HEAD') {
      state.requests.push({ method: 'MAP_PROVIDER_PROBE_FIXTURE', path: pathname });
      return route.fulfill({ status: 200, headers: { 'access-control-allow-origin': origin } });
    }
    if (url.origin !== origin || !['GET', 'HEAD'].includes(request.method())) {
      state.violations.push(`${request.method()} external/non-static ${url.origin}${pathname}`);
      return route.abort('blockedbyclient');
    }
    if (request.isNavigationRequest() && pathname !== '/') {
      const response = await route.fetch({ url: `${origin}/` });
      return route.fulfill({ response });
    }
    return route.continue(); // Only same-origin static UI reads reach the server.
  });
}

async function openDetails(locator) {
  if (!(await locator.evaluate(element => element.open))) await locator.locator(':scope > summary').click();
}

async function choose(page, id) {
  await page.getByRole('button', { name: 'Choose aircraft', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Choose aircraft', exact: true });
  await dialog.getByRole('radio', { name: new RegExp(`H${id}\\b`) }).check();
  await dialog.getByRole('button', { name: 'Inspect aircraft', exact: true }).click();
  await page.getByText('Snapshot current', { exact: true }).waitFor();
}

async function inspect(page) {
  await page.getByRole('searchbox', { name: 'Find parameter', exact: true }).fill(PARAMETER);
  await page.getByRole('button', { name: `Inspect ${PARAMETER}`, exact: true }).click();
  const dialog = page.getByRole('dialog', { name: PARAMETER, exact: true });
  await dialog.waitFor();
  return dialog;
}

async function scenario(browser, width, theme) {
  const state = fixtureState();
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 900 : 1000 }, colorScheme: theme,
    deviceScaleFactor: 1, serviceWorkers: 'block' });
  await context.addInitScript(value => {
    localStorage.setItem('drone-dashboard-theme', value);
    localStorage.setItem('mds:gcs-runtime-mode', 'sitl');
  }, theme);
  const page = await context.newPage();
  page.setDefaultTimeout(20000); page.setDefaultNavigationTimeout(30000);
  page.on('pageerror', error => state.pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() !== 'error') return;
    const text = message.text(), location = message.location().url || '';
    if (location.includes(`${API}/patch-jobs`) && /503/.test(text)) state.expectedConsoleErrors.push(text);
    else state.consoleErrors.push({ text, location });
  });
  await installFixtures(context, state, page);
  const capture = async name => {
    const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth,
      theme: document.documentElement.dataset.theme,
      panels: [...document.querySelectorAll('[role="dialog"]')].map(element => {
        const rect = element.getBoundingClientRect(); return { left: rect.left, right: rect.right, width: rect.width };
      }) }));
    assert(layout.document <= layout.viewport + 1, `${name}: document overflow ${layout.document} > ${layout.viewport}`);
    assert.equal(layout.theme, theme, `${name}: theme was applied by the real app`);
    layout.panels.forEach(panel => assert(panel.left >= -1 && panel.right <= layout.viewport + 1, `${name}: dialog overflow`));
    const filename = `${name}-${width}-${theme}.png`;
    await page.screenshot({ path: path.join(evidence, filename), fullPage: true }); state.screenshots.push(filename);
  };
  const waitSavedJob = jobId => page.waitForFunction(id => Object.keys(localStorage).some(key => {
    if (!key.startsWith('mds:px4-parameters:')) return false;
    try { return JSON.parse(localStorage.getItem(key)).some(receipt => receipt.job?.job_id === id); } catch (_) { return false; }
  }), jobId);
  try {
    await page.goto(`${origin}/px4-parameters`);
    await page.getByRole('heading', { name: 'PX4 Parameters', exact: true }).waitFor();
    await choose(page, '1');
    await capture('parameters-list');
    if (width === 1440) {
      assert(await page.locator('.px4-grid').isVisible(), 'Wide desktop keeps the real DataGrid');
      assert(await page.locator('.MuiDataGrid-row').count() < 200, '2,049 parameters must remain virtualized/paginated');
    } else if (width === 390) assert(await page.locator('.px4-grid').isVisible(), 'Phone keeps the virtualized List by default');
    let dialog = await inspect(page);
    assert(await dialog.getByRole('button', { name: 'Close', exact: true }).evaluate(element => element === document.activeElement), 'Accessible inspector starts focus on Close');
    await capture('guide-01-inspect');
    await dialog.getByRole('button', { name: 'Edit value', exact: true }).click();
    const editor = dialog.getByRole('textbox', { name: `New value for ${PARAMETER}`, exact: true });
    assert.equal(await editor.inputValue(), '6.123456789', 'Editing must not use display-rounded precision');
    await editor.fill(EXACT); await capture('guide-02-edit');
    await dialog.getByRole('button', { name: 'Review change', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Prepare parameter changes', exact: true });
    await dialog.getByRole('button', { name: 'Close', exact: true }).click();
    await choose(page, '2');
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByRole('button', { name: 'Refresh', exact: true }).waitFor();
    await page.getByRole('button', { name: 'Review changes', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Prepare parameter changes', exact: true });
    assert(await dialog.getByRole('checkbox', { name: 'Apply to ALPHA · H1', exact: true }).isChecked(), 'Inspection/refresh must preserve H1 draft target');
    assert.equal(await dialog.getByRole('checkbox', { name: 'Apply to BRAVO · H2', exact: true }).isChecked(), false);
    await dialog.getByRole('button', { name: 'Prepare review', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Review parameter changes', exact: true });
    await dialog.waitFor();
    const reviewed = [...state.reviews.values()].at(-1);
    assert.deepEqual(reviewed.hw_ids, ['1']); assert.equal(reviewed.targets[0].changes[0].desired_value, Number(EXACT));
    await capture('guide-03-review');
    await dialog.getByRole('button', { name: 'Apply 1 change to 1 aircraft', exact: true }).click();
    await waitSavedJob('fixture-job-1');
    await openDetails(page.locator('.px4-activity').first());
    await openDetails(page.locator('.px4-operation').first());
    assert(await page.locator('.px4-operation').first().getByText('Verified', { exact: true }).first().isVisible());
    await capture('guide-04-results');

    // A second target has an intentionally lost POST response. The saved key
    // survives reload, and only read-only lookup may reconcile it.
    dialog = await inspect(page);
    await dialog.getByRole('button', { name: 'Edit value', exact: true }).click();
    await dialog.getByRole('textbox', { name: `New value for ${PARAMETER}`, exact: true }).fill('9.7654321');
    await dialog.getByRole('button', { name: 'Review change', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Prepare review', exact: true }).click();
    state.nextOutcome = 'lost';
    await page.getByRole('dialog').getByRole('button', { name: 'Apply 1 change to 1 aircraft', exact: true }).click();
    await page.getByText(/Outcome unconfirmed:.*Synthetic apply response lost/).waitFor();
    const applyCount = state.applyPosts;
    await capture('unknown-before-reload');
    await page.reload();
    await page.getByRole('heading', { name: 'PX4 Parameters', exact: true }).waitFor();
    const unknownOperation = page.locator('.px4-operation').first();
    await unknownOperation.getByRole('button', { name: 'Check receipt', exact: true }).click();
    await waitSavedJob('fixture-job-2');
    assert.equal(state.applyPosts, applyCount, 'Reload/recovery must never replay parameter writes');
    assert(state.lookupGets > 0, 'Uncertain recovery uses the read-only receipt API');
    await openDetails(page.locator('.px4-operation').first());
    await capture('unknown-recovered');

    await page.getByRole('tab', { name: 'Profiles', exact: true }).click();
    await page.getByRole('heading', { name: 'Sample fleet baseline', exact: true }).waitFor();
    const labelLayout = await page.locator('.px4-profile .px4-change-table tbody th').first().evaluate(cell => {
      const name = cell.querySelector('code').getBoundingClientRect();
      const component = cell.querySelector('small').getBoundingClientRect();
      const next = cell.nextElementSibling.getBoundingClientRect();
      return { vertical: component.top >= name.bottom - 1, contained: component.right <= next.left + 1 };
    });
    assert(labelLayout.vertical, 'Profile component/type must sit below the parameter name');
    if (width > 560) assert(labelLayout.contained, 'Profile label must not overlap its next value column');
    await capture('guide-05-profile');
    await page.getByRole('button', { name: 'Review for aircraft', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Prepare parameter changes', exact: true });
    assert(await dialog.getByRole('button', { name: 'Prepare review', exact: true }).isDisabled(), 'Profile apply begins with no targets');
    await dialog.getByRole('checkbox', { name: 'Apply to ALPHA · H1', exact: true }).check();
    await dialog.getByRole('button', { name: 'Prepare review', exact: true }).click();
    await page.getByRole('dialog', { name: 'Review parameter changes', exact: true }).waitFor();
    assert.equal([...state.reviews.values()].at(-1).source, 'mds_profile');
    await capture('profile-reviewed');
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Discard draft', exact: true }).click();

    await page.getByRole('tab', { name: 'Parameters', exact: true }).click();
    await choose(page, '1');
    const importRows = state.rows.slice(1, 1201).map(row => `1\t1\t${row.name}\t${row.value + .25}\t9`);
    const content = ['# Synthetic QGroundControl fixture', ...importRows, '1\t1\tSKIPPED\t0\t99', ''].join('\n');
    await page.getByLabel('Import QGC parameter file', { exact: true }).setInputFiles({ name: 'example-fleet.params', mimeType: 'text/plain', buffer: Buffer.from(content) });
    dialog = page.getByRole('dialog', { name: 'Prepare parameter changes', exact: true });
    await dialog.waitFor();
    await openDetails(dialog.locator('details').filter({ has: page.locator('summary', { hasText: 'Import notes' }) }));
    assert(await dialog.getByText('Line 1202: Unsupported parameter type', { exact: true }).isVisible());
    await dialog.getByRole('button', { name: 'Prepare review', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Review parameter changes', exact: true });
    await dialog.getByRole('button', { name: 'Apply 1200 changes to 1 aircraft', exact: true }).waitFor();
    const last = dialog.getByText('TEST_1199', { exact: true });
    await last.scrollIntoViewIfNeeded(); assert(await last.isVisible(), 'Every imported change remains reachable');
    await capture('import-last-change');
    assert.equal([...state.reviews.values()].at(-1).targets[0].changes.length, 1200);
    assert.equal(state.applyPosts, 2, 'Profile/import reviews never dispatch implicitly');
    assert.deepEqual(state.fixtureErrors, [], 'Synthetic backend fixture assertions');
    assert.deepEqual(state.violations, [], 'No unexpected mutations or external traffic');
    assert.deepEqual(state.pageErrors, [], 'No browser runtime errors');
    assert.deepEqual(state.consoleErrors, [], 'No unexpected console errors');
    return { width, theme, passed: true, parameterCount: state.rows.length, applyPosts: state.applyPosts,
      lookupGets: state.lookupGets, profileGets: state.profileGets, imports: state.imports,
      requestCounts: state.requests.reduce((counts, request) => { const key = `${request.method} ${request.path}`; counts[key] = (counts[key] || 0) + 1; return counts; }, {}),
      screenshots: state.screenshots, expectedConsoleErrors: state.expectedConsoleErrors };
  } catch (error) {
    await page.screenshot({ path: path.join(evidence, `failure-${width}-${theme}.png`), fullPage: true }).catch(() => {});
    fs.writeFileSync(path.join(evidence, `failure-${width}-${theme}.json`), JSON.stringify({ error: error.stack,
      violations: state.violations, fixtureErrors: state.fixtureErrors, pageErrors: state.pageErrors,
      consoleErrors: state.consoleErrors, requests: state.requests }, null, 2));
    throw error;
  } finally { await context.close(); }
}

async function main() {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.MDS_CHROMIUM_EXECUTABLE ? { executablePath: process.env.MDS_CHROMIUM_EXECUTABLE } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const results = [];
  try {
    for (const width of [1440, 900, 390]) for (const theme of ['dark', 'light']) {
      results.push(await scenario(browser, width, theme));
      console.log(JSON.stringify({ width, theme, passed: true }));
    }
    const report = { fixtureOnly: true, scope: 'Real built UI with intercepted synthetic GCS and system-font fallback; no SITL/hardware or native-flight clearance.',
      origin, createdAt: new Date().toISOString(), results };
    fs.writeFileSync(path.join(evidence, 'browser-results.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify({ passed: true, scenarios: results.length, evidence }));
  } finally { await browser.close(); }
}

module.exports = { fixtureState, installFixtures, choose, PARAMETER };
if (require.main === module) main().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
