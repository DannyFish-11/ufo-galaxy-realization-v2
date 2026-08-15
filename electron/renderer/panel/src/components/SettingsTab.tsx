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
  // 保存超时死线的真源在主进程(electron/main.js 的 CONFIG_FETCH_BUDGET_MS 等
  // 常量);渲染层(ModelsTab.tsx)现查这个值而不是自己另维护一份独立数字，
  // 避免两边超时预算再次互相不对齐(真机复现过的"面板保存直接判假失败"根因)。
  getConfigSaveTimeoutMs?: () => Promise<number>;
  // 完整明细(本 tab 用):与 getConfig 分开路径,避免后端 /api/config 路由遮蔽
  // (system.py 精简版先注册、抢占同路径)导致这里永远读不到任何一项内容。
  getSettings?: () => Promise<Record<string, ConfigItem>>;
  onConfigUpdate: (callback: (changed: Record<string, string>) => void) => () => void;
  // 后端从"未就绪"变为"就绪"是异步的(main.js 在后台重试,不再阻塞
  // getConfig/getSettings 本身)。收到通知的一方(kind 区分是精简版还是完整
  // 明细)据此失效自己的缓存重新拉一次,而不是要求用户手动切走再切回来。
  onConfigReady?: (callback: (kind: 'config' | 'settings') => void) => () => void;
  saveConfig: () => Promise<{ success: boolean }>;
  /** 读取 Docker/Podman 安装/就绪/compose 与已选择状态。 */
  getRuntimeStatus?: () => Promise<RuntimeStatusPayload>;
  /** 对指定容器运行时执行可用性测试（引擎+compose）。 */
  testRuntime?: (runtime: 'docker' | 'podman') => Promise<{ ok: boolean; error?: string; details?: RuntimeItem }>;
  /** 保存并应用运行时选择。 */
  saveRuntime?: (runtime: 'docker' | 'podman') => Promise<{ ok: boolean; error?: string }>;
  /** 获取当前网关连接状态（用于离线提示/重试按钮）。 */
  getBackendStatus?: () => Promise<{ ok: boolean; healthy: boolean; baseUrl: string; managed: boolean; lastError?: string }>;
  /** 尝试从主进程拉起本地后端网关。 */
  startBackend?: () => Promise<{ ok: boolean; error?: string; baseUrl: string }>;
}

interface RuntimeItem {
  installed: boolean;
  version: string;
  daemon_ready: boolean;
  daemon_error?: string | null;
  compose_ready: boolean;
  compose_error?: string | null;
  compose_command?: string[];
}
interface RuntimeStatusPayload {
  ok: boolean;
  selected?: string;
  selected_source?: string;
  saved_choice?: string;
  saved_source?: string;
  requires_explicit_choice?: boolean;
  runtimes?: Record<'docker' | 'podman', RuntimeItem>;
}
const DEFAULT_BACKEND_BASE = 'http://localhost:9000';

// 浏览器预览兜底(无 galaxyAPI 时):直连后端完整明细端点。
// 真 bug 修复:此前这里是裸 fetch('/api/config/all')——相对路径解析到【页面自身
// 的 origin】,不是后端网关(与本文件其它 fetch 如 fetchRoster/fetchConnectors
// 等早就统一改成 await getBackendUrl() 不同,这里当时漏改)。也没有 vite 开发
// 代理去桥接这个落差,所以纯浏览器预览(无 Electron)下打开设置 tab,每个分类
// 都会显示"未从后端加载"占位行,保存也必然失败——与注释"直连后端"名不副实。
async function fetchSettings(): Promise<Record<string, ConfigItem>> {
  if (window.galaxyAPI?.getSettings) return window.galaxyAPI.getSettings();
  const base = await getBackendUrl();
  const r = await fetch(`${base}/api/config/all`);
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
    // getBackendUrl() 是 async(返回 Promise)——之前直接插进模板字符串,URL 会变成
    // "http://[object Promise]/..." 导致请求必失败,节点名单永远卡在"加载中…"。
    const base = await getBackendUrl();
    const r = await fetch(`${base}/api/v1/nodes/roster`);
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
    const base = await getBackendUrl();
    const r = await fetch(`${base}/api/v1/connectors`);
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
  advanced?: boolean;   // true=开发者/高级项，默认收在「高级」分组里，不占普通用户视线
}

