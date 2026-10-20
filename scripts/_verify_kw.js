// 验证：① 卡片标签完整不省略 ② 弹窗图上文案带中译 ③ 概览卖点/文案交叉分析表
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');
const fs = require('fs');

const DASH = process.env.DASH_URL || 'http://127.0.0.1:8793/index.html';
const OUT = 'C:/Users/Administrator/WorkBuddy/蜚美/np-lxp-harvest-dashboard/tmp_js';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath: path.join(os.homedir(), 'AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'),
    headless: true,
    args: ['--no-sandbox']
  });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1080 } });
  const errors = [];
  page.on('pageerror', err => errors.push('PAGEERROR: ' + String(err.message).slice(0, 200)));
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text().slice(0, 160)); });

  await page.goto(DASH, { waitUntil: 'networkidle', timeout: 120000 });
  await page.waitForTimeout(3500);

  // ① 概览：卖点/文案交叉分析表
  const kw = await page.evaluate(() => {
    const t = document.getElementById('aiKeywordTable');
    if (!t) return { missing: true };
    return {
      rows: t.querySelectorAll('tbody tr').length,
      headers: [...t.querySelectorAll('thead th')].map(th => th.textContent.trim()),
      first: [...t.querySelectorAll('tbody tr')].slice(0, 3).map(tr => tr.textContent.replace(/\s+/g, ' ').trim().slice(0, 90)),
      note: document.getElementById('aiKwNote')?.textContent
    };
  });
  console.log('交叉分析表:', JSON.stringify(kw));

  if (!kw.missing && kw.rows) {
    await page.evaluate(() => {
      const head = document.getElementById('aiKeywordTable').closest('section');
      head.scrollIntoView({ block: 'start' });
    });
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(OUT, 'ai_keywords.png'), clip: { x: 0, y: 0, width: 1680, height: 900 } });
    console.log('交叉分析截图 done');
  }

  // ② DMS 卡片：标签是否还有省略号
  await page.evaluate(() => {
    const tab = document.querySelector('.tab[data-view="dms"]');
    if (tab) tab.click();
  });
  await page.waitForTimeout(2200);

  const chip = await page.evaluate(() => {
    const chips = [...document.querySelectorAll('.dms-card .theme-chip')];
    const bad = chips.filter(c => {
      const b = c.querySelector('b');
      const i = c.querySelector('i');
      return (!b || b.scrollWidth > b.clientWidth + 1) || (i && i.scrollWidth > i.clientWidth + 1);
    });
    return {
      cards: document.querySelectorAll('.dms-card').length,
      chips: chips.length,
      clipped: bad.length,
      sample: chips.slice(0, 4).map(c => (c.textContent || '').trim().slice(0, 60))
    };
  });
  console.log('卡片标签:', JSON.stringify(chip));

  await page.evaluate(() => {
    const grid = document.getElementById('dmsCards');
    const card = grid.querySelector('.dms-card');
    if (card) window.scrollTo(0, window.scrollY + card.getBoundingClientRect().top - 120);
  });
  await page.waitForTimeout(1400);
  const rect = await page.evaluate(() => {
    const r = document.getElementById('dmsCards').getBoundingClientRect();
    return { x: Math.max(0, r.x), y: Math.max(0, r.y), width: Math.min(r.width, 1670), height: Math.min(r.height, 720) };
  });
  await page.screenshot({ path: path.join(OUT, 'kw_cards.png'), clip: rect });
  console.log('卡片截图 done');

  // ③ 弹窗：图上文案 + 中译
  const opened = await page.evaluate(() => {
    const cards = [...document.querySelectorAll('.dms-card')];
    const card = cards.find(c => c.querySelector('[data-lb-key]') && c.querySelector('[data-lb-src]'));
    if (!card) return null;
    card.scrollIntoView({ block: 'center' });
    const el = card.querySelector('[data-lb-src]');
    el.click();
    return { key: el.dataset.lbKey };
  });
  console.log('打开弹窗:', JSON.stringify(opened));
  await page.waitForTimeout(4000);

  const lb = await page.evaluate(() => {
    const box = document.getElementById('lbThemes');
    if (!box) return { box: null, url: location.href };
    return {
      hidden: box.hidden,
      text: (box.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 260),
      hasZh: !!box.querySelector('.lb-onimage-zh'),
      zh: box.querySelector('.lb-onimage-zh')?.textContent || ''
    };
  });
  console.log('弹窗:', JSON.stringify(lb));
  await page.screenshot({ path: path.join(OUT, 'kw_lightbox.png') });

  console.log('页面错误:', errors.length ? errors.slice(0, 4).join(' | ') : '无');
  await browser.close();
})();
