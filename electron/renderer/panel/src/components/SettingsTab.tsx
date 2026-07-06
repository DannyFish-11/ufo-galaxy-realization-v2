import { useEffect, useState, useCallback, useRef } from 'react';
import { useConfigCache } from '@/hooks/useConfigCache';
import { getBackendUrl } from '@/lib/api';
import './SettingsTab.css';

// ── IPC API Interfaces ──────────────────────────────────────────────

export interface ConfigItem {
  value: string;
  default: string;
  type: 'string' | 'password' | 'url' | 'number' | 'boolean' | 'select';
  category: string;
  description: string;
  options?: string[];
}

interface GalaxyAPI {
  getConfig: () => Promise<Record<string, ConfigItem>>;
  // 修复:之前只返回 { success: boolean },失败时真实原因(未知配置键、
  // .env 写入失败等)在 Electron IPC 层就被丢弃了,前端只能显示笼统的
  // "保存失败"，用户没法自己判断到底是哪个字段的问题。现在带回 error。
  setConfig: (config: Record<string, string>) => Promise<{ success: boolean; error?: string }>;
  // 完整明细(本 tab 用):与 getConfig 分开路径,避免后端 /api/config 路由遮蔽
  // (system.py 精简版先注册、抢占同路径)导致这里永远读不到任何一项内容。
  getSettings?: () => Promise<Record<string, ConfigItem>>;
  onConfigUpdate: (callback: (changed: Record<string, string>) => void) => () => void;
  saveConfig: () => Promise<{ success: boolean }>;
}

// 浏览器预览兜底(无 galaxyAPI 时):直连后端完整明细端点。
async function fetchSettings(): Promise<Record<string, ConfigItem>> {
  if (window.galaxyAPI?.getSettings) return window.galaxyAPI.getSettings();
  const r = await fetch('/api/config/all');
  if (!r.ok) throw new Error(`/api/config/all ${r.status}`);
  return r.json();
}

declare global {
  interface Window {
    galaxyAPI?: GalaxyAPI;
  }
}

// ── 节点名单台(端口与节点页展示)────────────────────────────────────
export interface RosterNode {
  num: number;
  name: string;
  type: string;
  type_label: string;
  runnable: boolean;
  purpose: string;
  dir: string;
  port: number | null;
  status: string;
  has_dockerfile: boolean;
  connector?: { kind: string; service: string | null };
}
export interface NodeRoster {
  count: number;
  type_labels: Record<string, string>;
  type_counts: Record<string, number>;
  nodes: RosterNode[];
}

