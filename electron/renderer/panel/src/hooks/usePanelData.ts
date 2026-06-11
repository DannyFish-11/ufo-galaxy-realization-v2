/**
 * usePanelData — IPC 驱动 Hook
 * 通过 Electron preload.js 暴露的 galaxyAPI.onBackendState 接收状态推送
 */

import { useEffect, useRef, useState } from 'react';
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

  // OpenClawd 状态
  openclawdStatus: {
    runtimeState: 'RUNNING' | 'PAUSED' | 'ERROR' | 'RESTARTING';
    phase: 'silent' | 'liminal' | 'manifest';
    coherence: number;
    activeTasks: number;
    completedTasks: number;
    connectedDevices: number;
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

  // === 新增：MCP/Skill 状态 ===
  mcpServers: Array<{
    id: string;
    name: string;
    status: 'healthy' | 'degraded' | 'offline';
    active: boolean;
    toolCount: number;
    activeTools: number;
  }>;
  skills: Array<{
    id: string;
    name: string;
    status: 'healthy' | 'degraded' | 'offline';
    active: boolean;
    callCount: number;
  }>;
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
  coherence: 0.95,
  collapseTendency: 0.0,
  llmRouting: {
    activeProviders: ['anthropic', 'openai', 'deepseek'],
    lastModelUsed: 'claude-fable-5',
  },
  nodeTopology: {
    totalNodes: 120,
    healthyNodes: 118,
    degradedNodes: 2,
  },
  costSummary: {
    totalUsd: 0.0,
    tokensInput: 0,
    tokensOutput: 0,
  },

  // === 维态面板默认值 ===
  topologyNodes: [
    { id: 'desktop_01', label: 'Desktop', role: 'controller', status: 'online', x: 0.5, y: 0.2, lastSeen: Date.now(), messageCount: 12847 },
    { id: 'android_01', label: 'Android', role: 'participant', status: 'online', x: 0.2, y: 0.6, lastSeen: Date.now(), messageCount: 8932 },
    { id: 'wear_01', label: 'WearOS', role: 'wearable', status: 'online', x: 0.8, y: 0.6, lastSeen: Date.now(), messageCount: 3456 },
    { id: 'gateway_01', label: 'Gateway', role: 'gateway', status: 'online', x: 0.5, y: 0.9, lastSeen: Date.now(), messageCount: 21500 },
  ],
  topologyEdges: [
    { from: 'desktop_01', to: 'gateway_01', label: 'mesh', active: true, messageRate: 120 },
    { from: 'android_01', to: 'gateway_01', label: 'mesh', active: true, messageRate: 85 },
    { from: 'wear_01', to: 'gateway_01', label: 'coord', active: true, messageRate: 45 },
    { from: 'desktop_01', to: 'android_01', label: 'sync', active: true, messageRate: 30 },
  ],
  meshSession: {
    sessionId: 'mesh-session-001',
    status: 'active',
    barrierStatus: 'open',
    tickSequence: 12847,
    participants: [
      { nodeId: 'desktop_01', role: 'controller', status: 'active', lastSeen: Date.now() },
      { nodeId: 'android_01', role: 'participant', status: 'active', lastSeen: Date.now() },
      { nodeId: 'wear_01', role: 'wearable', status: 'active', lastSeen: Date.now() },
    ],
    createdAt: Date.now() - 3600000,
  },
  openclawdStatus: {
    runtimeState: 'RUNNING',
    phase: 'manifest',
    coherence: 0.97,
    activeTasks: 3,
    completedTasks: 1527,
    connectedDevices: 3,
    lastTick: Date.now(),
    uptime: 3600,
  },
  natsMessages: [
    { id: 'msg-001', timestamp: Date.now() - 1000, topic: 'mesh.join', direction: 'in', payload: '{"nodeId":"android_01"}', msgType: 'mesh_join' },
    { id: 'msg-002', timestamp: Date.now() - 2000, topic: 'coord.sync', direction: 'out', payload: '{"tick":12847}', msgType: 'coord_sync' },
    { id: 'msg-003', timestamp: Date.now() - 3000, topic: 'human.input', direction: 'in', payload: '{"nodeId":"wear_01","type":"voice"}', msgType: 'human_input' },
    { id: 'msg-004', timestamp: Date.now() - 4000, topic: 'mesh.heartbeat', direction: 'in', payload: '{"nodeId":"desktop_01","status":"ok"}', msgType: 'heartbeat' },
    { id: 'msg-005', timestamp: Date.now() - 5000, topic: 'llm.route', direction: 'out', payload: '{"model":"claude-fable-5"}', msgType: 'llm_route' },
  ],

  // === MCP/Skill 默认值 ===
  mcpServers: [
    { id: 'filesystem', name: 'FileSystem', status: 'healthy', active: true, toolCount: 8, activeTools: 6 },
    { id: 'browser', name: 'Browser', status: 'healthy', active: true, toolCount: 6, activeTools: 5 },
    { id: 'database', name: 'Database', status: 'healthy', active: true, toolCount: 10, activeTools: 8 },
    { id: 'search', name: 'Search', status: 'degraded', active: true, toolCount: 4, activeTools: 2 },
    { id: 'terminal', name: 'Terminal', status: 'healthy', active: true, toolCount: 5, activeTools: 5 },
  ],
  skills: [
    { id: 'code-gen', name: 'CodeGen', status: 'healthy', active: true, callCount: 1543 },
    { id: 'debug', name: 'Debug', status: 'healthy', active: true, callCount: 892 },
    { id: 'review', name: 'Review', status: 'healthy', active: true, callCount: 1205 },
    { id: 'doc-write', name: 'DocWrite', status: 'healthy', active: true, callCount: 678 },
    { id: 'test-gen', name: 'TestGen', status: 'degraded', active: true, callCount: 445 },
    { id: 'refactor', name: 'Refactor', status: 'healthy', active: true, callCount: 567 },
    { id: 'analyze', name: 'Analyze', status: 'healthy', active: true, callCount: 2341 },
    { id: 'deploy', name: 'Deploy', status: 'offline', active: false, callCount: 0 },
  ],
};

