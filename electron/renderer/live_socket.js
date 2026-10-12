/**
 * 面板与覆盖层共用的那条长连接（`/ws/desktop-presence`）—— **断了会自己回来，死了看得出来**。
 *
 * 以前两边各写一份，各有各的毛病：
 *
 *   * **半开连接认不出来。** 笔记本合盖再打开、后端被硬杀（进程没了但没发 FIN）、网卡切换 ——
 *     socket 在浏览器这边仍然是「开着的」，而且可以一直这样下去：不会有 close 事件，也就不会重连。
 *     静息相位里后端本来就很少说话，于是面板看着正常、实际早就聋了。
 *   * **连上就清零退避。** 后端接下连接又立刻关掉（还没起完、鉴权没过）时，每次都从 0.4 秒重来，
 *     一秒两三次地撞。
 *   * **连接本身可以挂很久。** SYN 被丢掉时浏览器要等很久才判失败，这段时间里什么也不做。
 *   * **网回来了、窗口切回来了，还在等退避。** 最长要多等 8 秒。
 *   * 覆盖层那份是固定 3 秒重试、没有保活。
 *
 * 现在一份，两边都用：
 *
 *   * **保活**：每 `pingMs` 发一个 "ping"（后端回 {"type":"pong"}，见 core/api_routes.py）；
 *     `staleMs` 内**什么都没收到**（含 pong）就认定它死了 —— 不等 close 事件，当场拆掉重连。
 *   * **连接超时**：`connectTimeoutMs` 内没 open 就放弃这一次。
 *   * **退避 + 抖动**：0.4s 起翻倍，封顶 `maxDelayMs`，乘 0.5–1 的随机数（几个窗口不会同一拍一起撞）。
 *     **收到第一帧才清零** —— 后端连上就推一份当前状态，收到它才说明这条路真的通了。
 *   * **网回来 / 窗口切回来**：没连着就立刻重连；连着就立刻探一下（合盖回来最常见的就是半开连接）。
 *
 * 覆盖层是无构建的原生 JS（<script> 直接加载），面板是 Vite 打包 —— 沿用 presence_motion.js 的写法：
 * 挂在全局上，node 测试另走 module.exports（live_socket.test.js，假 WebSocket + 假时钟）。
 */
