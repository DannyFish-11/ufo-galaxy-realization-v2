import { useCallback, useEffect, useRef, useState } from 'react';
import type { ConfigItem } from './SettingsTab';
import './ModelsTab.css';

/**
 * ModelsTab — 模型管理（温润高级感 / 硬件设置式）
 *
 * 复用后端 /api/config（与 SettingsTab 同一套存储），按"脑"的角色分组呈现：
 *   本地主脑（原生多模态） · 云端·开源优先 · 云端·专有 · 接入与聚合
 * 不新建后端、不重复存储；只是把"填 API + 选主脑 + 看状态"做成一个专门的页。
 */

// ── 本地主脑可选模型（与 core/model_selection.py 一致）────────────────
const LOCAL_BRAINS: { tag: string; name: string; modal: string }[] = [
  { tag: 'gemma4:12b', name: 'Gemma 4 · 12B', modal: '视觉 · 听觉 · 工具 · 128K' },
  { tag: 'openbmb/minicpm-o4.5', name: 'MiniCPM-o 4.5', modal: '全模态 看/听/说（需显卡）' },
  { tag: 'gemma4:e4b', name: 'Gemma 4 · E4B', modal: '视觉 · 听觉 · 中等显存' },
  { tag: 'gemma4:e2b', name: 'Gemma 4 · E2B', modal: '视觉 · 听觉 · 轻量' },
];

// ── 提供商分组（name=中文主名, latin=拉丁副名, key=主配置项）──────────
interface Provider {
  key: string;        // 主 key（API key 或 token）
  name: string;
  latin: string;
  note?: string;      // 模型/能力提示
  extraKey?: string;  // 附加 key（如 OneAPI 的 URL）
  extraLabel?: string;
}

const OPEN_CLOUD: Provider[] = [
  { key: 'DEEPSEEK_API_KEY', name: 'DeepSeek', latin: 'deepseek', note: 'V4 / R1 · 推理 · 代码' },
  { key: 'QWEN_API_KEY', name: '通义千问', latin: 'Qwen', note: 'Qwen-Max · 通用' },
  { key: 'ZHIPU_API_KEY', name: '智谱 GLM', latin: 'GLM', note: 'GLM · 多模态' },
  { key: 'GROQ_API_KEY', name: 'Groq', latin: 'groq', note: 'Llama 等 · 极速' },
  { key: 'MINIMAX_API_KEY', name: 'MiniMax', latin: 'minimax', note: '长文 · 创意' },
  { key: 'MOONSHOT_API_KEY', name: 'Kimi', latin: 'moonshot', note: 'K2 · 长上下文' },
  { key: 'STEP_API_KEY', name: '阶跃星辰', latin: 'StepFun', note: 'Step · 多模态' },
  { key: 'MIMO_API_KEY', name: '小米 MiMo', latin: 'mimo', note: '快速响应' },
  { key: 'MISTRAL_API_KEY', name: 'Mistral', latin: 'mistral', note: '开源权重' },
];

const PROPRIETARY: Provider[] = [
  { key: 'ANTHROPIC_API_KEY', name: 'Claude', latin: 'anthropic', note: '强推理 · 兜底' },
  { key: 'OPENAI_API_KEY', name: 'OpenAI', latin: 'openai', note: 'GPT · 兜底' },
  { key: 'GOOGLE_API_KEY', name: 'Gemini', latin: 'google', note: '多模态 · 兜底' },
  { key: 'XAI_API_KEY', name: 'xAI', latin: 'grok' },
  { key: 'PERPLEXITY_API_KEY', name: 'Perplexity', latin: 'perplexity', note: '联网检索' },
];

const AGGREGATE: Provider[] = [
  { key: 'HF_API_TOKEN', name: 'HuggingFace', latin: 'hf', note: 'Token · 开源模型库' },
  { key: 'ONEAPI_API_KEY', name: 'OneAPI 聚合', latin: 'oneapi', extraKey: 'ONEAPI_URL', extraLabel: '聚合地址' },
  { key: 'LOCAL_VLLM_URL', name: '本地 vLLM', latin: 'vllm', note: '自托管推理地址' },
];

