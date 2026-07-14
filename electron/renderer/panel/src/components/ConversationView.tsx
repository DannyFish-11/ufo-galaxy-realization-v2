import { useCallback, useEffect, useRef, useState } from 'react';
import { streamChat, fetchHistory } from '@/lib/api';
import type { Phase } from '@/types/phase';

interface Message {
  id: number;
  role: 'user' | 'ai';
  content: string;
  streaming?: boolean;
  error?: boolean;
}

interface ConversationViewProps {
  /** 把流式过程中的三态上报给外壳(用于右侧在场对照);空闲时传 null。 */
  onStreamPhase?: (phase: Phase | null) => void;
}

const WELCOME: Message = {
  id: 0,
  role: 'ai',
  content: '你好，我是 Galaxy。说点什么，或交给我一件事。',
};

const SESSION_STORAGE_KEY = 'galaxy_session_id';

/** 读取上次持久化的会话 id;取不到(隐私模式/首次运行)则返回空串。 */
function loadPersistedSessionId(): string {
  try {
    return localStorage.getItem(SESSION_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

/** 修复:sessionIdRef 之前永远从 '' 起步、且从未持久化——每次面板重开/刷新都会
 * 丢失会话 id,导致挂载时的 fetchHistory(sessionIdRef.current) 恒等于
 * fetchHistory('')(在 lib/api.ts 里直接短路返回 []),历史消息永远拉不回来，
 * 界面上"看似能恢复会话"实为死代码。这里把 session_id 存进 localStorage，
 * 挂载时先读回来，让"进入时拉历史"真正生效。 */
function persistSessionId(id: string): void {
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, id);
  } catch {
    /* 隐私模式等场景下持久化失败不影响当次对话 */
  }
}

export default function ConversationView({ onStreamPhase }: ConversationViewProps) {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const sessionIdRef = useRef(loadPersistedSessionId());
  const idRef = useRef(1);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  // 进入时拉历史(若有持久会话)。无历史则保留欢迎语。
  useEffect(() => {
    (async () => {
      const hist = await fetchHistory(sessionIdRef.current);
      if (hist.length) {
        setMessages(
          hist.map((h) => ({
            id: idRef.current++,
            role: h.role === 'user' ? 'user' : 'ai',
            content: h.content,
          })),
        );
      }
    })();
  }, []);

  // 自动滚到底部
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  // 卸载时中断在飞的流
  useEffect(() => () => abortRef.current?.abort(), []);

  const autoGrow = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = 'auto';
    ta.style.height = `${Math.min(ta.scrollHeight, 160)}px`;
  }, []);

  const send = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;

    const userMsg: Message = { id: idRef.current++, role: 'user', content: text };
    const aiMsg: Message = { id: idRef.current++, role: 'ai', content: '', streaming: true };
    setMessages((m) => [...m, userMsg, aiMsg]);
    setInput('');
    setSending(true);
    if (taRef.current) taRef.current.style.height = 'auto';

    const abort = new AbortController();
    abortRef.current = abort;

    const patchAi = (fn: (prev: Message) => Message) =>
      setMessages((m) => m.map((msg) => (msg.id === aiMsg.id ? fn(msg) : msg)));

    try {
      await streamChat(text, sessionIdRef.current, {
        signal: abort.signal,
        onEvent: (ev) => {
          switch (ev.type) {
            case 'meta':
              if (ev.session_id) {
                sessionIdRef.current = ev.session_id;
                persistSessionId(ev.session_id);
              }
              break;
            case 'phase':
              if (ev.phase) onStreamPhase?.(ev.phase);
              break;
            case 'delta':
              if (ev.text) patchAi((p) => ({ ...p, content: p.content + ev.text }));
              break;
            case 'reset':
              // 后端作废已流出的草稿(级联换档/failover/工具轮):清空当前气泡,
              // 新一代内容随后重新流入。done.response 仍是权威全文兜底。
              patchAi((p) => ({ ...p, content: '' }));
              break;
            case 'done':
              patchAi((p) => ({
                ...p,
                content: ev.response ?? p.content,
                streaming: false,
              }));
              break;
            case 'error':
              patchAi((p) => ({
                ...p,
                content: p.content || `出错了：${ev.error ?? '未知错误'}`,
                streaming: false,
                error: true,
              }));
              break;
          }
        },
      });
    } catch (e) {
      const aborted = e instanceof DOMException && e.name === 'AbortError';
      patchAi((p) => ({
        ...p,
        content: aborted ? p.content : p.content || `连接失败：${String(e)}`,
        streaming: false,
        error: !aborted,
      }));
    } finally {
      patchAi((p) => ({ ...p, streaming: false }));
      setSending(false);
      onStreamPhase?.(null);
      abortRef.current = null;
    }
  }, [input, sending, onStreamPhase]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  };

  return (
    <div className="conv">
      <div className="conv-scroll" ref={scrollRef}>
        <div className="conv-list">
          {messages.map((m) => (
            <div key={m.id} className={`bubble-row ${m.role}`}>
              <div className={`bubble ${m.role}${m.error ? ' error' : ''}`}>
                {m.content}
                {m.streaming && <span className="caret" />}
              </div>
            </div>
          ))}
        </div>
      </div>

      <div className="composer glass">
        <textarea
          ref={taRef}
          className="composer-input"
          placeholder="跟 Galaxy 说点什么…  (Enter 发送 · Shift+Enter 换行)"
          value={input}
          rows={1}
          onChange={(e) => {
            setInput(e.target.value);
            autoGrow();
          }}
          onKeyDown={onKeyDown}
        />
        <button
          className="composer-send"
          onClick={send}
          disabled={!input.trim() || sending}
          aria-label="发送"
        >
          {sending ? (
            <span className="send-dot" />
          ) : (
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M4.4 11.2 18.6 5.1c.9-.4 1.8.5 1.4 1.4l-6.1 14.2c-.4 1-1.9.9-2.2-.2l-1.5-5.2a1 1 0 0 0-.7-.7L4.6 13.4c-1.1-.3-1.2-1.8-.2-2.2Z"
                fill="currentColor"
              />
            </svg>
          )}
        </button>
      </div>
    </div>
  );
}
