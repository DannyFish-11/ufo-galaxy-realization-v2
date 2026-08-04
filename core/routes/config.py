"""
Galaxy Configuration API
提供系统配置的全量读取和批量更新，持久化到 .env 文件。
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("Galaxy.API.Config")

router = APIRouter(prefix="/api/config", tags=["config"])

# .env 文件路径
ENV_FILE = Path(__file__).parent.parent.parent / ".env"

# 所有支持的配置项（键 → {默认值, 类型, 类别, 描述}）
CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    # --- LLM Providers (API Keys) ---
    "OPENAI_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "OpenAI API Key"},
    "ANTHROPIC_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Anthropic API Key"},
    "DEEPSEEK_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "DeepSeek API Key"},
    "GOOGLE_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Google API Key"},
    "GEMINI_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Gemini API Key (alias)"},
    "XAI_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "xAI API Key"},
    "META_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Meta Model API Key (Muse Spark)",
    },
    "MISTRAL_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Mistral API Key"},
    "AGNES_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "Agnes AI API Key(全模态免费)",
    },
    "QWEN_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Qwen API Key"},
    "DASHSCOPE_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "DashScope API Key (alias)",
    },
    "ZHIPU_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Zhipu API Key"},
    "GROQ_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Groq API Key"},
    "HF_API_TOKEN": {"default": "", "type": "string", "category": "llm", "description": "HuggingFace API Token"},
    "MOONSHOT_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Moonshot API Key"},
    "MIMO_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Mimo API Key"},
    "MINIMAX_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "MiniMax API Key"},
    "PERPLEXITY_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Perplexity API Key"},
    "STEP_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "StepFun API Key"},
    "ONEAPI_URL": {"default": "", "type": "url", "category": "llm", "description": "OneAPI Base URL"},
    "ONEAPI_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "OneAPI Key"},
    "OPENROUTER_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "OpenRouter API Key"},
    "DEEPSEEK_OCR2_API_KEY": {
        "default": "",
        "type": "string",
        "category": "llm",
        "description": "DeepSeek OCR API Key",
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
        "description": "Perplexity Sonar API Key (alias)",
    },
    "VLLM_URL": {"default": "", "type": "url", "category": "llm", "description": "vLLM URL (alias)"},
    "LOCAL_VLLM_URL": {"default": "", "type": "url", "category": "llm", "description": "Local vLLM URL"},
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
    "GATEWAY_PORT": {"default": "9000", "type": "number", "category": "ports", "description": "Galaxy Gateway Port"},
    "UFO_NODE_HOST": {"default": "localhost", "type": "string", "category": "ports", "description": "Node Host"},
    "NODE_92_URL": {
        "default": "http://localhost:8092",
        "type": "url",
        "category": "ports",
        "description": "Device Control Service",
    },
    "NODE_45_URL": {
        "default": "http://localhost:8045",
        "type": "url",
        "category": "ports",
        "description": "Desktop Endpoint",
    },
    "NODE_33_URL": {
        "default": "http://localhost:8033",
        "type": "url",
        "category": "ports",
        "description": "ADB Control",
    },
    "NODE_71_URL": {
        "default": "http://localhost:8071",
        "type": "url",
        "category": "ports",
        "description": "Multi-Device Orchestration",
    },
    "NODE_71_HOST": {"default": "localhost", "type": "string", "category": "ports", "description": "Node 71 Host"},
    "NODE_95_URL": {
        "default": "http://localhost:8095",
        "type": "url",
        "category": "ports",
        "description": "Vision Sampler",
    },
    "NODE_97_URL": {
        "default": "http://localhost:8097",
        "type": "url",
        "category": "ports",
        "description": "Academic Retrieval",
    },
    "NODE09_SANDBOX_URL": {"default": "", "type": "url", "category": "ports", "description": "Code Sandbox"},
    "OLLAMA_URL": {"default": "", "type": "url", "category": "ports", "description": "Ollama URL"},
    "QDRANT_URL": {"default": "", "type": "url", "category": "ports", "description": "Qdrant Vector DB"},
    "REDIS_URL": {"default": "", "type": "url", "category": "ports", "description": "Redis URL"},
    "SECRETVAULT_URL": {"default": "", "type": "url", "category": "ports", "description": "Secret Vault"},
    "MAIN_REPO_URL": {
        "default": "http://localhost:8080",
        "type": "url",
        "category": "ports",
        "description": "Main Repo URL",
    },
    "MQTT_PORT": {"default": "", "type": "number", "category": "ports", "description": "MQTT Broker Port"},
    # --- Authentication & Security ---
    "GALAXY_AUTH_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "auth",
        "description": "Enable Authentication",
    },
    "GALAXY_API_TOKEN": {"default": "", "type": "string", "category": "auth", "description": "API Token (single)"},
    "GALAXY_API_TOKENS": {
        "default": "",
        "type": "string",
        "category": "auth",
        "description": "API Tokens (comma-separated)",
    },
    "GALAXY_API_TOKEN_EXPIRY": {"default": "", "type": "string", "category": "auth", "description": "Token Expiry"},
    "GALAXY_REVOKED_TOKENS": {"default": "", "type": "string", "category": "auth", "description": "Revoked Tokens"},
    "GALAXY_REQUIRE_API_TOKEN": {
        "default": "false",
        "type": "boolean",
        "category": "auth",
        "description": "Require API Token",
    },
    "GALAXY_STRICT_AUTHORITY_CHECK": {
        "default": "false",
        "type": "boolean",
        "category": "auth",
        "description": "Strict Authority Check",
    },
    "GALAXY_SECRET_BACKEND": {
        "default": "env",
        "type": "select",
        "category": "auth",
        "description": "Secret Backend",
        "options": ["env", "vault", "kms"],
    },
    "GALAXY_TLS_CERT": {"default": "", "type": "string", "category": "auth", "description": "TLS Certificate Path"},
    "GITHUB_TOKEN": {"default": "", "type": "string", "category": "auth", "description": "GitHub Token"},
    # 融合(域6):删掉两个幽灵开关 GALAXY_AUDIT_KEY / GALAXY_MESSAGE_SIGNING_KEY——
    # 全仓无任何代码读它们(面板上摆着没实现的安全功能,误导操作者)。消息签名
    # 【真实已实现】,但键名是 GALAXY_MESH_SECRET(capability_token HMAC 签名/校验,
    # 缺省自动生成 .galaxy_mesh_key),把真的这只上面板。
    "GALAXY_MESH_SECRET": {
        "default": "",
        "type": "string",
        "category": "auth",
        "description": "Mesh 签名密钥(能力令牌 HMAC;留空自动生成)",
    },
    # --- Mesh & NATS ---
    "GALAXY_MDNS": {
        "default": "true",
        "type": "boolean",
        "category": "mesh",
        "description": "局域网零配置发现(mDNS · 手机/手表免输 IP 自动发现网关)",
    },
    # 这三条的说明原先只有一句英文,面板上照原样显示,中文用户看不懂开了会发生什么。
    # 是这一轮把守卫范围扩到 launcher/ 之后,启动器读到它们才连带扫出来的。
    "GALAXY_NATS_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "mesh",
        "description": "启用 NATS 消息总线（多设备协同的传输底座;单机自用可以关 · 默认开）",
    },
    "GALAXY_NATS_URL": {
        "default": "nats://localhost:4222",
        "type": "url",
        "category": "mesh",
        "description": "NATS 消息总线的地址（默认本机;接到别的机器上才需要改）",
    },
    "GALAXY_NATS_EXECUTOR_TIMEOUT": {
        "default": "30",
        "type": "number",
        "category": "mesh",
        "description": "NATS Executor Timeout (s)",
    },
    "GALAXY_NATS_EXECUTOR_FALLBACK": {
        "default": "sync",
        "type": "select",
        "category": "mesh",
        "description": "Executor Fallback Mode",
        "options": ["sync", "async", "reject"],
    },
    "GALAXY_CROSS_DEVICE_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "mesh",
        "description": "跨设备编排（让手机/手表/别的电脑也能承接任务;关掉则只在本机跑 · 默认开）",
    },
    "GALAXY_MASTER_BRAIN_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "mesh",
        "description": "启用主脑编排 + worker/NATS 分布式(多设备总开关 · 默认关=单机)",
    },
    "GALAXY_FABRIC_STRICT": {
        "default": "false",
        "type": "boolean",
        "category": "mesh",
        "description": "严格织网:NATS 不可达即视为致命(默认关=优雅降级单机)",
    },
    "GALAXY_HEARTBEAT_INTERVAL": {
        "default": "5",
        "type": "number",
        "category": "mesh",
        "description": "Heartbeat Interval (s)",
    },
    "FEDERATION_ENABLED": {
        "default": "false",
        "type": "boolean",
        "category": "mesh",
        "description": "Enable Federation",
    },
    "FEDERATION_LOCAL_HOST": {
        "default": "",
        "type": "string",
        "category": "mesh",
        "description": "Federation Local Host",
    },
    "FEDERATION_PEERS": {
        "default": "",
        "type": "string",
        "category": "mesh",
        "description": "Federation Peers (comma-separated)",
    },
    "FEDERATION_HEARTBEAT_INTERVAL": {
        "default": "10",
        "type": "number",
        "category": "mesh",
        "description": "Federation Heartbeat (s)",
    },
    "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE": {
        "default": "strict",
        "type": "select",
        "category": "mesh",
        "description": "Dispatch Authority Mode",
        "options": ["strict", "advisory", "disabled"],
    },
    # --- Circuit Breaker & Adaptive ---
    "GALAXY_ROUTER_ADAPTIVE_CONCURRENCY": {
        "default": "true",
        "type": "boolean",
        "category": "circuit",
        "description": "Adaptive Concurrency",
    },
    "GALAXY_ROUTER_CB_ENABLED": {
        "default": "true",
        "type": "boolean",
        "category": "circuit",
        "description": "Circuit Breaker",
    },
    "GALAXY_ROUTER_MAX_QUEUE_DEPTH": {
        "default": "1000",
        "type": "number",
        "category": "circuit",
        "description": "Max Queue Depth",
    },
    "GALAXY_CB_FAILURE_THRESHOLD": {
        "default": "5",
        "type": "number",
        "category": "circuit",
        "description": "CB Failure Threshold",
    },
    "GALAXY_CB_RECOVERY_TIMEOUT_S": {
        "default": "30",
        "type": "number",
        "category": "circuit",
        "description": "CB Recovery Timeout (s)",
    },
    "GALAXY_CB_HALF_OPEN_PROBES": {
        "default": "3",
        "type": "number",
        "category": "circuit",
        "description": "CB Half-Open Probes",
    },
    "GALAXY_CB_WINDOW_SIZE": {
        "default": "60",
        "type": "number",
        "category": "circuit",
        "description": "CB Window Size (s)",
    },
    "GALAXY_AS_TARGET_LATENCY_MS": {
        "default": "2000",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Target Latency (ms)",
    },
    "GALAXY_AS_ERROR_THRESHOLD": {
        "default": "0.1",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Error Threshold",
    },
    "GALAXY_AS_INIT_LIMIT": {
        "default": "10",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Init Limit",
    },
    "GALAXY_AS_MAX_LIMIT": {
        "default": "200",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Max Limit",
    },
    "GALAXY_AS_MIN_LIMIT": {
        "default": "1",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Min Limit",
    },
    "GALAXY_AS_SAMPLE_WINDOW": {
        "default": "60",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Sample Window (s)",
    },
    "GALAXY_AS_PROBE_INTERVAL_S": {
        "default": "5",
        "type": "number",
        "category": "circuit",
        "description": "Adaptive Probe Interval (s)",
    },
    # --- Storage ---
    "GALAXY_DATA_DIR": {"default": "./data", "type": "string", "category": "storage", "description": "Data Directory"},
    "GALAXY_MARKET_STORE_DIR": {
        "default": "./market",
        "type": "string",
        "category": "storage",
        "description": "Market Store Dir",
    },
    "GALAXY_FEATURE_FLAGS_PATH": {
        "default": "",
        "type": "string",
        "category": "storage",
        "description": "Feature Flags Path",
    },
    "GALAXY_MASTER_BRAIN_STATE_PATH": {
        "default": "",
        "type": "string",
        "category": "storage",
        "description": "Master Brain State Path",
    },
    "CHROMA_PERSIST_DIR": {
        "default": "./chroma",
        "type": "string",
        "category": "storage",
        "description": "Chroma Persist Dir",
    },
    "ANDROID_DEVICE_STATE_STORE_PATH": {
        "default": "",
        "type": "string",
        "category": "storage",
        "description": "Android State Store",
    },
    "ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS": {
        "default": "300",
        "type": "number",
        "category": "storage",
        "description": "Android Snapshot TTL (s)",
    },
    # --- Development ---
    "GALAXY_DEV_MODE": {"default": "false", "type": "boolean", "category": "dev", "description": "Developer Mode"},
    "GALAXY_MODE": {
        "default": "standard",
        "type": "select",
        "category": "dev",
        "description": "Run Mode",
        "options": ["standard", "distributed", "federated", "standalone"],
    },
    "GALAXY_SYSTEM_MODE": {
        "default": "desktop-local",
        "type": "select",
        "category": "mesh",
        "description": "运行模式（desktop-local=单机 · desktop-cross-device=跨设备织网）",
        "options": ["desktop-local", "desktop-cross-device"],
    },
    "GALAXY_PREFLIGHT_MODE": {
        "default": "normal",
        "type": "select",
        "category": "dev",
        "description": "Preflight Mode",
        "options": ["normal", "strict", "skip"],
    },
    "GALAXY_PREFLIGHT_FAIL_FAST": {
        "default": "false",
        "type": "boolean",
        "category": "dev",
        "description": "Preflight Fail-Fast",
    },
    "GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK": {
        "default": "false",
        "type": "boolean",
        "category": "dev",
        "description": "Legacy Scheduler Fallback",
    },
    "GALAXY_ENTRYMODE_USE_READINESS": {
        "default": "true",
        "type": "boolean",
        "category": "dev",
        "description": "Use Readiness Check",
    },
    "CMD_MAX_CONCURRENT": {
        "default": "50",
        "type": "number",
        "category": "dev",
        "description": "Max Concurrent Commands",
    },
    "CONCURRENCY_GLOBAL_MAX": {
        "default": "100",
        "type": "number",
        "category": "dev",
        "description": "Global Concurrency Max",
    },
    "GALAXY_MAX_CONTEXT_TOKENS": {
        "default": "100000",
        "type": "number",
        "category": "dev",
        "description": "Max Context Tokens",
    },
    "GALAXY_MAX_MESSAGE_SIZE": {
        "default": "10485760",
        "type": "number",
        "category": "dev",
        "description": "Max Message Size (bytes)",
    },
    # --- 行为 / 在场 (面板"行为"区直接开关，无需改环境变量) ---
    # 这些是面向用户的行为开关，面板上以明确的开关呈现:说/流式/自发在场/原生音频。
    "GALAXY_AUTONOMY": {
        "default": "guided",
        "type": "select",
        "category": "behavior",
        "description": "自治档位（safe=敏感操作全问 · guided=读放行写审批 · autonomous=不逐步问人）",
        "options": ["safe", "guided", "autonomous"],
    },
    "GALAXY_SPEAK": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "朗读回复（说 · 默认开）",
    },
    "GALAXY_TTS_ENGINE": {
        "default": "edge",
        "type": "select",
        "category": "behavior",
        "description": "说·语音引擎（edge=联网音质好 · melo=离线中英混读自然 · piper=离线最轻 · auto=优先edge退melo退piper）",
        "options": ["edge", "melo", "piper", "auto"],
    },
    "GALAXY_ASR_ENGINE": {
        "default": "auto",
        "type": "select",
        "category": "behavior",
        "description": "听·识别引擎（auto=中文CPU首选SenseVoice退Whisper · sensevoice=离线中文快而准 · whisper=兜底）",
        "options": ["auto", "sensevoice", "whisper"],
    },
    "GALAXY_VOICE_EAGERNESS": {
        "default": "auto",
        "type": "select",
        "category": "behavior",
        "description": "接话急切度（low=耐心等你想 · auto · high=抢答）——按说话内容判断回合是否结束",
        "options": ["low", "auto", "high"],
    },
    "GALAXY_VOICE_DELEGATE": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "语音委托模式（重活先口头致谢、后台跑,对话不被堵死 · 默认开）",
    },
    "GALAXY_VOICE_BACKCHANNEL": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "后台干活时的短应答（嗯,还在处理 · 默认开）",
    },
    "GALAXY_TTS_STREAMING": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "分句流式朗读（边生成边说 · 默认开）",
    },
    "GALAXY_AMBIENT_LOOP": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "自发在场（持续看/听、自己判断何时开口 · 默认开 · 需桌面感知授权）",
    },
    "GALAXY_NATIVE_AUDIO": {
        "default": "false",
        "type": "boolean",
        "category": "behavior",
        "description": "原生音频输入（模型直接听音频，需全模态服务；关则走 ASR 转文字）",
    },
    "GALAXY_AMBIENT_INTERVAL_S": {
        "default": "2.0",
        "type": "number",
        "category": "behavior",
        "description": "自发在场节拍(秒)",
    },
    "GALAXY_AMBIENT_COOLDOWN_S": {
        "default": "20.0",
        "type": "number",
        "category": "behavior",
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
        "category": "behavior",
        "description": "回声消除（把喇叭放出去的声音从麦克风里减掉,防止 AI 听见自己说话 · 默认开）",
    },
    "GALAXY_VOICE_ECHO_GUARD": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "自回声文字闸门（识别结果与刚念过的话高度重合时判为自己的回声、不当用户输入 · 默认开）",
    },
    "GALAXY_VOICE_BACKCHANNEL_TOLERANCE": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "应答不打断（用户只是嗯/对/好时继续说,只有真插话才停 · 关则一出词就打断 · 默认开）",
    },
    "GALAXY_SYSTEM_AUDIO_CAPTURE": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "采集本机播放声（回声消除的参考信号来源,也让 AI 能听见电脑在放什么 · 默认开）",
    },
    "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "把本机播放声送进感知（关掉则只用于回声消除、不进模型 · 默认开）",
    },
    # 三态:不设=按当前档位的**真实供给**自动判定(本机原生与云端一视同仁);
    # 1=强制开;0=强制关。写成 boolean/false 是**假的** —— 面板会显示"关"而实际
    # 已自动开启,那正是这条守卫要防的事。
    "GALAXY_VOICE_DUPLEX": {
        "default": "auto",
        "type": "string",
        "category": "behavior",
        "description": "全双工语音（auto=档位具备就自动开,云端 realtime 按分钟计费 / 1=强制开 / 0=强制关 · 默认 auto）",
    },
    # 残余回声抑制(RES/NLP):线性对消之后的第二级,专治扬声器削波/外壳振动带来的
    # **非线性**回声 —— 那部分线性滤波器原理上消不掉。实测非线性路径上多消约 10 dB。
    "GALAXY_AEC_RES": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "残余回声抑制（线性对消之后再压一层非线性残余 · 默认开）",
    },
    "GALAXY_AEC_RES_OVER": {
        "default": "1.5",
        "type": "number",
        "category": "behavior",
        "description": "残余抑制过减因子（越大压得越狠,代价是近端语音也多削一点 · 默认 1.5）",
    },
    "GALAXY_AEC_RES_FLOOR_DB": {
        "default": "-18",
        "type": "number",
        "category": "behavior",
        "description": "远端单讲时的抑制下限 dB（压到底会是一段死寂,反而难受 · 默认 -18）",
    },
    "GALAXY_AEC_RES_DT_FLOOR_DB": {
        "default": "-3",
        "type": "number",
        "category": "behavior",
        "description": "双讲时的抑制下限 dB（用户正在说话,必须比单讲宽松 · 默认 -3）",
    },
    "GALAXY_AEC_DTD_HANGOVER": {
        "default": "12",
        "type": "number",
        "category": "behavior",
        "description": "双讲检出后继续按双讲处理多少块（真实双讲连续,能量判据只抓得住峰 · 默认 12）",
    },
    "GALAXY_AEC_COMFORT_NOISE": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "舒适噪声（把被压掉的部分填回极低底噪,消除呼吸感 · 默认开）",
    },
    "GALAXY_TEXT_VOICE_LOCKSTEP": {
        "default": "auto",
        "type": "string",
        "category": "behavior",
        "description": "文字与语音同刻（auto=有语音时自动同刻 / 1=强制开 / 0=强制关 · 默认 auto）",
    },
    "GALAXY_VOICE_DUCKING": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "用户开口先压低音量而不是立刻掐断（等听清是应答还是真打断再决定 · 默认开）",
    },
    # 以下为细调参数:默认值已经是实测调过的,一般不需要动。
    "GALAXY_VOICE_DUCK_GAIN": {
        "default": "0.25",
        "type": "number",
        "category": "behavior",
        "description": "压低音量时的音量倍数(0~1,0.25≈−12dB:明显压下去但仍听得见)",
    },
    "GALAXY_VOICE_HOLD_S": {
        "default": "90.0",
        "type": "number",
        "category": "behavior",
        "description": "用户说“等一下/让我想想”后的静候时长(秒)",
    },
    "GALAXY_VOICE_ECHO_SIM": {
        "default": "0.62",
        "type": "number",
        "category": "behavior",
        "description": "自回声判定的重合度阈值(0~1,调高=更少误判成回声、更容易漏掉回声)",
    },
    "GALAXY_VOICE_ECHO_TAIL_S": {
        "default": "6.0",
        "type": "number",
        "category": "behavior",
        "description": "念完后仍防自回声的拖尾时长(秒)",
    },
    "GALAXY_VOICE_ECHO_MIN_CHARS": {
        "default": "4",
        "type": "number",
        "category": "behavior",
        "description": "短于这个字数的识别结果不做自回声判定(太短判不准)",
    },
    "GALAXY_VOICE_ECHO_MIN_BLOCK": {
        "default": "4",
        "type": "number",
        "category": "behavior",
        "description": "自回声判定要求的最短连续重合字数(防止零散字符碰巧凑出高重合度)",
    },
    "GALAXY_AEC_TAIL_MS": {
        "default": "128.0",
        "type": "number",
        "category": "behavior",
        "description": "回声消除的滤波器长度(毫秒,覆盖房间混响拖尾;房间空旷可调大)",
    },
    "GALAXY_AEC_MU": {
        "default": "0.35",
        "type": "number",
        "category": "behavior",
        "description": "回声消除的收敛步长(大=收敛快但易失稳,小=稳但慢)",
    },
    "GALAXY_AEC_MAX_DELAY_MS": {
        "default": "400.0",
        "type": "number",
        "category": "behavior",
        "description": "喇叭到麦克风的最大补偿延迟(毫秒)",
    },
    "GALAXY_AEC_DTD_MARGIN_DB": {
        "default": "6.0",
        "type": "number",
        "category": "behavior",
        "description": "双讲检测余量(dB,调高=更不容易把用户说话误判成回声)",
    },
    "GALAXY_REALTIME_PROVIDER": {
        "default": "openai_realtime",
        "type": "select",
        "category": "behavior",
        "description": "全双工语音的 provider（仅在全双工开启时生效）",
        "options": ["openai_realtime", "gemini_live"],
    },
    "GALAXY_REALTIME_MODEL": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "全双工语音的模型名(留空=按 provider 取默认)",
    },
    "GALAXY_REALTIME_VOICE": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "全双工语音的音色(留空=按 provider 取默认)",
    },
    "GALAXY_REALTIME_URL": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "全双工语音的 WebSocket 地址(留空=按 provider 自动组装;走聚合器时才需手填)",
    },
    # ── B 档本地全模态 server(core/native_modal.py)────────────────────────────
    # 这三项此前**两边都没登记**:功能在跑,但用户只能手改 .env —— 与之前那 21 个语音
    # 开关是同一类缺口。漏掉的原因是面板守卫测试的模块清单里没有 native_modal.py /
    # modality_bridge.py(已一并补进去)。
    "GALAXY_MINICPM_SERVER_URL": {
        "default": "http://localhost:32550",
        "type": "string",
        "category": "behavior",
        "description": (
            "B 档 MiniCPM-o 官方 server 的地址。原生听/说与双工的本地 realtime 地址都由它推导;"
            "可以不带 scheme(localhost:32550 也认)"
        ),
    },
    "GALAXY_NATIVE_MODAL_AUTO": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": ("切到 B 档时自动激活原生后端(后台补装客户端依赖 + 探测 server)。" "关掉则只能手动激活"),
    },
    "GALAXY_AMBIENT_ASR_SIZE": {
        "default": "base",
        "type": "string",
        "category": "behavior",
        "description": "环境聆听转写用的 Whisper 模型规格(tiny/base/small/medium/large)",
    },
    "GALAXY_VIDEO_FPS_NATIVE": {
        "default": "4.0",
        "type": "string",
        "category": "behavior",
        "description": "原生视频通路的抽帧帧率(模型原生吃连续视频时用,默认 4 fps)",
    },
    "GALAXY_VIDEO_FPS_BRIDGE": {
        "default": "1.0",
        "type": "string",
        "category": "behavior",
        "description": "抽帧桥接通路的帧率(模型不吃连续视频、只能喂稀疏图片时用,默认 1 fps)",
    },
    "GALAXY_NATIVE_REALTIME_PATH": {
        "default": "/v1/realtime",
        "type": "string",
        "category": "behavior",
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
        "category": "behavior",
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
        "category": "behavior",
        "description": "桌面操作闭环（让 AI 看屏幕、自己点鼠标敲键盘完成任务 · 默认开）",
    },
    "GALAXY_CU_MAX_STEPS": {
        "default": "15",
        "type": "number",
        "category": "behavior",
        "description": "桌面操作单次任务的步数上限（1~50,防止无限点下去 · 默认 15）",
    },
    "GALAXY_CU_SETTLE_S": {
        "default": "1.0",
        "type": "number",
        "category": "behavior",
        "description": "每步操作后等界面反应的静置时长(秒,0~10 · 默认 1)",
    },
    # --- 连续感知(core/perception/、core/multimodal/)---
    "GALAXY_DESKTOP_PERCEPTION_TTL": {
        "default": "10",
        "type": "number",
        "category": "behavior",
        "description": "桌面感知帧的保鲜时长(秒,超过就算过期不再当作当前画面 · 默认 10)",
    },
    "GALAXY_PERCEPTION_PRIVACY_DEFAULT": {
        "default": "active",
        "type": "select",
        "category": "behavior",
        "description": "启动时的感知状态（active=正常采集 / paused=启动即隐私暂停,什么都不采 · 默认 active）",
        "options": ["active", "paused"],
    },
    "GALAXY_PROACTIVE_SCREEN": {
        "default": "false",
        "type": "boolean",
        "category": "behavior",
        "description": "屏幕变化也触发主动开口（屏幕一直在变,开了会话多 · 默认关,只由声音/画面触发）",
    },
    "GALAXY_AMBIENT_SHARE_SESSION": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "主动开口续在当前对话主线上（关掉则另起一条独立会话,不打断你正在聊的 · 默认开）",
    },
    "GALAXY_VOICE_DIAG_S": {
        "default": "20",
        "type": "number",
        "category": "behavior",
        "description": "麦克风自检的延迟(秒,启动后多久做一次采集自检;0=关闭自检 · 默认 20)",
    },
    # --- 回话时序(core/routes/chat.py)---
    "GALAXY_CHAT_TIMEOUT_S": {
        "default": "90",
        "type": "number",
        "category": "behavior",
        "description": "单轮对话的总超时(秒,超了就中止本轮 · 默认 90)",
    },
    "GALAXY_LOCKSTEP_CPS": {
        "default": "14.0",
        "type": "number",
        "category": "behavior",
        "description": "文字与语音同刻时文字的吐字速度(字/秒,越大文字跑得越快 · 默认 14)",
    },
    "GALAXY_LOCKSTEP_GRACE_S": {
        "default": "2.0",
        "type": "number",
        "category": "behavior",
        "description": "同刻模式等首个语音块的宽限(秒,等不到就先放文字 · 默认 2)",
    },
    "GALAXY_LOCKSTEP_STALL_S": {
        "default": "8.0",
        "type": "number",
        "category": "behavior",
        "description": "同刻模式中途卡住多久判定语音掉线、文字自己往下走(秒 · 默认 8)",
    },
    "GALAXY_LOCKSTEP_DRAIN_S": {
        "default": "0.8",
        "type": "number",
        "category": "behavior",
        "description": "语音念完后文字收尾的排空时长(秒 · 默认 0.8)",
    },
    # --- 语音识别(core/asr/)---
    "GALAXY_ASR_INITIAL_PROMPT": {
        "default": "以下是普通话的句子。",
        "type": "string",
        "category": "behavior",
        "description": "中文识别的引导语（把 Whisper 的输出偏置到简体、顺带给点上下文;留空=不加引导）",
    },
    "GALAXY_SENSEVOICE_MODEL": {
        "default": "iic/SenseVoiceSmall",
        "type": "string",
        "category": "behavior",
        "description": "SenseVoice 识别引擎的模型 id（留空=用默认的 modelscope 版）",
    },
    # --- 语音合成:Edge / Piper ---
    "GALAXY_EDGE_TTS_TIMEOUT_S": {
        "default": "8",
        "type": "number",
        "category": "behavior",
        "description": "Edge 在线合成的超时(秒,超了就降级到本地引擎 · 默认 8)",
    },
    "GALAXY_PIPER_MODEL": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Piper 语音模型(.onnx)的路径（留空=自动在 models/piper/ 下找）",
    },
    # --- 语音合成:Kokoro ---
    "GALAXY_KOKORO_MODEL": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Kokoro 模型文件名（留空=kokoro-v1.0.onnx;显存/磁盘紧张可换 int8 版）",
    },
    "GALAXY_KOKORO_VOICE": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Kokoro 音色（留空=按文本语种自动挑:中文 zf_/zm_,英文 af_/am_）",
    },
    "GALAXY_KOKORO_LANG": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Kokoro 发音语种（留空=按文本自动判定:含中文用 cmn,否则 en-us）",
    },
    "GALAXY_KOKORO_AUTOFETCH": {
        "default": "true",
        "type": "boolean",
        "category": "behavior",
        "description": "首次使用 Kokoro 时后台自动下载模型（约 310MB · 默认开）",
    },
    # --- 语音合成:MeloTTS ---
    "GALAXY_MELO_LANG": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Melo 语种（留空=ZH_MIX_EN 中英混读;可选 ZH/EN/JP/KR/ES/FR）",
    },
    "GALAXY_MELO_SPEAKER": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Melo 说话人（留空=取该语种的第一个音色）",
    },
    "GALAXY_MELO_SPEED": {
        "default": "1.0",
        "type": "number",
        "category": "behavior",
        "description": "Melo 语速倍率（建议 0.8~1.2,调太快中文会糊 · 默认 1.0）",
    },
    "GALAXY_MELO_DEVICE": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "Melo 推理设备（留空=auto,有显卡走 cuda 否则 cpu;也可直接填 cuda / cpu）",
    },
    # --- 语音合成:IndexTTS-2(零样本音色克隆)---
    "GALAXY_INDEXTTS_REF_AUDIO": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "IndexTTS 参考音频 wav 的路径（零样本克隆的音色来源,不填这条 IndexTTS 用不了）",
    },
    "GALAXY_INDEXTTS_AUTOFETCH": {
        "default": "false",
        "type": "boolean",
        "category": "behavior",
        "description": "首次使用 IndexTTS 时后台自动下载模型（体积很大,默认关,要用请显式打开）",
    },
    "GALAXY_INDEXTTS_EMO_AUDIO": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "IndexTTS 情绪参考音频的路径（可选;用另一段音频的情绪配这段台词）",
    },
    "GALAXY_INDEXTTS_EMO_TEXT": {
        "default": "",
        "type": "string",
        "category": "behavior",
        "description": "IndexTTS 情绪文本描述（可选;如“轻声、带点笑意”,与台词内容解耦）",
    },
    "GALAXY_INDEXTTS_USE_EMO_TEXT": {
        "default": "false",
        "type": "boolean",
        "category": "behavior",
        "description": "由台词语义自动推断情绪（上面那条填了就自动生效,这里是不填也想推断时用 · 默认关）",
    },
    "GALAXY_INDEXTTS_EMO_ALPHA": {
        "default": "0.6",
        "type": "number",
        "category": "behavior",
        "description": "IndexTTS 情绪强度（官方建议 0.6;调高情绪更浓、音色稳定性下降）",
    },
    "GALAXY_INDEXTTS_FP16": {
        "default": "false",
        "type": "boolean",
        "category": "behavior",
        "description": "IndexTTS 用 fp16 推理（显存紧张的 GPU 场景打开,省显存略降质量 · 默认关）",
    },
    # --- 模型文件位置(与 GALAXY_DATA_DIR 等同属"东西放哪儿",归 storage)---
    "GALAXY_KOKORO_DIR": {
        "default": "models/kokoro",
        "type": "string",
        "category": "storage",
        "description": "Kokoro 模型目录（留空=models/kokoro）",
    },
    "GALAXY_INDEXTTS_DIR": {
        "default": "models/indextts2",
        "type": "string",
        "category": "storage",
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
        "category": "behavior",
        "description": "启用语音（关掉则启动时完全不起语音循环,麦克风也不占用 · 默认开）",
    },
    "GALAXY_WHISPER_MODEL": {
        "default": "base",
        "type": "string",
        "category": "behavior",
        "description": "语音循环的 Whisper 模型规格（tiny/base/small/medium/large,越大越准越慢 · 默认 base）",
    },
    # --- 桌面外壳(launcher/services.py、launcher/shell.py)---
    "GALAXY_DESKTOP_SHELL": {
        "default": "",
        "type": "select",
        "category": "behavior",
        "description": "桌面外壳（留空=自动挑选;electron=强制用 Electron 而不是 Tauri）",
        "options": ["", "electron"],
    },
    "GALAXY_SKIP_ELECTRON": {
        "default": "false",
        "type": "boolean",
        "category": "dev",
        "description": "启动时跳过桌面外壳（只起后端服务,用浏览器访问面板 · 默认关）",
    },
    "GALAXY_TAURI_AUTOBUILD": {
        "default": "true",
        "type": "boolean",
        "category": "dev",
        "description": "Tauri 外壳缺产物时自动构建（关掉则缺了就直接跳过、不占用启动时间 · 默认开）",
    },
    # --- 容器运行时(launcher/services.py)---
    "GALAXY_AUTO_DOCKER": {
        "default": "auto",
        "type": "string",
        "category": "dev",
        "description": "自动拉起容器运行时（auto=装了就用 / 1=强制 / 0=关闭 · 默认 auto）",
    },
    "GALAXY_CONTAINER_RUNTIME": {
        "default": "",
        "type": "select",
        "category": "dev",
        "description": "指定容器运行时（留空=两者都装时首启让你选;也可直接钉死 docker 或 podman）",
        "options": ["", "docker", "podman"],
    },
    "GALAXY_AUTO_DOCKER_DAEMON_WAIT": {
        "default": "60",
        "type": "number",
        "category": "dev",
        "description": "等容器守护进程起来的超时(秒 · 默认 60)",
    },
    "GALAXY_AUTO_DOCKER_WAIT": {
        "default": "90",
        "type": "number",
        "category": "dev",
        "description": "等容器内服务就绪的超时(秒 · 默认 90)",
    },
    # --- 启动诊断(main.py、launcher/services.py)---
    "GALAXY_VERBOSE": {
        "default": "false",
        "type": "boolean",
        "category": "dev",
        "description": "启动过程输出详细信息（每一步都展开,排查启动问题时打开 · 默认关）",
    },
    "GALAXY_STRICT_PREFLIGHT": {
        "default": "false",
        "type": "boolean",
        "category": "dev",
        "description": "启动前检查从严（任何一项不过就拒绝启动,而不是降级继续 · 默认关）",
    },
    # --- 节点起停(launcher/node_startup.py)---
    "GALAXY_API_HOST": {
        "default": "127.0.0.1",
        "type": "string",
        "category": "ports",
        "description": "各节点回连 API 时用的主机名（默认只走本机回环;跨机部署才需要改）",
    },
    "GALAXY_NODE_HEALTH_RETRIES": {
        "default": "",
        "type": "number",
        "category": "ports",
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
    # --- WebRTC & Network ---
    # 说明原先只有 "WebRTC Data Channel" 一句英文 —— 面板上照原样显示,中文用户看不懂
    # 这开了会发生什么。是这一轮把守卫范围改成按目录派生之后,
    # core/multimodal/webrtc_ingress_bridge.py 进了范围才扫出来的。
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL": {
        "default": "false",
        "type": "boolean",
        "category": "network",
        "description": "WebRTC 数据通道（浏览器/手机端把摄像头与麦克风的采集结果直接推给感知层 · 默认关）",
    },
    "GALAXY_TURN_URLS": {"default": "", "type": "string", "category": "network", "description": "TURN Server URLs"},
    "GALAXY_HEADSCALE_URL": {"default": "", "type": "url", "category": "network", "description": "Headscale URL"},
    "GALAXY_TAILSCALE_CHECK_INTERVAL": {
        "default": "60",
        "type": "number",
        "category": "network",
        "description": "Tailscale Check Interval (s)",
    },
    "CORS_ALLOWED_ORIGINS": {"default": "*", "type": "string", "category": "network", "description": "CORS Origins"},
    "CORS_ALLOWED_METHODS": {
        "default": "GET,POST,PUT,DELETE",
        "type": "string",
        "category": "network",
        "description": "CORS Methods",
    },
    "CORS_ALLOWED_HEADERS": {"default": "*", "type": "string", "category": "network", "description": "CORS Headers"},
    # --- SLO & Continuity ---
    "GALAXY_SLO_LATENCY_WINDOW": {
        "default": "300",
        "type": "number",
        "category": "slo",
        "description": "SLO Latency Window (s)",
    },
    "GALAXY_SLO_HEARTBEAT_WINDOW": {
        "default": "60",
        "type": "number",
        "category": "slo",
        "description": "SLO Heartbeat Window (s)",
    },
    "GALAXY_RESULT_INGRESS_CONTINUITY_MODE": {
        "default": "strict",
        "type": "select",
        "category": "slo",
        "description": "Result Continuity Mode",
        "options": ["strict", "best-effort", "disabled"],
    },
    "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE": {
        "default": "strict",
        "type": "select",
        "category": "slo",
        "description": "Truth Continuity Mode",
        "options": ["strict", "best-effort", "disabled"],
    },
    "GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S": {
        "default": "300",
        "type": "number",
        "category": "slo",
        "description": "Scaling Re-eval Interval (s)",
    },
    "GALAXY_TEMPORAL_URL": {"default": "", "type": "url", "category": "slo", "description": "Temporal URL"},
    "GALAXY_GW_ADAPTER_DLQ_SUBJECT": {"default": "", "type": "string", "category": "slo", "description": "DLQ Subject"},
}


class ConfigUpdateRequest(BaseModel):
    config: Dict[str, str]


# 面板角标读端点(自 core/routes/system.py 迁入)。迁移原因 —— 鉴权对称性:
# 它原先挂在 system 路由组(整组 Depends(require_auth)),而同路径的写端点
# POST /api/config 在本开放路由组 —— 生产模式(GALAXY_MODE=production 强制
# 开鉴权)下变成"写得进、读不出":Key 保存成功,面板角标读取却 401,永远显示
# "未配置"。读的是掩码状态(布尔 + 非敏感地址),密级不高于写端点,读写必须同权。
_SECRET_MODEL_KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "META_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "SONAR_API_KEY",
    "XAI_API_KEY",
    "ZHIPU_API_KEY",
    "QWEN_API_KEY",
    "DASHSCOPE_API_KEY",
    "MOONSHOT_API_KEY",
    "MINIMAX_API_KEY",
    "STEP_API_KEY",
    "MIMO_API_KEY",
    "MISTRAL_API_KEY",
    "AGNES_API_KEY",
    "HF_API_TOKEN",
    "ONEAPI_API_KEY",
    "DEEPSEEK_OCR2_API_KEY",
]
_NON_SECRET_MODEL_KEYS = [
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "ONEAPI_URL",
    "LOCAL_VLLM_URL",
    "VLLM_URL",
    "OPENAI_API_BASE",
]


@router.get("")
async def get_frontend_config(request: Request = None):
    """返回前端所需的非敏感配置(密钥只给"是否已配置"布尔,不下发值)。"""
    host = "localhost"
    port = "9000"
    if request:
        host = request.url.hostname or "localhost"
        port = str(request.url.port or 9000)

    def _is_configured(key_name: str) -> bool:
        from core.credential_vault import PLACEHOLDER_PREFIXES

        val = os.getenv(key_name, "")
        return bool(val and not val.lower().startswith(PLACEHOLDER_PREFIXES) and not val.startswith("sk-YOUR"))

    return JSONResponse(
        {
            "api_base_url": f"http://{host}:{port}",
            # 此前指向 ws://…/ws —— 该端点已被移除且有测试钉死"必须不存在"
            # (tests/test_pr1_canonical_device_ingress.py),字段却仍在广播幻影
            # 地址。改为真实存在的桌面在场通道。
            "ws_url": f"ws://{host}:{port}/ws/desktop-presence",
            "status": {
                "openai": _is_configured("OPENAI_API_KEY"),
                "deepseek": _is_configured("DEEPSEEK_API_KEY"),
                "anthropic": _is_configured("ANTHROPIC_API_KEY"),
                "gemini": _is_configured("GEMINI_API_KEY"),
                "groq": _is_configured("GROQ_API_KEY"),
                "openrouter": _is_configured("OPENROUTER_API_KEY"),
                "perplexity": _is_configured("SONAR_API_KEY") or _is_configured("PERPLEXITY_API_KEY"),
                "oneapi": _is_configured("ONEAPI_API_KEY"),
                "ocr": _is_configured("DEEPSEEK_OCR2_API_KEY"),
                "ollama": bool(os.getenv("OLLAMA_URL")),
            },
            "configured": {k: _is_configured(k) for k in _SECRET_MODEL_KEYS},
            "values": {k: os.getenv(k, "") for k in _NON_SECRET_MODEL_KEYS},
        }
    )


@router.get("/all")
async def get_config():
    """获取当前所有配置项（从环境变量 + 默认值合并）— 供「设置」tab 使用的完整明细。

    注意:不是挂在裸路径 GET /api/config —— core/routes/system.py 的精简版
    (仅 api_base_url/ws_url/status)先于本路由注册,会遮蔽同路径同方法的路由,
    导致「设置」tab 拿到的永远是精简版、按 key 查不到任何一项 → 只见左侧分类
    标签、右侧内容空白。故完整明细改挂 /api/config/all,与精简版共存不冲突。
    """
    # OLLAMA_MODEL 的候选项从 catalog 动态派生（单一真相源），而非用 schema 里的空占位。
    dynamic_options: Dict[str, list] = {}
    try:
        from core.model_catalog import local_choice_options

        dynamic_options["OLLAMA_MODEL"] = local_choice_options()
    except Exception:  # noqa: BLE001
        pass

    result = {}
    for key, meta in CONFIG_SCHEMA.items():
        result[key] = {
            "value": os.environ.get(key, meta["default"]),
            "default": meta["default"],
            "type": meta["type"],
            "category": meta["category"],
            "description": meta["description"],
        }
        if key in dynamic_options and dynamic_options[key]:
            result[key]["options"] = dynamic_options[key]
        elif "options" in meta:
            result[key]["options"] = meta["options"]
    return result


@router.post("")
async def update_config(req: ConfigUpdateRequest):
    """批量更新配置（写入环境变量 + .env 文件）"""
    # 修复:之前是"边校验边写 os.environ",遇到批次里某个未知 key 时半途
    # raise——已经处理过的合法 key 已经写进 os.environ(内存态生效),但因为
    # 异常发生在 _write_env_file() 之前,这些改动从未落盘到 .env,重启即丢失,
    # 前端只看到笼统的 400。这里先做一遍完整性校验,全部合法才动手写,
    # 避免"部分生效、部分丢失"的诡异中间态。
    unknown_keys = [k for k in req.config if k not in CONFIG_SCHEMA]
    if unknown_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown config key(s): {', '.join(unknown_keys)}",
        )

    # ── 计算最终值(url 补协议头),此刻【先不碰 os.environ】────────────────
    # 真机复现过:用户填 url 类字段(OLLAMA_URL/ONEAPI_URL 等)时只填 host:port
    # (如 "localhost:11434")没带协议头,原样落盘后 httpx 才炸「missing 'http://'
    # protocol」。在写入这一步就补全,不指望每个消费端自己校验。
    final: Dict[str, str] = {}
    for key, value in req.config.items():
        value = str(value)
        if CONFIG_SCHEMA[key]["type"] == "url":
            stripped = value.strip()
            if stripped and not stripped.startswith(("http://", "https://")):
                value = f"http://{stripped}"
        final[key] = value

    # ── 【先落盘、成功才应用到 os.environ】────────────────────────────────
    # 修复"显示已配置、却又保存失败"的自相矛盾:此前是先写 os.environ(前端 GET
    # /api/config 据 os.getenv 判定"已配置")、再写盘,一旦写盘失败(Windows 上
    # .env 被杀毒/编辑器占用、目录只读),就成了"明明已配置、却报保存失败",
    # 用户根本分不清到底存没存、生没生效。现在颠倒顺序:
    #   落盘成功 → 才把值应用进 os.environ(当次即时生效)、"已配置"随之如实为真;
    #   落盘失败 → os.environ 原封不动、"已配置"保持原状,错误如实说明原因。
    # 于是"已配置"与"保存成功"永远一致:存了就是存了、生效了;没存就没存、没生效。
    #
    # 密钥收敛到唯一密钥库:敏感项走 ConfigService.set_secret → runtime/secrets.env,
    # 不明文落 .env(否则重启时 .env 旧值会盖住 secrets.env,历史"重启丢 key"根因);
    # 写 secrets.env 失败的密钥回落 .env(不丢持久化)。
    _secrets_persisted: set = set()
    try:
        from core.config_schema import classify_key as _classify
        from core.config_service import ConfigService as _CS

        _cs = None
        for _k, _v in final.items():
            if _classify(_k) != "secret":
                continue
            try:
                if _cs is None:
                    _cs = _CS()
                if str(_v).strip():
                    _cs.set_secret(_k, str(_v))
                else:
                    # 空值 = 用户在面板上【清空】了这个密钥。此前这里用
                    # `and str(_v).strip()` 直接把空值跳过了,secrets.env 里的旧值
                    # 就一直留着;而启动时 secrets.env 会被灌回进程环境,于是"删掉
                    # 的密钥重启又活过来"。清空必须真的落到密钥库里去删。
                    _cs.delete_secret(_k)
                _secrets_persisted.add(_k)
            except Exception as _e:  # noqa: BLE001 — 失败则保留 .env 回落
                logger.debug("密钥写入/删除 secrets.env 失败(回落 .env): %s", _e)
    except Exception as exc:  # noqa: BLE001 — ConfigService 不可用 → 全部回落 .env
        logger.debug("密钥收敛不可用(降级为 .env 持久化): %s", exc)

    try:
        _write_env_file_with(final, exclude=_secrets_persisted)
    except OSError as exc:
        # 落盘失败 → os.environ 一个字没动,"已配置"如实保持原状,不制造矛盾。
        raise HTTPException(
            status_code=500,
            detail=f"写入 .env 失败: {exc}(检查文件是否被占用/只读，或目录权限）；本次未改动任何配置",
        ) from exc

    # ── 落盘成功 → 应用到 os.environ(当次即时生效),并做即时联动 ──────────
    os.environ.update(final)

    # 模型选择收敛到唯一门:model_catalog.save_tier 把【档位 + 主脑】写进同一条
    # 记录(runtime/model_state.json)并派生 OLLAMA_MODEL,按模型反推档位并联动。
    if "OLLAMA_MODEL" in final:
        try:
            from core import model_catalog as _mc

            _tag = final["OLLAMA_MODEL"]
            _mc.save_tier(_mc.infer_tier_from_model(_tag), main_brain=_tag)
        except Exception as exc:  # noqa: BLE001
            logger.debug("模型状态联动写入失败(非致命): %s", exc)

    # 自发在场开关改动 → 立刻生效(启动/停止常驻循环),不必重启。
    if "GALAXY_AMBIENT_LOOP" in final:
        try:
            from core.ambient_attention_loop import ambient_loop_enabled, get_ambient_loop

            _loop = get_ambient_loop()
            if ambient_loop_enabled() and not _loop.running:
                await _loop.start()
            elif not ambient_loop_enabled() and _loop.running:
                await _loop.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("ambient 循环即时开关失败(非致命): %s", exc)

    # UnifiedConfig 是进程启动时读一次 .env 就不再变的单例("Dashboard 优先级"
    # 那一层实际读的是它)——本函数只写了 os.environ/.env,从没告诉过它内容
    # 变了。同一进程内一直没炸,纯粹是因为 _get_key() 的兜底第三层直接读
    # os.environ 生效了；但 UnifiedConfig 自己上报的值会一直是启动时的旧值，
    # 直到进程重启。这里保存后顺手 reload 一下，让它也反映最新内容，不再是
    # 一个"名义最高优先级、实际全程失效"的摆设。
    try:
        from core.unified_config import config as _unified_cfg

        _unified_cfg.reload()
    except Exception as exc:  # noqa: BLE001
        # 这里静默 pass 等于让上面那段注释描述的修复悄悄失效:reload 一失败,
        # UnifiedConfig 就继续上报启动时的旧值,而保存接口照样返回成功 ——
        # 正是"名义最高优先级、实际全程失效"的原样复发,且无从排查。
        logger.warning(
            "配置已落盘,但 UnifiedConfig.reload() 失败(%s):该单例将继续上报进程启动时的旧值,直到重启",
            exc,
        )

    # 若改动涉及模型 API（llm 类），热刷新 LLM 路由器，让新填的 key 即时生效（无需重启）。
    # 根因修复(真机"保存悬挂"):此前这里同步 await refresh_llm_router()——内部对
    # Ollama/OneAPI 等做 2~5s/个的真实网络探测,离线机器上整体轻松 >8s,而 Electron
    # 主进程 fetchWithRetry 单次尝试 8s 即 abort 重发,保存请求永远答不完:面板卡死
    # 在「保存中…/仍在保存中,后端可能仍在启动…」直到 60s 预算耗尽;每次 abort 的
    # 断开连接还连锁触发后端 "Cannot call write() when UVStream is closing" 刷屏。
    # 保存路由必须快速返回:此刻配置已落盘、已进 os.environ(持久化真相已成立),
    # 慢的网络探测改为后台调度;需要探测结果的 verify-provider 端点自己有界等待
    # (wait_llm_router_refresh),新 key 依然"保存后即可验证",不牺牲功能。
    refreshed = None
    if any(CONFIG_SCHEMA.get(k, {}).get("category") == "llm" for k in final):
        try:
            from core.multi_llm_router import schedule_llm_router_refresh

            schedule_llm_router_refresh()
            refreshed = "scheduled"
        except Exception:
            refreshed = None

    return {"success": True, "updated": list(final.keys()), "router_refreshed": refreshed}


@router.post("/save")
async def save_config():
    """强制保存当前配置到 .env"""
    _write_env_file()
    return {"success": True}


class ProbeRequest(BaseModel):
    keys: list[str]


def _probe_one(raw: str) -> Dict[str, Any]:
    """对单个地址做同步 TCP 连接探测(在线程池里跑,不阻塞事件循环)。"""
    import socket
    import time as _time
    from urllib.parse import urlsplit

    raw = raw.strip()
    if not raw:
        return {"reachable": False, "latency_ms": None, "error": "未配置"}

    # 补默认 scheme,方便 urlsplit 解析出 host/port(例如 "localhost:4222"
    # 这种没写 scheme 的值)。
    parseable = raw if "://" in raw else f"tcp://{raw}"
    parsed = urlsplit(parseable)
    host = parsed.hostname
    port = parsed.port or {"http": 80, "https": 443, "redis": 6379, "nats": 4222}.get(parsed.scheme)

    if not host or not port:
        return {"reachable": False, "latency_ms": None, "error": f"无法解析地址: {raw}"}

    start = _time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=1.5):
            latency_ms = round((_time.monotonic() - start) * 1000, 1)
            return {"reachable": True, "latency_ms": latency_ms, "error": None}
    except OSError as exc:
        return {"reachable": False, "latency_ms": None, "error": str(exc)}


@router.post("/probe")
async def probe_config_urls(req: ProbeRequest):
    """对「设置」tab 里 type=url 的项做真实连通性探测(TCP 连接,不识别协议)。

    背景:「端口与节点」「网络」「组网」这几个分类之前只是纯文本配置编辑器——
    值本身是真实的(读写 os.environ/.env),但用户在设置页完全看不到"这个地址
    现在到底通不通"，被误认为"没有接真实数据"。这里补一个真正的、非伪造的
    连通性探测:对每个 key 解析出 host:port，尝试建立 TCP 连接(1.5s 超时)，
    成功即视为"可达"，不需要认识每种协议(NATS/Redis/HTTP 等)的具体握手。
    多个 key 用 asyncio.to_thread 并发探测,避免阻塞事件循环、也避免用户等待
    N 个地址依次超时的总时长。
    """
    import asyncio as _asyncio

    to_probe: Dict[str, str] = {}
    results: Dict[str, Dict[str, Any]] = {}
    for key in req.keys:
        meta = CONFIG_SCHEMA.get(key)
        if meta is None or meta.get("type") != "url":
            results[key] = {"reachable": False, "latency_ms": None, "error": "not a url-type key"}
            continue
        to_probe[key] = os.environ.get(key, meta["default"])

    if to_probe:
        probed = await _asyncio.gather(*(_asyncio.to_thread(_probe_one, raw) for raw in to_probe.values()))
        results.update(zip(to_probe.keys(), probed))

    return {"results": results}


def _write_env_file(exclude=None):
    """将所有【非空】配置写入 .env 文件(读 os.environ 现值)。"""
    return _write_env_file_with(None, exclude=exclude)


def _write_env_file_with(overrides=None, exclude=None):
    """将所有【非空】配置写入 .env 文件;overrides 里的键用其新值(而非 os.environ)。

    overrides: {key: 新值} —— 允许在【尚未写入 os.environ】时就把新值落盘,从而做到
    "先落盘、成功再应用 os.environ"(见 update_config)。None 时退化为读 os.environ 现值。

    exclude: 调用方按【本次请求】判定"已写进 canonical 密钥库"的密钥名集合——
    尊重调用方"这次没能存进 secrets.env、需要回落 .env"的显式意图(见下方安全
    修复,这层调用方 exclude 仍然生效,只是不再是唯一防线)。

    关键修复:之前把全部 schema 键(含空值)统统写成 ``KEY=`` 行。空字符串
    一旦被 .env 加载进 os.environ,就会把代码里的默认值顶掉——
    ``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 在
    ``OLLAMA_URL=""`` 存在时返回 ""，不是默认值。真机复现过的一整串症状都
    源于此:LocalBrainManager 拿空 URL ping Ollama(明明在跑却判"服务未响应/
    模型未就绪")、Redis "must specify scheme"、NATS "invalid hostname"。
    现在空值不写入(视同未配置),下次保存时旧 .env 里的空值行也会随全量
    重写被清掉。

    安全修复(密钥明文泄露回归,直接排查"已配置又保存失败"发现):旧版
    ``exclude`` 只是【调用方按本次请求】传入的集合——update_config() 只把
    "这次请求里刚成功写入 secrets.env 的 key"排除掉,对"之前某次请求已经存进
    secrets.env、现在仍躺在 os.environ 里"的密钥毫无防备:全量重写时会把它们
    当普通配置从 os.environ 读出来,原样明文写回 .env——保存任何一个【无关】
    的设置项,都会把所有【已经安全存好】的 API Key 重新泄露进 .env。
    ``/save`` 端点(强制保存)甚至完全没传 exclude,每次点都 100% 泄露全部密钥。
    这不仅是安全回归,也是"已配置但保存失败"的合理成因之一:一个不断被重新
    写入密钥明文的 .env,在 Windows 上更容易被杀毒/同步客户端占用触发 OSError。

    现在无论调用方传不传 exclude,这里都会【自行】额外并上 runtime/secrets.env
    里【当前真实存在】的全部键——不是所有 secret 分类的键(那样会把从未成功
    存进 secrets.env、只能靠 .env 兜底持久化的密钥连 .env 也一并排除掉,变成
    彻底丢失,破坏既有的降级持久化设计),只排除已确认安全落在 secrets.env
    的那些。读取失败(文件不存在/损坏)时保守地不额外排除,不影响本次落盘。
    """
    lines = ["# Galaxy Configuration - Auto-generated by Settings Panel\n"]

    # 按类别分组
    current_category = ""
    _exclude = set(exclude or set())
    try:
        from core.config_store import get_config_store

        _exclude |= set(get_config_store().read_secrets().keys())
    except Exception as exc:  # noqa: BLE001 — 排除集合计算失败不影响本次落盘,保守回落明文
        logger.debug("读取 secrets.env 计算排除集合失败(不影响本次落盘): %s", exc)
    _overrides = overrides or {}
    for key, meta in sorted(CONFIG_SCHEMA.items(), key=lambda x: x[1]["category"]):
        if key in _exclude:
            continue  # 已入 canonical 密钥库,不再明文写 .env
        value = _overrides.get(key, os.environ.get(key, meta["default"]))
        if not str(value).strip():
            continue  # 空值不落盘——否则会把代码默认值顶掉
        if meta["category"] != current_category:
            current_category = meta["category"]
            lines.append(f"\n# --- {current_category.upper()} ---\n")

        desc = meta["description"]
        lines.append(f"# {desc}\n{key}={value}\n")

    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


# 注:曾经这里有一个 _load_env_file()——但全仓库排查确认它从未被任何地方调用过,
# 是一段死代码(容易让人误以为"config.py 会自己加载 .env"从而误删/误改
# main.py 顶部真正生效的 dotenv.load_dotenv() 那段逻辑,造成隐蔽回归)。
# .env → os.environ 的真正加载点在 main.py / unified_launcher.py 顶部
# 的 load_dotenv() 调用,已删除此处死代码。