// ── IPC 驱动 Hook ────────────────────────────────

export function usePanelData(): UsePanelDataReturn {
  const [panelData, setPanelData] = useState<PanelData>(DEFAULT_PANEL_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const handlerRef = useRef<((() => void)) | null>(null);

  useEffect(() => {
    // 检查 IPC 通道是否可用
    if (typeof window === 'undefined' || !(window as any).galaxyAPI?.onBackendState) {
      console.warn('[Panel] IPC channel not available, using defaults');
      setLoading(false);
      setError('IPC not available');
      return;
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

        setPanelData({
          phase: mappedPhase,
          phaseLabel: mappedPhase.toUpperCase(),
          presenceIntensity: intensity,
          coherence: payload.coherence || 0.95,
          collapseTendency: payload.collapse_tendency || 0,
          llmRouting: {
            activeProviders: payload.llm_routing?.active_providers || ['anthropic', 'openai', 'deepseek'],
            lastModelUsed: payload.llm_routing?.last_model_used || 'unknown',
          },
          nodeTopology: {
            totalNodes: payload.node_topology?.total_nodes || 120,
            healthyNodes: payload.node_topology?.healthy_nodes || 118,
            degradedNodes: payload.node_topology?.degraded_nodes || 2,
          },
          costSummary: {
            totalUsd: payload.cost_summary?.total_usd || 0,
            tokensInput: payload.cost_summary?.tokens_input || 0,
            tokensOutput: payload.cost_summary?.tokens_output || 0,
          },
          topologyNodes: payload.topology_nodes || DEFAULT_PANEL_DATA.topologyNodes,
          topologyEdges: payload.topology_edges || DEFAULT_PANEL_DATA.topologyEdges,
          meshSession: payload.mesh_session || DEFAULT_PANEL_DATA.meshSession,
          openclawdStatus: payload.openclawd_status || DEFAULT_PANEL_DATA.openclawdStatus,
          natsMessages: payload.nats_messages || DEFAULT_PANEL_DATA.natsMessages,
          mcpServers: payload.mcp_servers || DEFAULT_PANEL_DATA.mcpServers,
          skills: payload.skills || DEFAULT_PANEL_DATA.skills,
        });
        setLoading(false);
        setError(null);
      } catch (e) {
        console.error('[Panel] Failed to parse state:', e);
        setError('Parse error');
      }
    };

    handlerRef.current = () => {};
    (window as any).galaxyAPI.onBackendState(handleState);
    setLoading(false);

    return () => {
      // IPC 通道不支持取消订阅，这里只是清理引用
      handlerRef.current = null;
    };
  }, []);

  return { panelData, loading, error };
}
