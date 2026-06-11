/**
 * VitalityTab — 维态面板
 * 左窄：ProviderPanel（模型配置）
 * 右宽：OakTreeCanvas（橡树根系可视化 + MCP/Skill 花草丛）
 */

import React, { useState, useCallback } from 'react';
import type { PanelData } from '@/hooks/usePanelData';
import ProviderPanel, { DEFAULT_PROVIDERS, type ProviderConfig } from './ProviderPanel';
import OakTreeCanvas, { type TreeNode, generateFractalNodes } from './OakTreeCanvas';
import './VitalityTab.css';

interface Props {
  data: PanelData;
}

const VitalityTab: React.FC<Props> = ({ data }) => {
  const [providers, setProviders] = useState<ProviderConfig[]>(DEFAULT_PROVIDERS);
  const [nodes] = useState<TreeNode[]>(generateFractalNodes());
  const [hoveredNode, setHoveredNode] = useState<TreeNode | null>(null);

  const handleToggleModel = useCallback((providerId: string, modelId: string) => {
    setProviders((prev) =>
      prev.map((p) =>
        p.id === providerId
          ? {
              ...p,
              models: p.models.map((m) =>
                m.id === modelId ? { ...m, active: !m.active } : m
              ),
            }
          : p
      )
    );
  }, []);

  const handleApiKeyChange = useCallback((providerId: string, key: string) => {
    setProviders((prev) =>
      prev.map((p) => (p.id === providerId ? { ...p, apiKey: key } : p))
    );
  }, []);

  // 构建 provider clusters for canvas
  const clusters = providers.map((p) => {
    const clusterMap: Record<string, { x: number; y: number }> = {
      anthropic: { x: 0.20, y: 0.12 },
      openai: { x: 0.42, y: 0.08 },
      deepseek: { x: 0.62, y: 0.10 },
      google: { x: 0.80, y: 0.14 },
      qwen: { x: 0.35, y: 0.20 },
      xai: { x: 0.72, y: 0.22 },
      step: { x: 0.15, y: 0.05 },
      zhipu: { x: 0.55, y: 0.04 },
      minimax: { x: 0.88, y: 0.08 },
      mimo: { x: 0.28, y: 0.18 },
      mistral: { x: 0.50, y: 0.20 },
      moonshot: { x: 0.68, y: 0.18 },
      perplexity: { x: 0.10, y: 0.22 },
      groq: { x: 0.85, y: 0.20 },
      ollama: { x: 0.45, y: 0.14 },
      hf_local: { x: 0.78, y: 0.06 },
    };
    const pos = clusterMap[p.id] || { x: 0.5, y: 0.15 };
    const activeModel = p.models.find((m) => m.active);
    return {
      id: p.id,
      name: p.name,
      color: p.color,
      x: pos.x,
      y: pos.y,
      models: p.models.map((m) => m.id),
      activeModel: activeModel?.id || p.models[0]?.id || 'unknown',
    };
  });

  return (
    <div className="vitality-tab-v2">
      {/* 左侧：模型配置 */}
      <div className="vitality-left-v2">
        <ProviderPanel
          providers={providers}
          onToggleModel={handleToggleModel}
          onApiKeyChange={handleApiKeyChange}
        />
      </div>

      {/* 右侧：橡树根系 + MCP/Skill 花草丛 */}
      <div className="vitality-right-v2">
        <OakTreeCanvas
          nodes={nodes}
          providers={clusters}
          onNodeHover={setHoveredNode}
          mcpServers={data.mcpServers}
          skills={data.skills}
        />
        {hoveredNode && (
          <div className="node-info-bar">
            <span className="node-info-id">{hoveredNode.id}</span>
            <span className="node-info-role">{hoveredNode.role}</span>
            <span className={`node-info-status ${hoveredNode.status}`}>{hoveredNode.status}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default React.memo(VitalityTab);
