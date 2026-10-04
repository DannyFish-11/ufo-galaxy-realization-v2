'use strict';
/**
 * 浏览器行为测试的公共件。
 *
 * 为什么要真开浏览器
 * ------------------
 * 覆盖层的坏法全是"不报错、画面不对"。最典型的一条：边光的呼吸曾是 CSS 关键帧，关键帧里的
 * opacity 压过普通声明 —— 隐私急停把 --rim 写成 0 也没用，屏幕上照样一明一暗地亮着。
 * 读源码、读 CSS 文本都看不出来；要问浏览器「算出来的 opacity 到底是多少」。
 * 这也是借自 AFK-surf/Comma 的一条规矩：别靠读实现的源码去推断运行行为，让行为自己说话。
 *
 * 没有浏览器时
 * ------------
 * 本地没装 Chromium：显式跳过并说明怎么装。**CI 里设 GALAXY_REQUIRE_BROWSER=1**：缺浏览器就
 * 是红的 —— 一条永远被跳过的绿线等于没有这条测试。
 */
const path = require('node:path');
const { chromium } = require('playwright');

const RENDERER = path.resolve(__dirname, '..');
const REQUIRE = process.env.GALAXY_REQUIRE_BROWSER === '1';

const fileUrl = (...parts) => 'file://' + path.join(RENDERER, ...parts);

/** 开浏览器。拿不到时：CI 抛错，本地跳过（并说清怎么装）。返回 null 表示已跳过。 */
async function launch(t) {
  try {
    return await chromium.launch();
  } catch (err) {
    if (REQUIRE) throw err;
    t.skip('没有可用的 Chromium（本地装一次: npx playwright install chromium）: ' + String(err.message).split('\n')[0]);
    return null;
  }
}

/** 轮询直到页面里的条件为真；比固定 sleep 稳，也比 sleep 快。 */
function until(page, fn, arg, timeout = 8000) {
  return page.waitForFunction(fn, arg, { timeout, polling: 50 });
}

module.exports = { RENDERER, fileUrl, launch, until, REQUIRE };

// ── 面板：真的打开打包后的 dist/，后端用拦截的方式给 ────────────────────────

const BASE = 'http://galaxy.test';
const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': '*',
  'access-control-allow-methods': 'GET,POST,PUT,DELETE,OPTIONS',
};

/**
 * 打开面板并接管它对后端的全部请求。
 *
 * ``handlers`` 是 {"METHOD /path": async (ctx) => 响应}，响应是 ``{json}`` 或 ``{sse: [帧…]}``；
 * 没登记的一律 404 —— 面板开机会拉一堆别的（配置、档位、模型…），它们与这里要测的无关。
 * 返回 ``ws``：面板连上 /ws/desktop-presence 之后，用 ``ws.server.send(...)`` 扮后端往它那边推帧。
 */
async function openPanel(browser, handlers = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1200, height: 760 } });
  const page = await ctx.newPage();
  await page.addInitScript((base) => {
    window.galaxyShell = { base };
  }, BASE);

  const ws = { server: null, opened: false };
  await page.routeWebSocket(/\/ws\/desktop-presence$/, (server) => {
    ws.server = server;
    ws.opened = true;
  });

  const calls = [];
  await page.route(`${BASE}/**`, async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS });
    const key = `${req.method()} ${url.pathname}`;
    calls.push(key + url.search);
    const handler = handlers[key];
    if (!handler) {
      return route.fulfill({ status: 404, headers: { ...CORS, 'content-type': 'application/json' }, body: '{}' });
    }
    const out = await handler({ req, url, body: req.postData() ? safeJson(req.postData()) : null });
    if (out.sse) {
      const body = out.sse.map((f) => `data: ${JSON.stringify(f)}\n\n`).join('');
      return route.fulfill({ status: 200, headers: { ...CORS, 'content-type': 'text/event-stream' }, body });
    }
    return route.fulfill({
      status: out.status || 200,
      headers: { ...CORS, 'content-type': 'application/json' },
      body: JSON.stringify(out.json ?? {}),
    });
  });

  await page.goto(fileUrl('panel', 'dist', 'index.html'));
  await page.waitForSelector('.shell');
  return { ctx, page, ws, calls };
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** 一个手动开关：``await gate.wait`` 一直等到 ``gate.open()``。让一轮对话「一直在跑」到我们说放。 */
function gate() {
  let open;
  const wait = new Promise((resolve) => {
    open = resolve;
  });
  return { wait, open };
}

module.exports.openPanel = openPanel;
module.exports.gate = gate;
module.exports.BASE = BASE;
