/**
 * 跟后端的两条线。
 *
 * **此刻的状态一律走 WS 的 `payload.render`** —— 那是后端每帧算好的双轴
 * 渲染契约(core/phase_contract.py 的 RenderPosture),也是唯一的权威。
 *
 * 同一份负载里还有 `payload.phase`(压扁成三档的字符串)和 `payload.posture`
 * (一维遗留投影)。它们与 render 讲的是同一件事 —— **这里只读 render**,
 * 另外两个当不存在。同一个事实读两处,迟早会出现两处不一致而没人发现。
 */
import type { RenderPosture } from './types';
import type { Bundle, DeviceLoad, DeviceRow, DeviceState, LockstepReason, LockstepState, MemoryCard, ModelTier, Phase, TierView, Turn } from './types';

/** RenderPosture 该有的字段。少一个就是**契约漂移**,不是正常降级。 */
const POSTURE_FIELDS = [
  'lifecycle', 'previous_lifecycle', 'transition_kind', 'transition_seq',
  'last_transition', 'continuum_phase',
  'is_returning', 'next_phases', 'liminal_activity', 'simulation',
  'local_chain', 'cross_device_chain', 'world_model', 'perception',
  'hybrid_execution', 'acting', 'stop_key', 'pathway', 'thinking_locus', 'runtime_domain',
  'motion', 'intensity', 'form_signature', 'spatial_presence', 'texture_hint',
  'presence_intensity', 'coherence', 'ambiguity', 'collapse_tendency',
  'retreat_tendency', 'stability', 'source', 'degraded', 'degrade_reason',
] as const;

export interface PostureFrame {
  readonly posture: RenderPosture;
  /** 这一帧缺了哪些字段。空 = 完整 */
  readonly missing: readonly string[];
}

/** 主轴 → 展示词汇。后端线上传 static,面板上叫 silent。 */
export function toPhase(lifecycle: string): Phase {
  if (lifecycle === 'manifest') return 'manifest';
  if (lifecycle === 'liminal') return 'liminal';
  return 'silent';
}

function readPosture(raw: unknown): PostureFrame | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const missing = POSTURE_FIELDS.filter((f) => !(f in o));
  // 缺字段照样往上送 —— 把漂移**暴露成事实**,而不是补上默认值让它看起来正常。
  // 补默认值的话面板会拿着假数据画图,而那正是最难查的一类毛病。
  return { posture: o as unknown as RenderPosture, missing };
}

export interface PresenceHandlers {
  onOpen?(): void;
  onClose?(): void;
  onPosture?(frame: PostureFrame): void;
  onTurn?(role: 'user' | 'agent', text: string, final: boolean): void;
  /** 设备清单变了。来自 WS 的 `panel_feed` 帧。 */
  onDevices?(rows: readonly DeviceRow[]): void;
}

/**
 * `/ws/desktop-presence` 的连接。断了自己退避重连。
 *
 * 退避是**有上限的指数**:断线时不该把后端打穿,也不该久到人以为它死了。
 *
 * `clientId` 是这个面板实例的身份(每次打开随机生成一个)。它自己发起的那一轮,
 * 后端也会同步推到这条通道上给**别的**界面看 —— 而这里已经从 /chat/stream 的 SSE
 * 拿到了同样的字。认出自己的回声、不画第二遍,见 `#dispatch`。
 */
export class PresenceSocket {
  #url: string;
  #h: PresenceHandlers;
  #clientId: string;
  #sock: WebSocket | null = null;
  #retry = 0;
  #timer = 0;
  #stopped = false;

  constructor(base: string, handlers: PresenceHandlers, clientId = '') {
    this.#url = base.replace(/^http/, 'ws') + '/ws/desktop-presence';
    this.#h = handlers;
    this.#clientId = clientId;
  }

  start(): void {
    this.#stopped = false;
    this.#open();
  }

