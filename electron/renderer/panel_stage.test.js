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

// ── 窗口外形：画布的圆角矩形，由系统裁窗口（透明在那台机器上不生效也不露白） ──

/** 这一点在不在 rects 并起来的那块里。 */
const inside = (rects, x, y) => rects.some((r) => x >= r.x && x < r.x + r.width && y >= r.y && y < r.y + r.height);

test('外形就是画布那一块：画布外（比例没对上留出来的那条）不在窗口里', () => {
  const view = { width: 1200, height: 760 };
  const f = PS.fit(view);
  const rects = PS.shapeRects(view);
  assert.ok(f.dy > 0);
  assert.ok(!inside(rects, 600, 10), '上面那条空出来的不该是窗口的一部分');
  assert.ok(!inside(rects, 600, 750), '下面那条也不该');
  assert.ok(inside(rects, 600, 380) && inside(rects, 600, Math.ceil(f.dy)) && inside(rects, 2, 380));
});

test('四个角是圆的：角上那一点不在、往里一个半径就在', () => {
  for (const k of [0.6, 1, 1.4]) {
    const view = { width: Math.round(PS.STAGE.width * k), height: Math.round(PS.STAGE.height * k) };
    const rects = PS.shapeRects(view);
    const r = Math.round(PS.RADIUS * k);
    const W = view.width;
    const H = view.height;
    for (const [x, y] of [[0, 0], [W - 1, 0], [0, H - 1], [W - 1, H - 1]]) {
      assert.ok(!inside(rects, x, y), `k=${k} 角 ${x},${y} 还在窗口里 —— 方角`);
    }
    for (const [x, y] of [[r, r], [W - 1 - r, r], [r, H - 1 - r], [W - 1 - r, H - 1 - r]]) {
      assert.ok(inside(rects, x, y), `k=${k} 圆心 ${x},${y} 被裁掉了`);
    }
    // 边的中点贴边在内：只有角是圆的，四条边是直的、到头。
    assert.ok(inside(rects, Math.floor(W / 2), 0) && inside(rects, 0, Math.floor(H / 2)));
  }
});

test('像素中心在圆弧以内 EDGE_IN 才算在内（与页面的圆角同一条弧）', () => {
  const view = { width: PS.STAGE.width, height: PS.STAGE.height };
  const rects = PS.shapeRects(view);
  const r = PS.RADIUS;
  for (let y = 0; y < r; y++) {
    for (let x = 0; x < r; x++) {
      const d = Math.hypot(r - (x + 0.5), r - (y + 0.5));
      const edge = r - PS.EDGE_IN;
      if (Math.abs(d - edge) < 0.02) continue; // 正好压在线上的不判
      assert.strictEqual(inside(rects, x, y), d < edge, `${x},${y} 距圆心 ${d.toFixed(2)}`);
    }
  }
});

test('外形的矩形不重叠、不出窗口', () => {
  const view = { width: 1000, height: 640 };
  const rects = PS.shapeRects(view);
  let area = 0;
  for (const r of rects) {
    assert.ok(r.width > 0 && r.height > 0 && r.x >= 0 && r.y >= 0);
    assert.ok(r.x + r.width <= view.width && r.y + r.height <= view.height);
    area += r.width * r.height;
  }
  let count = 0;
  for (let y = 0; y < view.height; y++) for (let x = 0; x < view.width; x += 7) if (inside(rects, x, y)) count++;
  assert.ok(Math.abs(count * 7 - area) / area < 0.01, '有矩形叠在一起');
});
