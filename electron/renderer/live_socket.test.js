/**
 * live_socket 的行为测试 —— node 内置 node:test，零依赖，假 WebSocket + 假时钟。
 *
 *     node --test electron/renderer/live_socket.test.js
 *
 * 钉的是**断了会自己回来、死了看得出来**这几件事（见 live_socket.js 文件头）。
 */
'use strict';

const test = require('node:test');
const assert = require('node:assert');
const LiveSocket = require('./live_socket.js');

/** 一个可以手动推进的时钟。 */
function clock() {
  let t = 0;
  let seq = 0;
  const timers = new Map();
  return {
    now: () => t,
    setTimeout(fn, ms) {
      const id = ++seq;
      timers.set(id, { at: t + ms, fn });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        let next = null;
        for (const [id, x] of timers) if (x.at <= end && (!next || x.at < next[1].at)) next = [id, x];
        if (!next) break;
        timers.delete(next[0]);
        t = next[1].at;
        next[1].fn();
      }
      t = end;
    },
  };
}

function fakeWS() {
  const made = [];
  class WS {
    constructor(url) {
      this.url = url;
      this.sent = [];
      this.closed = false;
      made.push(this);
    }
    send(x) {
      this.sent.push(x);
    }
    close() {
      this.closed = true;
    }
    // 测试驱动：
    open() {
      this.onopen && this.onopen();
    }
    recv(obj) {
      this.onmessage && this.onmessage({ data: typeof obj === 'string' ? obj : JSON.stringify(obj) });
    }
    drop() {
      this.onclose && this.onclose();
    }
  }
  return { WS, made };
}

function fakeWin() {
  const ls = {};
  return {
    addEventListener(k, f) { (ls[k] ||= []).push(f); },
    removeEventListener(k, f) { ls[k] = (ls[k] || []).filter((g) => g !== f); },
    fire(k) { for (const f of ls[k] || []) f(); },
    count(k) { return (ls[k] || []).length; },
  };
}

function make(opts = {}) {
  const c = clock();
  const { WS, made } = fakeWS();
  const win = fakeWin();
  const log = [];
  const s = new LiveSocket('ws://x/ws/desktop-presence', {
    onOpen: () => log.push('open'),
    onClose: () => log.push('close'),
    onMessage: (m) => log.push(m),
  }, { WebSocket: WS, setTimeout: c.setTimeout, clearTimeout: c.clearTimeout, now: c.now, random: () => 1, win, ...opts });
  return { s, c, made, win, log };
}

test('连上、收帧、保活的 pong 不往上报', () => {
  const { s, made, log } = make();
  s.start();
  assert.strictEqual(made.length, 1);
  made[0].open();
  made[0].recv({ type: 'state_event', payload: { a: 1 } });
  made[0].recv({ type: 'pong' });
  assert.deepStrictEqual(log, ['open', { type: 'state_event', payload: { a: 1 } }]);
  assert.strictEqual(s.connected, true);
});

test('定时发 ping；对方回 pong 就一直连着', () => {
  const { s, c, made } = make({ pingMs: 1000, staleMs: 2500 });
  s.start();
  made[0].open();
  for (let i = 0; i < 5; i++) {
    c.advance(1000);
    made[0].recv({ type: 'pong' });
  }
  assert.ok(made[0].sent.filter((x) => x === 'ping').length >= 5);
  assert.strictEqual(made.length, 1, '活着的连接不该被拆');
  assert.strictEqual(s.connected, true);
});

test('半开连接：一直没回音 → 不等 close 事件，当场拆掉重连', () => {
  const { s, c, made, log } = make({ pingMs: 1000, staleMs: 2500, baseDelayMs: 100 });
  s.start();
  made[0].open();
  c.advance(3500); // 三次 ping 都没回音
  assert.ok(made[0].closed, '死连接要被主动关掉');
  assert.deepStrictEqual(log, ['open', 'close']);
  c.advance(200);
  assert.strictEqual(made.length, 2, '拆掉之后要重连');
});

test('连接超时：一直不 open 就放弃这一次再连', () => {
  const { s, c, made, log } = make({ connectTimeoutMs: 1000, baseDelayMs: 100 });
  s.start();
  c.advance(1000);
  assert.ok(made[0].closed);
  assert.deepStrictEqual(log, [], '从没连上过，不该报 close');
  c.advance(200);
  assert.strictEqual(made.length, 2);
});

test('退避翻倍封顶；收到第一帧才清零（连上就被关不算通）', () => {
  const { s, c, made } = make({ baseDelayMs: 100, maxDelayMs: 800 });
  s.start();
  const waits = [];
  for (let i = 0; i < 6; i++) {
    const before = made.length;
    made[made.length - 1].open();
    made[made.length - 1].drop(); // 接下又立刻关
    let w = 0;
    while (made.length === before) { c.advance(10); w += 10; }
    waits.push(w);
  }
  assert.deepStrictEqual(waits, [100, 200, 400, 800, 800, 800]);
  // 这一次真的收到了帧 → 下一次断开从头退避
  made[made.length - 1].open();
  made[made.length - 1].recv({ type: 'state_event' });
  made[made.length - 1].drop();
  const before = made.length;
  let w = 0;
  while (made.length === before) { c.advance(10); w += 10; }
  assert.strictEqual(w, 100);
});

test('抖动：等待时间落在 [一半, 全额]', () => {
  const { s, c, made } = make({ baseDelayMs: 1000, random: () => 0 });
  s.start();
  made[0].drop();
  c.advance(499);
  assert.strictEqual(made.length, 1);
  c.advance(1);
  assert.strictEqual(made.length, 2);
});

test('网回来了：不等退避，立刻重连', () => {
  const { s, c, made, win } = make({ baseDelayMs: 5000 });
  s.start();
  made[0].drop();
  c.advance(100);
  assert.strictEqual(made.length, 1);
  win.fire('online');
  assert.strictEqual(made.length, 2);
});

test('窗口切回来时连着：探一下，没回音就当它死了', () => {
  const { s, c, made, win, log } = make({ probeMs: 1000, pingMs: 60000, staleMs: 120000 });
  s.start();
  made[0].open();
  made[0].recv({ type: 'state_event' });
  c.advance(10);
  win.fire('focus');
  assert.strictEqual(made[0].sent.at(-1), 'ping');
  c.advance(1000);
  assert.ok(made[0].closed);
  assert.deepStrictEqual(log.slice(-1), ['close']);
});

test('窗口切回来时连着且回了 pong：什么都不动', () => {
  const { s, c, made, win } = make({ probeMs: 1000, pingMs: 60000, staleMs: 120000 });
  s.start();
  made[0].open();
  c.advance(10);
  win.fire('focus');
  c.advance(100);
  made[0].recv({ type: 'pong' });
  c.advance(2000);
  assert.ok(!made[0].closed);
  assert.strictEqual(made.length, 1);
});

test('stop 之后不再重连，也不再听 online', () => {
  const { s, c, made, win } = make({ baseDelayMs: 100 });
  s.start();
  made[0].open();
  s.stop();
  assert.ok(made[0].closed);
  win.fire('online');
  c.advance(10000);
  assert.strictEqual(made.length, 1);
  assert.strictEqual(win.count('online'), 0);
});

test('不是 JSON 的帧丢掉，不往上报', () => {
  const { s, made, log } = make();
  s.start();
  made[0].open();
  made[0].recv('not json');
  assert.deepStrictEqual(log, ['open']);
});

test('挂在全局上 —— 覆盖层是 <script> 直接加载的，面板是打包后从全局取', () => {
  assert.strictEqual(globalThis.LiveSocket, LiveSocket);
});
