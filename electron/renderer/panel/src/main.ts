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
import {
  PresenceSocket,
  fetchAllConfig,
  fetchBundles,
  fetchCardTurns,
  fetchCards,
  fetchHistory,
  fetchTiers,
  nextBundleValue,
  saveConfig,
  ingestFiles,
  setBundle,
  setPrivacy,
  setTier,
  streamChat,
  toPhase,
} from './transport';
import { WAKE_CANDIDATES, platform } from './platform';
import { createDeck } from './ui/deck';
import { createLine } from './ui/line';
import type { LineTrust } from './ui/line';
import { createIsland } from './ui/island';
import { createThread } from './ui/thread';
import { createDock } from './ui/dock';
import { createSettings } from './ui/settings';
import type { Bundle, DeviceRow, PerceptionView, RenderPosture, Turn } from './types';

/**
 * 后端在哪。
 *
 * 从 `<meta name="galaxy-base">` 读,不走构建工具的环境变量 —— 那样源码就
 * 焊在某个打包器上了。外壳(Electron / Tauri / 直接开网页)注入这一行即可,
 * 三者一视同仁。留空 = 同源。
 */
/**
 * 后端在哪。按这个顺序问:
 *
 * 1. **外壳给的** —— `window.galaxyShell.base`。Electron 的 preload 在页面脚本
 *    之前把它挂上去(见 electron/preload.js),所以这里同步就能拿到。地址本身
 *    只在 electron/main.js 推导一次,这边不重推。
 * 2. `<meta name="galaxy-base">` —— 在浏览器里开发时用。
 * 3. 同源。
 *
 * 第一条不能省:Electron 用 file:// 加载面板,那时 `location.origin` 是 `null`,
 * 「同源」没有任何意义 —— WebSocket 会去连一个不存在的东西然后一直退避重试,
 * 界面上只看得到「一直连不上」,看不出为什么。
 */
function backendBase(): string {
  const shell = (window as { galaxyShell?: { base?: string } }).galaxyShell;
  const fromShell = shell?.base?.trim();
  if (fromShell) return fromShell;

  const meta = document.querySelector('meta[name="galaxy-base"]');
  const fromMeta = meta?.getAttribute('content')?.trim();
  if (fromMeta) return fromMeta;

  // file:// 下 origin 是字符串 'null'。拿它当地址只会一直连不上,
  // 而且看不出原因 —— 说出来。
  if (location.origin === 'null' || location.protocol === 'file:') {
    console.error('[hud] 没有外壳提供后端地址,而页面是 file:// 打开的 —— 连不上后端');
    return '';
  }
  return location.origin;
}
const BASE = backendBase();

