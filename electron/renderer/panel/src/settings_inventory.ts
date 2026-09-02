/**
 * 设置面的键清单 —— **数据,不是界面。**
 *
 * ## 这个文件为什么存在
 *
 * 旧的 React 面板被这一版 HUD 整个替换掉了。旧面板里有两处手写的键清单:
 *
 * - `SettingsTab.tsx` 的 `KEY_ORDER_HINT` —— 每一类里的显示顺序(303 个键,9 类)
 * - `ModelsTab.tsx` 的 provider 键 —— 供应商那一档能配哪些键(25 个)
 *
 * 它们不是渲染代码,是**判据**:`tests/test_config_schema_ui_parity.py` 一直
 * 拿它们跟 `core/routes/config.py::CONFIG_SCHEMA` 对账 —— 界面上出现、后端却
 * 不认的键,POST /api/config 会 400,用户看到的是「保存失败」。
 *
 * 删掉旧面板时如果把它们一起删了,那道门就没东西可读,只能跟着删。**那是在
 * 悄悄减少覆盖**,不是在重构。所以搬到这里,门改指这里。
 *
 * ## 但是要说清楚:**现在没有任何界面在渲染这份清单**
 *
 * 新面板的设置浮层只有四个整档开关;那个「全部设置」按钮**还没有接任何东西**。
 * 这 303 个键当前在界面上一个都调不了。
 *
 * 这份清单是那个还没建的设置面的**规格**,不是它的实现。谁来建,照着这里的
 * 分类与顺序建;建好之前,别把这份清单当成「设置面已经在了」的证据。
 */

/** 每一类里的显示顺序。未列到的键按字母序跟在后面。 */
export const KEY_ORDER_HINT: Record<string, string[]> = {
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
    'GALAXY_SPECULATIVE_DRAFT',
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
    // 双模型档里感知位选哪个型号(与 OLLAMA_MODEL 是两个独立的位)。
    'GALAXY_PERCEPTION_MODEL',
    // 本地 OpenAI 兼容推理服务(双模型本地主脑里跑在核显那一位)。llama.cpp server 的
    // SYCL/Vulkan 后端 或 OpenVINO Model Server 都讲这套协议,填地址即接入。
    'GALAXY_EXECUTION_ISOLATION',
    // 权重准入。trust_remote_code=True 会执行模型仓库自带的 .py,而这条路不走
    // SafeExecutor —— 容器边界对它无效。默认全部收紧,按模型白名单放行。
    'GALAXY_TRUST_REMOTE_CODE', 'GALAXY_WEIGHTS_HOSTS', 'GALAXY_WEIGHTS_ALLOW_PICKLE',
    // 出口闸。容器隔离挡不住出站——数据外泄走的是这条路。默认 audit 只记账不拦。
    'GALAXY_EGRESS_MODE', 'GALAXY_EGRESS_ALLOW', 'GALAXY_EGRESS_ALLOW_PRIVATE',
    // provider 地址复验 + MCP 工具清单复验(挡 rug-pull)+ 工具调用守护。
    'GALAXY_ALLOW_ENDPOINT_OVERRIDE', 'GALAXY_MCP_PIN_MODE', 'GALAXY_TOOL_GUARDIAN',
    'GALAXY_LLAMA_SERVER_BIN',
    'GALAXY_LOCAL_OPENAI_URL', 'GALAXY_LOCAL_OPENAI_MODEL', 'GALAXY_LOCAL_OPENAI_SERVES',
    'GALAXY_LOCAL_OPENAI_KEY',
    // 推理位/独显那条泳道。本地可以同时有**两台** OpenAI 兼容服务(感知位在核显、
    // 推理位在独显),multi_llm_router._LOCAL_OPENAI_LANES 早就按 env_prefix 认这
    // 四个键了 —— 缺的只是面板上没有地方填。结果是:感知位那台能在界面里配,
    // 推理位那台只能改 .env,而双模型档本来就是要两台一起用。
    'GALAXY_REASONING_OPENAI_URL', 'GALAXY_REASONING_OPENAI_MODEL',
    'GALAXY_REASONING_OPENAI_SERVES', 'GALAXY_REASONING_OPENAI_KEY',
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
    'GALAXY_OLLAMA_NUM_CTX', 'GALAXY_LLAMA_CTX', 'GALAXY_IGNORE_CONTEXT_MEASUREMENTS',
    'GALAXY_CONTEXT_ARCHIVE_MAX_MB', 'GALAXY_CONTEXT_ARCHIVE_MIN_DAYS', 'GALAXY_PHASE_LEDGER_DAYS', 'GALAXY_OLLAMA_KEEP_ALIVE', 'GALAXY_URL_SENTINEL',
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

/**
 * 供应商那一档能配的键。
 *
 * 来自旧 `ModelsTab.tsx`。这一档在新面板里同样**还没有界面** ——
 * 它属于上面说的那个待建的设置面。
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
  // 模型 API key 归供应商目录那一档:那边带中文名、用途标注和配套 base URL,
  // 拍平成设置页的 key-value 行会把这些信息全毁掉。见 PROVIDER_KEYS。
  'llm',
]);

export interface CategoryDef {
  readonly key: string;
  readonly label: string;
  readonly icon: string;
  readonly advanced?: boolean;
}

/**
 * 分类的显示装饰(中文标签 + 图标)。
 *
 * 这一版分类是**按「人想干什么」分的**,不是按工程子系统 —— 「说话与听」而不是
 * 「TTS/ASR」,「思考与执行」而不是「agent runtime」。改这里之前先想清楚:
 * 一个人为了达成某件事会去哪一格找。
 *
 * 同上:**当前没有任何界面在渲染它**。
 */
export const CATEGORIES: readonly CategoryDef[] = [
  { key: 'voice', label: '说话与听', icon: '🔊' },
  { key: 'perception', label: '感知', icon: '👁️' },
  { key: 'agent', label: '思考与执行', icon: '🧠' },
  { key: 'memory', label: '记忆', icon: '🗂️' },
  { key: 'devices', label: '设备与跨设备', icon: '🕸️' },
  { key: 'security', label: '安全与权限', icon: '🔒' },
  { key: 'network', label: '网络与端口', icon: '🌐' },
  { key: 'advanced', label: '进阶与调优', icon: '🛠️', advanced: true },
];
