'use strict';
/**
 * island.js —— 覆盖层上那座灵动岛：岛上写什么、什么时候长出来、点了做什么。
 *
 * 对齐的是所有者指的 winsland（github.com/adityasrivastava5098/WinIsland，启动脚本就叫 winsland.bat）：
 * 一座贴着屏幕上沿的黑岛，平时收着，有事长成一条药丸，点一下往下长成一块。从它那里借的、在这里落成什么：
 *
 *   · 音乐药丸（封面 + 跟着封面取色的声波，悬停换成歌名，暂停后还留一会儿）
 *       → **它在说话时**：桌宠 +「在说话」+ 一排声波；悬停换成「点一下可以叫它停下」；说完留一会儿再收
 *         （两句之间不闪）。点开有「停下」（POST /api/v1/presence/stop，掐断在念的话）。
 *   · 隐私指示点（岛旁边两颗小黑圆，绿 = 有程序在用摄像头，橙 = 在用麦克风；点一下看是谁、用了多久）
 *       → **它自己此刻在收的感知**：摄像头 / 麦克风 / 屏幕 / 系统声各一颗，只在那一路真在收（live）时亮；
 *         点一下展开「感知」那一页：每一路什么状态、一个「暂停感知」。急停时一颗都没有（岛就是那道细线）。
 *   · 「已复制」小药丸（剪贴板一变就亮 1.5 秒：文字 / 图片 / 文件）→ 原样借来（主进程只看格式和摘要，
 *     内容不离开这台电脑，见 electron/main.js 的 watchClipboard）。
 *   · 弹簧式的伸缩（它用 stiffness 380 / damping 28）→ 同一组数：长出来略过冲约 4% 再落定，半路掉头接着当前
 *     速度走、不跳；收回去碰到上沿就停（不往边框里过冲）。关了动效的人用临界阻尼（不过冲）。
 *   · 贴边模式只在下沿发光、光的颜色跟着内容走 → 岛的下沿那一圈光跟着卡片语气 / 声波的颜色。
 *   · 点开后右上角切换页面（音乐 / 日历 / 隐私）→ 「动态」（卡片、在做什么）与「感知」两页。
 *   · 悬停才接鼠标、点外面收起 → 指针在岛上（或那几颗点上）时窗口才接鼠标，离开一会儿收回去。
 *
 * 没借的：日历（这边没有日历来源）、多显示器各一座岛（覆盖层是一整块全屏窗口，另是一件事）。
 * 桌宠还是那一只：它坐在岛的最左边，样子与推导都不归这里管（app.js 的 _paintPet / pet_state.js）。
 *
 * 卡片（core/island_cards.py，WS type="island"）的规矩照旧：一张卡一个 id 原地更新、分先后、会过期、不改岛的长短。
 *
 * 几何（多宽多高、圆角、跟着三态长出来的那一段）在 app.js 的 _apply 里算 —— 尺寸常量 ISLE_* 也在那边。
 * 这里只给两个量：grow()（岛因为「有事」该长出来多少）与 unfold()（人点开了多少），以及量出来的宽和高。
 */
