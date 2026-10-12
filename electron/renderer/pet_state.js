/**
 * 桌宠此刻该是什么样子 —— **三只桌宠共用的那一份推导**。
 *
 * 屏幕上有三只桌宠：面板里那只（panel/src/ui/pet.ts）、覆盖层灵动岛上那只（app.js）、
 * 右下角托盘那只（windows_service/pet_icon.py）。它们读的是同一份帧
 * （WS / IPC 的 `payload.render`，托盘在进程内直接收同一份），所以**该是同一个样子**。
 *
 * 以前面板和覆盖层各写一份推导，于是在一件事上讲岔了：进程里没有感知库
 * （`perception.source === 'unwired'`）时，覆盖层那只眼睛是虚的（「不知道」），面板那只
 * 却是睁着的 —— 等于替后端说「它正看着」。现在两只都调这里；托盘那只是 Python，
 * 照同一张用例表（pet_state.cases.json）由 pytest 逐条核对，node 这边由
 * pet_state.test.js 核对同一张表。
 *
 * 覆盖层是无构建的原生 JS（<script> 直接加载），面板是 Vite 打包 —— 所以这里沿用
 * presence_motion.js 的写法：挂在全局上，node 测试另走 module.exports。
 *
 * 只管**推导**（这一帧该是哪一档），不管**画**（几何、颜色在各自的 CSS / 托盘里，
 * 由 tests/test_every_pet_is_the_same_pet.py 核对三处一模一样）。
 */
(function (root) {
  'use strict';

  // 阈限态里它在干嘛 → 呼吸多快。越往后使劲喘得越快。
  // 要躲开的那一带（0.17–0.25 Hz）判据在 panel/src/motion.ts，面板载入时由 checkPeriods 当场核对。
  //   none 9.0s = 0.111 Hz · understanding 6.5s = 0.154 Hz · thinking 3.6s = 0.278 Hz · rehearsing 2.6s = 0.385 Hz
  var BREATH = { none: '9s', understanding: '6.5s', thinking: '3.6s', rehearsing: '2.6s' };

  // 上一拍的决策 → 演哪一种反应。四档各一种，少一种那一档就没演。
  var POSE = { none: 'rest', speak: 'lean', silent: 'tuck', delegate: 'aside' };

  // 反应演多久（毫秒）。演完撤回实时那一层：一个已经过去的决策不该是一个永久的姿势。
  var REACT_MS = 1600;

  /**
   * 一帧 → 桌宠该是哪一档。
   *
   * input:
   *   lifecycle         主轴（silent/static · liminal · manifest）
   *   liminal_activity  阈限态里在干嘛（非阈限态时后端给 none）
   *   perception        契约里的 PerceptionView；null = 还没收到过帧
   *
   * 返回：
   *   phase    'silent' | 'liminal' | 'manifest'
   *   activity BREATH 的键（不认得的一律 none）
   *   rate     呼吸周期
   *   eyes     'open' | 'shut' | 'unknown' —— 三档，不是布尔
   *   sensing  'true' | 'false' | 'unknown' —— 与 eyes 分开两位：睁没睁是一件事，收没收是另一件事
   *   act      上一拍的决策；null = 不知道（没收到帧，或进程里根本没有感知库）
   */
  function derive(input) {
    var i = input || {};
    var life = i.lifecycle;
    var phase = life === 'liminal' || life === 'manifest' ? life : 'silent';
    var activity = Object.prototype.hasOwnProperty.call(BREATH, i.liminal_activity) ? i.liminal_activity : 'none';
    var p = i.perception || null;
    // 有感知库、而且收到过帧，才谈得上「睁着 / 在收 / 上一拍想了什么」。
    var known = !!(p && p.source !== 'unwired');

    // 眼睛：按了「别看了」就闭上 —— 哪怕别的都不知道，这一位是确定的。
    // 否则只有「知道」时才睁着；不知道就虚着：既不能画成睁着（替后端说它正看着），
    // 也不能画成闭着（说它已经停了）。
    var eyes = p && p.privacy_paused === true ? 'shut' : known ? 'open' : 'unknown';
    var sensing = known ? String(!!p.is_sensing) : 'unknown';
    var act = known ? (typeof p.ambient_action === 'string' && p.ambient_action ? p.ambient_action : 'none') : null;

    return {
      phase: phase,
      activity: activity,
      rate: BREATH[activity],
      eyes: eyes,
      sensing: sensing,
      act: act,
    };
  }

  /** 这一拍的决策该演哪一种反应；不演（none / 不知道）就是 null。 */
  function reactionFor(act) {
    if (!act || act === 'none') return null;
    return Object.prototype.hasOwnProperty.call(POSE, act) ? POSE[act] : 'rest';
  }

  var api = { BREATH: BREATH, POSE: POSE, REACT_MS: REACT_MS, derive: derive, reactionFor: reactionFor };

  root.PetState = api;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;
  }
})(globalThis);
