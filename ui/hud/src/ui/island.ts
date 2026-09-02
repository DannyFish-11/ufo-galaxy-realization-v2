/**
 * 右上那块岛:感知与设备。
 *
 * 它是**同一个元素自己长大**,不是弹出来一个新浮层 —— 宽、高、圆角连续
 * 过渡,内容交叉淡入。弹出会让人觉得来了个新东西,而它其实一直在那儿。
 *
 * 状态**不用点**,用**深度**:在线的浮起来(柔影 + 顶边受光),降级的几乎
 * 贴平,离线的沉进表面(只剩凹槽,没有影子)。状态就是它离墙多远。
 *
 * 活跃**不用闪**,用**光的行走**:一道细光斜掠而过,忙就掠得频繁、闲就
 * 几秒才飘一次。这是 Weiser 与 Brown 那根 Dangling String 的做法 ——
 * 屏幕上的符号需要解读,而这种东西跟人的周边视觉阻抗匹配得更好:
 * 忙不忙是**余光里感觉到**的,不是读出来的。
 */
import type { DeviceRow, ModalityState, ModalityView, PerceptionView } from '../types';

/** 状态 → 离墙多远。五档,不是布尔 —— 「闭着」和「没有」是两件事。 */
const ELEVATION: Record<ModalityState, string> = {
  live: 'up',
  idle: 'up',
  suppressed: 'shut',   // 它在说话,这一拍不听自己
  paused: 'paused',     // 你按了隐私暂停
  unavailable: 'sunk',  // 这条通路从没来过东西
};

const DEVICE_ELEVATION = { online: 'up', degraded: 'low', offline: 'sunk' } as const;

/** 忙 → 光掠得多频繁。忙则频繁,闲则数秒一次。 */
const RATE = { busy: '1.9s', idle: '7.5s' } as const;

const MODALITY_LABEL: Record<string, string> = {
  screen: '屏幕',
  camera: '摄像头',
  microphone: '麦克风',
  system_audio: '系统声',
};

const MODALITY_SHAPE: Record<string, string> = {
  screen: 't-screen',
  camera: 't-camera',
  microphone: 't-mic',
  system_audio: 't-sys',
};

/** 这一档对人的意思。**每一档都得说得出口**,否则五档等于没分。 */
function modalityNote(m: ModalityView): string {
  switch (m.state) {
    case 'live':
      return '在收';
    case 'idle':
      return m.signal_age_s === null ? '通着，还没来过信号' : `静了 ${Math.round(m.signal_age_s)} 秒`;
    case 'suppressed':
      return '它在说话，这拍不听自己';
    case 'paused':
      return '你按了暂停';
    case 'unavailable':
      return '这台机器没有这条通路';
    default:
      return '';
  }
}

function tile(shape: string, elevation: string, busy?: 'busy' | 'idle'): HTMLElement {
  const t = document.createElement('span');
  t.className = `tile ${shape}`;
  t.dataset['elev'] = elevation;
  if (busy) {
    t.dataset['busy'] = busy;
    t.style.setProperty('--rate', RATE[busy]);
  }
  const sheen = document.createElement('span');
  sheen.className = 'tile-sheen';
  t.append(sheen);
  return t;
}

function unit(shape: string, elev: string, busy: 'busy' | 'idle' | undefined, name: string, note: string, active: boolean): HTMLElement {
  const row = document.createElement('span');
  row.className = 'unit';
  const icon = document.createElement('span');
  icon.className = 'unit-icon';
  icon.append(tile(shape, elev, busy));
  const text = document.createElement('span');
  const n = document.createElement('span');
  n.className = 'unit-name';
  n.textContent = name;
  const s = document.createElement('span');
  s.className = 'unit-note';
  s.textContent = note;
  if (active) s.dataset['active'] = 'true';
  text.append(n, s);
  row.append(icon, text);
  return row;
}

