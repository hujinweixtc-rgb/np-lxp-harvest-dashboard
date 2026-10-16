// 素材快照验证 v2：滚动到表格，检查视口内缩略图真实加载情况
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');

(async () => {
  const base = process.env.DASH_URL || 'http://127.0.0.1:8795/index.html';
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

  // 滚动到素材明细表
  await page.evaluate(() => {
    const el = document.getElementById('postTable');
    if (el) el.scrollIntoView({ block: 'start' });
  });
  // 等待视口内图片加载（lazy 加载触发后需要时间走代理取 OSS）
  await page.waitForTimeout(12000);

  const stats = await page.evaluate(() => {
    const imgs = [...document.querySelectorAll('#postTable .post-thumb img')];
    const vis = imgs.filter(i => {
      const r = i.getBoundingClientRect();
      return r.top < window.innerHeight && r.bottom > 0;
    });
    let ok = 0, fail = 0, pending = 0;
    vis.forEach(i => {
      if (i.complete && i.naturalWidth > 0) ok++;
      else if (i.complete) fail++;
      else pending++;
    });
    return { total: imgs.length, inViewport: vis.length, ok, fail, pending };
  });
  console.log(`[主视图] 表内图片 ${stats.total}，视口内 ${stats.inViewport} → 成功 ${stats.ok} / 失败 ${stats.fail} / 加载中 ${stats.pending}`);
  await page.screenshot({ path: 'C:/tmp/shot_thumb_main2.png' });

  // DMS 素材页
  const nav = await page.$$('nav button, .nav button, [data-view]');
  for (const el of nav) {
    if (/DMS/.test((await el.textContent()) || '')) { await el.click(); break; }
  }
  await page.waitForTimeout(1000);
  await page.evaluate(() => {
    const el = document.getElementById('dmsTable');
    if (el) el.scrollIntoView({ block: 'start' });
  });
  await page.waitForTimeout(12000);
  const stats2 = await page.evaluate(() => {
    const imgs = [...document.querySelectorAll('#dmsTable .dms-thumb img')];
    const vis = imgs.filter(i => {
      const r = i.getBoundingClientRect();
      return r.top < window.innerHeight && r.bottom > 0;
    });
    let ok = 0, fail = 0, pending = 0;
    vis.forEach(i => {
      if (i.complete && i.naturalWidth > 0) ok++;
      else if (i.complete) fail++;
      else pending++;
    });
    return { total: imgs.length, inViewport: vis.length, ok, fail, pending };
  });
  console.log(`[DMS素材页] 表内图片 ${stats2.total}，视口内 ${stats2.inViewport} → 成功 ${stats2.ok} / 失败 ${stats2.fail} / 加载中 ${stats2.pending}`);
  await page.screenshot({ path: 'C:/tmp/shot_thumb_dms2.png' });

  console.log('JS 错误:', errors.length ? errors.slice(0, 5) : '无');
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
