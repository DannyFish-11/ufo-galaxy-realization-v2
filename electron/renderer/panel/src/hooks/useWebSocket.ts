import { useCallback, useEffect, useState } from 'react';
import type { WebSocketMessage } from '@/types/phase';
import { sendPresence, subscribePresence } from '@/lib/presenceSocket';

interface UseWebSocketReturn {
  connected: boolean;
  lastMessage: WebSocketMessage | null;
  send: (msg: WebSocketMessage) => void;
}

/**
 * state_event 消费端。
 *
 * 收敛修复:此前本 hook 与 usePanelData 各自 new WebSocket 连
 * /ws/desktop-presence(同一窗口两条相同连接、两套独立重连梯,后端
 * GalaxyPresenceBridge 的每次广播都要发两遍)。现在两者共用
 * lib/presenceSocket 的单例连接,本 hook 只做订阅分发;指数退避重连
 * (P26/P27 语义)整体移入单例。对外接口(connected / lastMessage / send)
 * 保持不变。
 */
export function useWebSocket(): UseWebSocketReturn {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);

  useEffect(() => {
    const unsubscribe = subscribePresence(
      (msg) => setLastMessage(msg as WebSocketMessage),
      (isConnected) => setConnected(isConnected),
    );
    return unsubscribe;
  }, []);

  const send = useCallback((msg: WebSocketMessage) => {
    sendPresence(msg);
  }, []);

  return { connected, lastMessage, send };
}
