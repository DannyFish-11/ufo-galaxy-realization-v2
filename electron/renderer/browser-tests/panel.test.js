'use strict';
/**
 * 面板的行为：真的打开打包后的 dist/，后端用拦截的方式给，问浏览器屏幕上到底发生了什么。
 *
 * 钉的都是读源码证明不了的：
 *   · 它忙的时候发送键真的变成停止键，按下去先让后端停；
 *   · 叫停那一刻正在飞的操作说「不确定」，不说「失败」；
 *   · 自己发起的那一轮不会在对话里出现两遍（后端也会把它推到 WS 上）；别的界面（语音）说的会出现；
 *   · 面板关着时说过的话，重开就在 —— 打开时读的是后端的对话主线；
 *   · 此刻在哪一相只认 WS —— SSE 的 phase 帧不能把线和岛带偏。
 */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { launch, until, openPanel, gate } = require('./harness');

let browser;
let skipped = false;

before(async (t) => {
  browser = await launch(t);
  skipped = browser === null;
});
after(async () => {
  if (browser) await browser.close();
});

const say = (page, text) =>
  page.fill('.field input', text).then(() => page.press('.field input', 'Enter'));
const turns = (page, role) =>
  page.$$eval(`.turn[data-role="${role}"]`, (ns) => ns.map((n) => n.textContent));
const sendMode = (page) => page.$eval('.send', (b) => b.dataset.mode);
const waitWs = async (ws) => {
  const deadline = Date.now() + 8000;
  while (!ws.opened && Date.now() < deadline) await new Promise((r) => setTimeout(r, 25));
  assert.ok(ws.opened, '面板没连上 /ws/desktop-presence');
};

test('忙的时候发送键是停止键；按下去先让后端停；正在飞的操作说「不确定」', async (t) => {
  if (skipped) return;
  const running = gate();
  const stopCalls = [];
  const { ctx, page } = await openPanel(browser, {
    'GET /api/v1/sessions/primary': () => ({ json: { success: true, session_id: '' } }),
    'POST /api/v1/chat/stream': async () => {
      await running.wait; // 这一轮一直在跑，直到有人按停
      return {
        sse: [
          { type: 'meta', session_id: 's-1' },
          { type: 'done', response: '', stopped: true, unknown_actions: [{ summary: 'click(x=320, y=180)' }] },
        ],
      };
    },
    'POST /api/v1/presence/stop': ({ url }) => {
      stopCalls.push(url.searchParams.get('reason'));
      running.open();
      return { json: { success: true, stopped: [{ source: 'chat' }], reason: 'panel' } };
    },
  });
  try {
    assert.equal(await sendMode(page), 'send');
    await say(page, '帮我把桌面整理一下');
    await until(page, () => document.querySelector('.send').dataset.mode === 'stop');
    await page.click('.send');
    await until(page, () => document.querySelector('.send').dataset.mode === 'send');

    assert.deepEqual(stopCalls, ['panel'], '按停止没有先去让后端停（只断开 SSE 停不住它在动鼠标键盘）');
    const reply = (await turns(page, 'agent')).join('\n');
    assert.match(reply, /你叫停的/, '被叫停的那一轮不能说成「后端什么都没给」');
    assert.match(reply, /不确定/, '叫停那一刻正在飞的操作可能已经执行了 —— 要说不确定');
    assert.match(reply, /click\(x=320, y=180\)/, '没说是哪一步');
    assert.match(reply, /先看一眼屏幕/, '只说不确定、不说该做什么，等于把问题丢给人');
  } finally {
    await ctx.close();
  }
});

test('自己发起的那一轮不出现两遍；别的界面（语音）说的会出现', async (t) => {
  if (skipped) return;
  const running = gate();
  let clientId = null;
  const { ctx, page, ws } = await openPanel(browser, {
    'GET /api/v1/sessions/primary': () => ({ json: { success: true, session_id: '' } }),
    'POST /api/v1/chat/stream': async ({ body }) => {
      clientId = body.client_id;
      await running.wait;
      return { sse: [{ type: 'meta', session_id: 's-1' }, { type: 'done', response: 'ok' }] };
    },
  });
  try {
    await waitWs(ws);
    await say(page, '今天几号');
    await until(page, () => document.querySelectorAll('.turn[data-role="user"]').length === 1);
    while (!clientId) await new Promise((r) => setTimeout(r, 25));
    assert.ok(clientId.length >= 8, '发起这一轮没带 client_id，回声就认不出来');

    const push = (payload) => ws.server.send(JSON.stringify({ type: 'conversation', payload }));
    // 后端把这一轮同步推到 WS 上：自己的回声（带自己的 id）…
    push({ role: 'user', text: '今天几号', final: true, client_id: clientId });
    // …和另一个界面（语音，没有 client_id；或别的面板）说的话。
    push({ role: 'ai', text: '来自语音的一句话', final: true, client_id: '' });
    push({ role: 'ai', text: '来自另一个面板', final: true, client_id: 'other-panel' });
    await until(page, () => document.body.textContent.includes('来自另一个面板'));

    assert.equal((await turns(page, 'user')).filter((x) => x === '今天几号').length, 1, '自己的回声又画了一遍');
    const agent = (await turns(page, 'agent')).join('\n');
    assert.match(agent, /来自语音的一句话/);
    assert.match(agent, /来自另一个面板/);
    running.open();
  } finally {
    running.open();
    await ctx.close();
  }
});

