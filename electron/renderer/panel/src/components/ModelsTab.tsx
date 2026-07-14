import { useCallback, useEffect, useRef, useState } from 'react';
import { useConfigCache } from '@/hooks/useConfigCache';
import { useModelCatalog, type CatalogModel, type StatusEntry } from '@/hooks/useModelCatalog';
import { getBackendUrl } from '@/lib/api';
import './ModelsTab.css';

/**
 * ModelsTab — 模型管理（温润高级感 / 硬件设置式）
 *
 * 本地主脑：AB 两档切换（A=Gemma 系 · B=MiniCPM-o 全模态）。
 * 档位、模型清单、能力全部来自后端 /api/v1/models/catalog（单一真相
 * 源 core.model_catalog），前端【不再硬编码】；安装/拉取状态后台静默轮询。
 * 云端 API 密钥沿用 /api/config（与 SettingsTab 同一套存储）。
 */

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
  { key: 'DEEPSEEK_OCR2_API_KEY', name: 'DeepSeek OCR', latin: 'deepseek-ocr2', note: '文档/图像识别' },
  { key: 'QWEN_API_KEY', name: '通义千问', latin: 'Qwen', note: 'Qwen-Max · 通用' },
  { key: 'ZHIPU_API_KEY', name: '智谱 GLM', latin: 'GLM', note: 'GLM · 多模态' },
  { key: 'GROQ_API_KEY', name: 'Groq', latin: 'groq', note: 'Llama 等 · 极速' },
  { key: 'MINIMAX_API_KEY', name: 'MiniMax', latin: 'minimax', note: '长文 · 创意' },
  { key: 'MOONSHOT_API_KEY', name: 'Kimi', latin: 'moonshot', note: 'K2 · 长上下文' },
  { key: 'STEP_API_KEY', name: '阶跃星辰', latin: 'StepFun', note: 'Step · 多模态' },
  { key: 'MIMO_API_KEY', name: '小米 MiMo', latin: 'mimo', note: '快速响应' },
  { key: 'MISTRAL_API_KEY', name: 'Mistral', latin: 'mistral', note: '开源权重' },
  { key: 'AGNES_API_KEY', name: 'Agnes AI', latin: 'agnes', note: '2.5 Flash · 全模态 · 免费' },
];

const PROPRIETARY: Provider[] = [
  { key: 'ANTHROPIC_API_KEY', name: 'Claude', latin: 'anthropic', note: '强推理 · 兜底' },
  {
    key: 'OPENAI_API_KEY', name: 'OpenAI', latin: 'openai', note: 'GPT · 兜底',
    extraKey: 'OPENAI_API_BASE', extraLabel: '自定义 API 地址（可选，兼容代理/中转）',
  },
  { key: 'GOOGLE_API_KEY', name: 'Gemini', latin: 'google', note: '多模态 · 兜底' },
  { key: 'XAI_API_KEY', name: 'xAI', latin: 'grok' },
  { key: 'META_API_KEY', name: 'Meta', latin: 'muse-spark', note: 'Muse Spark · agentic 多模态' },
  { key: 'PERPLEXITY_API_KEY', name: 'Perplexity', latin: 'perplexity', note: '联网检索' },
];

const AGGREGATE: Provider[] = [
  { key: 'HF_API_TOKEN', name: 'HuggingFace', latin: 'hf', note: 'Token · 开源模型库' },
  { key: 'ONEAPI_API_KEY', name: 'OneAPI 聚合', latin: 'oneapi', extraKey: 'ONEAPI_URL', extraLabel: '聚合地址' },
  { key: 'OPENROUTER_API_KEY', name: 'OpenRouter', latin: 'openrouter', note: '多模型聚合路由' },
  { key: 'LOCAL_VLLM_URL', name: '本地 vLLM', latin: 'vllm', note: '自托管推理地址' },
];

// 一个值是否"已配置"（非空 + 非占位）
function isSet(v?: string): boolean {
  if (!v) return false;
  const t = v.trim();
  return t.length > 0 && !t.startsWith('your-');
}

// 后端 GET /api/config 返回形状(system.py 增量字段):
//   configured: {ENV_KEY: bool}  — 密钥是否已配置(不下发密钥值本身)
//   values:     {ENV_KEY: str}   — 非敏感项(地址/模型名)明文回填
interface FrontendConfig {
  configured?: Record<string, boolean>;
  values?: Record<string, string>;
  status?: Record<string, boolean>;
}

