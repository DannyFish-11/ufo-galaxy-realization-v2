/**
 * 设置面的键清单 —— **数据,不是界面。**
 *
 * ## 这个文件为什么存在
 *
 * 旧的 React 面板被这一版 HUD 整个替换掉了。旧面板里有两处手写的键清单:
 *
 * - `SettingsTab.tsx` 的 `KEY_ORDER_HINT` —— 每一类里的显示顺序(303 个键,9 类)
 * - `ModelsTab.tsx` 的 provider 键 —— 供应商那一档能配哪些键(25 个,
 *   下面的 `PROVIDER_KEYS` 是 26 个:多出来的 `OLLAMA_MODEL` 见那里的说明)
 *
 * 它们不是渲染代码,是**判据**:`tests/test_config_schema_ui_parity.py` 一直
 * 拿它们跟 `core/routes/config.py::CONFIG_SCHEMA` 对账 —— 界面上出现、后端却
 * 不认的键,POST /api/config 会 400,用户看到的是「保存失败」。
 *
 * 删掉旧面板时如果把它们一起删了,那道门就没东西可读,只能跟着删。**那是在
 * 悄悄减少覆盖**,不是在重构。所以搬到这里,门改指这里。
 *
 * ## 现在这份清单**正在被渲染**(此前这里写的是相反的话)
 *
 * `ui/settings.ts` 就是那个设置面,`dock.ts` 的「全部设置」按钮打开它,
 * `main.ts` 每次打开都重新拉 `/api/config/all`。2026-09-04 实测后端返回 335 个键、
 * 9 类,每一个都在这一页上有一行可以改。(这是当天的快照 —— 键会随功能增减,
 * 数目本身不是判据;判据是那道 UI-后端对账门。)
 *
 * 这段文档此前说的是「没有任何界面在渲染这份清单」「那个按钮还没有接任何东西」
 * 「这 303 个键一个都调不了」—— 那是设置面**建成之前**写下的话,建成之后没人回来
 * 改它。留着它的代价不是「文档不好看」:下一个人读到「还没建」,要么以为面板没做完,
 * 要么真的再去建第二个设置面,于是同一件事有了两处实现。本仓最怕的是「看起来接上了、
 * 其实没有」,这是它的镜像 —— **其实接上了、文档说没接**,一样会把人带错。
 *
 * 所以不能只把话改对就完事:下面那道门(`tests/test_settings_inventory_doc_is_not_stale.py`)
 * 盯着这件事 —— 只要还有界面 import 这份清单,这里就不许再出现「还没有界面 /
 * 还没有接任何东西 / 一个都调不了」这类说法。话一旦再过期,它自己会红。
 *
 * ## 这份清单管什么、不管什么
 *
 * 管:同一类**里面**的显示顺序,以及那道 UI-后端对账门读什么。
 * 不管:一个键属于哪一类 —— 那个由后端 `/api/config/all` 的 `category` 现算。
 */

/**
 * 每一类里的显示顺序。未列到的键按字母序跟在后面。
 *
 * **这里的分组名必须是后端 `/api/config/all` 真正会返回的 category。**
 *
 * 2026-09-03 修:此前这份表的分组名是 behavior / ports / auth / mesh / circuit /
 * storage / dev / slo —— 那是**更早一版**的后端分类名。后端早就改成了按「人想干
 * 什么」分的九类(voice / perception / agent / memory / devices / security /
 * network / llm / advanced),而设置页是拿 `KEY_ORDER_HINT[category]` 去查的。
 *
 * 于是九组里只有 `network` 这一个名字碰巧还对得上,另外八组**一次都没有被查到过**,
 * 303 个键实际上全按字母序在排。这正是本仓最常见的那种失效:接口还在、调用还在、
 * 不报错,只是什么都没发生。
 *
 * 下面按真实 category 重新分了组,组内保持原来的相对先后;每一档的**主键**提到
 * 它那一类的最前面 —— 那是「这项能力开不开」,其余都是它的细调。
 *
 * `tests/test_config_schema_ui_parity.py` 现在把分组名和成员关系一起对账:
 * 分组名不是真 category、或者某个键列错了类,都会当场红。
 */
