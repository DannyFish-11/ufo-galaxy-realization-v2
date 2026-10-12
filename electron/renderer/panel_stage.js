/**
 * 面板窗口是**一整张固定尺寸的画布**，窗口多大只决定把它放多大 —— 主进程与面板共用这一份。
 *
 * 所有者：「我把上下左右角一放缩，有些东西就被揉起来了，无论是右上角设置里面的那个，还是整个面板，
 * 都会受到影响。而且这个面板给人感觉就像面团一样，不像一个完整的整体」。
 *
 * 原因：面板按窗口的实际大小重新排版（左栏定宽 + 右边 1fr、设置页的行跟着容器宽度折行）。窗口一窄，
 * 右边的卡片、设置页的那几行就被挤；窗口一扁，上下就被压。每一次拖动都是一次重新排版 —— 所以像面团。
 *
 * 现在：
 *
 *   * 面板在桌面外壳里永远按 `STAGE`（1200×700）排一次版，之后整张画布等比缩放（`fit`）。
 *     拖哪条边、哪个角，里面的排版都是同一张，只是变大变小。
 *   * 拉伸由面板自己做：边与角上各有一条拖拽手柄（面板 src/stage.ts），按住后主进程跟着光标算新的
 *     窗口大小（`resizeBounds`）—— 永远是同一个宽高比，所以等比缩放总是正好铺满，不留边。
 *     （窗口没有 Windows 的系统粗边框 —— 带着它四角会多出一圈方的白边 —— 系统也就不替它拉伸。）
 *   * 窗口大小有下限（`MIN_SCALE`）与上限（工作区），第一次打开不超过工作区的 `FIRST_FIT`。
 *
 * 浏览器里开发时（没有桌面外壳）面板照旧按视口排版 —— 这份只在外壳里起作用。
 *
 * 写法沿用 live_socket.js：挂在全局上（面板 import 进来打包），node 测试与主进程走 module.exports。
 */
(function (root) {
  'use strict';

  /** 面板排版用的那一张画布。窗口的宽高比就是它的宽高比。 */
  var STAGE = Object.freeze({ width: 1200, height: 700 });
  /** 最小缩到多少 —— 再小字就读不清了。 */
  var MIN_SCALE = 0.6;
  /** 第一次打开时最多占工作区的多少（宽、高各自算，取小的那个）。 */
  var FIRST_FIT = 0.92;

  function ratio() {
    return STAGE.width / STAGE.height;
  }

  /** 这块工作区里，窗口最大能放多大（等比、整张放得下）。 */
  function maxScale(workArea) {
    return Math.min(workArea.width / STAGE.width, workArea.height / STAGE.height);
  }

  /** 尺寸上下限（像素，等比）。工作区比最小尺寸还小时，上限压到工作区那么大。 */
  function limits(workArea) {
    var hi = Math.max(0, maxScale(workArea));
    var lo = Math.min(MIN_SCALE, hi);
    return {
      minWidth: Math.round(STAGE.width * lo),
      minHeight: Math.round(STAGE.height * lo),
      maxWidth: Math.round(STAGE.width * hi),
      maxHeight: Math.round(STAGE.height * hi),
    };
  }

  /** 第一次打开的大小：1 倍，屏幕放不下就缩到工作区的 FIRST_FIT（不低于最小）。 */
  function initialSize(workArea) {
    var hi = maxScale(workArea);
    var k = Math.min(1, hi * FIRST_FIT);
    k = Math.max(Math.min(MIN_SCALE, hi), k);
    return { width: Math.round(STAGE.width * k), height: Math.round(STAGE.height * k) };
  }

  /**
   * 这么大的视口里，画布放多大、往哪儿摆。
   *
   * 宽高比锁着时两个方向算出来的倍数一样；差的那一两个像素（取整）由居中吃掉，
   * 画布永远整张都在窗口里，不会被裁掉一条边。
   */
  function fit(view) {
    var k = Math.min(view.width / STAGE.width, view.height / STAGE.height);
    if (!(k > 0) || !isFinite(k)) k = 1;
    return {
      k: k,
      dx: (view.width - STAGE.width * k) / 2,
      dy: (view.height - STAGE.height * k) / 2,
    };
  }

  /** 能拖的八个方位：四条边、四个角。 */
  var EDGES = Object.freeze(['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw']);

  /**
   * 按住 `edge` 拖了 (dx, dy) 之后窗口该是多大、在哪儿。
   *
   *   * 宽高比永远是 STAGE 的；拖边只看那一个方向，拖角看动得多的那一个方向。
   *   * 对面的边（角）不动；拖上下边时左右居中地长，拖左右边时上下居中地长。
   *   * 夹在 `lim`（`limits` 给的上下限）之间。
   */
  function resizeBounds(start, edge, dx, dy, lim) {
    var r = ratio();
    var e = edge.indexOf('e') >= 0;
    var w = edge.indexOf('w') >= 0;
    var n = edge.indexOf('n') >= 0;
    var s = edge.indexOf('s') >= 0;
    var byX = start.width + (e ? dx : w ? -dx : 0);
    var byY = (start.height + (s ? dy : n ? -dy : 0)) * r;
    var width;
    if (!e && !w) width = byY;
    else if (!n && !s) width = byX;
    else width = Math.abs(byX - start.width) >= Math.abs(byY - start.width) ? byX : byY;
    width = Math.round(Math.min(lim.maxWidth, Math.max(lim.minWidth, width)));
    var height = Math.round(width / r);
    return {
      x: w ? start.x + start.width - width : e ? start.x : Math.round(start.x + (start.width - width) / 2),
      y: n ? start.y + start.height - height : s ? start.y : Math.round(start.y + (start.height - height) / 2),
      width: width,
      height: height,
    };
  }

  var PanelStage = {
    STAGE: STAGE,
    MIN_SCALE: MIN_SCALE,
    FIRST_FIT: FIRST_FIT,
    ratio: ratio,
    limits: limits,
    initialSize: initialSize,
    fit: fit,
    EDGES: EDGES,
    resizeBounds: resizeBounds,
  };

  root.PanelStage = PanelStage;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = PanelStage;
  }
})(globalThis);