// 注：模型 API（llm 类）已迁到专门的「模型」tab（ModelsTab），此处不再重复。
// 「行为 · 在场」放在最前并作默认分类——这些是最常调的面向用户开关(说/流式/
// 自发在场/原生音频),用户无需再去设置环境变量,打开设置即见、一键切换。
// 限流熔断/网络/开发者/服务水平 是内部/高级项(用户反馈"看不懂"),标 advanced,
// 默认折进「高级 · 开发者」分组,普通用户界面只留常用的几类。
// 真 bug 修复:每个分类的项数此前在这里手写死数字(count),跟下方 CONFIG_KEYS
// 实际数组长度早就对不上(behavior 写 6、实际 12;auth 写 12、实际 11;
// mesh 写 13、实际 15——因为 GALAXY_SYSTEM_MODE 曾重复登记在 mesh/dev 两处)。
// 内容区角标(见 renderCategoryItems 用 CONFIG_KEYS[activeCategory]?.length)
// 早就是从数组现算的,唯独这里的导航栏 title 提示还是手写死数字,会显示错误的
// 项数。彻底删掉这个字段,改在渲染处统一从 CONFIG_KEYS[cat.key].length 现算，
// 不再有第二份需要手动同步的数字。
const CATEGORIES: CategoryDef[] = [
  { key: 'behavior', label: '行为 · 在场', icon: '✨' },
  { key: 'ports', label: '端口与节点', icon: '🔌' },
  { key: 'auth', label: '鉴权', icon: '🔒' },
  { key: 'mesh', label: '组网 · 多设备', icon: '🕸️' },
  { key: 'storage', label: '存储', icon: '💾' },
  { key: 'circuit', label: '限流熔断', icon: '⚡', advanced: true },
  { key: 'dev', label: '开发者', icon: '🛠️', advanced: true },
  { key: 'network', label: '网络', icon: '🌐', advanced: true },
  { key: 'slo', label: '服务水平', icon: '📊', advanced: true },
];

// ── Config Key Registry ─────────────────────────────────────────────
//
// 标题里原先写着「(105 items)」,而实际是 99 项 —— 又一个手写死的数字漂掉了。
// 上面 CATEGORIES 那段注释已经为同类问题下过结论(每个分类的项数改为渲染时从
// CONFIG_KEYS[cat.key].length 现算,不再留第二份要手工同步的数字),这里照同一个
// 结论办:直接不写数字。要数就数数组。