// ── 读取配置(Electron IPC 优先,浏览器预览兜底直连 /api/config)──────────
async function fetchConfig(): Promise<FrontendConfig> {
  if (window.galaxyAPI?.getConfig) {
    return (await window.galaxyAPI.getConfig()) as unknown as FrontendConfig;
  }
  const r = await fetch('/api/config');
  if (!r.ok) throw new Error(`/api/config ${r.status}`);
  return r.json();
}
// ── 保存配置:POST /api/config {config:{KEY:VALUE}} → config.py 持久化到 .env
//    并热刷新 LLM 路由(新填的 key 即时生效,无需重启)。──────────────────
// 修复:之前只返回 boolean,后端/Electron IPC 层其实带回了真实错误原因
// (未知配置键、.env 写入失败等),但被这里直接丢弃,失败时只能显示笼统的
// "保存失败"，用户没法自己判断到底是哪个字段的问题。现在把 error 一并带出。
async function saveConfig(changed: Record<string, string>): Promise<{ success: boolean; error?: string }> {
  if (window.galaxyAPI?.setConfig) return window.galaxyAPI.setConfig(changed);
  const r = await fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: changed }),
  });
  if (r.ok) return { success: true };
  let detail = `HTTP ${r.status}`;
  try {
    const body = await r.json();
    detail = body.detail || body.error || body.message || detail;
  } catch {
    /* 响应体不是 JSON，退回状态码文案 */
  }
  return { success: false, error: detail };
}

// ── 密钥输入（带显隐）──────────────────────────────────────────────────
// 密钥值从不由后端下发;configured=true 时输入框留空并以占位提示"已配置",
// 用户输入新值即覆盖。
function SecretField({
  value, configured, onChange,
}: { value: string; configured: boolean; onChange: (v: string) => void }) {
  const [show, setShow] = useState(false);
  const placeholder = configured ? '已配置 · 如需更换请输入新密钥' : '粘贴密钥…';
  return (
    <div className="mt-secret">
      <input
        type={show ? 'text' : 'password'}
        className="mt-input"
        value={value}
        placeholder={placeholder}
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
  p, get, isConfigured, onChange,
}: {
  p: Provider;
  get: (k: string) => string;
  isConfigured: (k: string) => boolean;
  onChange: (k: string, v: string) => void;
}) {
  const configured = isConfigured(p.key);
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
        <SecretField value={get(p.key)} configured={configured} onChange={(v) => onChange(p.key, v)} />
      </div>
    </div>
  );
}

// ── 单个模型的实时状态徽标 ────────────────────────────────────────────────
function StatusBadge({ st }: { st?: StatusEntry }) {
  if (!st) return <span className="mt-mstatus idle" title="状态未知">…</span>;
  if (!st.ollama_reachable) return <span className="mt-mstatus idle" title="Ollama 未连接">离线</span>;
  if (st.status === 'installed') return <span className="mt-mstatus on" title="已安装且可用">已就绪</span>;
  if (st.status === 'broken') return <span className="mt-mstatus err" title="列表有但打不开,将重拉">需修复</span>;
  return <span className="mt-mstatus pull" title="未安装,选此档会后台拉取">未安装</span>;
}

function capText(caps: CatalogModel['caps']): string {
  const parts: string[] = [];
  if (caps.vision) parts.push('看');
  if (caps.audio_in) parts.push('听');
  if (caps.audio_out) parts.push('说');
  if (caps.tools) parts.push('工具');
  return parts.join(' · ');
}