export const KEY_ORDER_HINT: Record<string, string[]> = {
  voice: [
    'GALAXY_SPEAK', 'GALAXY_TTS_ENGINE', 'GALAXY_ASR_ENGINE', 'GALAXY_VOICE_EAGERNESS',
    'GALAXY_VOICE_DELEGATE', 'GALAXY_VOICE_BACKCHANNEL', 'GALAXY_TTS_STREAMING',
    'GALAXY_NATIVE_AUDIO', 'GALAXY_AEC', 'GALAXY_VOICE_ECHO_GUARD',
    'GALAXY_VOICE_BACKCHANNEL_TOLERANCE', 'GALAXY_VOICE_DUPLEX', 'GALAXY_VOICE_DUCKING',
    'GALAXY_VOICE_DUCK_GAIN', 'GALAXY_VOICE_HOLD_S', 'GALAXY_VOICE_ECHO_SIM',
    'GALAXY_VOICE_ECHO_TAIL_S', 'GALAXY_VOICE_ECHO_MIN_CHARS', 'GALAXY_VOICE_ECHO_MIN_BLOCK',
    'GALAXY_AEC_TAIL_MS', 'GALAXY_AEC_MU', 'GALAXY_AEC_MAX_DELAY_MS', 'GALAXY_AEC_DTD_MARGIN_DB',
    'GALAXY_AEC_RES', 'GALAXY_AEC_RES_OVER', 'GALAXY_AEC_RES_FLOOR_DB',
    'GALAXY_AEC_RES_DT_FLOOR_DB', 'GALAXY_AEC_DTD_HANGOVER', 'GALAXY_AEC_COMFORT_NOISE',
    'GALAXY_TEXT_VOICE_LOCKSTEP', 'GALAXY_REALTIME_VOICE', 'GALAXY_AMBIENT_ASR_SIZE',
    'GALAXY_VOICE_DIAG_S', 'GALAXY_LOCKSTEP_CPS', 'GALAXY_LOCKSTEP_GRACE_S',
    'GALAXY_LOCKSTEP_STALL_S', 'GALAXY_LOCKSTEP_DRAIN_S', 'GALAXY_ASR_INITIAL_PROMPT',
    'GALAXY_SENSEVOICE_MODEL', 'GALAXY_EDGE_TTS_TIMEOUT_S', 'GALAXY_PIPER_MODEL',
    'GALAXY_KOKORO_MODEL', 'GALAXY_KOKORO_VOICE', 'GALAXY_KOKORO_LANG', 'GALAXY_KOKORO_AUTOFETCH',
    'GALAXY_MELO_LANG', 'GALAXY_MELO_SPEAKER', 'GALAXY_MELO_SPEED', 'GALAXY_MELO_DEVICE',
    'GALAXY_INDEXTTS_REF_AUDIO', 'GALAXY_INDEXTTS_AUTOFETCH', 'GALAXY_INDEXTTS_EMO_AUDIO',
    'GALAXY_INDEXTTS_EMO_TEXT', 'GALAXY_INDEXTTS_USE_EMO_TEXT', 'GALAXY_INDEXTTS_EMO_ALPHA',
    'GALAXY_INDEXTTS_FP16', 'GALAXY_VOICE', 'GALAXY_WHISPER_MODEL', 'GALAXY_TTS_VOICE',
    'GALAXY_SPEAK_MAX_CHARS', 'GALAXY_LOCAL_AUDIO', 'GALAXY_KOKORO_DIR', 'GALAXY_INDEXTTS_DIR',
  ],
  perception: [
    'GALAXY_AMBIENT_LOOP', 'GALAXY_AMBIENT_INTERVAL_S', 'GALAXY_AMBIENT_COOLDOWN_S',
    'GALAXY_SYSTEM_AUDIO_CAPTURE', 'GALAXY_SYSTEM_AUDIO_TO_PERCEPTION',
    'GALAXY_NATIVE_REALTIME_PATH', 'GALAXY_NATIVE_MODAL_AUTO', 'GALAXY_VIDEO_FPS_NATIVE',
    'GALAXY_VIDEO_FPS_BRIDGE', 'GALAXY_PERCEPTION_MODEL', 'GALAXY_DESKTOP_PERCEPTION_TTL',
    'GALAXY_PERCEPTION_PRIVACY_DEFAULT', 'GALAXY_PROACTIVE_SCREEN',
    'GALAXY_AMBIENT_SHARE_SESSION', 'GALAXY_ACTIVE_PERCEPTION', 'GALAXY_NATIVE_MM_CHAT',
    'GALAXY_CLIP_MODEL', 'GALAXY_CLAP_MODEL', 'GALAXY_CLIP_DIR', 'GALAXY_CLAP_DIR',
  ],
  agent: [
    'GALAXY_AUTONOMY', 'GALAXY_SPECULATIVE_DRAFT', 'GALAXY_REALTIME_PROVIDER',
    'GALAXY_REALTIME_MODEL', 'GALAXY_REALTIME_URL', 'GALAXY_MINICPM_SERVER_URL',
    'GALAXY_MCP_PIN_MODE', 'GALAXY_LLAMA_SERVER_BIN', 'GALAXY_LOCAL_OPENAI_URL',
    'GALAXY_LOCAL_OPENAI_MODEL', 'GALAXY_LOCAL_OPENAI_SERVES', 'GALAXY_LOCAL_OPENAI_KEY',
    'GALAXY_REASONING_OPENAI_URL', 'GALAXY_REASONING_OPENAI_MODEL',
    'GALAXY_REASONING_OPENAI_SERVES', 'GALAXY_REASONING_OPENAI_KEY', 'GALAXY_REALTIME_API_KEY',
    'GALAXY_COMPUTER_USE', 'GALAXY_CU_MAX_STEPS', 'GALAXY_CU_SETTLE_S', 'GALAXY_CHAT_TIMEOUT_S',
    'GALAXY_OPENSOURCE_FIRST', 'GALAXY_BANDIT_ROUTING', 'GALAXY_ROUTE_OBSERVED_WEIGHT',
    'GALAXY_ROUTE_LATENCY_WEIGHT', 'GALAXY_ROUTE_TOKEN_WEIGHT', 'GALAXY_CASCADE_FLOOR_MID',
    'GALAXY_CASCADE_FLOOR_HI', 'GALAXY_MODEL_TIER', 'GALAXY_HF_OLLAMA_FALLBACK',
    'GALAXY_OLLAMA_NUM_CTX', 'GALAXY_LLAMA_CTX', 'GALAXY_IGNORE_CONTEXT_MEASUREMENTS',
    'GALAXY_OLLAMA_KEEP_ALIVE', 'GALAXY_MOA_ENABLED', 'GALAXY_MOA_COMPLEXITY',
    'GALAXY_MOA_PROPOSERS', 'GALAXY_MOA_LAYERS', 'GALAXY_CRITIC_MAX_ROUNDS',
    'GALAXY_FORCE_COLLAB_MODE', 'GALAXY_PLANNER_MAX_REPLANS', 'GALAXY_UNIFIED_WORKFLOW',
    'GALAXY_TOOLS_SLIM', 'GALAXY_TOOLS_JIT', 'GALAXY_TOOLS_STICKY', 'GALAXY_TOOLS_CORE',
    'GALAXY_FAST_LOOP', 'GALAXY_LIMINAL_REHEARSAL', 'GALAXY_REHEARSAL_CANDIDATES',
    'GALAXY_REHEARSAL_COMPLEXITY_FLOOR', 'GALAXY_DURABLE_EXEC', 'GALAXY_DISPATCH_IDEMPOTENCY',
    'OLLAMA_URL', 'GALAXY_ROUTER_ADAPTIVE_CONCURRENCY', 'GALAXY_ROUTER_CB_ENABLED',
    'GALAXY_ROUTER_MAX_QUEUE_DEPTH', 'GALAXY_MODELS_PROBE_BUDGET', 'GALAXY_MODELS_STATUS_TTL',
  ],
  memory: [
    'GALAXY_CONTEXT_ARCHIVE_MAX_MB', 'GALAXY_CONTEXT_ARCHIVE_MIN_DAYS',
    'GALAXY_PHASE_LEDGER_DAYS', 'GALAXY_EXPERIENCE_STRATEGY', 'GALAXY_ACI_ENABLED',
    'GALAXY_FOCUS_STACK_ENABLED', 'GALAXY_MEMORY_BACKENDS', 'GALAXY_EMBED_MODEL',
    'GALAXY_SIMPLEMEM_MODEL', 'GALAXY_SIMPLEMEM_API_KEY', 'CHROMA_PERSIST_DIR',
    'GALAXY_OMNIMEM_DIR', 'GALAXY_SIMPLEMEM_BASE_URL',
  ],
  devices: [
    'GALAXY_CROSS_DEVICE_ENABLED', 'GALAXY_HA_BRIDGE', 'GALAXY_REMOTE_DESKTOP', 'GALAXY_VNC_CMD',
    'GALAXY_DEVICE_NAME', 'GALAXY_DEVICE_TYPE', 'UFO_NODE_HOST', 'NODE_92_URL', 'NODE_45_URL',
    'NODE_33_URL', 'NODE_71_URL', 'NODE_71_HOST', 'NODE_95_URL', 'NODE_97_URL',
    'GALAXY_NODE_HEALTH_RETRIES', 'GALAXY_VNC_PORT', 'GALAXY_MESH_SECRET',
    'GALAXY_DEVICE_TOKEN_RETENTION_DAYS', 'GALAXY_DEVICE_TOKEN_MAX_RECORDS', 'GALAXY_MDNS',
    'GALAXY_MASTER_BRAIN_ENABLED', 'GALAXY_SYSTEM_MODE', 'GALAXY_FABRIC_STRICT',
    'GALAXY_NATS_ENABLED', 'GALAXY_NATS_URL', 'GALAXY_NATS_EXECUTOR_TIMEOUT',
    'GALAXY_NATS_EXECUTOR_FALLBACK', 'GALAXY_HEARTBEAT_INTERVAL', 'FEDERATION_ENABLED',
    'FEDERATION_LOCAL_HOST', 'FEDERATION_PEERS', 'FEDERATION_HEARTBEAT_INTERVAL',
    'GALAXY_LAN_DISCOVERY', 'GALAXY_LAN_DISCOVERY_TYPES', 'GALAXY_MESH_DISCOVERY_TIMEOUT',
    'GALAXY_TS_ADVERTISE_RELAY', 'GALAXY_TS_FUNNEL', 'GALAXY_ANDROID_WS_ENABLED',
    'GALAXY_MASTER_BRAIN_STATE_PATH', 'ANDROID_DEVICE_STATE_STORE_PATH',
    'ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS', 'GALAXY_DEVICE_TOKEN_STORE',
    'GALAXY_ENABLE_WEBRTC_DATA_CHANNEL', 'GALAXY_TURN_URLS', 'GALAXY_SIGNALING_TIMEOUT_S',
    'GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S',
  ],
  security: [
    'GALAXY_EXECUTION_ISOLATION', 'GALAXY_TRUST_REMOTE_CODE', 'GALAXY_WEIGHTS_HOSTS',
    'GALAXY_WEIGHTS_ALLOW_PICKLE', 'GALAXY_EGRESS_MODE', 'GALAXY_EGRESS_ALLOW',
    'GALAXY_EGRESS_ALLOW_PRIVATE', 'GALAXY_ALLOW_ENDPOINT_OVERRIDE', 'GALAXY_TOOL_GUARDIAN',
    'GALAXY_MANIFEST_ON_FIRST_TOKEN', 'GALAXY_HITL_CONFIRM_GATE', 'GALAXY_HITL_CONFIRM_TIMEOUT_S',
    'GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S', 'NODE09_SANDBOX_URL', 'SECRETVAULT_URL',
    'GALAXY_AUTH_ENABLED', 'GALAXY_API_TOKEN', 'GALAXY_API_TOKENS', 'GALAXY_API_TOKEN_EXPIRY',
    'GALAXY_REVOKED_TOKENS', 'GALAXY_REQUIRE_API_TOKEN', 'GALAXY_STRICT_AUTHORITY_CHECK',
    'GALAXY_SECRET_BACKEND', 'GALAXY_TLS_CERT', 'GITHUB_TOKEN', 'GALAXY_PERM_STRICT',
    'GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT', 'GALAXY_INPUT_VALIDATION_LOOPBACK',
    'GALAXY_RATE_LIMIT_LOOPBACK', 'GALAXY_PEER_DEFAULT_TRUST',
    'GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE', 'GALAXY_PEER_TRUST_PATH',
    'GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK', 'GALAXY_MAX_CONTEXT_TOKENS', 'CORS_ALLOWED_ORIGINS',
    'CORS_ALLOWED_METHODS', 'CORS_ALLOWED_HEADERS',
  ],
  network: [
    'GATEWAY_PORT', 'MQTT_PORT', 'GALAXY_API_HOST', 'GALAXY_TRANSPORT_ADAPTIVE',
    'GALAXY_TRANSPORT_BULK_BYTES', 'GALAXY_GATEWAY_MODE', 'GALAXY_HEADSCALE_URL',
    'GALAXY_TAILSCALE_CHECK_INTERVAL', 'GALAXY_HF_ENDPOINT', 'GALAXY_HF_MIRROR',
    'GALAXY_PIP_INDEX', 'GALAXY_OTEL_EXPORTER',
  ],
  advanced: [
    'GALAXY_DESKTOP_SHELL', 'GALAXY_URL_SENTINEL', 'QDRANT_URL', 'REDIS_URL', 'MAIN_REPO_URL',
    'GALAXY_CB_FAILURE_THRESHOLD', 'GALAXY_CB_RECOVERY_TIMEOUT_S', 'GALAXY_CB_HALF_OPEN_PROBES',
    'GALAXY_CB_WINDOW_SIZE', 'GALAXY_AS_TARGET_LATENCY_MS', 'GALAXY_AS_ERROR_THRESHOLD',
    'GALAXY_AS_INIT_LIMIT', 'GALAXY_AS_MAX_LIMIT', 'GALAXY_AS_MIN_LIMIT',
    'GALAXY_AS_SAMPLE_WINDOW', 'GALAXY_AS_PROBE_INTERVAL_S', 'GALAXY_DATA_DIR',
    'GALAXY_MARKET_STORE_DIR', 'GALAXY_FEATURE_FLAGS_PATH', 'GALAXY_TASK_LEDGER_PATH',
    'GALAXY_TASK_ALLOCATION_STATE_PATH', 'GALAXY_TASK_GRAPH_STATE_PATH',
    'GALAXY_LAST_OPERATOR_ACTION_STATE_PATH', 'GALAXY_DEV_MODE', 'GALAXY_MODE',
    'GALAXY_PREFLIGHT_MODE', 'GALAXY_PREFLIGHT_FAIL_FAST', 'GALAXY_ENTRYMODE_USE_READINESS',
    'CMD_MAX_CONCURRENT', 'CONCURRENCY_GLOBAL_MAX', 'GALAXY_MAX_MESSAGE_SIZE',
    'GALAXY_SKIP_ELECTRON', 'GALAXY_TAURI_AUTOBUILD', 'GALAXY_AUTO_DOCKER',
    'GALAXY_CONTAINER_RUNTIME', 'GALAXY_AUTO_DOCKER_DAEMON_WAIT', 'GALAXY_AUTO_DOCKER_WAIT',
    'GALAXY_VERBOSE', 'GALAXY_STRICT_PREFLIGHT', 'GALAXY_TAURI_AUTO_INSTALL_MSVC',
    'GALAXY_PHASE_TIMING', 'GALAXY_PANEL_PUSH_MIN_INTERVAL', 'GALAXY_SLO_LATENCY_WINDOW',
    'GALAXY_SLO_HEARTBEAT_WINDOW', 'GALAXY_RESULT_INGRESS_CONTINUITY_MODE',
    'GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE', 'GALAXY_TEMPORAL_URL',
    'GALAXY_GW_ADAPTER_DLQ_SUBJECT', 'GALAXY_OTEL_ENABLED', 'GALAXY_OTEL_SERVICE_NAME',
    'GALAXY_OPS_FAILURE_REASONS_MAX', 'GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX',
    'GALAXY_OPS_REJECTION_REASONS_MAX', 'GALAXY_OPS_FALLBACK_KINDS_MAX',
  ],
};

