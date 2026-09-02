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
import type { LockstepReason, LockstepState, Phase } from './types';

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