// ── 本地主脑：档位切换（动态、去硬编码、实时状态、后台刷新）───────────────
function LocalBrainTiers() {
  const { catalog, status, error, selectTier } = useModelCatalog();
  const [busy, setBusy] = useState<string | null>(null);

  const onPick = useCallback(async (tier: string) => {
    setBusy(tier);
    try { await selectTier(tier); } finally { setBusy(null); }
  }, [selectTier]);

  return (
    <section className="mt-card mt-hero">
      <div className="mt-card-top">
        <span className="mt-card-label">本地主脑 · 档位</span>
        {catalog
          ? <span className="mt-pill on">当前 {catalog.current_tier} 档</span>
          : <span className="mt-pill" title={error ?? ''}>{error ? '目录暂不可达' : '加载中…'}</span>}
      </div>

      {/* 目录未到位也先渲染骨架，不整页阻塞（要求：界面常在） */}
      <div className="mt-tiers">
        {(catalog?.tiers ?? []).map((t) => {
          const isCurrent = catalog?.current_tier === t.key;
          const io = t.effective_io;
          return (
            <button
              key={t.key}
              className={`mt-tier ${isCurrent ? 'active' : ''}`}
              onClick={() => onPick(t.key)}
              disabled={busy !== null}
              title={t.desc}
            >
              <div className="mt-tier-head">
                <span className="mt-tier-key">{t.key}</span>
                <span className="mt-tier-label">{t.label}</span>
                {isCurrent && <span className="mt-tier-check" aria-hidden>✓</span>}
                {busy === t.key && <span className="mt-tier-busy" aria-hidden>切换中…</span>}
              </div>
              <div className="mt-tier-io">
                看:{io.vision === 'native' ? '原生' : '—'} · 听:{io.audio_in === 'native' ? '原生' : 'ASR桥'} · 说:{io.audio_out === 'native' ? '原生' : 'TTS桥'}
              </div>
              <div className="mt-tier-models">
                {t.models.map((m) => (
                  <div className="mt-tier-model" key={m.tag}>
                    <span className="mt-tier-model-name">{m.name}</span>
                    <span className="mt-tier-model-cap">{capText(m.caps)}{m.size_mb ? ` · ${(m.size_mb / 1000).toFixed(1)}G` : ''}</span>
                    {m.source === 'local'
                      ? <StatusBadge st={status[m.tag]} />
                      : <span className="mt-mstatus idle" title="容器模型(vLLM),不经 Ollama">容器</span>}
                  </div>
                ))}
              </div>
            </button>
          );
        })}
        {!catalog && !error && <div className="mt-tier-skel">正在读取档位目录…</div>}
      </div>
    </section>
  );
}

