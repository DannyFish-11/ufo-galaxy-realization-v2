"""「全部设置」页上每一行的中文名，以及下拉档位的中文名。

为什么单独一份
--------------
设置页原先每行第一行写的是环境变量名（GALAXY_AEC_RES_FLOOR_DB），后面才是一句描述；
档位牌写的是原始取值（strict / best-effort / shadow）。对不读源码的人这两样都读不懂。
这里给每个列在面板上的键一个**短的中文名**，给每个下拉键的每个取值一个中文名。

* LABELS —— 键 → 中文名（2–20 字，全表不重名）。环境变量名不再占据行首，改成悬停提示。
* OPTION_LABELS —— 键 → {取值: 中文名}。没写的取值面板原样显示（比如 OLLAMA_MODEL 的型号串）；
  空串取值显示「自动」。

这份表只管**说法**，不管列不列、默认是什么、生效不生效 —— 那些是 config_schema_registry.py、
panel_switch_policy.py、config_bundles.py 的事。tests/test_every_listed_setting_has_a_chinese_name.py
钉住：GET /api/config/all 列出的每个键都在这里有名字、每个下拉取值都有中文名、表里没有过期的键。
新增一个会列在面板上的配置，不补这里测试会红。
"""

from __future__ import annotations

from typing import Dict

