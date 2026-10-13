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
 *   * 窗口的**外形**就是画布的圆角矩形（`shapeRects`，主进程交给系统裁窗口）。所有者在 Windows 上拍到：
 *     窗口矩形是白的、方角，面板的圆角落在里面，上沿还露一条白带 —— 那台机器上透明窗口没有透明，
 *     页面里怎么把圆角外弄透明都没用。由系统按外形裁掉，圆角外、画布外就不是窗口的一部分了：
 *     不画、也不接鼠标，透明生不生效都一样。
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
  /** 画布的圆角半径（画布像素）。与面板 hud.css 的 `--shell-r` 是同一个数（测试核对）。 */
  var RADIUS = 34;
  /** 窗口外形的圆弧比页面的圆弧往里收多少像素（见 `shapeRects`）。 */
  var EDGE_IN = 0.3;

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
   * 画布永远整张都在窗口里，不会被裁掉一条边。偏移取整像素：画布的边落在像素缝上，
   * 不会出现一整行半透明的边（窗口外形按整像素裁，见 `shapeRects`）。
   */
  function fit(view) {
    var k = Math.min(view.width / STAGE.width, view.height / STAGE.height);
    if (!(k > 0) || !isFinite(k)) k = 1;
    return {
      k: k,
      dx: Math.max(0, Math.floor((view.width - STAGE.width * k) / 2)),
      dy: Math.max(0, Math.floor((view.height - STAGE.height * k) / 2)),
    };
  }

  /**
   * 这么大的视口里，窗口该是什么形状：`fit` 摆好的那张画布、四角按 `RADIUS` 一起缩放倒圆。
   *
   * 给的是一组矩形（窗口坐标、与视口同一种像素），并起来就是那个圆角矩形：圆角那几行一行一条
   * （内缩相同的相邻行合并），中间一整块。一个像素的中心在圆弧以内 `EDGE_IN` 才算在内 —— 系统按
   * 整像素裁；页面的抗锯齿边比几何圆弧略靠里一点（Chromium 实测约 0.3 像素），盖不到一半的边缘像素
   * 留在窗口里，会在不透明的窗口上描出一圈浅色。
   */
  function shapeRects(view) {
    var f = fit(view);
    var x0 = f.dx;
    var y0 = f.dy;
    // 右边、下边同一条规矩：那一列 / 一行的像素中心在画布边以内 EDGE_IN 才算（缩放后边常落在像素中间）。
    var w = Math.floor(STAGE.width * f.k + 0.5 - EDGE_IN);
    var h = Math.floor(STAGE.height * f.k + 0.5 - EDGE_IN);
    if (!(w > 0 && h > 0)) return [];
    // 半径不取整：页面那条弧就是 RADIUS × k。
    var r = Math.max(0, Math.min(RADIUS * f.k, Math.min(w, h) / 2));
    var R = Math.min(Math.ceil(r), Math.floor(Math.min(w, h) / 2));
    var rows = [];
    var e = Math.min(EDGE_IN, r);
    for (var i = 0; i < R; i++) {
      // 第 i 行像素中心到圆心的竖直距离 d；水平距离小于 √((r−e)²−d²) 的像素在内。
      var d = r - (i + 0.5);
      var reach = d > 0 ? Math.sqrt(Math.max(0, (r - e) * (r - e) - d * d)) : r;
      rows.push(Math.min(R, Math.max(0, Math.floor(r - reach - 0.5) + 1)));
    }
    var rects = [];
    var push = function (y, height, inset) {
      rects.push({ x: x0 + inset, y: y, width: w - 2 * inset, height: height });
    };
    for (var a = 0; a < rows.length; ) {
      var b = a;
      while (b + 1 < rows.length && rows[b + 1] === rows[a]) b++;
      push(y0 + a, b - a + 1, rows[a]);
      push(y0 + h - 1 - b, b - a + 1, rows[a]);
      a = b + 1;
    }
    if (h - 2 * R > 0) push(y0 + R, h - 2 * R, 0);
    return rects;
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
    RADIUS: RADIUS,
    EDGE_IN: EDGE_IN,
    ratio: ratio,
    limits: limits,
    initialSize: initialSize,
    fit: fit,
    shapeRects: shapeRects,
    EDGES: EDGES,
    resizeBounds: resizeBounds,
  };

  root.PanelStage = PanelStage;
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = PanelStage;
  }
})(globalThis);