export default function ModelsTab() {
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const {
    data: cfg,
    loading,
    error,
    reload: load,
    invalidate,
  } = useConfigCache('models-config', fetchConfig);

  // 后端从「未就绪」变为「就绪」是异步的(Electron 主进程在后台重试,不再
  // 阻塞 IPC 调用本身——见 main.js galaxy:get-config)。收到就绪通知后主动
  // 失效缓存重新拉一次,而不是要求用户手动切走再切回来才能看到真实数据。
  useEffect(() => {
    if (!window.galaxyAPI?.onConfigReady) return undefined;
    return window.galaxyAPI.onConfigReady((kind) => {
      if (kind === 'config') invalidate();
    });
  }, [invalidate]);

  const configured = cfg?.configured ?? {};
  const values = cfg?.values ?? {};

  // 输入框显示值:用户改过取改动值,否则取后端回填的非敏感值(密钥无回填→空)
  const get = useCallback(
    (k: string) => (changed[k] !== undefined ? changed[k] : values[k] ?? ''),
    [changed, values],
  );
  // 是否已配置:用户改过看改动值是否非空;否则看后端 configured 布尔(密钥),
  // 或非敏感值是否已填(地址/模型)。
  const isConfigured = useCallback(
    (k: string) => {
      if (changed[k] !== undefined) return isSet(changed[k]);
      if (k in configured) return configured[k];
      return isSet(values[k]);
    },
    [changed, configured, values],
  );
  const set = useCallback((k: string, v: string) => {
    setChanged((prev) => ({ ...prev, [k]: v }));
  }, []);

  const flash = useCallback((m: string, ms = 2600) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(m);
    toastTimer.current = setTimeout(() => setToast(null), ms);
  }, []);

  const dirty = Object.keys(changed).length;
  const [saving, setSaving] = useState(false);

  const save = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    // 立即给等待态:后端启动期/拥塞时这一步可能要好几秒,没有这条用户会以为
    // "点了没反应"(真机反馈)。
    flash('保存中…', 30000);
    try {
      const result = await saveConfig(changed);
      if (!result.success) {
        // 修复:之前不管真实原因是什么,一律显示"保存失败"四个字。现在把
        // 后端/IPC 层透传上来的真实原因(未知配置键、.env 写入失败等)带出,
        // 且失败提示驻留更久,不会一闪而过。
        flash(result.error ? `保存失败：${result.error}` : '保存失败', 8000);
        return;
      }
      // 保存成功后使缓存失效并重新加载，回读服务端真值
      invalidate();
      // 「保存成功」≠「能用」:对改动里的每个 API Key 做一次真实连通验证
      // (后端 1-token 试调),把"到底好了没有"直接答在 toast 里。
      const keys = Object.keys(changed).filter(
        (k) => k.endsWith('_API_KEY') || k === 'OLLAMA_URL' || k === 'HF_TOKEN',
      );
      if (keys.length === 0) {
        flash('已保存并即时生效');
        return;
      }
      flash('已保存 · 正在验证连通性…', 30000);
      const base = await getBackendUrl();
      const results: string[] = [];
      for (const k of keys) {
        try {
          const r = await fetch(`${base}/api/v1/models/verify-provider`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ env_key: k }),
          });
          const v = await r.json();
          if (v.ok) {
            results.push(`${v.provider} ✓ 可用 ${Math.round(v.latency_ms)}ms`);
          } else {
            results.push(`${v.provider || k} ✗ ${v.error || '验证失败'}`);
          }
        } catch (e) {
          results.push(`${k} ✗ 验证请求失败：${e instanceof Error ? e.message : ''}`);
        }
      }
      const anyFail = results.some((s) => s.includes('✗'));
      flash(`已保存 · ${results.join('；')}`, anyFail ? 12000 : 6000);
    } catch (e) {
      flash(`保存出错：${e instanceof Error ? e.message : ''}`, 8000);
    } finally {
      setSaving(false);
    }
  }, [changed, flash, invalidate, saving]);

  // 状态统计
  const allProviders = [...OPEN_CLOUD, ...PROPRIETARY, ...AGGREGATE];
  const connectedCount = allProviders.filter((p) => isConfigured(p.key)).length;
  const localOn = isConfigured('OLLAMA_URL') || isSet(get('OLLAMA_MODEL'));

  // 界面本体始终渲染,不再用 loading/error 整屏遮挡——后端(尤其是启动期的
  // Ollama)可能要几十秒甚至几分钟才响应,之前"loading 就整屏转圈"会让用户
  // 在这几分钟内完全没法点进来填 API Key。改为:表单始终可交互(未加载到的
  // 项就是"未配置"的默认态),只在标题栏放一个不打断操作的小提示,真实数据
  // 到达后(或用户手动点重试)自动补上,不用重开这个 tab。
  const syncing = loading && !cfg;
  const offline = Boolean(error) && !cfg;

  return (
    <div className="models-tab">
      <div className="mt-scroll">
        <header className="mt-head">
          <div>
            <h1 className="mt-title">模型</h1>
            <p className="mt-sub">本地原生多模态为基座，开源 API 为主力，专有为兜底</p>
          </div>
          <div className="mt-summary">
            {syncing && <span className="mt-sync-badge" title="正在后台读取模型配置…">● 同步中</span>}
            {offline && (
              <span className="mt-sync-badge mt-sync-badge-err" title={error ?? ''}>
                ⚠ 暂未连接后端 · 自动重试中
                <button className="mt-sync-retry" onClick={load} type="button">重试</button>
              </span>
            )}
            <span><b>{localOn ? 1 : 0}</b> 本地</span>
            <span className="mt-sep" />
            <span><b>{connectedCount}</b> 已连接</span>
          </div>
        </header>

        {/* ── 本地主脑：档位切换（动态目录 + 实时状态 + 后台刷新）── */}
        <LocalBrainTiers />

        {/* Ollama 地址（沿用 /api/config 存储） */}
        <section className="mt-card">
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
              <ProviderRow key={p.key} p={p} get={get} isConfigured={isConfigured} onChange={set} />
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
              <ProviderRow key={p.key} p={p} get={get} isConfigured={isConfigured} onChange={set} />
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
              <ProviderRow key={p.key} p={p} get={get} isConfigured={isConfigured} onChange={set} />
            ))}
          </div>
        </section>
      </div>

      {/* ── 底部保存条 ── */}
      <footer className={`mt-foot ${dirty ? 'show' : ''}`}>
        <span className="mt-foot-info">{dirty ? `${dirty} 项改动` : '全部已保存'}</span>
        <div className="mt-foot-actions">
          <button className="mt-btn mt-btn-ghost" onClick={() => setChanged({})} disabled={!dirty || saving}>
            放弃
          </button>
          <button className="mt-btn mt-btn-primary" onClick={save} disabled={!dirty || saving}>
            {saving ? '保存中…' : '保存'}
          </button>
        </div>
      </footer>

      {toast && <div className="mt-toast">{toast}</div>}
    </div>
  );
}