  stop(): void {
    this.#stopped = true;
    window.clearTimeout(this.#timer);
    this.#sock?.close();
    this.#sock = null;
  }

  #open(): void {
    if (this.#stopped) return;
    let sock: WebSocket;
    try {
      sock = new WebSocket(this.#url);
    } catch {
      this.#scheduleRetry();
      return;
    }
    this.#sock = sock;

    sock.addEventListener('open', () => {
      this.#retry = 0;
      this.#h.onOpen?.();
    });

    sock.addEventListener('close', () => {
      this.#h.onClose?.();
      this.#scheduleRetry();
    });

    sock.addEventListener('error', () => sock.close());

    sock.addEventListener('message', (ev) => {
      let msg: unknown;
      try {
        msg = JSON.parse(String(ev.data));
      } catch {
        return; // 收到不是 JSON 的东西 —— 丢掉,不猜
      }
      this.#dispatch(msg);
    });
  }

  #dispatch(msg: unknown): void {
    if (!msg || typeof msg !== 'object') return;
    const m = msg as Record<string, unknown>;
    const payload = (m['payload'] ?? {}) as Record<string, unknown>;

    if (m['type'] === 'state_event') {
      const frame = readPosture(payload['render']);
      if (frame) this.#h.onPosture?.(frame);
      return;
    }
    if (m['type'] === 'panel_feed') {
      const rows = readDevices(m['feed']);
      if (rows) this.#h.onDevices?.(rows);
      return;
    }
    if (m['type'] === 'conversation') {
      // 自己发起的那一轮的回声:字已经从 SSE 画过了,再画一遍就是同一句话两个气泡。
      if (this.#clientId && payload['client_id'] === this.#clientId) return;
      const role = payload['role'] === 'user' ? 'user' : 'agent';
      this.#h.onTurn?.(role, String(payload['text'] ?? ''), Boolean(payload['final']));
    }
  }

  #scheduleRetry(): void {
    if (this.#stopped) return;
    const wait = Math.min(8000, 400 * 2 ** this.#retry);
    this.#retry += 1;
    window.clearTimeout(this.#timer);
    this.#timer = window.setTimeout(() => this.#open(), wait);
  }
}

export interface ChatHandlers {
  /**
   * 后端认下的会话 id。**必须接住** —— 历史、记忆卡片、补录都按它去问,
   * 面板自己编一个的话,问出来的永远是空的。
   */
  onSession?(sessionId: string): void;
  onDelta?(text: string): void;
  /** 作废已经流出去的内容。收到它就把这一轮清空重来。 */
  onReset?(): void;
  onLockstep?(state: LockstepState, reason: LockstepReason): void;
  /**
   * 这一轮说完了。``response`` 是后端在 done 帧里给的**完整答复**。
   *
   * 为什么需要它:锁步 `engaged` 时文字是跟着语音一句句放出来的,而这台机器上
   * 没有可用的发声器时,实测**一个 delta 都不会发** —— 整段答复只存在于 done
   * 帧的 response 里。只认 delta 的客户端会把整轮答复丢掉,画出一个空气泡。
   *
   * 所以 done 里的 response 不是"冗余的重复",是这条路上唯一到得了的那一份。
   *
   * ``stopped`` = 这一轮是被人叫停的(/api/v1/presence/stop)。那时回复本来就是空的,
   * 得说「停下了」,不能说成「后端什么都没给」—— 两件事的下一步完全不同。
   */
  onDone?(response: string, stopped: boolean): void;
  onError?(message: string): void;
}

/**
 * `POST /api/v1/chat/stream` 的 SSE。
 *
 * 用 fetch 而不是 EventSource:EventSource 只能 GET,而这条要带请求体。
 * 七种帧 —— phase / delta / reset / meta / lockstep / done / error。
 *
 * **phase 帧不读。** 此刻在哪一相,唯一权威是 WS 的 `payload.render`(见文件头)。
 * 这里曾经把 SSE 的 phase 也写进同一个状态位 —— 两路各有各的时序,于是那条线
 * 和岛会在两个相位之间来回跳一下,而且只在面板自己发起的那几轮里跳。
 */
export async function streamChat(
  base: string,
  body: Record<string, unknown>,
  h: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(base + '/api/v1/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  if (!resp.ok || !resp.body) {
    h.onError?.(`chat/stream ${resp.status}`);
    return;
  }

  const reader = resp.body.getReader();
  const dec = new TextDecoder();
  let buf = '';

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });

    // SSE 以空行分帧。最后一段可能不完整,留在缓冲里等下一块。
    let cut: number;
    while ((cut = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, cut);
      buf = buf.slice(cut + 2);
      const line = chunk.split('\n').find((l) => l.startsWith('data:'));
      if (!line) continue;
      let ev: Record<string, unknown>;
      try {
        ev = JSON.parse(line.slice(5).trim()) as Record<string, unknown>;
      } catch {
        continue;
      }
      switch (ev['type']) {
        case 'phase':
          break; // 见函数头:相位只认 WS 的 render
        case 'delta':
          h.onDelta?.(String(ev['text'] ?? ''));
          break;
        case 'reset':
          h.onReset?.();
          break;
        case 'lockstep':
          h.onLockstep?.(
            ev['state'] as LockstepState,
            (ev['reason'] ?? '') as LockstepReason,
          );
          break;
        case 'done':
          h.onDone?.(typeof ev['response'] === 'string' ? ev['response'] : '', ev['stopped'] === true);
          break;
        case 'error':
          h.onError?.(String(ev['error'] ?? ''));
          break;
        case 'meta': {
          // 后端在这里说「这轮记到哪条会话上了」。conversation_session_id 优先:
          // runtime_session_id 是这一次运行的 id,不是记忆挂靠的那条线。
          const sid = ev['session_id'];
          if (typeof sid === 'string' && sid) h.onSession?.(sid);
          break;
        }
        default:
          break; // 认不出来的帧:忽略,但不当成错误
      }
    }
  }
}

/** 后端 `topology_nodes[].status` → 面板的三档。认不出来的当离线,不当在线。 */
const DEVICE_STATE: Record<string, DeviceState> = {
  online: 'online',
  degraded: 'degraded',
  offline: 'offline',
};

/**
 * `panel_feed.topology_nodes` → 岛上那份设备清单。
 *
 * **这份 feed 里没有「它在忙什么」这件事。** 节点上只有 `messageCount`(累计
 * 计数,不是速率),边上那个 `messageRate` 说的是链路不是设备。所以 `load` 一律
 * 给 null、`doing` 一律给空串 —— 类型上 null 本来就是「不知道」,跟 'idle'
 * (知道它闲着)是两件事。拿累计计数硬凑一个忙闲出来,岛上那道光就会替一台
 * 谁也没问过的机器说话。
 *
 * 后端哪天真送了忙闲,再从这里接上,不必改别处。
 */
export function readDevices(raw: unknown): readonly DeviceRow[] | null {
  if (!raw || typeof raw !== 'object') return null;
  const nodes = (raw as Record<string, unknown>)['topology_nodes'];
  if (!Array.isArray(nodes)) return null;
  const now = Date.now();
  const rows: DeviceRow[] = [];
  for (const n of nodes) {
    if (!n || typeof n !== 'object') continue;
    const o = n as Record<string, unknown>;
    const id = typeof o['id'] === 'string' ? o['id'] : '';
    if (!id) continue;
    const seenMs = typeof o['lastSeen'] === 'number' ? o['lastSeen'] : null;
    const load: DeviceLoad = null;
    rows.push({
      id,
      name: typeof o['label'] === 'string' && o['label'] ? o['label'] : id,
      role: typeof o['role'] === 'string' ? o['role'] : 'participant',
      state: DEVICE_STATE[String(o['status'])] ?? 'offline',
      load,
      doing: '',
      lastSeenS: seenMs === null ? null : Math.max(0, (now - seenMs) / 1000),
    });
  }
  return rows;
}


// ---------------------------------------------------------------------------
// 整档开关
// ---------------------------------------------------------------------------
//
// 「哪一档管哪些键、开合看哪个主键」的唯一定义处在后端
// (core/routes/config_schema_registry.py 的 CONFIG_BUNDLES)。这里只搬运。

function readBundle(raw: unknown): Bundle | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const key = typeof o['key'] === 'string' ? o['key'] : '';
  if (!key) return null;

  const unwired = o['unwired'] === true;
  const opts = Array.isArray(o['options'])
    ? (o['options'] as unknown[]).filter((v): v is string => typeof v === 'string')
    : undefined;

  return {
    key,
    name: typeof o['name'] === 'string' ? o['name'] : key,
    note: typeof o['note'] === 'string' ? o['note'] : '',
    primary: typeof o['primary'] === 'string' ? o['primary'] : '',
    // 主键不存在时后端不给 value —— 那时**不能补一个默认值**:补上之后界面就
    // 画出一个看着正常、其实什么都没接的开关。空串在渲染那侧被当成「没接上」。
    value: typeof o['value'] === 'string' ? o['value'] : '',
    type: typeof o['type'] === 'string' ? o['type'] : '',
    ...(opts && opts.length ? { options: opts } : {}),
    overrides: typeof o['overrides'] === 'number' ? o['overrides'] : 0,
    unwired,
  };
}

