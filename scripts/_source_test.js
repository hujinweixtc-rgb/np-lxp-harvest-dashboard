const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');

const EXE = path.join(os.homedir(), 'AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe');
const BASE = 'http://127.0.0.1:8790/index.html';
const COMMON = 'from=2026-10-01&to=2026-10-13&brand=NP&country=ID';

const read = () => `(() => ({
  status: (document.getElementById('status') || {}).textContent || '',
  kpis: [...document.querySelectorAll('#kpis .kpi, .kpis > *')].map(el => el.textContent.replace(/\\s+/g, ' ').trim()).slice(0, 8),
  sourceLabel: (document.getElementById('sourceLabel') || {}).textContent || ''
}))()`;

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1200 } });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + (e && e.message)));

  const out = {};
  for (const [name, extra] of [
    ['allSources', ''],
    ['designOnly', '&source=' + encodeURIComponent('设计素材（SC）')],
    ['editOnly', '&source=' + encodeURIComponent('剪辑素材（JJ）')],
  ]) {
    await page.goto(`${BASE}?${COMMON}${extra}`, { waitUntil: 'load', timeout: 120000 });
    await page.waitForTimeout(7000);
    out[name] = await page.evaluate(read());
  }
  await page.screenshot({ path: 'C:/tmp/shot_source_sc.png' });
  out.errors = errors;
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
