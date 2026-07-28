/**
 * usePanelData — IPC 驱动 Hook
 * 通过 Electron preload.js 暴露的 galaxyAPI.onBackendState 接收状态推送
 */

import { useEffect, useRef, useState } from 'react';
import { subscribePresence } from '@/lib/presenceSocket';
import { _mapPhaseToken } from './usePhase';
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

  // NATS worker(Mesh 区显示/开关)。starting/lastError 配合后端
  // start_background()(toggle 立即返回、真正连接放后台跑)——
  // 由本 WS 推送持续反映"正在启动"与失败原因,而不是等一次可能
  // 很慢的 HTTP 往返。
  natsWorker: {
    running: boolean;
    workerId: string;
    enabledByEnv: boolean;
    starting: boolean;
    lastError: string | null;
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
    starting: false,
    lastError: null,
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
        // 真 bug 修复:后端在场桥用"存在模式"词汇广播(static/liminal/manifest,
        // 见 core/lumiv_websocket_bridge._build_message),而面板三态词汇是
        // silent/liminal/manifest——这里此前直接把原始 payload.phase(如
        // "static")强制类型转换成 Phase,从未归一化。WS 未连上/重连窗口期间
        // 走的正是这条 IPC 直推路径,会短暂把 phase 设成无效的 "static",导致
        // 在场状态标签渲染空白、光球丢失待机样式、三态圆点没有一个被点亮。
        // 复用 usePhase.ts 已有的归一化(WS 消息路径早就这么做了)。
        const rawPhase = payload.tri_state_phase || payload.phase;
        const phase: Phase = (rawPhase && _mapPhaseToken(String(rawPhase))) || 'silent';

        // ambient 只由 bridge 的 state_event 携带；/panel/feed 慢轮询里没有此字段。
        // 用函数式更新在缺省时【保留上一次】ambient，避免两路交替刷新时闪烁掉。
        const incomingAmbient = payload.ambient;

        // 真 bug 修复(headline finding):handleState 被两条完全不同形状的推送
        // 共用——高频小帧 state_event(core/lumiv_websocket_bridge._build_message:
        // 只有 phase/depth_factor/intent/speaking/mode/source/ambient,见该函数
        // 定义)和低频富帧 panel_feed(core/routes/panel.py::build_panel_feed:
        // mesh/topology/nats/cost/llm_routing/mcp/skills 等一整套维态数据)。此前
        // 除 ambient 外的每个字段都用 `payload.xxx || DEFAULT_PANEL_DATA.xxx`
        // 兜底——state_event 完全不携带这些富字段,于是每一次相位切换/自发注意力
        // tick(几乎每次对话都会触发多次)都会把维态/能力/诊断面板的真实数据整体
        // 闪回空/零,直到下一次真实设备/任务/技能/mesh 事件或 30s IPC 兜底轮询
        // 才恢复。现在把 ambient 已经用的"缺省时保留 prev"模式推广到全部富字段——
        // 只有真正收到该字段时才更新,state_event 这类不携带它们的推送不再覆盖。
        setPanelData((prev) => ({
          phase,
          phaseLabel: phase.toUpperCase(),
          presenceIntensity: payload.presence_intensity ?? prev.presenceIntensity,
          coherence: payload.coherence ?? prev.coherence,
          collapseTendency: payload.collapse_tendency ?? prev.collapseTendency,
          llmRouting: payload.llm_routing
            ? {
                activeProviders: payload.llm_routing.active_providers || [],
                lastModelUsed: payload.llm_routing.last_model_used || '',
              }
            : prev.llmRouting,
          nodeTopology: payload.node_topology
            ? {
                totalNodes: payload.node_topology.total_nodes ?? 0,
                healthyNodes: payload.node_topology.healthy_nodes ?? 0,
                degradedNodes: payload.node_topology.degraded_nodes ?? 0,
              }
            : prev.nodeTopology,
          costSummary: payload.cost_summary
            ? {
                totalUsd: payload.cost_summary.total_usd || 0,
                tokensInput: payload.cost_summary.tokens_input || 0,
                tokensOutput: payload.cost_summary.tokens_output || 0,
              }
            : prev.costSummary,
          topologyNodes: payload.topology_nodes || prev.topologyNodes,
          topologyEdges: payload.topology_edges || prev.topologyEdges,
          meshSession: payload.mesh_session || prev.meshSession,
          natsWorker: payload.nats_worker
            ? {
                running: !!payload.nats_worker.running,
                workerId: payload.nats_worker.worker_id || '',
                enabledByEnv: !!payload.nats_worker.enabled_by_env,
                starting: !!payload.nats_worker.starting,
                lastError: payload.nats_worker.last_error ?? null,
              }
            : prev.natsWorker,
          openclawdStatus: payload.openclawd_status || prev.openclawdStatus,
          natsMessages: payload.nats_messages || prev.natsMessages,
          smartDeviceList: payload.smart_devices || prev.smartDeviceList,
          diagnostics: payload.diagnostics || prev.diagnostics,
          startupTiming: payload.startup_timing || prev.startupTiming,
          mcpServers: payload.mcp_servers || prev.mcpServers,
          skills: payload.skills || prev.skills,
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

    // 推代替拉（主通道）:经共享单例连接消费 panel_feed 推送帧(收敛修复:
    // 此前这里自建第二条 WebSocket 连同一端点,与 useWebSocket 的连接并存,
    // 后端每次广播发两遍;现在两个消费方共用 lib/presenceSocket 一条连接,
    // 各按帧类型自取)。后端在任意状态事件后防抖推送【整份 feed】——
    // 事件→UI 毫秒级;Electron 主进程的慢轮询(已降频 30s)只作断线兜底。
    const unsubscribePresence = subscribePresence((msg) => {
      if (msg?.type === 'panel_feed' && msg.feed) handleState(msg.feed);
      // 其它帧类型(state_event 等)由 useWebSocket 消费,这里忽略
    });

    return () => {
      // 取消 IPC 订阅 + 退订共享 WS 通道
      if (handlerRef.current) handlerRef.current();
      handlerRef.current = null;
      unsubscribePresence();
    };
  }, []);

  return { panelData, loading, error };
}
