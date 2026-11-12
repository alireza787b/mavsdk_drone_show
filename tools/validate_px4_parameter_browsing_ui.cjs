#!/usr/bin/env node
// Focused built-browser gate. Reuses the isolated workspace fixtures; no API
// request or WebSocket is ever forwarded and Apply is never clicked.
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { fixtureState, installFixtures, choose, PARAMETER } = require('./validate_px4_parameter_workspace_ui.cjs');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.MDS_UI_BASE || 'http://127.0.0.1:3039';
const evidence = process.env.MDS_UI_EVIDENCE;
assert(evidence, 'Set MDS_UI_EVIDENCE to an owned evidence directory');
fs.mkdirSync(evidence, { recursive: true });

async function scenario(browser, width, theme) {
  const state = fixtureState();
  state.rows[1].category = 'Synthetic velocity category';
  const context = await browser.newContext({ viewport: { width, height: width === 390 ? 900 : 1000 }, colorScheme: theme,
    deviceScaleFactor: 1, serviceWorkers: 'block' });
  await context.addInitScript(value => localStorage.setItem('drone-dashboard-theme', value), theme);
  await context.addInitScript(() => {
    window.__mdsSizingWarnings = JSON.parse(sessionStorage.getItem('mds:grid-sizing-evidence') || '[]');
    const original = console.error;
    console.error = (...args) => {
      if (String(args[0]).includes('MUI X: useResizeContainer')) {
        window.__mdsSizingWarnings.push({ phase: window.__mdsBrowsePhase, screenshotActive: Boolean(window.__mdsScreenshotActive), viewportWidth: innerWidth,
          documentWidth: document.documentElement.clientWidth, grids: [...document.querySelectorAll('.MuiDataGrid-root')].map(el => ({
          connected: el.isConnected, width: el.getBoundingClientRect().width, height: el.getBoundingClientRect().height,
          parentWidth: el.parentElement?.getBoundingClientRect().width, display: getComputedStyle(el).display,
          parentDisplay: el.parentElement ? getComputedStyle(el.parentElement).display : '',
        })),
        });
        sessionStorage.setItem('mds:grid-sizing-evidence', JSON.stringify(window.__mdsSizingWarnings));
      }
      original(...args);
    };
  });
  const page = await context.newPage(), bounds = [], textBounds = [];
  page.setDefaultTimeout(20000);
  page.on('pageerror', error => state.pageErrors.push(error.message));
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().includes('503')) state.consoleErrors.push(message.text());
  });
  await installFixtures(context, state, page);
  const capture = async name => {
    await page.evaluate(value => { window.__mdsBrowsePhase = value; }, name);
    const layout = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth,
      theme: document.documentElement.dataset.theme, dialogs: [...document.querySelectorAll('[role=dialog]')].map(el => {
        const r = el.getBoundingClientRect(); return { left: r.left, right: r.right };
      }) }));
    assert(layout.document <= layout.viewport + 1, `${name}: document overflow`);
    assert.equal(layout.theme, theme);
    layout.dialogs.forEach(r => assert(r.left >= -1 && r.right <= layout.viewport + 1, `${name}: dialog overflow`));
    const filename = `${name}-${width}-${theme}.png`;
    await page.evaluate(() => { window.__mdsScreenshotActive = true; });
    // Chromium fullPage capture can temporarily probe a 1px layout viewport,
    // producing a genuine MUI resize warning unrelated to operator layout.
    // Keep original-resolution evidence at the actual requested viewport.
    await page.screenshot({ path: path.join(evidence, filename), fullPage: false });
    await page.evaluate(() => { window.__mdsScreenshotActive = false; });
    state.screenshots.push(filename);
  };
  const bounded = async name => {
    const count = await page.locator('.MuiDataGrid-row').count();
    assert(count > 0 && count <= 100, `${name}: expected bounded virtual rows, got ${count}`);
    assert.equal(await page.locator('.px4-parameter-list').count(), 0, 'No unbounded alternate mobile list');
    bounds.push({ name, renderedRows: count });
  };
  const unclippedText = async name => {
    const result = await page.locator('.px4-row-link > span, .px4-row-link > small, .MuiDataGrid-row:not(.px4-grid-group) .MuiDataGrid-cell[data-field=displayValue]').evaluateAll(elements => {
      const failures = [];
      for (const el of elements) {
        const cell = el.closest('.MuiDataGrid-cell'), box = cell.getBoundingClientRect();
        const range = document.createRange(); range.selectNodeContents(el);
        const text = range.getBoundingClientRect();
        if (text.width && (text.top < box.top - 1 || text.bottom > box.bottom + 1 || text.left < box.left - 1 || text.right > box.right + 1)) {
          failures.push({ text: el.textContent, textTop: text.top, textBottom: text.bottom, cellTop: box.top, cellBottom: box.bottom });
        }
      }
      return { checked: elements.length, failures };
    });
    assert(result.checked > 0 && !result.failures.length, `${name}: clipped parameter text ${JSON.stringify(result)}`);
    textBounds.push({ name, checked: result.checked });
  };
  const scrollToEnd = async name => {
    await page.locator('.MuiDataGrid-virtualScroller').evaluate(el => { el.scrollTop = el.scrollHeight; });
    await page.getByRole('button', { name: `Inspect ${name}`, exact: true }).waitFor();
  };
  try {
    await page.goto(`${base}/px4-parameters`);
    await page.getByText('Choose an aircraft to read its parameters.', { exact: true }).waitFor();
    await capture('no-aircraft');
    await choose(page, '1');
    assert.equal(await page.getByRole('button', { name: 'List', exact: true }).getAttribute('aria-pressed'), 'true');
    assert.equal((await page.locator('.MuiTablePagination-select[role=combobox]').innerText()).trim(), '50');
    await bounded('list-50');
    await unclippedText('list-50');
    await page.mouse.move(0, 0);
    const shades = await page.locator('.MuiDataGrid-row').evaluateAll(rows => rows.slice(0, 2).map(row => getComputedStyle(row).backgroundColor));
    assert.notEqual(shades[0], shades[1], 'Alternating rows must have different computed backgrounds');
    const first = page.getByRole('button', { name: `Inspect ${PARAMETER}`, exact: true });
    await first.hover();
    const hovered = await first.evaluate(el => getComputedStyle(el.closest('.MuiDataGrid-row')).backgroundColor);
    assert.notEqual(hovered, shades[0], 'Hover changes whole-row background');
    await page.mouse.move(0, 0);
    await capture('list-striped');
    await page.locator('.MuiTablePagination-select[role=combobox]').click();
    await page.getByRole('option', { name: 'Show all', exact: true }).click();
    await bounded('list-all');
    await scrollToEnd('TEST_2047');
    await bounded('list-all-last');
    await unclippedText('list-all-last');
    await capture('list-all-last');
    await page.getByRole('button', { name: 'Groups', exact: true }).click();
    for (const name of ['Multicopter Position Control · 1 parameters', 'Example group B · 1048 parameters', 'Example group A · 1000 parameters']) {
      await page.getByRole('button', { name, exact: true }).click();
    }
    await bounded('groups-expanded');
    await scrollToEnd(PARAMETER);
    await bounded('groups-last');
    await unclippedText('groups-last');
    await capture('groups-last');
    const search = page.getByRole('searchbox', { name: 'Find parameter', exact: true });
    await search.fill('Synthetic velocity category');
    await page.getByRole('button', { name: 'Inspect TEST_0000', exact: true }).waitFor();
    assert.equal(await page.locator('.px4-group-heading').count(), 0, 'Search reveals leaf matches');
    await search.fill('Example group B');
    await page.getByText('1048 parameters · Search results', { exact: true }).waitFor();
    await bounded('group-search');
    await search.fill('no-such-parameter');
    await page.getByText('No matching parameters.', { exact: true }).waitFor();
    await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    await scrollToEnd(PARAMETER);
    const opener = page.getByRole('button', { name: `Inspect ${PARAMETER}`, exact: true });
    await opener.focus();
    await page.keyboard.press('Enter');
    let dialog = page.getByRole('dialog', { name: PARAMETER, exact: true });
    await dialog.waitFor();
    assert(await dialog.getByRole('button', { name: 'Close', exact: true }).evaluate(el => el === document.activeElement));
    await page.keyboard.press('Escape');
    assert(await opener.evaluate(el => el === document.activeElement), 'Inspector restores keyboard focus');
    assert.equal(await opener.evaluate(el => el.closest('.MuiDataGrid-row').classList.contains('is-inspected')), true);
    assert.notEqual(await opener.evaluate(el => el.closest('.MuiDataGrid-row').getAttribute('aria-selected')), 'true', 'Inspection is not parameter/apply selection');
    await opener.press('Enter');
    dialog = page.getByRole('dialog', { name: PARAMETER, exact: true });
    await dialog.getByRole('button', { name: 'Edit value', exact: true }).click();
    await dialog.getByRole('textbox', { name: `New value for ${PARAMETER}`, exact: true }).fill('8.5');
    await dialog.getByRole('button', { name: 'Review change', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
    await choose(page, '2');
    await page.getByRole('button', { name: 'List', exact: true }).click();
    await search.fill('Position Control');
    await page.getByRole('button', { name: 'Review changes', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Prepare parameter changes', exact: true });
    assert(await dialog.getByRole('checkbox', { name: 'Apply to ALPHA · H1', exact: true }).isChecked());
    assert.equal(await dialog.getByRole('checkbox', { name: 'Apply to BRAVO · H2', exact: true }).isChecked(), false);
    await dialog.getByRole('button', { name: 'Prepare review', exact: true }).click();
    await page.getByRole('dialog', { name: 'Review parameter changes', exact: true }).waitFor();
    assert.deepEqual([...state.reviews.values()].at(-1).hw_ids, ['1']);
    await capture('frozen-targets');
    await page.getByRole('dialog').getByRole('button', { name: 'Close', exact: true }).click();
    await page.getByRole('button', { name: 'Discard draft', exact: true }).click();
    await page.reload();
    state.failNextSnapshot = true;
    await page.getByRole('button', { name: 'Choose aircraft', exact: true }).click();
    dialog = page.getByRole('dialog', { name: 'Choose aircraft', exact: true });
    await dialog.getByRole('radio', { name: /H1\b/ }).check();
    await dialog.getByRole('button', { name: 'Inspect aircraft', exact: true }).click();
    await page.getByRole('button', { name: 'Retry read', exact: true }).waitFor();
    await capture('read-failed');
    await page.getByRole('button', { name: 'Retry read', exact: true }).click();
    await page.getByText('Snapshot current', { exact: true }).waitFor();
    state.snapshotAgeMs = 120000;
    await page.getByRole('button', { name: 'Refresh', exact: true }).click();
    await page.getByText('Snapshot stale', { exact: true }).waitFor();
    await page.getByRole('searchbox', { name: 'Find parameter', exact: true }).fill(PARAMETER);
    await page.getByRole('button', { name: `Inspect ${PARAMETER}`, exact: true }).click();
    dialog = page.getByRole('dialog', { name: PARAMETER, exact: true });
    await dialog.getByText(/Snapshot stale/).waitFor();
    assert.equal(await dialog.getByText(/live values from aircraft/i).count(), 0);
    await capture('stale-inspector');
    assert.equal(state.applyPosts, 0, 'This browsing gate never applies even synthetic writes');
    assert.deepEqual(state.violations, []);
    assert.deepEqual(state.fixtureErrors, []);
    assert.deepEqual(state.pageErrors, []);
    const sizingWarnings = await page.evaluate(() => window.__mdsSizingWarnings);
    assert.deepEqual(state.consoleErrors, []);
    assert.equal(sizingWarnings.length, state.consoleErrors.length, 'Every sizing warning must retain synchronous geometry evidence across reload');
    assert(sizingWarnings.every(item => item.grids.length === 0 || item.grids.every(grid => grid.width > 0)), 'A mounted grid must never have zero width');
    return { width, theme, passed: true, parameterCount: 2049, bounds, textBounds, sizingWarnings, forwardedApiRequests: 0, applyPosts: state.applyPosts, screenshots: state.screenshots };
  } catch (error) {
    await page.screenshot({ path: path.join(evidence, `failure-${width}-${theme}.png`), fullPage: true }).catch(() => {});
    const sizingWarnings = await page.evaluate(() => window.__mdsSizingWarnings || []).catch(() => []);
    fs.writeFileSync(path.join(evidence, `failure-${width}-${theme}.json`), JSON.stringify({ error: error.stack, sizingWarnings,
      violations: state.violations, fixtureErrors: state.fixtureErrors, pageErrors: state.pageErrors, consoleErrors: state.consoleErrors }, null, 2));
    throw error;
  } finally { await context.close(); }
}

(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.MDS_CHROMIUM_EXECUTABLE,
    args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'] });
  const results = [];
  try {
    for (const width of (process.env.MDS_UI_WIDTHS || '1440,900,390').split(',').map(Number)) for (const theme of (process.env.MDS_UI_THEMES || 'dark,light').split(',')) {
      results.push(await scenario(browser, width, theme));
      fs.writeFileSync(path.join(evidence, 'browsing-results.json'), JSON.stringify({ fixtureOnly: true, results }, null, 2));
      console.log(JSON.stringify({ width, theme, passed: true }));
    }
    fs.writeFileSync(path.join(evidence, 'browsing-results.json'), JSON.stringify({ fixtureOnly: true, results }, null, 2));
    console.log(JSON.stringify({ passed: true, scenarios: results.length }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.stack || error.message); process.exitCode = 1; });