test('面板关着时说过的话，重开就在：打开时读的是后端的对话主线', async (t) => {
  if (skipped) return;
  const historyCalls = [];
  const { ctx, page } = await openPanel(browser, {
    'GET /api/v1/sessions/primary': () => ({ json: { success: true, session_id: 'main-1' } }),
    'GET /api/v1/sessions/main-1/history': ({ url }) => {
      historyCalls.push(url.pathname);
      return {
        json: {
          success: true,
          history: [
            { role: 'user', content: '用嘴说的这句', timestamp: '2026-09-26T01:00:00' },
            { role: 'assistant', content: '它自己开口说的这句', timestamp: '2026-09-26T01:00:05' },
          ],
        },
      };
    },
  });
  try {
    await until(page, () => document.body.textContent.includes('它自己开口说的这句'));
    assert.deepEqual(historyCalls, ['/api/v1/sessions/main-1/history']);
    assert.ok((await turns(page, 'user')).includes('用嘴说的这句'));
  } finally {
    await ctx.close();
  }
});

test('此刻在哪一相只认 WS：SSE 的 phase 帧带不偏线和岛', async (t) => {
  if (skipped) return;
  const { ctx, page, ws } = await openPanel(browser, {
    'GET /api/v1/sessions/primary': () => ({ json: { success: true, session_id: '' } }),
    'POST /api/v1/chat/stream': () => ({
      sse: [
        { type: 'meta', session_id: 's-1' },
        { type: 'phase', phase: 'manifest' }, // 面板自己发起的那几轮里，SSE 也会报相位 —— 不能听它的
        { type: 'delta', text: '好' },
        { type: 'done', response: '好' },
        { type: 'phase', phase: 'silent' },
      ],
    }),
  });
  try {
    await waitWs(ws);
    ws.server.send(JSON.stringify({ type: 'state_event', payload: { render: { lifecycle: 'liminal' } } }));
    await until(page, () => document.querySelector('.shell').dataset.phase === 'liminal');

    await say(page, '随便说一句');
    await until(page, () => document.body.textContent.includes('好'));
    await page.waitForTimeout(300);
    assert.equal(
      await page.$eval('.shell', (n) => n.dataset.phase),
      'liminal',
      'SSE 的 phase 帧把相位带偏了 —— 此刻在哪一相只有一个写者（WS 的 render）',
    );
  } finally {
    await ctx.close();
  }
});

test('打开时：上次中断留下的「结果不明」提示一次；没有就一声不吭', async (t) => {
  if (skipped) return;
  const withActions = await openPanel(browser, {
    'GET /api/v1/sessions/primary': () => ({ json: { success: true, session_id: '' } }),
    'GET /api/v1/presence/unresolved-actions': () => ({
      json: { success: true, actions: [{ summary: 'click(x=1, y=2)' }], journal_degraded: false },
    }),
  });
  try {
    await until(withActions.page, () => document.body.textContent.includes('结果不确定'));
    const notice = (await turns(withActions.page, 'agent')).join('\n');
    assert.match(notice, /click\(x=1, y=2\)/);
    assert.match(notice, /先看一眼屏幕/);
  } finally {
    await withActions.ctx.close();
  }

  const none = await openPanel(browser, {
    'GET /api/v1/sessions/primary': () => ({ json: { success: true, session_id: '' } }),
    'GET /api/v1/presence/unresolved-actions': () => ({ json: { success: true, actions: [] } }),
  });
  try {
    await until(none.page, () => true);
    await none.page.waitForTimeout(500);
    assert.equal((await turns(none.page, 'agent')).length, 0, '没有结果不明的操作，就不该冒出任何提示');
  } finally {
    await none.ctx.close();
  }
});
