/**
 * pet_state 的行为测试 —— node 内置 node:test，零依赖。
 *
 *     node --test electron/renderer/pet_state.test.js
 *
 * 用例表 pet_state.cases.json 与 pytest 那边（windows_service/pet_icon.derive，托盘那只）共用：
 * 三只桌宠读同一份帧，就得推出同一个样子。
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const PS = require('./pet_state.js');
const table = require('./pet_state.cases.json');

for (const c of table.cases) {
  test(`推导：${c.name}`, () => {
    assert.deepStrictEqual(PS.derive(c.input), c.expect);
  });
}

for (const r of table.reactions) {
  test(`反应：${r.act} → ${r.expect}`, () => {
    assert.strictEqual(PS.reactionFor(r.act), r.expect);
  });
}

test('挂在全局上 —— 覆盖层是 <script> 直接加载的，面板是打包后从全局取', () => {
  assert.strictEqual(globalThis.PetState, PS);
});

test('呼吸表的每一档都能被推导到（推导只认表里的键）', () => {
  for (const k of Object.keys(PS.BREATH)) {
    assert.strictEqual(PS.derive({ lifecycle: 'liminal', liminal_activity: k, perception: null }).activity, k);
  }
});
