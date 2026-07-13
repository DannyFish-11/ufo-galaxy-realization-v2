"""
Galaxy Configuration API
提供系统配置的全量读取和批量更新，持久化到 .env 文件。
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, HTTPException
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
    "META_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Meta Model API Key (Muse Spark)"},
    "MISTRAL_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Mistral API Key"},
    "QWEN_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Qwen API Key"},
    "DASHSCOPE_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "DashScope API Key (alias)"},
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
    "DEEPSEEK_OCR2_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "DeepSeek OCR API Key"},
    "OPENAI_API_BASE": {"default": "", "type": "url", "category": "llm", "description": "OpenAI-compatible Base URL (代理/中转)"},
    "SONAR_API_KEY": {"default": "", "type": "string", "category": "llm", "description": "Perplexity Sonar API Key (alias)"},
    "VLLM_URL": {"default": "", "type": "url", "category": "llm", "description": "vLLM URL (alias)"},
    "LOCAL_VLLM_URL": {"default": "", "type": "url", "category": "llm", "description": "Local vLLM URL"},
    # options 不再硬编码——由 get_config 在响应时从 core.model_catalog 动态派生
    # （与 model_selection、面板 ModelsTab 同一真相源，杜绝三份清单漂移）。
    "OLLAMA_MODEL": {"default": "", "type": "select", "category": "llm", "description": "本地主脑模型（原生多模态）", "options": []},

    # --- Service Ports & Nodes ---
    "GATEWAY_PORT": {"default": "9000", "type": "number", "category": "ports", "description": "Galaxy Gateway Port"},
    "UFO_NODE_HOST": {"default": "localhost", "type": "string", "category": "ports", "description": "Node Host"},
    "NODE_92_URL": {"default": "http://localhost:8092", "type": "url", "category": "ports", "description": "Device Control Service"},
    "NODE_45_URL": {"default": "http://localhost:8045", "type": "url", "category": "ports", "description": "Desktop Endpoint"},
    "NODE_33_URL": {"default": "http://localhost:8033", "type": "url", "category": "ports", "description": "ADB Control"},
    "NODE_71_URL": {"default": "http://localhost:8071", "type": "url", "category": "ports", "description": "Multi-Device Orchestration"},
    "NODE_71_HOST": {"default": "localhost", "type": "string", "category": "ports", "description": "Node 71 Host"},
    "NODE_95_URL": {"default": "http://localhost:8095", "type": "url", "category": "ports", "description": "Vision Sampler"},
    "NODE_97_URL": {"default": "http://localhost:8097", "type": "url", "category": "ports", "description": "Academic Retrieval"},
    "NODE09_SANDBOX_URL": {"default": "", "type": "url", "category": "ports", "description": "Code Sandbox"},
    "OLLAMA_URL": {"default": "", "type": "url", "category": "ports", "description": "Ollama URL"},
    "QDRANT_URL": {"default": "", "type": "url", "category": "ports", "description": "Qdrant Vector DB"},
    "REDIS_URL": {"default": "", "type": "url", "category": "ports", "description": "Redis URL"},
    "SECRETVAULT_URL": {"default": "", "type": "url", "category": "ports", "description": "Secret Vault"},
    "MAIN_REPO_URL": {"default": "http://localhost:8080", "type": "url", "category": "ports", "description": "Main Repo URL"},
    "MQTT_PORT": {"default": "", "type": "number", "category": "ports", "description": "MQTT Broker Port"},

    # --- Authentication & Security ---
    "GALAXY_AUTH_ENABLED": {"default": "false", "type": "boolean", "category": "auth", "description": "Enable Authentication"},
    "GALAXY_API_TOKEN": {"default": "", "type": "string", "category": "auth", "description": "API Token (single)"},
    "GALAXY_API_TOKENS": {"default": "", "type": "string", "category": "auth", "description": "API Tokens (comma-separated)"},
    "GALAXY_API_TOKEN_EXPIRY": {"default": "", "type": "string", "category": "auth", "description": "Token Expiry"},
    "GALAXY_REVOKED_TOKENS": {"default": "", "type": "string", "category": "auth", "description": "Revoked Tokens"},
    "GALAXY_REQUIRE_API_TOKEN": {"default": "false", "type": "boolean", "category": "auth", "description": "Require API Token"},
    "GALAXY_STRICT_AUTHORITY_CHECK": {"default": "false", "type": "boolean", "category": "auth", "description": "Strict Authority Check"},
    "GALAXY_SECRET_BACKEND": {"default": "env", "type": "select", "category": "auth", "description": "Secret Backend", "options": ["env", "vault", "kms"]},
    "GALAXY_TLS_CERT": {"default": "", "type": "string", "category": "auth", "description": "TLS Certificate Path"},
    "GITHUB_TOKEN": {"default": "", "type": "string", "category": "auth", "description": "GitHub Token"},
    # 融合(域6):删掉两个幽灵开关 GALAXY_AUDIT_KEY / GALAXY_MESSAGE_SIGNING_KEY——
    # 全仓无任何代码读它们(面板上摆着没实现的安全功能,误导操作者)。消息签名
    # 【真实已实现】,但键名是 GALAXY_MESH_SECRET(capability_token HMAC 签名/校验,
    # 缺省自动生成 .galaxy_mesh_key),把真的这只上面板。
    "GALAXY_MESH_SECRET": {"default": "", "type": "string", "category": "auth", "description": "Mesh 签名密钥(能力令牌 HMAC;留空自动生成)"},

    # --- Mesh & NATS ---
    "GALAXY_MDNS": {"default": "true", "type": "boolean", "category": "mesh", "description": "局域网零配置发现(mDNS · 手机/手表免输 IP 自动发现网关)"},
    "GALAXY_NATS_ENABLED": {"default": "true", "type": "boolean", "category": "mesh", "description": "Enable NATS"},
    "GALAXY_NATS_URL": {"default": "nats://localhost:4222", "type": "url", "category": "mesh", "description": "NATS URL"},
    "GALAXY_NATS_EXECUTOR_TIMEOUT": {"default": "30", "type": "number", "category": "mesh", "description": "NATS Executor Timeout (s)"},
    "GALAXY_NATS_EXECUTOR_FALLBACK": {"default": "sync", "type": "select", "category": "mesh", "description": "Executor Fallback Mode", "options": ["sync", "async", "reject"]},
    "GALAXY_CROSS_DEVICE_ENABLED": {"default": "true", "type": "boolean", "category": "mesh", "description": "Cross-Device Orchestration"},
    "GALAXY_MASTER_BRAIN_ENABLED": {"default": "false", "type": "boolean", "category": "mesh", "description": "启用主脑编排 + worker/NATS 分布式(多设备总开关 · 默认关=单机)"},
    "GALAXY_FABRIC_STRICT": {"default": "false", "type": "boolean", "category": "mesh", "description": "严格织网:NATS 不可达即视为致命(默认关=优雅降级单机)"},
    "GALAXY_HEARTBEAT_INTERVAL": {"default": "5", "type": "number", "category": "mesh", "description": "Heartbeat Interval (s)"},
    "FEDERATION_ENABLED": {"default": "false", "type": "boolean", "category": "mesh", "description": "Enable Federation"},
    "FEDERATION_LOCAL_HOST": {"default": "", "type": "string", "category": "mesh", "description": "Federation Local Host"},
    "FEDERATION_PEERS": {"default": "", "type": "string", "category": "mesh", "description": "Federation Peers (comma-separated)"},
    "FEDERATION_HEARTBEAT_INTERVAL": {"default": "10", "type": "number", "category": "mesh", "description": "Federation Heartbeat (s)"},
    "GALAXY_CANONICAL_DISPATCH_AUTHORITY_MODE": {"default": "strict", "type": "select", "category": "mesh", "description": "Dispatch Authority Mode", "options": ["strict", "advisory", "disabled"]},

    # --- Circuit Breaker & Adaptive ---
    "GALAXY_ROUTER_ADAPTIVE_CONCURRENCY": {"default": "true", "type": "boolean", "category": "circuit", "description": "Adaptive Concurrency"},
    "GALAXY_ROUTER_CB_ENABLED": {"default": "true", "type": "boolean", "category": "circuit", "description": "Circuit Breaker"},
    "GALAXY_ROUTER_MAX_QUEUE_DEPTH": {"default": "1000", "type": "number", "category": "circuit", "description": "Max Queue Depth"},
    "GALAXY_CB_FAILURE_THRESHOLD": {"default": "5", "type": "number", "category": "circuit", "description": "CB Failure Threshold"},
    "GALAXY_CB_RECOVERY_TIMEOUT_S": {"default": "30", "type": "number", "category": "circuit", "description": "CB Recovery Timeout (s)"},
    "GALAXY_CB_HALF_OPEN_PROBES": {"default": "3", "type": "number", "category": "circuit", "description": "CB Half-Open Probes"},
    "GALAXY_CB_WINDOW_SIZE": {"default": "60", "type": "number", "category": "circuit", "description": "CB Window Size (s)"},
    "GALAXY_AS_TARGET_LATENCY_MS": {"default": "2000", "type": "number", "category": "circuit", "description": "Adaptive Target Latency (ms)"},
    "GALAXY_AS_ERROR_THRESHOLD": {"default": "0.1", "type": "number", "category": "circuit", "description": "Adaptive Error Threshold"},
    "GALAXY_AS_INIT_LIMIT": {"default": "10", "type": "number", "category": "circuit", "description": "Adaptive Init Limit"},
    "GALAXY_AS_MAX_LIMIT": {"default": "200", "type": "number", "category": "circuit", "description": "Adaptive Max Limit"},
    "GALAXY_AS_MIN_LIMIT": {"default": "1", "type": "number", "category": "circuit", "description": "Adaptive Min Limit"},
    "GALAXY_AS_SAMPLE_WINDOW": {"default": "60", "type": "number", "category": "circuit", "description": "Adaptive Sample Window (s)"},
    "GALAXY_AS_PROBE_INTERVAL_S": {"default": "5", "type": "number", "category": "circuit", "description": "Adaptive Probe Interval (s)"},

    # --- Storage ---
    "GALAXY_DATA_DIR": {"default": "./data", "type": "string", "category": "storage", "description": "Data Directory"},
    "GALAXY_MARKET_STORE_DIR": {"default": "./market", "type": "string", "category": "storage", "description": "Market Store Dir"},
    "GALAXY_FEATURE_FLAGS_PATH": {"default": "", "type": "string", "category": "storage", "description": "Feature Flags Path"},
    "GALAXY_MASTER_BRAIN_STATE_PATH": {"default": "", "type": "string", "category": "storage", "description": "Master Brain State Path"},
    "CHROMA_PERSIST_DIR": {"default": "./chroma", "type": "string", "category": "storage", "description": "Chroma Persist Dir"},
    "ANDROID_DEVICE_STATE_STORE_PATH": {"default": "", "type": "string", "category": "storage", "description": "Android State Store"},
    "ANDROID_DEVICE_SNAPSHOT_TTL_SECONDS": {"default": "300", "type": "number", "category": "storage", "description": "Android Snapshot TTL (s)"},

    # --- Development ---
    "GALAXY_DEV_MODE": {"default": "false", "type": "boolean", "category": "dev", "description": "Developer Mode"},
    "GALAXY_MODE": {"default": "standard", "type": "select", "category": "dev", "description": "Run Mode", "options": ["standard", "distributed", "federated", "standalone"]},
    "GALAXY_SYSTEM_MODE": {"default": "desktop-local", "type": "select", "category": "mesh", "description": "运行模式（desktop-local=单机 · desktop-cross-device=跨设备织网）", "options": ["desktop-local", "desktop-cross-device"]},
    "GALAXY_PREFLIGHT_MODE": {"default": "normal", "type": "select", "category": "dev", "description": "Preflight Mode", "options": ["normal", "strict", "skip"]},
    "GALAXY_PREFLIGHT_FAIL_FAST": {"default": "false", "type": "boolean", "category": "dev", "description": "Preflight Fail-Fast"},
    "GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK": {"default": "false", "type": "boolean", "category": "dev", "description": "Legacy Scheduler Fallback"},
    "GALAXY_ENTRYMODE_USE_READINESS": {"default": "true", "type": "boolean", "category": "dev", "description": "Use Readiness Check"},
    "CMD_MAX_CONCURRENT": {"default": "50", "type": "number", "category": "dev", "description": "Max Concurrent Commands"},
    "CONCURRENCY_GLOBAL_MAX": {"default": "100", "type": "number", "category": "dev", "description": "Global Concurrency Max"},
    "GALAXY_MAX_CONTEXT_TOKENS": {"default": "100000", "type": "number", "category": "dev", "description": "Max Context Tokens"},
    "GALAXY_MAX_MESSAGE_SIZE": {"default": "10485760", "type": "number", "category": "dev", "description": "Max Message Size (bytes)"},

    # --- 行为 / 在场 (面板"行为"区直接开关，无需改环境变量) ---
    # 这些是面向用户的行为开关，面板上以明确的开关呈现:说/流式/自发在场/原生音频。
    "GALAXY_AUTONOMY": {"default": "guided", "type": "select", "category": "behavior", "description": "自治档位（safe=敏感操作全问 · guided=读放行写审批 · autonomous=不逐步问人）", "options": ["safe", "guided", "autonomous"]},
    "GALAXY_SPEAK": {"default": "true", "type": "boolean", "category": "behavior", "description": "朗读回复（说 · 默认开）"},
    "GALAXY_TTS_ENGINE": {"default": "edge", "type": "select", "category": "behavior", "description": "说·语音引擎（edge=联网音质好 · melo=离线中英混读自然 · piper=离线最轻 · auto=优先edge退melo退piper）", "options": ["edge", "melo", "piper", "auto"]},
    "GALAXY_ASR_ENGINE": {"default": "auto", "type": "select", "category": "behavior", "description": "听·识别引擎（auto=中文CPU首选SenseVoice退Whisper · sensevoice=离线中文快而准 · whisper=兜底）", "options": ["auto", "sensevoice", "whisper"]},
    "GALAXY_VOICE_EAGERNESS": {"default": "auto", "type": "select", "category": "behavior", "description": "接话急切度（low=耐心等你想 · auto · high=抢答）——按说话内容判断回合是否结束", "options": ["low", "auto", "high"]},
    "GALAXY_VOICE_DELEGATE": {"default": "true", "type": "boolean", "category": "behavior", "description": "语音委托模式（重活先口头致谢、后台跑,对话不被堵死 · 默认开）"},
    "GALAXY_VOICE_BACKCHANNEL": {"default": "true", "type": "boolean", "category": "behavior", "description": "后台干活时的短应答（嗯,还在处理 · 默认开）"},
    "GALAXY_TTS_STREAMING": {"default": "true", "type": "boolean", "category": "behavior", "description": "分句流式朗读（边生成边说 · 默认开）"},
    "GALAXY_AMBIENT_LOOP": {"default": "false", "type": "boolean", "category": "behavior", "description": "自发在场（持续看/听、自己判断何时开口 · 需桌面感知）"},
    "GALAXY_NATIVE_AUDIO": {"default": "false", "type": "boolean", "category": "behavior", "description": "原生音频输入（模型直接听音频，需全模态服务；关则走 ASR 转文字）"},
    "GALAXY_AMBIENT_INTERVAL_S": {"default": "2.0", "type": "number", "category": "behavior", "description": "自发在场节拍(秒)"},
    "GALAXY_AMBIENT_COOLDOWN_S": {"default": "20.0", "type": "number", "category": "behavior", "description": "开口/委托后冷却(秒,防话痨)"},

    # --- WebRTC & Network ---
    "GALAXY_ENABLE_WEBRTC_DATA_CHANNEL": {"default": "false", "type": "boolean", "category": "network", "description": "WebRTC Data Channel"},
    "GALAXY_TURN_URLS": {"default": "", "type": "string", "category": "network", "description": "TURN Server URLs"},
    "GALAXY_HEADSCALE_URL": {"default": "", "type": "url", "category": "network", "description": "Headscale URL"},
    "GALAXY_TAILSCALE_CHECK_INTERVAL": {"default": "60", "type": "number", "category": "network", "description": "Tailscale Check Interval (s)"},
    "CORS_ALLOWED_ORIGINS": {"default": "*", "type": "string", "category": "network", "description": "CORS Origins"},
    "CORS_ALLOWED_METHODS": {"default": "GET,POST,PUT,DELETE", "type": "string", "category": "network", "description": "CORS Methods"},
    "CORS_ALLOWED_HEADERS": {"default": "*", "type": "string", "category": "network", "description": "CORS Headers"},

    # --- SLO & Continuity ---
    "GALAXY_SLO_LATENCY_WINDOW": {"default": "300", "type": "number", "category": "slo", "description": "SLO Latency Window (s)"},
    "GALAXY_SLO_HEARTBEAT_WINDOW": {"default": "60", "type": "number", "category": "slo", "description": "SLO Heartbeat Window (s)"},
    "GALAXY_RESULT_INGRESS_CONTINUITY_MODE": {"default": "strict", "type": "select", "category": "slo", "description": "Result Continuity Mode", "options": ["strict", "best-effort", "disabled"]},
    "GALAXY_RUNTIME_TRUTH_CONTINUITY_MODE": {"default": "strict", "type": "select", "category": "slo", "description": "Truth Continuity Mode", "options": ["strict", "best-effort", "disabled"]},
    "GALAXY_MASTER_BRAIN_SCALING_REEVAL_INTERVAL_S": {"default": "300", "type": "number", "category": "slo", "description": "Scaling Re-eval Interval (s)"},
    "GALAXY_TEMPORAL_URL": {"default": "", "type": "url", "category": "slo", "description": "Temporal URL"},
    "GALAXY_GW_ADAPTER_DLQ_SUBJECT": {"default": "", "type": "string", "category": "slo", "description": "DLQ Subject"},
}


class ConfigUpdateRequest(BaseModel):
    config: Dict[str, str]


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

    for key, value in req.config.items():
        value = str(value)
        # 真机复现过:用户在面板填 url 类字段(OLLAMA_URL/ONEAPI_URL 等)时只填了
        # host:port(如 "localhost:11434"),没带协议头。这个值原样落进 .env,
        # 直到真正发起请求时 httpx 才会炸「missing 'http://' or 'https://'
        # protocol」——用户看到的只是笼统的"LLM 调用失败"。在写入这一步就
        # 补全协议头,而不是指望每个读它的消费端都记得自己校验。
        if CONFIG_SCHEMA[key]["type"] == "url":
            stripped = value.strip()
            if stripped and not stripped.startswith(("http://", "https://")):
                value = f"http://{stripped}"
        os.environ[key] = value

    # 密钥收敛到【唯一密钥库】:API key / token 等敏感项走 ConfigService.set_secret
    # → runtime/secrets.env(canonical 密钥库),不再明文落进 .env。
    # 关键的重启正确性:main.py 顶部先把 .env 灌进 os.environ,config_preflight 再以
    # `key not in os.environ` 的门读 secrets.env——所以 .env 里若残留同名旧值会【盖住】
    # secrets.env(正是历史上"重启丢 key"的根因)。因此:成功写进 secrets.env 的密钥
    # 必须从 .env 排除(_write_env_file 全量重写时自动清掉旧明文行);写 secrets.env 失败
    # 的仍回落 .env,不丢持久化。os.environ 上面已设,当次即时生效。
    _secrets_persisted: set = set()
    try:
        from core.config_schema import classify_key as _classify
        from core.config_service import ConfigService as _CS
        _cs = None
        for _k, _v in req.config.items():
            if _classify(_k) == "secret" and str(_v).strip():
                try:
                    if _cs is None:
                        _cs = _CS()
                    _cs.set_secret(_k, str(_v))
                    _secrets_persisted.add(_k)
                except Exception as _e:  # noqa: BLE001 — 失败则保留 .env 回落
                    logger.debug("密钥写入 secrets.env 失败(回落 .env): %s", _e)
    except Exception as exc:  # noqa: BLE001 — ConfigService 不可用 → 全部回落 .env
        logger.debug("密钥收敛不可用(降级为 .env 持久化): %s", exc)

    # 模型选择收敛到唯一门:model_catalog.save_tier 把【档位 + 主脑】写进同一条
    # 记录(runtime/model_state.json)并派生 OLLAMA_MODEL —— 不再各写 .galaxy_model /
    # .galaxy_tier / OLLAMA_MODEL 三处。按模型反推档位并联动,消除档位↔主脑分叉
    # (否则 active_effective_io() 读的档位与实际主脑不符,modality_bridge 会误判听/说通路)。
    # 上面 .env 里也已写了 OLLAMA_MODEL(env 层持久化,归配置域);二者一致。
    if "OLLAMA_MODEL" in req.config:
        try:
            from core import model_catalog as _mc
            _tag = req.config["OLLAMA_MODEL"]
            _mc.save_tier(_mc.infer_tier_from_model(_tag), main_brain=_tag)
        except Exception as exc:  # noqa: BLE001
            logger.debug("模型状态联动写入失败(非致命): %s", exc)

    # 自发在场开关改动 → 立刻生效(启动/停止常驻循环),不必重启。GALAXY_SPEAK/
    # TTS_STREAMING/NATIVE_AUDIO 都是每次用时现读 os.environ,上面已写入即时生效,
    # 唯独 ambient 循环是常驻后台任务,需在这里显式拉起/收起。
    if "GALAXY_AMBIENT_LOOP" in req.config:
        try:
            from core.ambient_attention_loop import get_ambient_loop, ambient_loop_enabled
            _loop = get_ambient_loop()
            if ambient_loop_enabled() and not _loop.running:
                await _loop.start()
            elif not ambient_loop_enabled() and _loop.running:
                await _loop.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("ambient 循环即时开关失败(非致命): %s", exc)

    # 修复:_write_env_file() 之前完全没有 try/except——Windows 上 .env 若被
    # 杀毒软件/编辑器占用锁定,或所在目录权限不足,write_text() 会抛
    # PermissionError,FastAPI 缺省转成裸 500、无任何 detail,前端只能显示
    # "保存失败"四个字,排查全靠猜。这里显式捕获并把真实原因透传出去。
    try:
        _write_env_file(exclude=_secrets_persisted)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"写入 .env 失败: {exc}(检查文件是否被占用/只读，或目录权限）",
        ) from exc

    # UnifiedConfig 是进程启动时读一次 .env 就不再变的单例("Dashboard 优先级"
    # 那一层实际读的是它)——本函数只写了 os.environ/.env,从没告诉过它内容
    # 变了。同一进程内一直没炸,纯粹是因为 _get_key() 的兜底第三层直接读
    # os.environ 生效了；但 UnifiedConfig 自己上报的值会一直是启动时的旧值，
    # 直到进程重启。这里保存后顺手 reload 一下，让它也反映最新内容，不再是
    # 一个"名义最高优先级、实际全程失效"的摆设。
    try:
        from core.unified_config import config as _unified_cfg
        _unified_cfg.reload()
    except Exception:
        pass

    # 若改动涉及模型 API（llm 类），热刷新 LLM 路由器，让新填的 key 即时生效（无需重启）。
    refreshed = None
    if any(CONFIG_SCHEMA.get(k, {}).get("category") == "llm" for k in req.config):
        try:
            from core.multi_llm_router import refresh_llm_router
            refreshed = await refresh_llm_router()
        except Exception:
            refreshed = None

    return {"success": True, "updated": list(req.config.keys()), "router_refreshed": refreshed}


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
        probed = await _asyncio.gather(
            *(_asyncio.to_thread(_probe_one, raw) for raw in to_probe.values())
        )
        results.update(zip(to_probe.keys(), probed))

    return {"results": results}


def _write_env_file(exclude=None):
    """将所有【非空】配置写入 .env 文件。

    exclude: 已写进 canonical 密钥库(runtime/secrets.env)的密钥名集合——这些
    不再明文落进 .env(否则重启时 .env 旧值会盖住 secrets.env),全量重写即清掉旧行。

    关键修复:之前把全部 schema 键(含空值)统统写成 ``KEY=`` 行。空字符串
    一旦被 .env 加载进 os.environ,就会把代码里的默认值顶掉——
    ``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 在
    ``OLLAMA_URL=""`` 存在时返回 ""，不是默认值。真机复现过的一整串症状都
    源于此:LocalBrainManager 拿空 URL ping Ollama(明明在跑却判"服务未响应/
    模型未就绪")、Redis "must specify scheme"、NATS "invalid hostname"。
    现在空值不写入(视同未配置),下次保存时旧 .env 里的空值行也会随全量
    重写被清掉。
    """
    lines = ["# Galaxy Configuration - Auto-generated by Settings Panel\n"]

    # 按类别分组
    current_category = ""
    _exclude = exclude or set()
    for key, meta in sorted(CONFIG_SCHEMA.items(), key=lambda x: x[1]["category"]):
        if key in _exclude:
            continue  # 已入 canonical 密钥库,不再明文写 .env
        value = os.environ.get(key, meta["default"])
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
