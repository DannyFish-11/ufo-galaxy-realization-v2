/**
 * presence_motion 的行为测试 —— 用 node 内置的 node:test 跑，零依赖。
 *
 *     node --test electron/renderer/
 *
 * 这里钉的都是**行为**，不是实现：
 *
 *   1. 拿不到 posture 时逐帧等于改造前的实现（用独立复刻的旧算法比对）；
 *   2. 塌缩倾向越大，上行穿越越快；回撤倾向对下行同理；
 *   3. 稳定度越低，弹簧越阻尼（振荡更小）；
 *   4. 目的地不受影响 —— 这件事改造前就是对的，不许改坏。
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const PM = require('./presence_motion.js');

// ---------------------------------------------------------------------------
// 旧实现的独立复刻。刻意从 git 历史里的 app.js._springUpdate 逐行抄来，
// 不 import 任何东西 —— 它的全部作用就是给"降级路径没变"当参照物。
// ---------------------------------------------------------------------------
function legacyAdvance(state, target, dt, intent) {
  const cur = state.depth;
  const gap = target - cur;
  const inBand = Math.max(cur, target) > 0.10 && Math.min(cur, target) < 0.90;
  if (inBand && Math.abs(gap) > 0.04) {
    const boost = 1.0 + intent * 0.8;
    const speed = (gap > 0 ? 0.34 : 0.55) * boost;
    const step = Math.sign(gap) * Math.min(Math.abs(gap), speed * dt);
    state.depth = Math.max(0, Math.min(1, cur + step));
    state.velocity = Math.sign(gap) * speed;
    return state;
  }
  const intentBoost = 1.0 + intent * 1.5;
  const tension = cur < target ? 50 * intentBoost : 70;
  const force = -tension * (cur - target);
  state.velocity += (force + -14 * state.velocity) * dt;
  state.depth = Math.max(0, Math.min(1, cur + state.velocity * dt));
  return state;
}

const DT = 1 / 30;

/** 跑 n 帧，返回整条轨迹。 */
function run(target, frames, signals, start) {
  const st = { depth: start === undefined ? 0.05 : start, velocity: 0 };
  const out = [];
  for (let i = 0; i < frames; i++) {
    PM.advance(st, target, DT, signals);
    out.push(st.depth);
  }
  return out;
}

/** 到达目标（±tol）所需帧数；没到返回 Infinity。 */
function framesToReach(traj, target, tol) {
  const t = tol === undefined ? 0.005 : tol;
  for (let i = 0; i < traj.length; i++) {
    if (Math.abs(traj[i] - target) < t) return i;
  }
  return Infinity;
}

// ---------------------------------------------------------------------------
// 1. 降级路径必须逐位一致
// ---------------------------------------------------------------------------

test('没有 posture 时，逐帧等于改造前的实现', () => {
  for (const intent of [0.0, 0.5, 1.0]) {
    for (const target of [0.05, 0.3065, 0.6072, 0.7287, 0.92]) {
      const mine = { depth: 0.05, velocity: 0 };
      const old = { depth: 0.05, velocity: 0 };
      for (let i = 0; i < 200; i++) {
        PM.advance(mine, target, DT, { intent: intent, posture: null });
        legacyAdvance(old, target, DT, intent);
        assert.strictEqual(
          mine.depth, old.depth,
          `intent=${intent} target=${target} 第 ${i} 帧出现分歧: ${mine.depth} vs ${old.depth}`
        );
      }
    }
  }
});

test('posture 里三个量取中性值时，同样等于改造前的实现', () => {
  // 这条防的是"只在 posture===null 时才降级"——真实的 anchor_only 姿态是
  // 一个**对象**，倾向为 0、稳定度为 1，也必须落回原行为。
  const neutral = { collapse_tendency: 0, retreat_tendency: 0, stability: 1 };
  const mine = { depth: 0.05, velocity: 0 };
  const old = { depth: 0.05, velocity: 0 };
  for (let i = 0; i < 200; i++) {
    PM.advance(mine, 0.62, DT, { intent: 0.5, posture: neutral });
    legacyAdvance(old, 0.62, DT, 0.5);
    assert.strictEqual(mine.depth, old.depth, `第 ${i} 帧出现分歧`);
  }
});

// ---------------------------------------------------------------------------
// 2. 倾向要影响【怎么过去】—— 这是整件事的核心
// ---------------------------------------------------------------------------

