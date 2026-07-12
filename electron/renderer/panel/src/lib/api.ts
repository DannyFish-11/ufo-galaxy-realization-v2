/**
 * api.ts — 面板 ↔ 本机网关(默认 :9000)的最小客户端
 *
 * 对话走 A 方案:POST /api/v1/chat/stream(SSE 逐字)。EventSource 不支持 POST,
 * 故用 fetch + ReadableStream 自行解析 SSE 帧。后端已对桌面壳来源(file:// null /
 * tauri://localhost)放行 CORS,渲染层可直连。
 */

let cachedBase: string | null = null;

/** 解析后端基址:优先 preload 暴露的 getBackendUrl,回退 localhost:9000。 */
export async function getBackendUrl(): Promise<string> {
  if (cachedBase) return cachedBase;
  try {
    const api = (window as any).galaxyAPI;
    if (api?.getBackendUrl) {
      const url = await api.getBackendUrl();
      if (typeof url === 'string' && url) {
        cachedBase = url.replace(/\/$/, '');
        return cachedBase;
      }
    }
  } catch {
    /* fall through */
  }
  cachedBase = 'http://localhost:9000';
  return cachedBase;
}

export interface ChatStreamEvent {
  type: 'meta' | 'phase' | 'delta' | 'reset' | 'done' | 'error';
  text?: string;
  phase?: 'silent' | 'liminal' | 'manifest';
  response?: string;
  intent?: string;
  success?: boolean;
  suggestions?: string[];
  session_id?: string;
  model?: string;
  runtime_session_id?: string;
  visible_action_surface?: Record<string, unknown>;
  error?: string;
}

export interface ChatStreamHandlers {
  onEvent: (ev: ChatStreamEvent) => void;
  signal?: AbortSignal;
}

/**
 * 发起一次流式对话。逐帧回调 onEvent;promise 在流结束时 resolve。
 * 调用方可用 AbortController.signal 中断。
 */
export async function streamChat(
  message: string,
  sessionId: string,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const base = await getBackendUrl();
  const resp = await fetch(`${base}/api/v1/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, session_id: sessionId || '' }),
    signal: handlers.signal,
  });

  if (!resp.ok || !resp.body) {
    handlers.onEvent({ type: 'error', error: `HTTP ${resp.status}` });
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  // SSE: 帧以 \n\n 分隔;每帧内以 "data: " 开头的行携带 JSON。
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sep: number;
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      for (const line of frame.split('\n')) {
        const trimmed = line.trimStart();
        if (!trimmed.startsWith('data:')) continue;
        const json = trimmed.slice(5).trim();
        if (!json) continue;
        try {
          handlers.onEvent(JSON.parse(json) as ChatStreamEvent);
        } catch {
          /* ignore malformed frame */
        }
      }
    }
  }
}

export interface HistoryMessage {
  role: string;
  content: string;
  [key: string]: unknown;
}

/** 拉取会话历史(非致命:失败返回空数组)。 */
export async function fetchHistory(sessionId: string): Promise<HistoryMessage[]> {
  if (!sessionId) return [];
  try {
    const base = await getBackendUrl();
    const resp = await fetch(
      `${base}/api/v1/sessions/${encodeURIComponent(sessionId)}/history?max_turns=50`,
    );
    if (!resp.ok) return [];
    const data = await resp.json();
    const history = Array.isArray(data?.history) ? data.history : [];
    return history
      .map((h: any) => ({
        role: String(h?.role || h?.sender || 'assistant'),
        content: String(h?.content ?? h?.message ?? h?.text ?? ''),
      }))
      .filter((h: HistoryMessage) => h.content);
  } catch {
    return [];
  }
}
