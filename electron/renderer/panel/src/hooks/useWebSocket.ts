import { useCallback, useEffect, useRef, useState } from 'react';
import type { WebSocketMessage } from '@/types/phase';

// P25 修复：端口统一为 9000（与主窗口 app.js 一致）
const WS_URL = 'ws://localhost:9000/ws/desktop-presence';
// P26 修复：指数退避参数（与主窗口 app.js 保持一致）
const RECONNECT_BASE_INTERVAL = 1000;
const RECONNECT_MAX_INTERVAL = 30000;

interface UseWebSocketReturn {
  connected: boolean;
  lastMessage: WebSocketMessage | null;
  send: (msg: WebSocketMessage) => void;
}

export function useWebSocket(): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>();
  const reconnectAttemptsRef = useRef(0);
  const isMountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!isMountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!isMountedRef.current) return;
        console.log('[Panel] WebSocket connected');
        setConnected(true);
        reconnectAttemptsRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (!isMountedRef.current) return;
        try {
          const msg = JSON.parse(event.data) as WebSocketMessage;
          setLastMessage(msg);
        } catch {
          setLastMessage({ type: 'text', data: event.data });
        }
      };

      ws.onclose = () => {
        if (!isMountedRef.current) return;
        console.log('[Panel] WebSocket closed');
        setConnected(false);
        wsRef.current = null;

        // P26+P27 修复：指数退避重连，无上限
        const interval = Math.min(
          RECONNECT_BASE_INTERVAL * Math.pow(2, reconnectAttemptsRef.current),
          RECONNECT_MAX_INTERVAL
        );
        reconnectAttemptsRef.current++;
        console.log(`[Panel] ${interval}ms 后重连 (第${reconnectAttemptsRef.current}次)...`);
        reconnectTimerRef.current = setTimeout(connect, interval);
      };

      ws.onerror = (err) => {
        if (!isMountedRef.current) return;
        console.error('[Panel] WebSocket error:', err);
        setConnected(false);
      };
    } catch (e) {
      console.error('[Panel] WebSocket connect failed:', e);
      setConnected(false);
    }
  }, []);

  const send = useCallback((msg: WebSocketMessage) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(msg));
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    connect();

    return () => {
      isMountedRef.current = fal