/** 拉一次档位。拉不到就返回 null —— **不返回空数组**:「没接上」和「一档都没有」是两件事。 */
export async function fetchBundles(base: string): Promise<readonly Bundle[] | null> {
  try {
    const resp = await fetch(base + '/api/config/bundles', { headers: { Accept: 'application/json' } });
    if (!resp.ok) {
      console.error('[hud] 拉档位失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as { bundles?: unknown };
    if (!Array.isArray(body.bundles)) return null;
    return body.bundles.map(readBundle).filter((b): b is Bundle => b !== null);
  } catch (err) {
    console.error('[hud] 拉档位失败:', err);
    return null;
  }
}

/**
 * 把一档设成某个值,返回后端**重新算过**的那一档。
 *
 * 刻意不在前端先乐观翻一下再对账:那样写失败时界面会停在一个后端并不认同的
 * 状态上,而这正是「看起来接上了,其实没有」最常见的形态。以后端返回的为准。
 */
export async function setBundle(
  base: string,
  key: string,
  value: string,
): Promise<Bundle | null> {
  try {
    const resp = await fetch(base + '/api/config/bundles', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, value }),
    });
    if (!resp.ok) {
      console.error('[hud] 改档位被拒:', resp.status, await resp.text().catch(() => ''));
      return null;
    }
    const body = (await resp.json()) as { bundle?: unknown };
    return readBundle(body.bundle);
  } catch (err) {
    console.error('[hud] 改档位失败:', err);
    return null;
  }
}

/** 这一档下一步该是什么值。布尔翻面;select 在自己的档位里循环。 */
export function nextBundleValue(b: Bundle): string | null {
  if (b.unwired || !b.type) return null;
  if (b.type === 'boolean') return b.value === 'true' ? 'false' : 'true';
  if (b.options && b.options.length > 0) {
    const i = b.options.indexOf(b.value);
    return b.options[(i + 1) % b.options.length] ?? b.options[0] ?? null;
  }
  return null;
}


// ---------------------------------------------------------------------------
// 全部设置 —— 332 个键的细调面
// ---------------------------------------------------------------------------
//
// 分组**不在这里定义**:每个键属于哪一类由后端 `/api/config/all` 的 `category`
// 现算,面板只按 `settings_inventory.ts` 里那份**顺序提示**排一下。这条区分是
// 这个仓库栽过一次的地方 —— 从前分组写在前端一份手写清单里,漏一个键的后果是
// 「它在设置页上完全看不见,后端却明明有它,还不报错」。

export interface ConfigItem {
  readonly key: string;
  /** 当前值。后端给的是字符串,原样搬 —— 不预先按 type 转,转错了看不出来。 */
  readonly value: string;
  readonly defaultValue: string;
  /** boolean / select / number / string / url / password … 决定画什么控件 */
  readonly type: string;
  readonly category: string;
  readonly description: string;
  readonly options?: readonly string[];
  /** 当前值偏离了默认。**这是留痕**,不是装饰。 */
  readonly overridden: boolean;
}

function readConfigItem(key: string, raw: unknown): ConfigItem | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const str = (k: string): string => (typeof o[k] === 'string' ? (o[k] as string) : String(o[k] ?? ''));
  const value = str('value');
  const defaultValue = str('default');
  const opts = Array.isArray(o['options'])
    ? (o['options'] as unknown[]).map((v) => String(v))
    : undefined;
  return {
    key,
    value,
    defaultValue,
    type: str('type') || 'string',
    // 后端没给 category 时归到 other 而不是丢掉 —— 丢掉就等于那个键在设置页上
    // 消失了,而它在后端明明存在。
    category: str('category') || 'other',
    description: str('description'),
    ...(opts && opts.length ? { options: opts } : {}),
    overridden: value !== defaultValue,
  };
}

/** 拉全部配置。拉不到返回 null —— **不返回空对象**:「没接上」与「一个键都没有」是两件事。 */
export async function fetchAllConfig(base: string): Promise<readonly ConfigItem[] | null> {
  try {
    const resp = await fetch(base + '/api/config/all', { headers: { Accept: 'application/json' } });
    if (!resp.ok) {
      console.error('[hud] 拉配置失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as Record<string, unknown>;
    const out: ConfigItem[] = [];
    for (const [k, v] of Object.entries(body)) {
      const item = readConfigItem(k, v);
      if (item) out.push(item);
    }
    return out;
  } catch (err) {
    console.error('[hud] 拉配置失败:', err);
    return null;
  }
}

/**
 * 写回若干个键。返回后端**认下来**的那些键,失败返回 null。
 *
 * 后端那条路是「先落盘、成功才应用到内存」,而且批次里有一个未知键就整批 400。
 * 所以这里不做乐观更新:写成功之后重新拉一次,以后端为准。
 */
export async function saveConfig(
  base: string,
  changes: Readonly<Record<string, string>>,
): Promise<boolean> {
  try {
    const resp = await fetch(base + '/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ config: changes }),
    });
    if (!resp.ok) {
      console.error('[hud] 保存配置被拒:', resp.status, await resp.text().catch(() => ''));
      return false;
    }
    return true;
  } catch (err) {
    console.error('[hud] 保存配置失败:', err);
    return false;
  }
}


// ---------------------------------------------------------------------------
// 本机模型档位 —— A/B/C/D
// ---------------------------------------------------------------------------
//
// 档位表的唯一定义处是 core/model_catalog.py 的 _TIERS。面板只渲染
// `GET /api/v1/models/catalog` 返回的东西,一个字都不自己存 —— 目录里加一档、
// 改一个型号,面板要立刻跟着变,而不是等人回来改前端。

function readTier(raw: unknown, fitMap: Record<string, unknown>): ModelTier | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const key = typeof o['key'] === 'string' ? o['key'] : '';
  if (!key) return null;

  const f = (fitMap[key] ?? {}) as Record<string, unknown>;
  const rawFit = typeof f['fit'] === 'string' ? f['fit'] : '';
  // 后端没给判断就是**没判断**。这里不补 'ok' —— 补了就是把「不知道」画成「能跑」。
  const fit: ModelTier['fit'] =
    rawFit === 'ok' || rawFit === 'no_gpu' || rawFit === 'insufficient_vram' ? rawFit : 'unknown';

  return {
    key,
    label: typeof o['label'] === 'string' ? o['label'] : key,
    desc: typeof o['desc'] === 'string' ? o['desc'] : '',
    kind: typeof o['kind'] === 'string' ? o['kind'] : '',
    activeTags: Array.isArray(o['active_tags'])
      ? (o['active_tags'] as unknown[]).filter((v): v is string => typeof v === 'string')
      : [],
    fit,
    fitReason: typeof f['reason'] === 'string' ? f['reason'] : fit === 'unknown' ? '硬件未探测到' : '',
    blockedBy: Array.isArray(f['blocked_by'])
      ? (f['blocked_by'] as unknown[]).filter((v): v is string => typeof v === 'string')
      : [],
  };
}

