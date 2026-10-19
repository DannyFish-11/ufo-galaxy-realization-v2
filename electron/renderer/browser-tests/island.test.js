'use strict';
/**
 * 灵动岛（electron/renderer/island.js，对齐 winsland）：喂它后端会发的帧（`type="island"` 的卡片、state_event 的
 * speaking、render.perception）与主进程的剪贴板提示，问浏览器屏幕上到底画了什么、点下去发出了什么请求。
 *
 * 钉的是：
 *   · 静息里来一张卡，岛自己长出来，写标题 / 副标题 / 「+N」，进度那道线走到对应的位置；过期了自己收回去；
 *   · 卡片不改岛的长短 —— 字再多，收起时也不超过上限，放不下就截断；
 *   · 急停时卡不上岛（岛就是那道细线）；
 *   · 指针停在岛上时窗口才接鼠标，离开就交还桌面；点一下才展开，展开后「停下」「打开面板」「知道了」各打各的；
 *   · 它在说话：岛上一排声波，悬停换成一句提示，点开能叫它停下；说完留一会儿再收；
 *   · 排法照 winsland 的药丸：桌宠贴左端、字居中、尾巴贴右端，宽度跟着内容走；岛旁边没有另一座小岛；
 *   · 点开后换到「感知」那一页：每一路一行，点用面板那套光（不是绿 / 橙 / 黄），能「暂停感知」；
 *   · 剪贴板一变：「已复制 · 图片」亮一下，不接鼠标；
 *   · 桌宠还是那一只 —— 来什么、去什么，它一直坐在岛上。
 */
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { fileUrl, launch, until } = require('./harness');

let browser;
let skipped = false;

before(async (t) => {
  browser = await launch(t);
  skipped = browser === null;
});
after(async () => {
  if (browser) await browser.close();
});

const percept = (over = {}) => ({
  source: 'live', is_sensing: true, privacy_paused: false, ambient_action: 'none', ambient_rationale: '',
  modalities: [{ modality: 'screen', state: 'live', signal_age_s: 0.4 }],
  ...over,
});

const frame = (over = {}) => ({
  render: {
    lifecycle: 'silent', previous_lifecycle: null, transition_kind: 'none', transition_seq: 0,
    last_transition: 'none', continuum_phase: 'formless', is_returning: false, liminal_activity: 'none',
    hybrid_execution: { is_decided: false, mode: 'none', reason: '', confidence: 0 },
    acting: false, stop_key: '', source: 'continuum', degraded: false, degrade_reason: null,
    collapse_tendency: 0.2, retreat_tendency: 0.1, stability: 0.9, perception: percept(),
    ...over,
  },
});

const card = (over = {}) => ({
  id: 'c1', kind: 'computer_use', title: '正在操作电脑', subtitle: '第 3/10 步 · 刚点击', body: '',
  progress: 0.2, tone: 'info', priority: 'high', action: 'stop', expires_in_s: null,
  ...over,
});