#: 键 → 中文名。按 CONFIG_SCHEMA 的分类分段，段内顺序同注册表。
LABELS: Dict[str, str] = {
    # ── 整档按钮的主键：设置页不画（按钮就是它的开关），但仍随 /api/config/all 返回，所以也要有名字 ──
    "GALAXY_AMBIENT_LOOP": "全模态常驻感知",
    "GALAXY_AUTONOMY": "自治档位",
    "GALAXY_CROSS_DEVICE_ENABLED": "跨设备模式",
    # ── llm ──
    "OPENAI_API_KEY": "OpenAI 密钥",
    "ANTHROPIC_API_KEY": "Anthropic 密钥",
    "DEEPSEEK_API_KEY": "DeepSeek 密钥",
    "GOOGLE_API_KEY": "Google 密钥",
    "GEMINI_API_KEY": "Gemini 密钥",
    "XAI_API_KEY": "xAI 密钥",
    "META_API_KEY": "Meta 密钥",
    "MISTRAL_API_KEY": "Mistral 密钥",
    "AGNES_API_KEY": "Agnes AI 密钥",
    "QWEN_API_KEY": "通义千问密钥",
    "DASHSCOPE_API_KEY": "阿里云百炼密钥",
    "ZHIPU_API_KEY": "智谱密钥",
    "ZHIPU_CODING_API_KEY": "智谱编码套餐密钥",
    "GROQ_API_KEY": "Groq 密钥",
    "HF_API_TOKEN": "HuggingFace 访问令牌",
    "MOONSHOT_API_KEY": "月之暗面 Kimi 密钥",
    "MIMO_API_KEY": "小米 MiMo 密钥",
    "MINIMAX_API_KEY": "MiniMax 密钥",
    "PERPLEXITY_API_KEY": "Perplexity 密钥",
    "STEP_API_KEY": "阶跃星辰密钥",
    "ONEAPI_URL": "OneAPI 网关地址",
    "ONEAPI_API_KEY": "OneAPI 网关密钥",
    "OPENROUTER_API_KEY": "OpenRouter 密钥",
    "DEEPSEEK_OCR2_API_KEY": "DeepSeek OCR 密钥",
    "ZHIPU_API_BASE": "智谱接口地址",
    "OPENAI_API_BASE": "OpenAI 接口地址（代理/中转）",
    "SONAR_API_KEY": "Perplexity Sonar 密钥",
    "LOCAL_VLLM_URL": "本机 vLLM 服务地址",
    "OLLAMA_MODEL": "本地主脑模型",
    # ── network ──
    "GATEWAY_PORT": "网关端口",
    # ── devices ──
    "UFO_NODE_HOST": "节点主机名",
    "NODE_92_URL": "设备控制服务的地址",
    "NODE_45_URL": "桌面端点的地址",
    "NODE_33_URL": "安卓 ADB 控制的地址",
    "NODE_71_URL": "多设备编排的地址",
    "NODE_71_HOST": "多设备编排的主机名",
    "NODE_95_URL": "视觉采样服务的地址",
    "NODE_97_URL": "学术检索服务的地址",
    # ── security ──
    "NODE09_SANDBOX_URL": "代码沙箱的地址",
    # ── agent ──
    "OLLAMA_URL": "Ollama 服务地址",
    # ── advanced ──
    "GALAXY_PS_ALLOWED_CMDLETS": "PowerShell 白名单追加项",
    "QDRANT_URL": "Qdrant 向量库的地址",
    "REDIS_URL": "Redis 的地址",
    # ── security ──
    "SECRETVAULT_URL": "密钥保险库的地址",
    # ── advanced ──
    "MAIN_REPO_URL": "主仓库服务的地址",
    # ── network ──
    "MQTT_PORT": "MQTT 消息代理的端口",
    # ── security ──
    "GALAXY_API_TOKEN": "API 访问令牌",
    "GALAXY_API_TOKENS": "多个 API 访问令牌",
    "GALAXY_API_TOKEN_EXPIRY": "令牌有效期",
    "GALAXY_REVOKED_TOKENS": "已吊销的令牌名单",
    "GALAXY_SECRET_BACKEND": "密钥存放方式",
    "GALAXY_TLS_CERT": "TLS 证书路径",
    "GALAXY_TLS_KEY": "TLS 私钥路径",
    # ── agent ──
    "GITHUB_ALLOWLIST": "允许安装的 GitHub 仓库",
    "GITHUB_BLOCKLIST": "禁止安装的 GitHub 仓库",
    "GALAXY_ADDON_UNATTENDED": "插件安装免确认（无人值守）",
    "GALAXY_ADDON_HOST_DEPS": "插件依赖装进主环境",
    # ── security ──
    "GITHUB_TOKEN": "GitHub 访问令牌",
    # ── devices ──
    "GALAXY_MESH_SECRET": "Mesh 签名密钥",
    "GALAXY_NATS_URL": "NATS 消息总线的地址",
    "GALAXY_NATS_EXECUTOR_TIMEOUT": "NATS 执行器超时",
    "GALAXY_NATS_EXECUTOR_FALLBACK": "NATS 不可用时怎么办",
    "GALAXY_MASTER_BRAIN_ENABLED": "主脑编排与分布式执行",
    "GALAXY_HEARTBEAT_INTERVAL": "节点心跳间隔",
    "FEDERATION_ENABLED": "启用联邦",
    "FEDERATION_LOCAL_HOST": "联邦里本机对外的主机名",
    "FEDERATION_PEERS": "联邦对端地址",
    "FEDERATION_HEARTBEAT_INTERVAL": "联邦心跳间隔",
    # ── security ──
    "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE": "派发权威模式",
    # ── agent ──
    "GALAXY_ROUTER_MAX_QUEUE_DEPTH": "请求排队上限",
    # ── advanced ──
    "GALAXY_CB_FAILURE_THRESHOLD": "连续失败几次触发熔断",
    "GALAXY_CB_RECOVERY_TIMEOUT_S": "熔断后隔多久试探恢复",
    "GALAXY_CB_HALF_OPEN_PROBES": "试探恢复时先放几个请求进去",
    "GALAXY_CB_WINDOW_SIZE": "熔断统计窗口",
    "GALAXY_AS_TARGET_LATENCY_MS": "自适应并发的目标延迟",
    "GALAXY_AS_ERROR_THRESHOLD": "自适应并发的错误率阈值",
    "GALAXY_AS_INIT_LIMIT": "自适应并发的起始并发数",
    "GALAXY_AS_MAX_LIMIT": "自适应并发的上限",
    "GALAXY_AS_MIN_LIMIT": "自适应并发的下限",
    "GALAXY_AS_SAMPLE_WINDOW": "自适应并发的采样窗口",
    "GALAXY_AS_PROBE_INTERVAL_S": "自适应并发的探测间隔",
    "GALAXY_DATA_DIR": "数据总目录",
    "GALAXY_MARKET_STORE_DIR": "技能市场的本地目录",
    "GALAXY_FEATURE_FLAGS_PATH": "功能开关文件路径",
    # ── devices ──
    "GALAXY_MASTER_BRAIN_STATE_PATH": "主脑状态文件路径",
    # ── memory ──
    "CHROMA_PERSIST_DIR": "Chroma 向量库目录",
    # ── devices ──
    "ANDROID_DEVICE_STATE_STORE_PATH": "安卓设备状态库路径",
    "ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS": "安卓设备快照的保鲜时长",
    # ── advanced ──
    "GALAXY_MODE": "运行模式",
    "GALAXY_PREFLIGHT_MODE": "手动预检查哪一组",
    "CMD_MAX_CONCURRENT": "单类命令的最大并发数",
    "CONCURRENCY_GLOBAL_MAX": "全局最大并发数",
    # ── security ──
    "GALAXY_MAX_CONTEXT_TOKENS": "上下文 token 上限",
    # ── advanced ──
    "GALAXY_MAX_MESSAGE_SIZE": "单条消息大小上限",
    # ── voice ──
    "GALAXY_TTS_ENGINE": "朗读引擎",
    "GALAXY_ASR_ENGINE": "听写引擎",
    "GALAXY_VOICE_EAGERNESS": "接话急切度",
    # ── perception ──
    "GALAXY_AMBIENT_INTERVAL_S": "自发在场的节拍",
    "GALAXY_AMBIENT_COOLDOWN_S": "开口或委托后的冷却",
    "GALAXY_AMBIENT_SPEAK_PER_HOUR": "自发开口每小时上限",
    "GALAXY_AMBIENT_DELEGATE_PER_HOUR": "自发委托每小时上限",
    "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION": "本机播放声进入感知",
    # ── agent ──
    "GALAXY_SPECULATIVE_DRAFT": "投机解码草稿",
    # ── voice ──
    "GALAXY_VOICE_DUPLEX": "全双工语音",
    "GALAXY_AEC_RES_OVER": "回声残余抑制强度",
    "GALAXY_AEC_RES_FLOOR_DB": "远端单讲的抑制下限",
    "GALAXY_AEC_RES_DT_FLOOR_DB": "双讲时的抑制下限",
    "GALAXY_AEC_DTD_HANGOVER": "双讲保持块数",
    "GALAXY_TEXT_VOICE_LOCKSTEP": "文字与语音同刻",
    "GALAXY_VOICE_DUCK_GAIN": "压低音量的倍数",
    "GALAXY_VOICE_HOLD_S": "「等一下」后的静候时长",
    "GALAXY_VOICE_ECHO_SIM": "自回声判定阈值",
    "GALAXY_VOICE_ECHO_TAIL_S": "念完后的防回声时长",
    "GALAXY_VOICE_ECHO_MIN_CHARS": "自回声判定的最短字数",
    "GALAXY_VOICE_ECHO_MIN_BLOCK": "自回声判定的最短重合字数",
    "GALAXY_AEC_TAIL_MS": "回声消除滤波器长度",
    "GALAXY_AEC_MU": "回声消除收敛步长",
    "GALAXY_AEC_MAX_DELAY_MS": "喇叭到麦克风的最大延迟",
    "GALAXY_AEC_DTD_MARGIN_DB": "双讲检测余量",
    # ── agent ──
    "GALAXY_REALTIME_PROVIDER": "全双工语音服务商",
    "GALAXY_DUPLEX_VIDEO_FPS": "通话画面上行帧率",
    "GALAXY_DUPLEX_VIDEO_JPEG_QUALITY": "通话画面 JPEG 质量",
    "GALAXY_REALTIME_MODEL": "全双工语音的模型",
    # ── voice ──
    "GALAXY_REALTIME_VOICE": "全双工语音的音色",
    # ── agent ──
    "GALAXY_REALTIME_URL": "全双工语音连接地址",
    "GALAXY_MINICPM_SERVER_URL": "本地全模态服务地址",
    # ── perception ──
    "GALAXY_PERCEPTION_MODEL": "感知模型型号",
    # ── security ──
    "GALAXY_EXECUTION_ISOLATION": "智能体自写代码的隔离方式",
    # ── agent ──
    "GALAXY_MCP_PIN_MODE": "MCP 工具清单复验档位",
    # ── security ──
    "GALAXY_TOOL_GUARDIAN": "工具调用守护",
    "GALAXY_EGRESS_MODE": "出站管控档位",
    "GALAXY_EGRESS_ALLOW": "出站白名单追加项",
    "GALAXY_TRUST_REMOTE_CODE": "允许运行自带代码的模型",
    "GALAXY_WEIGHTS_HOSTS": "允许下载权重的主机白名单",
    # ── agent ──
    "GALAXY_LLAMA_SERVER_BIN": "llama-server 程序路径",
    "GALAXY_LOCAL_GUI_VLM_URL": "端侧 GUI 视觉模型地址",
    "GALAXY_LOCAL_GUI_VLM_MODEL": "屏幕操作视觉模型型号",
    "GALAXY_LOCAL_GUI_VLM_TIMEOUT_S": "屏幕操作视觉模型超时",
    "GALAXY_VISION_BACKEND_ORDER": "视觉后端的尝试顺序",
    "GALAXY_COMPUTER_USE_STRATEGY": "桌面操作的规划粒度",
    # ── advanced ──
    "GALAXY_LOG_DIR": "日志目录",
    # ── security ──
    "GALAXY_LAUNCH_APP_ALLOWLIST": "允许桌面节点启动哪些程序",
    # ── agent ──
    "GALAXY_LOCAL_OPENAI_URL": "本地模型服务地址",
    "GALAXY_LOCAL_OPENAI_MODEL": "本地模型服务用哪个模型",
    "GALAXY_LOCAL_OPENAI_SERVES": "本地模型服务对应的目录型号",
    "GALAXY_LOCAL_OPENAI_KEY": "本地模型服务密钥",
    "GALAXY_REASONING_OPENAI_URL": "推理模型服务地址",
    "GALAXY_REASONING_OPENAI_MODEL": "推理模型服务用哪个模型",
    "GALAXY_REASONING_OPENAI_SERVES": "推理模型服务对应的目录型号",
    "GALAXY_REASONING_OPENAI_KEY": "推理模型服务密钥",
    # ── voice ──
    "GALAXY_AMBIENT_ASR_SIZE": "环境聆听的识别规格",
    # ── perception ──
    "GALAXY_VIDEO_FPS_NATIVE": "原生视频通路的抽帧帧率",
    "GALAXY_VIDEO_FPS_BRIDGE": "抽帧桥接通路的帧率",
    "GALAXY_NATIVE_REALTIME_PATH": "本地全模态的实时通道路径",
    # ── agent ──
    "GALAXY_REALTIME_API_KEY": "全双工语音的密钥",
    "GALAXY_CU_MAX_STEPS": "桌面操作步数上限",
    "GALAXY_CU_SETTLE_S": "每步操作后的静置时长",
    # ── perception ──
    "GALAXY_DESKTOP_PERCEPTION_TTL": "桌面感知帧的保鲜时长",
    "GALAXY_PERCEPTION_KEYFRAMES": "屏幕保留最近几帧",
    "GALAXY_PERCEPTION_PRIVACY_DEFAULT": "启动时的感知状态",
    "GALAXY_PROACTIVE_SCREEN": "屏幕变化也触发主动开口",
    # ── voice ──
    "GALAXY_VOICE_DIAG_S": "麦克风自检的延迟",
    # ── agent ──
    "GALAXY_CHAT_TIMEOUT_S": "单轮对话的总超时",
    # ── voice ──
    "GALAXY_LOCKSTEP_CPS": "同刻时的文字速度",
    "GALAXY_LOCKSTEP_GRACE_S": "同刻时等首个语音块的宽限",
    "GALAXY_LOCKSTEP_STALL_S": "同刻时判定语音掉线的时长",
    "GALAXY_LOCKSTEP_DRAIN_S": "语音念完后文字的收尾时长",
    "GALAXY_ASR_INITIAL_PROMPT": "中文识别的引导语",
    "GALAXY_SENSEVOICE_MODEL": "SenseVoice 模型",
    "GALAXY_EDGE_TTS_TIMEOUT_S": "Edge 在线合成的超时",
    "GALAXY_PIPER_MODEL": "Piper 语音模型",
    "GALAXY_KOKORO_MODEL": "Kokoro 模型文件名",
    "GALAXY_KOKORO_VOICE": "Kokoro 音色",
    "GALAXY_KOKORO_LANG": "Kokoro 发音语种",
    "GALAXY_MELO_LANG": "Melo 语种",
    "GALAXY_MELO_SPEAKER": "Melo 说话人",
    "GALAXY_MELO_SPEED": "Melo 语速倍率",
    "GALAXY_MELO_DEVICE": "Melo 推理设备",
    "GALAXY_INDEXTTS_REF_AUDIO": "IndexTTS 参考音频",
    "GALAXY_INDEXTTS_EMO_AUDIO": "IndexTTS 情绪参考音频",
    "GALAXY_INDEXTTS_EMO_TEXT": "IndexTTS 情绪描述",
    "GALAXY_INDEXTTS_EMO_ALPHA": "IndexTTS 情绪强度",
    "GALAXY_KOKORO_DIR": "Kokoro 模型目录",
    "GALAXY_INDEXTTS_DIR": "IndexTTS-2 模型目录",
    # ── network ──
    "GALAXY_HF_ENDPOINT": "模型下载源地址",
    # ── voice ──
    "GALAXY_VOICE": "启用语音",
    "GALAXY_WHISPER_MODEL": "语音循环的识别规格",
    # ── advanced ──
    "GALAXY_DESKTOP_SHELL": "桌面外壳",
    "GALAXY_AUTO_DOCKER": "自动拉起容器运行时",
    "GALAXY_CONTAINER_RUNTIME": "指定容器运行时",
    "GALAXY_AUTO_DOCKER_DAEMON_WAIT": "等容器守护进程起来的超时",
    "GALAXY_AUTO_DOCKER_WAIT": "等容器内服务就绪的超时",
    "GALAXY_RUNTIME_PROMPT_TIMEOUT": "首启选容器运行时的等待",
    "GALAXY_AUTO_PODMAN_API_WAIT": "等 Podman 接口就绪的超时",
    # ── network ──
    "GALAXY_API_HOST": "节点回连 API 的主机名",
    # ── devices ──
    "GALAXY_NODE_HEALTH_RETRIES": "节点健康检查的重试次数",
    # ── network ──
    "GALAXY_PIP_INDEX": "pip 下载源",
    "GALAXY_HF_MIRROR": "模型下载走国内镜像",
    # ── agent ──
    "GALAXY_OPENSOURCE_FIRST": "开源模型优先",
    "GALAXY_ROUTE_OBSERVED_WEIGHT": "选模型时「实测表现」的权重",
    "GALAXY_ROUTE_LATENCY_WEIGHT": "选模型时「快慢」的权重",
    "GALAXY_ROUTE_TOKEN_WEIGHT": "选模型时「省 token」的权重",
    "GALAXY_CASCADE_FLOOR_MID": "升到中档模型的复杂度门槛",
    "GALAXY_CASCADE_FLOOR_HI": "升到高档模型的复杂度门槛",
    "GALAXY_MODEL_TIER": "强制本地档位",
    "GALAXY_OLLAMA_NUM_CTX": "Ollama 上下文窗口大小",
    # ── memory ──
    "GALAXY_CONTEXT_ARCHIVE_MAX_MB": "上下文归档总量上限",
    "GALAXY_CONTEXT_ARCHIVE_MIN_DAYS": "上下文归档最少保留天数",
    "GALAXY_PHASE_LEDGER_DAYS": "三态转移账保留天数",
    # ── agent ──
    "GALAXY_LLAMA_CTX": "llama.cpp 上下文窗口",
    "GALAXY_OLLAMA_KEEP_ALIVE": "Ollama 模型驻留时长",
    "GALAXY_MOA_ENABLED": "多模型协作",
    "GALAXY_MOA_COMPLEXITY": "触发多模型协作的复杂度门槛",
    "GALAXY_MOA_PROPOSERS": "多模型协作时出方案的模型个数",
    "GALAXY_MOA_LAYERS": "多模型协作的汇总轮数",
    "GALAXY_CRITIC_MAX_ROUNDS": "自我复核的最多轮数",
    "GALAXY_FORCE_COLLAB_MODE": "强制协作方式",
    "GALAXY_PLANNER_MAX_REPLANS": "计划失败后最多重新规划几次",
    "GALAXY_TOOLS_SLIM": "精简工具集",
    "GALAXY_TOOLS_JIT": "按需加载工具",
    "GALAXY_TOOLS_STICKY": "保留上一轮用过的工具",
    "GALAXY_TOOLS_CORE": "常驻工具名单",
    # ── perception ──
    "GALAXY_ACTIVE_PERCEPTION": "主动感知",
    # ── meta ──
    "GALAXY_META_RSI": "自我改进循环",
    # ── agent ──
    "GALAXY_LIMINAL_REHEARSAL": "空闲预演",
    "GALAXY_REHEARSAL_CANDIDATES": "每次预演准备几个候选",
    "GALAXY_REHEARSAL_COMPLEXITY_FLOOR": "值得预演的复杂度下限",
    # ── devices ──
    "GALAXY_ONBOARDING_AUTO": "自动接入到哪一级",
    # ── advanced ──
    "GALAXY_ONBOARDING_SCAN_INTERVAL_S": "发现新设备的轮询间隔",
    "GALAXY_ONBOARDING_CAN_LISTEN_S": "CAN 口静听时长",
    "GALAXY_BLUEZ_DBUS_ADDRESS": "蓝牙服务的系统总线地址",
    "GALAXY_ONBOARDING_STATE_DIR": "设备接入账本目录",
    # ── devices ──
    "HOME_ASSISTANT_URL": "Home Assistant 地址",
    "HOME_ASSISTANT_TOKEN": "Home Assistant 访问令牌",
    # ── voice ──
    "GALAXY_TTS_VOICE": "在线合成的音色名",
    "GALAXY_SPEAK_MAX_CHARS": "单次朗读的字数上限",
    # ── memory ──
    "GALAXY_MEMORY_MEDIA": "保存记忆里的截图和录音",
    "GALAXY_MEMORY_MEDIA_MB": "媒体库容量上限",
    "GALAXY_MEMORY_MEDIA_DIR": "媒体库目录",
    "GALAXY_MEMORY_REPLAY_MEDIA": "召回时附带原截图和录音",
    # ── perception ──
    "GALAXY_NATIVE_AUDIO_CHAT": "把录音原样发给模型",
    # ── security ──
    "GALAXY_HITL_CONFIRM_GATE": "高危命令的额外确认闸",
    "GALAXY_HITL_CONFIRM_TIMEOUT_S": "等你确认的超时",
    "GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S": "高危动作等确认的超时",
    # ── devices ──
    "GALAXY_DEVICE_TOKEN_RETENTION_DAYS": "已吊销的设备凭证保留多少天",
    "GALAXY_DEVICE_TOKEN_MAX_RECORDS": "设备凭证记录总条数上限",
    # ── security ──
    "GALAXY_PEER_DEFAULT_TRUST": "新设备的默认信任级别",
    # ── devices ──
    "GALAXY_LAN_DISCOVERY_TYPES": "要浏览的服务类型",
    "GALAXY_MESH_DISCOVERY_TIMEOUT": "组网发现的等待超时",
    # ── network ──
    "GALAXY_TRANSPORT_BULK_BYTES": "大块传输的分片大小",
    # ── devices ──
    "GALAXY_TS_FUNNEL": "经 Funnel 暴露到公网",
    # ── network ──
    "GALAXY_GATEWAY_MODE": "网关部署模式",
    # ── devices ──
    "GALAXY_SIGNALING_TIMEOUT_S": "WebRTC 信令超时",
    # ── memory ──
    "GALAXY_MEMORY_BACKENDS": "启用的记忆后端",
    "GALAXY_EMBED_MODEL": "文本向量化模型",
    # ── perception ──
    "GALAXY_CLIP_MODEL": "图片记忆的向量模型",
    "GALAXY_CLAP_MODEL": "声音记忆的向量模型",
    # ── memory ──
    "GALAXY_SIMPLEMEM_MODEL": "记忆抽取模型",
    "GALAXY_SIMPLEMEM_BASE_URL": "记忆抽取服务地址",
    "GALAXY_SIMPLEMEM_API_KEY": "记忆抽取服务密钥",
    # ── devices ──
    "GALAXY_REMOTE_DESKTOP": "远程桌面接入",
    "GALAXY_VNC_CMD": "VNC 启动命令",
    "GALAXY_VNC_PORT": "VNC 端口",
    "GALAXY_DEVICE_NAME": "这台设备的显示名",
    "GALAXY_DEVICE_TYPE": "这台设备的类型",
    # ── perception ──
    "GALAXY_CLIP_DIR": "图片记忆库目录",
    "GALAXY_CLAP_DIR": "声音记忆库目录",
    # ── memory ──
    "GALAXY_OMNIMEM_DIR": "SimpleMem 记忆目录",
    # ── advanced ──
    "GALAXY_TASK_LEDGER_PATH": "任务成本账本路径",
    "GALAXY_TASK_ALLOCATION_STATE_PATH": "任务分配真相文件",
    "GALAXY_TASK_GRAPH_STATE_PATH": "任务图状态文件",
    "GALAXY_LAST_OPERATOR_ACTION_STATE_PATH": "面板最近操作记录",
    # ── security ──
    "GALAXY_PEER_TRUST_PATH": "设备信任名单文件",
    # ── advanced ──
    "GALAXY_TAILNET_MEMBERSHIP_PATH": "设备与 tailnet 对账记录",
    # ── devices ──
    "GALAXY_DEVICE_TOKEN_STORE": "设备凭证库位置",
    # ── network ──
    "GALAXY_OTEL_EXPORTER": "链路数据发到哪",
    # ── advanced ──
    "GALAXY_OTEL_SERVICE_NAME": "上报到追踪系统时的服务名",
    "GALAXY_OPS_FAILURE_REASONS_MAX": "失败原因最多留几条",
    "GALAXY_OPS_AUDIT_FAILURE_REASONS_MAX": "审计失败原因最多留几条",
    "GALAXY_OPS_REJECTION_REASONS_MAX": "拒绝原因最多留几条",
    "GALAXY_OPS_FALLBACK_KINDS_MAX": "降级类型最多留几种",
    "GALAXY_PANEL_PUSH_MIN_INTERVAL": "面板推送的最小间隔",
    # ── agent ──
    "GALAXY_MODELS_PROBE_BUDGET": "探测模型可用性的时间预算",
    "GALAXY_MODELS_STATUS_TTL": "模型状态缓存时长",
    # ── llm ──
    "GALAXY_RESPONSES_PROVIDERS": "走 Responses 接口的厂商",
    "NOVITA_API_KEY": "Novita 平台密钥",
    "DEEPSEEK_OCR2_API_BASE": "DeepSeek OCR 接口地址",
    "DEEPSEEK_OCR2_MODEL": "看图识屏用的型号",
    "GEMINI_AUDIO_MODEL": "听声音用的 Gemini 型号",
    "OPENAI_AUDIO_MODEL": "听声音用的 OpenAI 型号",
    # ── devices ──
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL": "WebRTC 数据通道",
    "GALAXY_TURN_URLS": "TURN 中继服务器地址",
    # ── network ──
    "GALAXY_HEADSCALE_URL": "Headscale 控制端地址",
    "GALAXY_HEADSCALE_API_KEY": "Headscale 密钥",
    "GALAXY_HEADSCALE_USER": "Headscale 用户名",
    "GALAXY_TAILSCALE_CHECK_INTERVAL": "Tailscale 状态检查间隔",
    # ── security ──
    "CORS_ALLOWED_ORIGINS": "允许跨域访问的来源",
    "CORS_ALLOWED_METHODS": "允许跨域的 HTTP 方法",
    "CORS_ALLOWED_HEADERS": "允许跨域的请求头",
    # ── advanced ──
    "GALAXY_SLO_LATENCY_WINDOW": "延迟统计窗口",
    "GALAXY_SLO_HEARTBEAT_WINDOW": "心跳统计窗口",
    "GALAXY_RESULT_INGRESS_CONTINUITY_MODE": "结果回流连续性模式",
    "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE": "运行时真相连续性模式",
    # ── devices ──
    "GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S": "主脑扩缩容重评估间隔",
    # ── advanced ──
    "GALAXY_TEMPORAL_URL": "Temporal 工作流地址",
    "GALAXY_GW_ADAPTER_DLQ_SUBJECT": "网关适配器死信队列的主题名",
    # ── network ──
    "GALAXY_STUN_URLS": "STUN 服务器地址",
    "GALAXY_TURN_USERNAME": "TURN 中继用户名",
    "GALAXY_TURN_CREDENTIAL": "TURN 中继凭据",
    "GALAXY_TAILSCALE_HOST": "本机 Tailscale 主机名",
    "GALAXY_TAILSCALE_TAG": "Tailscale 标签",
    "GALAXY_TRANSPORT_PRIORITY": "传输通道的先后顺序",
}

