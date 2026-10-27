/* Read-only Drone Show operator evidence probe.
 *
 * The browser is pointed at an isolated dashboard build and all GCS API
 * reads are fulfilled from a deterministic SITL fixture. Mutating requests
 * are rejected and recorded, so opening/cancelling the launch review can
 * never reach an aircraft or the real GCS. The probe produces desktop/mobile
 * screenshots in both themes and checks the core setup -> review -> monitor
 * path for overflow, runtime errors, and accidental writes.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');

const baseUrl = process.env.MDS_PROBE_URL || process.argv[2] || 'http://127.0.0.1:3030';
const outputDir = path.resolve(process.env.MDS_PROBE_OUTPUT || process.argv[3] || 'artifacts/drone-show-ui');
const widths = { desktop: { width: 1440, height: 960 }, mobile: { width: 390, height: 844 } };
const blockedWrites = [];
const reports = [];

const fleet = [
  { hw_id: 1, pos_id: 1, name: 'NET-LEADER', state: 'STANDBY', armed: false, battery_percent: 92, telemetry_fresh: true, ready_to_arm: true, readiness_summary: 'Ready' },
  { hw_id: 2, pos_id: 2, name: 'NET-FOLLOWER', state: 'STANDBY', armed: false, battery_percent: 88, telemetry_fresh: true, ready_to_arm: true, readiness_summary: 'Ready' },
];

function jsonResponse(data, status = 200) {
  return { status, contentType: 'application/json', body: JSON.stringify(data) };
}

function svgResponse() {
  const body = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 500"><rect width="1200" height="500" fill="#17202a"/><g stroke="#2f4858" stroke-width="1">${Array.from({ length: 13 }, (_, i) => `<path d="M${i * 100} 0V500"/>`).join('')}${Array.from({ length: 6 }, (_, i) => `<path d="M0 ${i * 100}H1200"/>`).join('')}</g><path d="M90 400 C260 340 270 90 480 120 S680 430 900 200 S1040 90 1120 70" fill="none" stroke="#36c2a0" stroke-width="7"/><path d="M90 420 C280 380 350 160 520 180 S700 410 900 250 S1030 140 1120 100" fill="none" stroke="#f3b562" stroke-width="4" stroke-dasharray="12 8"/><text x="34" y="42" fill="#e9f0f5" font-family="sans-serif" font-size="24">Trajectory preview · isolated SITL fixture</text></svg>`;
  return { status: 200, contentType: 'image/svg+xml', body };
}

function operationFixture(active) {
  return {
    state: active ? 'active' : 'idle',
    phase: active ? 'executing' : 'idle',
    mission_type: active ? 300 : null,
    timestamp: Date.now(),
    fleet: fleet.map((drone) => ({
      ...drone,
      state: active ? 'OFFBOARD' : drone.state,
      armed: active ? true : false,
    })),
    operation_target_ids: [1, 2],
    command_id: active ? 'probe-show-001' : null,
    command: { executions: { succeeded: active ? 1 : 0, failed: 0 } },
  };
}

function fixtureFor(url, active) {
  const p = url.pathname;
  if (p.includes('/plots/')) return svgResponse();
  if (p === '/api/v1/auth/status') return jsonResponse({ dashboard_auth_enabled: false, api_auth_enabled: false, authenticated: true, role: 'operator' });
  if (p === '/api/v1/system/runtime-status') return jsonResponse({ mode: 'SITL', configured_mode: 'SITL', configured_sim_mode: true, restart_required: false });
  if (p === '/api/v1/system/health' || p === '/ping' || p === '/health') return jsonResponse({ status: 'healthy' });
  if (p === '/api/v1/shows/skybrush/workspace') return jsonResponse({
    package: { available: true, name: 'Aurora Demo / rehearsal', revision: 'sitl-fixture-01', drone_count: 2, position_ids: [1, 2], duration_ms: 192000, max_altitude: 48 },
    metrics: { performance_metrics: { max_velocity_ms: 4.2 } },
    validation: { validation_status: 'PASS' },
    plots: { filenames: ['combined_drone_paths.jpg'] },
  });
  if (p === '/api/v1/shows/skybrush') return jsonResponse({ drone_count: 2, duration_ms: 192000, duration_minutes: 3, duration_seconds: 12, max_altitude: 48 });
  if (p === '/api/v1/shows/skybrush/plots') return jsonResponse({ filenames: ['combined_drone_paths.jpg', 'drone_1_path.jpg', 'drone_2_path.jpg'] });
  if (p === '/api/v1/shows/skybrush/metrics') return jsonResponse({
    basic_metrics: { max_altitude_details: { value: 48 }, min_altitude_details: { value: 3 }, max_distance_details: { value: 36 } },
    performance_metrics: { max_velocity_details: { value: 4.2 } },
  });
  if (p === '/api/v1/shows/operation/status') return jsonResponse(operationFixture(active));
  if (p === '/api/v1/origin') return jsonResponse({ lat: 48.8566, lon: 2.3522, alt: 42.1 });
  if (p === '/api/v1/origin/deviations') return jsonResponse({ deviations: { 1: { status: 'ok', horizontal_m: 0.12, vertical_m: 0.08 }, 2: { status: 'ok', horizontal_m: 0.18, vertical_m: 0.1 } } });
  if (p === '/api/v1/config/fleet') return jsonResponse(fleet);
  if (p === '/api/v1/config/swarm') return jsonResponse({ version: 1, assignments: [{ hw_id: 1, follow: 0, offset_x: 0, offset_y: 0, offset_z: 0, frame: 'ned' }, { hw_id: 2, follow: 1, offset_x: 6, offset_y: 0, offset_z: 0, frame: 'ned' }] });
  if (p === '/api/v1/fleet/telemetry') return jsonResponse({ drones: fleet });
  if (p === '/api/v1/fleet/heartbeats' || p === '/api/v1/fleet/node-boot-status' || p === '/api/v1/fleet/network-status') return jsonResponse({});
  if (p === '/api/v1/commands/recent' || p === '/api/v1/commands/active') return jsonResponse({ commands: [] });
  if (p === '/api/v1/git/status') return jsonResponse({ gcs_status: { status: 'clean', uncommitted_changes: [] } });
  if (p === '/api/v1/shows/custom') return jsonResponse({ drone_count: 0 });
  // The shell may ask for unrelated optional resources. Keep those reads
  // successful but empty so the evidence is about Drone Show, not errors from
  // unrelated navigation widgets.
  if (p.startsWith('/api/')) return jsonResponse({});
  return null;
}

async function waitForWorkspace(page) {
  await page.locator('.drone-show-workspace').waitFor({ state: 'visible', timeout: 20000 });
  await page.locator('.drone-show-workspace__summary-state').waitFor({ state: 'visible', timeout: 20000 });
  await page.waitForTimeout(700);
}

async function collectLayout(page) {
  return page.evaluate(() => {
    const overflow = [...document.querySelectorAll('*')].filter((node) => {
      const rect = node.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0 && rect.right > window.innerWidth + 2;
    }).slice(0, 10).map((node) => ({ tag: node.tagName, className: String(node.className), right: Math.round(node.getBoundingClientRect().right) }));
    return { viewport: innerWidth, documentWidth: document.documentElement.scrollWidth, overflow };
  });
}

async function runCase(browser, theme, viewportName) {
  const context = await browser.newContext({ viewport: widths[viewportName], colorScheme: theme });
  await context.addInitScript(({ selectedTheme }) => {
    localStorage.setItem('drone-dashboard-theme', selectedTheme);
  }, { selectedTheme: theme });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (['error', 'warning'].includes(message.type())) errors.push(`${message.type()}: ${message.text()}`); });
  page.on('websocket', (socket) => socket.on('framereceived', () => {}));
  let activeFixture = false;
  await page.route('**/*', async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isApi = url.port === '5030' || url.pathname.startsWith('/api/');
    if (!isApi) return route.continue();
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      blockedWrites.push({ theme, viewport: viewportName, method: request.method(), path: url.pathname });
      return route.fulfill(jsonResponse({ detail: 'Probe: writes disabled' }, 409));
    }
    const response = fixtureFor(url, activeFixture) || jsonResponse({});
    return route.fulfill(response);
  });

  const prefix = `${theme}-${viewportName}`;
  await page.goto(`${baseUrl.replace(/\/$/, '')}/drone-show?tab=operate`, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await waitForWorkspace(page);
  const operateLayout = await collectLayout(page);
  await page.screenshot({ path: path.join(outputDir, `${prefix}-operate-ready.png`), fullPage: true });

  await page.getByRole('tab', { name: 'Design / Setup' }).click();
  await page.waitForTimeout(450);
  const setupLayout = await collectLayout(page);
  await page.screenshot({ path: path.join(outputDir, `${prefix}-setup.png`), fullPage: true });

  await page.getByRole('tab', { name: 'Operate' }).click();
  await page.getByRole('button', { name: 'Launch show' }).click();
  await page.getByRole('dialog').waitFor({ state: 'visible', timeout: 5000 });
  await page.screenshot({ path: path.join(outputDir, `${prefix}-launch-review.png`), fullPage: true });
  await page.getByRole('dialog').getByRole('button', { name: 'Cancel' }).click();

  activeFixture = true;
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 30000 });
  await waitForWorkspace(page);
  await page.screenshot({ path: path.join(outputDir, `${prefix}-monitoring.png`), fullPage: true });
  const monitoringLayout = await collectLayout(page);
  const report = { theme, viewport: viewportName, operateLayout, setupLayout, monitoringLayout, errors };
  reports.push(report);
  await context.close();
}

