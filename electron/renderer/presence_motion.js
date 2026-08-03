/**
 * presence_motion.js —— 覆盖层的深度运动
 *
 * 为什么单独成文件
 * ----------------
 * 这段物理原本内联在 `app.js` 的 `_springUpdate` 里，和 canvas / WebGL / DOM
 * 缠在一起，没法在没有浏览器的地方跑。抽出来的**唯一理由是可测**：
 * "倾向大 → 过渡更决绝"这种话不能靠读代码取信，得能跑出数来。
 *
 * 这里不碰任何 DOM、不引任何依赖，纯输入输出。
 *
 * 它在修什么
 * ----------
 * 后端每拍算出的 `posture` 里带着 `collapse_tendency`（离翻到下一档还有多近）、
 * `retreat_tendency`、`stability`（低值 = 最近发生过相位振荡）。改造前渲染端
 * **只用了目的地**：
 *
 *     collapse=0.0  target=0.6072  穿越耗时 1.20s  速度 0.464/s
 *     collapse=0.9  target=0.7287  穿越耗时 1.43s  速度 0.474/s
 *                                                  ↑ 四档之间只差 2%
 *
 * 也就是说"离翻档有多近"只体现在**停在哪儿**，完全不体现在**怎么过去**——
 * 决绝的塌缩和犹豫的塌缩，动起来一模一样。这里把倾向接进穿越速度、把稳定度
 * 接进弹簧阻尼（`core/phase_contract.py` 里 stability 的注释写的就是
 * "前端可据此加大阻尼"，这是它第一次被真的用上）。
 *
 * 刻意保留的东西
 * --------------
 * **编排限速器不删**。它存在的理由仍然成立：着色器的分幕（0.25-0.40 边缘光
 * 收回 → 0.40-0.85 空间展开）假设 depth 匀速穿越，而相位事件仍是离散跳变
 * （广播是事件驱动的，不是每帧一拍）。纯弹簧约 100ms 就冲过整个收回窗口，
 * 回收动画在数学上就不可能被看见。这里改的是**速度怎么定**，不是要不要限速。
 *
 * **拿不到 posture 时逐位退回原行为**。倾向为 0、稳定度为 1 时，下面的式子
 * 化简回 `1.0 + intent * 0.8` 与 `friction = 14`，与改造前完全一致。
 * `presence_motion.test.js` 里有一条测试拿独立复刻的旧实现逐帧比对来钉这件事。
 */
(function (root) {
  'use strict';

  // ── 编排带（与 shaders/lumiv.frag 的分幕对应，勿随手改） ──
  var CHOREO_LO = 0.10;   // 带下沿：低于此值不再限速（纯静默区）
  var CHOREO_HI = 0.90;   // 带上沿
  var CHOREO_GAP = 0.04;  // 小于此跨度视为微调，走弹簧而非匀速
  var CHOREO_UP = 0.34;   // 上行基准速度（depth/秒）
  var CHOREO_DOWN = 0.55; // 下行基准速度：回到静默稍快

  // ── 连续量的作用强度 ──

  //: 倾向对穿越速度的最大加成。倾向拉满时穿越快约 1.6 倍（在 intent=0.5 时
  //: boost 从 1.40 升到 2.21）。取 0.9 而不是更大：再快就会重新压过着色器
  //: 的收回窗口，把这个限速器当初要修的问题原样带回来。
  var TENDENCY_BOOST = 0.9;

  //: 稳定度对弹簧阻尼的最大加成。stability=0（刚发生过相位振荡）时阻尼 ×1.8,
  //: 明显过阻尼——这正是想要的：抖的时候别跟着抖。
  var STABILITY_DAMP = 0.8;

  var SPRING_FRICTION = 14;

  function clamp01(v) {
    if (!(v >= 0)) return 0;   // 同时挡住 NaN
    return v > 1 ? 1 : v;
  }

  /**
   * 从 posture 里取三个连续量；拿不到就退回"中性值"——中性值代入下面的式子
   * 会让整段化简回改造前的常数，这是降级路径逐位一致的来源。
   */
  function readPosture(posture) {
    if (!posture || typeof posture !== 'object') {
      return { collapse: 0, retreat: 0, stability: 1 };
    }
    return {
      collapse: clamp01(posture.collapse_tendency),
      retreat: clamp01(posture.retreat_tendency),
      // stability 缺失按 1（最稳）处理：宁可不加阻尼，也不要凭空把动画拖慢。
      stability: posture.stability === undefined || posture.stability === null
        ? 1
        : clamp01(posture.stability),
    };
  }

  /**
   * 推进一帧。
   *
   * @param {{depth:number, velocity:number}} state 会被【就地修改】——每帧都调，
   *        不制造垃圾对象。
   * @param {number} target 后端给的目标深度（payload.depth_factor）
   * @param {number} dt 帧间隔（秒）
   * @param {{intent:number, posture:Object|null}} signals
   * @returns {{depth:number, velocity:number}} 就是传进来的 state
   */
  function advance(state, target, dt, signals) {
    var intent = (signals && typeof signals.intent === 'number') ? signals.intent : 0;
    var p = readPosture(signals && signals.posture);

    var cur = state.depth;
    var gap = target - cur;

    var inBand = Math.max(cur, target) > CHOREO_LO && Math.min(cur, target) < CHOREO_HI;

    if (inBand && Math.abs(gap) > CHOREO_GAP) {
      // 匀速穿越编排带。速度由【意图强度】+【本方向的倾向】共同决定：
      // 上行看塌缩倾向（推向下一档的概率质量），下行看回撤倾向。
      // 倾向为 0 时化简为原式 1.0 + intent * 0.8。
      var tendency = gap > 0 ? p.collapse : p.retreat;
      var boost = 1.0 + intent * 0.8 + tendency * TENDENCY_BOOST;
      var speed = (gap > 0 ? CHOREO_UP : CHOREO_DOWN) * boost;
      var step = (gap > 0 ? 1 : -1) * Math.min(Math.abs(gap), speed * dt);
      state.depth = Math.max(0, Math.min(1, cur + step));
      state.velocity = (gap > 0 ? 1 : -1) * speed;  // 供帧率/活跃判定复用
      return state;
    }

    // 带外 / 微调 → 弹簧微平滑。稳定度低（最近振荡过）时加大阻尼，
    // 让画面不跟着抖；stability=1 时化简为原式 friction = 14。
    var intentBoost = 1.0 + intent * 1.5;
    var tension = cur < target ? 50 * intentBoost : 70;
    var friction = SPRING_FRICTION * (1.0 + (1.0 - p.stability) * STABILITY_DAMP);
    var force = -tension * (cur - target);
    state.velocity += (force - friction * state.velocity) * dt;
    state.depth = Math.max(0, Math.min(1, cur + state.velocity * dt));
    return state;
  }

  var api = {
    advance: advance,
    // 导出常量供测试与调参使用；app.js 不直接读它们。
    CHOREO_LO: CHOREO_LO,
    CHOREO_HI: CHOREO_HI,
    CHOREO_GAP: CHOREO_GAP,
    CHOREO_UP: CHOREO_UP,
    CHOREO_DOWN: CHOREO_DOWN,
    TENDENCY_BOOST: TENDENCY_BOOST,
    STABILITY_DAMP: STABILITY_DAMP,
    SPRING_FRICTION: SPRING_FRICTION,
  };

  root.PresenceMotion = api;
  // 覆盖层是无构建的原生 JS（<script> 直接加载），所以主路径走全局；
  // 这一行只为让 node 测试能 require 它，浏览器里不会命中。
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this);
