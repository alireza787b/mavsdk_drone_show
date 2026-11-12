#!/usr/bin/env node
// Real built UI with isolated read fixtures; every API write is denied.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright-core');
const base = process.env.MDS_UI_BASE || 'http://127.0.0.1:3030';
const output = process.env.MDS_UI_EVIDENCE;
assert(output, 'Set MDS_UI_EVIDENCE to an owned evidence directory');
fs.mkdirSync(output, { recursive: true });
const widths = (process.env.MDS_UI_WIDTHS || '1440,900,390').split(',').map(Number);
const themes = (process.env.MDS_UI_THEMES || 'dark,light').split(',');
const fleet = [1, 2].map(id => ({ hw_id: String(id), pos_id: String(id),
  callsign: id === 1 ? 'ALPHA' : 'BRAVO', ip: `192.0.2.${id}`, mavlink_port: 14540 }));

async function run(browser, width, theme, routeName, buttonName, dialogName) {
  const context = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: theme });
  await context.addInitScript(value => localStorage.setItem('drone-dashboard-theme', value), theme);
  const page = await context.newPage(), errors = [], writes = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url()), now = Date.now();
    if (!(url.pathname.startsWith('/api/') || url.port === '5030')) return route.continue();
    const headers = { 'access-control-allow-origin': new URL(base).origin,
      'access-control-allow-credentials': 'true', 'access-control-allow-headers': '*',
      'access-control-expose-headers': 'X-MDS-Server-Time', 'X-MDS-Server-Time': String(now) };
    if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
    if (request.method() !== 'GET') {
      writes.push({ method: request.method(), path: url.pathname });
      return route.abort();
    }
    let json = {};
    if (url.pathname === '/api/v1/auth/status') json = { authenticated: true,
      dashboard_auth_enabled: false, api_auth_enabled: false, user: { username: 'Reviewer', role: 'viewer' } };
    else if (url.pathname === '/api/v1/system/runtime-status') json = { mode: 'sitl', configured_mode: 'sitl', restart_required: false };
    else if (url.pathname === '/api/v1/config/fleet') json = fleet;
    else if (url.pathname === '/api/v1/config/swarm') json = { version: 1, assignments: fleet.map((d, i) => ({ hw_id: d.hw_id, follow: i ? 1 : 0, offset_x: i * -6, offset_y: 0, offset_z: 0, frame: 'body' })) };
    else if (url.pathname === '/api/v1/fleet/telemetry') json = { telemetry: {}, timestamp: now };
    else if (url.pathname === '/api/v1/fleet/heartbeats') json = { heartbeats: [] };
    else if (url.pathname.includes('/px4/params/policy')) json = { mutations: { supported_component_ids: [1], require_disarmed: true }, docs: { version: 'Reference' } };
    else if (url.pathname.includes('/px4/params/profiles')) json = { profiles: [] };
    else if (url.pathname === '/api/logs/sources') json = { components: {} };
    else if (url.pathname === '/api/logs/sessions') json = { sessions: [] };
    else if (url.pathname.includes('/commands/')) json = { commands: [] };
    return route.fulfill({ json, headers });
  });
  try {
    await page.goto(`${base}/${routeName}`);
    await page.getByRole('button', { name: buttonName, exact: true }).click();
    const dialog = page.getByRole('dialog', { name: dialogName, exact: true });
    await dialog.getByRole('radio').last().waitFor();
    const layout = await dialog.evaluate(panel => {
      const body = panel.querySelector('.operator-confirm-dialog__message');
      return { viewportOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        panelOverflow: panel.scrollWidth > panel.clientWidth + 1,
        bodyOverflow: body.scrollWidth > body.clientWidth + 1,
        radios: [...panel.querySelectorAll('input[type=radio]')].map(el => ({
          width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height,
          labelClipped: el.closest('label').scrollWidth > el.closest('label').clientWidth + 1,
        })), searchWidth: panel.querySelector('input[type=search]').getBoundingClientRect().width };
    });
    await page.screenshot({ path: path.join(output, `${routeName}-${width}-${theme}.png`), fullPage: true });
    await dialog.getByRole('radio').last().check();
    // Inspection starts a native read request. This layout-only probe cancels
    // the review so neither real sources nor cached parameter snapshots change.
    await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
    await page.getByRole('button', { name: buttonName, exact: true }).waitFor();
    const passed = !layout.viewportOverflow && !layout.panelOverflow && !layout.bodyOverflow
      && layout.searchWidth > 100 && layout.radios.every(r => r.width >= 16 && r.width <= 24 && !r.labelClipped)
      && !errors.length && !writes.length;
    return { route: routeName, width, theme, passed, layout, errors, writes };
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true,
    ...(process.env.MDS_UI_CHROME ? { executablePath: process.env.MDS_UI_CHROME } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const results = [];
  try {
    for (const width of widths) for (const theme of themes) {
      for (const [route, button, dialog] of [['logs', 'Choose log source', 'Choose log source'],
        ['px4-parameters', 'Choose aircraft', 'Choose aircraft']]) {
        results.push(await run(browser, width, theme, route, button, dialog));
      }
    }
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(results, null, 2));
    console.log(JSON.stringify(results));
    assert(results.every(result => result.passed), 'Chooser controls or labels overflow the built modal');
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exitCode = 1; });