(function (root) {
  var LINGER = 1.5;           // 指针离开点开的岛多久收回去
  var SPEAK_LINGER = 1.2;     // 说完之后「在说话」再留多久（两句之间不闪）
  var COPY_SECONDS = 1.5;     // 「已复制」停多久（winsland 同一个数）

  var COPY_WORD = { text: '文字', image: '图片', file: '文件', generic: '内容' };
  // 岛旁边那几颗点，按这个顺序排；颜色在 index.html（莫兰迪化的 iOS 惯例：绿摄像头、橙麦克风）
  var SENSES = ['camera', 'microphone', 'screen', 'system_audio'];
  var SENSE_LABEL = { screen: '屏幕', camera: '摄像头', microphone: '麦克风', system_audio: '系统声' };

  // winsland 的弹簧（Framer Motion：stiffness 380 / damping 28，质量 1）。阻尼比约 0.72：过冲约 4%，0.3 秒上下停稳。
  var STIFF = 380;
  var DAMP = 28;
  var DAMP_CALM = 2 * Math.sqrt(STIFF);   // 临界阻尼：不过冲（关了动效的人）
  var H = 1 / 240;                        // 积分步长：按墙钟推进，帧再慢也是同一条曲线

  /** 把 {x, v} 往 target 推 dt 秒。收回去（target 0）碰到上沿就停 —— 岛不往边框里过冲。 */
  function spring(s, target, dt, calm) {
    var c = calm ? DAMP_CALM : DAMP;
    for (var left = dt; left > 1e-6; left -= H) {
      var h = Math.min(H, left);
      s.v += (-STIFF * (s.x - target) - c * s.v) * h;
      s.x += s.v * h;
      if (target === 0 && s.x <= 0) { s.x = 0; s.v = 0; }
    }
    if (Math.abs(s.x - target) < 1e-4 && Math.abs(s.v) < 1e-3) { s.x = target; s.v = 0; }
  }

  /** 一路感知此刻怎么说。与面板「感知与设备」那一栏同一套说法（panel/src/ui/island.ts 的 modalityNote）。 */
  function senseNote(m) {
    switch (m && m.state) {
      case 'live': return '在收';
      case 'idle':
        return typeof m.signal_age_s === 'number' ? '静了 ' + Math.round(m.signal_age_s) + ' 秒' : '通着，还没来过信号';
      case 'suppressed': return '它在说话，这拍不听自己';
      case 'paused': return '你按了暂停';
      case 'unavailable': return '这台机器没有这条通路';
      default: return '';
    }
  }

  function IslandView(doc, opts) {
    opts = opts || {};
    this.doc = doc;
    this.el = doc.getElementById('island');
    this.inner = this.el ? this.el.querySelector('.isl-in') : null;
    this.text = doc.getElementById('islandText');
    this.mode = doc.getElementById('islandMode');
    this.hint = doc.getElementById('islandHint');
    this.dot = doc.getElementById('islandDot');
    this.sub = doc.getElementById('islandSub');
    this.more = doc.getElementById('islandMore');
    this.wave = doc.getElementById('islandWave');
    this.full = this.el ? this.el.querySelector('.isl-full') : null;
    this.body = doc.getElementById('islandBody');
    this.list = doc.getElementById('islandList');
    this.senses = doc.getElementById('islandSenses');
    this.words = opts.words || { acting: '正在操作', activity: {}, mode: {} };
    this.minW = opts.minW || 280;
    this.maxW = opts.maxW || 440;
    this.base = opts.base || '';
    this.clock = opts.clock || function () { return performance.now() / 1000; };

    this.cards = [];          // 各带一个本地到期时刻 _until（秒，null = 不过期）
    this.speaking = false;
    this._speakUntil = 0;
    this.copied = null;       // { type, until }
    this.expanded = false;    // 人点开了没有
    this.view = 'activity';   // 点开后看哪一页：activity（动态）/ senses（感知）
    this.act = 0;             // 「有事」长出来多少（弹簧的位置，长出来时会略过 1）
    this.open = 0;            // 点开了多少（同上）
    this._g = { x: 0, v: 0, to: 0 };
    this._o = { x: 0, v: 0, to: 0 };
    this.calm = !!opts.calm;  // 关了动效：临界阻尼（app.js 跟着 prefers-reduced-motion 改它）
    this.hover = false;
    this._collapseAt = 0;
    this.width = this.minW;   // 收起时一行字要多宽（量出来的，夹在 minW..maxW）
    this.fullH = 0;           // 点开后下面那块多高（量出来的）
    this.shown = 0;           // 此刻岛实际长出来多少（app.js 每帧告诉这里，用来判鼠标）
    this._render = null;
    this._paused = false;
    this._sensesSig = '';
    this._pt = null;          // 指针最后在哪儿（岛收回去时拿它判还在不在那几颗点上）
  }

  // ── 输入 ─────────────────────────────────────────────────────────────

  /** 灵动岛上的卡：每次有变化后端推整份。 */
  IslandView.prototype.setCards = function (payload) {
    var now = this.clock();
    var list = payload && Array.isArray(payload.cards) ? payload.cards : [];
    this.cards = list
      .filter(function (c) { return c && typeof c.id === 'string' && typeof c.title === 'string' && c.title; })
      .map(function (c) {
        return Object.assign({}, c, { _until: typeof c.expires_in_s === 'number' ? now + c.expires_in_s : null });
      });
  };

  /** 它在不在出声（state_event 的 payload.speaking，属主是 core.speech_output.set_ai_speaking）。 */
  IslandView.prototype.setSpeaking = function (on) {
    if (on) {
      this.speaking = true;
      this._speakUntil = 0;
    } else if (this.speaking) {
      this.speaking = false;
      this._speakUntil = this.clock() + SPEAK_LINGER;
    }
  };

  /** 剪贴板刚变过（主进程只告诉这里「是哪一类」）。 */
  IslandView.prototype.copiedNow = function (type) {
    this.copied = { type: COPY_WORD[type] ? type : 'generic', until: this.clock() + COPY_SECONDS };
  };

  // ── 此刻的几件事 ─────────────────────────────────────────────────────

  /** 过期的自己走（后端不必为一张卡到点再推一次）。 */
  IslandView.prototype.liveCards = function () {
    var now = this.clock();
    if (this.cards.some(function (c) { return c._until !== null && c._until <= now; })) {
      this.cards = this.cards.filter(function (c) { return c._until === null || c._until > now; });
    }
    return this.cards;
  };

  IslandView.prototype.speakingShown = function () {
    return this.speaking || this.clock() < this._speakUntil;
  };

  IslandView.prototype.copiedShown = function () {
    return !!(this.copied && this.copied.until > this.clock());
  };

  /** 此刻在收的那几路（只算真在收的 live；急停、没接上都一颗不亮）。 */
  IslandView.prototype.liveSenses = function (render) {
    var p = render && render.perception;
    if (!p || p.privacy_paused || p.source !== 'live' || !Array.isArray(p.modalities)) return [];
    var live = {};
    p.modalities.forEach(function (m) { if (m && m.state === 'live') live[m.modality] = true; });
    return SENSES.filter(function (s) { return live[s]; });
  };

  /** 岛上有没有能点的东西：有，指针停上来时窗口才接鼠标。只是阈限态那一句话不算（平白挡住屏幕顶上那一块桌面）。 */
  IslandView.prototype.clickable = function (render) {
    return this.liveCards().length > 0 || !!(render && render.acting) || this.speakingShown() || this.expanded;
  };

  /** 岛该不该因为「有事」长出来。 */
  IslandView.prototype.wanted = function (render) {
    return this.clickable(render) || this.copiedShown();
  };

  // ── 每一帧 ───────────────────────────────────────────────────────────

  IslandView.prototype.step = function (dt, render) {
    this._render = render;
    this._g.to = this.wanted(render) ? 1 : 0;
    spring(this._g, this._g.to, dt, this.calm);
    this.act = this._g.x;
    if (this._collapseAt && this.clock() >= this._collapseAt) {
      this._collapseAt = 0;
      if (!this.hover) this.expanded = false;
    }
    // 动态那一页上什么都没了（卡走完、话说完、手停了）就收回去；感知那一页是人自己点开要看的，留着
    if (this.expanded && this.view === 'activity' && !this.liveCards().length && !(render && render.acting) && !this.speakingShown()) {
      this.expanded = false;
    }
    this._o.to = this.expanded ? 1 : 0;
    spring(this._o, this._o.to, dt, this.calm);
    this.open = this._o.x;
  };

  /** 弹簧还没停稳（app.js 拿它决定帧率：动着 30fps，停稳了回到省电的那一档）。 */
  IslandView.prototype.moving = function () {
    var still = function (s) { return s.x === s.to && s.v === 0; };
    return !still(this._g) || !still(this._o);
  };

  /** 「有事」长出来多少（弹簧的位置）。 */
  IslandView.prototype.grow = function () { return Math.max(0, this.act); };

  /** 人点开了多少。 */
  IslandView.prototype.unfold = function () { return Math.max(0, this.open); };

  // ── 鼠标 ─────────────────────────────────────────────────────────────
  //
  // 覆盖层是全屏透明窗口，平时整个穿透（electron/main.js 的 setIgnoreMouseEvents(true, {forward:true})）。
  // forward 让鼠标移动照样送到这里：指针进了岛（或那几颗点）的范围就让窗口接鼠标，出去就交还桌面。

  IslandView.prototype.bind = function (win) {
    var self = this;
    if (!this.el) return;
    this.doc.addEventListener('mousemove', function (e) {
      self._pt = { clientX: e.clientX, clientY: e.clientY };
      var inIsland = self.shown > 0.6 && self.clickable(self._render) && inside(self.el, e);
      self._setHover(inIsland || self._onDots(e), win);
    });
    this.el.addEventListener('click', function (e) {
      var b = e.target && e.target.closest ? e.target.closest('button[data-act]') : null;
      if (b) { self.act_(b.dataset.act, win); return; }
      if (self.clickable(self._render)) self.expanded = !self.expanded;
    });
    if (this.senses) {
      this.senses.addEventListener('click', function () {
        self.view = 'senses';
        self.expanded = true;
      });
    }
  };

  IslandView.prototype._onDots = function (pt) {
    return !!(pt && this.senses && this.senses.childElementCount > 0 && inside(this.senses, pt));
  };

  function inside(el, e) {
    var r = el.getBoundingClientRect();
    return e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
  }

  IslandView.prototype._setHover = function (on, win) {
    if (on === this.hover) return;
    this.hover = on;
    this.el.dataset.hover = String(on);
    if (this.senses) this.senses.dataset.hover = String(on);
    var api = win && win.galaxyAPI;
    if (api && api.setIgnoreMouse) api.setIgnoreMouse(!on);
    this._collapseAt = !on && this.expanded ? this.clock() + LINGER : 0;
  };

  /** 岛收回去了（或按了急停）而指针还「在岛上」：把鼠标交还桌面，不然那一块会一直挡着点不下去。 */
  IslandView.prototype.releaseIfGone = function (win) {
    if (this.hover && this.shown <= 0.6 && !this._onDots(this._pt)) this._setHover(false, win);
  };

  /** 岛上那几个键。都不等回音：停没停、卡撤没撤、感知停没停，下一帧会照实画出来。 */
  IslandView.prototype.act_ = function (what, win) {
    var top = this.liveCards()[0] || null;
    var post = function (url, method) { return fetch(url, { method: method || 'POST' }).catch(function () {}); };
    if (what === 'stop') {
      post(this.base + '/api/v1/presence/stop?reason=island');
    } else if (what === 'panel') {
      if (win && win.galaxyAPI && win.galaxyAPI.openPanel) win.galaxyAPI.openPanel();
    } else if (what === 'dismiss' && top) {
      this.cards = this.cards.filter(function (c) { return c.id !== top.id; });
      post(this.base + '/api/v1/presence/island/' + encodeURIComponent(top.id), 'DELETE');
    } else if (what === 'view') {
      this.view = this.view === 'senses' ? 'activity' : 'senses';
    } else if (what === 'pause') {
      // 与面板那颗「暂停感知」同一个口（停止采集并清空缓存）；恢复在面板上（急停时岛就是一道线，不留可点的东西）
      post(this.base + '/api/perception/desktop/privacy/pause');
    }
  };

  // ── 画 ───────────────────────────────────────────────────────────────

  /**
   * 画岛上的字、声波、那几颗点、点开后的那一块。``shown`` 是 app.js 算出来的此刻岛实际长出来多少
   * （与三态里长出来的那一段取大）。返回这一行字要多宽（夹在 minW..maxW），app.js 拿它定岛的宽。
   */
  IslandView.prototype.paint = function (render, paused, shown, style) {
    this._render = render;
    this._paused = paused;
    this.shown = paused ? 0 : shown;
    this._paintSenses(render, paused, style);
    if (paused) {
      // 急停：岛就是那道细线，什么都不上（卡还在队列里，没过期的恢复后照常出来）
      this.mode.hidden = true;
      if (this.hint) this.hint.hidden = true;
      show(this.sub, '');
      show(this.more, '');
      if (this.wave) this.wave.hidden = true;
      if (this.dot) this.dot.hidden = true;
      style.setProperty('--ibar-on', '0');
      return this.width;
    }
    var r = render || {};
    var acting = !!r.acting;
    var cards = this.liveCards();
    var top = cards[0] || null;
    var copied = this.copiedShown();
    var speaking = this.speakingShown();
    // 先后：手正在动（或那张卡就是它在做的事）> 刚复制 > 卡 > 在说话 > 阈限态那一句
    var kind = top && (acting || !copied) ? 'card'
      : acting ? 'acting'
      : copied ? 'copied'
      : speaking ? 'speaking'
      : 'word';
    var word;
    var subText = '';
    var tone = '';
    if (kind === 'card') { word = top.title; subText = top.subtitle || ''; tone = top.tone || 'info'; }
    else if (kind === 'acting') { word = this.words.acting; }
    else if (kind === 'copied') { word = '已复制'; subText = COPY_WORD[this.copied.type]; tone = 'success'; }
    else if (kind === 'speaking') { word = '在说话'; subText = this.hover ? '点一下可以叫它停下' : ''; tone = 'voice'; }
    else { word = this.words.activity[r.liminal_activity || 'none'] || 'Galaxy'; }

    var changed = false;
    if (this.text.textContent !== word) { this.text.textContent = word; changed = true; }
    changed = show(this.sub, subText) || changed;
    changed = show(this.more, kind === 'card' && cards.length > 1 ? '+' + (cards.length - 1) : '') || changed;
    var dotOn = kind === 'card' || kind === 'copied';
    if (this.dot && this.dot.hidden !== !dotOn) { this.dot.hidden = !dotOn; changed = true; }
    // 声波：在说话、指针没停在上面（停上来就换成那句提示 —— winsland 悬停换歌名的同一个手势）
    var waveOn = kind === 'speaking' && !this.hover;
    if (this.wave && this.wave.hidden !== !waveOn) { this.wave.hidden = !waveOn; changed = true; }
    if ((this.el.dataset.tone || '') !== tone) this.el.dataset.tone = tone;
    var mode = (r.hybrid_execution && r.hybrid_execution.mode) || 'none';
    var m = kind === 'acting' || kind === 'word' ? this.words.mode[mode] || '' : '';
    if (this.mode.hidden !== !m) { this.mode.hidden = !m; changed = true; }
    if (m && this.mode.textContent !== m) { this.mode.textContent = m; changed = true; }
    // 怎么叫停：只照 render.stop_key 写 —— 后端的键盘监听确实占到了才有值（core/stop_key.py）。
    // 写着「Esc 停止」而按了没用，比不写更糟。
    if (this.hint) {
      var hint = acting && r.stop_key ? r.stop_key + ' 停止' : '';
      if (this.hint.hidden !== !hint) { this.hint.hidden = !hint; changed = true; }
      if (hint && this.hint.textContent !== hint) { this.hint.textContent = hint; changed = true; }
    }
    // 进度：排第一的那张卡带着就画那道线（「第 3/15 步」）
    var p = kind === 'card' && typeof top.progress === 'number' ? top.progress : null;
    style.setProperty('--ibar-on', p === null ? '0' : '1');
    if (p !== null) style.setProperty('--ibar', (p * 100).toFixed(1) + '%');
    // 字变了，收起时多宽跟着量一次 —— 到 maxW 为止，再多就截断（副标题那一段收窄）。卡片不改岛的长短。
    if (changed && this.inner) this.width = Math.min(this.maxW, Math.max(this.minW, this._needWidth()));
    this._paintFull(render, cards, top, acting, speaking);
    return this.width;
  };

  /** 第一行要多宽：各段按自己的宽算（副标题能收窄，量整行会量成当前的宽、永远长不开），加上间距与两头留白。 */
  IslandView.prototype._needWidth = function () {
    var sum = 0;
    var n = 0;
    var self = this;
    Array.prototype.forEach.call(this.inner.children, function (el) {
      if (el.hidden) return;
      sum += el === self.sub ? el.scrollWidth : el.getBoundingClientRect().width;
      n += 1;
    });
    return Math.ceil(sum + Math.max(0, n - 1) * 9 + 34);
  };

  /** 岛旁边那几颗点：只在那一路真在收时亮。岛收着时它们自己居中挂在上沿。 */
  IslandView.prototype._paintSenses = function (render, paused, style) {
    if (!this.senses) return;
    var live = paused ? [] : this.liveSenses(render);
    var sig = live.join(',');
    if (sig !== this._sensesSig) {
      this._sensesSig = sig;
      var doc = this.doc;
      this.senses.replaceChildren.apply(this.senses, live.map(function (s) {
        var b = doc.createElement('button');
        b.type = 'button';
        b.className = 'sense';
        b.dataset.sense = s;
        b.title = '它此刻在收' + SENSE_LABEL[s] + ' · 点一下看看';
        b.setAttribute('aria-label', '它此刻在收' + SENSE_LABEL[s]);
        b.appendChild(doc.createElement('i'));
        return b;
      }));
    }
    // 0 = 岛收着、点自己居中挂在上沿；1 = 岛长出来了、点挂在岛右边。中间跟着岛一起挪，不跳
    var beside = Math.min(1, Math.max(0, (this.shown - 0.05) / 0.3));
    style.setProperty('--isa', beside.toFixed(3));
  };

  /** 点开之后下面那块。两页：动态（卡片、在做什么）/ 感知（每一路什么状态）。没点开就不画、不占高度。 */
  IslandView.prototype._paintFull = function (render, cards, top, acting, speaking) {
    if (!this.full) return;
    var open = this.expanded || this.open > 0.001;
    if (this.full.hidden !== !open) this.full.hidden = !open;
    if (!open) return;
    var doc = this.doc;
    var senses = this.view === 'senses';
    this.full.dataset.view = this.view;
    var body;
    var rows;
    if (senses) {
      var p = render && render.perception;
      var mods = p && Array.isArray(p.modalities) ? p.modalities : [];
      var on = mods.filter(function (m) { return m.state === 'live'; }).map(function (m) { return SENSE_LABEL[m.modality] || m.modality; });
      body = !p ? '还没收到过感知帧 —— 它在不在看、在不在听，不知道'
        : p.source !== 'live' ? '感知这条链路还没接上'
        : on.length ? '它此刻在收：' + on.join('、')
        : '它此刻什么都没在收';
      rows = mods.map(function (m) {
        return { key: 'm:' + m.modality + m.state, tone: m.state === 'live' ? 'sense-' + m.modality : 'off',
          text: (SENSE_LABEL[m.modality] || m.modality) + ' · ' + senseNote(m) };
      });
    } else {
      // 全文只放卡上的 body —— 没有就不写（不把上面那行副标题再抄一遍）
      body = top && top.body ? top.body
        : acting ? '它正在动你的鼠标键盘；按「停下」让它住手。'
        : speaking ? '它正在说话；按「停下」让它别念了。'
        : '';
      rows = cards.slice(1).map(function (c) {
        return { key: c.id + c.title + c.subtitle + c.tone, tone: c.tone || 'info',
          text: c.subtitle ? c.title + ' · ' + c.subtitle : c.title };
      });
    }
    if (this.body.textContent !== body) this.body.textContent = body;
    var sig = this.view + '|' + rows.map(function (x) { return x.key; }).join('|');
    if (this.list.dataset.sig !== sig) {
      this.list.dataset.sig = sig;
      this.list.replaceChildren.apply(this.list, rows.map(function (x) {
        var row = doc.createElement('div');
        row.className = 'row';
        row.dataset.tone = x.tone;
        var span = doc.createElement('span');
        span.textContent = x.text;
        row.append(doc.createElement('i'), span);
        return row;
      }));
    }
    var btn = function (what) { return this.el.querySelector("button[data-act='" + what + "']"); }.bind(this);
    var paused = !!(render && render.perception && render.perception.privacy_paused);
    // 「停下」：它在动手、在说话（或这张卡就是它正在做的事）时才有。走的是 HTTP，不靠键盘监听
    btn('stop').hidden = senses || !(acting || speaking || (top && top.action === 'stop'));
    btn('panel').hidden = senses ? false : !cards.some(function (c) { return c.action === 'panel'; });
    // 「知道了」撤的是排第一的那张；进行中的那张（桌面操作走到第几步）撤了下一步又会推上来，不给
    btn('dismiss').hidden = senses || !top || top.action === 'stop';
    btn('pause').hidden = !senses || paused;
    var toggle = btn('view');
    var label = senses ? '动态' : '感知';
    if (toggle.textContent !== label) toggle.textContent = label;
    toggle.title = senses ? '看它在做什么' : '看它此刻在看什么、在听什么';
    var h = Math.ceil(this.full.scrollHeight || 0);
    if (h > 0) this.fullH = h;
  };

  /** 显示 / 藏一段字；返回变没变。 */
  function show(el, text) {
    if (!el) return false;
    var changed = false;
    if (el.hidden !== !text) { el.hidden = !text; changed = true; }
    if (text && el.textContent !== text) { el.textContent = text; changed = true; }
    return changed;
  }

  IslandView.SENSES = SENSES;
  IslandView.COPY_WORD = COPY_WORD;
  IslandView.senseNote = senseNote;
  root.IslandView = IslandView;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = IslandView;
  }
})(globalThis);
