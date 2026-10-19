'use strict';
/**
 * island.js（IslandView）里不碰 DOM 的那一半：弹簧怎么动、什么时候该长出来、哪几颗点该亮。
 * 画出来什么样、点下去发什么请求，在 browser-tests/island.test.js 里问真浏览器。
 *
 * 钉的是 winsland 那组弹簧（stiffness 380 / damping 28）借过来之后的几条性质：
 *   · 长出来略过冲（几个百分点，不是来回晃），0.8 秒内停稳；
 *   · 收回去碰到上沿就停，不往边框里过冲；
 *   · 半路掉头接着当前位置走，不跳；
 *   · 帧率不同（60fps / 8fps）走的是同一条曲线；
 *   · 关了动效的人不过冲。
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const IslandView = require('./island.js');

const noDom = { getElementById: () => null };

function view(opts = {}) {
  let now = 0;
  const v = new IslandView(noDom, { clock: () => now, ...opts });
  v.tick = (seconds, render, fps = 60) => {
    const dt = 1 / fps;
    for (let t = 0; t < seconds - 1e-9; t += dt) {
      now += dt;
      v.step(dt, render);
    }
  };
  v.at = () => now;
  return v;
}

const quiet = { acting: false, perception: null };
const acting = { acting: true, perception: null };

function run(v, seconds, render, fps) {
  const trace = [];
  const dt = 1 / (fps || 60);
  for (let t = 0; t < seconds; t += dt) {
    v.tick(dt, render, fps || 60);
    trace.push(v.grow());
  }
  return trace;
}

test('长出来：略过冲（不到 8%），0.8 秒内停稳在 1', () => {
  const v = view();
  const trace = run(v, 0.8, acting);
  const peak = Math.max(...trace);
  assert.ok(peak > 1.01 && peak < 1.08, `过冲 ${peak}`);
  assert.equal(v.grow(), 1);
  assert.equal(v.moving(), false);
});

test('收回去：碰到上沿就停，不往边框里过冲', () => {
  const v = view();
  run(v, 0.6, acting);
  const trace = run(v, 0.6, quiet);
  assert.ok(Math.min(...trace) >= 0, '收回去不该小于 0');
  assert.equal(v.act, 0);
  assert.equal(v.moving(), false);
});

test('半路掉头：接着当前位置走，不跳', () => {
  const v = view();
  run(v, 0.08, acting);
  const before = v.grow();
  v.tick(1 / 60, quiet);
  assert.ok(Math.abs(v.grow() - before) < 0.08, `掉头那一帧跳了 ${before} → ${v.grow()}`);
});

test('帧率不同走的是同一条曲线（按墙钟积分）', () => {
  const fast = view();
  const slow = view();
  fast.tick(0.25, acting, 60);
  slow.tick(0.25, acting, 8);
  assert.ok(Math.abs(fast.grow() - slow.grow()) < 0.03, `${fast.grow()} vs ${slow.grow()}`);
});

test('关了动效的人：不过冲', () => {
  const v = view({ calm: true });
  const trace = run(v, 0.8, acting);
  assert.ok(Math.max(...trace) <= 1 + 1e-9, `过冲 ${Math.max(...trace)}`);
});

test('说完之后「在说话」再留一会儿（两句之间不闪），之后才收', () => {
  const v = view();
  v.setSpeaking(true);
  assert.equal(v.wanted(quiet), true);
  v.setSpeaking(false);
  v.tick(0.5, quiet);
  assert.equal(v.speakingShown(), true, '刚说完就收，两句之间会闪');
  v.tick(1.0, quiet);
  assert.equal(v.speakingShown(), false);
  assert.equal(v.wanted(quiet), false);
});

test('「已复制」亮 1.5 秒；认不得的类别算「内容」；它不让岛变成可点的', () => {
  const v = view();
  v.copiedNow('weird');
  assert.equal(v.copied.type, 'generic');
  assert.equal(v.wanted(quiet), true);
  assert.equal(v.clickable(quiet), false, '只是「已复制」就接鼠标，会平白挡住桌面');
  v.tick(1.6, quiet);
  assert.equal(v.copiedShown(), false);
});

test('「感知」那一页的点用面板那套光：在收 = 亮着，通着没信号 = 半边，暂停 / 没通路 = 沉下去', () => {
  const light = (state) => IslandView.senseLight({ modality: 'screen', state });
  assert.equal(light('live'), 'on');
  assert.equal(light('idle'), 'part');
  assert.equal(light('suppressed'), 'part');
  assert.equal(light('paused'), 'off');
  assert.equal(light('unavailable'), 'off');
  assert.equal(IslandView.senseLight(null), 'off');
});

test('卡片过期了自己走；没 id 没标题的不收', () => {
  const v = view();
  v.setCards({ cards: [
    { id: 'a', title: '一会儿就走', expires_in_s: 1 },
    { id: 'b', title: '一直在' },
    { id: 'c', title: '' },
    { title: '没有 id' },
  ] });
  assert.deepEqual(v.liveCards().map((c) => c.id), ['a', 'b']);
  v.tick(1.2, quiet);
  assert.deepEqual(v.liveCards().map((c) => c.id), ['b']);
});
