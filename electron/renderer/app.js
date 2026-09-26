/**
 * app.js —— 三态覆盖层的渲染端
 *
 * 一条编排，不是三个画面：
 *
 *   第一态  三条边（左·右·上）的氛围光，缓慢呼吸。底边没有。
 *   过渡    两臂同时上退 → 顶边从左往右收 → 灵动岛从上边框长出来；
 *           同时四条边一块儿向后延伸出空间（不是"推"、不是翻转，只长深度）。
 *   第二态  空间就是沙盒，推演与决策在里面发生。岛上放文字，空间本身不写字。
 *   第三态  空间收回，屏幕是干净的 —— 它在出字、出声、或动手。
 *           **它在动你的鼠标键盘时**，岛从上边框长出来说一句「正在操作」，
 *           以及（后端确实占到了叫停键的话）怎么叫停。
 *   收场    光从顶部中间铺回三条边 —— 不是把收回倒着放。
 *   急停    同一个收拢手势，但没有岛滑出，顶上只留一道贴边细线。
 *
 * 为什么整套换掉了 WebGL
 * ----------------------
 * 原来是一个 328 行的全屏片元着色器（shaders/lumiv.frag + webgl/context.js）。
 * 产品里带着一个把 GPU 整个关掉的开关（main.js 的 GALAXY_ELECTRON_GPU=0），
 * 而且它是因为真机反复崩溃才加的 —— 在那个模式下实测 1080p 每帧 **735ms（1.4fps）**，
 * 不是慢，是不能用；而全屏片元着色器的代价 ∝ 像素数 × 帧率、与画面复杂度无关，
 * 连只画一圈边缘光的静默态都要 82ms/帧。
 *
 * 顺带还量到那一版的两个洞：depth 0.30–0.42 **整段不画任何东西**（每次唤醒中间
 * 有 0.13~0.35 秒纯黑），以及 `u_intent` 声明了但着色器里一次都没读 ——
 * 每帧都在 setUniform，一个像素都没到达。
 *
 * 现在要画的东西本来全是形状，交给合成器（渐变 + 3D transform + 遮罩）。
 * **但软件合成下它并不天然便宜**：全屏的模糊层、带滤镜的 3D 面，每一帧都要在
 * CPU 上重新合成。实测 1080p、无 GPU 时第二态只有 3.3fps —— 主要花在一条一直
 * 在跑的边光呼吸动画（边光早就收回了，它还在合成）和四面墙上恒等的滤镜上。
 * 所以看不见的层打标记不画（index.html 的 data-rim / data-space），呼吸改由这里
 * 按帧给数，实算时不挂滤镜。
 *
 * 关于 mix-blend-mode
 * -------------------
 * 设计稿里四壁走的是 `screen`（光只加不减，桌面不会被盖住）。**真覆盖层里用不上**：
 * 窗口是透明的，桌面在窗口背后、不在同一个层叠上下文里，CSS 混合触不到 OS 合成
 * 那一层。所以这里是普通 alpha 合成，浅色壁纸上会比设计稿更"盖"一点 ——
 * 这是平台约束，不是可以靠改 CSS 绕过去的事，如实记在这儿。
 *
 * 读的是哪一份契约
 * ----------------
 * 整体编排跟**主轴** `render.lifecycle`（silent / liminal / manifest）——
 * core/phase_contract.py 写明它是"渲染端的首要依据"。
 * 转移看**驻留的** `render.transition_seq` + `render.last_transition`：序号变了
 * 就是发生过一次转移，不怕某一帧丢了、也不怕中途才连上。旧后端没有序号时退回
 * 一拍性的 `render.transition_kind`；副轴的驻留位 `render.is_returning` 再兜一层。
 * 第一态的浓度、眼睛、急停来自 `render.perception`（四模态五档 + privacy_paused）。
 * 岛上的字来自 `render.liminal_activity`、`render.hybrid_execution.mode` 与
 * `render.acting`（它此刻在不在动手）与 `render.stop_key`（按哪个键能停）。
 * 空间的可信度来自 `render.degraded` 与 `render.source`（判定与面板同一份）。
 *
 * 旧后端不发 `render` 时逐位退回读 `payload.phase`，覆盖层绝不因契约缺席而停摆。
 */