#: 下拉键 → 取值 → 中文名。取值必须和 CONFIG_SCHEMA[key]["options"] 一一对上（测试核对）。
OPTION_LABELS: Dict[str, Dict[str, str]] = {
    "GALAXY_AUTONOMY": {"safe": "敏感操作全问", "guided": "读放行·写审批", "autonomous": "不逐步问人"},
    # ── 注册表里写成 string、但取值其实只有几个的键（auto / 1 / 0 …）：listing 时按下拉画，见 config.py::get_config ──
    "GALAXY_SPECULATIVE_DRAFT": {"auto": "自动", "0": "关"},
    "GALAXY_VOICE_DUPLEX": {"auto": "自动", "1": "强制开", "0": "强制关"},
    "GALAXY_TEXT_VOICE_LOCKSTEP": {"auto": "自动", "1": "强制开", "0": "强制关"},
    "GALAXY_EXECUTION_ISOLATION": {"auto": "自动", "container": "必须用容器", "builtin": "只用内置沙箱"},
    "GALAXY_MCP_PIN_MODE": {"enforce": "变了就拒用", "warn": "只记不拦", "off": "不生效"},
    "GALAXY_EGRESS_MODE": {"audit": "只记账不拦", "enforce": "白名单外一律拒", "off": "不生效"},
    "GALAXY_AUTO_DOCKER": {"auto": "自动", "1": "强制", "0": "关闭"},
    "GALAXY_TOOLS_SLIM": {"auto": "自动", "1": "总是裁", "0": "从不裁"},
    "GALAXY_TOOLS_JIT": {"off": "全部预载", "on": "用到才载"},
    "GALAXY_TOOLS_STICKY": {"auto": "自动", "1": "保留", "0": "不保留"},
    "GALAXY_LIMINAL_REHEARSAL": {"auto": "自动", "1": "强制", "0": "关闭"},
    "GALAXY_SECRET_BACKEND": {"env": "本地加密文件", "vault": "独立保险库", "kms": "云密钥服务"},
    "GALAXY_NATS_EXECUTOR_FALLBACK": {"sync": "退回本机执行", "reject": "直接拒绝"},
    "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE": {"strict": "严格", "advisory": "仅提示", "disabled": "关闭"},
    "GALAXY_MODE": {"standard": "常规", "production": "生产"},
    "GALAXY_PREFLIGHT_MODE": {
        "auto": "自动",
        "all": "全部",
        "core": "核心",
        "gateway": "网关",
        "android": "安卓",
        "ws": "实时通道",
        "vault": "保险库",
    },
    "GALAXY_TTS_ENGINE": {"edge": "Edge（联网）", "melo": "Melo（离线）", "piper": "Piper（离线轻量）", "auto": "自动"},
    "GALAXY_ASR_ENGINE": {"auto": "自动", "sensevoice": "SenseVoice（离线中文）", "whisper": "Whisper（兜底）"},
    "GALAXY_VOICE_EAGERNESS": {"low": "耐心等", "auto": "自动", "high": "抢答"},
    "GALAXY_REALTIME_PROVIDER": {
        "openai_realtime": "OpenAI 实时",
        "gemini_live": "Gemini Live",
        "step_realtime": "阶跃实时",
    },
    "GALAXY_COMPUTER_USE_STRATEGY": {"step": "一次一步", "script": "一次一小段脚本"},
    "GALAXY_PERCEPTION_PRIVACY_DEFAULT": {"active": "正常采集", "paused": "启动即暂停"},
    "GALAXY_DESKTOP_SHELL": {"": "自动", "electron": "Electron"},
    "GALAXY_CONTAINER_RUNTIME": {"": "首次启动时问我", "docker": "Docker", "podman": "Podman"},
    "GALAXY_MODEL_TIER": {
        "": "自动",
        "A": "A 轻量本地",
        "B": "B 全模态单模型",
        "C": "C 双模型·35B",
        "D": "D 双模型·9B",
    },
    "GALAXY_META_RSI": {"off": "关", "shadow": "只在隔离区验证", "on": "开"},
    "GALAXY_ONBOARDING_AUTO": {"off": "全部等我确认", "none": "只自动接无需确认的", "approve": "连「同意」也自动"},
    "GALAXY_PEER_DEFAULT_TRUST": {"ask": "每次问我", "trusted": "直接放行", "blocked": "直接拒绝"},
    "GALAXY_OTEL_EXPORTER": {"": "不外发", "otlp": "发到采集器", "console": "打印到屏幕"},
    "GALAXY_RESULT_INGRESS_CONTINUITY_MODE": {"strict": "严格", "best-effort": "尽力而为", "disabled": "关闭"},
    "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE": {"strict": "严格", "best-effort": "尽力而为", "disabled": "关闭"},
}

