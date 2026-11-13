/* Compose a readable, original-resolution guide from read-only browser fixtures.
 * Run on the validation host after validate_fleet_overview.cjs --all-live.
 * Usage: node tools/render_overview_operator_guide.cjs INPUT_DIRECTORY OUTPUT.png [MANIFEST.json]
 * An optional manifest reuses the renderer for another operator workspace.
 */
const fs = require('fs');
const path = require('path');
const assert = require('assert/strict');
const { chromium } = require(process.env.MDS_PLAYWRIGHT_MODULE || 'playwright');

async function main() {
  const [, , input, output, manifestPath] = process.argv;
  assert(input && output && path.isAbsolute(input) && path.isAbsolute(output), 'Use absolute input/output paths');
  const image = name => `data:image/png;base64,${fs.readFileSync(path.join(input, name)).toString('base64')}`;
  const manifest = manifestPath ? JSON.parse(fs.readFileSync(manifestPath, 'utf8')) : {};
  const escape = value => String(value).replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
  const title = manifest.title || 'OVERVIEW · FIELD CONTROLS';
  const steps = manifest.steps || [
    ['01', 'Check the fleet', 'Confirm REAL or SITL. Check live aircraft and attention. Click an aircraft to inspect it.', 'overview-3-1440-dark.png'],
    ['02', 'Review command aircraft', 'To beside the flight controls owns recipients. Change the draft, then Use N aircraft. Cancel keeps the previous set; Show and search only change the display.', 'command-aircraft-1440-dark.png'],
    ['03', 'Review Takeoff', 'Check aircraft, height and launch mode. The review keeps its own exact aircraft list; excluding one here does not change Overview recipients.', 'takeoff-review-dark.png'],
    ['04', 'Inspect without changing recipients', 'Names and silhouettes open current measurements. Inspection does not select an aircraft.', 'inspector-dark.png'],
    ['05', 'Recover deliberately', 'Overview Return is immediate PX4 RTL. Managed Return and mission Start stay on the mission page. Follow results in Activity.', 'return-review-dark.png'],
  ];
  const browser = await chromium.launch({ headless: true,
    ...((process.env.MDS_CHROMIUM_EXECUTABLE || process.env.MDS_CHROMIUM_PATH) ? { executablePath: process.env.MDS_CHROMIUM_EXECUTABLE || process.env.MDS_CHROMIUM_PATH } : {}),
    args: ['--no-sandbox', '--disable-dev-shm-usage'] });
  try {
    const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, deviceScaleFactor: 1 });
    await page.route('**/*', route => route.abort());
    await page.setContent(`<!doctype html><html lang="en"><meta charset="utf-8"><title>${escape(title)}</title>
      <style>*{box-sizing:border-box}body{margin:0;padding:48px;background:#101820;color:#e8eef4;font:24px/1.4 Arial,sans-serif}h1{margin:0;font-size:46px;letter-spacing:.02em}header p{color:#b6c8d5;margin:8px 0 0}section{margin-top:40px;border-top:2px solid #476071;padding-top:24px}h2{font-size:34px;margin:0;display:flex;gap:24px;align-items:center}h2 span{color:#63b6e7;font:700 32px monospace}section p{margin:10px 0 20px;max-width:1400px;color:#d2dce5}img{display:block;max-width:1440px;max-height:none;width:auto;height:auto;margin:0 auto;border:1px solid #476071}footer{border-top:2px solid #476071;margin-top:40px;padding-top:20px;color:#b6c8d5;font-size:22px}</style>
      <header><h1>${escape(title)}</h1><p>${escape(manifest.subtitle || 'Check → select → review → confirm → monitor Activity')}</p></header>
      ${steps.map(([number, stepTitle, text, file]) => `<section><h2><span>${escape(number)}</span>${escape(stepTitle)}</h2><p>${escape(text)}</p><img alt="${escape(stepTitle)}" src="${image(file)}"></section>`).join('')}
      <footer>${escape(manifest.footer || 'Illustrated with synthetic aircraft. Closing a review does not stop an aircraft. Watch every result in Activity.')}</footer></html>`);
    await page.evaluate(() => Promise.all([...document.images].map(img => img.decode())));
    await page.screenshot({ path: output, fullPage: true });
    console.log(JSON.stringify({ status: 'saved', output, steps: steps.length }));
  } finally { await browser.close(); }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