(function (root) {
  'use strict';

  var DEFAULTS = {
    pingMs: 15000,
    staleMs: 40000,
    connectTimeoutMs: 8000,
    baseDelayMs: 400,
    maxDelayMs: 10000,
    // 窗口切回来 / 网回来时探一下：这么久没回音就当它死了。
    probeMs: 5000,
  };

  /**
   * @param {string} url
   * @param {{onOpen?:Function,onClose?:Function,onMessage?:Function}} handlers
   * @param {object} [options]  见 DEFAULTS；测试另可注入 WebSocket / setTimeout / clearTimeout / now / random / win
   */
  function LiveSocket(url, handlers, options) {
    var o = options || {};
    this._url = url;
    this._h = handlers || {};
    this._o = {};
    for (var k in DEFAULTS) this._o[k] = typeof o[k] === 'number' ? o[k] : DEFAULTS[k];
    this._WS = o.WebSocket || root.WebSocket;
    this._setTimeout = o.setTimeout || root.setTimeout.bind(root);
    this._clearTimeout = o.clearTimeout || root.clearTimeout.bind(root);
    this._now = o.now || function () { return Date.now(); };
    this._random = o.random || Math.random;
    this._win = o.win !== undefined ? o.win : (typeof root.addEventListener === 'function' ? root : null);

    this._sock = null;
    this._open = false;
    this._stopped = true;
    this._retry = 0;
    this._lastSeen = 0;
    this._retryTimer = 0;
    this._connectTimer = 0;
    this._pingTimer = 0;
    this._probeTimer = 0;

    var self = this;
    this._onOnline = function () { self.kick(); };
    this._onVisible = function () {
      var doc = root.document;
      if (!doc || doc.visibilityState === 'visible') self.kick();
    };
  }

  Object.defineProperty(LiveSocket.prototype, 'connected', {
    get: function () { return this._open; },
  });

  LiveSocket.prototype.start = function () {
    if (!this._stopped) return;
    this._stopped = false;
    if (this._win) {
      this._win.addEventListener('online', this._onOnline);
      if (root.document && typeof root.document.addEventListener === 'function') {
        root.document.addEventListener('visibilitychange', this._onVisible);
      } else {
        this._win.addEventListener('focus', this._onVisible);
      }
    }
    this._connect();
  };

  LiveSocket.prototype.stop = function () {
    this._stopped = true;
    if (this._win) {
      this._win.removeEventListener('online', this._onOnline);
      this._win.removeEventListener('focus', this._onVisible);
      if (root.document && typeof root.document.removeEventListener === 'function') {
        root.document.removeEventListener('visibilitychange', this._onVisible);
      }
    }
    this._clearTimeout(this._retryTimer);
    this._teardown();
  };

  /** 没连着就立刻重连（不等退避）；连着就探一下，`probeMs` 内没回音就当它死了。 */
  LiveSocket.prototype.kick = function () {
    if (this._stopped) return;
    if (!this._sock) {
      this._clearTimeout(this._retryTimer);
      this._retryTimer = 0;
      this._retry = 0;
      this._connect();
      return;
    }
    if (!this._open) return; // 正在连 —— 连接超时那一道会管
    var self = this;
    var asked = this._now();
    this._send('ping');
    this._clearTimeout(this._probeTimer);
    this._probeTimer = this._setTimeout(function () {
      self._probeTimer = 0;
      if (self._lastSeen < asked) self._dead();
    }, this._o.probeMs);
  };

  LiveSocket.prototype._connect = function () {
    if (this._stopped || this._sock) return;
    var self = this;
    var sock;
    try {
      sock = new this._WS(this._url);
    } catch (e) {
      this._schedule();
      return;
    }
    this._sock = sock;
    this._connectTimer = this._setTimeout(function () {
      self._connectTimer = 0;
      if (self._sock === sock && !self._open) self._dead();
    }, this._o.connectTimeoutMs);

    sock.onopen = function () {
      if (self._sock !== sock) return;
      self._clearTimeout(self._connectTimer);
      self._connectTimer = 0;
      self._open = true;
      self._lastSeen = self._now();
      self._heartbeat();
      if (self._h.onOpen) self._h.onOpen();
    };
    sock.onmessage = function (ev) {
      if (self._sock !== sock) return;
      self._lastSeen = self._now();
      // 收到第一帧才算真的通了，退避这时才清零。
      self._retry = 0;
      var msg;
      try {
        msg = JSON.parse(String(ev.data));
      } catch (e) {
        return; // 不是 JSON —— 丢掉，不猜
      }
      if (msg && msg.type === 'pong') return;
      if (self._h.onMessage) self._h.onMessage(msg);
    };
    sock.onclose = function () {
      if (self._sock !== sock) return;
      self._dead();
    };
    sock.onerror = function () {
      // 浏览器在 error 之后一定会给 close；这里不重复处理，等 close。
      // 但连接阶段的 error 有的实现不跟 close —— 连接超时那一道兜着。
    };
  };

  LiveSocket.prototype._heartbeat = function () {
    var self = this;
    this._clearTimeout(this._pingTimer);
    this._pingTimer = this._setTimeout(function () {
      self._pingTimer = 0;
      if (!self._open) return;
      if (self._now() - self._lastSeen > self._o.staleMs) {
        self._dead();
        return;
      }
      self._send('ping');
      self._heartbeat();
    }, this._o.pingMs);
  };

  LiveSocket.prototype._send = function (text) {
    try {
      if (this._sock && this._open) this._sock.send(text);
    } catch (e) {
      /* 发不出去 —— 下一拍的超时判据会认出它死了 */
    }
  };

  /** 认定这一条死了：拆掉（不等 close 事件），说一声，排下一次。 */
  LiveSocket.prototype._dead = function () {
    var was = this._open;
    this._teardown();
    if (was && this._h.onClose) this._h.onClose();
    this._schedule();
  };

  LiveSocket.prototype._teardown = function () {
    var sock = this._sock;
    this._sock = null;
    this._open = false;
    this._clearTimeout(this._connectTimer);
    this._clearTimeout(this._pingTimer);
    this._clearTimeout(this._probeTimer);
    this._connectTimer = this._pingTimer = this._probeTimer = 0;
    if (!sock) return;
    sock.onopen = sock.onmessage = sock.onclose = sock.onerror = null;
    try { sock.close(); } catch (e) { /* 已经关了 */ }
  };

  LiveSocket.prototype._schedule = function () {
    if (this._stopped) return;
    var self = this;
    var cap = Math.min(this._o.maxDelayMs, this._o.baseDelayMs * Math.pow(2, this._retry));
    var wait = Math.round(cap * (0.5 + 0.5 * this._random()));
    this._retry = Math.min(this._retry + 1, 30);
    this._clearTimeout(this._retryTimer);
    this._retryTimer = this._setTimeout(function () {
      self._retryTimer = 0;
      self._connect();
    }, wait);
  };

  LiveSocket.DEFAULTS = DEFAULTS;
  root.LiveSocket = LiveSocket;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = LiveSocket;
  }
})(globalThis);
