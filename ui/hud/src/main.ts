/**
 * 面板入口。
 *
 * 装配四块:左栏(卡片 + 那条线)、右上的岛、对话、底下那条。
 *
 * 一条贯穿全篇的规矩:**「此刻」只有一个权威 —— WS 的 `payload.render`。**
 * 同一份负载里还有 `payload.phase` 和 `payload.posture`,讲的是同一件事;
 * 这里一个都不读。同一个事实读两处,迟早出现两处不一致而没人发现,而那
 * 恰恰是最难查的一类毛病。
 */
import './styles/hud.css';

import { Store, VISIBLE_CARDS, clampStart, initialState } from './store';
import { PresenceSocket, streamChat, toPhase } from './transport';
import { WAKE_CANDIDATES, platform } from './platform';
import { createDeck } from './ui/deck';
import { createLine } from './ui/line';
import type { LineTrust } from './ui/line';
import { createIsland } from './ui/island';
import { createThread } from './ui/thread';
import { createDock } from './ui/dock';
import type { Bundle, DeviceRow, PerceptionView, RenderPosture, Turn } from './types';

/**
 * 后端在哪。
 *
 * 从 `<meta name="galaxy-base">` 读,不走构建工具的环境变量 —— 那样源码就
 * 焊在某个打包器上了。外壳(Electron / Tauri / 直接开网页)注入这一行即可,
 * 三者一视同仁。留空 = 同源。
 */
function backendBase(): string {
  const meta = document.querySelector('meta[name="galaxy-base"]');
  const v = meta?.getAttribute('content')?.trim();
  return v || location.origin;
}
const BASE = backendBase();

function mount(host: HTMLElement): void {
  const store = new Store(initialState);

  const shell = document.createElement('div');
  shell.className = 'shell';
  const panel = document.createElement('div');
  panel.className = 'panel';

  const deck = createDeck(store);
  const line = createLine();
  deck.root.append(line.root);

  const main = document.createElement('div');
  main.className = 'main';

  const island = createIsland(() =>
    store.patch({ islandOpen: !store.state.islandOpen }),
  );
  const thread = createThread();
  const dock = createDock({
    onSend: (text) => void send(text),
    onTogglePopover: (which) =>
      store.patch({ popover: store.state.popover === which ? null : which }),
    onToggleBundle: (key) =>
      store.patch({
        bundles: store.state.bundles.map((b) =>
          b.key === key ? { ...b, on: !b.on } : b,
        ),
      }),
  });

  main.append(island.root, thread.root, dock.root);
  panel.append(deck.root, main);
  shell.append(panel);
  host.replaceChildren(shell);

  // 点别处收起浮层与岛。放在捕获阶段之外 —— 各控件自己 stopPropagation。
  document.addEventListener('click', () => {
    if (store.state.popover || store.state.islandOpen) {
      store.patch({ popover: null, islandOpen: false });
    }
  });

  // ── 渲染:状态一变就重画。没有虚拟 DOM,也不需要 ────────────────────
  function render(): void {
    const s = store.state;
    panel.dataset['slim'] = String(s.slim);
    deck.render();
    line.update(s.phase, s.slim, lineTrust(s.posture));
    island.render(s.posture?.perception ?? null, s.devices, s.islandOpen);
    island.setHeight(deck.root.querySelector('.deck')?.clientHeight ?? 0);
    thread.render(s.turns, s.lockstep, s.lockstepReason);
    dock.render(s.bundles, s.popover);
  }

  store.subscribe(render);

  // ── 后端:实时那条 ───────────────────────────────────────────────
  const socket = new PresenceSocket(BASE, {
    onOpen: () => store.patch({ connected: true }),
    onClose: () => store.patch({ connected: false }),
    onPosture: ({ posture, missing }) => {
      store.patch({
        posture,
        postureDrift: missing,
        phase: toPhase(posture.lifecycle),
      });
      if (missing.length > 0) {
        // 后端少发字段是**契约漂移**,不是正常降级。喊出来,不要补默认值 ——
        // 补上之后面板会拿着假数据画图,看起来一切正常。
        console.warn('[hud] 渲染契约缺字段:', missing.join(', '));
      }
    },
    onTurn: (role, text, final) => appendTurn(role, text, final),
    onDevices: (rows) => store.patch({ devices: rows }),
  });
  socket.start();

  function appendTurn(role: 'user' | 'agent', text: string, final: boolean): void {
    const turns = store.state.turns.slice();
    const last = turns[turns.length - 1];
    if (last && last.role === role && last.streaming) {
      turns[turns.length - 1] = { ...last, text: last.text + text, streaming: !final };
    } else {
      turns.push({
        id: `${Date.now()}-${turns.length}`,
        role,
        text,
        pending: '',
        attachments: [],
        streaming: !final,
      });
    }
    store.patch({ turns });
  }

  async function send(text: string): Promise<void> {
    const turns = store.state.turns.slice();
    turns.push({
      id: `u-${Date.now()}`, role: 'user', text,
      pending: '', attachments: [], streaming: false,
    });
    turns.push({
      id: `a-${Date.now()}`, role: 'agent', text: '',
      pending: '', attachments: [], streaming: true,
    });
    store.patch({ turns, lockstep: 'off', lockstepReason: '' });

    const idx = turns.length - 1;
    const patchAgent = (fn: (t: Turn) => Turn): void => {
      const next = store.state.turns.slice();
      const cur = next[idx];
      if (!cur) return;
      next[idx] = fn(cur);
      store.patch({ turns: next });
    };

    await streamChat(
      BASE,
      { message: text },
      {
        onPhase: (phase) => store.patch({ phase }),
        onDelta: (chunk) => patchAgent((t) => ({ ...t, text: t.text + chunk })),
        // 作废已经流出去的内容:清空这一轮重来,不是往后追加。
        onReset: () => patchAgent((t) => ({ ...t, text: '', pending: '' })),
        onLockstep: (state, reason) =>
          store.patch({ lockstep: state, lockstepReason: reason }),
        onDone: () => patchAgent((t) => ({ ...t, streaming: false })),
        onError: (msg) => {
          console.warn('[hud] chat/stream:', msg);
          patchAgent((t) => ({ ...t, streaming: false }));
        },
      },
    );
  }

  // ── 唤醒键 ──────────────────────────────────────────────────────
  void platform()
    .registerWake(WAKE_CANDIDATES)
    .then((chord) => {
      // 注册"成功"不等于按得到 —— 键可能在到达本进程之前就被输入法 /
      // 远程桌面 / 开发者工具截走。所以把真正生效的那个显示出来,
      // 让人按一次确认,而不是对着一个失灵的键猜。
      console.info(
        chord
          ? `[hud] 唤醒键：${chord.label}`
          : '[hud] 没有可用的唤醒键（网页里本来就没有全局热键）',
      );
    });

  if (demoEnabled()) seedDemo(store);

  // 尺寸变了要重算:卡高、滑键、岛的等高。
  const ro = new ResizeObserver(() => render());
  ro.observe(shell);
  window.addEventListener('resize', render);

  render();
}

