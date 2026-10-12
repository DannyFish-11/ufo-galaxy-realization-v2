/**
 * panel_stage 的测试 —— node 内置 node:test，零依赖。
 *
 *     node --test electron/renderer/panel_stage.test.js
 *
 * 钉的是**面板是一整张画布、拖哪儿都等比**这几件事（见 panel_stage.js 文件头）。
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const PS = require('./panel_stage.js');

const WIDE = { width: 1920, height: 1040 };
const START = { x: 300, y: 200, width: 1200, height: 700 };
const near = (a, b, tol) => Math.abs(a - b) <= tol;

test('画布在窗口里等比放大缩小，宽高比锁着时正好铺满', () => {
  for (const k of [0.6, 0.75, 1, 1.3]) {
    const f = PS.fit({ width: PS.STAGE.width * k, height: PS.STAGE.height * k });
    assert.ok(near(f.k, k, 1e-9));
    assert.ok(near(f.dx, 0, 1e-9) && near(f.dy, 0, 1e-9));
  }
});

test('宽高比没对上时整张都还在窗口里（居中，不裁边）', () => {
  const f = PS.fit({ width: 900, height: 700 });
  assert.ok(PS.STAGE.width * f.k <= 900 + 1e-9 && PS.STAGE.height * f.k <= 700 + 1e-9);
  assert.ok(f.dy > 0 && near(f.dx, 0, 1e-9));
});

test('拖哪条边、哪个角，结果都是同一个宽高比', () => {
  const lim = PS.limits(WIDE);
  for (const edge of PS.EDGES) {
    for (const [dx, dy] of [[90, 40], [-150, -20], [10, 200], [-400, 300]]) {
      const b = PS.resizeBounds(START, edge, dx, dy, lim);
      assert.ok(near(b.width / b.height, PS.ratio(), 0.01), `${edge} ${dx},${dy} → ${b.width}x${b.height}`);
    }
  }
});

test('对面的边不动：拖右下角时左上角钉着，拖左上角时右下角钉着', () => {
  const lim = PS.limits(WIDE);
  const se = PS.resizeBounds(START, 'se', 120, 0, lim);
  assert.deepStrictEqual([se.x, se.y], [START.x, START.y]);
  assert.strictEqual(se.width, 1320);
  const nw = PS.resizeBounds(START, 'nw', -120, 0, lim);
  assert.strictEqual(nw.x + nw.width, START.x + START.width);
  assert.strictEqual(nw.y + nw.height, START.y + START.height);
});

test('拖上下边时按竖直方向算，左右居中地长', () => {
  const b = PS.resizeBounds(START, 's', 999, 70, PS.limits(WIDE));
  assert.strictEqual(b.height, 770);
  assert.strictEqual(b.y, START.y);
  assert.ok(near(b.x + b.width / 2, START.x + START.width / 2, 1));
});

test('有下限也有上限（工作区）', () => {
  const lim = PS.limits(WIDE);
  const tiny = PS.resizeBounds(START, 'se', -5000, -5000, lim);
  assert.strictEqual(tiny.width, Math.round(PS.STAGE.width * PS.MIN_SCALE));
  const huge = PS.resizeBounds(START, 'se', 5000, 5000, lim);
  assert.ok(huge.width <= WIDE.width && huge.height <= WIDE.height);
});

test('第一次打开：放得下就 1 倍，小屏缩到工作区里', () => {
  assert.deepStrictEqual(PS.initialSize(WIDE), { width: 1200, height: 700 });
  const small = PS.initialSize({ width: 1366, height: 728 });
  assert.ok(small.height <= 728 && small.width <= 1366);
  assert.ok(near(small.width / small.height, PS.ratio(), 0.01));
});
