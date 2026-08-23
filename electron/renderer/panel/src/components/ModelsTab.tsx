import { useCallback, useEffect, useRef, useState } from 'react';
import { useConfigCache } from '@/hooks/useConfigCache';
import { useModelCatalog, type CatalogModel, type StatusEntry } from '@/hooks/useModelCatalog';
import { apiUrl, getBackendUrl, fetchWithTimeout, withTimeout } from '@/lib/api';
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
  {
    key: 'ZHIPU_CODING_API_KEY', name: '智谱 GLM 编码套餐', latin: 'GLM Coding Plan',
    note: 'GLM-5.3 · 订阅制 · 仅编码场景，与上面的 GLM Key 是两把不同的 Key',
  },
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
// 与后端 core.credential_vault.PLACEHOLDER_PREFIXES 保持同一份判定口径
// (.env.example / runtime/secrets.example.env 实际发的是下划线格式
// "your_..._here",连字符格式是历史遗留)。这里只做前缀集合的手工镜像——
// TS 渲染层和 Python 后端之间没有共享常量的构建期机制,若以后
// PLACEHOLDER_PREFIXES 改动,需要手动同步这里(与 electron/main.js 的
// CONFIG_FETCH_* 常量不同,这个值不是运行期可查询的,因为它纯粹是本地即时
// UI 预览逻辑,不值得为此新增一条 IPC 往返)。
const ISSET_PLACEHOLDER_PREFIXES = ['your_', 'your-', 'change_me', 'todo', '<', 'example', 'xxx'];
function isSet(v?: string): boolean {
  if (!v) return false;
  const t = v.trim().toLowerCase();
  return t.length > 0 && !ISSET_PLACEHOLDER_PREFIXES.some((p) => t.startsWith(p));
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
  // 均加超时:IPC 或 HTTP 挂死时,缓存 hook 的 loading 会永远为 true,
  // 保存后回读服务端真值这一步就永远转圈,"已配置"状态刷不出来。
  if (window.galaxyAPI?.getConfig) {
    return withTimeout(
      window.galaxyAPI.getConfig() as unknown as Promise<FrontendConfig>,
      15000,
      '读取配置',
    );
  }
  // 浏览器预览兜底:面板经 loadFile 以 file:// origin 加载,相对路径 '/api/config'
  // 会解析成 file:///api/config、100% 失败(SettingsTab 同类 bug 早已改为
  // getBackendUrl,这里当时漏改)。
  const base = await getBackendUrl();
  const r = await fetchWithTimeout(apiUrl(base, '/api/config'), {}, 15000);
  if (!r.ok) throw new Error(`/api/config ${r.status}`);
  return r.json();
}
// ── 保存配置:POST /api/config {config:{KEY:VALUE}} → config.py 持久化到 .env
//    并热刷新 LLM 路由(新填的 key 即时生效,无需重启)。──────────────────
// 修复:之前只返回 boolean,后端/Electron IPC 层其实带回了真实错误原因
// (未知配置键、.env 写入失败等),但被这里直接丢弃,失败时只能显示笼统的
// "保存失败"，用户没法自己判断到底是哪个字段的问题。现在把 error 一并带出。
//
// 真 bug 修复(真机反馈"面板保存 API key 直接失败"):这里的 IPC 分支此前硬编码
// 20000ms 死线,但 electron/main.js 的 galaxy:set-config 处理器自己的重试预算
// (专门为"后端首次启动要下语音模型、1~2 分钟才监听端口"这个真实场景设计)最长
// 约 60s——两个数字从未对齐过,渲染层 20s 一到就先报"保存失败",主进程那边却
// 可能 30~60s 后才真的存成功,用户看到的是一次本可避免的假失败。
// 兜底值:与 electron/main.js 的 CONFIG_FETCH_BUDGET_MS(60s)+
// CONFIG_FETCH_ATTEMPT_TIMEOUT_MS(8s)+CONFIG_SAVE_CLIENT_MARGIN_MS(10s)
// 保持一致。只有 galaxyAPI.getConfigSaveTimeoutMs 未暴露时(preload/main
// 版本落后的极端情况)才会走到这个数字——正常情况下这里的"真源"是主进程,
// 渲染层通过 IPC 现查,不再自己维护一份独立数字。
const FALLBACK_SAVE_TIMEOUT_MS = 78000;
async function saveConfig(changed: Record<string, string>): Promise<{ success: boolean; error?: string }> {
  // IPC 与 HTTP 两条路径都加超时:后端启动期/写盘卡住时,裸调用会挂到 OS 级
  // 超时(几分钟),"保存中…"按钮就一直转圈。到点即返回一个可显示的错误。
  if (window.galaxyAPI?.setConfig) {
    let timeoutMs = FALLBACK_SAVE_TIMEOUT_MS;
    if (window.galaxyAPI.getConfigSaveTimeoutMs) {
      try {
        timeoutMs = await window.galaxyAPI.getConfigSaveTimeoutMs();
      } catch {
        /* IPC 查询失败:退回本地兜底值,不影响后续保存本身 */
      }
    }
    try {
      return await withTimeout(window.galaxyAPI.setConfig(changed), timeoutMs, '保存配置');
    } catch (e) {
      return { success: false, error: e instanceof Error ? e.message : '保存超时' };
    }
  }
  // 浏览器预览兜底路径(无 galaxyAPI,无 Electron 中间层/重试预算):这里的
  // fetchWithTimeout(...20000) 保持不变——没有 main.js 的重试层,后端未起来时
  // fetch() 会直接 ECONNREFUSED(近乎瞬时),20s 绰绰有余,与本 bug 无关。
  const base = await getBackendUrl();
  const r = await fetchWithTimeout(apiUrl(base, '/api/config'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: changed }),
  }, 20000);
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
                    {catalog?.gpu_fit?.[m.tag] === 'no_gpu' && (
                      <span
                        className="mt-mstatus warn"
                        title="此模型需要显卡,当前未检测到可用 GPU:会以 CPU 运行,首字延迟数秒到数十秒。建议选 A 档或在下方配置云端 API(如 Agnes 免费全模态)。"
                      >无显卡·会极慢</span>
                    )}
                    {catalog?.gpu_fit?.[m.tag] === 'insufficient_vram' && (
                      <span
                        className="mt-mstatus warn"
                        title="显存装不下此模型,会部分溢出到内存(明显变慢)。建议换更小档位或量化版本。"
                      >显存不足</span>
                    )}
                  </div>
                ))}
              </div>
            </button>
          );
        })}
        {!catalog && !error && <div className="mt-tier-skel">正在读取档位目录…</div>}
      </div>
      <LatencyProbe />
    </section>
  );
}

