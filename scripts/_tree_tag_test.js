// 树状图原始标签口径验证：打开本地页面，检查树状图根节点数量与层级汇总表行数
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');

(async () => {
  const base = process.env.DASH_URL || 'http://127.0.0.1:8792/index.html';
  const browser = await chromium.launch({
    executablePath: path.join(os.homedir(), 'AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'),
    headless: true,
    args: ['--no-sandbox']
  });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1050 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto(base, { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForTimeout(1500);

  const roots = await page.$$eval('#tagTreemap .tree-root', els => els.slice(0, 12).map(el => ({
    title: el.querySelector('.tree-root-title')?.textContent.trim(),
    meta: el.querySelector('.tree-root-meta')?.textContent.replace(/\s+/g, ' ').trim().slice(0, 120)
  })));
  console.log('=== 树状图根节点（前 12）=== 共', await page.$$eval('#tagTreemap .tree-root', els => els.length));
  roots.forEach(r => console.log(' ', r.title, '|', r.meta));

  const rows = await page.$$eval('#tagHierarchyTable tbody tr', els => els.length);
  console.log('层级汇总表行数:', rows);
  const firstRows = await page.$$eval('#tagHierarchyTable tbody tr', els => els.slice(0, 8).map(el => el.querySelector('td .tree-indent')?.textContent.trim()));
  firstRows.forEach(t => console.log('  表行:', t));

  // tag1 分布条形图
  const tag1Bars = await page.$$eval('#tag1Bars .bar-row, #tag1Bars [class*=bar]', els => els.length).catch(() => 0);
  console.log('一级标签分布条目数:', tag1Bars);

  // 筛选器选项
  await page.click('.multi-select[data-key="tag1"] .multi-button');
  await page.waitForTimeout(400);
  const opts = await page.$$eval('.multi-select[data-key="tag1"] .multi-panel label, .multi-select[data-key="tag1"] .multi-panel [data-value]', els => els.slice(0, 15).map(el => el.textContent.trim().replace(/\s+/g, ' ')));
  console.log('一级标签筛选选项（前 15）:', opts);
  console.log('JS 错误:', errors.length ? errors : '无');

  await page.screenshot({ path: 'C:/tmp/shot_tree_tags.png', fullPage: false });
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
