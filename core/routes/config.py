"""
Galaxy Configuration API
提供系统配置的全量读取和批量更新，持久化到 .env 文件。
"""

import os
import json
from pathlib import Path
from typing import Any, Dict
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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
    "LOCAL_VLLM_URL": {"default": "", "type": "url", "category": "llm", "description": "Local vLLM URL"},
    "OLLAMA_MODEL": {"default": "", "type": "select", "category": "llm", "description": "本地主脑模型（原生多模态）", "options": ["gemma4:12b", "openbmb/minicpm-o4.5", "gemma4:e4b", "gemma4:e2b"]},

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
    "GALAXY_AUDIT_KEY": {"default": "", "type": "string", "category": "auth", "description": "Audit Key"},
    "GALAXY_MESSAGE_SIGNING_KEY": {"default": "", "type": "string", "category": "auth", "description": "Message Signing Key"},

    # --- Mesh & NATS ---
    "GALAXY_NATS_ENABLED": {"default": "true", "type": "boolean", "category": "mesh", "description": "Enable NATS"},
    "GALAXY_NATS_URL": {"default": "nats://localhost:4222", "type": "url", "category": "mesh", "description": "NATS URL"},
    "GALAXY_NATS_EXECUTOR_TIMEOUT": {"default": "30", "type": "number", "category": "mesh", "description": "NATS Executor Timeout (s)"},
    "GALAXY_NATS_EXECUTOR_FALLBACK": {"default": "sync", "type": "select", "category": "mesh", "description": "Executor Fallback Mode", "options": ["sync", "async", "reject"]},
    "GALAXY_CROSS_DEVICE_ENABLED": {"default": "true", "type": "boolean", "category": "mesh", "description": "Cross-Device Orchestration"},
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
    "GALAXY_SYSTEM_MODE": {"default": "active", "type": "select", "category": "dev", "description": "System Mode", "options": ["active", "passive", "maintenance"]},
    "GALAXY_PREFLIGHT_MODE": {"default": "normal", "type": "select", "category": "dev", "description": "Preflight Mode", "options": ["normal", "strict", "skip"]},
    "GALAXY_PREFLIGHT_FAIL_FAST": {"default": "false", "type": "boolean", "category": "dev", "description": "Preflight Fail-Fast"},
    "GALAXY_ALLOW_LEGACY_SCHEDULER_FALLBACK": {"default": "false", "type": "boolean", "category": "dev", "description": "Legacy Scheduler Fallback"},
    "GALAXY_ENTRYMODE_USE_READINESS": {"default": "true", "type": "boolean", "category": "dev", "description": "Use Readiness Check"},
    "CMD_MAX_CONCURRENT": {"default": "50", "type": "number", "category": "dev", "description": "Max Concurrent Commands"},
    "CONCURRENCY_GLOBAL_MAX": {"default": "100", "type": "number", "category": "dev", "description": "Global Concurrency Max"},
    "GALAXY_MAX_CONTEXT_TOKENS": {"default": "100000", "type": "number", "category": "dev", "description": "Max Context Tokens"},
    "GALAXY_MAX_MESSAGE_SIZE": {"default": "10485760", "type": "number", "category": "dev", "description": "Max Message Size (bytes)"},

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
    result = {}
    for key, meta in CONFIG_SCHEMA.items():
        result[key] = {
            "value": os.environ.get(key, meta["default"]),
            "default": meta["default"],
            "type": meta["type"],
            "category": meta["category"],
            "description": meta["description"],
        }
        if "options" in meta:
            result[key]["options"] = meta["options"]
    return result


@router.post("")
async def update_config(req: ConfigUpdateRequest):
    """批量更新配置（写入环境变量 + .env 文件）"""
    for key, value in req.config.items():
        if key not in CONFIG_SCHEMA:
            raise HTTPException(status_code=400, detail=f"Unknown config key: {key}")
        os.environ[key] = str(value)

    # 同步写入 .env 文件
    _write_env_file()

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


def _write_env_file():
    """将所有配置写入 .env 文件"""
    lines = ["# Galaxy Configuration - Auto-generated by Settings Panel\n"]

    # 按类别分组
    current_category = ""
    for key, meta in sorted(CONFIG_SCHEMA.items(), key=lambda x: x[1]["category"]):
        if meta["category"] != current_category:
            current_category = meta["category"]
            lines.append(f"\n# --- {current_category.upper()} ---\n")

        value = os.environ.get(key, meta["default"])
        desc = meta["description"]
        lines.append(f"# {desc}\n{key}={value}\n")

    ENV_FILE.write_text("\n".join(lines), encoding="utf-8")


def _load_env_file():
    """启动时从 .env 加载配置到环境变量"""
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key and key not in os.environ:
            os.environ[key] = value.strip()
