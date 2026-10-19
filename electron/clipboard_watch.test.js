'use strict';
/**
 * 剪贴板提示（clipboard_watch.js）：灵动岛「已复制」那一下从这里来。钉的是：
 *   · 开机时剪贴板里本来有的不算；之后文字变了、格式变了各报一次，没变不报；
 *   · 发出去的只有类别 —— 原文不出主进程（连摘要都不发）；
 *   · 别的程序占着剪贴板（读的时候抛错）不炸，下一拍照常。
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { watchClipboard, kindOf } = require('./clipboard_watch');

function rig(initial) {
  const board = { formats: initial.formats, text: initial.text || '', broken: false };
  const clipboard = {
    availableFormats() { if (board.broken) throw new Error('busy'); return board.formats; },
    readText() { return board.text; },
  };
  const sent = [];
  let tick = null;
  const stop = watchClipboard(clipboard, (m) => sent.push(m), {
    hash: (s) => `h(${s.length}:${s})`,
    every: (fn) => { tick = fn; return 1; },
    cancel: () => { tick = null; },
  });
  return { board, sent, step: () => tick && tick(), stop };
}

test('开机时本来有的不算；文字变了报一次，没变不报', () => {
  const r = rig({ formats: ['text/plain'], text: '旧的' });
  r.step();
  assert.deepEqual(r.sent, []);
  r.board.text = '新复制的一段';
  r.step();
  r.step();
  assert.deepEqual(r.sent, [{ type: 'text' }]);
});

test('格式变了也算：文字 → 图片 → 文件', () => {
  const r = rig({ formats: ['text/plain'], text: 'x' });
  r.board.formats = ['image/png'];
  r.step();
  r.board.formats = ['text/uri-list', 'text/plain'];
  r.step();
  assert.deepEqual(r.sent.map((m) => m.type), ['image', 'file']);
});

test('发出去的只有类别：原文、摘要都不出主进程', () => {
  const r = rig({ formats: ['text/plain'], text: '' });
  r.board.text = '我的密码是 hunter2';
  r.step();
  assert.equal(r.sent.length, 1);
  assert.deepEqual(Object.keys(r.sent[0]), ['type']);
  assert.ok(!JSON.stringify(r.sent).includes('hunter2'));
});

test('别的程序占着剪贴板：这一拍跳过，不炸，之后照常', () => {
  const r = rig({ formats: ['text/plain'], text: 'a' });
  r.board.broken = true;
  assert.doesNotThrow(() => r.step());
  r.board.broken = false;
  r.board.text = 'b';
  r.step();
  assert.deepEqual(r.sent, [{ type: 'text' }]);
});

test('停下之后不再看', () => {
  const r = rig({ formats: ['text/plain'], text: 'a' });
  r.stop();
  r.board.text = 'b';
  r.step();
  assert.deepEqual(r.sent, []);
});

test('类别判法与 island.js 认的四个一致', () => {
  assert.equal(kindOf(['image/jpeg']), 'image');
  assert.equal(kindOf(['FileNameW']), 'file');
  assert.equal(kindOf(['text/plain']), 'text');
  assert.equal(kindOf(['text/html']), 'generic');
  assert.equal(kindOf(undefined), 'generic');
});
