/**
 * app.js —— 三态覆盖层的渲染端
 *
 * 一条编排，不是三个画面：
 *
 *   第一态  三条边（左·右·上）的氛围光，缓慢呼吸。底边没有。
 *   过渡    两臂同时上退 → 顶边从左往右收 → 灵动岛从上边框长出来；
 *           同时四条边一块儿向后延伸出空间（不是"推"、不是翻转，只长深度）。
 *   第二态  空间就是沙盒，推演与决策在里面发生。岛上放文字，空间本身不写字。
 *   第三态  **两种，方向相反**（见下面 TRANSITION_KIND 那一段）。
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
 * 现在要画的东西本来全是形状，交给合成器（渐变 + 3D transform + 遮罩）：
 * 有 GPU 走 GPU，没有就走软件光栅，两条路都便宜；箱体透视是浏览器原生能力。
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
 * 退场看 `render.transition_kind`，不看深度往哪边走（理由见下）。
 * 第一态的浓度、眼睛、急停来自 `render.perception`（四模态五档 + privacy_paused）。
 * 岛上的字来自 `render.liminal_activity` 与 `render.hybrid_execution.mode`。
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

// 阈限态越往后使劲，桌宠喘得越快。四档都刻意避开 0.18–0.22 Hz 那一带。
const PET_RATE = { none: '6s', understanding: '4.3s', thinking: '3.5s', rehearsing: '2.9s' };

const ACTIVITY_WORD = {
  none: 'Galaxy', understanding: '正在理解', thinking: '正在规划', rehearsing: '正在推演',
};
const MODE_WORD = {
  none: '', sequential_degrade: '顺序降级', parallel_race: '并行竞速',
  staged_hybrid: '分段混合', local_preferred: '本机优先', remote_preferred: '云端优先',
};

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
    this.islandText = document.getElementById('islandText');
    this.islandMode = document.getElementById('islandMode');
    this.pet = document.getElementById('pet');

    // 后端每一拍给的东西。拿不到就保持 null —— 绝不构造，也绝不假装知道。
    this.phase = 'static';
    this.intent = 0;
    this.posture = null;
    this.render = null;

    // 展开度的运动学状态，由 presence_motion 就地推进。
    this.open = 0;
    this.openV = 0;

    // 铺回（只在 dissolving 用）：光从顶部中间朝左右两边长开，再顺两边下来。
    this.spreading = false;
    this.spread = 0;

    this._lastKind = 'none';
    this.lastFrame = 0;
  }

  init() {
    this._connectBackend();
    this._apply();
    requestAnimationFrame((t) => this._loop(t));
  }

  // ── 后端接线（与改造前同一条路，未动）──

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

    // ── 第三态有两种收场，方向相反 ──
    //
    //   manifest → liminal  = handoff     做完接着下一轮
    //   manifest → silent   = dissolving  做完就散
    //
    // 契约对这一位的注释就是冲着这件事写的：**退场编排该看这一位，而不是看深度
    // 往哪边走** —— 深度倒着走只能把进场动画倒放，而这两件事本就该是两段不同的动作。
    //
    // handoff 不需要在这儿做任何事：后端接着会报 lifecycle=liminal，展开度自己
    // 回到 1，于是"收到一半又推出去"是主轴序列自然长出来的，不是编出来的。
    // dissolving 才要额外一步：把光从顶部中间铺回三条边 —— 岛把它还回去。
    const kind = (this.render && this.render.transition_kind) || 'none';
    if (kind !== this._lastKind) {
      if (kind === 'dissolving') { this.spreading = true; this.spread = 0; }
      else if (kind === 'emerging' || kind === 'committing') { this.spreading = false; this.spread = 0; }
      this._lastKind = kind;
    }
  }

  // ── 运动学：只决定"怎么走"，不决定"走到哪儿" ──
  //
  // 落点由主轴给（OPEN_BY_LIFECYCLE），过程交给 presence_motion：编排带里匀速
  // 穿越（着色器时代留下的限速器，现在换成 CSS 依然需要 —— 相位广播是事件驱动的
  // 离散跳变，纯弹簧约 100ms 就冲过整段，中间的动作在数学上看不见），带外走弹簧；
  // 塌缩/回撤倾向接进穿越速度、稳定度接进阻尼（抖的时候别跟着抖）。
  _advance(dt) {
    const life = (this.render && this.render.lifecycle) || this.phase;
    const target = OPEN_BY_LIFECYCLE[life] !== undefined ? OPEN_BY_LIFECYCLE[life] : 0;

    if (typeof PresenceMotion === 'undefined') {
      this.open += (target - this.open) * Math.min(1, dt * 3);
      return;
    }
    const st = { depth: this.open, velocity: this.openV };
    PresenceMotion.advance(st, target, dt, {
      intent: this.intent,
      posture: this.render || this.posture,
    });
    this.open = st.depth;
    this.openV = st.velocity;
  }

  _loop(now) {
    requestAnimationFrame((t) => this._loop(t));

    // 自适应帧率（无独显机器的省电闸，沿用改造前的取向）：
    // 静默且没有过渡 → 12fps 只够那口慢呼吸；过渡中或已展开 → 30fps。
    const moving = Math.abs(this.openV) > 0.0015
      || Math.abs(this.open - (OPEN_BY_LIFECYCLE[(this.render && this.render.lifecycle) || this.phase] || 0)) > 0.01
      || this.spreading;
    const minFrameMs = 1000 / (this.open > 0.02 || moving ? 30 : 12);
    if (now - this.lastFrame < minFrameMs) return;
    const dt = Math.min((now - this.lastFrame) / 1000, 0.05);
    this.lastFrame = now;

    this._advance(dt);
    if (this.spreading) {
      this.spread += 0.85 * dt;
      if (this.spread >= 1) { this.spread = 1; this.spreading = false; }
    }
    this._apply();
  }

  // ── 把状态写成 CSS 变量。样式全在 index.html，这里只给数。 ──
  _apply() {
    const s = this.root.style;
    const open = this.open;
    const pull = ease(seg(open, 'pull'));
    const grow = easeOut(seg(open, 'grow'));
    const isle = ease(seg(open, 'isle'));

    const p = (this.render && this.render.perception) || null;
    const paused = !!(p && p.privacy_paused);

    // ── 表达期屏幕是干净的：边光**不能**跟着空间一起回来 ──
    //
    // 展开度在 silent 和 manifest 都是 0（一个还没展开、一个已经收回），单靠它
    // 分不出这两件事。而第一态那条光的含义是"在场但不表达"，manifest 恰恰是
    // "对外表达"—— 收完之后它正在点你的鼠标，这时候亮着那条光等于说反了。
    // 所以表达期把收回量钉死在满格，光留在外面，屏幕让给桌面。
    const life = (this.render && this.render.lifecycle) || this.phase;
    const pullNow = (life === 'manifest') ? 1 : pull;

    // 收回 / 铺回：两条路各管各的，见 index.html 里那三条遮罩。
    if (this.spreading || this.spread > 0.001) {
      s.setProperty('--my', '0%');
      s.setProperty('--mx', '0%');
      s.setProperty('--r', (this.spread * 260).toFixed(1) + '%');
    } else {
      s.setProperty('--my', (sub(pullNow, 0, 0.62) * 100).toFixed(2) + '%');
      s.setProperty('--mx', (sub(pullNow, 0.62, 1) * 109).toFixed(2) + '%');
      s.setProperty('--r', '260%');
    }

    // 四壁：只长深度，转角写死 90°。
    const H = window.innerHeight || 900;
    s.setProperty('--D', (grow * H * 1.12).toFixed(1) + 'px');
    s.setProperty('--wop', grow.toFixed(4));

    // ── 第一态的浓度：只调浓淡，不动几何 ──
    //
    // 感知帧 2 秒才一拍，而且绝大多数拍是"看到了不打扰"（ambient 循环的门控层
    // 直接免费跳过）。跟着数据跳就是一惊一乍 —— 那本身就是打扰。
    // 所以光自己缓慢呼吸，后端只给四档：亮着 / 闭着 / 压成线 / 不亮。
    s.setProperty('--rim', (paused ? 0 : this._senseGlow(p)).toFixed(3));

    // ── 灵动岛：从上边框长出来。收到最小就是一道贴边细线。 ──
    //
    // **急停那道线就是岛本身**，不是另加一个元素：有线＝我在但我闭着，
    // 没线＝这台机器根本没有感知可用。契约把 privacy_paused 单独给一位，
    // 正是因为"用户按停了"是一个整体姿态，不是"恰好四条都闭着"。
    const h = paused ? 2 : 2 + isle * 31;
    const w = paused ? 68 : 66 + isle * 182;
    s.setProperty('--ih', h.toFixed(1) + 'px');
    s.setProperty('--iw', w.toFixed(1) + 'px');
    s.setProperty('--ir', (paused ? 2 : 2 + isle * 15).toFixed(1) + 'px');
    s.setProperty('--iop', paused ? '0.85' : (isle > 0.001 ? '1' : '0'));
    s.setProperty('--itx', Math.max(0, (isle - 0.55) / 0.45).toFixed(3));

    this._paintIsland(paused);
    this._paintPet(p, paused);
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
    if (paused) { this.islandMode.hidden = true; return; }
    const r = this.render || {};
    const act = r.liminal_activity || 'none';
    const mode = (r.hybrid_execution && r.hybrid_execution.mode) || 'none';
    const word = ACTIVITY_WORD[act] || 'Galaxy';
    if (this.islandText.textContent !== word) this.islandText.textContent = word;
    const m = MODE_WORD[mode] || '';
    this.islandMode.hidden = !m;
    if (m && this.islandMode.textContent !== m) this.islandMode.textContent = m;
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

    const act = (this.render && this.render.liminal_activity) || 'none';
    const rate = PET_RATE[act] || PET_RATE.none;
    if (this.pet.style.getPropertyValue('--pet-rate') !== rate) {
      this.pet.style.setProperty('--pet-rate', rate);
    }
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('DOMContentLoaded', () => {
    window.lumivRenderer = new GalaxyOverlay();
    window.lumivRenderer.init();
  });
}
