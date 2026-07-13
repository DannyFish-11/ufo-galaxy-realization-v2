/**
 * usePanelData — IPC 驱动 Hook
 * 通过 Electron preload.js 暴露的 galaxyAPI.onBackendState 接收状态推送
 */

import { useEffect, useRef, useState } from 'react';
import { getBackendUrl } from '@/lib/api';
import type { Phase } from '@/types/phase';

// ── AIP v3 类型定义 ──────────────────────────────

export interface PanelData {
  phase: Phase;
  phaseLabel: string;
  presenceIntensity: number;
  coherence: number;
  collapseTendency: number;
  llmRouting: {
    activeProviders: string[];
    lastModelUsed: string;
  };
  nodeTopology: {
    totalNodes: number;
    healthyNodes: number;
    degradedNodes: number;
  };
  costSummary: {
    totalUsd: number;
    tokensInput: number;
    tokensOutput: number;
  };

  // === 新增：维态面板数据 ===
  // 设备拓扑
  topologyNodes: Array<{
    id: string;
    label: string;
    role: 'controller' | 'participant' | 'gateway' | 'wearable';
    status: 'online' | 'degraded' | 'offline';
    x: number;
    y: number;
    lastSeen: number;
    messageCount: number;
  }>;
  topologyEdges: Array<{
    from: string;
    to: string;
    label?: string;
    active: boolean;
    messageRate: number;
  }>;

  // Mesh 会话
  meshSession: {
    sessionId: string;
    status: 'active' | 'pending' | 'closed';
    barrierStatus: string;
    tickSequence: number;
    participants: Array<{
      nodeId: string;
      role: string;
      status: 'active' | 'idle' | 'disconnected';
      lastSeen: number;
    }>;
    createdAt: number;
  };

  // NATS worker(Mesh 区显示/开关)
  natsWorker: {
    running: boolean;
    workerId: string;
    enabledByEnv: boolean;
  };

  // OpenClawd 状态
  openclawdStatus: {
    runtimeState: 'RUNNING' | 'PAUSED' | 'ERROR' | 'RESTARTING';
    phase: 'silent' | 'liminal' | 'manifest';
    coherence: number;
    activeTasks: number;
    completedTasks: number;
    connectedDevices: number;
    smartDevices?: number;
    lastTick: number;
    uptime: number;
  };

  // NATS 消息
  natsMessages: Array<{
    id: string;
    timestamp: number;
    topic: string;
    direction: 'in' | 'out';
    payload: string;
    msgType: string;
  }>;

  // URL 哨兵抓到的"缺协议头请求 URL"记录(平时为空;有才在诊断抽屉里显示)
  // 智能设备明细(UDM iot:HA 镜像 + mDNS 发现),维态 tab 渲染
  smartDeviceList: Array<{
    deviceId: string;
    name: string;
    domain: string;
    state: string;
    online: boolean;
    protocol: string;
  }>;

  diagnostics: Array<{
    ts: string;
    url: string;
    culprit: string;
  }>;

  // 启动每阶段耗时(定位"加载半天"卡在哪段)
  startupTiming: Array<{
    name: string;
    seconds: number;
    ts: string;
  }>;

  // MCP 服务器状态（星元面板花草丛）
  mcpServers: Array<{
    name: string;
    url: string;
    status: 'online' | 'offline' | 'error' | 'unknown';
    toolsCount: number;
  }>;

  // Skill 状态（星元面板花草丛）
  skills: Array<{
    name: string;
    version: string;
    status: 'loaded' | 'unloaded' | 'error' | 'disabled';
    description: string;
  }>;

  // 自发注意力（在场栏实时显示"它正在看/听什么、刚才为何开口/沉默"）
  ambient: {
    seeing: boolean;
    hearing: boolean;
    action: string;      // speak | silent | delegate | ''
    rationale: string;
    ts: number;
  };
}

interface UsePanelDataReturn {
  panelData: PanelData;
  loading: boolean;
  error: string | null;
}

// ── 默认值 ───────────────────────────────────────

const DEFAULT_PANEL_DATA: PanelData = {
  phase: 'silent',
  phaseLabel: 'STANDBY',
  presenceIntensity: 0.0,
  coherence: 0.0,
  collapseTendency: 0.0,
  llmRouting: {
    activeProviders: [],
    lastModelUsed: '',
  },
  nodeTopology: {
    totalNodes: 0,
    healthyNodes: 0,
    degradedNodes: 0,
  },
  costSummary: {
    totalUsd: 0.0,
    tokensInput: 0,
    tokensOutput: 0,
  },
  // 初始空值：后端首次推送后替换
  topologyNodes: [],
  topologyEdges: [],
  meshSession: {
    sessionId: '',
    status: 'closed',
    barrierStatus: 'n/a',
    tickSequence: 0,
    participants: [],
    createdAt: 0,
  },
  natsWorker: {
    running: false,
    workerId: '',
    enabledByEnv: false,
  },
  openclawdStatus: {
    runtimeState: 'RESTARTING',
    phase: 'silent',
    coherence: 0,
    activeTasks: 0,
    completedTasks: 0,
    connectedDevices: 0,
    smartDevices: 0,
    lastTick: 0,
    uptime: 0,
  },
  natsMessages: [],
  smartDeviceList: [],
  diagnostics: [],
  startupTiming: [],
  mcpServers: [],
  skills: [],
  ambient: { seeing: false, hearing: false, action: '', rationale: '', ts: 0 },
};

// ── IPC 驱动 Hook ────────────────────────────────

