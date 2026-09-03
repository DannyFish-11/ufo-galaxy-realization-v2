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
import type { DeviceRow, ModalityState, ModalityView, PerceptionView, TierView } from '../types';

/** 状态 → 离墙多远。五档,不是布尔 —— 「闭着」和「没有」是两件事。 */
const ELEVATION: Record<ModalityState, string> = {
  live: 'up',
  idle: 'up',
  suppressed: 'shut',   // 它在说话,这一拍不听自己
  paused: 'paused',     // 你按了隐私暂停
  unavailable: 'sunk',  // 这条通路从没来过东西
};

const DEVICE_ELEVATION = { online: 'up', degraded: 'low', offline: 'sunk' } as const;

/**
 * 收起态那颗药丸只有 186px:感知恒定四格吃掉一半,剩下的宽度按 v18 的排法
 * 装得下四格设备。设备数会长(七台、十台都可能),不设上限就会顶穿右边缘。
 *
 * 截断了**必须留痕**:留痕那一小格自己也占宽,所以一旦要留痕就只画三格。
 * 谁被留下按状态排:在线 > 降级 > 离线 —— 余光里该看见的是「还有谁醒着」。
 */
const MINI_DEVICES = 4;
const MINI_DEVICES_TRUNCATED = 3;

const DEVICE_ORDER: Record<DeviceRow['state'], number> = { online: 0, degraded: 1, offline: 2 };

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
  render(
    perception: PerceptionView | null,
    devices: readonly DeviceRow[],
    tiers: TierView | null,
    open: boolean,
  ): void;
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

  // 展开态最下面一行:此刻在跑哪一档、哪两个型号。**只读。**
  //
  // 换档在设置浮层那边(那里能看见一共有几档、哪几档这台机器跑不动)。这里只
  // 回答「现在是什么」—— 岛是状态面,不是控制面;把换档也塞进来的话,人会在
  // 余光里误触一次代价很大的操作(驱逐旧模型、拉新模型、热刷 LLM 路由)。
  const brainKey = document.createElement('span');
  brainKey.className = 'sec-key brain-key';
  brainKey.append(document.createTextNode('本机模型'));
  const brainLine = document.createElement('span');
  brainLine.className = 'brain-line';
  full.append(perKey, perGrid, devKey, devList, brainKey, brainLine);

  island.append(mini, full);

  // 展开之后点它任何一处都收回去。挡住内部点击的话就永远关不上 ——
  // 因为展开态整个内部就是那一层。
  //
  // stopPropagation 是必须的:document 上那个「点别处收起」的监听器会收到
  // 同一次冒泡上来的 click,于是刚展开就被自己关掉 —— 看起来是「点了没反应」。
  island.addEventListener('click', (e) => {
    e.stopPropagation();
    onToggle();
  });

  function render(
    perception: PerceptionView | null,
    devices: readonly DeviceRow[],
    tiers: TierView | null,
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
    // 「四条都没在收」和「这条链路压根没建起来」是两件事。
    //
    // 后端如实报着 perception.source = 'unwired',而这行字原先只按数量算,
    // 于是两种情形写出来一模一样是 `0 / 4 在收` —— 看着像此刻恰好安静,其实是
    // 桌面壳一帧都没推过。契约特地分了这两个值,面板不能在最后一步把它抹平。
    const wired = perception !== null && perception.source === 'live';
    perCount.textContent = !modalities.length
      ? '未接'
      : wired
        ? `${live} / ${modalities.length} 在收`
        : `${modalities.length} 条 · 还没接上`;
    perKey.dataset['unwired'] = String(modalities.length > 0 && !wired);

    // 收起态只装得下几格,展开态一个不少。
    const truncated = devices.length > MINI_DEVICES;
    const miniCap = truncated ? MINI_DEVICES_TRUNCATED : MINI_DEVICES;
    const miniPick = devices
      .map((d, i) => ({ d, i }))
      .sort((a, b) => DEVICE_ORDER[a.d.state] - DEVICE_ORDER[b.d.state] || a.i - b.i)
      .slice(0, miniCap)
      .sort((a, b) => a.i - b.i)
      .map(({ i }) => i);
    const inMini = new Set(miniPick);

    for (const [i, d] of devices.entries()) {
      const shape = `t-dev${d.role === 'controller' ? ' wide' : d.role === 'wearable' ? ' tiny' : ''}`;
      const elev = DEVICE_ELEVATION[d.state];
      // load 有三种:忙、闲、**不知道**(null)。不知道就不给光 ——
      // 那道光是「这台机器此刻在动」的断言,后端没说过的话不能替它说。
      // 原先把 null 归进 idle,于是一台从没报过忙闲的机器,在岛上也每 7.5 秒
      // 亮一次,看着就像连上了、正闲着。
      const busy =
        d.state === 'offline' || d.load === null
          ? undefined
          : d.load === 'busy'
            ? ('busy' as const)
            : ('idle' as const);
      if (inMini.has(i)) miniDev.append(tile(shape, elev, busy));
      const note =
        d.state === 'offline'
          ? d.lastSeenS === null
            ? '离线 · 从没连上过'
            : `离线 · 上次 ${formatAgo(d.lastSeenS)}`
          : d.doing
            ? d.doing
            : d.load === null
              ? // 「在线」和「降级」是两档,写出来也得是两句 —— 一台降级的机器
                // 顶着「在线」两个字,那格沉下去的深度就白做了。
                `${d.state === 'degraded' ? '降级' : '在线'} · ${
                  d.lastSeenS === null ? '没报过在忙什么' : `${formatAgo(d.lastSeenS)}有心跳`
                }`
              : '空闲';
      devList.append(unit(shape, elev, busy, d.name, note, d.load === 'busy'));
    }
    if (truncated) {
      const more = document.createElement('span');
      more.className = 'mini-more';
      more.setAttribute('aria-hidden', 'true');
      miniDev.append(more);
    }
    const online = devices.filter((d) => d.state !== 'offline').length;
    devCount.textContent = devices.length ? `${online} / ${devices.length} 在线` : '未接';
    // 收起态截了几台,只有无障碍标签说得出口 —— 药丸上那一小格留痕是给眼睛的。
    island.setAttribute(
      'aria-label',
      devices.length ? `感知与设备 · ${online} / ${devices.length} 台在线` : '感知与设备',
    );

    // 本机模型那一行。**三种状态各写各的话**:
    //   null      —— 没拉到目录。不是「没有档位」,别写成空白。
    //   有 current —— 写出档位标签和两位实际在跑的型号。「C 档」三个字说不出
    //                在跑哪两个模型,而那才是人想确认的东西。
    //   current 空 —— 拉到了目录但一档都没选定。这也得说出来。
    if (tiers === null) {
      brainLine.textContent = '读不到档位';
      brainLine.dataset['unwired'] = 'true';
    } else {
      const cur = tiers.tiers.find((t) => t.key === tiers.current);
      const slots = tiers.slots.filter((s) => s.model).map((s) => `${s.role} ${s.model}`);
      brainLine.textContent = cur
        ? slots.length
          ? `${cur.key} 档 · ${slots.join(' + ')}`
          : `${cur.key} 档 · ${cur.label}`
        : tiers.current
          ? `${tiers.current} 档（目录里没有这一档）`
          : '还没选定档位';
      // 装不下也要说 —— 岛上写着「C 档」而这台机器跑不动 C,是最难查的那种误导。
      brainLine.dataset['unwired'] = String(!cur || cur.fit === 'no_gpu' || cur.fit === 'insufficient_vram');
      if (cur && cur.fit !== 'ok' && cur.fit !== 'unknown') {
        brainLine.textContent += ` · ${cur.fitReason}`;
      }
    }
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