'use strict';

// ── 主轴 → 空间展开程度 ───────────────────────────────────────────────
//
// **不能拿 depth_factor 当展开度。** 那是一维遗留投影，三个锚点是
// static .05 / liminal .62 / manifest .92 —— 一路单调上升；而这套编排里
// manifest 恰恰是**空间收回去**的那一段（收干净了才真正动手）。
// 照着 depth 画，第三态会越张越大，跟它的语义正好相反。
const OPEN_BY_LIFECYCLE = {
  silent: 0,
  static: 0,     // 遗留 payload.phase 用的名字
  liminal: 1,
  manifest: 0,   // 收回就是执行的开场
};

// ── 编排分段（以展开度 open 为轴）──
//
// **grow 必须在 pull 走完之前就起来。** 两段首尾相接的话，边光退干净了、墙还没
// 长出来，屏幕会空一段 —— 那正是旧着色器 depth 0.30–0.42 全黑的同一个洞。
const SEG = {
  pull: [0.00, 0.46],   // 边光收回：前 62% 两臂上退，后 38% 顶边左→右
  grow: [0.08, 0.72],   // 四壁向后延伸
  isle: [0.46, 0.88],   // 灵动岛从上边框长出来
};

// ── 与空间编排无关的三段时长（秒）──
//
// 边光自己收回去：从亮着直接进表达期（比如静息里直接开口说话）时，边光没有跟着
// 空间收过，得自己收。走同一条路径（两臂上退 → 顶边左→右），用时与空间编排里
// 那一段相当。原先这里是一帧里直接从全亮切到全收。
const HIDE_SECONDS = 0.9;
// 光从顶部中间铺回三条边。原先是 spread += 0.85 * dt，约 1.18 秒，不改。
const SPREAD_SECONDS = 1 / 0.85;
// 动手期间那座岛自己长出来 / 收回去（表达期空间是收着的，岛不能跟着空间走）。
const ISLE_SECONDS = 0.45;

// ── 时间怎么走 ──
//
// 原先每帧最多只推进 0.05 秒：帧一慢，整段编排跟着变慢。软件合成下实测第二态
// 4–6fps，展开原本 1.7 秒，实际走了 5 秒以上 —— 回答都出来了，空间还没长完。
// 现在按墙钟走：一帧里过了多久就推进多久，拆成小步给弹簧（它需要小步长才稳），
// 只在间隔大到不正常（切走窗口、休眠）时封顶，免得回来时一步跳到头。
const STEP = 1 / 60;
const MAX_GAP = 0.25;

// 呼吸的起伏：与原先那条关键帧同一对数（.62 ↔ 1）。周期读 index.html 的 --c-rim。
const BREATH_LO = 0.62;
const BREATH_HI = 1.0;

// 阈限态越往后使劲，桌宠喘得越快。**这四个数就是面板那只桌宠的那四个数**
// （panel/src/ui/pet.ts 的 BREATH），一字不差 —— 两只是同一只东西，不能一只
// 喘 6 秒另一只喘 9 秒。判据钉在 tests/test_overlay_reads_the_two_axis_contract.py。
//
// 要躲开的那一带是 **0.17–0.25 Hz**，唯一权威在 panel/src/motion.ts 的
// AVOID_LO / AVOID_HI，**不在这段注释里**。这里原先写的是 0.18–0.22，
// 而 understanding 档原先取 4.3s = 0.233 Hz —— 按真带子它在里面，按注释
// 自己写的窄带子它在外面。这条弯路 motion.ts 的开头已经记过两回：
// line.ts 的 5.1s、pet.ts 的 5.2s，两回都是"判据写在注释里"。这是第三回，
// 而且是照着那份注释又走了一遍。所以数字不再自己定，照抄权威那一份。
//
//   none          9.0s = 0.111 Hz
//   understanding 6.5s = 0.154 Hz
//   thinking      3.6s = 0.278 Hz
//   rehearsing    2.6s = 0.385 Hz
//
// 0.17–0.25 Hz 对应 4.0–5.9 秒，这一整段不能用，四档必须从它上面跳到下面。
// 跳的那一步放在 understanding → thinking（"在读"到"在想"），因为那一步
// 本来就该是最明显的一档变化。
const PET_RATE = { none: '9s', understanding: '6.5s', thinking: '3.6s', rehearsing: '2.6s' };

