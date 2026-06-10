/**
 * usePanelData — AIP v3 格式轮询 Hook
 * 替换原有的 useWebSocket + usePhase
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { Phase } from '@/types/phase';

// ── AIP v3 类型定义 ──────────────────────────────

export interface AIPV3Payload {
  tri_state_phase: string;
  presence_intensity: number;
  coherence: number;
  continuum_state: {
    phase: string;
    presence_intensity: number;
    coherence: number;
    collapse_tendency: number;
  };
  llm_routing: {
    active_providers: string[];
    last_model_used: string;
  };
  node_topology: {
    total_nodes: number;
    healthy_nodes: number;
    degraded_nodes: number;
  };
  cost_summary: {
    total_usd: number;
    tokens_input: number;
    tokens_output: number;
  };
}

export interface AIPV3Response {
  type: string;
  aip_version: string;
  source: string;
  timestamp: number;
  payload: AIPV3Payload;
}

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
  refresh: () => void;
}

// ── Mock 降级数据 ────────────────────────────────

const MOCK_PANEL_DATA: PanelData = {
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
    totalNodes: 47,
    healthyNodes: 45,
    degradedNodes: 2,
  },
  costSummary: {
    totalUsd: 12.45,
    tokensInput: 456000,
    tokensOutput: 89000,
  },
};

// ── Phase 解析 ───────────────────────────────────

function parsePhase(raw: string | undefined): Phase {
  if (!raw) return 'silent';
  const p = raw.toLowerCase();
  if (p === 'silent' || p === 'standby') return 'silent';
  if (p === 'liminal' || p === 'thinking' || p === 'processing') return 'liminal';
  if (p === 'manifest' || p === 'online' || p === 'active') return 'manifest';
  return 'silent';
}

function toPhaseLabel(phase: Phase): string {
  switch (phase) {
    case 'silent':
      return 'STANDBY';
    case 'liminal':
      return 'THINKING...';
    case 'manifest':
      return 'ONLINE';
  }
}

// ── API 配置 ─────────────────────────────────────

const API_URL = 'http://localhost:8000/api/v1/panel/unified';
const POLL_INTERVAL = 2000;

// ── Hook ─────────────────────────────────────────

export function usePanelData(): UsePanelDataReturn {
  const [panelData, setPanelData] = useState<PanelData>(MOCK_PANEL_DATA);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval>>();

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(API_URL, {
        method: 'GET',
        headers: { Accept: 'application/json' },
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}: ${res.statusText}`);
      }

      const json = (await res.json()) as AIPV3Response;

      // 校验 AIP v3 格式
      if (json.type !== 'panel_payload' || json.aip_version !== '3.0') {
        console.warn('[Panel] AIP v3 format mismatch, using mock data');
        setPanelData(MOCK_PANEL_DATA);
        setError('AIP v3 format mismatch');
        setLoading(false);
        return;
      }

      const payload = json.payload;
      const phase = parsePhase(payload.tri_state_phase);

      setPanelData({
        phase,
        phaseLabel: toPhaseLabel(phase),
        presenceIntensity: payload.presence_intensity ?? 0,
        coherence: payload.coherence ?? 0,
        collapseTendency: payload.continuum_state?.collapse_tendency ?? 0,
        llmRouting: {
          activeProviders: payload.llm_routing?.active_providers ?? [],
          lastModelUsed: payload.llm_routing?.last_model_used ?? 'unknown',
        },
        nodeTopology: {
          totalNodes: payload.node_topology?.total_nodes ?? 0,
          healthyNodes: payload.node_topology?.healthy_nodes ?? 0,
          degradedNodes: payload.node_topology?.degraded_nodes ?? 0,
        },
        costSummary: {
          totalUsd: payload.cost_summary?.total_usd ?? 0,
          tokensInput: payload.cost_summary?.tokens_input ?? 0,
          tokensOutput: payload.cost_summary?.tokens_output ?? 0,
        },
      });

      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      console.warn(`[Panel] API error: ${msg}, using mock data`);
      // 降级到 mock 数据（保持当前 phase）
      setPanelData((prev) => ({
        ...MOCK_PANEL_DATA,
        phase: prev.phase,
        phaseLabel: prev.phaseLabel,
      }));
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  // 轮询
  useEffect(() => {
    setLoading(true);
    fetchData();

    intervalRef.current = setInterval(fetchData, POLL_INTERVAL);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [fetchData]);

  const refresh = useCallback(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]);

  return { panelData, loading, error, refresh };
}