#: 下拉键的说明：描述里原本枚举的是原始取值（``env=`` / ``strict=``），档位牌已是中文，这里用中文名重写一遍。
HINTS: Dict[str, str] = {
    "GALAXY_SPECULATIVE_DRAFT": "自动＝只在实测更快的机器上才开；关＝一律不用。开不开由 scripts/probe_models.py --draft 的真机 A/B 决定。",
    "GALAXY_VOICE_DUPLEX": "自动＝本机档位具备就自动开（云端实时语音按分钟计费）；强制开；强制关。默认自动。",
    "GALAXY_TEXT_VOICE_LOCKSTEP": "自动＝有语音时自动同刻；强制开；强制关。默认自动。",
    "GALAXY_EXECUTION_ISOLATION": (
        "自动＝有 Docker/Podman 就跑进容器，否则退回内置轻量沙箱；必须用容器＝没有容器边界就拒绝执行；"
        "只用内置沙箱＝强制内置。内置沙箱与主程序同一内核、同一用户，只挡得住手滑，挡不住一次不走运的代码生成。"
    ),
    "GALAXY_MCP_PIN_MODE": (
        "MCP 服务器的工具清单变了怎么办。变了就拒用（默认）；只记不拦；不生效。"
        "第一次见到的服务器按「首次信任」记下 —— 挡得住后来被改，挡不住一开始就是坏的。"
    ),
    "GALAXY_EGRESS_MODE": (
        "对外连接怎么管。只记账不拦（默认）；白名单外一律拒；不生效。"
        "只记账不提供保护，只提供可见性 —— 别把它当成已防护。"
    ),
    "GALAXY_AUTO_DOCKER": "自动＝装了就用；强制；关闭。默认自动。",
    "GALAXY_TOOLS_SLIM": "自动＝按上下文压力自动裁；总是裁；从不裁。默认自动。",
    "GALAXY_TOOLS_JIT": "全部预载＝一次发全；用到才载＝省上下文，但多一次往返。默认全部预载。",
    "GALAXY_TOOLS_STICKY": "自动＝已选本地主脑时保留，否则按相关性挑；保留；不保留。默认自动。",
    "GALAXY_LIMINAL_REHEARSAL": (
        "闲时提前想可能被问到的事。自动＝按复杂度门槛、且有工具可调才做；强制＝凡有工具就做"
        "（时机已过时仍不做）；关闭。默认自动。"
    ),
    "GALAXY_SECRET_BACKEND": "密钥放在哪里保管。默认本地加密文件。",
    "GALAXY_NATS_EXECUTOR_FALLBACK": "消息总线连不上时，任务是退回本机做，还是直接拒绝。默认退回本机执行。",
    "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE": "派发任务时是否只认规范来源。严格＝不接受旁路；默认严格。",
    "GALAXY_MODE": "常规是默认。生产会强制开启鉴权，并要求 API 访问令牌至少 32 位，否则启动失败。",
    "GALAXY_PREFLIGHT_MODE": "手动运行配置预检（python -m core.config_preflight）时检查哪一组。默认全部。",
    "GALAXY_TTS_ENGINE": "朗读用哪个引擎。Edge 联网、音质好；Melo 离线、中英混读自然；Piper 离线、最轻；自动＝优先 Edge，不行退 Melo，再退 Piper。",
    "GALAXY_ASR_ENGINE": "听写用哪个引擎。自动＝中文 CPU 首选 SenseVoice，不行退 Whisper；SenseVoice 离线、中文又快又准；Whisper 兜底。",
    "GALAXY_VOICE_EAGERNESS": "按你说话的内容判断这一轮是否说完。耐心等＝等你想完；抢答＝尽快接话。",
    "GALAXY_REALTIME_PROVIDER": "全双工语音用哪家的实时服务（只在全双工开启时生效）。",
    "GALAXY_COMPUTER_USE_STRATEGY": "一次一步＝一次一个动作（默认）；一次一小段脚本＝一次写一小段受限脚本，适合「连点七个开关」这类中间无需重新判断的连续操作。",
    "GALAXY_PERCEPTION_PRIVACY_DEFAULT": "启动时感知处于什么状态。启动即暂停＝什么都不采，要你手动恢复。默认正常采集。",
    "GALAXY_DESKTOP_SHELL": "自动＝自动挑选；Electron＝强制用 Electron，而不是 Tauri。",
    "GALAXY_CONTAINER_RUNTIME": "用哪个容器运行时。留空＝两者都装时首次启动让你选；也可以直接钉死 Docker 或 Podman。",
    "GALAXY_MODEL_TIER": (
        "强制本地模型档位，自动＝按本机能力判断。A＝轻量本地（Gemma 4 系，无独显也能跑）；"
        "B＝全模态单模型（MiniCPM-o，需显卡）；C＝双模型，35B 推理；D＝双模型，9B 推理。"
    ),
    "GALAXY_META_RSI": "关＝不跑；只在隔离区验证＝永不生效；开＝运行时，通过验证的补丁直接生效。默认关。",
    "GALAXY_ONBOARDING_AUTO": "新设备接入时自动做到哪一级。全部等我确认；只自动接无需确认的；连「同意」类也自动（配网码、设备上确认、执行命令永远要人）。",
    "GALAXY_PEER_DEFAULT_TRUST": "新设备第一次出现时怎么处理：每次问我、直接放行、直接拒绝。默认每次问我。",
    "GALAXY_OTEL_EXPORTER": "链路追踪数据发到哪。不外发＝只在进程内产生；发到采集器（OTLP）；打印到屏幕＝调试用。",
    "GALAXY_RESULT_INGRESS_CONTINUITY_MODE": "结果回流链路断了怎么办。严格＝断了就报，不静默补；默认严格。",
    "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE": "运行时真相链路断了怎么办。严格＝断了就报；默认严格。",
}