async function fetchRoster(): Promise<NodeRoster | null> {
  try {
    const r = await fetch(`${getBackendUrl()}/api/v1/nodes/roster`);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

export interface ConnectorInfo {
  service: string;
  label: string;
  status: 'needs_config' | 'disconnected' | 'connected';
  account?: string | null;
  redirect_uri: string;
  create_app_url?: string;
  create_hint?: string;
  has_client_id: boolean;
}
async function fetchConnectors(): Promise<ConnectorInfo[] | null> {
  try {
    const r = await fetch(`${getBackendUrl()}/api/v1/connectors`);
    if (!r.ok) return null;
    const j = await r.json();
    return j.connectors ?? [];
  } catch {
    return null;
  }
}

// 状态 → 中文 + 颜色类
function statusMeta(s: string): { label: string; cls: string } {
  const t = (s || '').toLowerCase();
  if (t.includes('health') || t === 'running' || t === 'online') return { label: '运行中', cls: 'ok' };
  if (t.includes('start')) return { label: '启动中', cls: 'warn' };
  if (t.includes('degrad') || t.includes('unhealth')) return { label: '降级', cls: 'warn' };
  if (t.includes('fail') || t.includes('error') || t.includes('offline') || t.includes('stop'))
    return { label: '未运行', cls: 'off' };
  return { label: '未知', cls: 'idle' };
}

// ── Category Definitions ────────────────────────────────────────────

interface CategoryDef {
  key: string;
  label: string;
  icon: string;
  count: number;
}

// 注：模型 API（llm 类）已迁到专门的「模型」tab（ModelsTab），此处不再重复。
const CATEGORIES: CategoryDef[] = [
  { key: 'ports', label: '端口与节点', icon: '🔌', count: 16 },
  { key: 'auth', label: '鉴权', icon: '🔒', count: 12 },
  { key: 'mesh', label: '组网', icon: '🕸️', count: 11 },
  { key: 'circuit', label: '限流熔断', icon: '⚡', count: 14 },
  { key: 'storage', label: '存储', icon: '💾', count: 7 },
  { key: 'dev', label: '开发者', icon: '🛠️', count: 11 },
  { key: 'network', label: '网络', icon: '🌐', count: 7 },
  { key: 'slo', label: '服务水平', icon: '📊', count: 7 },
];

// ── Config Key Registry (105 items) ─────────────────────────────────

const CONFIG_KEYS: Record<string, string[]> = {
  ports: [
    'GATEWAY_PORT', 'UFO_NODE_HOST', 'NODE_92_URL', 'NODE_45_URL', 'NODE_33_URL',
    'NODE_71_URL', 'NODE_71_HOST', 'NODE_95_URL', 'NODE_97_URL', 'NODE09_SANDBOX_URL',
    'OLLAMA_URL', 'QDRANT_URL', 'REDIS_URL', 'SECRETVAULT_URL', 'MAIN_REPO_URL',
    'MQTT_PORT',
  ],
  auth: [
    'GALAXY_AUTH_ENABLED', 'GALAXY_API_TOKEN', 'GALAXY_API_TOKENS',
    'GALAXY_API_TOKEN_EXPIRY', 'GALAXY_REVOKED_TOKENS', 'GALAXY_REQUIRE_API_TOKEN',
    'GALAXY_STRICT_AUTHORITY_CHECK', 'GALAXY_SECRET_BACKEND', 'GALAXY_TLS_CERT',
    'GITHUB_TOKEN', 'GALAXY_AUDIT_KEY', 'GALAXY_MESSAGE_SIGNING_KEY',
  ],
  mesh: [
    'GALAXY_NATS_ENABLED', 'GALAXY_NATS_URL', 'GALAXY_NATS_EXECUTOR_TIMEOUT',
    'GALAXY_NATS_EXECUTOR_FALLBACK', 'GALAXY_CROSS_DEVICE_ENABLED',
    'GALAXY_HEARTBEAT_INTERVAL', 'FEDERATION_ENABLED', 'FEDERATION_LOCAL_HOST',
    'FEDERATION_PEERS', 'FEDERATION_HEARTBEAT_INTERVAL',
    'GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE',
  ],
  circuit: [
    'GALAXY_ROUTER_ADAPTIVE_CONCURRENCY', 'GALAXY_ROUTER_CB_ENABLED',
    'GALAXY_ROUTER_MAX_QUEUE_DEPTH', 'GALAXY_CB_FAILURE_THRESHOLD',
    'GALAXY_CB_RECOVERY_TIMEOUT_S', 'GALAXY_CB_HALF_OPEN_PROBES',
    'GALAXY_CB_WINDOW_SIZE', 'GALAXY_AS_TARGET_LATENCY_MS',
    'GALAXY_AS_ERROR_THRESHOLD', 'GALAXY_AS_INIT_LIMIT', 'GALAXY_AS_MAX_LIMIT',
    'GALAXY_AS_MIN_LIMIT', 'GALAXY_AS_SAMPLE_WINDOW', 'GALAXY_AS_PROBE_INTERVAL_S',
  ],
  storage: [
    'GALAXY_DATA_DIR', 'GALAXY_MARKET_STORE_DIR', 'GALAXY_FEATURE_FLAGS_PATH',
    'GALAXY_MASTER_BRAIN_STATE_PATH', 'CHROMA_PERSIST_DIR',
    'ANDROID_DEVICE_STATE_STORE_PATH', 'ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS',
  ],
  dev: [
    'GALAXY_DEV_MODE', 'GALAXY_MODE', 'GALAXY_SYSTEM_MODE', 'GALAXY_PREFLIGHT_MODE',
    'GALAXY_PREFLIGHT_FAIL_FAST', 'GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK',
    'GALAXY_ENTRYMODE_USE_READINESS', 'CMD_MAX_CONCURRENT', 'CONCURRENCY_GLOBAL_MAX',
    'GALAXY_MAX_CONTEXT_TOKENS', 'GALAXY_MAX_MESSAGE_SIZE',
  ],
  network: [
    'GALAXY_ENABLE_WEBRTC_DATA_CHANNEL', 'GALAXY_TURN_URLS', 'GALAXY_HEADSCALE_URL',
    'GALAXY_TAILSCALE_CHECK_INTERVAL', 'CORS_ALLOWED_ORIGINS',
    'CORS_ALLOWED_METHODS', 'CORS_ALLOWED_HEADERS',
  ],
  slo: [
    'GALAXY_SLO_LATENCY_WINDOW', 'GALAXY_SLO_HEARTBEAT_WINDOW',
    'GALAXY_RESULT_INGRESS_CONTINUITY_MODE', 'GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE',
    'GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S', 'GALAXY_TEMPORAL_URL',
    'GALAXY_GW_ADAPTER_DLQ_SUBJECT',
  ],
};

// ── Helper: derive label from key ───────────────────────────────────

function formatLabel(key: string): string {
  return key
    .replace(/^GALAXY_/, '')
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── Sub-components ──────────────────────────────────────────────────

function ToggleSwitch({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div
      className={`settings-toggle ${value ? 'on' : ''}`}
      onClick={() => onChange(!value)}
      role="switch"
      aria-checked={value}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          onChange(!value);
        }
      }}
    />
  );
}

