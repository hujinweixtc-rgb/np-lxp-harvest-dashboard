const { chromium } = require('playwright-core');
const path = require('path');
const fs = require('fs');

const URL = process.argv[2] || 'http://127.0.0.1:8790/index.html';
const OUT_DIR = process.argv[3] || 'C:/tmp';

const EXECUTABLES = [
  path.join(process.env.LOCALAPPDATA || '', 'ms-playwright/chromium-1234/chrome-win64/chrome.exe'),
  path.join(process.env.LOCALAPPDATA || '', 'ms-playwright/chromium-1234/chrome-win/chrome.exe'),
].filter(p => p && fs.existsSync(p));

function fieldsInfo() {
  const bar = document.getElementById('filtersBar');
  const visible = [...bar.querySelectorAll('.field')].filter(f => f.offsetParent !== null);
  const rects = visible.map(f => {
    const label = f.querySelector('label');
    const r = f.getBoundingClientRect();
    return { label: label ? label.textContent.trim() : '?', top: Math.round(r.top), width: Math.round(r.width) };
  });
  const rows = [...new Set(rects.map(r => r.top))];
  const hidden = [...bar.querySelectorAll('.field')].filter(f => f.offsetParent === null)
    .map(f => (f.querySelector('label') || {}).textContent || '?');
  return {
    collapsed: bar.classList.contains('collapsed'),
    visibleLabels: rects.map(r => r.label),
    rowCount: rows.length,
    rows: rows.map(top => ({ top, labels: rects.filter(r => r.top === top).map(r => r.label) })),
    hiddenCount: hidden.length,
    btnText: (document.querySelector('#filtersToggle .filters-toggle-text') || {}).textContent,
  };
}

(async () => {
  const browser = await chromium.launch({ executablePath: EXECUTABLES[0], headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  await page.goto(URL, { waitUntil: 'load', timeout: 180000 });
  await page.waitForFunction(() => {
    const el = document.getElementById('kpis');
    return el && el.children.length > 0;
  }, null, { timeout: 180000 });
  await page.waitForTimeout(800);

  // 清掉历史折叠状态，保证从展开态开始
  await page.evaluate(() => localStorage.removeItem('np-lxp-filters-collapsed'));
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => {
    const el = document.getElementById('kpis');
    return el && el.children.length > 0;
  }, null, { timeout: 180000 });
  await page.waitForTimeout(800);

  const expanded = await page.evaluate(fieldsInfo);
  await page.screenshot({ path: OUT_DIR + '/collapse_expanded.png', fullPage: false });

  // 收起
  await page.click('#filtersToggle');
  await page.waitForTimeout(400);
  const collapsed = await page.evaluate(fieldsInfo);
  await page.screenshot({ path: OUT_DIR + '/collapse_collapsed.png', fullPage: false });

  // 刷新，验证状态持久化
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(() => document.getElementById('kpis') && document.getElementById('kpis').children.length > 0, null, { timeout: 180000 });
  await page.waitForTimeout(800);
  const afterReload = await page.evaluate(fieldsInfo);

  // 再展开，验证 DOM 恢复
  await page.click('#filtersToggle');
  await page.waitForTimeout(400);
  const reExpanded = await page.evaluate(fieldsInfo);

  console.log(JSON.stringify({
    expanded: { rows: expanded.rowCount, visible: expanded.visibleLabels.length, hidden: expanded.hiddenCount, btn: expanded.btnText },
    collapsed: { rows: collapsed.rowCount, visible: collapsed.visibleLabels, hidden: collapsed.hiddenCount, btn: collapsed.btnText, rowDetail: collapsed.rows },
    afterReloadCollapsed: afterReload.collapsed,
    reExpanded: { rows: reExpanded.rowCount, visible: reExpanded.visibleLabels.length, btn: reExpanded.btnText },
    errors: errors.filter(e => !/ORB|ERR_BLOCKED/.test(e)).slice(0, 10),
  }, null, 2));

  await browser.close();
})().catch(e => { console.error('FATAL', e.message); process.exit(1); });