export function usePanelData(): UsePanelDataReturn {
  const [panelData, setPanelData] = useState<PanelData>(DEFAULT_PANEL_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const handlerRef = useRef<((() => void)) | null>(null);

  useEffect(() => {
    // IPC 通道可用性(缺失时不再放弃——退化为 WS-only 模式,浏览器预览也能拿到数据)
    const ipcAvailable =
      typeof window !== 'undefined' && !!(window as any).galaxyAPI?.onBackendState;
    if (!ipcAvailable) {
      console.warn('[Panel] IPC channel not available, WS-only mode');
    }

    // 注册 IPC 状态回调
    const handleState = (state: any) => {
      try {
        const payload = state?.payload || state;
        const phase = (payload.tri_state_phase || payload.phase || 'silent') as Phase;
        const intensity = payload.presence_intensity || 0;

        // 根据 intensity 映射 phase（如果后端未提供 tri_state_phase）
        let mappedPhase: Phase = phase;
        if (!payload.tri_state_phase && intensity > 0) {
          if (intensity < 0.33) mappedPhase = 'silent';
          else if (intensity < 0.66) mappedPhase = 'liminal';
          else mappedPhase = 'manifest';
        }

        // ambient 只由 bridge 的 state_event 携带；/panel/feed 慢轮询里没有此字段。
        // 用函数式更新在缺省时【保留上一次】ambient，避免两路交替刷新时闪烁掉。
        const incomingAmbient = payload.ambient;
        setPanelData((prev) => ({
          phase: mappedPhase,
          phaseLabel: mappedPhase.toUpperCase(),
          presenceIntensity: intensity,
          coherence: payload.coherence ?? 0,
          collapseTendency: payload.collapse_tendency ?? 0,
          llmRouting: {
            activeProviders: payload.llm_routing?.active_providers || [],
            lastModelUsed: payload.llm_routing?.last_model_used || '',
          },
          nodeTopology: {
            totalNodes: payload.node_topology?.total_nodes ?? 0,
            healthyNodes: payload.node_topology?.healthy_nodes ?? 0,
            degradedNodes: payload.node_topology?.degraded_nodes ?? 0,
          },
          costSummary: {
            totalUsd: payload.cost_summary?.total_usd || 0,
            tokensInput: payload.cost_summary?.tokens_input || 0,
            tokensOutput: payload.cost_summary?.tokens_output || 0,
          },
          topologyNodes: payload.topology_nodes || DEFAULT_PANEL_DATA.topologyNodes,
          topologyEdges: payload.topology_edges || DEFAULT_PANEL_DATA.topologyEdges,
          meshSession: payload.mesh_session || DEFAULT_PANEL_DATA.meshSession,
          natsWorker: payload.nats_worker
            ? {
                running: !!payload.nats_worker.running,
                workerId: payload.nats_worker.worker_id || '',
                enabledByEnv: !!payload.nats_worker.enabled_by_env,
              }
            : DEFAULT_PANEL_DATA.natsWorker,
          openclawdStatus: payload.openclawd_status || DEFAULT_PANEL_DATA.openclawdStatus,
          natsMessages: payload.nats_messages || DEFAULT_PANEL_DATA.natsMessages,
          smartDeviceList: payload.smart_devices || DEFAULT_PANEL_DATA.smartDeviceList,
          diagnostics: payload.diagnostics || DEFAULT_PANEL_DATA.diagnostics,
          startupTiming: payload.startup_timing || DEFAULT_PANEL_DATA.startupTiming,
          mcpServers: payload.mcp_servers || DEFAULT_PANEL_DATA.mcpServers,
          skills: payload.skills || DEFAULT_PANEL_DATA.skills,
          ambient: incomingAmbient ? {
            seeing: !!incomingAmbient.seeing,
            hearing: !!incomingAmbient.hearing,
            action: incomingAmbient.action || '',
            rationale: incomingAmbient.rationale || '',
            ts: incomingAmbient.ts || 0,
          } : prev.ambient,
        }));
        setLoading(false);
        setError(null);
      } catch (e) {
        console.error('[Panel] Failed to parse state:', e);
        setError('Parse error');
      }
    };

    // 注册 IPC 状态回调（兜底通道），保存 cleanup 函数以防止内存泄漏
    const cleanup = ipcAvailable
      ? (window as any).galaxyAPI.onBackendState(handleState)
      : null;
    if (cleanup) handlerRef.current = cleanup;
    setLoading(false);

    // 推代替拉（主通道）:直连后端 /ws/desktop-presence,消费 panel_feed 推送帧。
    // 后端在任意状态事件(设备/任务/技能/mesh…)后防抖推送【整份 feed】——
    // 事件→UI 毫秒级;Electron 主进程的慢轮询(已降频 30s)只作断线兜底。
    let ws: WebSocket | null = null;
    let wsRetry: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const connectWs = async () => {
      try {
        const base = await getBackendUrl();
        if (disposed) return;
        ws = new WebSocket(base.replace(/^http/, 'ws') + '/ws/desktop-presence');
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data);
            if (msg?.type === 'panel_feed' && msg.feed) handleState(msg.feed);
          } catch { /* 非 JSON / 其它帧类型忽略(state_event 由 useWebSocket 消费) */ }
        };
        ws.onclose = () => { if (!disposed) wsRetry = setTimeout(connectWs, 3000); };
        ws.onerror = () => { try { ws?.close(); } catch { /* noop */ } };
      } catch { if (!disposed) wsRetry = setTimeout(connectWs, 3000); }
    };
    connectWs();

    return () => {
      // 取消 IPC 订阅 + 关闭 WS 推送通道
      if (handlerRef.current) handlerRef.current();
      handlerRef.current = null;
      disposed = true;
      if (wsRetry) clearTimeout(wsRetry);
      try { ws?.close(); } catch { /* noop */ }
    };
  }, []);

  return { panelData, loading, error };
}
