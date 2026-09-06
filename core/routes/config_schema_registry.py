"""core/routes/config_schema_registry.py — 面板配置项总表(SSOT)

这份表原先长在 ``core/routes/config.py`` 里。把整个 core/ 纳入面板守卫范围、补齐
99 个未登记键之后,它涨到 1900 多行,把同文件里那几百行**路由逻辑**整个压在了底下 ——
文件复杂度门也据此报红(2343 行 / 基线 1612)。

它是一张**纯声明表**:键 → 默认值 / 类型 / 分类 / 中文说明。与路由的读写逻辑没有
任何耦合,拆出来是纯收益:改一个开关的说明不再需要翻过路由代码,而路由文件回到
400 行出头、重新可读。

``CONFIG_SCHEMA`` 仍从 ``core.routes.config`` 原样导出(那里 re-export),所以既有的
``from core.routes.config import CONFIG_SCHEMA`` 一律不受影响 —— 拆的是文件,不是接口。
"""

from typing import Any, Dict

# 所有支持的配置项（键 → {默认值, 类型, 类别, 描述}）
CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    # --- LLM Providers (API Keys) ---
    "OPENAI_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "OpenAI 的 API Key（GPT 系列；也是若干功能的默认回落 key）",
    },
    "ANTHROPIC_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Anthropic 的 API Key（Claude 系列）",
    },
    "DEEPSEEK_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "DeepSeek 的 API Key（国内直连，性价比高）",
    },
    "GOOGLE_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Google 的 API Key（Gemini 系列）",
    },
    "GEMINI_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Gemini 的 API Key（GOOGLE_API_KEY 的别名，填任一即可）",
    },
    "XAI_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "xAI 的 API Key（Grok 系列）"},
    "META_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Meta 的 API Key（Meta Model API / Muse Spark 系列，不是开源 Llama）",
    },
    "MISTRAL_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Mistral 的 API Key"},
    "AGNES_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Agnes AI API Key(全模态免费)",
    },
    "QWEN_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "通义千问的 API Key"},
    "DASHSCOPE_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "阿里云百炼的 API Key（QWEN_API_KEY 的别名）",
    },
    "ZHIPU_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "智谱 GLM 的 API Key"},
    "ZHIPU_CODING_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "智谱 GLM 编码套餐(Coding Plan)专属 Key —— 与上面的 ZHIPU_API_KEY 是两码事:"
        "订阅制月费,限定编码 agent 场景,端点也不同(/api/coding/paas/v4)。"
        "配这把 key 不代表也配了普通 ZHIPU_API_KEY,反之亦然。",
    },
    "GROQ_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Groq 的 API Key（推理很快，适合要低延迟的场合）",
    },
    "HF_API_TOKEN": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "HuggingFace 的访问令牌（下载受限模型时需要）",
    },
    "MOONSHOT_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "月之暗面 Kimi 的 API Key"},
    "MIMO_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "小米 MiMo 的 API Key"},
    "MINIMAX_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "MiniMax 的 API Key"},
    "PERPLEXITY_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Perplexity 的 API Key（带联网搜索的问答）",
    },
    "STEP_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "阶跃星辰 StepFun 的 API Key"},
    "ONEAPI_URL": {
        "default": "",
        "type": "url",
        "category": "llm",
        "description": "OneAPI 聚合网关的地址（用一个入口转发到多家模型）",
    },
    "ONEAPI_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "OneAPI 聚合网关的 Key"},
    "OPENROUTER_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "OpenRouter 的 API Key（一个 key 用多家模型）",
    },
    "DEEPSEEK_OCR2_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "DeepSeek OCR 的 API Key（图片转文字）",
    },
    "ZHIPU_API_BASE": {
        "default": "",
        "type": "url",
        "category": "llm",
        "description": "智谱 GLM 的 Base URL 覆盖（留空=国内 open.bigmodel.cn；海外填 https://api.z.ai/api/paas/v4）",
    },
    "OPENAI_API_BASE": {
        "default": "",
        "type": "url",
        "category": "llm",
        "description": "OpenAI-compatible Base URL (代理/中转)",
    },
    "SONAR_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Perplexity Sonar 的 API Key（PERPLEXITY_API_KEY 的别名）",
    },
    "LOCAL_VLLM_URL": {
        "default": "",
        "type": "url",
        "category": "llm",
        "description": "本机 vLLM 推理服务地址（自己部署的高性能推理后端）",
    },
    # options 不再硬编码——由 get_config 在响应时从 core.model_catalog 动态派生
    # （与 model_selection、面板 ModelsTab 同一真相源，杜绝三份清单漂移）。
    "OLLAMA_MODEL": {
        "default": "",
        "type": "select",
        "category": "llm",
        "description": "本地主脑模型（原生多模态）",
        "options": [],
    },
    # --- Service Ports & Nodes ---
    "GATEWAY_PORT": {
        "default": "9000",
        "type": "number",
        "category": "network",
        "description": "网关端口（对外的统一入口 · 默认 9000）",
    },
    "UFO_NODE_HOST": {
        "default": "localhost",
        "type": "string",
        "category": "devices",
        "description": "节点主机名（默认 localhost；跨机部署才需要改）",
    },
    "NODE_92_URL": {
        "default": "http://localhost:8092",
        "type": "url",
        "category": "devices",
        "description": "设备控制服务的地址（Node 92：鼠标键盘/屏幕操作）",
    },
    "NODE_45_URL": {
        "default": "http://localhost:8045",
        "type": "url",
        "category": "devices",
        "description": "桌面端点的地址（Node 45）",
    },
    "NODE_33_URL": {
        "default": "http://localhost:8033",
        "type": "url",
        "category": "devices",
        "description": "安卓 ADB 控制的地址（Node 33：连手机做自动化）",
    },
    "NODE_71_URL": {
        "default": "http://localhost:8071",
        "type": "url",
        "category": "devices",
        "description": "多设备编排的地址（Node 71：跨设备协同调度）",
    },
    "NODE_71_HOST": {
        "default": "localhost",
        "type": "string",
        "category": "devices",
        "description": "多设备编排的主机名（Node 71）",
    },
    "NODE_95_URL": {
        "default": "http://localhost:8095",
        "type": "url",
        "category": "devices",
        "description": "视觉采样服务的地址（Node 95：抽帧/看画面）",
    },
    "NODE_97_URL": {
        "default": "http://localhost:8097",
        "type": "url",
        "category": "devices",
        "description": "学术检索服务的地址（Node 97：查论文）",
    },
    "NODE09_SANDBOX_URL": {
        "default": "",
        "type": "url",
        "category": "security",
        "description": "代码沙箱的地址（Node 09：隔离环境里跑代码）",
    },
    "OLLAMA_URL": {
        "default": "",
        "type": "url",
        "category": "agent",
        "description": "Ollama 本地模型服务的地址（留空=自动探测常见端口）",
    },
    "GALAXY_SKIP_DESKTOP_SURFACE": {
        "default": "false",
        "type": "boolean",
        "category": "advanced",
        "description": (
            "跳过桌面壳这一启动阶段（无头/服务端部署用；" "打开后不再探测或安装 Electron 依赖，面板也不会被拉起）"
        ),
    },
    "QDRANT_URL": {
        "default": "",
        "type": "url",
        "category": "advanced",
        "description": "Qdrant 向量库的地址（留空=不用它）",
    },
    "REDIS_URL": {
        "default": "",
        "type": "url",
        "category": "advanced",
        "description": "Redis 的地址（做缓存与队列；留空=不用）",
    },
    "SECRETVAULT_URL": {
        "default": "",
        "type": "url",
        "category": "security",
        "description": "密钥保险库的地址（GALAXY_SECRET_BACKEND=vault 时才用）",
    },
    "MAIN_REPO_URL": {
        "default": "http://localhost:8080",
        "type": "url",
        "category": "advanced",
        "description": "主仓库服务的地址（默认 localhost:8080）",
    },
    "MQTT_PORT": {
        "default": "",
        "type": "number",
        "category": "network",
        "description": "MQTT 消息代理的端口（接 IoT 设备时用）",
    },
    # --- Authentication & Security ---
    "GALAXY_AUTH_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "启用鉴权（默认关=本机自用免验证；对外开放前务必打开）",
    },
    "GALAXY_API_TOKEN": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "API 访问令牌（单个）",
    },
    "GALAXY_API_TOKENS": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "API 访问令牌（多个，逗号分隔；给不同设备发不同令牌时用）",
    },
    "GALAXY_API_TOKEN_EXPIRY": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "令牌有效期（留空=永不过期）",
    },
    "GALAXY_REVOKED_TOKENS": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "已吊销的令牌名单（逗号分隔，列进来的立即失效）",
    },
    "GALAXY_REQUIRE_API_TOKEN": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "强制要求令牌（默认关；开了则没带令牌的请求一律拒绝）",
    },
    "GALAXY_STRICT_AUTHORITY_CHECK": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "权威校验从严（默认关；开了则来源存疑的指令一律拒绝）",
    },
    "GALAXY_SECRET_BACKEND": {
        "default": "env",
        "type": "select",
        "category": "security",
        "description": "密钥存放方式（env=落本地加密文件 / vault=放独立保险库 · 默认 env）",
        "options": ["env", "vault", "kms"],
    },
    "GALAXY_TLS_CERT": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "TLS 证书路径（走 HTTPS 时填；留空=用明文 HTTP，仅限本机）",
    },
    "GITHUB_TOKEN": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "GitHub 访问令牌（读写仓库、发 PR 时用）",
    },
    # 融合(域6):删掉两个幽灵开关 GALAXY_AUDIT_KEY / GALAXY_MESSAGE_SIGNING_KEY——
    # 全仓无任何代码读它们(面板上摆着没实现的安全功能,误导操作者)。消息签名
    # 【真实已实现】,但键名是 GALAXY_MESH_SECRET(capability_token HMAC 签名/校验,
    # 缺省自动生成 .galaxy_mesh_key),把真的这只上面板。
    "GALAXY_MESH_SECRET": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "Mesh 签名密钥(能力令牌 HMAC;留空自动生成)",
    },
    # --- Mesh & NATS ---
    "GALAXY_MDNS": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "局域网零配置发现(mDNS · 手机/手表免输 IP 自动发现网关)",
    },
    # 这三条的说明原先只有一句英文,面板上照原样显示,中文用户看不懂开了会发生什么。
    # 是这一轮把守卫范围扩到 launcher/ 之后,启动器读到它们才连带扫出来的。
    "GALAXY_NATS_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "启用 NATS 消息总线（多设备协同的传输底座;单机自用可以关 · 默认开）",
    },
    "GALAXY_NATS_URL": {
        "default": "nats://localhost:4222",
        "type": "url",
        "category": "devices",
        "description": "NATS 消息总线的地址（默认本机;接到别的机器上才需要改）",
    },
    "GALAXY_NATS_EXECUTOR_TIMEOUT": {
        "default": "30",
        "type": "number",
        "category": "devices",
        "description": "NATS 执行器超时(秒 · 默认 30)",
    },
    "GALAXY_NATS_EXECUTOR_FALLBACK": {
        "default": "sync",
        "type": "select",
        "category": "devices",
        "description": "NATS 不可用时怎么办（sync=退回本机同步执行 · 默认 sync）",
        "options": ["sync", "async", "reject"],
    },
    "GALAXY_CROSS_DEVICE_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "跨设备编排（让手机/手表/别的电脑也能承接任务;关掉则只在本机跑 · 默认开）",
    },
    "GALAXY_MASTER_BRAIN_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "启用主脑编排 + worker/NATS 分布式(多设备总开关 · 默认关=单机)",
    },
    "GALAXY_FABRIC_STRICT": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "严格织网:NATS 不可达即视为致命(默认关=优雅降级单机)",
    },
    "GALAXY_HEARTBEAT_INTERVAL": {
        "default": "5",
        "type": "number",
        "category": "devices",
        "description": "设备心跳间隔(秒 · 默认 5；调大省电，掉线发现得慢)",
    },
    "FEDERATION_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "启用联邦（把多套 Galaxy 连成一片 · 默认关）",
    },
    "FEDERATION_LOCAL_HOST": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "联邦里本机对外的主机名",
    },
    "FEDERATION_PEERS": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "联邦对端地址（逗号分隔）",
    },
    "FEDERATION_HEARTBEAT_INTERVAL": {
        "default": "10",
        "type": "number",
        "category": "devices",
        "description": "联邦心跳间隔(秒 · 默认 10)",
    },
    "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE": {
        "default": "strict",
        "type": "select",
        "category": "security",
        "description": "派发权威模式（strict=只认规范来源，不接受旁路 · 默认 strict）",
        "options": ["strict", "advisory", "disabled"],
    },
    # --- Circuit Breaker & Adaptive ---
    "GALAXY_ROUTER_ADAPTIVE_CONCURRENCY": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "自适应并发（按实测延迟自动调同时处理多少请求 · 默认开）",
    },
    "GALAXY_ROUTER_CB_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "熔断器（后端连续出错就暂时停用它，别一直撞墙 · 默认开）",
    },
    "GALAXY_ROUTER_MAX_QUEUE_DEPTH": {
        "default": "1000",
        "type": "number",
        "category": "agent",
        "description": "请求排队上限（超了直接拒绝，防止堆积雪崩 · 默认 1000）",
    },
    "GALAXY_CB_FAILURE_THRESHOLD": {
        "default": "5",
        "type": "number",
        "category": "advanced",
        "description": "连续失败几次触发熔断（默认 5）",
    },
    "GALAXY_CB_RECOVERY_TIMEOUT_S": {
        "default": "30",
        "type": "number",
        "category": "advanced",
        "description": "熔断后隔多久试探恢复(秒 · 默认 30)",
    },
    "GALAXY_CB_HALF_OPEN_PROBES": {
        "default": "3",
        "type": "number",
        "category": "advanced",
        "description": "试探恢复时先放几个请求进去（默认 3）",
    },
    "GALAXY_CB_WINDOW_SIZE": {
        "default": "60",
        "type": "number",
        "category": "advanced",
        "description": "熔断统计窗口(秒 · 默认 60)",
    },
    "GALAXY_AS_TARGET_LATENCY_MS": {
        "default": "2000",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的目标延迟(毫秒 · 默认 2000；超了就减并发)",
    },
    "GALAXY_AS_ERROR_THRESHOLD": {
        "default": "0.1",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的错误率阈值（0~1 · 默认 0.1）",
    },
    "GALAXY_AS_INIT_LIMIT": {
        "default": "10",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的起始并发数（默认 10）",
    },
    "GALAXY_AS_MAX_LIMIT": {
        "default": "200",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的上限（默认 200）",
    },
    "GALAXY_AS_MIN_LIMIT": {
        "default": "1",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的下限（默认 1，保证不会降到零）",
    },
    "GALAXY_AS_SAMPLE_WINDOW": {
        "default": "60",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的采样窗口(秒 · 默认 60)",
    },
    "GALAXY_AS_PROBE_INTERVAL_S": {
        "default": "5",
        "type": "number",
        "category": "advanced",
        "description": "自适应并发的探测间隔(秒 · 默认 5)",
    },
    # --- Storage ---
    "GALAXY_DATA_DIR": {
        "default": "./data",
        "type": "string",
        "category": "advanced",
        "description": "数据总目录（记忆库/账本等都放这儿 · 默认 ./data）",
    },
    "GALAXY_MARKET_STORE_DIR": {
        "default": "./market",
        "type": "string",
        "category": "advanced",
        "description": "技能市场的本地目录（默认 ./market）",
    },
    "GALAXY_FEATURE_FLAGS_PATH": {
        "default": "",
        "type": "string",
        "category": "advanced",
        "description": "功能开关文件路径（留空=用内置默认位置）",
    },
    "GALAXY_MASTER_BRAIN_STATE_PATH": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "主脑状态文件路径（留空=用内置默认位置）",
    },
    "CHROMA_PERSIST_DIR": {
        "default": "./chroma",
        "type": "string",
        "category": "memory",
        "description": "Chroma 向量库目录（默认 ./chroma；换目录等于换一套记忆）",
    },
    "ANDROID_DEVICE_STATE_STORE_PATH": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "安卓设备状态库路径（留空=用内置默认位置）",
    },
    "ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS": {
        "default": "300",
        "type": "number",
        "category": "devices",
        "description": "安卓设备快照的保鲜时长(秒 · 默认 300)",
    },
    # --- Development ---
    "GALAXY_DEV_MODE": {
        "default": "false",
        "type": "boolean",
        "category": "advanced",
        "description": "开发者模式（多打日志、放宽部分校验 · 默认关）",
    },
    "GALAXY_MODE": {
        "default": "standard",
        "type": "select",
        "category": "advanced",
        "description": "运行模式（standard=常规 · 默认 standard）",
        "options": ["standard", "distributed", "federated", "standalone"],
    },
    "GALAXY_SYSTEM_MODE": {
        "default": "desktop-local",
        "type": "select",
        "category": "devices",
        "description": "运行模式（desktop-local=单机 · desktop-cross-device=跨设备织网）",
        "options": ["desktop-local", "desktop-cross-device"],
    },
    "GALAXY_PREFLIGHT_MODE": {
        "default": "normal",
        "type": "select",
        "category": "advanced",
        "description": "启动前检查的模式（normal=常规 · 默认 normal）",
        "options": ["normal", "strict", "skip"],
    },
    "GALAXY_PREFLIGHT_FAIL_FAST": {
        "default": "false",
        "type": "boolean",
        "category": "advanced",
        "description": "启动前检查一失败就停（默认关=能降级就继续起）",
    },
    "GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "允许回落旧调度器（迁移期兜底 · 默认关）",
    },
    "GALAXY_ENTRYMODE_USE_READINESS": {
        "default": "true",
        "type": "boolean",
        "category": "advanced",
        "description": "入口按「就绪度」判定（而不是只看进程在不在 · 默认开）",
    },
    "CMD_MAX_CONCURRENT": {
        "default": "50",
        "type": "number",
        "category": "advanced",
        "description": "单类命令的最大并发数（默认 50）",
    },
    "CONCURRENCY_GLOBAL_MAX": {
        "default": "100",
        "type": "number",
        "category": "advanced",
        "description": "全局最大并发数（默认 100）",
    },
    "GALAXY_MAX_CONTEXT_TOKENS": {
        "default": "100000",
        "type": "number",
        "category": "security",
        "description": "上下文 token 上限（超了会裁剪历史 · 默认 100000）",
    },
    "GALAXY_MAX_MESSAGE_SIZE": {
        "default": "10485760",
        "type": "number",
        "category": "advanced",
        "description": "单条消息大小上限(字节 · 默认 10MB)",
    },
    # --- 行为 / 在场 (面板"行为"区直接开关，无需改环境变量) ---
    # 这些是面向用户的行为开关，面板上以明确的开关呈现:说/流式/自发在场/原生音频。
    "GALAXY_AUTONOMY": {
        "default": "guided",
        "type": "select",
        "category": "agent",
        "description": "自治档位（safe=敏感操作全问 · guided=读放行写审批 · autonomous=不逐步问人）",
        "options": ["safe", "guided", "autonomous"],
    },
    "GALAXY_SPEAK": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "朗读回复（说 · 默认开）",
    },
    "GALAXY_TTS_ENGINE": {
        "default": "edge",
        "type": "select",
        "category": "voice",
        "description": "说·语音引擎（edge=联网音质好 · melo=离线中英混读自然 · piper=离线最轻 · auto=优先edge退melo退piper）",
        "options": ["edge", "melo", "piper", "auto"],
    },
    "GALAXY_ASR_ENGINE": {
        "default": "auto",
        "type": "select",
        "category": "voice",
        "description": "听·识别引擎（auto=中文CPU首选SenseVoice退Whisper · sensevoice=离线中文快而准 · whisper=兜底）",
        "options": ["auto", "sensevoice", "whisper"],
    },
    "GALAXY_VOICE_EAGERNESS": {
        "default": "auto",
        "type": "select",
        "category": "voice",
        "description": "接话急切度（low=耐心等你想 · auto · high=抢答）——按说话内容判断回合是否结束",
        "options": ["low", "auto", "high"],
    },
    "GALAXY_VOICE_DELEGATE": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "语音委托模式（重活先口头致谢、后台跑,对话不被堵死 · 默认开）",
    },
    "GALAXY_VOICE_BACKCHANNEL": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "后台干活时的短应答（嗯,还在处理 · 默认开）",
    },
    "GALAXY_TTS_STREAMING": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "分句流式朗读（边生成边说 · 默认开）",
    },
    "GALAXY_AMBIENT_LOOP": {
        "default": "true",
        "type": "boolean",
        "category": "perception",
        "description": "自发在场（持续看/听、自己判断何时开口 · 默认开 · 需桌面感知授权）",
    },
    "GALAXY_NATIVE_AUDIO": {
        "default": "false",
        "type": "boolean",
        "category": "voice",
        "description": "原生音频输入（模型直接听音频，需全模态服务；关则走 ASR 转文字）",
    },
    "GALAXY_AMBIENT_INTERVAL_S": {
        "default": "2.0",
        "type": "number",
        "category": "perception",
        "description": "自发在场节拍(秒)",
    },
    "GALAXY_AMBIENT_COOLDOWN_S": {
        "default": "20.0",
        "type": "number",
        "category": "perception",
        "description": "开口/委托后冷却(秒,防话痨)",
    },
    # --- 边说边听(自回声抑制 / 打断策略 / 系统播放声 / 双工)---
    #
    # 这一组开关此前【只存在于代码里】:功能真做了也真在跑,但既不在本 schema 里、
    # 也不在面板前端的 CONFIG_KEYS 注册表里 —— 面板设置页不显示它们,而 set_config
    # 还会把它们当 unknown_keys 拒掉(见下方 set_config)。用户想开只能手改 .env 或
    # 导出环境变量,等于"写了没接"。两边同时登记才算真正接进面板。
    #
    # 每一项的 default 都与代码里的实际默认值逐个核对过(改默认值时两处必须一起改,
    # 否则面板显示的"默认"是假的):
    #   GALAXY_AEC                        → acoustic_echo_canceller.py::aec_enabled
    #   GALAXY_VOICE_ECHO_GUARD           → voice_echo_guard.py::echo_guard_enabled
    #   GALAXY_VOICE_BACKCHANNEL_TOLERANCE→ voice_dialog_policy.py::backchannel_tolerance_enabled
    #   GALAXY_SYSTEM_AUDIO_CAPTURE       → system_audio_capture_service.py::capture_enabled
    #   GALAXY_VOICE_DUPLEX / _DUCKING    → voice_duplex_session.py::duplex_enabled / ducking_enabled
    "GALAXY_AEC": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "回声消除（把喇叭放出去的声音从麦克风里减掉,防止 AI 听见自己说话 · 默认开）",
    },
    "GALAXY_VOICE_ECHO_GUARD": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "自回声文字闸门（识别结果与刚念过的话高度重合时判为自己的回声、不当用户输入 · 默认开）",
    },
    "GALAXY_VOICE_BACKCHANNEL_TOLERANCE": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "应答不打断（用户只是嗯/对/好时继续说,只有真插话才停 · 关则一出词就打断 · 默认开）",
    },
    "GALAXY_SYSTEM_AUDIO_CAPTURE": {
        "default": "true",
        "type": "boolean",
        "category": "perception",
        "description": "采集本机播放声（回声消除的参考信号来源,也让 AI 能听见电脑在放什么 · 默认开）",
    },
    "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION": {
        "default": "true",
        "type": "boolean",
        "category": "perception",
        "description": "把本机播放声送进感知（关掉则只用于回声消除、不进模型 · 默认开）",
    },
    # 三态:不设=按当前档位的**真实供给**自动判定(本机原生与云端一视同仁);
    # 1=强制开;0=强制关。写成 boolean/false 是**假的** —— 面板会显示"关"而实际
    # 已自动开启,那正是这条守卫要防的事。
    # 三态:不设=按目录声明 + 真机实测自动判定;0=强制关。**没有"强制开"这一档** ——
    # 开不开取决于这台机器实测出来是快是慢(公开数据里同一件事既有 +2.69x 也有
    # 净 -44.6%),给一个"强制开"等于允许用户把自己调慢一半还不知道为什么。
    # 要开就去跑 scripts/probe_models.py --draft,让实测说话。
    "GALAXY_SPECULATIVE_DRAFT": {
        "default": "auto",
        "type": "string",
        "category": "agent",
        "description": "投机解码草稿位（auto=实测更快才开 / 0=强制关 · 默认 auto；开不开由 scripts/probe_models.py --draft 的真机 A/B 决定）",
    },
    "GALAXY_VOICE_DUPLEX": {
        "default": "auto",
        "type": "string",
        "category": "voice",
        "description": "全双工语音（auto=档位具备就自动开,云端 realtime 按分钟计费 / 1=强制开 / 0=强制关 · 默认 auto）",
    },
    # 残余回声抑制(RES/NLP):线性对消之后的第二级,专治扬声器削波/外壳振动带来的
    # **非线性**回声 —— 那部分线性滤波器原理上消不掉。实测非线性路径上多消约 10 dB。
    "GALAXY_AEC_RES": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "残余回声抑制（线性对消之后再压一层非线性残余 · 默认开）",
    },
    "GALAXY_AEC_RES_OVER": {
        "default": "1.5",
        "type": "number",
        "category": "voice",
        "description": "残余抑制过减因子（越大压得越狠,代价是近端语音也多削一点 · 默认 1.5）",
    },
    "GALAXY_AEC_RES_FLOOR_DB": {
        "default": "-18",
        "type": "number",
        "category": "voice",
        "description": "远端单讲时的抑制下限 dB（压到底会是一段死寂,反而难受 · 默认 -18）",
    },
    "GALAXY_AEC_RES_DT_FLOOR_DB": {
        "default": "-3",
        "type": "number",
        "category": "voice",
        "description": "双讲时的抑制下限 dB（用户正在说话,必须比单讲宽松 · 默认 -3）",
    },
    "GALAXY_AEC_DTD_HANGOVER": {
        "default": "12",
        "type": "number",
        "category": "voice",
        "description": "双讲检出后继续按双讲处理多少块（真实双讲连续,能量判据只抓得住峰 · 默认 12）",
    },
    "GALAXY_AEC_COMFORT_NOISE": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "舒适噪声（把被压掉的部分填回极低底噪,消除呼吸感 · 默认开）",
    },
    "GALAXY_TEXT_VOICE_LOCKSTEP": {
        "default": "auto",
        "type": "string",
        "category": "voice",
        "description": "文字与语音同刻（auto=有语音时自动同刻 / 1=强制开 / 0=强制关 · 默认 auto）",
    },
    "GALAXY_VOICE_DUCKING": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "用户开口先压低音量而不是立刻掐断（等听清是应答还是真打断再决定 · 默认开）",
    },
    # 以下为细调参数:默认值已经是实测调过的,一般不需要动。
    "GALAXY_VOICE_DUCK_GAIN": {
        "default": "0.25",
        "type": "number",
        "category": "voice",
        "description": "压低音量时的音量倍数(0~1,0.25≈−12dB:明显压下去但仍听得见)",
    },
    "GALAXY_VOICE_HOLD_S": {
        "default": "90.0",
        "type": "number",
        "category": "voice",
        "description": "用户说“等一下/让我想想”后的静候时长(秒)",
    },
    "GALAXY_VOICE_ECHO_SIM": {
        "default": "0.62",
        "type": "number",
        "category": "voice",
        "description": "自回声判定的重合度阈值(0~1,调高=更少误判成回声、更容易漏掉回声)",
    },
    "GALAXY_VOICE_ECHO_TAIL_S": {
        "default": "6.0",
        "type": "number",
        "category": "voice",
        "description": "念完后仍防自回声的拖尾时长(秒)",
    },
    "GALAXY_VOICE_ECHO_MIN_CHARS": {
        "default": "4",
        "type": "number",
        "category": "voice",
        "description": "短于这个字数的识别结果不做自回声判定(太短判不准)",
    },
    "GALAXY_VOICE_ECHO_MIN_BLOCK": {
        "default": "4",
        "type": "number",
        "category": "voice",
        "description": "自回声判定要求的最短连续重合字数(防止零散字符碰巧凑出高重合度)",
    },
    "GALAXY_AEC_TAIL_MS": {
        "default": "128.0",
        "type": "number",
        "category": "voice",
        "description": "回声消除的滤波器长度(毫秒,覆盖房间混响拖尾;房间空旷可调大)",
    },
    "GALAXY_AEC_MU": {
        "default": "0.35",
        "type": "number",
        "category": "voice",
        "description": "回声消除的收敛步长(大=收敛快但易失稳,小=稳但慢)",
    },
    "GALAXY_AEC_MAX_DELAY_MS": {
        "default": "400.0",
        "type": "number",
        "category": "voice",
        "description": "喇叭到麦克风的最大补偿延迟(毫秒)",
    },
    "GALAXY_AEC_DTD_MARGIN_DB": {
        "default": "6.0",
        "type": "number",
        "category": "voice",
        "description": "双讲检测余量(dB,调高=更不容易把用户说话误判成回声)",
    },
    "GALAXY_REALTIME_PROVIDER": {
        "default": "openai_realtime",
        "type": "select",
        "category": "agent",
        "description": "全双工语音的 provider（仅在全双工开启时生效）",
        "options": ["openai_realtime", "gemini_live"],
    },
    "GALAXY_REALTIME_MODEL": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "全双工语音的模型名(留空=按 provider 取默认)",
    },
    "GALAXY_REALTIME_VOICE": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "全双工语音的音色(留空=按 provider 取默认)",
    },
    "GALAXY_REALTIME_URL": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "全双工语音的 WebSocket 地址(留空=按 provider 自动组装;走聚合器时才需手填)",
    },
    # ── B 档本地全模态 server(core/native_modal.py)────────────────────────────
    # 这三项此前**两边都没登记**:功能在跑,但用户只能手改 .env —— 与之前那 21 个语音
    # 开关是同一类缺口。漏掉的原因是面板守卫测试的模块清单里没有 native_modal.py /
    # modality_bridge.py(已一并补进去)。
    "GALAXY_MINICPM_SERVER_URL": {
        "default": "http://localhost:32550",
        "type": "string",
        "category": "agent",
        "description": (
            "B 档 MiniCPM-o 官方 server 的地址。原生听/说与双工的本地 realtime 地址都由它推导;"
            "可以不带 scheme(localhost:32550 也认)"
        ),
    },
    "GALAXY_NATIVE_MODAL_AUTO": {
        "default": "true",
        "type": "boolean",
        "category": "perception",
        "description": ("切到 B 档时自动激活原生后端(后台补装客户端依赖 + 探测 server)。" "关掉则只能手动激活"),
    },
    "GALAXY_PERCEPTION_MODEL": {
        "default": "",
        "type": "string",
        "category": "perception",
        "description": (
            "双模型档里**感知位**(看/听/说那一位)选哪个型号。留空=用该档候选表第一个。"
            "与 OLLAMA_MODEL(文本主脑/推理位)是两个独立的位,换一个不影响另一个"
        ),
    },
    # ── 本地 OpenAI 兼容推理服务(core/multi_llm_router._register_local_openai)──
    # 双模型本地主脑的另一半:感知位跑在核显上时,用 llama.cpp server 的 SYCL/Vulkan
    # 后端或 OpenVINO Model Server 起一个 OpenAI 兼容端点,填地址即可接入 ——
    # 路由层的 OpenAIAdapter 讲的就是这套协议,不需要新后端。
    # 模型自己写出来的代码跑在多硬的边界里。判据见 core/execution_isolation.py。
    #
    # 刻意**没有** "强制容器" 之外的第四档:auto 已经是"有容器就用容器",
    # 而 container 的含义是"宁可不跑,也不在裸机上跑"。
    "GALAXY_EXECUTION_ISOLATION": {
        "default": "auto",
        "type": "string",
        "category": "security",
        "description": (
            "智能体自写代码的执行边界(auto=有 Docker/Podman 就跑进容器,否则退回内置轻量沙箱 / "
            "container=没有容器边界就拒绝执行 / builtin=强制内置)。"
            "内置档是同一内核、同一用户,只挡得住手滑,挡不住一次不走运的代码生成"
        ),
    },
    # 这一位与下面三个 GALAXY_LOCAL_OPENAI_* 是一组:它说"二进制在哪",那三个说
    # "起来之后怎么接进来"。由我们自己起服务时,后三个会被 core.llama_server 自动
    # 导出,人只需要填这一个。
    # ── provider 地址与 MCP 工具清单的复验 ────────────────────────────────
    # 改掉一个 base_url,api_key 与每一次对话的全文都会照常发往新地址,而一切看起来
    # 都正常工作。默认仍放行(中转是主流用法),但会留痕并出现在诊断面上;真正的
    # 拦截由 egress_guard 承担。判据见 core/endpoint_admission.py。
    "GALAXY_ALLOW_ENDPOINT_OVERRIDE": {
        "default": "true",
        "type": "boolean",
        "category": "security",
        "description": (
            "允不允许用环境变量/面板短键覆盖 provider 的 base_url。默认允许(中转/relay 要用)。"
            "关掉后覆盖失效并回落到注册表里的登记地址,且会留痕——不静默忽略"
        ),
    },
    # MCP 工具描述与入参 schema 是**直接进模型上下文**的文本,而服务器随时能改。
    # 先干净上线、被信任之后再推更新把描述换掉,就是 rug-pull。
    # 默认 enforce 配 TOFU 是能用的:第一次照记不拦,只有"变了"才拦。
    "GALAXY_MCP_PIN_MODE": {
        "default": "enforce",
        "type": "string",
        "category": "agent",
        "description": (
            "MCP 工具清单复验档位(enforce=变了就拒用,默认 / warn=只记不拦 / off=不生效)。"
            "第一次见到的服务器按 TOFU 记下——挡得住后来被改,挡不住一开始就是坏的"
        ),
    },
    "GALAXY_TOOL_GUARDIAN": {
        "default": "on",
        "type": "string",
        "category": "security",
        "description": (
            "工具调用守护(风险评分 + 超阈值拦截 + 审计)。默认开。"
            "此前这道闸写好了却从未在生产路径上生效过——没有任何调用方传过它的配置"
        ),
    },
    # ── 出口闸(core/egress_guard.py)───────────────────────────────────────
    # 在这三个开关之前,整个系统说不出"这次执行往外发了什么、发去了哪儿"。
    # 提示注入最严重的后果通常不是删文件,而是把数据编进一个 URL 顺手发出去 ——
    # 容器隔离挡不住出站,这是那道边界的另一半。
    #
    # 默认 audit 是**刻意的让步**:合法出站远不止 provider 调用(MCP、抓网页、
    # 装依赖都在出站),带着一份没整理过的白名单直接 enforce 会把能用的全打死。
    # 但 audit 档**不提供保护**,只提供可见性 —— 报告里如实这么写。
    "GALAXY_EGRESS_MODE": {
        "default": "audit",
        "type": "string",
        "category": "security",
        "description": (
            "出站管控档位(audit=只记账不拦,默认 / enforce=白名单外一律拒 / off=完全不生效)。"
            "audit 档不提供保护,只提供可见性——别把它当成已防护"
        ),
    },
    "GALAXY_EGRESS_ALLOW": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": (
            "出站白名单追加项(逗号分隔的主机名,支持 *.example.com)。"
            "各家 provider 的地址与权重下载主机会自动从既有注册表推导,不用在这里重列"
        ),
    },
    "GALAXY_EGRESS_ALLOW_PRIVATE": {
        "default": "true",
        "type": "boolean",
        "category": "security",
        "description": (
            "允不允许连内网地址。默认允许——跨设备编队/mesh 走的就是内网,关掉会把多设备打死。"
            "内网出站一样进账本:发给同一局域网的另一台机器同样是一条外泄路径"
        ),
    },
    # ── 权重准入(core/weights_admission.py)────────────────────────────────
    # trust_remote_code=True 的含义是**模型仓库自带的 .py 会被直接执行**,而下载源
    # 默认是第三方镜像且没有哈希校验。这条路不走 SafeExecutor,容器边界对它无效。
    #
    # 默认全部收紧:一个模型都不许执行自带代码。**刻意不做成一个总开关** ——
    # 一刀切会让依赖它的模型全部加载不了,那样的闸最终会被整个关掉。
    "GALAXY_TRUST_REMOTE_CODE": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": (
            "允许执行仓库自带 .py 的模型白名单(逗号分隔的 repo id)。留空=一个都不许。"
            "填 '*' 会放开全部——那等于把这道闸关掉,报告里会如实标出来。"
            "登记后建议再钉指纹,否则上游改了会执行的代码不会被发现"
        ),
    },
    "GALAXY_WEIGHTS_HOSTS": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": (
            "允许下载权重的主机白名单(逗号分隔)。留空=用默认表"
            "(huggingface.co / hf-mirror.com / modelscope.cn)。留空**不等于**允许所有"
        ),
    },
    "GALAXY_WEIGHTS_ALLOW_PICKLE": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": (
            "允不允许加载 pickle 格式权重(.bin/.pt/.pth/.ckpt)。默认否——"
            "pickle 反序列化即执行代码,是历次模型投毒事件的载体;"
            "safetensors/gguf 不受影响,它们反序列化不执行代码"
        ),
    },
    "GALAXY_LLAMA_SERVER_BIN": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": (
            "llama-server 可执行文件路径。留空=在 PATH 上找(llama-server / llama_server / server)。"
            "C 档的专家卸载(--n-cpu-moe)与 D 档的草稿位(--spec-type)只在这个二进制上有,"
            "llama-cpp-python 的进程内绑定不透出它们"
        ),
    },
    "GALAXY_LOCAL_OPENAI_URL": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": (
            "本地 OpenAI 兼容推理服务地址(llama.cpp server 的 SYCL/Vulkan 后端 或 OpenVINO Model Server)。"
            "留空=不启用;可不带 scheme 与 /v1(127.0.0.1:8000 也认)"
        ),
    },
    "GALAXY_LOCAL_OPENAI_MODEL": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": ("指定用该服务托管的哪个模型。留空=用它 /v1/models 自报的第一个;填错会告警并回落自报值"),
    },
    "GALAXY_LOCAL_OPENAI_SERVES": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": (
            "声明这台服务伺候的是目录里哪个型号(如 openbmb/minicpm-o4.5)。"
            "服务按自己那套命名报模型 id(OpenVINO 的 MiniCPM-o-4_5-int4-ov 之类)、"
            "与目录 tag 对不上时填它;留空=按名字匹配"
        ),
    },
    "GALAXY_LOCAL_OPENAI_KEY": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "该本地服务若开了鉴权就填它的 key;自托管通常留空",
    },
    # ── 推理位那条泳道(core/multi_llm_router._LOCAL_OPENAI_LANES 第二条)────────
    # 与上面四个 GALAXY_LOCAL_OPENAI_* 一一对应,只是伺候的是另一只手:那四个是
    # **感知位/核显侧**,这四个是**推理位/独显侧**。C/D 档本来就是双模型、两块
    # 加速器、两台服务 —— 只留一组的后果是二选一:接了核显那台,独显那台就没有
    # 地方填地址。
    #
    # 独显侧的候选引擎:FreeToken 的 `ft serve`(MoE 专用,自带专家 LRU 缓存与
    # CPU-GPU 带宽自适应)、vLLM、llama.cpp server 的 CUDA 后端 —— 都讲同一套
    # OpenAI 兼容协议,填地址即可,不需要新后端。
    "GALAXY_REASONING_OPENAI_URL": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": (
            "推理位那台 OpenAI 兼容服务的地址(FreeToken ft serve 默认 127.0.0.1:1919 / vLLM / "
            "llama.cpp server CUDA)。留空=不启用;可不带 scheme 与 /v1"
        ),
    },
    "GALAXY_REASONING_OPENAI_MODEL": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": ("指定用该服务托管的哪个模型。留空=用它 /v1/models 自报的第一个;填错会告警并回落自报值"),
    },
    "GALAXY_REASONING_OPENAI_SERVES": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": (
            "声明这台服务伺候的是目录里哪个推理位型号(qwen3.6:35b-a3b 或 agents-a1:35b-a3b)。"
            "服务按自己那套命名报模型 id(FreeToken 默认取 --model 路径的 basename)、与目录 tag "
            "对不上时填它;留空=按名字匹配。**与感知位那条各有各的** —— 共用一个就等于说两台装的是同一个型号"
        ),
    },
    "GALAXY_REASONING_OPENAI_KEY": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "该服务若开了鉴权就填它的 key;自托管通常留空",
    },
    "GALAXY_AMBIENT_ASR_SIZE": {
        "default": "base",
        "type": "string",
        "category": "voice",
        "description": "环境聆听转写用的 Whisper 模型规格(tiny/base/small/medium/large)",
    },
    "GALAXY_VIDEO_FPS_NATIVE": {
        "default": "4.0",
        "type": "string",
        "category": "perception",
        "description": "原生视频通路的抽帧帧率(模型原生吃连续视频时用,默认 4 fps)",
    },
    "GALAXY_VIDEO_FPS_BRIDGE": {
        "default": "1.0",
        "type": "string",
        "category": "perception",
        "description": "抽帧桥接通路的帧率(模型不吃连续视频、只能喂稀疏图片时用,默认 1 fps)",
    },
    "GALAXY_NATIVE_REALTIME_PATH": {
        "default": "/v1/realtime",
        "type": "string",
        "category": "perception",
        "description": (
            "本地全模态 server 上 realtime 端点的路径。B 档原生就绪且没配云端 key 时,"
            "双工会自动指向本地 server 的这个路径试一次流式;试不通会安静退回原生回合制"
            "(听/说仍是原生)。你的 server 路径不是默认的 /v1/realtime 时改这里"
        ),
    },
    # 这一项是**密钥**。登记它是安全的:core/config_schema.py::classify_key() 按后缀
    # 启发式判定,凡以 _API_KEY / _TOKEN / _SECRET / _PASSWORD 结尾的一律归为 "secret",
    # 而 update_config() 对 secret 走 ConfigService.set_secret() → runtime/secrets.env,
    # 不会明文落 .env(已实测 classify_key("GALAXY_REALTIME_API_KEY") == "secret")。
    #
    # 我先前一度以为"必须同时加进 _SECRET_MODEL_KEYS 才不会明文落盘",据此在测试里留了
    # 一条绊线。那个前提是错的:_SECRET_MODEL_KEYS 只决定面板「模型」tab 的"已配置"
    # 角标读哪些键,与写入分流无关。绊线已改为直接断言 classify_key 的分流结果。
    "GALAXY_REALTIME_API_KEY": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "全双工语音专用 API Key(留空=退回该 provider 的通用 key,如 OPENAI_API_KEY)",
    },
    # ── 语音/感知栈的其余配置键(2026-08-04 一次性登记齐)──────────────────────────
    #
    # 前两轮补登记都是**发现一处补一处**:先补了 21 个语音开关,再补了 5 个 B 档模态键。
    # 每一次都以为补完了,每一次都还有。根因是那道守卫的模块清单是**手工维护**的
    # (tests/test_voice_switches_reach_the_panel.py::_VOICE_MODULES),清单没写进去的
    # 模块就静默不受保护 —— 补键治的是症状,清单本身才是病。
    #
    # 这一轮同时做了两件事:
    #   1. 把那份清单改成**按目录模式派生**(core/voice_*.py、core/multimodal/*.py、
    #      core/asr/*.py、core/tts/*.py、core/perception/*.py …),新增模块自动纳管,
    #      这一类漏法不会再来第四次;
    #   2. 派生后一次扫出 36 个未登记键,除 GALAXY_ENV(部署标记,已显式豁免)外
    #      全部登记在此。
    #
    # 每一条的 default 都读过源码逐个核对。注意有几把键的读取点原先用的是
    # ``os.environ.get(key, 默认值)`` —— 那个默认值**对空串不生效**,而登记进面板后
    # 用户清空输入框存回来的正是空串。相关读取点已一并改成 ``.strip() or 默认``
    # (kokoro/melo/indextts/sensevoice),否则"能在面板上改"会直接变成"一改就坏"。
    #
    # --- 桌面操作闭环(core/computer_use_loop.py)---
    "GALAXY_COMPUTER_USE": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "桌面操作闭环（让 AI 看屏幕、自己点鼠标敲键盘完成任务 · 默认开）",
    },
    "GALAXY_CU_MAX_STEPS": {
        "default": "15",
        "type": "number",
        "category": "agent",
        "description": "桌面操作单次任务的步数上限（1~50,防止无限点下去 · 默认 15）",
    },
    "GALAXY_CU_SETTLE_S": {
        "default": "1.0",
        "type": "number",
        "category": "agent",
        "description": "每步操作后等界面反应的静置时长(秒,0~10 · 默认 1)",
    },
    # --- 连续感知(core/perception/、core/multimodal/)---
    "GALAXY_DESKTOP_PERCEPTION_TTL": {
        "default": "10",
        "type": "number",
        "category": "perception",
        "description": "桌面感知帧的保鲜时长(秒,超过就算过期不再当作当前画面 · 默认 10)",
    },
    "GALAXY_PERCEPTION_KEYFRAMES": {
        "default": "4",
        "type": "number",
        "category": "perception",
        "description": "屏幕保留最近几帧（让 AI 能看出「刚才发生了什么」而不只是此刻 · 0=只留当前一帧 · 默认 4）",
    },
    "GALAXY_PERCEPTION_PRIVACY_DEFAULT": {
        "default": "active",
        "type": "select",
        "category": "perception",
        "description": "启动时的感知状态（active=正常采集 / paused=启动即隐私暂停,什么都不采 · 默认 active）",
        "options": ["active", "paused"],
    },
    "GALAXY_PROACTIVE_SCREEN": {
        "default": "false",
        "type": "boolean",
        "category": "perception",
        "description": "屏幕变化也触发主动开口（屏幕一直在变,开了会话多 · 默认关,只由声音/画面触发）",
    },
    "GALAXY_AMBIENT_SHARE_SESSION": {
        "default": "true",
        "type": "boolean",
        "category": "perception",
        "description": "主动开口续在当前对话主线上（关掉则另起一条独立会话,不打断你正在聊的 · 默认开）",
    },
    "GALAXY_VOICE_DIAG_S": {
        "default": "20",
        "type": "number",
        "category": "voice",
        "description": "麦克风自检的延迟(秒,启动后多久做一次采集自检;0=关闭自检 · 默认 20)",
    },
    # --- 回话时序(core/routes/chat.py)---
    "GALAXY_CHAT_TIMEOUT_S": {
        "default": "90",
        "type": "number",
        "category": "agent",
        "description": "单轮对话的总超时(秒,超了就中止本轮 · 默认 90)",
    },
    "GALAXY_LOCKSTEP_CPS": {
        "default": "14.0",
        "type": "number",
        "category": "voice",
        "description": "文字与语音同刻时文字的吐字速度(字/秒,越大文字跑得越快 · 默认 14)",
    },
    "GALAXY_LOCKSTEP_GRACE_S": {
        "default": "2.0",
        "type": "number",
        "category": "voice",
        "description": "同刻模式等首个语音块的宽限(秒,等不到就先放文字 · 默认 2)",
    },
    "GALAXY_LOCKSTEP_STALL_S": {
        "default": "8.0",
        "type": "number",
        "category": "voice",
        "description": "同刻模式中途卡住多久判定语音掉线、文字自己往下走(秒 · 默认 8)",
    },
    "GALAXY_LOCKSTEP_DRAIN_S": {
        "default": "0.8",
        "type": "number",
        "category": "voice",
        "description": "语音念完后文字收尾的排空时长(秒 · 默认 0.8)",
    },
    # --- 语音识别(core/asr/)---
    "GALAXY_ASR_INITIAL_PROMPT": {
        "default": "以下是普通话的句子。",
        "type": "string",
        "category": "voice",
        "description": "中文识别的引导语（把 Whisper 的输出偏置到简体、顺带给点上下文;留空=不加引导）",
    },
    "GALAXY_SENSEVOICE_MODEL": {
        "default": "iic/SenseVoiceSmall",
        "type": "string",
        "category": "voice",
        "description": "SenseVoice 识别引擎的模型 id（留空=用默认的 modelscope 版）",
    },
    # --- 语音合成:Edge / Piper ---
    "GALAXY_EDGE_TTS_TIMEOUT_S": {
        "default": "8",
        "type": "number",
        "category": "voice",
        "description": "Edge 在线合成的超时(秒,超了就降级到本地引擎 · 默认 8)",
    },
    "GALAXY_PIPER_MODEL": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Piper 语音模型(.onnx)的路径（留空=自动在 models/piper/ 下找）",
    },
    # --- 语音合成:Kokoro ---
    "GALAXY_KOKORO_MODEL": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Kokoro 模型文件名（留空=kokoro-v1.0.onnx;显存/磁盘紧张可换 int8 版）",
    },
    "GALAXY_KOKORO_VOICE": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Kokoro 音色（留空=按文本语种自动挑:中文 zf_/zm_,英文 af_/am_）",
    },
    "GALAXY_KOKORO_LANG": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Kokoro 发音语种（留空=按文本自动判定:含中文用 cmn,否则 en-us）",
    },
    "GALAXY_KOKORO_AUTOFETCH": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "首次使用 Kokoro 时后台自动下载模型（约 310MB · 默认开）",
    },
    # --- 语音合成:MeloTTS ---
    "GALAXY_MELO_LANG": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Melo 语种（留空=ZH_MIX_EN 中英混读;可选 ZH/EN/JP/KR/ES/FR）",
    },
    "GALAXY_MELO_SPEAKER": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Melo 说话人（留空=取该语种的第一个音色）",
    },
    "GALAXY_MELO_SPEED": {
        "default": "1.0",
        "type": "number",
        "category": "voice",
        "description": "Melo 语速倍率（建议 0.8~1.2,调太快中文会糊 · 默认 1.0）",
    },
    "GALAXY_MELO_DEVICE": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "Melo 推理设备（留空=auto,有显卡走 cuda 否则 cpu;也可直接填 cuda / cpu）",
    },
    # --- 语音合成:IndexTTS-2(零样本音色克隆)---
    "GALAXY_INDEXTTS_REF_AUDIO": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "IndexTTS 参考音频 wav 的路径（零样本克隆的音色来源,不填这条 IndexTTS 用不了）",
    },
    "GALAXY_INDEXTTS_AUTOFETCH": {
        "default": "false",
        "type": "boolean",
        "category": "voice",
        "description": "首次使用 IndexTTS 时后台自动下载模型（体积很大,默认关,要用请显式打开）",
    },
    "GALAXY_INDEXTTS_EMO_AUDIO": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "IndexTTS 情绪参考音频的路径（可选;用另一段音频的情绪配这段台词）",
    },
    "GALAXY_INDEXTTS_EMO_TEXT": {
        "default": "",
        "type": "string",
        "category": "voice",
        "description": "IndexTTS 情绪文本描述（可选;如“轻声、带点笑意”,与台词内容解耦）",
    },
    "GALAXY_INDEXTTS_USE_EMO_TEXT": {
        "default": "false",
        "type": "boolean",
        "category": "voice",
        "description": "由台词语义自动推断情绪（上面那条填了就自动生效,这里是不填也想推断时用 · 默认关）",
    },
    "GALAXY_INDEXTTS_EMO_ALPHA": {
        "default": "0.6",
        "type": "number",
        "category": "voice",
        "description": "IndexTTS 情绪强度（官方建议 0.6;调高情绪更浓、音色稳定性下降）",
    },
    "GALAXY_INDEXTTS_FP16": {
        "default": "false",
        "type": "boolean",
        "category": "voice",
        "description": "IndexTTS 用 fp16 推理（显存紧张的 GPU 场景打开,省显存略降质量 · 默认关）",
    },
    # --- 模型文件位置(与 GALAXY_DATA_DIR 等同属"东西放哪儿",归 storage)---
    "GALAXY_KOKORO_DIR": {
        "default": "models/kokoro",
        "type": "string",
        "category": "voice",
        "description": "Kokoro 模型目录（留空=models/kokoro）",
    },
    "GALAXY_INDEXTTS_DIR": {
        "default": "models/indextts2",
        "type": "string",
        "category": "voice",
        "description": "IndexTTS-2 模型目录（留空=models/indextts2）",
    },
    # --- 模型下载源 ---
    # 归 network:它与 GALAXY_HF_MIRROR 是同一件事的两面,而真正决定用哪个源的是
    # core/hf_endpoint.py::pick_endpoint()(探测择优后写回 HF_ENDPOINT)。
    "GALAXY_HF_ENDPOINT": {
        "default": "https://hf-mirror.com",
        "type": "url",
        "category": "network",
        "description": "模型下载源地址（默认国内镜像 hf-mirror.com;填自建镜像则只用它、不做失败转移）",
    },
    # ── 统一启动器 launcher/ + main.py(2026-08-04 补登记)──────────────────────
    #
    # 启动器重做落地(main.py / launcher/*.py 取代了 install.py、launch_desktop.py、
    # unified_launcher.py、system_manager.py)之后,那一侧读的 15 个配置键同样两边都
    # 没登记。**这不是"新代码还没来得及登记"** —— 它们大多是从旧启动器原样搬过来的,
    # 也就是说旧启动器时代就一直没接进面板,只是这次把守卫范围扩到 launcher/ 才扫出来。
    #
    # 其中 GALAXY_VOICE 是**语音总开关**:它决定语音循环起不起来。整条语音链路的开关
    # 都已在面板上,唯独最上面那个总闸只能手改 .env —— 这一条尤其不该漏。
    #
    # --- 语音总闸与识别规格(launcher/services.py)---
    "GALAXY_VOICE": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "启用语音（关掉则启动时完全不起语音循环,麦克风也不占用 · 默认开）",
    },
    "GALAXY_WHISPER_MODEL": {
        "default": "base",
        "type": "string",
        "category": "voice",
        "description": "语音循环的 Whisper 模型规格（tiny/base/small/medium/large,越大越准越慢 · 默认 base）",
    },
    # --- 桌面外壳(launcher/services.py、launcher/shell.py)---
    "GALAXY_DESKTOP_SHELL": {
        "default": "",
        "type": "select",
        "category": "advanced",
        "description": "桌面外壳（留空=自动挑选;electron=强制用 Electron 而不是 Tauri）",
        "options": ["", "electron"],
    },
    "GALAXY_SKIP_ELECTRON": {
        "default": "false",
        "type": "boolean",
        "category": "advanced",
        "description": "启动时跳过桌面外壳（只起后端服务,用浏览器访问面板 · 默认关）",
    },
    "GALAXY_TAURI_AUTOBUILD": {
        "default": "true",
        "type": "boolean",
        "category": "advanced",
        "description": "Tauri 外壳缺产物时自动构建（关掉则缺了就直接跳过、不占用启动时间 · 默认开）",
    },
    # --- 容器运行时(launcher/services.py)---
    "GALAXY_AUTO_DOCKER": {
        "default": "auto",
        "type": "string",
        "category": "advanced",
        "description": "自动拉起容器运行时（auto=装了就用 / 1=强制 / 0=关闭 · 默认 auto）",
    },
    "GALAXY_CONTAINER_RUNTIME": {
        "default": "",
        "type": "select",
        "category": "advanced",
        "description": "指定容器运行时（留空=两者都装时首启让你选;也可直接钉死 docker 或 podman）",
        "options": ["", "docker", "podman"],
    },
    "GALAXY_AUTO_DOCKER_DAEMON_WAIT": {
        "default": "60",
        "type": "number",
        "category": "advanced",
        "description": "等容器守护进程起来的超时(秒 · 默认 60)",
    },
    "GALAXY_AUTO_DOCKER_WAIT": {
        "default": "90",
        "type": "number",
        "category": "advanced",
        "description": "等容器内服务就绪的超时(秒 · 默认 90)",
    },
    # --- 启动诊断(main.py、launcher/services.py)---
    "GALAXY_VERBOSE": {
        "default": "false",
        "type": "boolean",
        "category": "advanced",
        "description": "启动过程输出详细信息（每一步都展开,排查启动问题时打开 · 默认关）",
    },
    "GALAXY_STRICT_PREFLIGHT": {
        "default": "false",
        "type": "boolean",
        "category": "advanced",
        "description": "启动前检查从严（任何一项不过就拒绝启动,而不是降级继续 · 默认关）",
    },
    # --- 节点起停(launcher/node_startup.py)---
    "GALAXY_API_HOST": {
        "default": "127.0.0.1",
        "type": "string",
        "category": "network",
        "description": "各节点回连 API 时用的主机名（默认只走本机回环;跨机部署才需要改）",
    },
    "GALAXY_NODE_HEALTH_RETRIES": {
        "default": "",
        "type": "number",
        "category": "devices",
        "description": "节点健康检查的重试次数（留空=按模式自动:桌面本机 5 次、其余 10 次;最低 2 次）",
    },
    # --- 依赖下载源(launcher/deps.py、main.py)---
    "GALAXY_PIP_INDEX": {
        "default": "",
        "type": "url",
        "category": "network",
        "description": "pip 下载源（留空=按内置镜像轮换;填了则只用它）",
    },
    "GALAXY_HF_MIRROR": {
        "default": "true",
        "type": "boolean",
        "category": "network",
        "description": "模型下载走国内镜像（关掉则只认官方 huggingface.co、不再回落镜像 · 默认开）",
    },
    # ══ core/ 全量配置键补登记(2026-08-05)══════════════════════════════════════
    #
    # 前三轮补登记都是「发现一处补一处」:先 21 个语音开关、再 5 个 B 档模态键、
    # 再 36 个语音/感知键 + 15 个启动器键。每一次都以为补完了。
    #
    # 这一次把守卫范围直接放到**整个 core/**,一次扫出 99 个未登记键 —— 也就是说
    # 前面三轮加起来仍然只覆盖了这个仓库配置面的一部分。根因始终是同一个:范围是
    # 人划的,划到哪儿就只保护到哪儿。范围放到 core/ 全量之后,这一类缺口才算真的封死。
    #
    # 其中 92 个是用户设置项,登记在下面;7 个是引导层/进程身份标记,进
    # tests/test_voice_switches_reach_the_panel.py::_NOT_USER_SETTINGS 并写明理由。
    # 每一条 default 都对着源码核过(读取点的真实回落值,不是文档里写的值)。
    "GALAXY_OPENSOURCE_FIRST": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "开源模型优先（同等能力下先用本地/开源，省钱且不出网 · 默认开）",
    },
    "GALAXY_BANDIT_ROUTING": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "按实测表现自动挑模型（用历史成功率/延迟学习，而不是固定优先级 · 默认开）",
    },
    "GALAXY_ROUTE_OBSERVED_WEIGHT": {
        "default": "1.0",
        "type": "number",
        "category": "agent",
        "description": "选模型时「实测表现」的权重（越大越信历史数据 · 默认 1.0）",
    },
    "GALAXY_ROUTE_LATENCY_WEIGHT": {
        "default": "0.5",
        "type": "number",
        "category": "agent",
        "description": "选模型时「快慢」的权重（越大越偏向快的 · 默认 0.5）",
    },
    "GALAXY_ROUTE_TOKEN_WEIGHT": {
        "default": "0.6",
        "type": "number",
        "category": "agent",
        "description": "选模型时「省 token」的权重（越大越偏向便宜的 · 默认 0.6）",
    },
    "GALAXY_CASCADE_FLOOR_MID": {
        "default": "0.35",
        "type": "number",
        "category": "agent",
        "description": "升到中档模型的复杂度门槛（0~1，低于它用小模型 · 默认 0.35）",
    },
    "GALAXY_CASCADE_FLOOR_HI": {
        "default": "0.70",
        "type": "number",
        "category": "agent",
        "description": "升到高档模型的复杂度门槛（0~1 · 默认 0.70）",
    },
    "GALAXY_MODEL_TIER": {
        "default": "",
        # **必须是 select,不能是 string。**
        #
        # 原先是 string 且没有 options —— 设置页据 type 决定控件形态,于是这一栏
        # 渲染成自由文本框:能填进任何垃圾,而档位表只认 A/B/C/D,填错的后果是
        # load_tier() 静默回落到默认档,用户以为自己钉住了某一档,其实没有。
        "type": "select",
        # 空串 = 不钉,按能力自动判。它必须在选项里,否则「不钉」这个选择在界面上
        # 表达不出来 —— 那才是默认值。
        "options": ["", "A", "B", "C", "D"],
        "category": "agent",
        # 原先写的是「填 A/B 可钉死用哪一档」。**实际有四档**(见
        # core/model_catalog.py 的 _TIERS):A 轻量本地 / B 全模态单模型 /
        # C 双模型·35B 推理位 / D 双模型·9B 推理位。说明少两档,人就只会在
        # 两档里挑,而 C 恰恰是当前默认在用的那一档。
        "description": (
            "强制本地档位（留空=按能力自动判）。"
            "A=轻量本地(Gemma 4 系，无独显也能跑) · "
            "B=全模态单模型(MiniCPM-o，需显卡) · "
            "C=双模型/35B 推理位 · D=双模型/9B 推理位"
        ),
    },
    "GALAXY_HF_OLLAMA_FALLBACK": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "HuggingFace 模型拉不到时回落 Ollama（默认开）",
    },
    "GALAXY_OLLAMA_NUM_CTX": {
        "default": "",
        "type": "number",
        "category": "agent",
        "description": (
            "Ollama 上下文窗口大小(token · 留空=按实际装配量与显存自动定；" "填了则一律尊重，0=用模型默认)"
        ),
    },
    "GALAXY_CONTEXT_ARCHIVE_MAX_MB": {
        "default": "",
        "type": "number",
        "category": "memory",
        "description": ("上下文归档总量上限(MB · 留空=2048；0=不设上限、永不自动删)"),
    },
    "GALAXY_CONTEXT_ARCHIVE_MIN_DAYS": {
        "default": "",
        "type": "number",
        "category": "memory",
        "description": ("上下文归档最少保留天数(留空=30 · 这么新的会话一律不删，" "哪怕已超总量上限——那时只告警不删)"),
    },
    "GALAXY_PHASE_LEDGER_DAYS": {
        "default": "",
        "type": "number",
        "category": "memory",
        "description": (
            "三态转移账保留天数(留空=90 · 记忆卡片按 3 天一张，90 天约 30 张；" "更早的窗口本身已经是摘要了)"
        ),
    },
    "GALAXY_IGNORE_CONTEXT_MEASUREMENTS": {
        "default": "",
        "type": "boolean",
        "category": "agent",
        "description": ("忽略本机实测的 KV 单价(排障用 · 打开后上下文只按目录声明算，" "不再按实测放开)"),
    },
    "GALAXY_LLAMA_CTX": {
        "default": "",
        "type": "number",
        "category": "agent",
        "description": ("llama.cpp 上下文窗口大小(token · 留空=按实际装配量与显存自动定；" "填了则一律尊重)"),
    },
    "GALAXY_OLLAMA_KEEP_ALIVE": {
        "default": "-1",
        "type": "string",
        "category": "agent",
        "description": "Ollama 模型在显存里驻留多久（-1=一直留着不卸载，省下每次加载时间 · 默认 -1）",
    },
    "GALAXY_URL_SENTINEL": {
        "default": "true",
        "type": "boolean",
        "category": "advanced",
        "description": "Ollama 地址自检（启动时探一次地址对不对，不对就纠正 · 默认开）",
    },
    "GALAXY_MOA_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "多模型协作（难题让几个模型各出方案再汇总 · 默认开）",
    },
    "GALAXY_MOA_COMPLEXITY": {
        "default": "0.85",
        "type": "number",
        "category": "agent",
        "description": "触发多模型协作的复杂度门槛（0~1，越高越少触发 · 默认 0.85）",
    },
    "GALAXY_MOA_PROPOSERS": {
        "default": "3",
        "type": "number",
        "category": "agent",
        "description": "多模型协作时出方案的模型个数（默认 3）",
    },
    "GALAXY_MOA_LAYERS": {
        "default": "2",
        "type": "number",
        "category": "agent",
        "description": "多模型协作的汇总轮数（默认 2）",
    },
    "GALAXY_CRITIC_MAX_ROUNDS": {
        "default": "2",
        "type": "number",
        "category": "agent",
        "description": "自我复核的最多轮数（写完让模型自己挑毛病再改 · 默认 2）",
    },
    "GALAXY_FORCE_COLLAB_MODE": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "强制协作模式（留空=按任务自动选；可填 single/moa 等钉死）",
    },
    "GALAXY_PLANNER_MAX_REPLANS": {
        "default": "1",
        "type": "number",
        "category": "agent",
        "description": "计划失败后最多重新规划几次（默认 1）",
    },
    "GALAXY_EXPERIENCE_STRATEGY": {
        "default": "true",
        "type": "boolean",
        "category": "memory",
        "description": "用历史经验调整策略（从过去做过的类似任务里学 · 默认开）",
    },
    "GALAXY_UNIFIED_WORKFLOW": {
        "default": "false",
        "type": "boolean",
        "category": "agent",
        "description": "统一工作流引擎（实验特性 · 默认关）",
    },
    "GALAXY_TOOLS_SLIM": {
        "default": "auto",
        "type": "string",
        "category": "agent",
        "description": "精简工具集（auto=按上下文压力自动裁 / 1=总是裁 / 0=从不裁 · 默认 auto）",
    },
    "GALAXY_TOOLS_JIT": {
        "default": "off",
        "type": "string",
        "category": "agent",
        "description": "按需加载工具（off=全部预载 / on=用到才载，省上下文但多一次往返 · 默认 off）",
    },
    "GALAXY_TOOLS_STICKY": {
        "default": "auto",
        "type": "string",
        "category": "agent",
        "description": "保留上一轮用过的工具（auto=自动 / 1/0 · 默认 auto）",
    },
    "GALAXY_TOOLS_CORE": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "常驻热核工具的名字片段（逗号分隔；留空=用内置默认，这些工具永不被裁掉）",
    },
    "GALAXY_ACTIVE_PERCEPTION": {
        "default": "false",
        "type": "boolean",
        "category": "perception",
        "description": "主动感知（不等你开口，AI 自己看屏幕/听环境找事做 · 默认关）",
    },
    "GALAXY_ACI_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "memory",
        "description": "预取上下文（提前把可能要用的资料捞好，回答更快 · 默认开）",
    },
    "GALAXY_FAST_LOOP": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "快速回路（简单请求走短路径，不进完整规划 · 默认开）",
    },
    "GALAXY_FOCUS_STACK_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "memory",
        "description": "注意力栈（记住「刚才在聊什么」，被打断后能接回去 · 默认开）",
    },
    "GALAXY_MANIFEST_ON_FIRST_TOKEN": {
        "default": "true",
        "type": "boolean",
        "category": "security",
        "description": "首个字一出就显形（而不是等整句生成完 · 默认开）",
    },
    "GALAXY_LIMINAL_REHEARSAL": {
        "default": "auto",
        "type": "string",
        "category": "agent",
        "description": "空闲预演（闲时提前想可能被问到的事 · auto=自动 / 1 / 0 · 默认 auto）",
    },
    "GALAXY_REHEARSAL_CANDIDATES": {
        "default": "1",
        "type": "number",
        "category": "agent",
        "description": "每次预演准备几个候选（默认 1）",
    },
    "GALAXY_REHEARSAL_COMPLEXITY_FLOOR": {
        "default": "0.55",
        "type": "number",
        "category": "agent",
        "description": "值得预演的复杂度下限（0~1 · 默认 0.55）",
    },
    "GALAXY_HA_BRIDGE": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "接入 Home Assistant（能控智能家居 · 默认开，没装 HA 时自动跳过）",
    },
    "GALAXY_TTS_VOICE": {
        "default": "zh-CN-XiaoxiaoNeural",
        "type": "string",
        "category": "voice",
        "description": "在线合成的音色名（Edge TTS 的音色 id · 默认晓晓）",
    },
    "GALAXY_SPEAK_MAX_CHARS": {
        "default": "600",
        "type": "number",
        "category": "voice",
        "description": "单次朗读的字数上限（超长会截断，防止一口气念太久 · 默认 600）",
    },
    "GALAXY_LOCAL_AUDIO": {
        "default": "true",
        "type": "boolean",
        "category": "voice",
        "description": "本机播放声音（关掉则只出文字不出声 · 默认开）",
    },
    "GALAXY_NATIVE_MM_CHAT": {
        "default": "false",
        "type": "boolean",
        "category": "perception",
        "description": "原生多模态对话格式（把图片/音频按模型原生格式发，而不是转文字 · 默认关）",
    },
    "GALAXY_CU_MEMORY": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "桌面操作记住失败经验（下次遇到同一个界面会带上「上次这么点没用」· 默认开）",
    },
    "GALAXY_HITL_CONFIRM_GATE": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "执行前都要你点确认（最稳但最慢 · 默认关，只有高危动作才问）",
    },
    "GALAXY_HITL_CONFIRM_TIMEOUT_S": {
        "default": "60",
        "type": "number",
        "category": "security",
        "description": "等你确认的超时(秒，超时按拒绝处理 · 默认 60)",
    },
    "GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S": {
        "default": "90.0",
        "type": "number",
        "category": "security",
        "description": "高危动作等确认的超时(秒 · 默认 90)",
    },
    "GALAXY_PERM_STRICT": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "节点权限从严（没显式授权的动作一律拒绝 · 默认关，按默认策略放行）",
    },
    "GALAXY_ALLOW_REMOTE_INSTALL_SCRIPT": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "允许执行远程安装脚本（有供应链风险，装本地模型时才需要 · 默认关）",
    },
    "GALAXY_INPUT_VALIDATION_LOOPBACK": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "本机回环也做输入校验（默认关=本机来的请求免校验，图快）",
    },
    "GALAXY_RATE_LIMIT_LOOPBACK": {
        "default": "false",
        "type": "boolean",
        "category": "security",
        "description": "本机回环也限流（默认关=本机不限）",
    },
    "GALAXY_DEVICE_TOKEN_RETENTION_DAYS": {
        "default": "30",
        "type": "number",
        "category": "devices",
        "description": "已吊销的设备凭证保留多少天（默认 30）",
    },
    "GALAXY_DEVICE_TOKEN_MAX_RECORDS": {
        "default": "512",
        "type": "number",
        "category": "devices",
        "description": "设备凭证记录总条数上限（只淘汰已吊销的，绝不删还在用的 · 默认 512）",
    },
    "GALAXY_PEER_DEFAULT_TRUST": {
        "default": "ask",
        "type": "select",
        "category": "security",
        "description": "新设备的默认信任级别（ask=每次问你 / trusted=直接放行 / blocked=直接拒 · 默认 ask）",
        "options": ["ask", "trusted", "blocked"],
    },
    "GALAXY_LAN_DISCOVERY": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "局域网自动发现设备（默认开）",
    },
    "GALAXY_LAN_DISCOVERY_TYPES": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "要浏览的服务类型（逗号分隔；留空=用内置默认那几种）",
    },
    "GALAXY_MESH_DISCOVERY_TIMEOUT": {
        "default": "2.0",
        "type": "number",
        "category": "devices",
        "description": "组网发现的等待超时(秒 · 默认 2)",
    },
    "GALAXY_TRANSPORT_ADAPTIVE": {
        "default": "true",
        "type": "boolean",
        "category": "network",
        "description": "传输方式自适应（按网络状况自动在几种通道间切 · 默认开）",
    },
    "GALAXY_TRANSPORT_BULK_BYTES": {
        "default": "65536",
        "type": "number",
        "category": "network",
        "description": "大块传输的分片大小(字节 · 默认 65536)",
    },
    "GALAXY_TS_ADVERTISE_RELAY": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "把本机登记为 Tailscale 中继（帮别的设备转发 · 默认开）",
    },
    "GALAXY_TS_FUNNEL": {
        "default": "true",
        "type": "boolean",
        "category": "devices",
        "description": "把网关经 Tailscale Funnel 暴露到公网（手表带流量单独出门时唯一能连的一条 · 默认开；未开鉴权时会被硬闸门拒绝执行）",
    },
    "GALAXY_ANDROID_WS_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "启用 Android WebSocket 接入面（默认关，开鉴权时会连带打开）",
    },
    "GALAXY_GATEWAY_MODE": {
        "default": "",
        "type": "string",
        "category": "network",
        "description": "网关部署模式（留空=不作为网关；配了它启动前检查会按网关口径校验）",
    },
    "GALAXY_SIGNALING_TIMEOUT_S": {
        "default": "",
        "type": "number",
        "category": "devices",
        "description": "WebRTC 信令超时(秒；留空=用内置默认)",
    },
    "GALAXY_MEMORY_BACKENDS": {
        "default": "vector",
        "type": "string",
        "category": "memory",
        "description": "启用的记忆后端（逗号分隔，如 vector,graph · 默认 vector）",
    },
    "GALAXY_EMBED_MODEL": {
        "default": "paraphrase-multilingual-MiniLM-L12-v2",
        "type": "string",
        "category": "memory",
        "description": "文本向量化模型（换模型后旧向量库要重建 · 默认多语言 MiniLM）",
    },
    "GALAXY_CLIP_MODEL": {
        "default": "clip-ViT-B-32",
        "type": "string",
        "category": "perception",
        "description": "图片记忆的向量模型（默认 CLIP ViT-B/32）",
    },
    "GALAXY_CLAP_MODEL": {
        "default": "laion/clap-htsat-unfused",
        "type": "string",
        "category": "perception",
        "description": "声音记忆的向量模型（默认 CLAP）",
    },
    "GALAXY_SIMPLEMEM_MODEL": {
        "default": "",
        "type": "string",
        "category": "memory",
        "description": "SimpleMem 记忆抽取用的模型（留空=退回 OPENAI_MODEL，再空则 gpt-4o-mini）",
    },
    "GALAXY_SIMPLEMEM_BASE_URL": {
        "default": "",
        "type": "url",
        "category": "memory",
        "description": "SimpleMem 的 API 地址（留空=退回 OPENAI_API_BASE）",
    },
    "GALAXY_SIMPLEMEM_API_KEY": {
        "default": "",
        "type": "string",
        "category": "memory",
        "description": "SimpleMem 专用 API Key（留空=退回 OPENAI_API_KEY / DEEPSEEK_API_KEY）",
    },
    "GALAXY_REMOTE_DESKTOP": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "远程桌面接入（默认关）",
    },
    "GALAXY_VNC_CMD": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "VNC 启动命令（留空=自动探测已装的 VNC 服务）",
    },
    "GALAXY_VNC_PORT": {
        "default": "5900",
        "type": "number",
        "category": "devices",
        "description": "VNC 端口（默认 5900）",
    },
    "GALAXY_DEVICE_NAME": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "这台设备的显示名（留空=用设备 id；多设备时起个好认的名字）",
    },
    "GALAXY_DEVICE_TYPE": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "这台设备的类型（留空=unknown；如 desktop/laptop/server）",
    },
    "GALAXY_DURABLE_EXEC": {
        "default": "false",
        "type": "boolean",
        "category": "agent",
        "description": "持久化执行（任务状态落盘，进程重启能接着跑 · 默认关）",
    },
    "GALAXY_DISPATCH_IDEMPOTENCY": {
        "default": "true",
        "type": "boolean",
        "category": "agent",
        "description": "派发幂等（同一个任务重复下发只执行一次 · 默认开）",
    },
    "GALAXY_TAURI_AUTO_INSTALL_MSVC": {
        "default": "true",
        "type": "boolean",
        "category": "advanced",
        "description": "Windows 上缺 MSVC 时自动装（构建桌面壳要用 · 默认开）",
    },
    "GALAXY_CLIP_DIR": {
        "default": "",
        "type": "string",
        "category": "perception",
        "description": "图片记忆库目录（留空=跟随 CHROMA_PERSIST_DIR，再空则 ./data/clip_memory）",
    },
    "GALAXY_CLAP_DIR": {
        "default": "./data/clap_memory",
        "type": "string",
        "category": "perception",
        "description": "声音记忆库目录（默认 ./data/clap_memory）",
    },
    "GALAXY_OMNIMEM_DIR": {
        "default": "./data/omni_simplemem",
        "type": "string",
        "category": "memory",
        "description": "SimpleMem 记忆目录（默认 ./data/omni_simplemem）",
    },
    "GALAXY_TASK_LEDGER_PATH": {
        "default": "data/task_cost_ledger.jsonl",
        "type": "string",
        "category": "advanced",
        "description": "任务成本账本路径（默认 data/task_cost_ledger.jsonl）",
    },
    "GALAXY_TASK_ALLOCATION_STATE_PATH": {
        "default": "",
        "type": "string",
        "category": "advanced",
        "description": "任务分配真相文件（留空=runtime/task_allocation_truth.json）",
    },
    "GALAXY_TASK_GRAPH_STATE_PATH": {
        "default": "",
        "type": "string",
        "category": "advanced",
        "description": "任务图状态文件（留空=用内置默认位置）",
    },
    "GALAXY_LAST_OPERATOR_ACTION_STATE_PATH": {
        "default": "",
        "type": "string",
        "category": "advanced",
        "description": "面板最近操作记录（留空=runtime/panel_last_operator_action.json）",
    },
    "GALAXY_PEER_TRUST_PATH": {
        "default": "",
        "type": "string",
        "category": "security",
        "description": "设备信任名单文件（留空=用内置默认位置）",
    },
    "GALAXY_DEVICE_TOKEN_STORE": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "设备凭证库位置（留空=用内置默认位置）",
    },
    "GALAXY_OTEL_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "advanced",
        "description": "OpenTelemetry 链路追踪（没装 SDK 时自动降级不报错 · 默认开）",
    },
    "GALAXY_OTEL_EXPORTER": {
        "default": "",
        "type": "select",
        "category": "network",
        "description": "链路数据发到哪（留空=只在进程内产生不外发 / otlp=发到采集器 / console=打屏调试）",
        "options": ["", "otlp", "console"],
    },
    "GALAXY_OTEL_SERVICE_NAME": {
        "default": "galaxy-v2",
        "type": "string",
        "category": "advanced",
        "description": "上报到追踪系统时的服务名（默认 galaxy-v2）",
    },
    "GALAXY_OPS_FAILURE_REASONS_MAX": {
        "default": "200",
        "type": "number",
        "category": "advanced",
        "description": "失败原因最多留几条（超出丢最旧的 · 默认 200）",
    },
    "GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX": {
        "default": "100",
        "type": "number",
        "category": "advanced",
        "description": "审计失败原因最多留几条（默认 100）",
    },
    "GALAXY_OPS_REJECTION_REASONS_MAX": {
        "default": "200",
        "type": "number",
        "category": "advanced",
        "description": "拒绝原因最多留几条（默认 200）",
    },
    "GALAXY_OPS_FALLBACK_KINDS_MAX": {
        "default": "50",
        "type": "number",
        "category": "advanced",
        "description": "降级类型最多留几种（默认 50）",
    },
    "GALAXY_PHASE_TIMING": {
        "default": "true",
        "type": "boolean",
        "category": "advanced",
        "description": "记录启动各阶段耗时（排查启动慢时有用 · 默认开）",
    },
    "GALAXY_PANEL_PUSH_MIN_INTERVAL": {
        "default": "1.0",
        "type": "number",
        "category": "advanced",
        "description": "面板推送的最小间隔(秒，防止刷屏 · 默认 1)",
    },
    "GALAXY_MODELS_PROBE_BUDGET": {
        "default": "4.0",
        "type": "number",
        "category": "agent",
        "description": "探测模型可用性的时间预算(秒 · 默认 4)",
    },
    "GALAXY_MODELS_STATUS_TTL": {
        "default": "3.0",
        "type": "number",
        "category": "agent",
        "description": "模型状态缓存时长(秒 · 默认 3)",
    },
    # 2026-09-06 补。没有这个键之前,registry 里 deepseek / meta 标着
    # supports_responses,却没有任何一条路能走到那条传输上 —— 声明摆着、一处也
    # 到不了。判据在 core/multi_llm_router._responses_opt_in()。
    "GALAXY_RESPONSES_PROVIDERS": {
        "default": "",
        "type": "string",
        "category": "agent",
        "description": "让这些厂商走 Responses 接口（逗号分隔，如 deepseek,meta · 那条路没有逐字流式 · 默认空）",
    },
    # --- WebRTC & Network ---
    # 说明原先只有 "WebRTC Data Channel" 一句英文 —— 面板上照原样显示,中文用户看不懂
    # 这开了会发生什么。是这一轮把守卫范围改成按目录派生之后,
    # core/multimodal/webrtc_ingress_bridge.py 进了范围才扫出来的。
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL": {
        "default": "false",
        "type": "boolean",
        "category": "devices",
        "description": "WebRTC 数据通道（浏览器/手机端把摄像头与麦克风的采集结果直接推给感知层 · 默认关）",
    },
    "GALAXY_TURN_URLS": {
        "default": "",
        "type": "string",
        "category": "devices",
        "description": "TURN 中继服务器地址（NAT 穿不透时靠它转发音视频）",
    },
    "GALAXY_HEADSCALE_URL": {
        "default": "",
        "type": "url",
        "category": "network",
        "description": "Headscale 控制端地址（自建的 Tailscale 控制面）",
    },
    "GALAXY_TAILSCALE_CHECK_INTERVAL": {
        "default": "60",
        "type": "number",
        "category": "network",
        "description": "Tailscale 状态检查间隔(秒 · 默认 60)",
    },
    "CORS_ALLOWED_ORIGINS": {
        "default": "*",
        "type": "string",
        "category": "security",
        "description": "允许跨域访问的来源（* = 全允许；对外开放时务必收紧）",
    },
    "CORS_ALLOWED_METHODS": {
        "default": "GET,POST,PUT,DELETE",
        "type": "string",
        "category": "security",
        "description": "允许跨域的 HTTP 方法（默认 GET,POST,PUT,DELETE）",
    },
    "CORS_ALLOWED_HEADERS": {
        "default": "*",
        "type": "string",
        "category": "security",
        "description": "允许跨域的请求头（* = 全允许）",
    },
    # --- SLO & Continuity ---
    "GALAXY_SLO_LATENCY_WINDOW": {
        "default": "300",
        "type": "number",
        "category": "advanced",
        "description": "延迟统计窗口(秒 · 默认 300)",
    },
    "GALAXY_SLO_HEARTBEAT_WINDOW": {
        "default": "60",
        "type": "number",
        "category": "advanced",
        "description": "心跳统计窗口(秒 · 默认 60)",
    },
    "GALAXY_RESULT_INGRESS_CONTINUITY_MODE": {
        "default": "strict",
        "type": "select",
        "category": "advanced",
        "description": "结果回流连续性模式（strict=断了就报，不静默补 · 默认 strict）",
        "options": ["strict", "best-effort", "disabled"],
    },
    "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE": {
        "default": "strict",
        "type": "select",
        "category": "advanced",
        "description": "运行时真相连续性模式（strict=断了就报 · 默认 strict）",
        "options": ["strict", "best-effort", "disabled"],
    },
    "GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S": {
        "default": "300",
        "type": "number",
        "category": "devices",
        "description": "主脑扩缩容重评估间隔(秒 · 默认 300)",
    },
    "GALAXY_TEMPORAL_URL": {
        "default": "",
        "type": "url",
        "category": "advanced",
        "description": "Temporal 工作流引擎地址（留空=不用）",
    },
    "GALAXY_GW_ADAPTER_DLQ_SUBJECT": {
        "default": "",
        "type": "string",
        "category": "advanced",
        "description": "网关适配器死信队列的主题名（处理不了的消息扔这儿）",
    },
}