export interface IslandHandles {
  readonly root: HTMLElement;
  render(perception: PerceptionView | null, devices: readonly DeviceRow[], open: boolean): void;
  /** 展开后与左边卡片区顶对齐、等高。 */
  setHeight(px: number): void;
}

export function createIsland(onToggle: () => void): IslandHandles {
  const island = document.createElement('button');
  island.className = 'island';
  island.type = 'button';
  island.setAttribute('aria-label', '感知与设备');

  const mini = document.createElement('span');
  mini.className = 'island-view island-mini';
  const miniPer = document.createElement('span');
  miniPer.className = 'mini-group';
  const miniDev = document.createElement('span');
  miniDev.className = 'mini-group';
  mini.append(miniPer, miniDev);

  const full = document.createElement('span');
  full.className = 'island-view island-full';
  const perKey = document.createElement('span');
  perKey.className = 'sec-key';
  const perCount = document.createElement('b');
  perKey.append(document.createTextNode('感知'), perCount);
  const perGrid = document.createElement('span');
  perGrid.className = 'per-grid';
  const devKey = document.createElement('span');
  devKey.className = 'sec-key dev-key';
  const devCount = document.createElement('b');
  devKey.append(document.createTextNode('设备'), devCount);
  const devList = document.createElement('span');
  devList.className = 'dev-list';
  full.append(perKey, perGrid, devKey, devList);

  island.append(mini, full);

  // 展开之后点它任何一处都收回去。挡住内部点击的话就永远关不上 ——
  // 因为展开态整个内部就是那一层。
  island.addEventListener('click', onToggle);

  function render(
    perception: PerceptionView | null,
    devices: readonly DeviceRow[],
    open: boolean,
  ): void {
    island.dataset['open'] = String(open);
    island.setAttribute('aria-expanded', String(open));

    miniPer.replaceChildren();
    miniDev.replaceChildren();
    perGrid.replaceChildren();
    devList.replaceChildren();

    // 感知恒定四条。**缺的那条以 unavailable 出现,不是从队列里消失** ——
    // 遍历一个长度会变的数组,就永远画不出「这一侧没有」。
    const modalities = perception?.modalities ?? [];
    for (const m of modalities) {
      const shape = MODALITY_SHAPE[m.modality] ?? 't-sys';
      const elev = ELEVATION[m.state] ?? 'up';
      const busy = m.state === 'live' ? ('busy' as const) : undefined;
      miniPer.append(tile(shape, elev, busy));
      perGrid.append(
        unit(shape, elev, busy, MODALITY_LABEL[m.modality] ?? m.modality, modalityNote(m), m.state === 'live'),
      );
    }
    const live = modalities.filter((m) => m.state === 'live').length;
    perCount.textContent = modalities.length ? `${live} / ${modalities.length} 在收` : '未接';

    for (const d of devices) {
      const shape = `t-dev${d.role === 'controller' ? ' wide' : d.role === 'wearable' ? ' tiny' : ''}`;
      const elev = DEVICE_ELEVATION[d.state];
      const busy = d.state === 'offline' ? undefined : d.load === 'busy' ? ('busy' as const) : ('idle' as const);
      miniDev.append(tile(shape, elev, busy));
      const note =
        d.state === 'offline'
          ? d.lastSeenS === null
            ? '离线 · 从没连上过'
            : `离线 · 上次 ${formatAgo(d.lastSeenS)}`
          : d.doing || '空闲';
      devList.append(unit(shape, elev, busy, d.name, note, d.load === 'busy'));
    }
    const online = devices.filter((d) => d.state !== 'offline').length;
    devCount.textContent = devices.length ? `${online} / ${devices.length} 在线` : '未接';
  }

  function setHeight(px: number): void {
    if (px > 60) island.style.setProperty('--island-h', `${px}px`);
  }

  return { root: island, render, setHeight };
}

function formatAgo(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} 秒前`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} 分钟前`;
  if (seconds < 172800) return `${Math.round(seconds / 3600)} 小时前`;
  return `${Math.round(seconds / 86400)} 天前`;
}
