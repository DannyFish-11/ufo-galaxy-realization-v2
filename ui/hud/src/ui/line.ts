/**
 * 左下那条线。**它只管这台机器。**
 *
 * 跨设备与多设备不往这条线上叠 —— 一件乐器只说一件事,叠上去之后
 * 「本机在动」和「别处在动」就再也分不开了。
 *
 * 线本身不动,一道窄光从前往后走。三态由脉冲的**快慢与亮度**表达,
 * 线上没有任何标记(没有点,也不把线弯成波)。
 *
 * 六个周期都避开 0.2 Hz 那一带(约 0.17–0.25 Hz)。**六个,不是三个** ——
 * 收窄态是另一套节拍,不是把常态乘一个系数:
 *   常态  静 8.0s=0.125Hz   阈 3.4s=0.294Hz   显 2.2s=0.455Hz
 *   收窄  静 12.0s=0.083Hz  阈 6.4s=0.156Hz   显 3.2s=0.313Hz
 * 这是照 Apple 那份动效指引来的 —— 那个频段人最敏感,持续振荡容易引起不适。
 *
 * 这里原先是常态 × 1.5,于是收窄态的阈落到 5.1s = 0.196 Hz,**正好在带里**,
 * 而上面这段注释还写着「都避开」。判据写在注释里就是这个下场,所以下面那道
 * 载入即跑的检查才存在:再有人动这张表,越界会当场说出来。
 *
 * 真接后端之后,快慢该跟 `presence_intensity`(EMA 平滑的连续量)走,
 * 而不是按相位跳三档。那一步等投影链路查清楚再做,现在按相位是演示值。
 */
import type { Phase } from '../types';

interface Cadence {
  readonly seconds: number;
  /** 收窄之后的周期。**单列一栏**,不是常态乘系数 —— 乘出来的值没人核过。 */
  readonly slimSeconds: number;
  readonly amplitude: number;
}

const CADENCE: Record<Phase, Cadence> = {
  silent: { seconds: 8.0, slimSeconds: 12.0, amplitude: 0.3 },
  liminal: { seconds: 3.4, slimSeconds: 6.4, amplitude: 0.5 },
  manifest: { seconds: 2.2, slimSeconds: 3.2, amplitude: 0.72 },
};

/** 要躲开的那一带,单位 Hz。 */
const AVOID_LO = 0.17;
const AVOID_HI = 0.25;

/** 落在带里就是不合格。周期 → 频率,只有一处换算。 */
export function inAvoidBand(seconds: number): boolean {
  const hz = 1 / seconds;
  return hz >= AVOID_LO && hz <= AVOID_HI;
}

// 载入即跑。不静默 —— 越界要留痕,否则改坏了没人知道。
for (const [phase, c] of Object.entries(CADENCE)) {
  for (const [mode, secs] of [['常态', c.seconds], ['收窄', c.slimSeconds]] as const) {
    if (inAvoidBand(secs)) {
      console.error(
        `[hud/line] ${phase} 的${mode}周期 ${secs}s = ${(1 / secs).toFixed(3)} Hz,` +
          `落在要躲开的 ${AVOID_LO}–${AVOID_HI} Hz 带里。`,
      );
    }
  }
}

/**
 * 这条线**当前算不算数**。
 *
 * `live` 是 continuum 实算出来的;`anchor` 是拿不到 continuum、按相位锚点兜的底;
 * `degraded` 是后端明说本拍跑在降级模式。契约里 `source` 与 `degraded` 一直
 * 老老实实报着这三种情况,而线原先三种画得一模一样 —— 兜底的相位和实算的相位
 * 摆出同样的光,人就没法知道自己在看的是测出来的还是猜出来的。
 */
export type LineTrust = 'live' | 'anchor' | 'degraded';

export interface LineHandles {
  readonly root: HTMLElement;
  /** 三态变了、线宽变了、可信度变了,都调它。 */
  update(phase: Phase, slim: boolean, trust: LineTrust): void;
}

export function createLine(): LineHandles {
  const zone = document.createElement('div');
  zone.className = 'line-zone';
  const line = document.createElement('div');
  line.className = 'line';
  const pulse = document.createElement('div');
  pulse.className = 'line-pulse';
  line.append(pulse);
  zone.append(line);

  let lastPhase: Phase | null = null;
  let lastSlim = false;

  /**
   * 线自己变宽变窄要**自己看见**。
   *
   * 收窄是一段 CSS 过渡:`update()` 在状态变的那一刻跑,量到的还是旧宽度,
   * 于是 212px 的行程配上 60px 的线 —— 那道光大半个周期都在可视区外面,
   * 收窄之后基本看不到它在走。外层那个 ResizeObserver 盯的是整壳,线自己
   * 缩了它不响。所以这里单独盯这一条线。
   */
  const ro = new ResizeObserver(() => {
    if (lastPhase !== null) geometry(lastPhase, lastSlim);
  });
  ro.observe(line);

  /** 只算跟宽度有关的那几个量。相位没变就不重起那道光。 */
  function geometry(phase: Phase, slim: boolean): void {
    const w = line.clientWidth || 120;
    // 脉冲不能比线还长。收窄之后线只有几十像素,那道亮得跟着缩 ——
    // 不缩的话它整个行程都在线外,看着就是没动。
    const pw = Math.max(18, Math.min(96, w * 0.4));
    line.style.setProperty('--w', `${w}px`);
    line.style.setProperty('--pw', `${pw}px`);
    line.style.setProperty(
      '--dur',
      `${(slim ? CADENCE[phase].slimSeconds : CADENCE[phase].seconds).toFixed(2)}s`,
    );
    line.style.setProperty(
      '--amp',
      String(slim ? CADENCE[phase].amplitude * 0.7 : CADENCE[phase].amplitude),
    );
  }

  function update(phase: Phase, slim: boolean, trust: LineTrust): void {
    lastSlim = slim;
    line.dataset['trust'] = trust;
    geometry(phase, slim);

    // 三态变了就从头起一道,让「它变了」当场能感觉到。
    if (phase !== lastPhase) {
      lastPhase = phase;
      delete line.dataset['run'];
      void line.offsetWidth;
    }
    line.dataset['run'] = 'true';
  }

  return { root: zone, update };
}
