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

// 所有模型 ID 均来自 2026 年 6 月各厂商最新公开 API 文档
// Anthropic: claude-fable-5 (2026/6/9), Opus 4.8 (2026/5/28), Sonnet 4.6 (2026/2/17)
// OpenAI: GPT-5.5 (2026/4/23), GPT-5.5 Instant (2026/5/28 更新)
// DeepSeek: V4 Pro / V4 Flash (2026/4)
// Google: Gemini 3.5 Pro / Flash (2026/5/19)
// xAI: Grok 4.3 (2026/4/30), grok-4.1 已于 2026/5/15 退役
// Qwen: 3.7 Max / 3.7 Coder (2026/5/20), 3.6-27B (2026/4/22)
// Step: 3.7 Flash / Turbo (2026/5/28)
// Zhipu: GLM-5.1 / Flash (2026/4/8)
// MiniMax: M3 (2026/6/1), M2.7 (2026/3/18)
// Mistral: Large 3 (2026/5), Medium 3.5, Small 4
// Moonshot: Kimi K2.6 (2026/4/20, 1T 参数开源)
// Perplexity: Sonar Reasoning Pro / Pro
// Groq: Llama 4 Scout / Maverick (2026), Llama 3.3 70B
// Ollama: Gemma 4 系列 (12B/26B/31B + QAT 版本)
// HF Local: Qwen 3.6-27B / 35B-A3B
export const DEFAULT_PROVIDERS: ProviderConfig[] = [
  {
    id: 'anthropic',
    name: 'Anthropic',
    color: '#d4a57b',
    models: [
      { id: 'claude-fable-5', name: 'Claude Fable 5', active: true },
      { id: 'claude-opus-4-8', name: 'Claude Opus 4.8', active: false },
      { id: 'claude-sonnet-4-6', name: 'Claude Sonnet 4.6', active: false },
      { id: 'claude-haiku-4-5', name: 'Claude Haiku 4.5', active: false },
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
      { id: 'gpt-5.5-instant', name: 'GPT-5.5 Instant', active: false },
      { id: 'gpt-5.5-pro', name: 'GPT-5.5 Pro', active: false },
      { id: 'gpt-5.3-codex', name: 'GPT-5.3 Codex', active: false },
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
      { id: 'deepseek-v4-flash', name: 'DeepSeek V4 Flash', active: false },
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
      { id: 'gemini-3.5-pro', name: 'Gemini 3.5 Pro', active: false },
      { id: 'gemini-3.5-flash', name: 'Gemini 3.5 Flash', active: false },
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
      { id: 'qwen3.7-max', name: 'Qwen 3.7 Max', active: true },
      { id: 'qwen3.7-coder', name: 'Qwen 3.7 Coder', active: false },
      { id: 'qwen3.6-27b', name: 'Qwen 3.6 27B', active: false },
    ],
    apiKey: '',
    status: 'online',
    usagePercent: 4,
  },
  {
    id: 'xai',
    name: 'xAI',
    color: '#1d9bf0',
    models: [
      { id: 'grok-4.3', name: 'Grok 4.3', active: false },
      { id: 'grok-4.20', name: 'Grok 4.20', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 3,
  },
  {
    id: 'step',
    name: 'Step',
    color: '#1677ff',
    models: [
      { id: 'step-3.7-flash', name: 'Step 3.7 Flash', active: false },
      { id: 'step-3.7-turbo', name: 'Step 3.7 Turbo', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'zhipu',
    name: 'Zhipu',
    color: '#6b21a8',
    models: [
      { id: 'glm-5.1', name: 'GLM 5.1', active: false },
      { id: 'glm-5.1-flash', name: 'GLM 5.1 Flash', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'minimax',
    name: 'MiniMax',
    color: '#ec4899',
    models: [
      { id: 'minimax-m3', name: 'MiniMax M3', active: false },
      { id: 'minimax-m2.7', name: 'MiniMax M2.7', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'mimo',
    name: 'Mimo',
    color: '#14b8a6',
    models: [
      { id: 'mimo-v2.5-pro', name: 'Mimo V2.5 Pro', active: false },
      { id: 'mimo-v2.5-lite', name: 'Mimo V2.5 Lite', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'mistral',
    name: 'Mistral',
    color: '#fb923c',
    models: [
      { id: 'mistral-large-3', name: 'Mistral Large 3', active: false },
      { id: 'mistral-medium-3.5', name: 'Mistral Medium 3.5', active: false },
      { id: 'mistral-small-4', name: 'Mistral Small 4', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'moonshot',
    name: 'Moonshot',
    color: '#f59e0b',
    models: [
      { id: 'kimi-k2.6', name: 'Kimi K2.6', active: false },
      { id: 'kimi-k2.5', name: 'Kimi K2.5', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'perplexity',
    name: 'Perplexity',
    color: '#20b8cd',
    models: [
      { id: 'sonar-reasoning-pro', name: 'Sonar Reasoning Pro', active: false },
      { id: 'sonar-pro', name: 'Sonar Pro', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'groq',
    name: 'Groq',
    color: '#f55036',
    models: [
      { id: 'llama-4-scout', name: 'Llama 4 Scout', active: false },
      { id: 'llama-4-maverick', name: 'Llama 4 Maverick', active: false },
      { id: 'llama-3.3-70b-versatile', name: 'Llama 3.3 70B', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
  },
  {
    id: 'ollama',
    name: 'Ollama (Local)',
    color: '#ffffff',
    models: [
      { id: 'gemma4:e4b', name: 'Gemma4 E4B (default)', active: true },
      { id: 'gemma4:e2b', name: 'Gemma4 E2B', active: false },
      { id: 'gemma4:12b', name: 'Gemma4 12B Unified', active: false },
      { id: 'gemma4:26b', name: 'Gemma4 26B MoE', active: false },
      { id: 'gemma4:31b', name: 'Gemma4 31B Dense', active: false },
      { id: 'minicpm-o:4.5', name: 'MiniCPM-o 4.5', active: false },
      { id: 'minicpm-v:4.6', name: 'MiniCPM-V 4.6', active: false },
    ],
    apiKey: '',
    status: 'online',
    usagePercent: 0,
  },
  {
    id: 'hf_local',
    name: 'HF Local',
    color: '#ffd21e',
    models: [
      { id: 'Qwen/Qwen3.6-27B-Instruct', name: 'Qwen 3.6 27B', active: false },
      { id: 'Qwen/Qwen3.6-35B-A3B', name: 'Qwen 3.6 35B MoE', active: false },
    ],
    apiKey: '',
    status: 'offline',
    usagePercent: 0,
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