// 一个值是否"已配置"（非空 + 非占位）
function isSet(v?: string): boolean {
  if (!v) return false;
  const t = v.trim();
  return t.length > 0 && !t.startsWith('your-');
}

// ── 浏览器预览兜底：无 galaxyAPI 时直接打 /api/config ──────────────────
async function fetchConfig(): Promise<Record<string, ConfigItem>> {
  if (window.galaxyAPI?.getConfig) return window.galaxyAPI.getConfig();
  const r = await fetch('/api/config');
  if (!r.ok) throw new Error(`/api/config ${r.status}`);
  return r.json();
}
async function saveConfig(changed: Record<string, string>): Promise<boolean> {
  if (window.galaxyAPI?.setConfig) return (await window.galaxyAPI.setConfig(changed)).success;
  const r = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: changed }),
  });
  return r.ok;
}

// ── 密钥输入（带显隐）──────────────────────────────────────────────────
function SecretField({
  value, placeholder, onChange,
}: { value: string; placeholder?: string; onChange: (v: string) => void }) {
  const [show, setShow] = useState(false);
  return (
    <div className="mt-secret">
      <input
        type={show ? 'text' : 'password'}
        className="mt-input"
        value={value}
        placeholder={placeholder || '粘贴密钥…'}
        spellCheck={false}
        autoComplete="off"
        onChange={(e) => onChange(e.target.value)}
      />
      <button className="mt-eye" type="button" tabIndex={-1}
        onClick={() => setShow((s) => !s)} aria-label={show ? '隐藏' : '显示'}>
        {show ? '隐藏' : '显示'}
      </button>
    </div>
  );
}

// ── 单个提供商行 ──────────────────────────────────────────────────────
function ProviderRow({
  p, get, onChange,
}: { p: Provider; get: (k: string) => string; onChange: (k: string, v: string) => void }) {
  const configured = isSet(get(p.key)) && (!p.extraKey || isSet(get(p.extraKey)) || true);
  return (
    <div className={`mt-row ${configured ? 'is-on' : ''}`}>
      <div className="mt-row-id">
        <span className="mt-dot" />
        <div className="mt-row-name">
          <span className="mt-name">{p.name}</span>
          <span className="mt-latin">{p.latin}</span>
        </div>
        {p.note && <span className="mt-note">{p.note}</span>}
        <span className={`mt-state ${configured ? 'on' : ''}`}>
          {configured ? '已连接' : '未配置'}
        </span>
      </div>
      <div className="mt-row-fields">
        {p.extraKey && (
          <input
            className="mt-input mt-input-url"
            value={get(p.extraKey)}
            placeholder={p.extraLabel || '地址'}
            spellCheck={false}
            onChange={(e) => onChange(p.extraKey!, e.target.value)}
          />
        )}
        <SecretField value={get(p.key)} onChange={(v) => onChange(p.key, v)} />
      </div>
    </div>
  );
}