/** 拉一次档位目录。拉不到返回 null —— 与「一档都没有」是两件事。 */
export async function fetchTiers(base: string): Promise<TierView | null> {
  try {
    const resp = await fetch(base + '/api/v1/models/catalog', {
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) {
      console.error('[hud] 拉档位目录失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as Record<string, unknown>;
    if (!Array.isArray(body['tiers'])) return null;
    const fitMap = (body['tier_fit'] ?? {}) as Record<string, unknown>;
    const tiers = (body['tiers'] as unknown[])
      .map((t) => readTier(t, fitMap))
      .filter((t): t is ModelTier => t !== null);
    const current = typeof body['current_tier'] === 'string' ? body['current_tier'] : '';

    // 感知位/推理位从**当前那一档**的 slots 里取。取不到就是空数组 —— 岛内那行
    // 会说「未知」,而不是编一个型号名出来。
    const cur = (body['tiers'] as unknown[]).find(
      (t) => (t as Record<string, unknown>)?.['key'] === current,
    ) as Record<string, unknown> | undefined;
    const slots = Array.isArray(cur?.['slots'])
      ? (cur!['slots'] as unknown[])
          .map((s) => s as Record<string, unknown>)
          .map((s) => ({
            role: typeof s['role'] === 'string' ? s['role'] : '',
            model: typeof s['selected'] === 'string' ? s['selected'] : '',
          }))
          .filter((s) => s.role !== '')
      : [];

    return { current, tiers, slots };
  } catch (err) {
    console.error('[hud] 拉档位目录失败:', err);
    return null;
  }
}

/**
 * 换档。**不在前端先乐观切一下** —— 换档要驱逐旧模型、拉新模型,失败的可能性
 * 比翻一个开关大得多;先切了再对账的话,界面会停在一个后端并不认同的档位上。
 *
 * 返回 ``runtime_gaps``:后端算出来的「这一档缺什么依赖」。**必须画出来** ——
 * 只写日志等于没说,用户会以为换成了而其实那一档跑不起来。
 */
export async function setTier(
  base: string,
  key: string,
): Promise<{ ok: boolean; gaps: readonly string[] }> {
  try {
    const resp = await fetch(base + '/api/v1/models/tier', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tier: key }),
    });
    if (!resp.ok) {
      console.error('[hud] 换档被拒:', resp.status, await resp.text().catch(() => ''));
      return { ok: false, gaps: [] };
    }
    const body = (await resp.json()) as Record<string, unknown>;
    const gaps = Array.isArray(body['runtime_gaps'])
      ? (body['runtime_gaps'] as unknown[])
          .map((g) => (g as Record<string, unknown>)?.['detail'])
          .filter((d): d is string => typeof d === 'string')
      : [];
    return { ok: body['success'] === true, gaps };
  } catch (err) {
    console.error('[hud] 换档失败:', err);
    return { ok: false, gaps: [] };
  }
}


// ---------------------------------------------------------------------------
// 会话历史 —— 面板不该每次打开都从空白开始
// ---------------------------------------------------------------------------

/**
 * 把一条会话的历史读回来。
 *
 * 拉不到返回 null,**不返回空数组** —— 「后端没接上」和「这条会话确实没说过话」
 * 是两件事,画成一样的话,一次连不上的启动看起来就跟失忆一模一样。
 */
export async function fetchHistory(
  base: string,
  sessionId: string,
  maxTurns = 50,
): Promise<readonly Turn[] | null> {
  if (!sessionId) return null;
  try {
    const resp = await fetch(
      `${base}/api/v1/sessions/${encodeURIComponent(sessionId)}/history?max_turns=${maxTurns}`,
      { headers: { Accept: 'application/json' } },
    );
    if (!resp.ok) {
      // 404 = 后端不认识这条会话(通常是本地存的 id 过期了)。这不是错误,
      // 但也不是「没有历史」—— 交给调用方决定要不要重开一条。
      console.error('[hud] 拉历史失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as { success?: boolean; history?: unknown };
    if (body.success === false || !Array.isArray(body.history)) return null;
    return body.history
      .map((raw, i) => readHistoryTurn(raw, i))
      .filter((t): t is Turn => t !== null);
  } catch (err) {
    console.error('[hud] 拉历史失败:', err);
    return null;
  }
}

function readHistoryTurn(raw: unknown, i: number): Turn | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const text = typeof o['content'] === 'string' ? o['content'] : '';
  if (!text) return null;
  // 后端的角色是 user / assistant / system。system 不上屏 —— 它是给模型的,
  // 不是说给人听的;画出来会让人以为自己看漏了一段对话。
  const role = String(o['role'] ?? '');
  if (role === 'system') return null;
  const md = (o['metadata'] ?? {}) as Record<string, unknown>;
  const files = Array.isArray(md['ingested_files']) ? (md['ingested_files'] as unknown[]) : [];
  return {
    id: `h-${i}-${String(o['timestamp'] ?? '')}`,
    role: role === 'user' ? 'user' : 'agent',
    text,
    pending: '',
    attachments: files
      .filter((f): f is string => typeof f === 'string')
      .map((name) => ({ kind: 'file' as const, name, note: '' })),
    // 历史里的每一条都已经说完了 —— streaming 为真会让最后一条永远转圈。
    streaming: false,
  };
}


// ---------------------------------------------------------------------------
// 喂东西进去 —— 选中的文件要真的进对话与记忆
// ---------------------------------------------------------------------------

/**
 * 把用户挑的文件补录成对话轮次。
 *
 * `/api/v1/sessions/ingest_turns` 走的是 `record_session_turn` 那道统一记忆门
 * (会话历史 + 工作记忆 + 对话记忆 + 统一语义记忆一次写齐)。所以喂进去的东西
 * **和正常说话走的是同一条路** —— 不是另存一份面板自己的清单。
 *
 * 返回后端实际录进去了几条。`null` = 没接上。**「录了 0 条」和「没接上」要分开**:
 * 前者是文件被后端拒了(空内容、格式不认),后者是请求根本没到。
 */
export async function ingestFiles(
  base: string,
  sessionId: string,
  files: readonly { readonly name: string; readonly text: string }[],
): Promise<number | null> {
  if (!sessionId || !files.length) return null;
  try {
    const resp = await fetch(base + '/api/v1/sessions/ingest_turns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        turns: files.map((f) => ({
          role: 'user',
          content: f.text,
          ts: Date.now() / 1000,
          // 留痕:这条轮次是喂进来的文件,不是人打出来的。历史读回来时靠它
          // 还原成附件,而不是一整屏莫名其妙的正文。
          metadata: { source: 'panel_ingest', ingested_files: [f.name] },
        })),
      }),
    });
    if (!resp.ok) {
      console.error('[hud] 喂文件被拒:', resp.status, await resp.text().catch(() => ''));
      return null;
    }
    const body = (await resp.json()) as { success?: boolean; ingested?: unknown };
    if (body.success !== true) return null;
    return typeof body.ingested === 'number' ? body.ingested : 0;
  } catch (err) {
    console.error('[hud] 喂文件失败:', err);
    return null;
  }
}


