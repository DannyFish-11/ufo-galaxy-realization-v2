/**
 * 桌面外壳里,面板是**一整张固定尺寸的画布**,窗口多大只决定把它整张放多大。
 *
 * 以前面板按窗口实际大小排版:窗口一窄,右边的卡片、设置页里的行就被挤;一扁,上下就被压 ——
 * 每拖一下都重新排一次版,所有者说它「像面团一样,不像一个完整的整体」。
 *
 * 现在画布按 `PanelStage.STAGE`(electron/renderer/panel_stage.js,主进程锁窗口宽高比用的也是它)
 * 排一次版,之后只做等比的 `transform: scale`。拖哪条边、哪个角,里面都是同一张,只是变大变小;
 * 排版不变,卡片高度、滑键这些按布局量出来的东西也就不用跟着重算。
 *
 * 拉伸:窗口没有系统粗边框(带着它,Windows 会沿窗口矩形描一圈方的白边),系统不替它拉伸 ——
 * 四条边、四个角上各有一条看不见的手柄,按住时告诉外壳(`galaxyShell.beginResize`),外壳跟着
 * 光标等比改窗口大小,松手再说一声。手柄挂在 body 上、不在画布里:它们按窗口像素量,不跟着缩放。
 *
 * 浏览器里开发(没有 `galaxyShell`)照旧按视口排版。
 */
import '../../panel_stage.js';

const PS = globalThis.PanelStage;

interface ResizeShell {
  beginResize?(edge: string): void;
  endResize?(): void;
}

function addGrips(shell: ResizeShell): void {
  const begin = shell.beginResize;
  const end = shell.endResize;
  if (typeof begin !== 'function' || typeof end !== 'function') return;
  for (const edge of PS.EDGES) {
    const grip = document.createElement('div');
    grip.className = 'grip';
    grip.dataset['edge'] = edge;
    grip.addEventListener('pointerdown', (e: PointerEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      // 光标拖出窗口也要收到松手 —— 不然窗口会一直跟着光标变。
      grip.setPointerCapture(e.pointerId);
      begin.call(shell, edge);
    });
    const stop = (): void => end.call(shell);
    grip.addEventListener('pointerup', stop);
    grip.addEventListener('lostpointercapture', stop);
    document.body.append(grip);
  }
}

/** 把面板挂到画布上并跟着窗口等比缩放。不在桌面外壳里就什么都不做。 */
export function fitStage(host: HTMLElement, inDesktopShell: boolean): void {
  if (!inDesktopShell) return;
  const root = document.documentElement;
  root.dataset['stage'] = 'fixed';
  host.style.width = `${PS.STAGE.width}px`;
  host.style.height = `${PS.STAGE.height}px`;

  const apply = (): void => {
    const { k, dx, dy } = PS.fit({ width: window.innerWidth, height: window.innerHeight });
    host.style.transform = `translate(${dx}px, ${dy}px) scale(${k})`;
    // 文档那一层按壳的圆角裁(hud.css):半径要跟着画布一起缩,不然缩小时会裁进壳的圆角里。
    root.style.setProperty('--stage-k', String(k));
  };
  apply();
  window.addEventListener('resize', apply);
  addGrips((window as { galaxyShell?: ResizeShell }).galaxyShell ?? {});
}