/**
 * 这条线现在算不算数 —— **唯一一处判定**。
 *
 * 契约里 `degraded` 与 `source` 各说一件事:前者是「本拍跑在降级模式」,后者是
 * 「这份姿态是实算的(continuum)还是按相位锚点兜的底(anchor_only)」。降级优先,
 * 因为它更重。姿态还没来的时候也算兜底 —— 那时候画的相位是初值,不是它的相位。
 *
 * 判定只写在这里。散在各处的话,迟早有一处忘了改,而那一处画出来的线会说谎。
 */
function lineTrust(posture: RenderPosture | null): LineTrust {
  if (posture === null) return 'anchor';
  if (posture.degraded) return 'degraded';
  return posture.source === 'continuum' ? 'live' : 'anchor';
}

/**
 * 演示数据。
 *
 * **默认不装。** 只有页面上写了 `<meta name="galaxy-demo" content="on">`
 * 才会灌进去 —— 悄悄塞一批假卡片,和「后端还没接上」在界面上就分不开了,
 * 而那正是这个仓库反复要躲的那类事。
 */
function seedDemo(store: Store): void {
  const titles = [
    '显存路由那三天', '', '把记忆接回一条线', '', '', '配对了手表',
    '锁步那件事', '', '第一次跨设备', '', '设置页重分类', '',
    '工作流那个重复键', '把卡片做成实体卡',
  ];
  const weights = [0.9, 0.4, 0.95, 0.2, null, 0.6, 0.75, 0.35, 0.7, 0.25, 0.55, 0.3, 0.45, 0.8];
  const pad = (n: number): string => String(n).padStart(2, '0');
  const cards = titles.map((t, i) => {
    const a = new Date(2026, 7, 14 - i * 3);
    const b = new Date(2026, 7, 16 - i * 3);
    const w = weights[i] ?? null;
    return {
      id: `card-${i}`,
      title: t ?? '',
      from: `${pad(a.getMonth() + 1)}.${pad(a.getDate())}`,
      to: `${pad(b.getMonth() + 1)}.${pad(b.getDate())}`,
      weight: w,
      turns: w === null ? 0 : Math.round(8 + w * 60),
      modalities: w === null ? [] : w > 0.6 ? ['文字', '屏幕', '声音'] : w > 0.3 ? ['文字', '声音'] : ['文字'],
      profile:
        w === null
          ? []
          : Array.from({ length: 14 }, (_, k) =>
              Math.max(0.12, Math.min(1, w * (0.55 + 0.65 * Math.abs(Math.sin(i * 2.7 + k * 1.1))))),
            ),
    };
  });

  // 感知恒定四条。这四档刻意各占一种 —— 让「闭着」和「没有」在演示里
  // 就分得开:摄像头是你按了暂停,系统声是这台机器根本没这条通路。
  const perception = {
    source: 'live',
    is_sensing: true,
    privacy_paused: false,
    ambient_action: 'none',
    ambient_rationale: '',
    modalities: [
      { modality: 'screen', state: 'live', signal_age_s: 0.4 },
      { modality: 'camera', state: 'paused', signal_age_s: null },
      { modality: 'microphone', state: 'suppressed', signal_age_s: 1.2 },
      { modality: 'system_audio', state: 'unavailable', signal_age_s: null },
    ],
  } as unknown as PerceptionView;

  const devices: DeviceRow[] = [
    { id: 'local', name: '本机 · 台式', role: 'controller', state: 'online',
      load: 'busy', doing: '在跑：整理三天的记录', lastSeenS: 0 },
    { id: 'phone', name: '手机', role: 'participant', state: 'online',
      load: 'idle', doing: '', lastSeenS: 3 },
    { id: 'watch', name: '手表', role: 'wearable', state: 'degraded',
      load: 'idle', doing: '信号弱，心跳慢了', lastSeenS: 41 },
    { id: 'pad', name: '平板', role: 'participant', state: 'offline',
      load: null, doing: '', lastSeenS: 7200 },
    { id: 'brain', name: '书房 · 主脑', role: 'controller', state: 'online',
      load: 'busy', doing: '在跑：向量库重建', lastSeenS: 1 },
    { id: 'speaker', name: '客厅音箱', role: 'wearable', state: 'online',
      load: 'idle', doing: '', lastSeenS: 12 },
    { id: 'old', name: '旧笔记本', role: 'participant', state: 'offline',
      load: null, doing: '', lastSeenS: 518400 },
  ];

  const turns: Turn[] = [
    {
      id: 'demo-u', role: 'user',
      text: '把上周那份显存路由的结论整理一下，我要拿去汇报。',
      pending: '', attachments: [], streaming: false,
    },
    {
      id: 'demo-a', role: 'agent',
      text: '那份结论落在八月中旬那张卡片里。核心是三条：本地档位按显存分级、',
      // 还没被念出来、因此还没上屏的那一截 —— 锁步就长这样
      pending: '草稿位只在实测过倍数之后才开、云端只在本地明确不够时接手。',
      attachments: [
        { kind: 'image', name: '显存分级曲线.png', note: '那三天里你截给我的' },
      ],
      streaming: true,
    },
  ];

  const bundles: Bundle[] = [
    { key: 'omnimodal', name: '全模态', note: '屏 摄 麦 系统声', on: true, keyCount: 20, overrides: 1 },
    { key: 'crossDevice', name: '跨设备', note: '发现 配对 主脑 手机 手表', on: true, keyCount: 36, overrides: 0 },
    { key: 'voice', name: '声音', note: '跟文字锁步', on: true, keyCount: 63, overrides: 0 },
    { key: 'autonomy', name: '自主', note: '问过再做', on: false, keyCount: 58, overrides: 0 },
  ];

  store.patch({
    cards, bundles, devices, turns,
    posture: { perception } as unknown as RenderPosture,
    phase: 'liminal',
    start: clampStart(0, cards.length),
    drawn: 0,
  });
}

function demoEnabled(): boolean {
  return (
    document
      .querySelector('meta[name="galaxy-demo"]')
      ?.getAttribute('content')
      ?.trim() === 'on'
  );
}

const host = document.getElementById('hud');
if (host) mount(host);

export { mount, seedDemo, demoEnabled, VISIBLE_CARDS };