// ---------------------------------------------------------------------------
// 隐私暂停 —— 一按就别看了
// ---------------------------------------------------------------------------

/**
 * 暂停 / 恢复桌面感知。返回**写成功了没有**,不返回状态。
 *
 * 闸门在后端的 DesktopPerceptionStore(唯一进出口),一按四个消费方同时失明,
 * 没有绕行路径。
 *
 * **这里不把新状态带回去。** 停没停的唯一权威是 posture 帧里的
 * `perception.privacy_paused`,每一帧都带着;写完等下一帧即可(最快 0.4 秒)。
 * 从这条路再回传一份,就是同一个事实两处各存 —— 别处按停之后两份会立刻打架。
 *
 * 曾经这里有一个 `fetchPrivacy()` 启动时问一次 HTTP。它和帧里那份是同一件事,
 * 而且只在启动那一刻对;删了。
 */
export async function setPrivacy(base: string, paused: boolean): Promise<boolean> {
  // **整条路径写全,不要拼。** 拼出来的路径在源码里只是两截字符串,
  // tests/test_api_surface_contract.py 那道「面板调的端点后端必须有」的门
  // 扫不出完整地址 —— 它会把前缀 `/api/perception/desktop` 当成一个端点,报成
  // 「后端没有这个端点」。门看不见的调用,等于这条路没有人守。
  const path = paused
    ? '/api/perception/desktop/privacy/pause'
    : '/api/perception/desktop/privacy/resume';
  try {
    const resp = await fetch(base + path + '?reason=panel', { method: 'POST' });
    if (!resp.ok) {
      console.error('[hud] 切隐私状态被拒:', resp.status);
      return false;
    }
    const body = (await resp.json()) as Record<string, unknown>;
    if (body['success'] !== true) return false;
    // 后端回了 200 却没说自己现在停没停 —— 那不算写成功。**不当作成功**:
    // 界面会因此不提示任何东西,而人以为按下去了。
    const st = (body['privacy'] ?? {}) as Record<string, unknown>;
    return typeof st['paused'] === 'boolean';
  } catch (err) {
    console.error('[hud] 切隐私状态失败:', err);
    return false;
  }
}


// ---------------------------------------------------------------------------
// 记忆卡片 —— 一条线折成的三天切片
// ---------------------------------------------------------------------------
//
// **「怎么切」不在这里。** 三天这个粒度、边界锚在哪、weight 相对谁归一,全部在
// 后端 core/memory_cards.py 一处。面板照着切好的片画,自己不做任何分段判断 ——
// 否则同一条线在这里切五张、在别的界面切六张,两边都以为自己是对的。

/**
 * 让它现在住手:取消在跑的请求、掐断在念的话、打断双工里正在说的那一句。
 *
 * 不是断开 SSE:断开只能停面板**自己**发起的那一轮,而它可能正因为一句语音在动你的
 * 鼠标键盘。后端把它停下之后,这一轮的 SSE 会照常收尾,done 帧带 `stopped: true`。
 *
 * 返回后端有没有接下这次「停」。没接下时调用方自己断开 SSE 兜底。
 */
export async function stopActivity(base: string, reason: string): Promise<boolean> {
  try {
    const resp = await fetch(
      `${base}/api/v1/presence/stop?reason=${encodeURIComponent(reason)}`,
      { method: 'POST' },
    );
    if (!resp.ok) {
      console.error('[hud] 停止被拒:', resp.status);
      return false;
    }
    const body = (await resp.json()) as Record<string, unknown>;
    return body['success'] === true;
  } catch (err) {
    console.error('[hud] 停止失败:', err);
    return false;
  }
}

/**
 * 当前对话主线是哪一条会话。
 *
 * 面板只是这份上下文的一个视图:语音、双工、它自己开口说的话都记在这一条上
 * (判据在后端 core/conversation_mainline.py,这里不另判)。所以打开面板时先问它,
 * 而不是只认本地记着的那一条 —— 面板关着的时候说过的话,全在主线上。
 *
 * `''` = 还没有任何真实对话;`null` = 没问到(后端没接上)。两者不能混:
 * 前者就该从空白开始,后者该退回本地记着的那一条。
 */