/**
 * 供应商那一档能配的键 —— 也就是各家的 API Key 填在哪。
 *
 * 来自旧 `ModelsTab.tsx`。此前这里写着「这一档在新面板里同样还没有界面」,
 * 同样是过期的话:实测这 26 个键**全部**出现在 `/api/config/all` 的 `llm` 类里,
 * 在「全部设置 → 大模型」那一段逐个可填。密钥类的键走密码框,且已有值永远不回填
 * 到 DOM —— 那等于把密钥又摊开一次。
 *
 * `llm` 这一类没有出现在上面的 `KEY_ORDER_HINT` 里,所以这 29 个键按字母序排。
 * 这是清单说好的兜底行为(未列到的跟在后面),不是漏接。
 */
export const PROVIDER_KEYS: readonly string[] = [
  // 旧 ModelsTab 里这个不是目录条目的 key: 字段,而是在判「本地档开没开」时
  // 直接读的(isSet(get('OLLAMA_MODEL')))。按 key:/extraKey: 抽取会漏掉它,
  // 而 llm 这一类是**委派**出去的 —— 漏一个就等于它在整个面板上无处可配。
  'OLLAMA_MODEL',
  'AGNES_API_KEY',
  'ANTHROPIC_API_KEY',
  'DEEPSEEK_API_KEY',
  'DEEPSEEK_OCR2_API_KEY',
  'GOOGLE_API_KEY',
  'GROQ_API_KEY',
  'HF_API_TOKEN',
  'LOCAL_VLLM_URL',
  'META_API_KEY',
  'MIMO_API_KEY',
  'MINIMAX_API_KEY',
  'MISTRAL_API_KEY',
  'MOONSHOT_API_KEY',
  'ONEAPI_API_KEY',
  'ONEAPI_URL',
  'OPENAI_API_BASE',
  'OPENAI_API_KEY',
  'OPENROUTER_API_KEY',
  'PERPLEXITY_API_KEY',
  'QWEN_API_KEY',
  'STEP_API_KEY',
  'XAI_API_KEY',
  'ZHIPU_API_BASE',
  'ZHIPU_API_KEY',
  'ZHIPU_CODING_API_KEY',
];