# 名字后面能接说明的分隔符。中文名是按这些符号从描述开头截出来的，所以「名字」之后要么结束、要么就是它们。
_AFTER_NAME = "（(：:，,。;；·—= "
_OPEN_TO_CLOSE = {"（": "）", "(": ")"}


def _unwrap(rest: str) -> str:
    """「（补充说明）后面还有话」→「补充说明；后面还有话」。括号按配对找，里面有嵌套括号也不会截断。"""
    close = _OPEN_TO_CLOSE.get(rest[:1])
    if not close:
        return rest.lstrip("，,：:。;；·—= ").strip()
    depth = 0
    for i, ch in enumerate(rest):
        if ch in _OPEN_TO_CLOSE:
            depth += 1
        elif ch in _OPEN_TO_CLOSE.values():
            depth -= 1
            if depth == 0:
                inner = rest[1:i].strip()
                tail = rest[i + 1 :].strip().lstrip("，,：:。;；·—= ").strip()
                return "；".join(x for x in (inner, tail) if x)
    return rest[1:].strip()  # 括号没配上：宁可保留原文，也不吞字


def hint_for(key: str, description: str) -> str:
    """行里名字下面那一句。有手写的用手写的；否则把描述开头与中文名重复的那一段去掉。"""
    if key in HINTS:
        return HINTS[key]
    text = (description or "").strip()
    name = LABELS.get(key, "")
    if name and text.startswith(name) and (len(text) == len(name) or text[len(name)] in _AFTER_NAME):
        return _unwrap(text[len(name) :].lstrip())
    return text


def label_for(key: str) -> str:
    """键的中文名；没登记就返回空串（调用方回落到键名本身，不要在这里编一个）。"""
    return LABELS.get(key, "")


def option_labels_for(key: str) -> Dict[str, str]:
    """下拉键的 取值 → 中文名；没有则空 dict。返回副本，调用方随便改。"""
    return dict(OPTION_LABELS.get(key, {}))