async function open() {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  // 外壳那一侧：记下窗口穿透开关与「打开面板」
  await page.addInitScript(() => {
    window.__shell = { ignore: [], panel: 0, clip: null };
    window.galaxyAPI = {
      setIgnoreMouse: (v) => window.__shell.ignore.push(v),
      openPanel: () => { window.__shell.panel += 1; },
      onClipboard: (cb) => { window.__shell.clip = cb; },
    };
  });
  const calls = [];
  await page.route('http://127.0.0.1:9000/api/**', (route) => {
    calls.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`);
    route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  });
  await page.goto(fileUrl('index.html'));
  await page.waitForFunction(() => !!window.lumivRenderer);
  const send = (f) => page.evaluate((x) => window.lumivRenderer._onStateEvent(x), f);
  const cards = (list) => page.evaluate((c) => window.lumivRenderer.isle.setCards({ cards: c, seq: 1 }), list);
  const look = () => page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    const isl = q('#island');
    const r = isl.getBoundingClientRect();
    return {
      text: q('#islandText').textContent,
      sub: q('#islandSub').hidden ? null : q('#islandSub').textContent,
      more: q('#islandMore').hidden ? null : q('#islandMore').textContent,
      tone: isl.dataset.tone || '',
      wave: !q('#islandWave').hidden,
      width: r.width,
      height: r.height,
      opacity: parseFloat(getComputedStyle(isl).opacity),
      bar: document.documentElement.style.getPropertyValue('--ibar'),
      barOn: document.documentElement.style.getPropertyValue('--ibar-on'),
      fullShown: !q('.isl-full').hidden,
      petInIsland: !!isl.querySelector('#pet'),
      buttons: [...isl.querySelectorAll('button[data-act]')].filter((b) => !b.hidden).map((b) => b.dataset.act),
    };
  });
  return { ctx, page, send, cards, look, calls };
}

test('静息里来一张卡：岛长出来写卡上的字，进度线走到对应位置；桌宠还坐在岛上', async () => {
  if (skipped) return;
  const { ctx, page, send, cards, look } = await open();
  try {
    await send(frame());
    await cards([card(), card({ id: 'c2', title: '有设备在等你同意', subtitle: '客厅平板', tone: 'warning', action: 'panel' })]);
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    const v = await look();
    assert.equal(v.text, '正在操作电脑');
    assert.equal(v.sub, '第 3/10 步 · 刚点击');
    assert.equal(v.more, '+1', '队列里还有一张，岛上要说出来');
    assert.equal(v.tone, 'info');
    assert.equal(v.barOn, '1');
    assert.equal(v.bar, '20.0%');
    assert.ok(v.opacity > 0.99 && v.height >= 27 && v.height <= 29, `收起态还是那条瘦长的药丸，实际高 ${v.height}`);
    assert.ok(v.petInIsland, '桌宠还是那一只，一直坐在岛上');
  } finally {
    await ctx.close();
  }
});

test('卡过期了自己走，岛收回去', async () => {
  if (skipped) return;
  const { ctx, page, send, cards } = await open();
  try {
    await send(frame());
    // 寿命要比岛长出来那 0.45 秒宽裕得多：机器忙（帧率掉）时卡要是先过期，岛还没长满就开始收，第一个等待永远等不到
    await cards([card({ title: '做完了', subtitle: '对着屏幕核对过', tone: 'success', progress: null, expires_in_s: 2.5 })]);
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    await until(page, () => window.lumivRenderer.isle.act <= 0.001, undefined, 8000);
    assert.equal(await page.evaluate(() => window.lumivRenderer.isle.cards.length), 0);
  } finally {
    await ctx.close();
  }
});

test('卡片不改岛的长短：字再多，收起时也不超过上限，副标题截断', async () => {
  if (skipped) return;
  const { ctx, page, send, cards, look } = await open();
  try {
    await send(frame());
    await cards([card({ subtitle: '一段很长很长的副标题'.repeat(8), progress: null })]);
    // 弹簧长出来会略过冲几个百分点 —— 量的是停稳之后
    await until(page, () => window.lumivRenderer.isle.act >= 0.999 && !window.lumivRenderer.isle.moving());
    await page.waitForTimeout(100);
    const v = await look();
    assert.ok(v.width <= 441, `收起态宽 ${v.width}px，超过上限 440`);
    assert.ok(v.width >= 223, `收起态宽 ${v.width}px，比下限还窄`);
    const clipped = await page.evaluate(() => {
      const el = document.querySelector('#islandSub');
      return el.scrollWidth > el.clientWidth;
    });
    assert.ok(clipped, '放不下的副标题应该被截断，而不是把岛撑宽');
  } finally {
    await ctx.close();
  }
});

test('急停时卡不上岛：岛就是那道细线', async () => {
  if (skipped) return;
  const { ctx, page, send, cards, look } = await open();
  try {
    await send(frame({ perception: percept({ privacy_paused: true, is_sensing: false }) }));
    await cards([card()]);
    await page.waitForTimeout(600);
    const v = await look();
    assert.ok(v.height <= 2.5, `急停时岛只该剩一道线，实际高 ${v.height}`);
    assert.equal(v.sub, null);
    assert.equal(v.barOn, '0');
  } finally {
    await ctx.close();
  }
});

test('指针停在岛上才接鼠标；点一下展开，三个键各打各的', async () => {
  if (skipped) return;
  const { ctx, page, send, cards, look, calls } = await open();
  try {
    await send(frame({ lifecycle: 'manifest', acting: true, stop_key: 'Esc' }));
    await cards([
      card(),
      card({ id: 'truth_chain:isolated', kind: 'result', title: '有结果没收口', subtitle: '1 条等你看',
        tone: 'warning', priority: 'normal', action: 'panel', progress: null, expires_in_s: 30 }),
    ]);
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    const box = await page.evaluate(() => {
      const r = document.querySelector('#island').getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    });

    await page.mouse.move(20, 600);
    await page.mouse.move(box.x, box.y);
    await until(page, () => document.querySelector('#island').dataset.hover === 'true');
    assert.deepEqual(await page.evaluate(() => window.__shell.ignore), [false], '进了岛的范围，窗口才接鼠标');

    await page.mouse.click(box.x, box.y);
    await until(page, () => window.lumivRenderer.isle.open >= 0.999);
    let v = await look();
    assert.ok(v.fullShown && v.height > 40, `点开之后岛往下长，实际高 ${v.height}`);
    assert.deepEqual(v.buttons.sort(), ['panel', 'stop', 'view'],
      '在动手：停下；有要去面板点的：打开面板；进行中的那张不给「知道了」；换页那颗一直在');
    const rows = await page.evaluate(() => [...document.querySelectorAll('#islandList .row')].map((r) => r.textContent));
    assert.deepEqual(rows, ['有结果没收口 · 1 条等你看']);

    await page.click("button[data-act='stop']");
    await page.click("button[data-act='panel']");
    await until(page, () => window.__shell.panel === 1);
    await page.waitForTimeout(200);
    assert.ok(calls.includes('POST /api/v1/presence/stop'), `「停下」该打住手接口，实际 ${calls}`);

    // 离开岛：交还鼠标，过一会儿收回去
    await page.mouse.move(20, 600);
    await until(page, () => document.querySelector('#island').dataset.hover === 'false');
    assert.deepEqual(await page.evaluate(() => window.__shell.ignore), [false, true]);
    await until(page, () => window.lumivRenderer.isle.open <= 0.001, undefined, 5000);
    v = await look();
    assert.equal(v.fullShown, false);
  } finally {
    await ctx.close();
  }
});

test('「知道了」撤掉排第一的那张，后端也撤', async () => {
  if (skipped) return;
  const { ctx, page, send, cards, calls } = await open();
  try {
    await send(frame());
    await cards([card({ id: 'device:pending:abc', kind: 'device', title: '有设备在等你同意', subtitle: '客厅平板',
      tone: 'warning', action: 'panel', progress: null, expires_in_s: 20 })]);
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    await page.evaluate(() => { window.lumivRenderer.isle.expanded = true; });
    await until(page, () => !document.querySelector("button[data-act='dismiss']").hidden);
    await page.evaluate(() => document.querySelector("button[data-act='dismiss']").click());
    await until(page, () => window.lumivRenderer.isle.cards.length === 0);
    await until(page, () => window.lumivRenderer.isle.act <= 0.001, undefined, 5000);
    assert.ok(calls.includes('DELETE /api/v1/presence/island/device%3Apending%3Aabc'), `实际 ${calls}`);
  } finally {
    await ctx.close();
  }
});

test('岛上没东西可点（只是阈限态那句话）就不接鼠标，不平白挡住桌面', async () => {
  if (skipped) return;
  const { ctx, page, send } = await open();
  try {
    await send(frame({ lifecycle: 'liminal', liminal_activity: 'thinking', transition_seq: 1, last_transition: 'emerging' }));
    await until(page, () => window.lumivRenderer.isle.shown > 0.9, undefined, 8000);
    const box = await page.evaluate(() => {
      const r = document.querySelector('#island').getBoundingClientRect();
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    });
    await page.mouse.move(20, 600);
    await page.mouse.move(box.x, box.y);
    await page.waitForTimeout(200);
    assert.deepEqual(await page.evaluate(() => window.__shell.ignore), []);
  } finally {
    await ctx.close();
  }
});

// ── winsland 借来的几样 ─────────────────────────────────────────────────

const center = (page, sel) => page.evaluate((s) => {
  const r = document.querySelector(s).getBoundingClientRect();
  return { x: r.left + r.width / 2, y: r.top + r.height / 2, w: r.width, right: r.right };
}, sel);

test('它在说话：一排声波，悬停换成提示、点开能叫它停下；说完留一会儿再收', async () => {
  if (skipped) return;
  const { ctx, page, send, look, calls } = await open();
  try {
    await send({ ...frame(), speaking: true });
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    let v = await look();
    assert.equal(v.text, '在说话');
    assert.equal(v.wave, true, '在说话时岛上该有那排声波');
    assert.equal(v.tone, 'voice');
    assert.ok(v.petInIsland, '桌宠还坐在岛上');
    const bars = await page.evaluate(() => document.querySelectorAll('#islandWave i').length);
    assert.equal(bars, 5);

    const box = await center(page, '#island');
    await page.mouse.move(20, 600);
    await page.mouse.move(box.x, box.y);
    await until(page, () => document.querySelector('#island').dataset.hover === 'true');
    // 下一帧才重画（静着时 12fps）
    await until(page, () => document.querySelector('#islandWave').hidden);
    v = await look();
    assert.equal(v.wave, false, '悬停时声波换成一句提示');
    assert.equal(v.sub, '点一下可以叫它停下');

    await page.mouse.click(box.x, box.y);
    await until(page, () => window.lumivRenderer.isle.open >= 0.999);
    v = await look();
    assert.ok(v.buttons.includes('stop'), `说话时点开要有「停下」，实际 ${v.buttons}`);
    await page.click("button[data-act='stop']");
    await page.waitForTimeout(150);
    assert.ok(calls.includes('POST /api/v1/presence/stop'), `实际 ${calls}`);

    // 说完：先留一会儿（两句之间不闪），再收回去
    await page.mouse.move(20, 600);
    await send({ ...frame(), speaking: false });
    await page.waitForTimeout(400);
    assert.equal((await look()).text, '在说话', '刚说完就收，两句之间会闪');
    await until(page, () => window.lumivRenderer.isle.act <= 0.001, undefined, 6000);
  } finally {
    await ctx.close();
  }
});

test('药丸的排法：桌宠贴左端、字居中、声波贴右端；宽度跟着内容走；岛旁边没有另一座小岛', async () => {
  if (skipped) return;
  const { ctx, page, send } = await open();
  try {
    await send({ ...frame(), speaking: true });
    await until(page, () => window.lumivRenderer.isle.act >= 0.999 && !window.lumivRenderer.isle.moving());
    await page.waitForTimeout(100);
    const g = await page.evaluate(() => {
      const box = (s) => document.querySelector(s).getBoundingClientRect();
      const isl = box('#island');
      const pet = box('#pet');
      const text = box('#islandText');
      const wave = box('#islandWave');
      return { isl: { l: isl.left, r: isl.right, w: isl.width, c: isl.left + isl.width / 2 },
        petL: pet.left, textC: text.left + text.width / 2, waveR: wave.right,
        extra: document.querySelectorAll('#islandSenses, .sense').length };
    });
    assert.ok(g.petL - g.isl.l <= 14, `桌宠该贴着左端，离左沿 ${g.petL - g.isl.l}px`);
    assert.ok(g.isl.r - g.waveR <= 16, `声波该贴着右端，离右沿 ${g.isl.r - g.waveR}px`);
    assert.ok(Math.abs(g.textC - g.isl.c) <= 3, `字该在正中，偏了 ${g.textC - g.isl.c}px`);
    assert.ok(g.isl.w <= 250, `一句「在说话」岛就 ${g.isl.w}px 宽 —— 两边空着一大截，桌宠和字显得又小又挤`);
    assert.equal(g.extra, 0, '岛旁边不该再有一座放点的小岛');
  } finally {
    await ctx.close();
  }
});

test('「感知」那一页：每一路一行，点用面板那套光（白芯 / 半边 / 沉下去），不用颜色；能暂停感知', async () => {
  if (skipped) return;
  const { ctx, page, send, cards, calls } = await open();
  try {
    await send(frame({ perception: percept({ modalities: [
      { modality: 'screen', state: 'idle', signal_age_s: 3 },
      { modality: 'microphone', state: 'live', signal_age_s: 0.2 },
      { modality: 'camera', state: 'paused' },
    ] }) }));
    await cards([card({ action: 'panel' })]);
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    await page.evaluate(() => { window.lumivRenderer.isle.expanded = true; });
    await until(page, () => !document.querySelector('.isl-full').hidden);
    await page.evaluate(() => document.querySelector("button[data-act='view']").click());
    await until(page, () => document.querySelector('.isl-full').dataset.view === 'senses');
    await until(page, () => window.lumivRenderer.isle.open >= 0.999);
    const rows = await page.evaluate(() => [...document.querySelectorAll('#islandList .row')].map((r) => {
      const c = getComputedStyle(r.querySelector('i')).backgroundColor.match(/[\d.]+/g).map(Number);
      return { text: r.textContent, light: r.dataset.light, rgb: c.slice(0, 3) };
    }));
    assert.deepEqual(rows.map((r) => [r.text, r.light]), [
      ['屏幕 · 静了 3 秒', 'part'], ['麦克风 · 在收', 'on'], ['摄像头 · 你按了暂停', 'off']]);
    for (const r of rows) {
      const spread = Math.max(...r.rgb) - Math.min(...r.rgb);
      assert.ok(spread <= 12, `「${r.text}」那颗点带了颜色 rgb(${r.rgb})—— 面板说状态靠光和深度，不靠绿 / 橙 / 黄`);
    }
    const body = await page.evaluate(() => document.querySelector('#islandBody').textContent);
    assert.equal(body, '它此刻在收：麦克风');
    await page.evaluate(() => document.querySelector("button[data-act='pause']").click());
    await page.waitForTimeout(150);
    assert.ok(calls.includes('POST /api/perception/desktop/privacy/pause'), `实际 ${calls}`);
  } finally {
    await ctx.close();
  }
});

test('剪贴板一变：「已复制 · 图片」亮一下就走，不接鼠标', async () => {
  if (skipped) return;
  const { ctx, page, send, look } = await open();
  try {
    await send(frame());
    await page.evaluate(() => window.__shell.clip({ type: 'image' }));
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    const v = await look();
    assert.equal(v.text, '已复制');
    assert.equal(v.sub, '图片');
    assert.equal(v.tone, 'success');
    const box = await center(page, '#island');
    await page.mouse.move(20, 600);
    await page.mouse.move(box.x, box.y);
    await page.waitForTimeout(150);
    assert.deepEqual(await page.evaluate(() => window.__shell.ignore), [], '只是「已复制」不该挡住桌面');
    await until(page, () => window.lumivRenderer.isle.act <= 0.001, undefined, 6000);
  } finally {
    await ctx.close();
  }
});

test('点开之后换页：动态 ↔ 感知', async () => {
  if (skipped) return;
  const { ctx, page, send, cards } = await open();
  try {
    await send(frame());
    await cards([card({ action: 'panel', subtitle: '客厅平板' }), card({ id: 'c2', title: '第二张', action: 'panel' })]);
    await until(page, () => window.lumivRenderer.isle.act >= 0.999);
    await page.evaluate(() => { window.lumivRenderer.isle.expanded = true; });
    await until(page, () => !document.querySelector('.isl-full').hidden);
    const rows = () => page.evaluate(() => [...document.querySelectorAll('#islandList .row')].map((r) => r.textContent));
    assert.deepEqual(await rows(), ['第二张 · 第 3/10 步 · 刚点击']);
    assert.equal(await page.evaluate(() => document.querySelector("button[data-act='view']").textContent), '感知');

    await page.evaluate(() => document.querySelector("button[data-act='view']").click());
    await until(page, () => document.querySelector('.isl-full').dataset.view === 'senses');
    assert.deepEqual(await rows(), ['屏幕 · 在收']);
    assert.equal(await page.evaluate(() => document.querySelector("button[data-act='view']").textContent), '动态');

    await page.evaluate(() => document.querySelector("button[data-act='view']").click());
    await until(page, () => document.querySelector('.isl-full').dataset.view === 'activity');
    assert.deepEqual(await rows(), ['第二张 · 第 3/10 步 · 刚点击']);
  } finally {
    await ctx.close();
  }
});