// ── 本地推理一键测速:后端用 Ollama 自带 eval 计数报真实速度 + 诚实判词 ──
function LatencyProbe() {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<{ stages?: Record<string, unknown>; verdicts?: string[] } | null>(null);
  const [err, setErr] = useState('');

  const run = useCallback(async () => {
    setRunning(true);
    setErr('');
    setResult(null);
    try {
      const base = await getBackendUrl();
      const r = await fetch(apiUrl(base, '/api/v1/models/latency-probe'), { method: 'POST' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setResult(await r.json());
    } catch (e) {
      setErr(String(e));
    } finally {
      setRunning(false);
    }
  }, []);

  const s = (result?.stages ?? {}) as Record<string, unknown>;
  return (
    <div className="mt-probe">
      <button className="mt-probe-btn" onClick={run} disabled={running}>
        {running ? '测速中(最长约 1 分钟)…' : '本地推理一键测速'}
      </button>
      {err && <div className="mt-probe-line err">测速失败:{err}</div>}
      {result && (
        <div className="mt-probe-result mono">
          {s.decode_tokens_per_s != null && <div className="mt-probe-line">生成速度:{String(s.decode_tokens_per_s)} tok/s</div>}
          {s.prefill_tokens_per_s != null && <div className="mt-probe-line">预填速度:{String(s.prefill_tokens_per_s)} tok/s</div>}
          {s.est_agent_first_token_s != null && <div className="mt-probe-line">满配代理回合首字估计:约 {String(s.est_agent_first_token_s)}s</div>}
          {s.load_ms != null && Number(s.load_ms) > 500 && <div className="mt-probe-line">模型冷加载:{String(s.load_ms)}ms</div>}
          {(result.verdicts ?? []).map((v, i) => (
            <div className="mt-probe-line verdict" key={i}>{v}</div>
          ))}
        </div>
      )}
    </div>
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

  // 迟到成功兜底:理论上渲染层的保存超时死线现在已经 ≥ 主进程真实预算(见
  // saveConfig() 的 getConfigSaveTimeoutMs 现查逻辑),不该再出现"渲染层已经
  // 判超时失败、主进程后来却真的存成功了"这种错位——但仍保留这层兜底,覆盖
  // getConfigSaveTimeoutMs 不可用、退回本地兜底值的边缘情况。那种情况下 toast
  // 已经错误地显示过"失败",这里监听 main.js 的迟到广播,至少把"已连接"徽标
  // 自我纠正过来，不额外弹二次 toast(用户可能已经离开这个 tab,二次提示反而
  // 困惑)。
  useEffect(() => {
    if (!window.galaxyAPI?.onConfigUpdate) return undefined;
    return window.galaxyAPI.onConfigUpdate(() => invalidate());
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
    // "点了没反应"(真机反馈)。覆盖主进程最坏情形(~78s):避免这条 toast 自己
    // 的自动消失定时器在中途把"保存中"提前撤掉,看起来像"卡死无提示"。
    flash('保存中…', 80000);
    // 12s 是经验值:正常(后端已在线)保存几乎瞬时完成,这个定时器多半会在
    // finally 里被 clearTimeout 掉、从不触发;只有真的撞上冷启动重试窗口时
    // 才会把提示换成更明确的文案,而不是让用户盯着同一句"保存中…"数十秒。
    const interimTimer = setTimeout(() => {
      flash('仍在保存中，后端可能仍在启动…', 80000);
    }, 12000);

    // 阶段一:持久化。saveConfig 现已带超时,不会无限挂起。持久化【一结束】
    // 就释放按钮 —— 后续的连通性验证是慢步骤(真实上游试调),绝不能再把
    // "保存中…"按钮卡在那里转圈(这正是"保存半天没反应"的根因)。
    let persisted = false;
    try {
      const result = await saveConfig(changed);
      if (!result.success) {
        flash(result.error ? `保存失败：${result.error}` : '保存失败', 8000);
        return;
      }
      persisted = true;
      invalidate(); // 使缓存失效并回读服务端真值,刷新"已配置"状态
    } catch (e) {
      flash(`保存出错：${e instanceof Error ? e.message : ''}`, 8000);
      return;
    } finally {
      clearTimeout(interimTimer);
      setSaving(false); // 无论成败,持久化阶段一结束就解锁按钮
    }
    if (!persisted) return;

    // 阶段二:连通性验证(按钮已解锁,此步只更新 toast,不阻塞界面)。
    // 「保存成功」≠「能用」:对改动里的每个 API Key 做一次真实试调,
    // 把"到底好了没有"答在 toast 里。每个请求都带超时,整体不会挂死。
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
        const r = await fetchWithTimeout(apiUrl(base, '/api/v1/models/verify-provider'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ env_key: k }),
        }, 12000);
        const v = await r.json();
        if (v.ok) {
          results.push(`${v.provider} ✓ 可用 ${Math.round(v.latency_ms)}ms`);
        } else {
          results.push(`${v.provider || k} ✗ ${v.error || '验证失败'}`);
        }
      } catch (e) {
        const to = e instanceof DOMException && e.name === 'TimeoutError';
        results.push(`${k} ✗ ${to ? '验证超时(12s)' : `验证请求失败：${e instanceof Error ? e.message : ''}`}`);
      }
    }
    const anyFail = results.some((s) => s.includes('✗'));
    flash(`已保存 · ${results.join('；')}`, anyFail ? 12000 : 6000);
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
