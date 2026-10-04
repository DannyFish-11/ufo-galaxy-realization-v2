'use strict';
/**
 * 覆盖层的行为：喂它后端会发的帧，问浏览器屏幕上到底算出了什么。
 *
 * 钉的都是栽过的、而且读代码看不出来的：
 *   · 隐私急停之后边光必须真的熄了（曾经被关键帧里的 opacity 压住，照样亮着）；
 *   · 它在动你的键鼠时岛上说「正在操作」；「Esc 停止」只在后端确实占到了那个键时才写
 *     （写着能停而按了没用，比不写更糟）；
 *   · 做完就散，光从顶部铺回来 —— 即便一拍性的那一位丢了（丢一帧它就没了）。
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

async function open(over = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, ...over });
  const page = await ctx.newPage();
  await page.goto(fileUrl('index.html'));
  await page.waitForFunction(() => !!window.lumivRenderer);
  const send = (f) => page.evaluate((x) => window.lumivRenderer._onStateEvent(x), f);
  const look = () => page.evaluate(() => {
    const q = (s) => document.querySelector(s);
    return {
      rimFlag: document.documentElement.dataset.rim,
      spaceFlag: document.documentElement.dataset.space,
      rimOpacity: parseFloat(getComputedStyle(q('.rim:not(.core):not(.bloom)')).opacity),
      islandText: q('#islandText').textContent,
      hint: q('#islandHint').hidden ? null : q('#islandHint').textContent,
    };
  });
  return { ctx, page, send, look };
}

test('隐私急停：边光真的熄了，不只是变量写成了 0', async (t) => {
  if (skipped) return;
  const { ctx, page, send, look } = await open();
  try {
    await send(frame());
    await until(page, () => document.documentElement.dataset.rim === 'on');
    assert.ok((await look()).rimOpacity > 0.5, '亮着的时候应该是亮的');

    await send(frame({
      perception: percept({ privacy_paused: true, is_sensing: false,
        modalities: [{ modality: 'screen', state: 'paused', signal_age_s: null }] }),
    }));
    await until(page, () => document.documentElement.dataset.rim === 'off');
    const after = await look();
    assert.equal(after.rimOpacity, 0, '算出来的 opacity 必须是 0 —— 曾经被关键帧压住，照样一明一暗地亮着');
    assert.equal(after.spaceFlag, 'off', '看不见的墙不该还在合成');
  } finally {
    await ctx.close();
  }
});

test('边光的浓度跟着感知走：压下去就淡，亮着就浓', async (t) => {
  if (skipped) return;
  const { ctx, page, send, look } = await open();
  try {
    await send(frame({ perception: percept({ modalities: [{ modality: 'screen', state: 'suppressed' }] }) }));
    await until(page, () => document.documentElement.style.getPropertyValue('--rim') === '0.220');
    const dim = (await look()).rimOpacity;
    await send(frame({ perception: percept({ modalities: [{ modality: 'screen', state: 'live' }] }) }));
    await until(page, () => document.documentElement.style.getPropertyValue('--rim') === '1.000');
    const bright = (await look()).rimOpacity;
    assert.ok(dim <= 0.23, `压下去的那一档不该超过 0.22，实际 ${dim}`);
    assert.ok(bright >= 0.6, `亮着的那一档不该比呼吸谷底还暗，实际 ${bright}`);
  } finally {
    await ctx.close();
  }
});

test('动手时岛上说「正在操作」；「Esc 停止」只在后端占到了那个键时才写', async (t) => {
  if (skipped) return;
  const { ctx, page, send, look } = await open();
  try {
    await send(frame({ lifecycle: 'manifest', transition_seq: 1, last_transition: 'committing', acting: true, stop_key: '' }));
    await until(page, () => document.querySelector('#islandText').textContent === '正在操作');
    assert.equal((await look()).hint, null, '没占到键就不能写「Esc 停止」');

    await send(frame({ lifecycle: 'manifest', transition_seq: 1, last_transition: 'committing', acting: true, stop_key: 'Esc' }));
    await until(page, () => !document.querySelector('#islandHint').hidden);
    assert.equal((await look()).hint, 'Esc 停止');

    await send(frame({ lifecycle: 'manifest', transition_seq: 1, last_transition: 'committing', acting: false, stop_key: 'Esc' }));
    await until(page, () => document.querySelector('#islandHint').hidden);
    assert.notEqual((await look()).islandText, '正在操作', '没在动手就不能说在操作');
  } finally {
    await ctx.close();
  }
});

// 变异验证时发现：把「按序号认转移」整段关掉，这条照样过 —— 覆盖层自己的状态机在「静默、
// 而光还收着」时本来就会把光铺回来（_stepRim 那一支），与转移事件是两条互为冗余的路。所以这条
// 钉的是**看得见的结果**：一拍性的那一位丢了，光也照样回来。序号怎么认，由后端的性质测试
// （tests/test_lifecycle_properties.py）钉在发的那一头。
test('做完就散：光从顶部铺回来 —— 一拍性的那一位丢了也照样铺', async (t) => {
  if (skipped) return;
  const { ctx, page, send, look } = await open();
  try {
    await send(frame({ transition_seq: 5 }));
    await send(frame({ lifecycle: 'liminal', transition_seq: 6, last_transition: 'emerging', transition_kind: 'emerging' }));
    await send(frame({ lifecycle: 'manifest', transition_seq: 7, last_transition: 'committing', transition_kind: 'committing' }));
    // 等光**真的收完**，不能等 data-rim==='off'：覆盖层启动时（还没收到感知帧）本来就是 off，
    // 等那个标志会在光还没收回来时就放行 —— 而「本来亮着的光不会从零再铺」正是设计。
    await until(page, () => window.lumivRenderer.hide >= 0.999, undefined, 10000);
    assert.equal((await look()).rimFlag, 'off');

    // 做完就散。**一拍性的 transition_kind 在这一帧里丢了（none）**，只有驻留的序号变了。
    await send(frame({ lifecycle: 'silent', transition_seq: 8, last_transition: 'dissolving', transition_kind: 'none' }));
    await until(page, () => window.lumivRenderer.spreading === true || window.lumivRenderer.spread > 0);
    await until(page, () => document.documentElement.dataset.rim === 'on', undefined, 10000);
    assert.ok((await look()).rimOpacity > 0.5, '铺回来之后边光应该是亮的');
  } finally {
    await ctx.close();
  }
});

test('中途才连上：第一帧只记下序号，不补演一遍「做完就散」', async (t) => {
  if (skipped) return;
  const { ctx, page, send } = await open();
  try {
    await send(frame({ lifecycle: 'silent', transition_seq: 41, last_transition: 'dissolving' }));
    await page.waitForTimeout(300);
    const spread = await page.evaluate(() => window.lumivRenderer.spreading);
    assert.equal(spread, false, '本来就亮着的边光不该从零再铺一遍（那是一次凭空的闪烁）');
  } finally {
    await ctx.close();
  }
});

test('减少动效：呼吸停在定值，不再一明一暗', async (t) => {
  if (skipped) return;
  const { ctx, page, send } = await open({ reducedMotion: 'reduce' });
  try {
    await send(frame());
    await until(page, () => document.documentElement.dataset.rim === 'on');
    const samples = [];
    for (let i = 0; i < 6; i++) {
      samples.push(await page.evaluate(() => getComputedStyle(document.querySelector('.rim:not(.core):not(.bloom)')).opacity));
      await page.waitForTimeout(250);
    }
    assert.equal(new Set(samples).size, 1, `开了「减少动效」却还在变: ${samples}`);
  } finally {
    await ctx.close();
  }
});
