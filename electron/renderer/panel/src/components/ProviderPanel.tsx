/**
 * ProviderPanel — 模型提供商配置面板
 * 左侧窄栏：提供商列表 + 模型选择 + API Key 填入
 */

import React, { useState, useCallback } from 'react';

// ── 类型 ─────────────────────────────────────────

export interface ProviderModel {
  id: string;
  name: string;
  active: boolean;
}

export interface ProviderConfig {
  id: string;
  name: string;
  color: string;
  models: ProviderModel[];
  apiKey: string;
  status: 'online' | 'offline' | 'degraded';
  usagePercent: number;
}

interface Props {
  providers: ProviderConfig[];
  onToggleModel: (providerId: string, modelId: string) => void;
  onApiKeyChange: (providerId: string, key: string) => void;
}

// ── Mock 数据 ────────────────────────────────────

export const DEFAULT_PROVIDERS: ProviderConfig[] = [
  {
    id: 'anthropic',
    name: 'Anthropic',
    color: '#d4a030',
    models: [
      { id: 'claude-fable-5', name: 'Claude Fable 5', active: true },
      { id: 'claude-opus-4.8', name: 'Claude Opus 4.8', active: false },
      { id: 'claude-sonnet-4.6', name: 'Claude Sonnet 4.6', active: false },
    ],
    apiKey: '',
    status: 'online',
    usagePercent: 42,
  },
  {
    id: 'openai',
    name: 'OpenAI',
    color: '#10a37f',
    models: [
      { id: 'gpt-5.5', name: 'GPT-5.5', active: true },
      { id: 'gpt-5', name: 'GPT-5', active: false },
      { id: 'gpt-4o', name: 'GPT-4o', active: false },
    ],
    apiKey: '',
    status: 'online',
    usagePercent: 28,
  },
  {
    id: 'deepseek',
    name: 'DeepSeek',
    color: '#4f6ef7',
    models: [
      { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', active: true },
      { id: 'deepseek-v3', name: 'DeepSeek V3', active: false },
    ],
    apiKey: '',
    status: 'online',
    usagePercent: 15,
  },
  {
    id: 'google',
    name: 'Google',
    color: '#4285f4',
    models: [
      { id: 'gemini-3.1-pro', name: 'Gemini 3.1 Pro', active: false },
      { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', active: false },
    ],
    apiKey: '',
    status: 'degraded',
    usagePercent: 8,
  },
  {
    id: 'qwen',
    name: 'Qwen',
    color: '#615ced',
    models: [
      { id: 'qwen3-235b', name: 'Qwen3 235B', active: false },
      { id: 'qwen3-30b', name: 'Qwen3 30B', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 4,
  },
  {
    id: 'xai',
    name: 'xAI',
    color: '#1d9bf0',
    models: [
      { id: 'grok-3', name: 'Grok 3', active: false },
      { id: 'grok-3-mini', name: 'Grok 3 Mini', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 3,
  },
];

// ── 状态色 ───────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  online: 'rgba(100, 200, 130, 0.8)',
  degraded: 'rgba(220, 180, 80, 0.8)',
  offline: 'rgba(200, 80, 80, 0.5)',
};

// ── 组件 ─────────────────────────────────────────

const ProviderPanel: React.FC<Props> = ({ providers, onToggleModel, onApiKeyChange }) => {
  const [showKeyMap, setShowKeyMap] = useState<Record<string, boolean>>({});

  const toggleShowKey = useCallback((providerId: string) => {
    setShowKeyMap((prev) => ({ ...prev, [providerId]: !prev[providerId] }));
  }, []);

  return (
    <div className="provider-panel">
      <div className="panel-header">
        <h2 className="panel-title">模型路由</h2>
        <span className="panel-subtitle">{providers.length} 提供商</span>
      </div>

      <div className="provider-list-vitality">
        {providers.map((provider) => (
          <div key={provider.id} className="provider-card-vitality">
            {/* 头部：名称 + 状态 */}
            <div className="provider-header">
              <div className="provider-id">
                <div
                  className="provider-dot"
                  style={{ background: provider.color }}
                />
                <span className="provider-name" style={{ color: provider.color }}>
                  {provider.name}
                </span>
              </div>
              <div className="provider-meta">
                <span
                  className="status-dot"
                  style={{ background: STATUS_COLOR[provider.status] }}
                />
                <span className="usage-text">{provider.usagePercent}%</span>
              </div>
            </div>

            {/* 使用率条 */}
            <div className="usage-bar-wrap">
              <div
                className="usage-bar-fill"
                style={{
                  width: `${provider.usagePercent}%`,
                  background: `linear-gradient(90deg, ${provider.color}88, ${provider.color}33)`,
                }}
              />
            </div>

            {/* 模型列表 */}
            <div className="model-list-vitality">
              {provider.models.map((model) => (
                <label
                  key={model.id}
                  className={`model-item-vitality ${model.active ? 'active' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={model.active}
                    onChange={() => onToggleModel(provider.id, model.id)}
                    className="model-checkbox"
                  />
                  <span className="model-name-vitality">{model.name}</span>
                  {model.active && (
                    <span className="model-badge" style={{ background: `${provider.color}33`, color: provider.color }}>
                      ON
                    </span>
                  )}
                </label>
              ))}
            </div>

            {/* API Key 输入 */}
            <div className="api-key-row">
              <input
                type={showKeyMap[provider.id] ? 'text' : 'password'}
                value={provider.apiKey}
                onChange={(e) => onApiKeyChange(provider.id, e.target.value)}
                placeholder={`${provider.name} API Key`}
                className="api-key-input-vitality"
              />
              <button
                className="eye-btn"
                onClick={() => toggleShowKey(provider.id)}
                type="button"
              >
                {showKeyMap[provider.id] ? '🙈' : '👁'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default React.memo(ProviderPanel);