const CONFIG_KEYS: Record<string, string[]> = {
  behavior: [
    'GALAXY_AUTONOMY',
    'GALAXY_SPEAK', 'GALAXY_TTS_ENGINE', 'GALAXY_ASR_ENGINE', 'GALAXY_VOICE_EAGERNESS',
    'GALAXY_VOICE_DELEGATE', 'GALAXY_VOICE_BACKCHANNEL', 'GALAXY_TTS_STREAMING', 'GALAXY_AMBIENT_LOOP',
    'GALAXY_NATIVE_AUDIO', 'GALAXY_AMBIENT_INTERVAL_S', 'GALAXY_AMBIENT_COOLDOWN_S',
    // 边说边听:开关先行,细调参数排在后面。
    //
    // 这一组此前【只存在于后端代码里】——功能真在跑,但既没登记进
    // core/routes/config.py::CONFIG_SCHEMA,也不在本注册表里。两边缺任何一边这一项
    // 都不会出现在设置页:后端缺 → /api/config/all 不返回它,前端渲染成"未从后端加载";
    // 前端缺 → 后端认识它但这里不列出,页面上根本没有它的位置。而且 set_config 会把
    // 未登记的键当 unknown_keys 拒掉,所以前端硬塞也存不进去。
    'GALAXY_AEC', 'GALAXY_VOICE_ECHO_GUARD', 'GALAXY_VOICE_BACKCHANNEL_TOLERANCE',
    'GALAXY_SYSTEM_AUDIO_CAPTURE', 'GALAXY_SYSTEM_AUDIO_TO_PERCEPTION',
    'GALAXY_VOICE_DUPLEX', 'GALAXY_VOICE_DUCKING',
    'GALAXY_VOICE_DUCK_GAIN', 'GALAXY_VOICE_HOLD_S',
    'GALAXY_VOICE_ECHO_SIM', 'GALAXY_VOICE_ECHO_TAIL_S',
    'GALAXY_VOICE_ECHO_MIN_CHARS', 'GALAXY_VOICE_ECHO_MIN_BLOCK',
    'GALAXY_AEC_TAIL_MS', 'GALAXY_AEC_MU', 'GALAXY_AEC_MAX_DELAY_MS', 'GALAXY_AEC_DTD_MARGIN_DB',
    // 残余回声抑制(第二级,治非线性回声)+ 双讲滞后保持 + 舒适噪声
    'GALAXY_AEC_RES', 'GALAXY_AEC_RES_OVER', 'GALAXY_AEC_RES_FLOOR_DB',
    'GALAXY_AEC_RES_DT_FLOOR_DB', 'GALAXY_AEC_DTD_HANGOVER', 'GALAXY_AEC_COMFORT_NOISE',
    // 文字与语音同刻(三态 auto/1/0)
    'GALAXY_TEXT_VOICE_LOCKSTEP',
    'GALAXY_REALTIME_PROVIDER', 'GALAXY_REALTIME_MODEL', 'GALAXY_REALTIME_VOICE', 'GALAXY_REALTIME_URL',
    // 本地全模态 server 的 realtime 路径。B 档原生就绪且没配云端 key 时,双工会自动指向
    // 本地 server 的这个路径试一次流式;server 路径不是默认 /v1/realtime 时在这里改。
    'GALAXY_NATIVE_REALTIME_PATH',
    // B 档本地全模态 server 与模态通路。此前两边都没登记 —— 功能在跑但只能手改 .env。
    'GALAXY_MINICPM_SERVER_URL', 'GALAXY_NATIVE_MODAL_AUTO',
    'GALAXY_AMBIENT_ASR_SIZE', 'GALAXY_VIDEO_FPS_NATIVE', 'GALAXY_VIDEO_FPS_BRIDGE',
    // 本地 OpenAI 兼容推理服务(双模型本地主脑里跑在核显那一位)。llama.cpp server 的
    // SYCL/Vulkan 后端 或 OpenVINO Model Server 都讲这套协议,填地址即接入。
    'GALAXY_LOCAL_OPENAI_URL', 'GALAXY_LOCAL_OPENAI_MODEL', 'GALAXY_LOCAL_OPENAI_SERVES',
    'GALAXY_LOCAL_OPENAI_KEY',
    // 密钥项。后端 classify_key() 按 _API_KEY 后缀判为 secret,会走 set_secret() 落
    // runtime/secrets.env,不明文进 .env —— 所以在这里列出来是安全的。
    'GALAXY_REALTIME_API_KEY',
    // ── 语音/感知栈的其余配置键(2026-08-04 一次性登记齐)────────────────────
    // 前两轮补登记都是发现一处补一处(先 21 个语音开关、再 5 个 B 档模态键),
    // 每次都还有剩。根因是后端那道守卫的模块清单是手工维护的,没写进清单的模块
    // 就静默不受保护。那份清单已改成按目录模式派生(core/tts/*.py、core/asr/*.py、
    // core/perception/*.py …),派生后一次扫出 36 个,除部署标记 GALAXY_ENV 外全在这里。
    // 桌面操作闭环
    'GALAXY_COMPUTER_USE', 'GALAXY_CU_MAX_STEPS', 'GALAXY_CU_SETTLE_S',
    // 连续感知
    'GALAXY_DESKTOP_PERCEPTION_TTL', 'GALAXY_PERCEPTION_PRIVACY_DEFAULT',
    'GALAXY_PROACTIVE_SCREEN', 'GALAXY_AMBIENT_SHARE_SESSION', 'GALAXY_VOICE_DIAG_S',
    // 回话时序(文字与语音同刻的细调)
    'GALAXY_CHAT_TIMEOUT_S', 'GALAXY_LOCKSTEP_CPS', 'GALAXY_LOCKSTEP_GRACE_S',
    'GALAXY_LOCKSTEP_STALL_S', 'GALAXY_LOCKSTEP_DRAIN_S',
    // 语音识别
    'GALAXY_ASR_INITIAL_PROMPT', 'GALAXY_SENSEVOICE_MODEL',
    // 语音合成:Edge / Piper / Kokoro / Melo / IndexTTS-2
    'GALAXY_EDGE_TTS_TIMEOUT_S', 'GALAXY_PIPER_MODEL',
    'GALAXY_KOKORO_MODEL', 'GALAXY_KOKORO_VOICE', 'GALAXY_KOKORO_LANG', 'GALAXY_KOKORO_AUTOFETCH',
    'GALAXY_MELO_LANG', 'GALAXY_MELO_SPEAKER', 'GALAXY_MELO_SPEED', 'GALAXY_MELO_DEVICE',
    'GALAXY_INDEXTTS_REF_AUDIO', 'GALAXY_INDEXTTS_AUTOFETCH',
    'GALAXY_INDEXTTS_EMO_AUDIO', 'GALAXY_INDEXTTS_EMO_TEXT', 'GALAXY_INDEXTTS_USE_EMO_TEXT',
    'GALAXY_INDEXTTS_EMO_ALPHA', 'GALAXY_INDEXTTS_FP16',
    // 启动器侧的语音总闸与桌面外壳(launcher/services.py)。GALAXY_VOICE 决定语音
    // 循环起不起来 —— 整条语音链路的开关都在面板上,唯独最上面那个总闸此前只能手改 .env。
    'GALAXY_VOICE', 'GALAXY_WHISPER_MODEL', 'GALAXY_DESKTOP_SHELL',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_OPENSOURCE_FIRST', 'GALAXY_BANDIT_ROUTING', 'GALAXY_ROUTE_OBSERVED_WEIGHT',
    'GALAXY_ROUTE_LATENCY_WEIGHT', 'GALAXY_ROUTE_TOKEN_WEIGHT', 'GALAXY_CASCADE_FLOOR_MID',
    'GALAXY_CASCADE_FLOOR_HI', 'GALAXY_MODEL_TIER', 'GALAXY_HF_OLLAMA_FALLBACK',
    'GALAXY_OLLAMA_NUM_CTX', 'GALAXY_OLLAMA_KEEP_ALIVE', 'GALAXY_URL_SENTINEL',
    'GALAXY_MOA_ENABLED', 'GALAXY_MOA_COMPLEXITY', 'GALAXY_MOA_PROPOSERS',
    'GALAXY_MOA_LAYERS', 'GALAXY_CRITIC_MAX_ROUNDS', 'GALAXY_FORCE_COLLAB_MODE',
    'GALAXY_PLANNER_MAX_REPLANS', 'GALAXY_EXPERIENCE_STRATEGY', 'GALAXY_UNIFIED_WORKFLOW',
    'GALAXY_TOOLS_SLIM', 'GALAXY_TOOLS_JIT', 'GALAXY_TOOLS_STICKY',
    'GALAXY_TOOLS_CORE', 'GALAXY_ACTIVE_PERCEPTION', 'GALAXY_ACI_ENABLED',
    'GALAXY_FAST_LOOP', 'GALAXY_FOCUS_STACK_ENABLED', 'GALAXY_MANIFEST_ON_FIRST_TOKEN',
    'GALAXY_LIMINAL_REHEARSAL', 'GALAXY_REHEARSAL_CANDIDATES', 'GALAXY_REHEARSAL_COMPLEXITY_FLOOR',
    'GALAXY_HA_BRIDGE', 'GALAXY_TTS_VOICE', 'GALAXY_SPEAK_MAX_CHARS',
    'GALAXY_LOCAL_AUDIO', 'GALAXY_NATIVE_MM_CHAT', 'GALAXY_HITL_CONFIRM_GATE',
    'GALAXY_HITL_CONFIRM_TIMEOUT_S', 'GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S', 'GALAXY_MEMORY_BACKENDS',
    'GALAXY_EMBED_MODEL', 'GALAXY_CLIP_MODEL', 'GALAXY_CLAP_MODEL',
    'GALAXY_SIMPLEMEM_MODEL', 'GALAXY_SIMPLEMEM_API_KEY', 'GALAXY_REMOTE_DESKTOP',
    'GALAXY_VNC_CMD', 'GALAXY_DEVICE_NAME', 'GALAXY_DEVICE_TYPE',
    'GALAXY_DURABLE_EXEC', 'GALAXY_DISPATCH_IDEMPOTENCY',
  ],
  ports: [
    'GATEWAY_PORT', 'UFO_NODE_HOST', 'NODE_92_URL', 'NODE_45_URL', 'NODE_33_URL',
    'NODE_71_URL', 'NODE_71_HOST', 'NODE_95_URL', 'NODE_97_URL', 'NODE09_SANDBOX_URL',
    'OLLAMA_URL', 'QDRANT_URL', 'REDIS_URL', 'SECRETVAULT_URL', 'MAIN_REPO_URL',
    'MQTT_PORT',
    // 节点起停(launcher/node_startup.py)
    'GALAXY_API_HOST', 'GALAXY_NODE_HEALTH_RETRIES',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_VNC_PORT',
  ],
  auth: [
    'GALAXY_AUTH_ENABLED', 'GALAXY_API_TOKEN', 'GALAXY_API_TOKENS',
    'GALAXY_API_TOKEN_EXPIRY', 'GALAXY_REVOKED_TOKENS', 'GALAXY_REQUIRE_API_TOKEN',
    'GALAXY_STRICT_AUTHORITY_CHECK', 'GALAXY_SECRET_BACKEND', 'GALAXY_TLS_CERT',
    'GITHUB_TOKEN', 'GALAXY_MESH_SECRET',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_PERM_STRICT', 'GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT', 'GALAXY_INPUT_VALIDATION_LOOPBACK',
    'GALAXY_RATE_LIMIT_LOOPBACK', 'GALAXY_DEVICE_TOKEN_RETENTION_DAYS', 'GALAXY_DEVICE_TOKEN_MAX_RECORDS',
    'GALAXY_PEER_DEFAULT_TRUST',
  ],
  mesh: [
    'GALAXY_MDNS', 'GALAXY_MASTER_BRAIN_ENABLED', 'GALAXY_SYSTEM_MODE', 'GALAXY_FABRIC_STRICT',
    'GALAXY_NATS_ENABLED', 'GALAXY_NATS_URL', 'GALAXY_NATS_EXECUTOR_TIMEOUT',
    'GALAXY_NATS_EXECUTOR_FALLBACK', 'GALAXY_CROSS_DEVICE_ENABLED',
    'GALAXY_HEARTBEAT_INTERVAL', 'FEDERATION_ENABLED', 'FEDERATION_LOCAL_HOST',
    'FEDERATION_PEERS', 'FEDERATION_HEARTBEAT_INTERVAL',
    'GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_LAN_DISCOVERY', 'GALAXY_LAN_DISCOVERY_TYPES', 'GALAXY_MESH_DISCOVERY_TIMEOUT',
    'GALAXY_TRANSPORT_ADAPTIVE', 'GALAXY_TRANSPORT_BULK_BYTES', 'GALAXY_TS_ADVERTISE_RELAY',
    'GALAXY_TS_FUNNEL',
    'GALAXY_ANDROID_WS_ENABLED', 'GALAXY_GATEWAY_MODE',
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
    // 语音模型放哪儿。与上面几项同属"东西存在哪",归 storage 而不是 behavior
    // (behavior 里放的是这些引擎**怎么发音**的参数)。
    'GALAXY_KOKORO_DIR', 'GALAXY_INDEXTTS_DIR',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_CLIP_DIR', 'GALAXY_CLAP_DIR', 'GALAXY_OMNIMEM_DIR',
    'GALAXY_TASK_LEDGER_PATH', 'GALAXY_TASK_ALLOCATION_STATE_PATH', 'GALAXY_TASK_GRAPH_STATE_PATH',
    'GALAXY_LAST_OPERATOR_ACTION_STATE_PATH', 'GALAXY_PEER_TRUST_PATH', 'GALAXY_DEVICE_TOKEN_STORE',
  ],
  dev: [
    // 真 bug 修复:GALAXY_SYSTEM_MODE 此前在 mesh/dev 两个分类里重复出现——
    // core/routes/config.py::CONFIG_SCHEMA 里它的唯一 canonical category 是
    // "mesh"(desktop-local/desktop-cross-device),dev 分类是误重复。功能上
    // 编辑不受影响(共用同一份 changed 状态),但导致下方 CATEGORIES 的项数
    // 统计跟着漂移。只保留 mesh 分类里的那一份。
    'GALAXY_DEV_MODE', 'GALAXY_MODE', 'GALAXY_PREFLIGHT_MODE',
    'GALAXY_PREFLIGHT_FAIL_FAST', 'GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK',
    'GALAXY_ENTRYMODE_USE_READINESS', 'CMD_MAX_CONCURRENT', 'CONCURRENCY_GLOBAL_MAX',
    'GALAXY_MAX_CONTEXT_TOKENS', 'GALAXY_MAX_MESSAGE_SIZE',
    // 统一启动器(main.py / launcher/*.py)。多数是从旧启动器原样搬过来的键 ——
    // 旧启动器时代就没接进面板,这次把守卫范围扩到 launcher/ 才扫出来。
    'GALAXY_SKIP_ELECTRON', 'GALAXY_TAURI_AUTOBUILD',
    'GALAXY_AUTO_DOCKER', 'GALAXY_CONTAINER_RUNTIME',
    'GALAXY_AUTO_DOCKER_DAEMON_WAIT', 'GALAXY_AUTO_DOCKER_WAIT',
    'GALAXY_VERBOSE', 'GALAXY_STRICT_PREFLIGHT',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_TAURI_AUTO_INSTALL_MSVC', 'GALAXY_PHASE_TIMING', 'GALAXY_PANEL_PUSH_MIN_INTERVAL',
    'GALAXY_MODELS_PROBE_BUDGET', 'GALAXY_MODELS_STATUS_TTL',
  ],
  network: [
    'GALAXY_ENABLE_WEBRTC_DATA_CHANNEL', 'GALAXY_TURN_URLS', 'GALAXY_HEADSCALE_URL',
    'GALAXY_TAILSCALE_CHECK_INTERVAL',
    // 模型下载源。真正决定用哪个源的是 core/hf_endpoint.py::pick_endpoint()
    // (探测择优后写回 HF_ENDPOINT),这里配的是它的偏好起点。
    'GALAXY_HF_ENDPOINT', 'GALAXY_HF_MIRROR',
    // 依赖下载源(launcher/deps.py)
    'GALAXY_PIP_INDEX',
    'CORS_ALLOWED_ORIGINS',
    'CORS_ALLOWED_METHODS', 'CORS_ALLOWED_HEADERS',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_SIGNALING_TIMEOUT_S', 'GALAXY_SIMPLEMEM_BASE_URL',
  ],
  slo: [
    'GALAXY_SLO_LATENCY_WINDOW', 'GALAXY_SLO_HEARTBEAT_WINDOW',
    'GALAXY_RESULT_INGRESS_CONTINUITY_MODE', 'GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE',
    'GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S', 'GALAXY_TEMPORAL_URL',
    'GALAXY_GW_ADAPTER_DLQ_SUBJECT',
    // ── core/ 全量补登记(2026-08-05)──────────────────────────────────────
    // 守卫范围放到整个 core/ 之后一次扫出 99 个未登记键，其中 92 个是用户
    // 设置项。前三轮「发现一处补一处」覆盖到的仍只是配置面的一部分。
    'GALAXY_OTEL_ENABLED', 'GALAXY_OTEL_EXPORTER', 'GALAXY_OTEL_SERVICE_NAME',
    'GALAXY_OPS_FAILURE_REASONS_MAX', 'GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX', 'GALAXY_OPS_REJECTION_REASONS_MAX',
    'GALAXY_OPS_FALLBACK_KINDS_MAX',
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

/** 推拉开关。
 *
 * 用的是 App.css 里那份 `.switch` / `.switch-knob` —— 与 MeshView 的 NATS Worker
 * 开关【同一套类名、同一份样式】,而不是各自长得差不多的两份实现。此前
 * SettingsTab.css 里另有一个 `.settings-toggle`(白滑块 + accent 底、无描边),
 * 和 worker 那个(描边轨道 + 滑块变绿)并排放在同一个面板里能看出不一致。
 * 统一到 worker 那份:轨道带描边、开启时轨道转绿且滑块也转绿。
 *
 * 轨道用 <button> 而非 <div>:原生按钮自带键盘激活与焦点管理,不必手写
 * onKeyDown 去补 Enter/Space —— 少一处会和浏览器默认行为不一致的自造轮子。
 */
function ToggleSwitch({
  value,
  onChange,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      className={`switch${value ? ' on' : ''}`}
      onClick={() => onChange(!value)}
      role="switch"
      aria-checked={value}
    >
      <span className="switch-knob" />
    </button>
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

// ── Main Component ──────────────────────────────────────────────────

export default function SettingsTab() {
  const [config, setConfig] = useState<Record<string, ConfigItem>>({});
  const [changed, setChanged] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [activeCategory, setActiveCategory] = useState<string>('behavior');
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
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
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatusPayload | null>(null);
  const [runtimeSelection, setRuntimeSelection] = useState<'docker' | 'podman'>('docker');
  const [runtimeBusy, setRuntimeBusy] = useState(false);
  const [backendStatus, setBackendStatus] = useState<{ healthy: boolean; baseUrl: string; managed: boolean; lastError?: string } | null>(null);

  // ── Load config via shared cache ─────────────────────────────────

  const {
    data: cacheData,
    loading: cacheLoading,
    error: cacheError,
    reload: loadConfig,
    invalidate,
  } = useConfigCache('settings-config', fetchSettings);

  // 同步 loading/error 状态
  useEffect(() => { setLoading(cacheLoading); }, [cacheLoading]);
  useEffect(() => { setError(cacheError); }, [cacheError]);

  // 后端后台就绪通知 → 主动失效缓存重新拉取(见 useConfigCache 顶部注释)。
  useEffect(() => {
    if (!window.galaxyAPI?.onConfigReady) return undefined;
    return window.galaxyAPI.onConfigReady((kind) => {
      if (kind === 'settings') invalidate();
    });
  }, [invalidate]);

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

  const refreshRuntimeStatus = useCallback(async () => {
    try {
      if (!window.galaxyAPI?.getRuntimeStatus) return;
      const state = await window.galaxyAPI.getRuntimeStatus();
      setRuntimeStatus(state);
      const selected = (state?.selected || state?.saved_choice || '') as 'docker' | 'podman';
      if (selected === 'docker' || selected === 'podman') setRuntimeSelection(selected);
    } catch (e) {
      setToast(`运行时检测失败：${e instanceof Error ? e.message : ''}`);
    }
  }, []);

  const refreshBackendStatus = useCallback(async () => {
    try {
      if (!window.galaxyAPI?.getBackendStatus) return;
      const st = await window.galaxyAPI.getBackendStatus();
      if (st?.ok) setBackendStatus({
        healthy: Boolean(st.healthy),
        baseUrl: st.baseUrl,
        managed: Boolean(st.managed),
        lastError: st.lastError || '',
      });
    } catch {
      /* ignore */
    }
  }, []);

  useEffect(() => {
    refreshRuntimeStatus();
    refreshBackendStatus();
    const t = setInterval(refreshBackendStatus, 10000);
    return () => clearInterval(t);
  }, [refreshRuntimeStatus, refreshBackendStatus]);

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
  const connectService = useCallback(async (svc: string) => {
    const base = await getBackendUrl();
    const popup = window.open(
      `${base}/api/v1/connectors/${svc}/authorize`, '_blank', 'width=560,height=720',
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

  // 真 bug 修复:这两个接口(core/routes/nodes.py::connector_disconnect/
  // connector_creds)无论成功失败都固定返回 HTTP 200,真实结果只在响应体的
  // {ok, error} 里——此前只看 fetch 是否抛异常(网络层失败才会抛),完全没读
  // 响应体的 ok 字段,也没包 try/catch。于是后端拒绝(比如未知连接器)时,
  // disconnectService 悄无声息什么反馈都没有,saveConnCreds 还会无条件弹出
  // "凭据已保存"的成功提示、并清空刚填的 client_id/secret 输入框——用户以为
  // 保存成功,实际什么都没存住,还得重新把两个值再打一遍。
  const disconnectService = useCallback(async (svc: string) => {
    try {
      const base = await getBackendUrl();
      const r = await fetch(`${base}/api/v1/connectors/${svc}/disconnect`, { method: 'POST' });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.ok === false) {
        showToast(`${svc} 断开失败：${body?.error || `HTTP ${r.status}`}`);
        return;
      }
      refreshConnectors();
    } catch (e) {
      showToast(`${svc} 断开出错：${e instanceof Error ? e.message : ''}`);
    }
  }, [refreshConnectors, showToast]);

  const saveConnCreds = useCallback(async (svc: string) => {
    try {
      const base = await getBackendUrl();
      const r = await fetch(`${base}/api/v1/connectors/${svc}/credentials`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ client_id: cid.trim(), client_secret: csecret.trim() }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok || body?.ok === false) {
        showToast(`${svc} 凭据保存失败：${body?.error || `HTTP ${r.status}`}`);
        return; // 保存失败时保留 cid/csecret 输入框内容,不清空,免得用户重打一遍
      }
      setConnCfg(null); setCid(''); setCsecret('');
      showToast(`${svc} 凭据已保存,可点连接授权`);
      refreshConnectors();
    } catch (e) {
      showToast(`${svc} 凭据保存出错：${e instanceof Error ? e.message : ''}`);
    }
  }, [cid, csecret, refreshConnectors, showToast]);

  const testSelectedRuntime = useCallback(async () => {
    if (!window.galaxyAPI?.testRuntime) return;
    setRuntimeBusy(true);
    try {
      const res = await window.galaxyAPI.testRuntime(runtimeSelection);
      if (res?.ok) showToast(`${runtimeSelection} 运行时检测通过`);
      else showToast(`运行时检测失败：${res?.error || '未知错误'}`);
      await refreshRuntimeStatus();
    } catch (e) {
      showToast(`运行时检测异常：${e instanceof Error ? e.message : ''}`);
    } finally {
      setRuntimeBusy(false);
    }
  }, [runtimeSelection, refreshRuntimeStatus, showToast]);

  const saveSelectedRuntime = useCallback(async () => {
    if (!window.galaxyAPI?.saveRuntime) return;
    setRuntimeBusy(true);
    try {
      const res = await window.galaxyAPI.saveRuntime(runtimeSelection);
      if (res?.ok) showToast(`已保存并应用运行时：${runtimeSelection}`);
      else showToast(`保存运行时失败：${res?.error || '未知错误'}`);
      await refreshRuntimeStatus();
    } catch (e) {
      showToast(`保存运行时异常：${e instanceof Error ? e.message : ''}`);
    } finally {
      setRuntimeBusy(false);
    }
  }, [runtimeSelection, refreshRuntimeStatus, showToast]);

  const startBackendFromPanel = useCallback(async () => {
    if (!window.galaxyAPI?.startBackend) return;
    setRuntimeBusy(true);
    try {
      const res = await window.galaxyAPI.startBackend();
      if (res?.ok) showToast('网关已就绪');
      else showToast(`网关启动失败：${res?.error || '未知错误'}`);
      await refreshBackendStatus();
    } catch (e) {
      showToast(`网关启动异常：${e instanceof Error ? e.message : ''}`);
    } finally {
      setRuntimeBusy(false);
    }
  }, [refreshBackendStatus, showToast]);

  // ── Value change handler ─────────────────────────────────────────

  const handleChange = useCallback((key: string, value: string) => {
    setChanged((prev) => ({ ...prev, [key]: value }));
  }, []);

  // ── Save handler ─────────────────────────────────────────────────

  const handleSave = useCallback(async () => {
    if (saving) return;
    // 真 bug 修复(数据丢失):保存这条 IPC 调用最长可能要等主进程 ~68s 的
    // 冷启动重试预算(见 electron/main.js CONFIG_FETCH_BUDGET_MS),但此前此按钮
    // 没有任何 saving 态锁定——用户在保存进行中继续编辑其它字段,一旦这次保存
    // 成功返回,`setChanged({})` 会把保存期间新增的编辑连同已保存的一起【无条件
    // 清空】,用户眼睁睁看着刚打的字消失,毫无提示。这里先快照本次实际要保存的
    // 内容,保存成功后只精确移除"值自那以后未再被改过"的那些键——保存期间新增
    // 或改成新值的编辑原样保留在 changed 里,下次点保存会带上它们。
    const snapshot = changed;
    setSaving(true);
    try {
      const result = window.galaxyAPI
        ? await window.galaxyAPI.setConfig(snapshot)
        : await (async () => {
            // 真 bug 修复:此前是裸 fetch('/api/config', ...)——相对路径解析到
            // 页面自身 origin 而非后端网关,浏览器预览模式下保存必然失败。
            const base = await getBackendUrl();
            const r = await fetch(`${base}/api/config`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ config: snapshot }),
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
        setChanged((prev) => {
          const next = { ...prev };
          for (const k of Object.keys(snapshot)) {
            if (next[k] === snapshot[k]) delete next[k];
          }
          return next;
        });
        showToast('已保存并即时生效');
      } else {
        // 修复:之前不管真实原因是什么,一律显示"保存失败"四个字，用户没法
        // 自己判断问题出在哪个字段。现在把后端/IPC 层透传上来的真实原因带出。
        showToast(result.error ? `保存失败：${result.error}` : '保存失败');
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : '';
      showToast(`保存出错：${msg}`);
    } finally {
      setSaving(false);
    }
  }, [changed, invalidate, showToast, saving]);

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
      const base = await getBackendUrl();
      await fetch(
        `${base}/api/v1/nodes/${n.num}/${running ? 'stop' : 'start'}?mode=${nodeMode}`,
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

  const renderRuntimeManager = () => {
    if (!runtimeStatus) return null;
    const runtimes = runtimeStatus.runtimes || ({} as Record<'docker' | 'podman', RuntimeItem>);
    const options: Array<'docker' | 'podman'> = ['docker', 'podman'];
    const selected = runtimeSelection;
    const noneInstalled = options.every((rt) => !runtimes[rt]?.installed);
    return (
      <div className="runtime-manager">
        <div className="runtime-manager-head">
          <span className="runtime-manager-title">容器运行时</span>
          <span className="runtime-manager-sub">
            已选：{runtimeStatus.selected || '未选择'} · 来源：{runtimeStatus.selected_source || 'none'}
          </span>
        </div>
        <div className="runtime-grid">
          {options.map((rt) => {
            const s = runtimes[rt];
            const installed = Boolean(s?.installed);
            return (
              <label key={rt} className={`runtime-card ${selected === rt ? 'active' : ''} ${installed ? '' : 'disabled'}`}>
                <div className="runtime-card-row">
                  <input
                    type="radio"
                    name="runtime-choice"
                    checked={selected === rt}
                    disabled={!installed}
                    onChange={() => setRuntimeSelection(rt)}
                  />
                  <span className="runtime-name">{rt}</span>
                  <span className={`runtime-pill ${installed ? 'ok' : 'off'}`}>{installed ? '已安装' : '未安装'}</span>
                </div>
                <div className="runtime-meta">版本：{s?.version || '—'}</div>
                <div className="runtime-meta">
                  引擎：{s?.daemon_ready ? '就绪' : '未就绪'}{s?.daemon_error ? ` · ${s.daemon_error}` : ''}
                </div>
                <div className="runtime-meta">
                  Compose：{s?.compose_ready ? '可用' : '不可用'}{s?.compose_error ? ` · ${s.compose_error}` : ''}
                </div>
              </label>
            );
          })}
        </div>
        {runtimeStatus.requires_explicit_choice && (
          <div className="runtime-warning">检测到 Docker 与 Podman 同时可用，请先显式保存选择后再启动容器模式。</div>
        )}
        {noneInstalled && (
          <div className="runtime-warning">未检测到 Docker/Podman。请先安装其一，再点击“检测/刷新”。</div>
        )}
        <div className="runtime-actions">
          <button className="connector-btn cfg" type="button" onClick={refreshRuntimeStatus} disabled={runtimeBusy}>
            检测/刷新
          </button>
          <button className="connector-btn on" type="button" onClick={testSelectedRuntime} disabled={runtimeBusy || !runtimes[selected]?.installed}>
            测试运行时
          </button>
          <button className="connector-btn on" type="button" onClick={saveSelectedRuntime} disabled={runtimeBusy || !runtimes[selected]?.installed}>
            保存并应用
          </button>
        </div>
        <div className="runtime-gateway">
          <span className={`runtime-pill ${backendStatus?.healthy ? 'ok' : 'off'}`}>
            网关 {backendStatus?.healthy ? '已连接' : '离线'}
          </span>
          <span className="runtime-meta runtime-gateway-url">{backendStatus?.baseUrl || DEFAULT_BACKEND_BASE}</span>
          {!backendStatus?.healthy && (
            <button className="connector-btn cfg" type="button" onClick={startBackendFromPanel} disabled={runtimeBusy}>
              重试启动网关
            </button>
          )}
          {!backendStatus?.healthy && backendStatus?.lastError && (
            <div className="runtime-warning">{backendStatus.lastError}</div>
          )}
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
      {/* 常用类常显;高级/开发者类折进可展开分组,避免"一堆看不懂的东西"占视线。 */}
      <nav className="settings-nav">
        {CATEGORIES.filter((c) => !c.advanced).map((cat) => (
          <button
            key={cat.key}
            className={`settings-nav-item ${activeCategory === cat.key ? 'active' : ''}`}
            onClick={() => setActiveCategory(cat.key)}
            title={`${cat.label} (${CONFIG_KEYS[cat.key]?.length ?? 0} items)`}
          >
            <span className="settings-nav-icon">{cat.icon}</span>
            <span className="settings-nav-label">{cat.label}</span>
          </button>
        ))}
        <button
          className="settings-nav-item settings-nav-advanced-toggle"
          onClick={() => setShowAdvanced((v) => !v)}
          title="高级 / 开发者设置(限流、网络、SLO 等)"
        >
          <span className="settings-nav-icon">{showAdvanced ? '▾' : '▸'}</span>
          <span className="settings-nav-label">高级 · 开发者</span>
        </button>
        {showAdvanced && CATEGORIES.filter((c) => c.advanced).map((cat) => (
          <button
            key={cat.key}
            className={`settings-nav-item settings-nav-sub ${activeCategory === cat.key ? 'active' : ''}`}
            onClick={() => setActiveCategory(cat.key)}
            title={`${cat.label} (${CONFIG_KEYS[cat.key]?.length ?? 0} items)`}
          >
            <span className="settings-nav-icon">{cat.icon}</span>
            <span className="settings-nav-label">{cat.label}</span>
          </button>
        ))}
      </nav>

      {/* ── Right Content ── */}
      {/* 界面本体始终渲染,不再用 loading/error 整屏遮挡——后端可能要几十秒
          到几分钟才响应(尤其是启动期的 Ollama),之前"loading 就整屏转圈"
          会让用户完全没法看/改任何一项设置。缺项时 renderCategoryItems()
          本就会渲染"未从后端加载"的占位行,真实数据到达后原地补上。 */}
      <div className="settings-content">
        {error && !Object.keys(config).length && (
          <div className="settings-sync-banner">
            <span>⚠ 暂未连接后端 · 后台自动重试中（{error}）</span>
            <button className="settings-btn-retry-inline" onClick={loadConfig} type="button">
              重试
            </button>
          </div>
        )}
        <div className="settings-scroll">
          <h2 className="settings-group-title">
            {activeLabel}
            <span className="settings-count">
              {CONFIG_KEYS[activeCategory]?.length ?? 0} 项
            </span>
            {loading && <span className="settings-sync-dot" title="正在后台同步…" />}
          </h2>
          {activeCategory === 'ports' && renderRuntimeManager()}
          {activeCategory === 'ports' && renderConnectors()}
          {activeCategory === 'ports' && renderNodeRoster()}
          <div className="settings-list">{renderCategoryItems()}</div>
        </div>

        {/* ── Footer ── */}
        <div className="settings-footer">
          <button
            className="settings-btn settings-btn-cancel"
            onClick={handleCancel}
            disabled={!isDirty || saving}
          >
            放弃
          </button>
          <button
            className={`settings-btn settings-btn-save ${isDirty ? 'dirty' : ''}`}
            onClick={handleSave}
            disabled={!isDirty || saving}
          >
            {saving ? '保存中…' : '保存'}
            {isDirty && !saving && (
              <span className="settings-dirty-badge">
                {Object.keys(changed).length}
              </span>
            )}
          </button>
        </div>

        {/* ── Toast ── */}
        {toast && <div className="settings-toast">{toast}</div>}
      </div>
    </div>
  );
}
