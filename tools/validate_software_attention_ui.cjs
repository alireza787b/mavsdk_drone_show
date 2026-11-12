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
    for (const width of (process.env.MDS_UI_WIDTHS || '1440,900,390').split(',').map(Number))
      for (const theme of (process.env.MDS_UI_THEMES || 'dark,light').split(',')) {
      const state = fixtureState();
      state.telemetryOverrides = Object.fromEntries(['1','2'].map(id => [id, {
        gps_fix_type: 6, satellites_visible: 20, battery_remaining_percent: 83,
        battery_voltage: 16.1, position_alt: 1200,
        heartbeat_network_info: { primary_link: { type: id === '1' ? 'ethernet' : 'wifi',
          interface: id === '1' ? 'end0' : 'wlan0' }, wifi: { signal_strength_percent: 72 } },
      }]));
      const context = await browser.newContext({ viewport: { width, height: 1000 }, colorScheme: theme,
        hasTouch: width === 390, serviceWorkers: 'block' });
      await context.addInitScript(value => localStorage.setItem('drone-dashboard-theme', value), theme);
      const page = await context.newPage();
      await page.clock.install({ time: new Date() });
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
      try { await page.locator('.fleet-aircraft').first().waitFor(); }
      catch (error) {
        await page.screenshot({ path: path.join(evidence, `failure-${width}-${theme}.png`) });
        fs.writeFileSync(path.join(evidence, `failure-${width}-${theme}.json`), JSON.stringify({
          message: error.message, pageErrors: state.pageErrors, requests: state.requests,
          text: (await page.locator('body').innerText()).slice(0, 3000),
        }, null, 2));
        throw error;
      }
      assert.equal(await page.locator('.sync-warning-banner a').count(), 1);
      const link = page.getByRole('link', { name: 'Review aircraft software' });
      assert.equal(await link.getAttribute('href'), '/fleet-ops?tab=sync&filter=drift');
      assert.equal(await page.locator('.fleet-aircraft__metric--link').first().innerText(), '');
      assert(await page.locator('.fleet-aircraft__metric--link').first().getAttribute('aria-label'));
      assert.equal(await page.locator('.fleet-aircraft__metric--link').nth(1).innerText(), '72%');
      const geometry = await page.locator('.sync-warning-banner').evaluate(element => ({
        radius: getComputedStyle(element).borderTopLeftRadius, width: innerWidth,
        documentWidth: document.documentElement.scrollWidth, shadow: getComputedStyle(element).boxShadow,
      }));
      assert.equal(geometry.radius, '0px'); assert.equal(geometry.shadow, 'none');
      assert(geometry.documentWidth <= geometry.width+1, 'No horizontal overflow');
      const filename = `software-review-${width}-${theme}.png`;
      await page.screenshot({ path: path.join(evidence, filename), fullPage: false });
      await page.locator('.sync-warning-banner').screenshot({ path: path.join(evidence, `software-notice-${width}-${theme}.png`) });
      for (const [name, expected] of [['ALPHA', 'Ethernet'], ['BRAVO', 'Wi-Fi · 72%']]) {
        await page.getByRole('button', { name: `Inspect ${name} · H${name === 'ALPHA' ? '1' : '2'}`, exact: true }).click();
        const inspector = page.getByRole('dialog', { name, exact: true });
        assert.equal(await inspector.locator('dt').filter({ hasText: /^Network$/ })
          .locator('xpath=following-sibling::dd[1]').innerText(), expected);
        assert.equal(await inspector.getByText('Wi-Fi signal', { exact: true }).count(), 0);
        const bounds = await inspector.boundingBox();
        assert(bounds.x >= -1 && bounds.x + bounds.width <= width + 1, 'Inspector fits the viewport');
        await page.screenshot({ path: path.join(evidence, `network-${name.toLowerCase()}-${width}-${theme}.png`) });
        await inspector.getByRole('button', { name: 'Close aircraft details', exact: true }).click();
      }
      await page.evaluate(() => { window.__softwareNotice = document.querySelector('.sync-warning-banner'); });
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
