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
 *   卡片    这台电脑上刚发生、人该余光知道的事（桌面操作走到第几步、核对的结论、有结果没收口、
 *           有设备在等你同意），任何一态里都会让岛长出来一会儿（借 WinIslands 的上岛推送：一张卡
 *           一个 id 原地更新、分先后、会过期、带进度、不改岛的长短）。点一下岛才展开：全文、
 *           队列里其余的卡、停下 / 打开面板 / 知道了。后端见 core/island_cards.py。
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
// 岛长成之后的尺寸（px）：一条**瘦长**的药丸，约 10:1（280 × 28）。
// 历史：248 × 33（7.5:1）→ 上一版 216 × 40（5.4:1，更窄更高）—— 那一版方向反了，
// 越改越像一块墩子；所有者要的是 Windows 灵动岛（wisland）那种又薄又长的一条。
// 宽度只是下限：文字多了（模式、叫停提示）会自己撑开，见 islandInner 的量法。
const ISLE_MIN_W = 280;
const ISLE_H = 26;   // 展开后高度 = 2 + ISLE_H
const ISLE_R = 14;   // 下沿圆角 = 2 + ISLE_R（略大于高度的一半，下沿圆润成药丸）
// 上限：卡片不改岛的长短（WinIslands 的规矩）—— 字再多，收起时也只到这么宽，放不下就截断；
// 点开之后也是这个宽，只往下长。
const ISLE_MAX_W = 440;
const ISLE_OPEN_R = 18;  // 点开之后的下沿圆角
// 指针离开点开的岛多久收回去（秒）。马上收的话，从岛上移去按钮时蹭出边一点就关了。
const ISLE_LINGER = 1.5;

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

