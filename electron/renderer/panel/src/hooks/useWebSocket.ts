import { useCallback, useEffect, useRef, useState } from 'react';
import type { WebSocketMessage } from '@/types/phase';
import { getBackendUrl } from '@/lib/api';

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

  const connect = useCallback(async () => {
    if (!isMountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      // 修复:之前硬编码 ws://localhost:9000,与「设置」tab 里可编辑的网关端口
      // (GATEWAY_PORT)完全脱节——用户改了端口,WS 仍悄悄连着旧端口,永远连不上,
      // 面板只能靠慢速 IPC 轮询兜底,且没有任何可见报错。这里改成跟 REST 请求
      // 共用同一套后端地址解析(getBackendUrl),端口一致，来源单一。
      const base = await getBackendUrl();
      if (!isMountedRef.current) return;
      const wsUrl = base.replace(/^http/, 'ws') + '/ws/desktop-presence';
      const ws = new WebSocket(wsUrl);
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
      isMountedRef.current = false;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      try {
        wsRef.current?.close();
      } catch {
        /* ignore */
      }
      wsRef.current = null;
    };
  }, [connect]);

  return { connected, lastMessage, send };
}
