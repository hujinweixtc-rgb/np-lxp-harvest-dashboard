const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');

const EXE = path.join(os.homedir(), 'AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe');
const BASE = process.env.DASH_URL || 'http://127.0.0.1:8791/index.html';

( async () => {
  const browser = await chromium.launch({ executablePath: EXE, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1680, height: 1100 } });
  const errors = [];
  page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });
  page.on('pageerror', e => errors.push('pageerror: ' + (e && e.message)));

  await page.goto(BASE, { waitUntil: 'load', timeout: 120000 });
  await page.waitForTimeout(9000);

  const info = await page.evaluate(() => {
    const version = document.getElementById('appVersion');
    const wrap = document.getElementById('refreshWrap');
    const btn = document.getElementById('refreshData');
    const prog = document.getElementById('refreshProgress');
    return {
      version: version ? version.textContent : null,
      versionLive: version ? version.classList.contains('live') : null,
      refreshVisible: wrap ? !wrap.hidden : null,
      refreshBtn: btn ? btn.textContent.trim() : null,
      refreshBtnDisabled: btn ? btn.disabled : null,
      progressVisible: prog ? !prog.hidden : null,
      progressText: prog ? prog.textContent.trim() : null,
      sourceLine: (document.getElementById('sourceLine') || {}).textContent || '',
      tableRows: document.querySelectorAll('table tbody tr').length,
      kpiCount: document.querySelectorAll('#kpis .kpi, .kpis > *').length,
    };
  });

  await page.screenshot({ path: 'C:/tmp/shot_refresh_btn.png', fullPage: false });

  // 静态托管回退验证：/api/status 打到 404 时应显示 static 且隐藏按钮
  const page2 = await browser.newPage();
  await page2.route('**/api/**', route => route.fulfill({ status: 404, body: 'not found' }));
  await page2.goto(BASE, { waitUntil: 'load', timeout: 120000 });
  await page2.waitForTimeout(8000);
  const fallback = await page2.evaluate(() => {
    const version = document.getElementById('appVersion');
    const wrap = document.getElementById('refreshWrap');
    return {
      version: version ? version.textContent : null,
      versionLive: version ? version.classList.contains('live') : null,
      refreshVisible: wrap ? !wrap.hidden : null,
      tableRows: document.querySelectorAll('table tbody tr').length,
    };
  });

  console.log(JSON.stringify({ live: info, staticFallback: fallback, errors }, null, 2));
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
