import { useCallback, useEffect, useRef, useState } from 'react';
import type { WebSocketMessage } from '@/types/phase';

const WS_URL = 'ws://localhost:8765/ws/desktop-presence';
const RECONNECT_INTERVAL = 3000;
const MAX_RECONNECT_ATTEMPTS = 10;

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

        // 自动重连
        if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttemptsRef.current++;
          reconnectTimerRef.current = setTimeout(connect, RECONNECT_INTERVAL);
        }
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
      isMountedRef.current = false;
      clearTimeout(reconnectTimerRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected, lastMessage, send };
}