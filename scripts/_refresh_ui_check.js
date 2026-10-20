// 验证刷新按钮在 static / live 两种渠道下的行为
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');
const fs = require('fs');

const OUT = 'C:/Users/Administrator/WorkBuddy/蜚美/np-lxp-harvest-dashboard/tmp_js';
if (!fs.existsSync(OUT)) fs.mkdirSync(OUT, { recursive: true });

(async () => {
  const browser = await chromium.launch({
    executablePath: path.join(os.homedir(), 'AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe'),
    headless: true,
    args: ['--no-sandbox']
  });

  const probe = async (url, tag) => {
    const page = await browser.newPage({ viewport: { width: 1680, height: 700 } });
    await page.goto(url, { waitUntil: 'networkidle', timeout: 120000 });
    await page.waitForTimeout(3500);
    const info = await page.evaluate(() => {
      const btn = document.getElementById('refreshData');
      const wrap = document.getElementById('refreshWrap');
      const prog = document.getElementById('refreshProgress');
      return {
        badge: document.getElementById('appVersion')?.textContent,
        badgeClass: document.getElementById('appVersion')?.className,
        wrapHidden: wrap?.hidden,
        wrapDisplay: wrap ? getComputedStyle(wrap).display : null,
        btnText: btn?.textContent,
        btnClass: btn?.className,
        progress: prog && !prog.hidden ? prog.textContent : '(hidden)'
      };
    });
    console.log(tag, JSON.stringify(info));
    await page.screenshot({ path: path.join(OUT, `refresh_${tag}.png`), clip: { x: 0, y: 0, width: 1680, height: 120 } });
    await page.close();
    return info;
  };

  await probe('http://127.0.0.1:8793/index.html', 'static');
  await probe('https://np-lxp-harvest-dashboard-a2vd6kqlpq-as.a.run.app/', 'live');

  await browser.close();
})();