(async () => {
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true, ...(process.env.MDS_CHROMIUM_PATH ? { executablePath: process.env.MDS_CHROMIUM_PATH } : {}), args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    for (const theme of ['dark', 'light']) for (const viewport of ['desktop', 'mobile']) await runCase(browser, theme, viewport);
  } finally {
    await browser.close();
  }
  const failures = reports.flatMap((report) => [
    ...(report.errors.length ? [{ case: `${report.theme}/${report.viewport}`, type: 'runtime', errors: report.errors }] : []),
    ...[report.operateLayout, report.setupLayout, report.monitoringLayout].filter((layout) => layout.documentWidth > layout.viewport + 2 || layout.overflow.length).map((layout) => ({ case: `${report.theme}/${report.viewport}`, type: 'overflow', layout })),
  ]);
  const summary = { baseUrl, outputDir, cases: reports.length, reports, blockedWrites, failures, passed: failures.length === 0 && blockedWrites.length === 0 };
  fs.writeFileSync(path.join(outputDir, 'ui-summary.json'), `${JSON.stringify(summary, null, 2)}\n`);
  console.log(JSON.stringify({ cases: summary.cases, passed: summary.passed, blockedWrites, failures }, null, 2));
  if (!summary.passed) process.exitCode = 1;
})().catch((error) => { console.error(error); process.exitCode = 1; });