test('塌缩倾向越大，上行穿越越快（严格单调）', () => {
  const target = 0.62;
  const times = [0.0, 0.3, 0.6, 0.9].map((c) =>
    framesToReach(run(target, 300, {
      intent: 0.5,
      posture: { collapse_tendency: c, retreat_tendency: 0, stability: 1 },
    }), target)
  );
  for (let i = 1; i < times.length; i++) {
    assert.ok(
      times[i] < times[i - 1],
      `塌缩倾向增大没有让穿越更快：${JSON.stringify(times)}`
    );
  }
  // 不只是"快一点点"：改造前四档之间只差 2%，那等于没有信息。
  const gain = (times[0] - times[3]) / times[0];
  assert.ok(gain > 0.25, `倾向拉满只快了 ${(gain * 100).toFixed(1)}%，仍然读不出差别`);
});

test('回撤倾向越大，下行回落越快', () => {
  const target = 0.05;
  const times = [0.0, 0.5, 1.0].map((r) =>
    framesToReach(run(target, 300, {
      intent: 0.5,
      posture: { collapse_tendency: 0, retreat_tendency: r, stability: 1 },
    }, 0.92), target, 0.02)
  );
  for (let i = 1; i < times.length; i++) {
    assert.ok(times[i] < times[i - 1], `回撤倾向没有加快下行：${JSON.stringify(times)}`);
  }
});

test('倾向只作用于自己那个方向', () => {
  // 上行时回撤倾向不该提速，否则两个信号会互相串台。
  const target = 0.62;
  const a = framesToReach(run(target, 300, {
    intent: 0.5, posture: { collapse_tendency: 0, retreat_tendency: 0, stability: 1 },
  }), target);
  const b = framesToReach(run(target, 300, {
    intent: 0.5, posture: { collapse_tendency: 0, retreat_tendency: 0.9, stability: 1 },
  }), target);
  assert.strictEqual(a, b, '上行被回撤倾向影响了');
});

// ---------------------------------------------------------------------------
// 3. 目的地不许被改坏
// ---------------------------------------------------------------------------

test('无论倾向如何，最终都停在后端给的目标上', () => {
  for (const c of [0.0, 0.5, 1.0]) {
    for (const target of [0.05, 0.3065, 0.6072, 0.7287, 0.92]) {
      const traj = run(target, 600, {
        intent: 0.5,
        posture: { collapse_tendency: c, retreat_tendency: 0, stability: 1 },
      });
      assert.ok(
        Math.abs(traj[traj.length - 1] - target) < 0.002,
        `collapse=${c} target=${target} 最终停在 ${traj[traj.length - 1]}`
      );
    }
  }
});

test('深度恒在 [0,1] 内，倾向越界也不炸', () => {
  const traj = run(0.92, 300, {
    intent: 5,
    posture: { collapse_tendency: 99, retreat_tendency: -3, stability: NaN },
  });
  for (const d of traj) {
    assert.ok(d >= 0 && d <= 1 && Number.isFinite(d), `越界或非有限值: ${d}`);
  }
});

// ---------------------------------------------------------------------------
// 4. 稳定度 → 阻尼（契约里 stability 的注释写的就是这个用途）
// ---------------------------------------------------------------------------

test('稳定度低时弹簧更阻尼（过冲更小）', () => {
  // 从目标下方一小段起步（跨度 < 0.04 → 走弹簧分支，不走匀速带）。
  const target = 0.62;
  const overshoot = (stability) => {
    const st = { depth: 0.60, velocity: 0 };
    let peak = 0;
    for (let i = 0; i < 200; i++) {
      PM.advance(st, target, DT, {
        intent: 0.5,
        posture: { collapse_tendency: 0, retreat_tendency: 0, stability: stability },
      });
      peak = Math.max(peak, st.depth - target);
    }
    return peak;
  };
  const stable = overshoot(1.0);
  const shaky = overshoot(0.0);
  assert.ok(shaky < stable, `稳定度低时过冲反而更大：stable=${stable} shaky=${shaky}`);
});

test('自证：稳定度确实进了摩擦项', () => {
  // 防"两条轨迹碰巧都不过冲，上面那条恒真"式的假绿。
  assert.ok(PM.STABILITY_DAMP > 0, 'STABILITY_DAMP 为 0 的话稳定度根本没接上');
  assert.ok(PM.TENDENCY_BOOST > 0, 'TENDENCY_BOOST 为 0 的话倾向根本没接上');
});
