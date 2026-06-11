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