export async function fetchPrimarySession(base: string): Promise<string | null> {
  try {
    const resp = await fetch(`${base}/api/v1/sessions/primary`, {
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) return null;
    const body = (await resp.json()) as Record<string, unknown>;
    if (body['success'] !== true) return null;
    return typeof body['session_id'] === 'string' ? body['session_id'] : null;
  } catch (err) {
    console.error('[hud] 问对话主线失败:', err);
    return null;
  }
}

function readCard(raw: unknown): MemoryCard | null {
  if (!raw || typeof raw !== 'object') return null;
  const o = raw as Record<string, unknown>;
  const id = typeof o['id'] === 'string' ? o['id'] : '';
  if (!id) return null;
  return {
    id,
    title: typeof o['title'] === 'string' ? o['title'] : '',
    from: typeof o['from'] === 'string' ? o['from'] : '',
    to: typeof o['to'] === 'string' ? o['to'] : '',
    // **null 不能塌成 0。** 0 = 这三天确实什么都没发生;null = 这三天没有留下
    // 可读的记录。卡面上前者是空、后者是虚线空心,人看到的下一步完全不同。
    weight: typeof o['weight'] === 'number' ? o['weight'] : null,
    turns: typeof o['turns'] === 'number' ? o['turns'] : 0,
    modalities: Array.isArray(o['modalities'])
      ? (o['modalities'] as unknown[]).filter((m): m is string => typeof m === 'string')
      : [],
    profile: Array.isArray(o['profile'])
      ? (o['profile'] as unknown[]).filter((n): n is number => typeof n === 'number')
      : [],
  };
}

/** 拉这条线的卡片。null = 没接上或后端不认识这条会话,与「一张卡都没有」不同。 */
export async function fetchCards(
  base: string,
  sessionId: string,
): Promise<readonly MemoryCard[] | null> {
  if (!sessionId) return null;
  try {
    const resp = await fetch(
      base + '/api/v1/memory/cards?session_id=' + encodeURIComponent(sessionId),
      { headers: { Accept: 'application/json' } },
    );
    if (!resp.ok) {
      console.error('[hud] 拉记忆卡片失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as { known?: boolean; cards?: unknown };
    // 后端不认识这条会话时 known=false。**那不是「没有卡片」** —— 返回空数组
    // 会让面板画出一个干净的空态,人以为自己真的没聊过。
    if (body.known !== true || !Array.isArray(body.cards)) return null;
    return body.cards.map(readCard).filter((c): c is MemoryCard => c !== null);
  } catch (err) {
    console.error('[hud] 拉记忆卡片失败:', err);
    return null;
  }
}


/**
 * 抽出来那张卡那几天说了什么。
 *
 * **区间判断不在这里。** 面板拿到卡片之后自己按 from/to 去筛历史,等于在前端
 * 重做一遍切片 —— 两处对「这一天算前一张还是后一张」的理解迟早不一致,而不
 * 一致的表现是「点开这张卡少了两句」,没人会去查。所以问后端要,后端用与卡片
 * 列表**同一套分桶**取出来。
 *
 * `null` = 没接上。`found: false` = 这张卡后端不认识(面板手上那张过期了)——
 * 与「这几天确实没说话」是两件事,后者是 `found: true` 加一个空数组。
 */
export async function fetchCardTurns(
  base: string,
  sessionId: string,
  cardId: string,
): Promise<{ turns: readonly Turn[]; total: number; truncated: boolean } | null> {
  if (!sessionId || !cardId) return null;
  try {
    const resp = await fetch(
      `${base}/api/v1/memory/cards/${encodeURIComponent(cardId)}/turns` +
        `?session_id=${encodeURIComponent(sessionId)}`,
      { headers: { Accept: 'application/json' } },
    );
    if (!resp.ok) {
      console.error('[hud] 拉卡片内容失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as Record<string, unknown>;
    if (body['found'] !== true || !Array.isArray(body['turns'])) return null;
    return {
      turns: (body['turns'] as unknown[])
        .map((raw, i) => readHistoryTurn(raw, i))
        .filter((t): t is Turn => t !== null),
      total: typeof body['total'] === 'number' ? body['total'] : 0,
      truncated: body['truncated'] === true,
    };
  } catch (err) {
    console.error('[hud] 拉卡片内容失败:', err);
    return null;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 我的模型服务 —— 用户自己声明的端点
//
// 与上面那些「配置项」不同:这是一张**对象表**,不是扁平的键值。所以它不走
// /api/config,自己一条路。后端判据全在 core/user_providers.py,这里只搬运。
// ─────────────────────────────────────────────────────────────────────────────

/** 一条用户声明的端点。**没有 api_key 字段** —— 后端永不回显密钥,只给 has_key。 */
export interface UserProvider {
  readonly id: string;
  readonly label: string;
  readonly base_url: string;
  readonly protocol: string;
  /** 当前认哪些型号(网关报的优先,其次是人手填的)。 */
  readonly models: readonly string[];
  /** 人手填的那份。空 = 交给网关的 /models 去发现。 */
  readonly declared_models: readonly string[];
  /** 网关自己报的那份。空 = **没问出来**,不是「网关是空的」。 */
  readonly discovered_models: readonly string[];
  /** live=两步都过 · declared=网关不报型号但人手填了且试调过 · unverified=没过 */
  readonly state: string;
  /** 没过的时候卡在哪一步。过了就是空串。 */
  readonly state_reason: string;
  readonly verified_at: number | null;
  readonly added_by: string;
  readonly has_key: boolean;
}

function readUserProvider(v: unknown): UserProvider | null {
  if (!v || typeof v !== 'object') return null;
  const o = v as Record<string, unknown>;
  if (typeof o['id'] !== 'string') return null;
  const strs = (k: string): string[] =>
    Array.isArray(o[k]) ? (o[k] as unknown[]).filter((x): x is string => typeof x === 'string') : [];
  return {
    id: o['id'],
    label: typeof o['label'] === 'string' ? o['label'] : o['id'],
    base_url: typeof o['base_url'] === 'string' ? o['base_url'] : '',
    protocol: typeof o['protocol'] === 'string' ? o['protocol'] : 'openai',
    models: strs('models'),
    declared_models: strs('declared_models'),
    discovered_models: strs('discovered_models'),
    state: typeof o['state'] === 'string' ? o['state'] : 'unverified',
    state_reason: typeof o['state_reason'] === 'string' ? o['state_reason'] : '',
    verified_at: typeof o['verified_at'] === 'number' ? o['verified_at'] : null,
    added_by: typeof o['added_by'] === 'string' ? o['added_by'] : 'user',
    has_key: o['has_key'] === true,
  };
}

/** 端点清单 + 后端支持哪些协议。 */
export interface UserProviderPage {
  readonly providers: readonly UserProvider[];
  /**
   * 后端认哪些协议。**由后端给,前端不自己写死** —— 写死就成了第二处权威:
   * 后端加一种,界面永远看不见;后端去掉一种,界面还让人选,选了才 400。
   */
  readonly supportedProtocols: readonly string[];
}

/** 拉这台机器上声明过的端点。拉不到返回 null —— 与「一条都没有」是两件事。 */
export async function fetchUserProviders(base: string): Promise<UserProviderPage | null> {
  try {
    const resp = await fetch(base + '/api/v1/providers/user', {
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) {
      console.error('[hud] 拉用户端点失败:', resp.status);
      return null;
    }
    const body = (await resp.json()) as Record<string, unknown>;
    const rows = Array.isArray(body['providers']) ? (body['providers'] as unknown[]) : [];
    const protos = Array.isArray(body['supported_protocols'])
      ? (body['supported_protocols'] as unknown[]).filter((x): x is string => typeof x === 'string')
      : [];
    return {
      providers: rows.map(readUserProvider).filter((x): x is UserProvider => x !== null),
      supportedProtocols: protos,
    };
  } catch (err) {
    console.error('[hud] 拉用户端点失败:', err);
    return null;
  }
}

/** 新增或改一条。后端拒绝时返回它给的那句人话 —— 直接显示给用户,别自己编。 */
export async function saveUserProvider(
  base: string,
  body: {
    id: string;
    label: string;
    base_url: string;
    protocol: string;
    models: readonly string[];
    api_key?: string;
  },
): Promise<{ ok: true; row: UserProvider } | { ok: false; reason: string }> {
  try {
    const resp = await fetch(base + '/api/v1/providers/user', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const json = (await resp.json()) as Record<string, unknown>;
    if (!resp.ok) {
      const detail = typeof json['detail'] === 'string' ? json['detail'] : `后端拒绝了（HTTP ${resp.status}）`;
      return { ok: false, reason: detail };
    }
    const row = readUserProvider(json);
    return row ? { ok: true, row } : { ok: false, reason: '后端返回的内容看不懂' };
  } catch (err) {
    return { ok: false, reason: `发不出去：${String(err)}` };
  }
}

/**
 * 两步自证。**没通过也返回 ok** —— 「没通过」是一个结论,不是一次请求错误,
 * 结论在 row.state / row.state_reason 里。
 */
export async function verifyUserProvider(
  base: string,
  id: string,
): Promise<UserProvider | null> {
  try {
    const resp = await fetch(base + '/api/v1/providers/user/' + encodeURIComponent(id) + '/verify', {
      method: 'POST',
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) return null;
    return readUserProvider(await resp.json());
  } catch (err) {
    console.error('[hud] 验证端点失败:', err);
    return null;
  }
}

/** 删掉一条（连同它在 vault 里的密钥）。 */
export async function deleteUserProvider(base: string, id: string): Promise<boolean> {
  try {
    const resp = await fetch(base + '/api/v1/providers/user/' + encodeURIComponent(id), {
      method: 'DELETE',
    });
    return resp.ok;
  } catch (err) {
    console.error('[hud] 删除端点失败:', err);
    return false;
  }
}

// ── GitHub 插件 ───────────────────────────────────────────────────────────────

/**
 * 一个装进来的 GitHub 插件。
 *
 * 形状对齐后端 manifest 的记录(``core/github_installer.py`` 的 ``record``),
 * 只挑界面真的要用的字段 —— 全盘照搬会让后端每加一个内部字段,这里就得跟着改一次。
 */
/** 三份集成契约。顺序就是安装器的判定顺序:mcp → skill → SKILL.md。 */
export const GITHUB_CONTRACT_KEYS = ['mcp', 'skill', 'skill_md'] as const;
export type GitHubContractKey = (typeof GITHUB_CONTRACT_KEYS)[number];

export interface GitHubAddon {
  readonly name: string;
  /** 后端判定的原始类型:mcp / skill / skill_md / ordinary_tool_repo。排障用。 */
  readonly type: string;
  readonly owner: string;
  readonly repo: string;
  readonly ref: string;
  readonly commit: string;
  readonly installedAt: string;
  readonly installPath: string;
  /**
   * **接入形态** —— 三档是并列的,不是"成功/降级"两档。
   *
   * · mcp      根上有 mcp_tool.json,注册成了一个 MCP 工具
   * · skill    根上有 skill.json 或 SKILL.md,注册成了一个 Skill
   * · project  哪个契约都没有 —— 以项目完整形式接进来:代码落盘,没注册成工具
   *
   * MCP / Skill 是 GitHub 项目的**交集**,不是它的定义。接一个仓库可能是为了拿它
   * 跑实验、读它、当素材。把 project 画成一种失败,等于规定了"接项目 = 接工具"。
   */
  readonly form: 'mcp' | 'skill' | 'project';
  /** 这次接入成没成。project 形态没有"注册"这一步,所以永远是 true。 */
  readonly ok: boolean;
  /** ok=false 时卡在哪一步;project 形态时是"它以什么形式接进来了"那句话。 */
  readonly formDetail: string;
  /**
   * 三个接入槽各自的实情。面板右侧把三个都摆出来,所以三个都要有据可依。
   *
   * ``present`` = 根上摆着这份契约文件;``chosen`` = 它被选中并走了注册那条路。
   * 两者不是一回事:一个仓库可能同时带 mcp_tool.json 和 skill.json,而只有前者
   * 被选中。只按 chosen 画的话,另外两个槽就会一律显示成"没有" —— 那是在替
   * 仓库说一句它没说过的话。
   */
  readonly contracts: Readonly<Record<GitHubContractKey, { present: boolean; chosen: boolean }>>;
  /** 依赖装到哪:venv / host / rejected / venv_unavailable / none。 */
  readonly depsScope: string;
  /** 依赖没装成时的原因(含 requirements.txt 被整份拒绝的那几行)。 */
  readonly depsError: string;
}

/**
 * 形态与成败**优先读后端的 ``integration``**,读不到才退回自己推。
 *
 * 为什么留退路:``integration`` 是新加的字段,而 manifest 里躺着的是**以前装的**
 * 那些记录 —— 它们没有这个字段。不留退路的话,升级之后已经装好的插件会集体
 * 变成"认不出的形态",而它们明明好好的。
 *
 * 为什么退路**不**是默认路径:后端的判定是唯一权威。前端这份推导只是给老记录用的
 * 兼容垫片,它推不出 project 这一档(老记录里没有任何字段能区分"没有契约"和
 * "注册失败"),所以退回来的结论必然偏保守 —— 这正是它只能当垫片的原因。
 */
function readGitHubAddon(v: unknown): GitHubAddon | null {
  if (!v || typeof v !== 'object') return null;
  const o = v as Record<string, unknown>;
  if (typeof o['name'] !== 'string') return null;
  const str = (k: string): string => (typeof o[k] === 'string' ? (o[k] as string) : '');
  const sub = (k: string): Record<string, unknown> =>
    o[k] && typeof o[k] === 'object' ? (o[k] as Record<string, unknown>) : {};

  const type = str('type') || 'unknown';
  const integration = sub('integration');
  const rawForm = integration['form'];

  let form: GitHubAddon['form'];
  let ok: boolean;
  let formDetail: string;

  if (rawForm === 'mcp' || rawForm === 'skill' || rawForm === 'project') {
    form = rawForm;
    ok = integration['ok'] === true;
    formDetail = typeof integration['detail'] === 'string' ? (integration['detail'] as string) : '';
  } else {
    // 老记录的兼容垫片。按 type 认形态,按 registration+verification 认成败。
    form = type === 'mcp' ? 'mcp' : type === 'skill' || type === 'skill_md' ? 'skill' : 'project';
    const reg = sub('registration');
    const ver = sub('verification');
    // project 形态在老记录里也是 reg.success=false —— 那时它确实被当成失败记下来的。
    // 这里按形态给结论:没有契约的就不该拿"注册成没成"去判。
    ok = form === 'project' ? true : reg['success'] === true && ver['success'] === true;
    if (!ok) {
      formDetail =
        reg['success'] !== true
          ? typeof reg['error'] === 'string' && reg['error']
            ? `注册失败：${reg['error']}`
            : '注册没成功'
          : typeof ver['error'] === 'string' && ver['error']
            ? `自证失败：${ver['error']}`
            : '自证没通过';
    } else {
      formDetail = form === 'project' ? '代码已落盘，没有注册成可调用的工具' : '';
    }
  }

  // 三个槽位。老记录里没有 contracts —— 那就只能按被选中的那一个反推,
  // 另外两个照实报"不知道"(present=false + chosen=false)。这是兼容垫片能做到的
  // 全部:老记录里确实没有记下另外两份在不在。
  const rawContracts = integration['contracts'];
  const contractSrc: Record<string, unknown> =
    rawContracts && typeof rawContracts === 'object' ? (rawContracts as Record<string, unknown>) : {};
  const contracts = {} as Record<GitHubContractKey, { present: boolean; chosen: boolean }>;
  for (const key of GITHUB_CONTRACT_KEYS) {
    const slot = contractSrc[key];
    if (slot && typeof slot === 'object') {
      const o2 = slot as Record<string, unknown>;
      contracts[key] = { present: o2['present'] === true, chosen: o2['chosen'] === true };
    } else {
      contracts[key] = { present: type === key, chosen: type === key };
    }
  }

  const deps = sub('dependency_install');
  return {
    name: o['name'],
    type,
    owner: str('owner'),
    repo: str('repo'),
    ref: str('ref'),
    commit: str('commit'),
    installedAt: str('installed_at'),
    installPath: str('install_path'),
    form,
    ok,
    formDetail,
    contracts,
    depsScope: typeof deps['scope'] === 'string' ? (deps['scope'] as string) : 'none',
    depsError: typeof deps['error'] === 'string' ? (deps['error'] as string) : '',
  };
}

/** 装插件之前会不会先问人。由后端给 —— 前端自己按环境变量推会成为第二处权威。 */
export interface GitHubAddonStatus {
  readonly tokenConfigured: boolean;
  readonly installDir: string;
  readonly allowlist: readonly string[];
  readonly blocklist: readonly string[];
  /** allowlist=名单内直接装、名单外拒 · ask=每次都问 · unattended=一律不问 */
  readonly approvalMode: string;
}

export interface GitHubAddonPage {
  readonly addons: readonly GitHubAddon[];
  readonly status: GitHubAddonStatus | null;
}

/** 拉已装插件 + 安装策略。拉不到返回 null —— 与「一个都没装」是两件事。 */
export async function fetchGitHubAddons(base: string): Promise<GitHubAddonPage | null> {
  try {
    const [listResp, statusResp] = await Promise.all([
      fetch(base + '/api/v1/github/list', { headers: { Accept: 'application/json' } }),
      fetch(base + '/api/v1/github/status', { headers: { Accept: 'application/json' } }),
    ]);
    if (!listResp.ok) {
      console.error('[hud] 拉 GitHub 插件失败:', listResp.status);
      return null;
    }
    const body = (await listResp.json()) as Record<string, unknown>;
    const rows = Array.isArray(body['addons']) ? (body['addons'] as unknown[]) : [];

    let status: GitHubAddonStatus | null = null;
    if (statusResp.ok) {
      const s = (await statusResp.json()) as Record<string, unknown>;
      const strs = (k: string): string[] =>
        Array.isArray(s[k]) ? (s[k] as unknown[]).filter((x): x is string => typeof x === 'string') : [];
      status = {
        tokenConfigured: s['token_configured'] === true,
        installDir: typeof s['install_dir'] === 'string' ? s['install_dir'] : '',
        allowlist: strs('allowlist'),
        blocklist: strs('blocklist'),
        approvalMode: typeof s['approval_mode'] === 'string' ? s['approval_mode'] : '',
      };
    }
    return {
      addons: rows.map(readGitHubAddon).filter((x): x is GitHubAddon => x !== null),
      status,
    };
  } catch (err) {
    console.error('[hud] 拉 GitHub 插件失败:', err);
    return null;
  }
}

/**
 * 装一个，或者只验一下地址（dry_run）。
 *
 * **被准入闸拒绝也走 ok:false** —— 那是一个结论,不是请求出错,而且后端给的那句话
 * (要人确认 / 不在名单里 / 被名单挡了)就是用户要看的,别自己编。
 *
 * 为什么没有「装下来了但没注册成功」这一路:后端在 reg/verify 任一没过时
 * 就返回 `success:false` + HTTP 400,于是那种情况本来就走 ok:false。
 * 曾经在这里写过一个 `degraded: true` 的成功分支 —— 它**永远不会被走到**,
 * 而一段永远不执行的分支会让人以为这条路被处理过了。degraded 只在
 * `/api/v1/github/list` 的记录上有意义(manifest 是在成败判定之前就写下的),
 * 那一处由 `readGitHubAddon` 负责。
 */
export async function installGitHubAddon(
  base: string,
  body: { url: string; ref?: string; type?: string; dry_run?: boolean },
): Promise<{ ok: true; name: string; dryRun: boolean; message: string } | { ok: false; reason: string }> {
  try {
    const resp = await fetch(base + '/api/v1/github/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const json = (await resp.json()) as Record<string, unknown>;
    const pick = (k: string): string => (typeof json[k] === 'string' ? (json[k] as string) : '');
    if (!resp.ok || json['success'] !== true) {
      // error → failure_reason → detail(FastAPI 的校验错误走这个)→ 兜底的状态码。
      // 顺序是有意的:越靠前的越具体,而具体的那句才是能拿去排查的。
      const reason =
        pick('error') || pick('failure_reason') || pick('detail') || `后端拒绝了（HTTP ${resp.status}）`;
      return { ok: false, reason };
    }
    return {
      ok: true,
      name: pick('name'),
      dryRun: json['dry_run'] === true,
      message: pick('message'),
    };
  } catch (err) {
    return { ok: false, reason: `发不出去：${String(err)}` };
  }
}

/** 卸一个（连同它装在 data/github_addons 下的那份副本）。 */
export async function uninstallGitHubAddon(base: string, name: string): Promise<boolean> {
  try {
    const resp = await fetch(base + '/api/v1/github/uninstall', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
    if (!resp.ok) return false;
    const json = (await resp.json()) as Record<string, unknown>;
    return json['success'] === true;
  } catch (err) {
    console.error('[hud] 卸载插件失败:', err);
    return false;
  }
}