/**
 * 不在设置面出现的分类 —— 由别处拥有。
 *
 * **显式列出**而不是「碰巧没列」:某一类没出现,和某一类被别人管着,是两件事;
 * 后者要写下来才查得到。`tests/test_voice_switches_reach_the_panel.py` 会核对
 * 「声称委派出去的键,是不是真的在那边」—— 否则「委派」就是「藏起来」的好听说法。
 */
export const DELEGATED_CATEGORIES = new Set<string>([
  // **这里现在是空的,而且这件事必须说清楚。**
  //
  // 原先 'llm' 在这儿,理由是「模型 API key 归 ModelsTab:那边是供应商目录,
  // 拍平成设置页的 key-value 行会把中文名/用途标注/配套 base URL 全毁掉」。
  //
  // 那个理由当时成立。但 ModelsTab 随旧 React 面板一起删掉了 —— **委派的目的地
  // 不存在了**。继续把 llm 标成「已委派」,等于声称那 29 个供应商键在别处管着,
  // 而实际上它们无处可配。这正是「委派」变成「藏起来」的好听说法的那一刻。
  //
  // 所以 llm 收回到设置页,并在 CATEGORIES 里给了它自己的标签。等供应商目录那个
  // 界面真的建起来,再把它移回来 —— 到那时这一行有目的地,才配叫委派。
]);

