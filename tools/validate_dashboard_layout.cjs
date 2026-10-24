/* Read-only viewport audit of an existing dashboard build. Run on the build host.
 * API requests are mocked; POST/PUT/PATCH/DELETE cannot reach aircraft or GCS.
 * --source-css overlays current layout CSS for pre-build iteration only.
 */
const fs = require('fs');
const path = require('path');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const source = path.resolve(__dirname, '../app/dashboard/drone-dashboard/src');
const routes = ['/', '/mission-control', '/swarm-design', '/drone-show-design',
  '/manage-drone-show', '/mission-config', '/fleet-enrollment', '/fleet-ops',
  '/fleet-ops/wifi', '/fleet-ops/mavlink', '/drone-detail', '/custom-show', '/globe-view',
  '/swarm-trajectory', '/px4-parameters', '/trajectory-planning', '/quickscout',
  '/runtime-admin', '/environments', '/simurgh', '/logs', '/sitl-control'];
const styles = ['App.css', ...['OperatorPrimitives', 'CustomShowPage', 'Overview',
  'LogViewer', 'QuickScout', 'TrajectoryPlanning', 'GlobeView', 'MissionConfig'].map(name => `styles/${name}.css`)];
const overlay = process.argv.includes('--source-css');
const output = process.env.MDS_LAYOUT_OUTPUT;
const fleet = [{ hw_id: 1, pos_id: 1, callsign: 'SCOUT', ip: '127.0.0.1' },
  { hw_id: 2, pos_id: 2, callsign: 'NET-LEADER', ip: '127.0.0.2' }];
const assignments = fleet.map((drone, i) => ({ hw_id: drone.hw_id, follow: i ? 1 : 0,
  offset_x: i ? 6 : 0, offset_y: 0, offset_z: 0, frame: 'ned' }));

let browser;
(async () => {
  browser = await chromium.launch({ headless: true,
    ...(process.env.MDS_CHROMIUM_PATH ? { executablePath: process.env.MDS_CHROMIUM_PATH } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  const results = [];
  const blockedWrites = [];
  for (const width of (process.env.MDS_LAYOUT_WIDTHS || '390,768,1366,1920').split(',').map(Number)) {
    const page = await browser.newPage({ viewport: { width, height: 960 } });
    const writes = [];
    const errors = [];
    const resourceFailures = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
      if (response.status() >= 400 && /\.(js|css)(\?|$)/.test(response.url()))
        resourceFailures.push({ url: response.url(), status: response.status() });
    });
    page.on('requestfailed', request => {
      if (['script', 'stylesheet'].includes(request.resourceType()))
        resourceFailures.push({ url: request.url(), error: request.failure()?.errorText });
    });
    await page.routeWebSocket('**/*', socket => socket.close());
    await page.route('**/*', async route => {
      const request = route.request();
      const url = new URL(request.url());
      const api = url.port === '5030' || url.pathname.startsWith('/api/');
      if (!api) return route.continue();
      if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
        writes.push(url.pathname);
        return route.fulfill({ status: 409, json: { detail: 'Layout audit: writes disabled' } });
      }
      let data;
      if (url.pathname.includes('/auth')) data = { enabled: false, auth_enabled: false, authenticated: true };
      else if (url.pathname.endsWith('/config/fleet')) data = fleet;
      else if (url.pathname.endsWith('/config/swarm')) data = { version: 1, assignments };
      else if (url.pathname.includes('git')) data = { gcs_status: { status: 'clean', uncommitted_changes: [] } };
      else if (url.pathname.includes('/health')) data = { status: 'healthy' };
      else if (url.pathname.includes('/runtime')) data = { mode: 'REAL', restart_required: false, clusters: [] };
      else return route.fulfill({ status: 503, json: { detail: 'Layout fixture: service unavailable' } });
      return route.fulfill({ status: 200, json: data });
    });
    for (const route of process.env.MDS_LAYOUT_ROUTES ? process.env.MDS_LAYOUT_ROUTES.split(',') : routes) {
      console.log('CHECK', width, route);
      errors.length = 0;
      resourceFailures.length = 0;
      await page.goto((process.env.MDS_LAYOUT_URL || 'http://127.0.0.1:3038') + route);
      await page.locator('.content').waitFor({ timeout: 5000 }).catch(() => {});
      await page.waitForTimeout(350);
      if (overlay) {
        // Removed root clipping must not be inherited from the previous bundle.
        await page.addStyleTag({ content: 'html,body,#root,.content{overflow-x:visible}' });
        for (const style of styles) await page.addStyleTag({ content: fs.readFileSync(path.join(source, style), 'utf8').replace(/@import[^;]+;/g, '') });
      }
      for (const alternateNavigation of [false, true]) {
        const collapsed = width > 768 && alternateNavigation;
        const navigationOpen = width <= 768 && alternateNavigation;
        if (alternateNavigation) {
          const toggle = page.locator(width > 768 ? '.sidebar-toggle' : '.mobile-sidebar-toggle').first();
          if (await toggle.count()) await toggle.click();
          await page.waitForTimeout(250);
        }
        const measurement = await page.evaluate(() => {
          const content = document.querySelector('.content');
          if (!content) return { unavailable: true, pageText: document.body.innerText.slice(0, 300) };
          const box = content.getBoundingClientRect();
          const pageShell = content.querySelector('.operator-page-shell');
          const shellBox = pageShell?.getBoundingClientRect();
          const overflow = [...content.querySelectorAll('*')].filter(node => {
            const rect = node.getBoundingClientRect();
            if (!rect.width || !rect.height || rect.right <= innerWidth + 2) return false;
            let parent = node.parentElement;
            while (parent && parent !== content) {
              if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(parent).overflowX)) return false;
              parent = parent.parentElement;
            }
            return true;
          }).slice(0, 12).map(node => ({ tag: node.tagName, className: String(node.className), right: Math.round(node.getBoundingClientRect().right) }));
          return { content: { left: box.left, width: box.width, right: box.right },
            shell: shellBox ? { left: shellBox.left, width: shellBox.width, right: shellBox.right } : null,
            documentWidth: document.documentElement.scrollWidth, viewport: innerWidth, overflow };
        });
        results.push({ route, width, collapsed, navigationOpen, errors: [...errors], resourceFailures: [...resourceFailures], ...measurement });
        if (measurement.unavailable || measurement.documentWidth > width + 2) console.log('ISSUE', JSON.stringify(results.at(-1)));
      }
    }
    blockedWrites.push(...writes.map(endpoint => ({ width, endpoint })));
    await page.close();
  }
  await browser.close();
  const failures = results.filter(result => result.documentWidth > result.width + 2 || result.content?.right > result.width + 2);
  const unavailable = results.filter(result => result.unavailable);
  const report = { sourceCssOverlay: overlay, coverage: 'Mock fleet plus empty/unavailable-service states; not populated flight workflow acceptance', results, failures, unavailable, blockedWrites };
  if (output) fs.writeFileSync(output, JSON.stringify(report, null, 2));
  console.log(JSON.stringify({ cases: results.length, failures, unavailable }, null, 2));
  if (failures.length) process.exitCode = 1;
})().catch(error => { console.error(error); process.exitCode = 1; })
  .finally(async () => { if (browser) await browser.close(); });
