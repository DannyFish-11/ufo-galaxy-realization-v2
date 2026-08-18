/**
 * api.ts — 面板 ↔ 本机网关(默认 :9000)的最小客户端
 *
 * 对话走 A 方案:POST /api/v1/chat/stream(SSE 逐字)。EventSource 不支持 POST,
 * 故用 fetch + ReadableStream 自行解析 SSE 帧。后端已对桌面壳来源(file:// null /
 * tauri://localhost)放行 CORS,渲染层可直连。
 *
 * 端点与请求体的类型从后端生成
 * ============================
 * `scripts/gen_ts_types.py` 从 `core/api_routes.py` 组装出的 OpenAPI 生成
 * `types/api.gen.ts`(388 条路径 / 103 个组件 schema),CI 里 `test_api_surface_contract`
 * 重跑生成器逐字比对,保证它不过期。
 *
 * 但在本次改动之前,**面板对这个文件的引用数是 0** —— 端点写成裸字符串、请求体
 * 字段靠人对着后端源码抄。于是后端改一个字段:生成的那份会变、Python 侧的测试会红,
 * 而面板编译**不会红**,只会在运行时拿到 `undefined`。生成机制是齐的、CI 里也确实
 * 在跑 `tsc`(见 ci.yml 的 panel-dist-consistency),唯独差 import 这一步。
 *
 * 现在端点一律经 {@link apiUrl} 走 `ApiPath`,请求体用生成的 schema 类型。
 */
import type { ApiPath, ChatRequest } from '@/types/api.gen';

let cachedBase: string | null = null;

/**
 * 拼一条**经过类型校验**的端点 URL。
 *
 * @param base 网关基址(不带尾斜杠)。
 * @param path 权威 API 层里的路径。写错一个字母、或调一个后端已经删掉的端点,
 *   `tsc` 当场报错 —— 这正是接生成类型的全部意义。
 * @param params 路径里 `{name}` 占位符的取值。多给的键会被忽略;**少给会抛异常**,
 *   因为把 `/sessions/{session_id}/history` 原样发出去只会得到一个 404,
 *   那种错误在运行时比在这里难查得多。
 *
 * @example
 * apiUrl(base, '/api/v1/sessions/{session_id}/history', { session_id: 'abc' })
 */
export function apiUrl<P extends ApiPath>(
  base: string,
  path: P,
  params?: Record<string, string | number>,
): string {
  const filled = path.replace(/\{([^}]+)\}/g, (_m, key: string) => {
    const v = params?.[key];
    if (v === undefined || v === null || v === '') {
      throw new Error(`端点 ${path} 缺少路径参数 ${key}`);
    }
    return encodeURIComponent(String(v));
  });
  return `${base}${filled}`;
}


/**
 * 带超时的 fetch —— 任何请求都不该无限等待。后端启动期/провайдер 不可达时,
 * 裸 fetch 会挂到 OS 级 TCP 超时(可达几分钟),表现为按钮"一直转圈没反应"。
 * 到点即 abort,把"挂死"转成一个可显示的错误。调用方传入的 signal 仍受尊重
 * (任一触发都会中断)。
 */
export async function fetchWithTimeout(
  input: string,
  init: RequestInit = {},
  timeoutMs = 15000,
): Promise<Response> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(new DOMException('timeout', 'TimeoutError')), timeoutMs);
  // 若调用方也给了 signal,任一 abort 都应生效。
  if (init.signal) {
    if (init.signal.aborted) ctrl.abort(init.signal.reason);
    else init.signal.addEventListener('abort', () => ctrl.abort(init.signal!.reason), { once: true });
  }
  try {
    return await fetch(input, { ...init, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
}

/** 给任意 Promise 套一个超时(用于 IPC 调用等无法 abort 的场景)。 */
export function withTimeout<T>(p: Promise<T>, timeoutMs: number, label = '操作'): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`${label}超时(${Math.round(timeoutMs / 1000)}s 未响应)`)),
      timeoutMs,
    );
    p.then(
      (v) => { clearTimeout(timer); resolve(v); },
      (e) => { clearTimeout(timer); reject(e); },
    );
  });
}

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
  // 请求体用生成的 schema 类型标注:后端给 ChatRequest 改字段名,这里当场编译报错,
  // 而不是照旧发出去、后端按默认值处理、面板看着"正常"。
  const body: ChatRequest = { message, session_id: sessionId || '' };
  const resp = await fetch(apiUrl(base, '/api/v1/chat/stream'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
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
    const url = apiUrl(base, '/api/v1/sessions/{session_id}/history', { session_id: sessionId });
    const resp = await fetch(`${url}?max_turns=50`);
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
