/**
 * 左下那条线。**它只管这台机器。**
 *
 * 跨设备与多设备不往这条线上叠 —— 一件乐器只说一件事,叠上去之后
 * 「本机在动」和「别处在动」就再也分不开了。
 *
 * 线本身不动,一道窄光从前往后走。三态由脉冲的**快慢与亮度**表达,
 * 线上没有任何标记(没有点,也不把线弯成波)。
 *
 * 三个周期都避开 0.2 Hz 那一带(约 0.17–0.25 Hz):
 *   静 8.0s = 0.125 Hz   阈 3.4s = 0.29 Hz   显 2.2s = 0.45 Hz
 * 这是照 Apple 那份动效指引来的 —— 那个频段人最敏感,持续振荡容易引起不适。
 *
 * 真接后端之后,快慢该跟 `presence_intensity`(EMA 平滑的连续量)走,
 * 而不是按相位跳三档。那一步等投影链路查清楚再做,现在按相位是演示值。
 */
import type { Phase } from '../types';

interface Cadence {
  readonly seconds: number;
  readonly amplitude: number;
}

const CADENCE: Record<Phase, Cadence> = {
  silent: { seconds: 8.0, amplitude: 0.3 },
  liminal: { seconds: 3.4, amplitude: 0.5 },
  manifest: { seconds: 2.2, amplitude: 0.72 },
};

export interface LineHandles {
  readonly root: HTMLElement;
  /** 三态变了、或者线宽变了,都调它。 */
  update(phase: Phase, slim: boolean): void;
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

  function update(phase: Phase, slim: boolean): void {
    const w = line.clientWidth || 120;
    const c = CADENCE[phase];

    // 脉冲不能比线还长。收窄之后线只有几十像素,那道亮得跟着缩 ——
    // 不缩的话它会整个溢出线外,看着就是坏的。
    const pw = Math.max(18, Math.min(96, w * 0.4));

    line.style.setProperty('--w', `${w}px`);
    line.style.setProperty('--pw', `${pw}px`);
    line.style.setProperty('--dur', `${(c.seconds * (slim ? 1.5 : 1)).toFixed(2)}s`);
    line.style.setProperty('--amp', String(slim ? c.amplitude * 0.7 : c.amplitude));

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
