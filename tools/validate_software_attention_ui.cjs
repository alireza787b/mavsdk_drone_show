#!/usr/bin/env node
// Built UI + synthetic fixtures only. Never forwards API/WebSocket traffic.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixtureState, installFixtures } = require('./validate_px4_parameter_workspace_ui.cjs');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MDS_UI_BASE || 'http://127.0.0.1:3039';
const evidence = process.env.MDS_UI_EVIDENCE;
assert(evidence);
fs.mkdirSync(evidence, { recursive: true });

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.MDS_CHROMIUM_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] });
  const results = [];
  try {
    for (const width of [1440, 900, 390]) for (const theme of ['dark', 'light']) {
      const state = fixtureState();
      const context = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: theme,
        hasTouch: width === 390, serviceWorkers: 'block' });
      await context.addInitScript(value => localStorage.setItem('drone-dashboard-theme', value), theme);
      const page = await context.newPage();
      page.setDefaultTimeout(15000);
      page.on('pageerror', error => state.pageErrors.push(error.message));
      await installFixtures(context, state, page);
      let failed = false;
      await context.route('**/api/v1/git/status', route => {
        const request = route.request();
        assert(['GET', 'OPTIONS'].includes(request.method()));
        const headers = { 'access-control-allow-origin': new URL(base).origin,
          'access-control-allow-credentials': 'true',
          'access-control-allow-headers': request.headers()['access-control-request-headers'] || 'Content-Type' };
        if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
        if (failed) return route.fulfill({ status: 503, headers, json: { detail: 'Synthetic outage' } });
        return route.fulfill({ headers, json: { needs_sync_count: 1, unknown_count: 1, total_drones: 2,
          gcs_status: { commit: 'synthetic-gcs' }, git_status: {
            '1': { commit: 'synthetic-older', status: 'behind', in_sync_with_gcs: false },
            '2': { commit: 'unknown', status: 'unknown', in_sync_with_gcs: false },
          } } });
      });
      await page.goto(base+'/');
      await page.getByText('Software differs', { exact: true }).waitFor();
      await page.locator('.fleet-aircraft').first().waitFor();
      assert.equal(await page.locator('.sync-warning-banner a').count(), 1);
      const link = page.getByRole('link', { name: 'Review aircraft software' });
      assert.equal(await link.getAttribute('href'), '/fleet-ops?tab=sync&filter=drift');
      assert.equal(await page.locator('.fleet-aircraft__metric--link').first().innerText(), '');
      assert(await page.locator('.fleet-aircraft__metric--link').first().getAttribute('aria-label'));
      const geometry = await page.locator('.sync-warning-banner').evaluate(element => ({
        radius: getComputedStyle(element).borderTopLeftRadius, width: innerWidth,
        documentWidth: document.documentElement.scrollWidth, shadow: getComputedStyle(element).boxShadow,
      }));
      assert.equal(geometry.radius, '0px'); assert.equal(geometry.shadow, 'none');
      assert(geometry.documentWidth <= geometry.width+1, 'No horizontal overflow');
      const filename = `software-review-${width}-${theme}.png`;
      await page.screenshot({ path: path.join(evidence, filename), fullPage: false });
      await page.evaluate(() => { window.__softwareNotice = document.querySelector('.sync-warning-banner'); });
      await page.clock.install();
      failed = true;
      await page.clock.fastForward(12000);
      assert(await page.evaluate(() => window.__softwareNotice === document.querySelector('.sync-warning-banner')));
      await page.getByText('Software differs', { exact: true }).waitFor();
      await page.clock.fastForward(21000);
      await page.getByText('Software status unavailable', { exact: true }).waitFor();
      assert(await page.evaluate(() => window.__softwareNotice === document.querySelector('.sync-warning-banner')));
      failed = false;
      await page.clock.fastForward(11000);
      await page.getByText('Software differs', { exact: true }).waitFor();
      assert.equal(state.violations.length, 0);
      assert.equal(state.pageErrors.length, 0);
      assert.equal(state.requests.filter(request => request.method === 'POST').length, 0);
      results.push({ width, theme, passed: true, screenshot: filename, forwardedApiRequests: 0 });
      fs.writeFileSync(path.join(evidence, 'software-attention-results.json'), JSON.stringify({ fixtureOnly: true, results }, null, 2));
      await context.close();
    }
  } finally { await browser.close(); }
  console.log(JSON.stringify({ passed: true, cases: results.length }));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
