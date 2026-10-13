const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');

const EXE = path.join(os.homedir(), 'AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe');
const URL = process.argv[2] || 'http://127.0.0.1:8790/index.html';
const OUT = process.argv[3] || 'C:/tmp/shot.png';

(async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
  const errors = [];
  const logs = [];
  page.on('console', m => {
    const t = `${m.type()}: ${m.text()}`;
    logs.push(t);
    if (m.type() === 'error') errors.push(t);
  });
  page.on('pageerror', e => errors.push('pageerror: ' + (e && e.message)));
  page.on('requestfailed', r => errors.push('requestfailed: ' + r.url().slice(0, 140) + ' :: ' + (r.failure() && r.failure().errorText)));

  await page.goto(URL, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(9000);

  const info = await page.evaluate(() => {
    const txt = id => (document.getElementById(id) || {}).textContent || '';
    return {
      title: document.title,
      sourceLine: txt('sourceLine'),
      status: txt('status'),
      kpiCount: document.querySelectorAll('#kpis .kpi, .kpis > *').length,
      boardRows: document.querySelectorAll('#boardTable tbody tr').length,
      productRows: document.querySelectorAll('#productBars tbody tr').length,
      tag1Bars: document.querySelectorAll('#tag1Bars .barrow, #tag1Bars > *').length,
      tag1HtmlLen: (document.getElementById('tag1Bars') || {}).innerHTML?.length || 0,
      treeRoots: document.querySelectorAll('#tagTreemap .tree-root').length,
      hierarchyRows: document.querySelectorAll('#tagHierarchyTable tbody tr').length,
      detailRows: document.querySelectorAll('#postTable tbody tr').length,
      trendCanvas: !!document.getElementById('trendChart'),
      panelTitles: [...document.querySelectorAll('.panel h2')].map(el => el.textContent.trim()),
    };
  });

  await page.screenshot({ path: OUT, fullPage: false });
  console.log(JSON.stringify({ info, errors: errors.slice(0, 25), errorCount: errors.length }, null, 2));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
