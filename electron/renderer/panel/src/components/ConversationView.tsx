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

export default function ConversationView({ onStreamPhase }: ConversationViewProps) {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const sessionIdRef = useRef('');
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
              if (ev.session_id) sessionIdRef.current = ev.session_id;
              break;
            case 'phase':
              if (ev.phase) onStreamPhase?.(ev.phase);
              break;
            case 'delta':
              if (ev.text) patchAi((p) => ({ ...p, content: p.content + ev.text }));
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
          {sending ? <span className="send-dot" /> : '↑'}
        </button>
      </div>
    </div>
  );
}