// 上一拍的决策 → 演哪一种反应。**与面板那只同一张表**（panel/src/ui/pet.ts 的 POSE）。
// 四档各一种，少一种那一档就没演。
const POSE = { none: 'rest', speak: 'lean', silent: 'tuck', delegate: 'aside' };

//: 反应演多久（毫秒）。与面板那只一致。
const REACT_MS = 1600;

// ── 这一拍的姿态算不算数 ──
//
// 契约里 `degraded` 与 `source` 各说一件事：前者是"continuum 本拍跑在降级模式"
// （tick 超预算、内部错误，见 core/continuum/orchestrator.py），后者是"这份姿态
// 是实算的（continuum）还是按相位锚点兜的底（anchor_only）"。降级优先，因为它更重；
// 姿态还没来时也算兜底 —— 那时画的相位是初值，不是它的相位。
//
// **这段判定是从面板 main.ts 的 lineTrust() 一字不差搬过来的**，判据钉住两边不漂。
// 仓库的规矩是「降级必须留痕」，而此前覆盖层这两位一位都不读：后端跑在降级模式时，
// 屏幕上跟实算出来的一模一样 —— 那就是"看起来接上了，其实没有"。
function trustOf(render) {
  if (!render) return 'anchor';
  if (render.degraded) return 'degraded';
  return render.source === 'continuum' ? 'live' : 'anchor';
}

const ACTIVITY_WORD = {
  none: 'Galaxy', understanding: '正在理解', thinking: '正在规划', rehearsing: '正在推演',
};
const MODE_WORD = {
  none: '', sequential_degrade: '顺序降级', parallel_race: '并行竞速',
  staged_hybrid: '分段混合', local_preferred: '本机优先', remote_preferred: '云端优先',
};
// 它在动你的鼠标键盘时岛上那句话。
const ACTING_WORD = '正在操作';

// 五档模态状态 → 边光浓度。**取值与含义抄自 core/phase_contract.MODALITY_STATES
// 的注释**，那里逐档写明了该怎么画；这里不另立一套说法。
const SENSE_GLOW = { live: 1.0, idle: 0.58, suppressed: 0.22, paused: 0, unavailable: 0 };