export interface CategoryDef {
  readonly key: string;
  readonly label: string;
  readonly advanced?: boolean;
}

/**
 * 分类的中文标签。
 *
 * **没有图标这一栏。** 原来每一类配一个 emoji(🔊 👁️ 🧠 …),2026-09-04 整个删掉 ——
 * 连字段一起删,不留一个填空字符串的空壳。九个彩色小人偶排在一列,是"生成出来的
 * 界面"最容易被认出来的标记之一;而且它们一个字的信息都没多给:「说话与听」旁边
 * 放一个喇叭,读的人早就知道那是说话与听了。
 *
 * 段与段的分隔改由排版承担(字号、间距、段头的字重)。
 *
 * 这一版分类是**按「人想干什么」分的**,不是按工程子系统 —— 「说话与听」而不是
 * 「TTS/ASR」,「思考与执行」而不是「agent runtime」。改这里之前先想清楚:
 * 一个人为了达成某件事会去哪一格找。
 *
 * 这九个标签就是设置面上那九段的段头,`ui/settings.ts::groupByCategory` 按这里的
 * 顺序排段。此前这里跟着上面一起写着「当前没有任何界面在渲染它」—— 同样是过期的话。
 *
 * 顺序有意义:越靠前越是「人天天要动的」。`advanced` 那一段默认收起,因为进去的人
 * 多半是来调某一个具体的键,不是来浏览的。
 */
export const CATEGORIES: readonly CategoryDef[] = [
  { key: 'voice', label: '说话与听' },
  { key: 'perception', label: '感知' },
  { key: 'agent', label: '思考与执行' },
  { key: 'memory', label: '记忆' },
  { key: 'devices', label: '设备与跨设备' },
  { key: 'security', label: '安全与权限' },
  { key: 'network', label: '网络与端口' },
  { key: 'llm', label: '供应商与密钥' },
  { key: 'advanced', label: '进阶与调优', advanced: true },
];
