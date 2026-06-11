import { useEffect, useState, useCallback, useRef } from 'react';
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
  setConfig: (config: Record<string, string>) => Promise<{ success: boolean }>;
  onConfigUpdate: (callback: (config: Record<string, ConfigItem>) => void) => () => void;
  saveConfig: () => Promise<{ success: boolean }>;
}

declare global {
  interface Window {
    galaxyAPI?: GalaxyAPI;
  }
}

// ── Category Definitions ────────────────────────────────────────────

interface CategoryDef {
  key: string;
  label: string;
  icon: string;
  count: number;
}

const CATEGORIES: CategoryDef[] = [
  { key: 'llm', label: 'LLM Keys', icon: '🔑', count: 20 },
  { key: 'ports', label: 'Ports', icon: '🔌', count: 16 },
  { key: 'auth', label: 'Auth', icon: '🔒', count: 12 },
  { key: 'mesh', label: 'Mesh', icon: '🕸️', count: 11 },
  { key: 'circuit', label: 'Circuit', icon: '⚡', count: 14 },
  { key: 'storage', label: 'Storage', icon: '💾', count: 7 },
  { key: 'dev', label: 'Dev', icon: '🛠️', count: 11 },
  { key: 'network', label: 'Network', icon: '🌐', count: 7 },
  { key: 'slo', label: 'SLO', icon: '📊', count: 7 },
];

// ── Config Key Registry (105 items) ─────────────────────────────────

const CONFIG_KEYS: Record<string, string[]> = {
  llm: [
    'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'DEEPSEEK_API_KEY', 'GOOGLE_API_KEY',
    'GEMINI_API_KEY', 'XAI_API_KEY', 'MISTRAL_API_KEY', 'QWEN_API_KEY',
    'DASHSCOPE_API_KEY', 'ZHIPU_API_KEY', 'GROQ_API_KEY', 'HF_API_TOKEN',
    'MOONSHOT_API_KEY', 'MIMO_API_KEY', 'MINIMAX_API_KEY', 'PERPLEXITY_API_KEY',
    'STEP_API_KEY', 'ONEAPI_URL', 'ONEAPI_API_KEY', 'LOCAL_VLLM_URL',
  ],
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
        aria-label={visible ? 'Hide password' : 'Show password'}
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
      <span className="settings-loading-text">Loading configuration...</span>
    </div>
  );
}

// ── Main Component ──────────────────────────────────────────────────

export default function SettingsTab() {
  const [config, setConfig] = useState<Record<string, ConfigItem>>({});
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [activeCategory, setActiveCategory] = useState<string>('llm');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Load config on mount ─────────────────────────────────────────

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (!window.galaxyAPI) {
        throw new Error('Galaxy API not available — running in browser mode?');
      }
      const data = await window.galaxyAPI.getConfig();
      setConfig(data);
      setChanged({});
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load config';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // ── Listen for backend config updates ────────────────────────────

  useEffect(() => {
    if (!window.galaxyAPI) return;
    const unsubscribe = window.galaxyAPI.onConfigUpdate((newConfig) => {
      setConfig((prev) => {
        const merged = { ...prev, ...newConfig };
        return merged;
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

  // ── Value change handler ─────────────────────────────────────────

  const handleChange = useCallback((key: string, value: string) => {
    setChanged((prev) => ({ ...prev, [key]: value }));
  }, []);

  // ── Save handler ─────────────────────────────────────────────────

  const handleSave = useCallback(async () => {
    if (!window.galaxyAPI) {
      showToast('Error: Galaxy API not available');
      return;
    }
    try {
      const result = await window.galaxyAPI.setConfig(changed);
      if (result.success) {
        setConfig((prev) => {
          const updated = { ...prev };
          Object.entries(changed).forEach(([k, v]) => {
            if (updated[k]) {
              updated[k] = { ...updated[k], value: v };
            }
          });
          return updated;
        });
        setChanged({});
        showToast('Configuration saved successfully');
      } else {
        showToast('Failed to save configuration');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Save failed';
      showToast(`Error: ${msg}`);
    }
  }, [changed, showToast]);

  // ── Cancel handler ───────────────────────────────────────────────

  const handleCancel = useCallback(() => {
    setChanged({});
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
            placeholder={item.default || 'Enter value'}
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
        return (
          <input
            type="url"
            className="settings-input"
            value={currentValue}
            placeholder={item.default || 'https://...'}
            onChange={(e) => handleChange(key, e.target.value)}
          />
        );
      }

      case 'string':
      default: {
        return (
          <input
            type="text"
            className="settings-input"
            value={currentValue}
            placeholder={item.default || 'Enter value'}
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
      if (!item) return;

      const label = formatLabel(key);
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
              Retry
            </button>
          </div>
        ) : (
          <>
            <div className="settings-scroll">
              <h2 className="settings-group-title">
                {activeLabel}
                <span className="settings-count">
                  {CONFIG_KEYS[activeCategory]?.length ?? 0} items
                </span>
              </h2>
              <div className="settings-list">{renderCategoryItems()}</div>
            </div>

            {/* ── Footer ── */}
            <div className="settings-footer">
              <button
                className="settings-btn settings-btn-cancel"
                onClick={handleCancel}
                disabled={!isDirty}
              >
                Cancel
              </button>
              <button
                className={`settings-btn settings-btn-save ${isDirty ? 'dirty' : ''}`}
                onClick={handleSave}
                disabled={!isDirty}
              >
                Save Changes
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
