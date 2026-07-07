/**
 * useConversation — 实时对话上下文 Hook
 *
 * 订阅 /ws/desktop-presence 上的 conversation 事件（后端 emit_conversation 推送），
 * 维护一条滚动的"听到的 / AI 说的"实时对话，供面板常驻的实时上下文视图显示。
 * 与三态在场共用同一条 WS 通道，无论是否打开对话 tab 都是活的。
 */

import { useEffect, useRef, useState } from 'react';
import type { WebSocketMessage } from '@/types/phase';

export interface ConversationTurn {
  id: number;
  role: 'user' | 'ai';
  text: string;
  source: string; // 'voice' | 'text'
  final: boolean;
}

const MAX_TURNS = 12;

export function useConversation(lastMessage: WebSocketMessage | null, connected = true): {
  turns: ConversationTurn[];
  speaking: boolean;
} {
  const [turns, setTurns] = useState<ConversationTurn[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const idRef = useRef(0);
  const streamKeyRef = useRef<string>('');

  // WS 断线时后端可能永远发不出 speaking:false 那一帧 → "正在朗读…"会永久卡住。
  // 连接断开即强制复位 speaking，避免面板停在假的"朗读中"。
  useEffect(() => {
    if (!connected) setSpeaking(false);
  }, [connected]);

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'conversation') return;
    const p = (lastMessage.payload ?? {}) as Record<string, unknown>;
    const role: 'user' | 'ai' = p.role === 'ai' ? 'ai' : 'user';
    const text = String(p.text ?? '');
    const source = String(p.source ?? 'text');
    const final = p.final === undefined ? true : Boolean(p.final);
    const turnId = String(p.turn_id ?? '');

    // 只在消息确实带了 speaking 字段时才更新，避免无关轮次把它强制拉成 false。
    if ('speaking' in p) setSpeaking(Boolean(p.speaking));
    if (!text.trim()) return;

    setTurns((prev) => {
      const key = `${turnId}:${role}`;
      const next = [...prev];
      const lastIdx = next.length - 1;
      // 流式增量：同一轮未 final → 原地替换最后一条；否则新增一条。
      if (!final && streamKeyRef.current === key && lastIdx >= 0 && next[lastIdx].role === role) {
        next[lastIdx] = { ...next[lastIdx], text, final };
      } else {
        next.push({ id: idRef.current++, role, text, source, final });
      }
      streamKeyRef.current = final ? '' : key;
      return next.slice(-MAX_TURNS);
    });
  }, [lastMessage]);

  return { turns, speaking };
}
