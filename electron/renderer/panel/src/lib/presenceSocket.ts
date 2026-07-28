/**
 * /ws/desktop-presence 的共享单例连接。
 *
 * 此前 useWebSocket(消费 state_event)与 usePanelData(消费 panel_feed)
 * 各自 new WebSocket 连同一端点、各带一套独立重连梯——同一个面板窗口
 * 常年挂着两条相同连接,后端 GalaxyPresenceBridge 的每次广播都要发两遍。
 * 收敛为单连接 + 订阅分发:各消费方按帧类型自取,重连梯只有一套
 * (指数退避,与主窗口 app.js 一致)。
 *
 * 生命周期:面板窗口存续期 = 应用存续期,单例不随组件卸载关闭,
 * 订阅方卸载时仅退订。
 */
import { getBackendUrl } from './api';

type Listener = (msg: any) => void;
type StatusListener = (connected: boolean) => void;

const RECONNECT_BASE_INTERVAL = 1000;
const RECONNECT_MAX_INTERVAL = 30000;
const RECONNECT_MAX_ATTEMPTS = 10;
const RECONNECT_COOLDOWN_MS = 60000;

let ws: WebSocket | null = null;
let started = false;
let attempts = 0;
let connectedState = false;
const listeners = new Set<Listener>();
const statusListeners = new Set<StatusListener>();

function notifyStatus(v: boolean) {
  connectedState = v;
  statusListeners.forEach((l) => {
    try {
      l(v);
    } catch {
      /* 订阅方异常互相隔离 */
    }
  });
}

async function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  try {
    const base = await getBackendUrl();
    const sock = new WebSocket(base.replace(/^http/, 'ws') + '/ws/desktop-presence');
    ws = sock;
    sock.onopen = () => {
      attempts = 0;
      notifyStatus(true);
    };
    sock.onmessage = (ev) => {
      let msg: any;
      try {
        msg = JSON.parse(ev.data);
      } catch {
        msg = { type: 'text', data: ev.data };
      }
      listeners.forEach((l) => {
        try {
          l(msg);
        } catch {
          /* 订阅方异常互相隔离 */
        }
      });
    };
    sock.onclose = () => {
      notifyStatus(false);
      ws = null;
      if (attempts >= RECONNECT_MAX_ATTEMPTS) {
        console.warn('[Panel] presence WS 重连达到上限,冷却后重试');
        setTimeout(() => {
          attempts = 0;
          connect();
        }, RECONNECT_COOLDOWN_MS);
        return;
      }
      const interval = Math.min(RECONNECT_BASE_INTERVAL * 2 ** attempts, RECONNECT_MAX_INTERVAL);
      attempts++;
      setTimeout(connect, interval);
    };
    sock.onerror = () => {
      try {
        sock.close();
      } catch {
        /* noop */
      }
    };
  } catch {
    setTimeout(connect, 3000);
  }
}

/** 订阅 presence 帧;返回退订函数。首个订阅方触发建连。 */
export function subscribePresence(onMessage: Listener, onStatus?: StatusListener): () => void {
  listeners.add(onMessage);
  if (onStatus) {
    statusListeners.add(onStatus);
    onStatus(connectedState);
  }
  if (!started) {
    started = true;
    connect();
  }
  return () => {
    listeners.delete(onMessage);
    if (onStatus) statusListeners.delete(onStatus);
  };
}

/** 经共享连接发送一帧(未连接时静默丢弃,与旧 useWebSocket.send 语义一致)。 */
export function sendPresence(msg: unknown): void {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}