// 桌宠此刻该是哪一档（相位、睁闭眼、在不在收、呼吸快慢、上一拍演哪种反应）：**三只桌宠共用的那一份**
// 推导在 pet_state.js（全局 PetState，index.html 里先于本文件加载）。以前这里抄了一份面板那边的表、
// 又自己写了一份推导 —— 两份在「进程里没有感知库」那一件事上讲岔了（这只眼睛虚着、面板那只睁着）。
// 呼吸四档要躲开的那一带（0.17–0.25 Hz）判据在 panel/src/motion.ts。

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
    this.islandDot = document.getElementById('islandDot');
    this.islandSub = document.getElementById('islandSub');
    this.islandMore = document.getElementById('islandMore');
    this.islandFull = this.island ? this.island.querySelector('.isl-full') : null;
    this.islandBody = document.getElementById('islandBody');
    this.islandList = document.getElementById('islandList');
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
    this.isleMax = ISLE_MIN_W;
    // 灵动岛上的卡（WS type="island"，core/island_cards.py）。各带一个本地到期时刻（秒，null = 不过期）：
    // 后端给的是「还剩几秒」，这里自己数，不跟后端对表。
    this.cards = [];
    // 点开了没有（人点的）、点开的程度（动画）、点开后下面那块多高（量出来的）。
    this.expanded = false;
    this.isleOpen = 0;
    this.fullH = 0;
    // 指针在不在岛上：在的时候窗口才接鼠标（覆盖层平时整个穿透，点到桌面上）。
    this.hover = false;
    this._collapseAt = 0;
    this._isleNow = 0;

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
    this._bindIsland();
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
    // 两条路，一主一备，到的是同一份帧：
    //
    //   * **WS（主）** /ws/desktop-presence —— 连上即推一份当前状态（快照），之后每一拍都到；
    //     保活、半开连接、断线重连交给与面板共用的那一份 live_socket.js。
    //   * **IPC（备）** 后端 POST 到 Electron 主进程、主进程转给这扇窗。它只在后端有事广播时才来：
    //     没有快照（覆盖层比后端先起来时，静息相位里可能很久都等不到第一帧）、断了也不知道；
    //     主进程那个端口被占（EADDRINUSE）时整条路是死的 —— 以前覆盖层只有这一条，于是会冻在
    //     启动时的样子一直不动。
    //
    // WS 连着时只认 WS：同一拍从两条路各到一次、先后不定，后到的那份旧帧会把画面拽回上一拍。
    const base = (window.galaxyShell && window.galaxyShell.base) || this._fallbackBase();
    this._base = base;   // 岛上「停下」「知道了」打 HTTP 用（令牌由外壳注入，见 electron/main.js）
    this._ws = new LiveSocket(base.replace(/^http/, 'ws') + '/ws/desktop-presence', {
      onOpen: () => console.log('[Galaxy] WebSocket connected'),
      onClose: () => {
        console.log('[Galaxy] WebSocket lost — reconnecting');
        // 断开时感知那一份是上一个进程的样子，不是现在的 —— 当成「还没收到」画（桌宠眼睛虚着）。
        // IPC 那条后备路要是还活着，它下一帧就会把感知带回来。
        if (this.render) this.render = Object.assign({}, this.render, { perception: null });
      },
      onMessage: (msg) => {
        if (msg && msg.type === 'state_event' && msg.payload) this._onStateEvent(msg.payload);
        else if (msg && msg.type === 'island' && msg.payload) this._onIsland(msg.payload);
      },
    });
    this._ws.start();
    if (window.galaxyAPI && window.galaxyAPI.onBackendState) {
      window.galaxyAPI.onBackendState((payload) => {
        if (this._ws && this._ws.connected) return;
        this._onStateEvent(payload);
      });
    }
  }

  // 浏览器里直接打开（没有 Electron 外壳给地址）时的兜底。用 127.0.0.1 而不是 localhost：
  // 网关只监听 IPv4，Windows 上 localhost 先解析到 ::1，连过去只会被拒（electron/main.js 同一条理由）。
  _fallbackBase() {
    const gwPort = (typeof window !== 'undefined' && window.GALAXY_GATEWAY_PORT)
      || new URLSearchParams(location.search).get('gwport')
      || 9000;
    return `http://127.0.0.1:${gwPort}`;
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

  // ── 灵动岛上的卡：每次有变化后端推整份（卡很少，整份比增量简单，也不怕丢一帧） ──
  _onIsland(payload) {
    const now = performance.now() / 1000;
    const list = Array.isArray(payload.cards) ? payload.cards : [];
    this.cards = list
      .filter((c) => c && typeof c.id === 'string' && typeof c.title === 'string' && c.title)
      .map((c) => Object.assign({}, c, {
        _until: typeof c.expires_in_s === 'number' ? now + c.expires_in_s : null,
      }));
    if (!this.cards.length) this.expanded = false;
  }

  // 过期的自己走（后端不必为一张卡到点再推一次）。
  _liveCards() {
    const now = performance.now() / 1000;
    if (this.cards.some((c) => c._until !== null && c._until <= now)) {
      this.cards = this.cards.filter((c) => c._until === null || c._until > now);
      if (!this.cards.length) this.expanded = false;
    }
    return this.cards;
  }

  // ── 岛接鼠标：只在指针停在岛上时 ──
  //
  // 覆盖层是全屏透明窗口，平时整个穿透（electron/main.js 的 setIgnoreMouseEvents(true, {forward:true})）。
  // forward 让鼠标移动照样送到这里：指针进了岛的范围就让窗口接鼠标，出去就交还桌面。点一下展开 / 收起；
  // 展开后指针离开 ISLE_LINGER 秒收回。岛没长出来时（静息、急停那道细线）一律不接。
  _bindIsland() {
    if (!this.island) return;
    document.addEventListener('mousemove', (e) => {
      // 岛上没东西可点（只是阈限态里那句「正在规划」）就不接 —— 平白挡住屏幕顶上那一小块桌面。
      const r = this.island.getBoundingClientRect();
      const something = this.cards.length > 0 || !!(this.render && this.render.acting);
      const inside = something && this._isleNow > 0.6
        && e.clientX >= r.left && e.clientX <= r.right && e.clientY >= r.top && e.clientY <= r.bottom;
      this._setHover(inside);
    });
    this.island.addEventListener('click', (e) => {
      const b = e.target && e.target.closest ? e.target.closest('button[data-act]') : null;
      if (b) { this._islandAct(b.dataset.act); return; }
      if (this.cards.length || (this.render && this.render.acting)) this.expanded = !this.expanded;
    });
  }

  _setHover(inside) {
    if (inside === this.hover) return;
    this.hover = inside;
    this.island.dataset.hover = String(inside);
    if (window.galaxyAPI && window.galaxyAPI.setIgnoreMouse) window.galaxyAPI.setIgnoreMouse(!inside);
    this._collapseAt = !inside && this.expanded ? performance.now() / 1000 + ISLE_LINGER : 0;
  }

  // 岛上那三个键。都不等回音：停没停、卡撤没撤，下一帧会照实画出来。
  _islandAct(act) {
    const top = this._liveCards()[0] || null;
    if (act === 'stop') {
      fetch(this._base + '/api/v1/presence/stop?reason=island', { method: 'POST' }).catch(() => {});
    } else if (act === 'panel') {
      if (window.galaxyAPI && window.galaxyAPI.openPanel) window.galaxyAPI.openPanel();
    } else if (act === 'dismiss' && top) {
      this.cards = this.cards.filter((c) => c.id !== top.id);
      fetch(this._base + '/api/v1/presence/island/' + encodeURIComponent(top.id), { method: 'DELETE' })
        .catch(() => {});
      if (!this.cards.length) this.expanded = false;
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

  // ── 岛：动手期间、岛上有卡的时候自己长出来；人点开时往下长 ──
  _stepIsle(dt) {
    const acting = !!(this.render && this.render.acting);
    const target = acting || this._liveCards().length ? 1 : 0;
    const step = dt / ISLE_SECONDS;
    this.isleAct = target > this.isleAct
      ? Math.min(target, this.isleAct + step)
      : Math.max(target, this.isleAct - step);
    if (this._collapseAt && performance.now() / 1000 >= this._collapseAt) {
      this._collapseAt = 0;
      if (!this.hover) this.expanded = false;
    }
    const openTarget = this.expanded ? 1 : 0;
    this.isleOpen = openTarget > this.isleOpen
      ? Math.min(openTarget, this.isleOpen + step)
      : Math.max(openTarget, this.isleOpen - step);
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
      || (this.isleAct > 0.001 && this.isleAct < 0.999)
      || (this.isleOpen > 0.001 && this.isleOpen < 0.999);
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
    // 点开：同一座岛往下长（宽到上限、下面长出 .isl-full 那么高），不是另弹一个窗。
    const full = paused ? 0 : ease(this.isleOpen) * isle;
    const h = paused ? 2 : 2 + isle * ISLE_H + full * this.fullH;
    const w = paused ? 68 : 66 + isle * (this.isleMax - 66) + full * Math.max(0, ISLE_MAX_W - this.isleMax);
    s.setProperty('--ih', h.toFixed(1) + 'px');
    s.setProperty('--iw', w.toFixed(1) + 'px');
    s.setProperty('--ir', (paused ? 2 : 2 + isle * ISLE_R + full * (ISLE_OPEN_R - ISLE_R)).toFixed(1) + 'px');
    s.setProperty('--iop', paused ? '0.85' : (isle > 0.001 ? '1' : '0'));
    s.setProperty('--itx', Math.max(0, (isle - 0.55) / 0.45).toFixed(3));
    s.setProperty('--ifx', Math.max(0, (full - 0.5) / 0.5).toFixed(3));
    this._isleNow = paused ? 0 : isle;
    // 岛收回去了（或按了急停）而指针还「在岛上」：把鼠标交还桌面，不然那一块会一直挡着点不下去。
    if (this.hover && this._isleNow <= 0.6) this._setHover(false);

    // ── 降级留痕：只落在**空间**上，不落在边光和桌宠上 ──
    //
    // 这两位说的是 continuum 那条链，而空间（四壁 + 远端那层霭）正是跟着它走的。
    // 边光和桌宠读的是 perception —— 那是另一条独立的只读拉取，continuum 降级
    // 跟"它此刻在不在看/在不在听"毫无关系。一并压暗等于替另一条链说了假话。
    const trust = trustOf(this.render);
    if (this.root.dataset.trust !== trust) this.root.dataset.trust = trust;

    this._paintIsland(paused);
    this._paintPet(p);
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
    const s = this.root.style;
    if (paused) {
      // 急停：岛就是那道细线，卡片不上（还在队列里，没过期的恢复后照常出来）。
      this.islandMode.hidden = true;
      if (this.islandHint) this.islandHint.hidden = true;
      this._show(this.islandSub, '');
      this._show(this.islandMore, '');
      if (this.islandDot) this.islandDot.hidden = true;
      s.setProperty('--ibar-on', '0');
      return;
    }
    const r = this.render || {};
    const acting = !!r.acting;
    const act = r.liminal_activity || 'none';
    const mode = (r.hybrid_execution && r.hybrid_execution.mode) || 'none';
    const cards = this._liveCards();
    const top = cards[0] || null;
    // 有卡先说卡（它是刚发生的事）；否则动手期间说它在动手，再否则说阈限态里它在干嘛。
    const word = top ? top.title : acting ? ACTING_WORD : (ACTIVITY_WORD[act] || 'Galaxy');
    let changed = false;
    if (this.islandText.textContent !== word) { this.islandText.textContent = word; changed = true; }
    changed = this._show(this.islandSub, top ? top.subtitle || '' : '') || changed;
    changed = this._show(this.islandMore, cards.length > 1 ? `+${cards.length - 1}` : '') || changed;
    if (this.islandDot && this.islandDot.hidden !== !top) { this.islandDot.hidden = !top; changed = true; }
    const tone = top ? top.tone || 'info' : '';
    if ((this.island.dataset.tone || '') !== tone) this.island.dataset.tone = tone;
    const m = top ? '' : MODE_WORD[mode] || '';
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
    // 进度：排第一的那张卡带着就画那道线（「第 3/15 步」）。
    const p = top && typeof top.progress === 'number' ? top.progress : null;
    s.setProperty('--ibar-on', p === null ? '0' : '1');
    if (p !== null) s.setProperty('--ibar', (p * 100).toFixed(1) + '%');
    // 岛上的字变了，收起时多宽跟着量一次 —— 但到 ISLE_MAX_W 为止，再多就截断（副标题那一段收窄）。
    if (changed && this.islandInner) this.isleMax = Math.min(ISLE_MAX_W, Math.max(ISLE_MIN_W, this._needWidth()));
    this._paintFull(cards, top, acting && !!r.stop_key, acting);
  }

  // 显示 / 藏一段字；返回变没变。
  _show(el, text) {
    if (!el) return false;
    let changed = false;
    if (el.hidden !== !text) { el.hidden = !text; changed = true; }
    if (text && el.textContent !== text) { el.textContent = text; changed = true; }
    return changed;
  }

  // 第一行要多宽：各段按**自己的**宽算（副标题能收窄，量整行会量成当前的宽、永远长不开），加上间距与两头留白。
  _needWidth() {
    let sum = 0;
    let n = 0;
    for (const el of this.islandInner.children) {
      if (el.hidden) continue;
      sum += el === this.islandSub ? el.scrollWidth : el.getBoundingClientRect().width;
      n += 1;
    }
    return Math.ceil(sum + Math.max(0, n - 1) * 9 + 34);
  }

  // 点开之后下面那块：排第一那张卡的全文、其余的卡、能按的键。没点开就不画（也不占高度）。
  _paintFull(cards, top, canStop, acting) {
    if (!this.islandFull) return;
    const open = this.expanded || this.isleOpen > 0.001;
    if (this.islandFull.hidden !== !open) this.islandFull.hidden = !open;
    if (!open) return;
    // 全文只放卡上的 body —— 没有就不写（不把上面那行副标题再抄一遍）；它在动手时说一句怎么让它住手。
    const body = top && top.body ? top.body : acting ? '它正在动你的鼠标键盘；按「停下」让它住手。' : '';
    if (this.islandBody.textContent !== body) this.islandBody.textContent = body;
    const rows = cards.slice(1).map((c) => {
      const row = document.createElement('div');
      row.className = 'row';
      row.dataset.tone = c.tone || 'info';
      const dot = document.createElement('i');
      const text = document.createElement('span');
      text.textContent = c.subtitle ? `${c.title} · ${c.subtitle}` : c.title;
      row.append(dot, text);
      return row;
    });
    const sig = cards.slice(1).map((c) => c.id + c.title + c.subtitle + c.tone).join('|');
    if (this.islandList.dataset.sig !== sig) {
      this.islandList.dataset.sig = sig;
      this.islandList.replaceChildren(...rows);
    }
    const btn = (act) => this.island.querySelector(`button[data-act='${act}']`);
    // 「停下」：它在动手（或这张卡就是它正在做的事）时才有。不要求叫停键 —— 这一下走的是 HTTP，不靠键盘监听。
    btn('stop').hidden = !(acting || canStop || (top && top.action === 'stop'));
    btn('panel').hidden = !cards.some((c) => c.action === 'panel');
    // 「知道了」撤的是排第一的那张；进行中的那张（桌面操作走到第几步）撤了下一步又会推上来，不给。
    btn('dismiss').hidden = !top || top.action === 'stop';
    const h = Math.ceil(this.islandFull.scrollHeight || 0);
    if (h > 0) this.fullH = h;
  }

  _paintPet(p) {
    // 推导用三只桌宠共用的那一份（pet_state.js）：同一份帧，面板、托盘那两只推出来的是同一档。
    const life = (this.render && this.render.lifecycle) || this.phase;
    const d = PetState.derive({
      lifecycle: life,
      liminal_activity: (this.render && this.render.liminal_activity) || 'none',
      perception: p,
    });
    // 眼睛**三档，不是布尔**：还没收到过感知帧时既不能画成睁着（等于替后端说
    // "它正看着"），也不能画成闭着（等于说"已经停了"）。
    if (this.pet.dataset.eyes !== d.eyes) this.pet.dataset.eyes = d.eyes;
    // 在收的时候眼睛睁得开一点。**不知道就不动它** —— 那不是"没在收"。
    if (this.pet.dataset.sensing !== d.sensing) this.pet.dataset.sensing = d.sensing;
    // 主轴此刻在哪一相：静的时候小而沉，显形时立起来。
    if (this.pet.dataset.phase !== d.phase) this.pet.dataset.phase = d.phase;
    if (this.pet.style.getPropertyValue('--pet-rate') !== d.rate) {
      this.pet.style.setProperty('--pet-rate', d.rate);
    }
    this._petReact(d.act);
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
  // 演哪一种、演多久都在 pet_state.js（三只桌宠同一张表）；这里只管「只认变化、演完就撤」。
  _petReact(act) {
    const key = act === null ? '' : act;
    if (key === this._lastAct) return;
    this._lastAct = key;

    if (this._reactTimer) { clearTimeout(this._reactTimer); this._reactTimer = 0; }
    const pose = PetState.reactionFor(act);
    if (pose) {
      this.pet.dataset.react = pose;
      this._reactTimer = setTimeout(() => {
        delete this.pet.dataset.react;
        this._reactTimer = 0;
      }, PetState.REACT_MS);
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
