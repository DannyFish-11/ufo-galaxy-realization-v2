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
import type { Bundle, DeviceLoad, DeviceRow, DeviceState, LockstepReason, LockstepState, Phase } from './types';

/** RenderPosture 该有的字段。少一个就是**契约漂移**,不是正常降级。 */
const POSTURE_FIELDS = [
  'lifecycle', 'previous_lifecycle', 'transition_kind', 'continuum_phase',
  'is_returning', 'next_phases', 'liminal_activity', 'simulation',
  'local_chain', 'cross_device_chain', 'world_model', 'perception',
  'hybrid_execution', 'pathway', 'thinking_locus', 'runtime_domain',
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
 */
export class PresenceSocket {
  #url: string;
  #h: PresenceHandlers;
  #sock: WebSocket | null = null;
  #retry = 0;
  #timer = 0;
  #stopped = false;

  constructor(base: string, handlers: PresenceHandlers) {
    this.#url = base.replace(/^http/, 'ws') + '/ws/desktop-presence';
    this.#h = handlers;
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
  onPhase?(phase: Phase): void;
  onDelta?(text: string): void;
  /** 作废已经流出去的内容。收到它就把这一轮清空重来。 */
  onReset?(): void;
  onLockstep?(state: LockstepState, reason: LockstepReason): void;
  onDone?(): void;
  onError?(message: string): void;
}

/**
 * `POST /api/v1/chat/stream` 的 SSE。
 *
 * 用 fetch 而不是 EventSource:EventSource 只能 GET,而这条要带请求体。
 * 七种帧 —— phase / delta / reset / meta / lockstep / done / error。
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
          h.onPhase?.(toPhase(String(ev['phase'] ?? '')));
          break;
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
          h.onDone?.();
          break;
        case 'error':
          h.onError?.(String(ev['error'] ?? ''));
          break;
        default:
          break; // meta 等:面板不用,但不当成错误
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
    keyCount: typeof o['key_count'] === 'number' ? o['key_count'] : 0,
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