function clamp01(v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
function seg(x, s) { return clamp01((x - SEG[s][0]) / (SEG[s][1] - SEG[s][0])); }
function sub(x, a, b) { return clamp01((x - a) / (b - a)); }
function ease(x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; }
// 延伸用先快后慢：三次 in-out 在开头几乎不动，那会把上面那个洞再挖一遍。
function easeOut(x) { return 1 - Math.pow(1 - x, 2.2); }

class GalaxyOverlay {
  constructor() {
    this.root = document.documentElement;
    this.island = document.getElementById('island');
    this.islandInner = this.island ? this.island.querySelector('.isl-in') : null;
    this.islandText = document.getElementById('islandText');
    this.islandMode = document.getElementById('islandMode');
    this.islandHint = document.getElementById('islandHint');
    this.pet = document.getElementById('pet');

    // 后端每一拍给的东西。拿不到就保持 null —— 绝不构造，也绝不假装知道。
    this.phase = 'static';
    this.intent = 0;
    this.posture = null;
    this.render = null;

    // 展开度的运动学状态，由 presence_motion 就地推进。
    this.open = 0;
    this.openV = 0;

    // 边光收回了多少：0 = 三条边全亮，1 = 全部收回。第二态里它跟着空间的编排走
    // （SEG.pull 那一段），表达期由它自己收完（HIDE_SECONDS）。
    this.hide = 0;

    // 铺回：光从顶部中间朝左右两边长开，再顺两边下来。铺完停在 1，边光全亮。
    this.spreading = false;
    this.spread = 0;

    // 动手期间那座岛的大小（与空间编排里长出来的那座取大）。
    this.isleAct = 0;
    // 岛展开到最大时多宽 —— 按岛上此刻那几个字量出来，不写死（见 _paintIsland）。
    this.isleMax = 248;

    // 边光的呼吸。周期读 index.html 的 --c-rim（判据在那边，这里不另写一份数）。
    this.breathT = 0;
    this.breathPeriod = 6;
    this.reducedMotion = false;

    // 转移：最近见过的驻留序号。null = 还没见过 —— 第一帧只记下，不补演。
    this._seenSeq = null;
    this._lastKind = 'none';
    this._lastReturning = false;
    this._lastAct = '';
    this._reactTimer = 0;
    this.lastFrame = 0;
  }

  init() {
    this._readRhythm();
    this._connectBackend();
    this._apply();
    requestAnimationFrame((t) => this._loop(t));
  }

  _readRhythm() {
    try {
      const v = parseFloat(getComputedStyle(this.root).getPropertyValue('--c-rim'));
      if (v > 0) this.breathPeriod = v;
    } catch (e) { /* 读不到就用兜底值 */ }
    try {
      const mq = window.matchMedia('(prefers-reduced-motion: reduce)');
      this.reducedMotion = !!mq.matches;
      if (mq.addEventListener) mq.addEventListener('change', (e) => { this.reducedMotion = !!e.matches; });
    } catch (e) { /* 没有 matchMedia 的环境：按不减动效处理 */ }
  }

  // ── 后端接线 ──

  _connectBackend() {
    if (window.galaxyAPI && window.galaxyAPI.onBackendState) {
      window.galaxyAPI.onBackendState((payload) => this._onStateEvent(payload));
      console.log('[Galaxy] IPC backend connected');
    } else {
      const gwPort = (typeof window !== 'undefined' && window.GALAXY_GATEWAY_PORT)
        || new URLSearchParams(location.search).get('gwport')
        || 9000;
      this._wsConnect(`ws://localhost:${gwPort}/ws/desktop-presence`);
    }
  }

  _wsConnect(url) {
    try {
      const ws = new WebSocket(url);
      ws.onopen = () => {
        console.log('[Galaxy] WebSocket connected');
        ws.send(JSON.stringify({ type: 'register', client: 'desktop-presence', version: '2.0.0' }));
      };
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'state_event' && msg.payload) this._onStateEvent(msg.payload);
        } catch (e) { /* 坏帧不该拖垮渲染循环 */ }
      };
      ws.onclose = () => setTimeout(() => this._wsConnect(url), 3000);
      ws.onerror = () => {};
    } catch (e) {
      console.error('[Galaxy] WebSocket failed:', e);
    }
  }

  _onStateEvent(payload) {
    if (payload.intent !== undefined) this.intent = payload.intent;
    if (payload.phase !== undefined) this.phase = payload.phase;
    if (payload.posture !== undefined) this.posture = payload.posture;
    if (payload.render !== undefined) this.render = payload.render;

    // ── 认转移 ──
    //
    // 第三态有两种收场，方向相反：
    //
    //   manifest → liminal  = handoff     做完接着下一轮
    //   manifest → silent   = dissolving  做完就散
    //
    // handoff 不需要在这儿做任何事：后端接着会报 lifecycle=liminal，展开度自己
    // 回到 1。dissolving 要把光从顶部中间铺回三条边 —— 岛把它还回去。
    //
    // 优先看**驻留的**序号：一拍性的 transition_kind 只在转移之后的第一份广播里有，
    // 覆盖层中途才连上、或那一份恰好丢了，这一拍就整个没了。序号每一份都带着。
    const r = this.render;
    if (r && typeof r.transition_seq === 'number') {
      if (this._seenSeq === null) {
        this._seenSeq = r.transition_seq;   // 中途连上：只记下，不补演
      } else if (r.transition_seq !== this._seenSeq) {
        this._seenSeq = r.transition_seq;
        this._onTransition(r.last_transition || 'none');
      }
    } else {
      // 旧后端没有序号：退回读一拍性的那一位。
      const kind = (r && r.transition_kind) || 'none';
      if (kind !== this._lastKind) {
        this._lastKind = kind;
        this._onTransition(kind);
      }
    }

    // ── 兜底：驻留位 `is_returning` ──
    //
    // 副轴的 `is_returning`（continuum_phase === 'receding'）整段返回弧里都为真。
    // 主轴 silent 之下，「刚做完正在消散」与「静息」只有这一位能分开。边沿触发 +
    // 只在边光确实收着、还没铺过时启动，所以不会把同一段消散演两遍。
    const returning = !!(r && r.is_returning);
    if (returning !== this._lastReturning) {
      if (returning && !this.spreading && this.spread <= 0.001 && this.hide > 0.001) {
        this.spreading = true;
        this.spread = 0;
      }
      this._lastReturning = returning;
    }
  }

  _onTransition(kind) {
    // 只有边光确实收着的时候才铺回 —— 它本来就亮着时从零再铺一遍，是一次凭空的闪烁。
    if (kind === 'dissolving') { if (this.hide > 0.001 && !this.spreading) { this.spreading = true; this.spread = 0; } }
  }

  // ── 边光：收回与铺回 ──
  //
  // 收回只有一条路径（两臂上退 → 顶边左→右），铺回只有一种样子（从顶部中间长开）。
  // 回来的时候**不把收回倒着放** —— 那是进场动画倒放，这套编排从一开始就不要它。
  _stepRim(dt) {
    const life = (this.render && this.render.lifecycle) || this.phase;
    const pull = ease(seg(this.open, 'pull'));

    // 表达期屏幕是干净的：边光不能跟着空间一起回来。
    //
    // 展开度在 silent 和 manifest 都是 0（一个还没展开、一个已经收回），单靠它
    // 分不出这两件事。而第一态那条光的含义是"在场但不表达"，manifest 恰恰是
    // "对外表达" —— 收完之后它正在出字、出声或点你的鼠标，这时候亮着那条光等于说反了。
    const hideTarget = (life === 'manifest') ? 1 : 0;
    const opening = OPEN_BY_LIFECYCLE[life] === 1;

    if (hideTarget > 0 || opening) {
      // 要收（或空间在展开）：已铺满的那一段放掉，交回给收回的遮罩。
      if (this.spreading || this.spread > 0) { this.spreading = false; this.spread = 0; }
      if (hideTarget > 0) {
        // 跟着空间收过的，从那儿接着收；从亮着直接进表达期的（静息里直接开口），自己收。
        this.hide = Math.min(1, Math.max(this.hide, pull) + dt / HIDE_SECONDS);
      } else {
        // 第二态：收回跟着空间的编排走。已经收着的（表达完接着下一轮）不先亮一下再收。
        this.hide = Math.max(pull, this.hide);
      }
    } else if (this.hide > 0.001) {
      if (this.hide < 0.25 && !this.spreading) {
        // 只收了一点点（刚进阈限就被叫停）：原路退回来就好，犯不着从零铺一遍。
        this.hide = Math.max(0, this.hide - dt / HIDE_SECONDS);
      } else {
        // 该亮了，而它还收着：从顶部中间铺回来。
        if (!this.spreading) { this.spreading = true; this.spread = 0; }
        this.hide = 0;
      }
    }

    if (this.spreading) {
      this.spread += dt / SPREAD_SECONDS;
      if (this.spread >= 1) { this.spread = 1; this.spreading = false; }
    }
  }

  // ── 岛：动手期间自己长出来 ──
  _stepIsle(dt) {
    const acting = !!(this.render && this.render.acting);
    const target = acting ? 1 : 0;
    const step = dt / ISLE_SECONDS;
    this.isleAct = target > this.isleAct
      ? Math.min(target, this.isleAct + step)
      : Math.max(target, this.isleAct - step);
  }

  // ── 运动学：只决定"怎么走"，不决定"走到哪儿" ──
  //
  // 落点由主轴给（OPEN_BY_LIFECYCLE），过程交给 presence_motion：编排带里匀速
  // 穿越（相位广播是事件驱动的离散跳变，纯弹簧约 100ms 就冲过整段，中间的动作在
  // 数学上看不见），带外走弹簧；倾向接进穿越速度、稳定度接进阻尼。
  //
  // 倾向按**要去哪一相**取（toward），不按往哪边走取：这条轴上 manifest 是 0，
  // 落手那一下是往下走 —— 按方向取就取成了回撤倾向。见 presence_motion.js 的 tendencyFor。
  _advance(dt) {
    const life = (this.render && this.render.lifecycle) || this.phase;
    const target = OPEN_BY_LIFECYCLE[life] !== undefined ? OPEN_BY_LIFECYCLE[life] : 0;

    if (typeof PresenceMotion === 'undefined') {
      this.open += (target - this.open) * Math.min(1, dt * 3);
      return;
    }
    const toward = target > this.open ? 'open' : (life === 'manifest' ? 'commit' : 'retreat');
    const st = { depth: this.open, velocity: this.openV };
    PresenceMotion.advance(st, target, dt, {
      intent: this.intent,
      posture: this.render || this.posture,
      toward: toward,
    });
    this.open = st.depth;
    this.openV = st.velocity;
  }

  _loop(now) {
    requestAnimationFrame((t) => this._loop(t));

    // 自适应帧率（无独显机器的省电闸）：静默且没有过渡 → 12fps，只够那口慢呼吸；
    // 过渡中或已展开 → 30fps。
    const life = (this.render && this.render.lifecycle) || this.phase;
    const moving = Math.abs(this.openV) > 0.0015
      || Math.abs(this.open - (OPEN_BY_LIFECYCLE[life] || 0)) > 0.01
      || this.spreading
      || (this.hide > 0.001 && this.hide < 0.999)
      || (this.isleAct > 0.001 && this.isleAct < 0.999);
    const minFrameMs = 1000 / (this.open > 0.02 || moving ? 30 : 12);
    if (now - this.lastFrame < minFrameMs) return;

    // 按墙钟推进 —— 见 STEP / MAX_GAP 那一段。
    const gap = Math.min((now - this.lastFrame) / 1000, MAX_GAP);
    this.lastFrame = now;
    for (let left = gap; left > 1e-6; left -= STEP) this._advance(Math.min(STEP, left));
    this._stepRim(gap);
    this._stepIsle(gap);
    this.breathT += gap;
    this._apply();
  }

  // ── 把状态写成 CSS 变量。样式全在 index.html，这里只给数。 ──
  _apply() {
    const s = this.root.style;
    const open = this.open;
    const grow = easeOut(seg(open, 'grow'));
    const isle = Math.max(ease(seg(open, 'isle')), ease(this.isleAct));

    const p = (this.render && this.render.perception) || null;
    const paused = !!(p && p.privacy_paused);

    // 收回 / 铺回：两条路各管各的，见 index.html 里那三条遮罩。
    const spreadShown = this.spreading || this.spread > 0.001;
    if (spreadShown) {
      s.setProperty('--my', '0%');
      s.setProperty('--mx', '0%');
      s.setProperty('--r', (this.spread * 260).toFixed(1) + '%');
    } else {
      s.setProperty('--my', (sub(this.hide, 0, 0.62) * 100).toFixed(2) + '%');
      s.setProperty('--mx', (sub(this.hide, 0.62, 1) * 109).toFixed(2) + '%');
      s.setProperty('--r', '260%');
    }

    // 四壁：只长深度，转角写死 90°。
    const H = window.innerHeight || 900;
    s.setProperty('--D', (grow * H * 1.12).toFixed(1) + 'px');
    // 透视跟着视口高一起给 —— 投影只看 D/perspective，写死 perspective 的话
    // 屏幕越高隧道越深、近端那条粉色越往里铺（实测 20.7% → 24.6% 屏宽）。
    // 1.1429 = 1.12 / 0.98，0.98 是设计稿上的 D/perspective（784 / 800）。
    s.setProperty('--persp', (H * 1.1429).toFixed(1) + 'px');
    s.setProperty('--wop', grow.toFixed(4));

    // ── 第一态的浓度：只调浓淡，不动几何 ──
    //
    // 感知帧 2 秒才一拍，而且绝大多数拍是"看到了不打扰"（ambient 循环的门控层
    // 直接免费跳过）。跟着数据跳就是一惊一乍 —— 那本身就是打扰。
    // 所以光自己缓慢呼吸，后端只给四档：亮着 / 闭着 / 压成线 / 不亮。
    const glow = paused ? 0 : this._senseGlow(p);
    s.setProperty('--rim', glow.toFixed(3));
    // 呼吸与浓度在 index.html 里相乘 —— 为什么不能写成 animation 见那边 .rim 的注释。
    const breath = this.reducedMotion
      ? 1
      : BREATH_LO + (BREATH_HI - BREATH_LO) * (0.5 - 0.5 * Math.cos((2 * Math.PI * this.breathT) / this.breathPeriod));
    s.setProperty('--breath', breath.toFixed(3));

    // 看不见的就别画（软件合成下这是主要开销，见 index.html）。
    this._flag('rim', glow > 0.001 && (spreadShown || this.hide < 0.999) ? 'on' : 'off');
    this._flag('space', grow > 0.001 ? 'on' : 'off');

    // ── 灵动岛：从上边框长出来。收到最小就是一道贴边细线。 ──
    //
    // **急停那道线就是岛本身**，不是另加一个元素：有线＝我在但我闭着，
    // 没线＝这台机器根本没有感知可用。契约把 privacy_paused 单独给一位，
    // 正是因为"用户按停了"是一个整体姿态，不是"恰好四条都闭着"。
    const h = paused ? 2 : 2 + isle * 31;
    const w = paused ? 68 : 66 + isle * (this.isleMax - 66);
    s.setProperty('--ih', h.toFixed(1) + 'px');
    s.setProperty('--iw', w.toFixed(1) + 'px');
    s.setProperty('--ir', (paused ? 2 : 2 + isle * 15).toFixed(1) + 'px');
    s.setProperty('--iop', paused ? '0.85' : (isle > 0.001 ? '1' : '0'));
    s.setProperty('--itx', Math.max(0, (isle - 0.55) / 0.45).toFixed(3));

    // ── 降级留痕：只落在**空间**上，不落在边光和桌宠上 ──
    //
    // 这两位说的是 continuum 那条链，而空间（四壁 + 远端那层霭）正是跟着它走的。
    // 边光和桌宠读的是 perception —— 那是另一条独立的只读拉取，continuum 降级
    // 跟"它此刻在不在看/在不在听"毫无关系。一并压暗等于替另一条链说了假话。
    const trust = trustOf(this.render);
    if (this.root.dataset.trust !== trust) this.root.dataset.trust = trust;

    this._paintIsland(paused);
    this._paintPet(p, paused);
  }

  _flag(name, value) {
    if (this.root.dataset[name] !== value) this.root.dataset[name] = value;
  }

  _senseGlow(p) {
    if (!p || p.source === 'unwired' || !Array.isArray(p.modalities)) return 0;
    let g = 0;
    for (const m of p.modalities) {
      const v = SENSE_GLOW[m && m.state];
      if (v !== undefined && v > g) g = v;
    }
    return g;
  }

  _paintIsland(paused) {
    if (paused) {
      this.islandMode.hidden = true;
      if (this.islandHint) this.islandHint.hidden = true;
      return;
    }
    const r = this.render || {};
    const acting = !!r.acting;
    const act = r.liminal_activity || 'none';
    const mode = (r.hybrid_execution && r.hybrid_execution.mode) || 'none';
    // 动手期间先说它在动手；否则说阈限态里它在干嘛。
    const word = acting ? ACTING_WORD : (ACTIVITY_WORD[act] || 'Galaxy');
    let changed = false;
    if (this.islandText.textContent !== word) { this.islandText.textContent = word; changed = true; }
    const m = MODE_WORD[mode] || '';
    if (this.islandMode.hidden !== !m) { this.islandMode.hidden = !m; changed = true; }
    if (m && this.islandMode.textContent !== m) { this.islandMode.textContent = m; changed = true; }
    // 怎么叫停：只照 `render.stop_key` 写 —— 后端的键盘监听确实占到了才有值
    // （core/stop_key.py）。不能从 acting 推出来：分不清人按的和它自己注入的键的
    // 平台上，动手期间也是空的。写着「Esc 停止」而按了没用，比不写更糟。
    if (this.islandHint) {
      const hint = acting && r.stop_key ? `${r.stop_key} 停止` : '';
      if (this.islandHint.hidden !== !hint) { this.islandHint.hidden = !hint; changed = true; }
      if (hint && this.islandHint.textContent !== hint) { this.islandHint.textContent = hint; changed = true; }
    }
    // 岛上的字变了，展开到最大时的宽度跟着量一次（字多了原来那 248px 装不下）。
    if (changed && this.islandInner) {
      const need = Math.ceil(this.islandInner.scrollWidth || 0) + 34;
      this.isleMax = Math.max(248, need);
    }
  }

  _paintPet(p, paused) {
    // 眼睛**三档，不是布尔**：还没收到过感知帧时既不能画成睁着（等于替后端说
    // "它正看着"），也不能画成闭着（等于说"已经停了"）。
    let eyes = 'unknown';
    if (paused) eyes = 'shut';
    else if (p && p.source !== 'unwired') eyes = 'open';
    if (this.pet.dataset.eyes !== eyes) this.pet.dataset.eyes = eyes;

    // 在收的时候眼睛睁得开一点。**不知道就不动它** —— 那不是"没在收"。
    // 与 data-eyes 分开两位：睁没睁是三档事实，收没收是另一件事，
    // 压成一位就会出现"没在收"被画成"闭着"。
    const sensing = (p && p.source !== 'unwired') ? String(!!p.is_sensing) : 'unknown';
    if (this.pet.dataset.sensing !== sensing) this.pet.dataset.sensing = sensing;

    // 主轴此刻在哪一相：静的时候小而沉，显形时立起来。与面板那只同一套。
    const life = (this.render && this.render.lifecycle) || this.phase;
    const ph = (life === 'liminal' || life === 'manifest') ? life : 'silent';
    if (this.pet.dataset.phase !== ph) this.pet.dataset.phase = ph;

    const act = (this.render && this.render.liminal_activity) || 'none';
    const rate = PET_RATE[act] || PET_RATE.none;
    if (this.pet.style.getPropertyValue('--pet-rate') !== rate) {
      this.pet.style.setProperty('--pet-rate', rate);
    }

    this._petReact(p);
  }

  // ── 上面叠一次性的反应：上一拍决定了什么 ──
  //
  // **不是常驻姿势。** `ambient_action` 是"上一拍" —— 一个已经发生完的事实。
  // 拿它当常驻姿势，它会一直卡在"忍住没说"那个样子不动，而下一次决策可能是
  // 几分钟以后，看着像死了。所以演一遍（REACT_MS）就撤回实时那一层。
  //
  // 而且它是**驻留位**：同一个决策会跟着之后每一帧一遍遍发回来。照帧演的话
  // 它每一帧抽一下 —— 既刺眼，又把"刚才"说成了"一直"。所以只在它变了时演。
  //
  // 这一整段是照着面板那只搬的（panel/src/ui/pet.ts 末尾那段），逐条对齐：
  // 同一张 POSE 表、同样只认变化、同样 1.6 秒撤回。两只桌宠读的是同一位数据，
  // 行为就不能是两样。
  _petReact(p) {
    const act = (p && p.source !== 'unwired') ? (p.ambient_action || 'none') : null;
    const key = act === null ? '' : act;
    if (key === this._lastAct) return;
    this._lastAct = key;

    if (this._reactTimer) { clearTimeout(this._reactTimer); this._reactTimer = 0; }
    if (act && act !== 'none') {
      this.pet.dataset.react = POSE[act] || 'rest';
      this._reactTimer = setTimeout(() => {
        delete this.pet.dataset.react;
        this._reactTimer = 0;
      }, REACT_MS);
    } else {
      delete this.pet.dataset.react;
    }
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('DOMContentLoaded', () => {
    window.lumivRenderer = new GalaxyOverlay();
    window.lumivRenderer.init();
  });
}