export default function ModelsTab() {
  const [config, setConfig] = useState<Record<string, ConfigItem>>({});
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      setConfig(await fetchConfig());
      setChanged({});
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载配置失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const get = useCallback(
    (k: string) => (changed[k] !== undefined ? changed[k] : config[k]?.value ?? ''),
    [changed, config],
  );
  const set = useCallback((k: string, v: string) => {
    setChanged((prev) => ({ ...prev, [k]: v }));
  }, []);

  const flash = useCallback((m: string) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(m);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  }, []);

  const dirty = Object.keys(changed).length;

  const save = useCallback(async () => {
    try {
      const ok = await saveConfig(changed);
      if (ok) {
        setConfig((prev) => {
          const next = { ...prev };
          Object.entries(changed).forEach(([k, v]) => {
            next[k] = { ...(next[k] ?? { value: '', default: '', type: 'string', category: 'llm', description: '' }), value: v };
          });
          return next;
        });
        setChanged({});
        flash('已保存并即时生效');
      } else {
        flash('保存失败');
      }
    } catch (e) {
      flash(`保存出错：${e instanceof Error ? e.message : ''}`);
    }
  }, [changed, flash]);

  // 状态统计
  const allProviders = [...OPEN_CLOUD, ...PROPRIETARY, ...AGGREGATE];
  const connectedCount = allProviders.filter((p) => isSet(get(p.key))).length;
  const localOn = isSet(get('OLLAMA_URL')) || isSet(get('OLLAMA_MODEL'));
  const currentBrain = get('OLLAMA_MODEL') || 'gemma4:e2b';

  if (loading) {
    return <div className="mt-state-screen">正在读取模型配置…</div>;
  }
  if (error) {
    return (
      <div className="mt-state-screen">
        <div className="mt-err">{error}</div>
        <button className="mt-btn" onClick={load}>重试</button>
      </div>
    );
  }

  return (
    <div className="models-tab">
      <div className="mt-scroll">
        <header className="mt-head">
          <div>
            <h1 className="mt-title">模型</h1>
            <p className="mt-sub">本地原生多模态为基座，开源 API 为主力，专有为兜底</p>
          </div>
          <div className="mt-summary">
            <span><b>{localOn ? 1 : 0}</b> 本地</span>
            <span className="mt-sep" />
            <span><b>{connectedCount}</b> 已连接</span>
          </div>
        </header>

        {/* ── 本地主脑 ── */}
        <section className="mt-card mt-hero">
          <div className="mt-card-top">
            <span className="mt-card-label">本地主脑 · 原生多模态</span>
            <span className={`mt-pill ${localOn ? 'on' : ''}`}>{localOn ? '已就绪' : '未启用'}</span>
          </div>
          <div className="mt-brains">
            {LOCAL_BRAINS.map((b) => {
              const active = currentBrain === b.tag;
              return (
                <button
                  key={b.tag}
                  className={`mt-brain ${active ? 'active' : ''}`}
                  onClick={() => set('OLLAMA_MODEL', b.tag)}
                >
                  <span className="mt-brain-name">{b.name}</span>
                  <span className="mt-brain-modal">{b.modal}</span>
                  {active && <span className="mt-brain-check" aria-hidden>✓</span>}
                </button>
              );
            })}
          </div>
          <div className="mt-local-url">
            <label>Ollama 地址</label>
            <input
              className="mt-input mt-input-url"
              value={get('OLLAMA_URL')}
              placeholder="http://localhost:11434"
              spellCheck={false}
              onChange={(e) => set('OLLAMA_URL', e.target.value)}
            />
          </div>
        </section>

        {/* ── 云端·开源优先 ── */}
        <section className="mt-card">
          <div className="mt-card-top">
            <span className="mt-card-label">云端 · 开源优先</span>
            <span className="mt-card-hint">做任务主力</span>
          </div>
          <div className="mt-rows">
            {OPEN_CLOUD.map((p) => (
              <ProviderRow key={p.key} p={p} get={get} onChange={set} />
            ))}
          </div>
        </section>

        {/* ── 云端·专有 ── */}
        <section className="mt-card">
          <div className="mt-card-top">
            <span className="mt-card-label">云端 · 专有</span>
            <span className="mt-card-hint">高端兜底</span>
          </div>
          <div className="mt-rows">
            {PROPRIETARY.map((p) => (
              <ProviderRow key={p.key} p={p} get={get} onChange={set} />
            ))}
          </div>
        </section>

        {/* ── 接入与聚合 ── */}
        <section className="mt-card">
          <div className="mt-card-top">
            <span className="mt-card-label">接入与聚合</span>
            <span className="mt-card-hint">HuggingFace · OneAPI · vLLM</span>
          </div>
          <div className="mt-rows">
            {AGGREGATE.map((p) => (
              <ProviderRow key={p.key} p={p} get={get} onChange={set} />
            ))}
          </div>
        </section>
      </div>

      {/* ── 底部保存条 ── */}
      <footer className={`mt-foot ${dirty ? 'show' : ''}`}>
        <span className="mt-foot-info">{dirty ? `${dirty} 项改动` : '全部已保存'}</span>
        <div className="mt-foot-actions">
          <button className="mt-btn mt-btn-ghost" onClick={() => setChanged({})} disabled={!dirty}>
            放弃
          </button>
          <button className="mt-btn mt-btn-primary" onClick={save} disabled={!dirty}>
            保存
          </button>
        </div>
      </footer>

      {toast && <div className="mt-toast">{toast}</div>}
    </div>
  );
}