function PasswordInput({
  value,
  placeholder,
  onChange,
}: {
  value: string;
  placeholder?: string;
  onChange: (v: string) => void;
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div className="settings-password-wrap">
      <input
        type={visible ? 'text' : 'password'}
        className="settings-input"
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
      <button
        className="settings-eye-btn"
        onClick={() => setVisible(!visible)}
        type="button"
        tabIndex={-1}
        aria-label={visible ? '隐藏' : '显示'}
      >
        {visible ? '🙈' : '👁️'}
      </button>
    </div>
  );
}

function NumberControl({
  value,
  min,
  max,
  step,
  onChange,
}: {
  value: number;
  min?: number;
  max?: number;
  step?: number;
  onChange: (v: number) => void;
}) {
  const minVal = min ?? 0;
  const maxVal = max ?? Math.max(100, value * 2);
  const stepVal = step ?? 1;

  return (
    <div className="settings-number-control">
      <input
        type="range"
        className="settings-slider"
        min={minVal}
        max={maxVal}
        step={stepVal}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      <input
        type="number"
        className="settings-input settings-number-input"
        min={minVal}
        max={maxVal}
        step={stepVal}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}

// ── Loading Spinner ─────────────────────────────────────────────────

function LoadingSpinner() {
  return (
    <div className="settings-loading">
      <div className="settings-spinner" />
      <span className="settings-loading-text">正在读取配置…</span>
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────

export default function SettingsTab() {
  const [config, setConfig] = useState<Record<string, ConfigItem>>({});
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [activeCategory, setActiveCategory] = useState<string>('ports');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 「端口与节点」「网络」「组网」分类里全是纯文本配置(URL/端口),之前从
  // 没做过任何真实连通性探测——用户看不到"这个地址现在到底通不通"，被解读
  // 成"没有接真实数据"。probeResults 保存每个 url 类字段的真实探测结果。
  const [probeResults, setProbeResults] = useState<
    Record<string, { loading: boolean; reachable?: boolean; latencyMs?: number | null; error?: string | null }>
  >({});
  // 节点名单(端口与节点页顶部展示全部 125 个节点:分类+排序+状态)。
  const [roster, setRoster] = useState<NodeRoster | null>(null);
  // OAuth 连接器(自建 A 方案):外部账号 Gmail/GitHub/Notion/Slack/Discord。
  const [connectors, setConnectors] = useState<ConnectorInfo[] | null>(null);
  const [connCfg, setConnCfg] = useState<string | null>(null); // 正在配 client_id 的服务
  const [cid, setCid] = useState('');
  const [csecret, setCsecret] = useState('');
  // 节点启停方式:子进程(默认,轻)或 容器(跑进所选 Docker/Podman,首次 build 慢)。
  const [nodeMode, setNodeMode] = useState<'subprocess' | 'container'>('subprocess');

  // ── Load config via shared cache ─────────────────────────────────

  const {
    data: cacheData,
    loading: cacheLoading,
    error: cacheError,
    reload: loadConfig,
    invalidate,
  } = useConfigCache(fetchSettings, []);

  // 同步 loading/error 状态
  useEffect(() => { setLoading(cacheLoading); }, [cacheLoading]);
  useEffect(() => { setError(cacheError); }, [cacheError]);

  // 当 cache 数据加载/刷新时，同步到本地 config
  useEffect(() => {
    if (cacheData) {
      setConfig(cacheData);
      setChanged({});
    }
  }, [cacheData]);

  // ── 拉节点名单 + 连接器状态(端口与节点页用);每 15s 刷新 ──
  useEffect(() => {
    let alive = true;
    const load = () => {
      fetchRoster().then((r) => { if (alive && r) setRoster(r); });
      fetchConnectors().then((c) => { if (alive && c) setConnectors(c); });
    };
    load();
    const t = setInterval(load, 15000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  const refreshConnectors = useCallback(
    () => fetchConnectors().then((c) => { if (c) setConnectors(c); }), []);

  // ── Listen for backend config updates ────────────────────────────

  useEffect(() => {
    if (!window.galaxyAPI) return;
    // 广播载荷是裸的 {KEY: 新值}(见 electron/main.js galaxy:set-config)，
    // 按 key 合并进已有 ConfigItem 的 .value，不能整项覆盖(否则 .value 之外的
    // type/category/description 会丢，渲染直接读到 undefined)。
    const unsubscribe = window.galaxyAPI.onConfigUpdate((changed) => {
      setConfig((prev) => {
        const next = { ...prev };
        Object.entries(changed).forEach(([k, v]) => {
          if (next[k]) next[k] = { ...next[k], value: v };
        });
        return next;
      });
    });
    return () => unsubscribe();
  }, []);

  // ── Toast helper ─────────────────────────────────────────────────

  const showToast = useCallback((message: string) => {
    if (toastTimerRef.current) {
      clearTimeout(toastTimerRef.current);
    }
    setToast(message);
    toastTimerRef.current = setTimeout(() => {
      setToast(null);
    }, 3000);
  }, []);

  // ── OAuth 连接器操作(showToast 之后定义,避免前向引用)──
  const connectService = useCallback((svc: string) => {
    const popup = window.open(
      `${getBackendUrl()}/api/v1/connectors/${svc}/authorize`, '_blank', 'width=560,height=720',
    );
    // 授权页(用户在弹窗里登录、同意授权)耗时因人而异——之前固定 4 秒后刷新
    // 一次,手慢一点(读同意页/输密码)就赶不上,状态卡在"未连接"直到用户自己
    // 手动切走再切回来。改成轮询弹窗是否关闭(回调页成功后 3 秒自动
    // window.close(),见 core/routes/nodes.py 的 connector_callback):关闭即
    // 说明流程走完(成功或用户主动关掉),立刻刷新一次拿到真实状态/账号名。
    if (popup) {
      const poll = setInterval(() => {
        if (popup.closed) {
          clearInterval(poll);
          refreshConnectors();
        }
      }, 800);
      // 兜底:弹窗被拦截识别不到关闭事件、或用户异常操作时,别永远轮询下去。
      setTimeout(() => clearInterval(poll), 5 * 60 * 1000);
    } else {
      setTimeout(refreshConnectors, 4000);
    }
  }, [refreshConnectors]);

  const disconnectService = useCallback(async (svc: string) => {
    await fetch(`${getBackendUrl()}/api/v1/connectors/${svc}/disconnect`, { method: 'POST' });
    refreshConnectors();
  }, [refreshConnectors]);

  const saveConnCreds = useCallback(async (svc: string) => {
    await fetch(`${getBackendUrl()}/api/v1/connectors/${svc}/credentials`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: cid.trim(), client_secret: csecret.trim() }),
    });
    setConnCfg(null); setCid(''); setCsecret('');
    showToast(`${svc} 凭据已保存,可点连接授权`);
    refreshConnectors();
  }, [cid, csecret, refreshConnectors, showToast]);

  // ── Value change handler ─────────────────────────────────────────

  const handleChange = useCallback((key: string, value: string) => {
    setChanged((prev) => ({ ...prev, [key]: value }));
  }, []);

  // ── Save handler ─────────────────────────────────────────────────

  const handleSave = useCallback(async () => {
    try {
      const result = window.galaxyAPI
        ? await window.galaxyAPI.setConfig(changed)
        : await (async () => {
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
          })();
      if (result.success) {
        // 保存成功后使缓存失效，确保读到服务端真值
        invalidate();
        setChanged({});
        showToast('已保存并即时生效');
      } else {
        // 修复:之前不管真实原因是什么,一律显示"保存失败"四个字，用户没法
        // 自己判断问题出在哪个字段。现在把后端/IPC 层透传上来的真实原因带出。
        showToast(result.error ? `保存失败：${result.error}` : '保存失败');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      showToast(`保存出错：${msg}`);
    }
  }, [changed, invalidate, showToast]);

  // ── Cancel handler ───────────────────────────────────────────────

  const handleCancel = useCallback(() => {
    setChanged({});
  }, []);

  // ── 连通性探测(真实 TCP 连接,不是伪造的固定状态) ──────────────────

  const probeKey = useCallback(async (key: string) => {
    setProbeResults((prev) => ({ ...prev, [key]: { loading: true } }));
    try {
      const base = await getBackendUrl();
      const r = await fetch(`${base}/api/config/probe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ keys: [key] }),
      });
      const body = await r.json();
      const result = body?.results?.[key];
      setProbeResults((prev) => ({
        ...prev,
        [key]: {
          loading: false,
          reachable: Boolean(result?.reachable),
          latencyMs: result?.latency_ms ?? null,
          error: result?.error ?? null,
        },
      }));
    } catch (err) {
      setProbeResults((prev) => ({
        ...prev,
        [key]: { loading: false, reachable: false, error: err instanceof Error ? err.message : '探测失败' },
      }));
    }
  }, []);

  // ── Render a single config item ──────────────────────────────────

  const renderControl = (key: string, item: ConfigItem) => {
    const currentValue = changed[key] !== undefined ? changed[key] : item.value;

    switch (item.type) {
      case 'boolean': {
        const boolVal = String(currentValue).toLowerCase() === 'true';
        return (
          <ToggleSwitch
            value={boolVal}
            onChange={(v) => handleChange(key, String(v))}
          />
        );
      }

      case 'password': {
        return (
          <PasswordInput
            value={currentValue}
            placeholder={item.default || '请输入…'}
            onChange={(v) => handleChange(key, v)}
          />
        );
      }

      case 'number': {
        const numVal = Number(currentValue) || 0;
        return (
          <NumberControl
            value={numVal}
            onChange={(v) => handleChange(key, String(v))}
          />
        );
      }

      case 'select': {
        const options = item.options ?? [];
        return (
          <select
            className="settings-select"
            value={currentValue}
            onChange={(e) => handleChange(key, e.target.value)}
          >
            {options.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        );
      }

      case 'url': {
        const probe = probeResults[key];
        const dotTone = probe?.loading
          ? 'checking'
          : probe?.reachable === true
            ? 'ok'
            : probe?.reachable === false
              ? 'fail'
              : 'idle';
        const dotTitle = probe?.loading
          ? '探测中…'
          : probe?.reachable === true
            ? `可达 · ${probe.latencyMs}ms`
            : probe?.reachable === false
              ? probe.error || '不可达'
              : '尚未探测';
        return (
          <div className="settings-url-probe-wrap">
            <input
              type="url"
              className="settings-input"
              value={currentValue}
              placeholder={item.default || 'https://...'}
              onChange={(e) => handleChange(key, e.target.value)}
            />
            <span
              className={`settings-probe-dot settings-probe-dot-${dotTone}`}
              title={dotTitle}
              aria-label={dotTitle}
            />
            <button
              type="button"
              className="settings-probe-btn"
              onClick={() => probeKey(key)}
              disabled={probe?.loading}
              title="测试真实连通性(TCP 连接)"
            >
              {probe?.loading ? '…' : '测试'}
            </button>
          </div>
        );
      }

      case 'string':
      default: {
        return (
          <input
            type="text"
            className="settings-input"
            value={currentValue}
            placeholder={item.default || '请输入…'}
            onChange={(e) => handleChange(key, e.target.value)}
          />
        );
      }
    }
  };

  // ── Render settings items for active category ────────────────────

  const renderCategoryItems = () => {
    const keys = CONFIG_KEYS[activeCategory] || [];
    const items: JSX.Element[] = [];

    keys.forEach((key) => {
      const item = config[key];
      const label = formatLabel(key);

      // 修复"tab 里啥都没有":后端 /api/config/all 没返回该 key 时,item 为空。此前
      // 直接 return → 整个分类一条不渲染 = 看着全空。改为渲染一个【占位行】(显示
      // key 名 + "未从后端加载"),让字段始终可见,而不是整条消失。
      if (!item) {
        items.push(
          <div key={key} className="settings-item settings-item-missing">
            <div className="settings-item-label">
              <div className="settings-item-name">{label}</div>
              <div className="settings-item-desc">未从后端加载(检查 /api/config/all)</div>
            </div>
            <div className="settings-item-control">
              <span className="settings-missing-badge">—</span>
            </div>
          </div>
        );
        return;
      }

      const isDirty = changed[key] !== undefined;

      items.push(
        <div key={key} className={`settings-item ${isDirty ? 'dirty' : ''}`}>
          <div className="settings-item-label">
            <div className="settings-item-name">{label}</div>
            {item.description && (
              <div className="settings-item-desc">{item.description}</div>
            )}
          </div>
          <div className="settings-item-control">
            {renderControl(key, item)}
          </div>
        </div>
      );
    });

    return items;
  };

  // 一键启停单个节点(阶段2a):POST /start|/stop → 刷新名单。
  const toggleNode = useCallback(async (n: RosterNode, running: boolean) => {
    try {
      await fetch(
        `${getBackendUrl()}/api/v1/nodes/${n.num}/${running ? 'stop' : 'start'}?mode=${nodeMode}`,
        { method: 'POST' });
      const via = nodeMode === 'container' ? '(容器)' : '';
      showToast(`${running ? '停止' : '启动'}${via} #${n.num} ${n.name}…`);
      // 容器首次要 build,给更久再刷新。
      setTimeout(() => fetchRoster().then((r) => { if (r) setRoster(r); }),
        nodeMode === 'container' ? 3000 : 1200);
    } catch {
      showToast(`操作 #${n.num} 失败`);
    }
  }, [showToast, nodeMode]);

  // ── 外部账号一键连接(自建 OAuth,A 方案)────────────────────────────
  const renderConnectors = () => {
    if (!connectors || connectors.length === 0) return null;
    const stMap: Record<string, { label: string; cls: string }> = {
      connected: { label: '已连接', cls: 'ok' },
      disconnected: { label: '未连接', cls: 'idle' },
      needs_config: { label: '待配置', cls: 'warn' },
    };
    return (
      <div className="connectors">
        <div className="connectors-title">外部账号连接<span className="connectors-sub">一键 OAuth · token 存本机</span></div>
        <div className="connector-grid">
          {connectors.map((c) => {
            const st = stMap[c.status] ?? stMap.disconnected;
            return (
              <div className="connector-card" key={c.service}>
                <div className="connector-row">
                  <span className="connector-name">{c.label}</span>
                  <span className={`connector-status ${st.cls}`}>
                    {st.label}{c.status === 'connected' && c.account ? ` · ${c.account}` : ''}
                  </span>
                </div>
                <div className="connector-actions">
                  {c.status === 'connected' ? (
                    <button className="connector-btn off" onClick={() => disconnectService(c.service)}>断开</button>
                  ) : c.status === 'disconnected' ? (
                    <button className="connector-btn on" onClick={() => connectService(c.service)}>连接授权</button>
                  ) : (
                    <button className="connector-btn cfg" onClick={() => setConnCfg(connCfg === c.service ? null : c.service)}>
                      {connCfg === c.service ? '收起' : '配置 App'}
                    </button>
                  )}
                </div>
                {connCfg === c.service && (
                  <div className="connector-cfg">
                    <div className="connector-cfg-hint">
                      1. 去 <a href={c.create_app_url} target="_blank" rel="noreferrer">建 OAuth App</a>;{c.create_hint}
                    </div>
                    <div className="connector-cfg-redirect">
                      回调地址(填进 App):<code>{c.redirect_uri}</code>
                    </div>
                    <input className="connector-input" placeholder="client_id" value={cid} onChange={(e) => setCid(e.target.value)} />
                    <input className="connector-input" placeholder="client_secret" type="password" value={csecret} onChange={(e) => setCsecret(e.target.value)} />
                    <button className="connector-btn on" onClick={() => saveConnCreds(c.service)}>保存凭据</button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    );
  };

  // ── 节点名单台(端口与节点页):125 个节点,按类型分组、编号排序、显示状态 ──
  const renderNodeRoster = () => {
    if (!roster) {
      return <div className="node-roster-loading">节点名单加载中…</div>;
    }
    // 按类型分组,组内按编号排序;类型顺序按节点数从多到少。
    const groups: Record<string, RosterNode[]> = {};
    roster.nodes.forEach((n) => { (groups[n.type] ||= []).push(n); });
    const typeOrder = Object.keys(groups).sort(
      (a, b) => (roster.type_counts[b] ?? 0) - (roster.type_counts[a] ?? 0)
    );
    return (
      <div className="node-roster">
        <div className="node-roster-head">
          <span className="node-roster-title">节点系统</span>
          <span className="node-roster-sub">
            共 {roster.count} 个 · {typeOrder.length} 类
          </span>
          <span className="node-mode-switch">
            启停方式:
            <button
              className={`node-mode-btn ${nodeMode === 'subprocess' ? 'active' : ''}`}
              onClick={() => setNodeMode('subprocess')}
              title="以本机 Python 子进程启动(轻,默认)"
            >子进程</button>
            <button
              className={`node-mode-btn ${nodeMode === 'container' ? 'active' : ''}`}
              onClick={() => setNodeMode('container')}
              title="跑进所选 Docker/Podman 容器(首次 build 慢,按需逐个起)"
            >容器</button>
          </span>
        </div>
        {typeOrder.map((type) => {
          const list = groups[type].sort((a, b) => a.num - b.num);
          const label = roster.type_labels[type] ?? type;
          return (
            <div className="node-group" key={type}>
              <div className="node-group-title">
                {label} <span className="node-group-count">{list.length}</span>
              </div>
              <div className="node-grid">
                {list.map((n) => {
                  const st = statusMeta(n.status);
                  const running = st.cls === 'ok' || st.cls === 'warn';
                  return (
                    <div className="node-card" key={n.num} title={n.purpose}>
                      <div className="node-card-top">
                        <span className="node-num">#{n.num}</span>
                        <span className="node-name">{n.name}</span>
                        <span className={`node-status ${st.cls}`}>{st.label}</span>
                        {n.runnable && (
                          <button
                            className={`node-toggle ${running ? 'stop' : 'start'}`}
                            onClick={() => toggleNode(n, running)}
                            title={running ? '停止该节点' : '启动该节点'}
                          >
                            {running ? '停止' : '启动'}
                          </button>
                        )}
                      </div>
                      <div className="node-card-meta">
                        {n.port && <span className="node-port">:{n.port}</span>}
                        {n.connector?.kind === 'oauth' && (
                          <span className="node-conn oauth">连接 {n.connector.service}</span>
                        )}
                        {n.connector?.kind === 'key' && (
                          <span className="node-conn key">需 Key {n.connector.service}</span>
                        )}
                        {!n.runnable && <span className="node-conn stub">占位</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
        <div className="node-roster-note">
          说明:名单来自全量审计(每个节点均为独立服务、皆可容器化)。一键启停 /
          一键连接(Gmail/GitHub/Notion…)/ 按需跑在 Docker·Podman —— 后续阶段接入。
        </div>
      </div>
    );
  };

  // ── Compute dirty state ──────────────────────────────────────────

  const isDirty = Object.keys(changed).length > 0;

  // ── Active category label ────────────────────────────────────────

  const activeLabel = CATEGORIES.find((c) => c.key === activeCategory)?.label ?? activeCategory;

  // ── Render ───────────────────────────────────────────────────────

  return (
    <div className="settings-tab">
      {/* ── Left Navigation ── */}
      <nav className="settings-nav">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.key}
            className={`settings-nav-item ${activeCategory === cat.key ? 'active' : ''}`}
            onClick={() => setActiveCategory(cat.key)}
            title={`${cat.label} (${cat.count} items)`}
          >
            <span className="settings-nav-icon">{cat.icon}</span>
            <span className="settings-nav-label">{cat.label}</span>
          </button>
        ))}
      </nav>

      {/* ── Right Content ── */}
      <div className="settings-content">
        {loading ? (
          <LoadingSpinner />
        ) : error ? (
          <div className="settings-error">
            <div className="settings-error-icon">⚠️</div>
            <div className="settings-error-text">{error}</div>
            <button className="settings-btn settings-btn-retry" onClick={loadConfig}>
              重试
            </button>
          </div>
        ) : (
          <>
            <div className="settings-scroll">
              <h2 className="settings-group-title">
                {activeLabel}
                <span className="settings-count">
                  {CONFIG_KEYS[activeCategory]?.length ?? 0} 项
                </span>
              </h2>
              {activeCategory === 'ports' && renderConnectors()}
              {activeCategory === 'ports' && renderNodeRoster()}
              <div className="settings-list">{renderCategoryItems()}</div>
            </div>

            {/* ── Footer ── */}
            <div className="settings-footer">
              <button
                className="settings-btn settings-btn-cancel"
                onClick={handleCancel}
                disabled={!isDirty}
              >
                放弃
              </button>
              <button
                className={`settings-btn settings-btn-save ${isDirty ? 'dirty' : ''}`}
                onClick={handleSave}
                disabled={!isDirty}
              >
                保存
                {isDirty && (
                  <span className="settings-dirty-badge">
                    {Object.keys(changed).length}
                  </span>
                )}
              </button>
            </div>
          </>
        )}

        {/* ── Toast ── */}
        {toast && <div className="settings-toast">{toast}</div>}
      </div>
    </div>
  );
}