function mount(host: HTMLElement): void {
  const store = new Store(initialState);

  const shell = document.createElement('div');
  shell.className = 'shell';
  const panel = document.createElement('div');
  panel.className = 'panel';

  const deck = createDeck(store, (i) => void openCard(i));
  const line = createLine();
  deck.root.append(line.root);

  const main = document.createElement('div');
  main.className = 'main';

  const island = createIsland({
    onToggle: () => store.patch({ islandOpen: !store.state.islandOpen }),
    onPrivacy: (paused) => void flipPrivacy(paused),
  });
  const thread = createThread();
  const dock = createDock({
    onSend: (text) => void send(text),
    onFeed: (files) => void feedFiles(files),
    onTogglePopover: (which) =>
      store.patch({ popover: store.state.popover === which ? null : which }),
    onToggleBundle: (key) => void flipBundle(key),
    onOpenAllSettings: () => void openAllSettings(),
    onPickTier: (key) => void pickTier(key),
  });

  const settings = createSettings({
    onClose: () => store.patch({ settingsOpen: false }),
    onSave: (changes) => void applyConfig(changes),
  });

  main.append(island.root, thread.root, dock.root, settings.root);
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
    island.render(s.posture?.perception ?? null, s.devices, s.tiers, s.privacyBusy, s.islandOpen);
    island.setHeight(deck.root.querySelector('.deck')?.clientHeight ?? 0);
    thread.render(s.turns, s.lockstep, s.lockstepReason);
    dock.render(s.bundles, s.tiers, s.tierGaps, s.popover);
    settings.render(s.config, s.settingsOpen, s.configBusy);
  }

  store.subscribe(render);

  /**
   * 翻一档。**先问后端,再改界面。**
   *
   * 不做乐观更新:写失败时界面会停在一个后端并不认同的状态上,而那正是
   * 「看起来接上了,其实没有」最常见的形态。后端返回什么,界面就是什么。
   */
  async function flipBundle(key: string): Promise<void> {
    const current = store.state.bundles.find((b) => b.key === key);
    if (!current) return;
    const next = nextBundleValue(current);
    if (next === null) {
      // 主键不存在,或类型认不出来 —— 点了没反应是**对的**,但要说出为什么。
      console.error(`[hud] 档位「${current.name}」没有接上任何东西(主键 ${current.primary || '未知'})`);
      return;
    }
    const updated = await setBundle(BASE, key, next);
    if (!updated) return; // 失败原因已由 setBundle 打出来;界面保持不动
    store.patch({
      bundles: store.state.bundles.map((b) => (b.key === key ? updated : b)),
    });
  }

  /**
   * 打开全部设置。**每次打开都重新拉** —— 配置可能被别处改过(命令行、.env、
   * 另一台设备),拿缓存显示会让人对着一份过期的值做决定。
   */
  async function openAllSettings(): Promise<void> {
    store.patch({ settingsOpen: true, popover: null, configBusy: true });
    const items = await fetchAllConfig(BASE);
    store.patch({ config: items, configBusy: false });
  }

  /**
   * 写回一批改动。**成功之后重新拉一次,以后端为准。**
   *
   * 后端那条路是「先落盘、成功才应用到内存」,而且批次里有一个未知键就整批 400。
   * 不重新拉的话,界面显示的是我以为写进去的值,而后端可能一个都没收 ——
   * 那正是「看起来接上了,其实没有」。
   */
  async function applyConfig(changes: Readonly<Record<string, string>>): Promise<void> {
    store.patch({ configBusy: true });
    const ok = await saveConfig(BASE, changes);
    const items = await fetchAllConfig(BASE);
    store.patch({ config: items, configBusy: false });
    if (!ok) return;
    // 档位那几档也可能被这批改动波及(它们的主键就在这 332 个里),重新算一遍。
    await loadBundles();
  }

  /** 拉一次真实档位。拉不到就**保持空**,不拿演示数据顶上。 */
  async function loadBundles(): Promise<void> {
    const rows = await fetchBundles(BASE);
    if (rows) store.patch({ bundles: rows });
  }
  void loadBundles();

  /**
   * 换本机模型档位。**先问后端,再改界面** —— 同 flipBundle 那条理由,而且换档
   * 的失败面比翻开关大得多:要驱逐旧模型、拉新模型、热刷 LLM 路由。
   */
  async function pickTier(key: string): Promise<void> {
    const view = store.state.tiers;
    if (!view || key === view.current) return;
    store.patch({ tierGaps: [] });
    const { ok, gaps } = await setTier(BASE, key);
    if (!ok) return; // 失败原因已由 setTier 打出来;界面保持在原来那一档
    // 换完重新拉:后端可能没给到我请求的那一档(档位被别处钉死、资源对齐失败),
    // 以它认下的为准。缺依赖照原样带上 —— 只写日志等于没说。
    await loadTiers();
    store.patch({ tierGaps: gaps });
  }

  // ── 会话 · 历史 · 记忆卡片 · 喂东西 · 隐私 ─────────────────────────

  /** 上次那条会话记在哪。换机器/清缓存就没了 —— 那时从空白开始是对的。 */
  const SESSION_KEY = 'galaxy.session_id';

  function rememberSession(sid: string): void {
    try {
      window.localStorage.setItem(SESSION_KEY, sid);
    } catch {
      // 隐私模式 / 站点数据被禁 —— 记不住只是下次要重新开一条,不该炸。
    }
  }

  function recallSession(): string {
    try {
      return window.localStorage.getItem(SESSION_KEY) ?? '';
    } catch {
      return '';
    }
  }

  /**
   * 开面板时把上次那条对话读回来。
   *
   * 从前这里什么都没有:每次打开都是一屏空白,而后端明明记着。那不是「新对话」,
   * 是**看起来失忆**。
   *
   * 读不到时**保持空**并说明白 —— 拿演示数据顶上就等于伪造记忆。
   */
  async function restoreSession(): Promise<void> {
    const sid = recallSession();
    if (!sid) return;
    const turns = await fetchHistory(BASE, sid);
    if (turns === null) {
      // 后端不认识这条 id(通常是它过期了)。**丢掉本地那条**,否则接下来每一次
      // 拉历史、拉卡片都会对着一个不存在的会话问,而且永远拿不到东西。
      console.warn('[hud] 后端不认识上次那条会话,重新开一条:', sid);
      try {
        window.localStorage.removeItem(SESSION_KEY);
      } catch {
        /* 同上 */
      }
      return;
    }
    store.patch({ sessionId: sid, turns });
    await loadCards();
  }

  /**
   * 抽出来一张卡 —— 把那几天的对话摆上来。
   *
   * **区间判断在后端**(与卡片列表同一套分桶)。面板拿 from/to 自己筛历史的话,
   * 两处对「这一天算前一张还是后一张」的理解迟早差一点,而差的那点表现出来是
   * 「点开这张卡少了两句」——没人会去查。
   *
   * `index < 0` = 卡片被推回去了,那就回到当前会话的对话。
   */
  async function openCard(index: number): Promise<void> {
    const sid = store.state.sessionId;
    if (!sid) return;
    if (index < 0) {
      const turns = await fetchHistory(BASE, sid);
      if (turns !== null) store.patch({ turns });
      return;
    }
    const card = (store.state.cards ?? [])[index];
    if (!card) return;

    const got = await fetchCardTurns(BASE, sid, card.id);
    if (got === null) {
      // 后端不认识这张卡(手上这份过期了),或者根本没接上。**说出来** ——
      // 静默保持原样的话,人会以为这张卡里就是当前这些对话。
      pushNotice(`打不开「${card.from} – ${card.to}」这张卡 —— 后端没接上，或这张卡已经过期`);
      return;
    }
    const head: Turn[] = [
      {
        id: `card-${card.id}`,
        role: 'agent',
        text: got.truncated
          ? `${card.from} – ${card.to} 这三天，共 ${got.total} 条，下面是最近的 ${got.turns.length} 条`
          : `${card.from} – ${card.to} 这三天，共 ${got.total} 条`,
        pending: '',
        attachments: [],
        streaming: false,
      },
    ];
    store.patch({ turns: [...head, ...got.turns] });
  }

  /**
   * 拉左栏那叠卡片。
   *
   * **「怎么切」不在这里** —— 三天这个粒度、边界锚在哪、weight 相对谁归一,
   * 全在后端 core/memory_cards.py 一处。面板照着切好的片画。
   */
  async function loadCards(): Promise<void> {
    const sid = store.state.sessionId;
    if (!sid) return;
    const cards = await fetchCards(BASE, sid);
    // null = 没拉到。**保持 null**,别塌成空数组 —— 空数组在界面上是「这条线
    // 上什么都没有」,而那是句谎话。
    if (cards !== null) {
      store.patch({ cards, start: clampStart(store.state.start, cards.length) });
    }
  }

  /**
   * 把挑中的文件喂进这条对话。
   *
   * 走 `/api/v1/sessions/ingest_turns`,也就是**正常说话走的同一条记忆门**
   * (会话历史 + 工作记忆 + 对话记忆 + 统一语义记忆一次写齐),不是面板另存
   * 一份自己的清单。
   */
  async function feedFiles(files: readonly File[]): Promise<void> {
    const sid = store.state.sessionId;
    if (!sid) {
      // 还没有会话就没有地方可挂。**说出来** —— 静默丢掉正是这个按钮原来的毛病。
      console.warn('[hud] 还没开始对话,先说一句再喂文件');
      pushNotice('还没开始对话 —— 先说一句,再把文件喂进来');
      return;
    }
    store.patch({ popover: null });

    const readable: { name: string; text: string }[] = [];
    const unreadable: string[] = [];
    for (const f of files) {
      try {
        // 只读得动文本。二进制在这条路上没有意义 —— 补录端点收的是**对话轮次**,
        // 不是附件存储。图片那条要走多模态注入,那是另一条路,还没接。
        const text = await f.text();
        if (text.trim()) readable.push({ name: f.name, text });
        else unreadable.push(f.name);
      } catch {
        unreadable.push(f.name);
      }
    }
    if (unreadable.length) {
      // 读不动的**要说**,不能混在「成功」里 —— 用户会以为整批都进去了。
      pushNotice(`这几个读不出文本，没有喂进去：${unreadable.join('、')}`);
    }
    if (!readable.length) return;

    const n = await ingestFiles(BASE, sid, readable);
    if (n === null) {
      pushNotice('文件没能喂进去 —— 后端没接上或拒绝了这一批');
      return;
    }
    // **先把历史读回来,再报数。** 反过来的话,那句提示刚挂上去就被整条历史
    // 覆盖掉了 —— 实测过一次:后端确实收下了文件,而界面上什么话都没说。
    const turns = await fetchHistory(BASE, sid);
    if (turns !== null) store.patch({ turns });
    // 以后端**实际录进去的条数**为准。前端按选中数量报数的话,后端拒掉几条
    // 就没人知道了。
    pushNotice(n === readable.length ? `喂进去 ${n} 个文件` : `${readable.length} 个里后端只收下 ${n} 个`);
    await loadCards();
  }

  /** 把一句提示挂到对话流里。面板没有单独的提示条,而这些话不该只进控制台。 */
  function pushNotice(text: string): void {
    store.patch({
      turns: [
        ...store.state.turns,
        { id: `n-${Date.now()}`, role: 'agent', text, pending: '', attachments: [], streaming: false },
      ],
    });
  }

  /**
   * 按停 / 恢复桌面感知。
   *
   * **写完不在这里存结果。** 停没停的唯一权威是 posture 帧里的
   * `perception.privacy_paused`,下一帧(最快 0.4 秒)就会带着新状态回来,界面
   * 跟着它变。这里只管把按钮压住免得连点写两遍。
   *
   * 曾经这里 `store.patch({ privacyPaused: st.paused })` —— 那就是同一个事实
   * 两处各存:别处(托盘、命令行、另一台设备)按停之后帧里说停了,而面板这份
   * 副本还是旧的,按钮和它下面那四条通路当场自相矛盾。
   */
  async function flipPrivacy(paused: boolean): Promise<void> {
    store.patch({ privacyBusy: true });
    const ok = await setPrivacy(BASE, paused);
    store.patch({ privacyBusy: false });
    if (!ok) {
      pushNotice(paused ? '没能暂停感知 —— 后端没接上，它还在采' : '没能恢复感知 —— 后端没接上');
    }
  }

  void restoreSession();

  /** 拉一次档位目录。拉不到**保持 null**,浮层那一行会说「读不到」而不是空着。 */
  async function loadTiers(): Promise<void> {
    const view = await fetchTiers(BASE);
    if (view) store.patch({ tiers: view });
  }
  void loadTiers();

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
      // **带上会话 id。** 不带的话后端按它自己的默认会话收这一轮 —— 而面板
      // 刚刚从本地存的 id 把上一条对话读了回来。于是屏幕上显示的是 A 的历史、
      // 新说的话记进了 B,两边都「成功」,没有一处报错。空串时后端照旧自己开
      // 一条,并在 meta 帧里把 id 告诉我们。
      { message: text, session_id: store.state.sessionId },
      {
        onPhase: (phase) => store.patch({ phase }),
        // 后端说这轮记到哪条会话上了。**接住它** —— 历史、记忆卡片、喂文件
        // 全按它去问;面板自己编一个的话,问出来永远是空的。
        onSession: (sid) => {
          if (sid && sid !== store.state.sessionId) {
            store.patch({ sessionId: sid });
            rememberSession(sid);
          }
        },
        onDelta: (chunk) => patchAgent((t) => ({ ...t, text: t.text + chunk })),
        // 作废已经流出去的内容:清空这一轮重来,不是往后追加。
        onReset: () => patchAgent((t) => ({ ...t, text: '', pending: '' })),
        onLockstep: (state, reason) =>
          store.patch({ lockstep: state, lockstepReason: reason }),
        onDone: (response) => {
          // **一个 delta 都没来的时候,拿 done 里的 response 兜底。**
          //
          // 实测(对着真的 chat router):锁步是 `engaged` 而这台机器上没有可用的
          // 发声器时,文字要跟着语音走 —— 语音永远没来,于是一个 delta 都不发,
          // 整段答复只存在于 done 帧的 response 里。只认 delta 的话,答复就丢了,
          // 面板画出一个空气泡。而空气泡跟「它想了想没什么好说的」长得一模一样。
          //
          // 这不是给后端打补丁:done.response 本来就是后端在那一帧里明说的答复,
          // 读它是对的。同一次请求换成不走锁步(no_speaker)时,delta 正常发三条、
          // 内容与 response 一致,两条路对得上。
          //
          // 真的什么都没有时才说「什么都没拿到」—— 那句话必须留给真正空的那种。
          patchAgent((t) => ({
            ...t,
            streaming: false,
            text:
              t.text ||
              response ||
              '这一轮后端没有返回任何内容 —— 不是它没话说，是这条路上什么都没拿到',
          }));
          // 这一轮进了记忆,卡片就变了。**重新问后端**,不在前端自己给最新那张
          // 卡的计数加一 —— 切片的判断只有后端做得了(这一轮可能落进新的三天)。
          void loadCards();
        },
        onError: (msg) => {
          // 只写 console.warn 等于没说 —— 出错的那一轮在界面上照样是个空气泡。
          console.warn('[hud] chat/stream:', msg);
          patchAgent((t) => ({
            ...t,
            streaming: false,
            text: t.text ? `${t.text}\n\n（这一轮中断了：${msg}）` : `这一轮没能说完：${msg}`,
          }));
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

  // 演示用的四档。**形状与后端 /api/config/bundles 一致**,但值是编的 ——
  // 真实的一份由 fetchBundles() 拉,见 mount() 里那段。
  const bundles: Bundle[] = [
    { key: 'omnimodal', name: '全模态', note: '屏 摄 麦 系统声', primary: 'GALAXY_AMBIENT_LOOP',
      value: 'true', type: 'boolean', overrides: 1, unwired: false },
    { key: 'cross_device', name: '跨设备', note: '发现 配对 主脑 手机 手表', primary: 'GALAXY_CROSS_DEVICE_ENABLED',
      value: 'true', type: 'boolean', overrides: 0, unwired: false },
    { key: 'voice', name: '声音', note: '跟文字锁步', primary: 'GALAXY_SPEAK',
      value: 'true', type: 'boolean', overrides: 0, unwired: false },
    { key: 'autonomy', name: '自主', note: '问过再做', primary: 'GALAXY_AUTONOMY',
      value: 'guided', type: 'select', options: ['safe', 'guided', 'autonomous'],
      overrides: 0, unwired: false },
  ];;

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

/**
 * 挂载。**不能假设脚本跑的时候 body 已经在了。**
 *
 * 这个产物打成经典脚本(IIFE)是为了能在 file:// 下加载 —— Electron 用
 * loadFile() 打开它,而 `type="module"` 在 file:// 下会被 CORS 拦掉。代价是
 * 经典脚本**不像 module 那样默认 defer**:标签在 <head> 里就立刻执行,那一刻
 * `#hud` 还不存在,`getElementById` 返回 null,于是什么都不挂 —— 而且不报错。
 *
 * 构建时会给标签补 defer,但挂载这件事不该只靠「标签属性没被人改坏」。这里
 * 自己等一次 DOM。
 */
function boot(): void {
  const host = document.getElementById('hud');
  if (host) {
    mount(host);
    return;
  }
  console.error('[hud] 页面里没有 #hud,面板无处可挂');
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', boot, { once: true });
} else {
  boot();
}

export { mount, seedDemo, demoEnabled, VISIBLE_CARDS };
