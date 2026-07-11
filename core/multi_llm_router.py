"""
多 LLM 智能路由器 (Multi-LLM Router)
=====================================

真正的多提供商路由，直接调用 OpenAI / Claude / Gemini / DeepSeek / Ollama，
根据任务类型智能选择最优模型，支持故障转移和负载均衡。
"""

import os
import json
import time
import asyncio
import logging
import random
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

import httpx

logger = logging.getLogger("Galaxy.LLMRouter")


# ───────────────────── 数据模型 ─────────────────────

class TaskType(Enum):
    """任务类型 → 决定模型选择策略"""
    REASONING = "reasoning"          # 复杂推理 → 强模型
    FAST_RESPONSE = "fast_response"  # 快速问答 → 快模型
    CODING = "coding"                # 代码生成 → 代码模型
    CREATIVE = "creative"            # 创作 → 创意模型
    ANALYSIS = "analysis"            # 分析 → 均衡模型
    PLANNING = "planning"            # 规划 → 强推理模型
    AGENT_CONTROL = "agent_control"  # Agent 指令生成
    GENERAL = "general"


class ProviderStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class ProviderConfig:
    """单个提供商配置"""
    name: str
    api_key: str
    base_url: str
    models: List[str]
    default_model: str
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    supports_tools: bool = True
    supports_json_mode: bool = True
    timeout: float = 60.0
    multimodal: bool = False          # 是否原生支持多模态（图像/音频/视频输入）
    env_key: str = ""                 # 对应的环境变量名（用于可用性提示）
    # PR-HA: 硬件感知 + 多模态优先新增字段
    source_type: str = "api"          # "api" / "local" / "hf_local" / "oneapi"
    hardware_tier: str = "remote"    # "gpu_full" / "gpu_quantized" / "cpu" / "remote"
    supports_vision: bool = False     # 是否支持图像输入（VLM能力）
    supports_audio: bool = False      # 是否支持音频输入
    kv_cache_enabled: bool = False    # 是否启用KV cache（借鉴vLLM）
    prefix_cache_enabled: bool = False # 是否启用前缀缓存（借鉴SGLang RadixAttention）
    quantization: str = "none"        # "none" / "q4" / "q5" / "q8" / "awq" / "gptq"
    # 运行时状态
    status: ProviderStatus = ProviderStatus.HEALTHY
    latency_avg_ms: float = 0.0
    error_count: int = 0
    success_count: int = 0
    last_error: Optional[str] = None
    last_used: float = 0.0
    down_since: float = 0.0  # 标记为 DOWN 的时刻(见 is_available())

    def __post_init__(self) -> None:
        # base_url 规范化收口在类型本身:任何构造路径(发现/面板保存/持久化
        # 恢复)传进无协议头或空的 URL,都在这里一次修好,而不是指望每个
        # 调用点自己记得。空值对本地 provider 回退默认地址,避免运行时
        # 才炸 "Request URL is missing an 'http://' or 'https://' protocol."
        raw = (self.base_url or "").strip()
        if not raw and self.name == "ollama":
            raw = os.environ.get("OLLAMA_URL", "").strip() or "http://localhost:11434"
        if raw and not raw.startswith(("http://", "https://")):
            raw = f"http://{raw}"
        self.base_url = raw

    def is_available(self, recovery_seconds: float = 60.0) -> bool:
        """该 provider 现在是否该被当作候选。

        修复:status 字段一旦被打成 DOWN(连续 5 次失败),此前【没有任何自愈
        路径】——route()/route_multimodal_first()/route_with_cost_policy() 等
        十几处候选筛选全部一律排除 DOWN,而重新变回候选的唯一办法是成功调用
        一次；但 DOWN 的 provider 永远不会被选为候选,自然也永远没机会成功调用，
        于是一旦 DOWN 就【整个进程生命周期】卡死,除非手动触发 refresh_llm_router()
        (保存一次 llm 类配置)或重启——同一个类里的断路器(ProviderCircuitBreaker)
        反而设计对了(OPEN 到期自动进 HALF_OPEN 重新试探)，两套健康判断互相矛盾。
        这里让 DOWN 状态也按同样的冷却窗口自动过期，恢复候选资格，真正出问题时
        断路器仍会在 chat() 调用前再拦一道。
        """
        if self.status != ProviderStatus.DOWN:
            return True
        return bool(self.down_since) and (time.time() - self.down_since) >= recovery_seconds


@dataclass
class RoutingDecision:
    """路由决策"""
    provider: str
    model: str
    reason: str
    alternatives: List[str] = field(default_factory=list)


@dataclass
class LLMResponse:
    """统一响应"""
    content: str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    cost: float = 0.0
    tool_calls: Optional[List[Dict]] = None
    raw_response: Optional[Dict] = None


# ───────────────────── 路由策略 ─────────────────────

# PR-3: Local LLM provider role clarification.
# Ollama is a first-class local provider registered in the unified policy
# layer via MultiLLMRouter._discover_providers().  It participates in the
# provider selection logic when OLLAMA_URL is configured.  Its role in the
# routing preferences is as a low-priority fallback for GENERAL tasks,
# reflecting that local models typically have lower capability ceilings than
# remote API providers but do not require network access or API keys.
# Local VLM / multimodal providers (e.g. LLaVA served via Ollama) are
# NOT governed by this router; they are extension-layer capabilities handled
# via core/multimodal/* and are not part of the main-chain model supply.
LOCAL_LLM_PROVIDER_ROLE: str = (
    "MULTI_LLM_ROUTER::LOCAL_LLM_PROVIDER_ROLE_PR3: "
    "ollama is a registered local LLM provider in the unified routing policy "
    "layer.  It is eligible for GENERAL task fallback when OLLAMA_URL is set. "
    "Local VLM / multimodal providers are extension-layer capabilities, "
    "NOT governed by this router.  Closes PR-3 local-provider role clarity."
)

# _get_key() 短 provider 名 → 真实 .env / os.environ 长名的映射。
#
# 关键背景:_get_key() 在 _discover_providers() 里全部按短名调用(如
# self._get_key("deepseek")),但 .env / os.environ / UnifiedConfig._load_env()
# 存的都是长名(如 DEEPSEEK_API_KEY，小写存成 deepseek_api_key)——短名
# "deepseek" 从未真正命中过 unified_config 或 os.environ 里的任何一层，
# _get_key() 事实上只有 CredentialVault(层 2)显式按短名写入时才会命中，
# ENV/.env(层 1 的 flat 兜底 + 层 3)从未真正生效过。真机复现过:「模型」tab
# 存的任何 API Key(DeepSeek/OpenAI/Anthropic/……全部受影响，不止某一家)
# 保存当次生效(setConfig 同步写了 os.environ)，但重启新进程后一律读不回来。
_PROVIDER_ENV_KEY_MAP: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openai_base": "OPENAI_API_BASE",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "xai": "XAI_API_KEY",
    "meta": "META_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "QWEN_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "step": "STEP_API_KEY",
    "mimo": "MIMO_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "groq": "GROQ_API_KEY",
    "ollama": "OLLAMA_URL",
    "oneapi": "ONEAPI_API_KEY",
    "oneapi_url": "ONEAPI_URL",
}

# 任务类型 → 提供商优先级
# LOCAL-BRAIN-FIRST: Ollama 被移到第一位作为本地主脑优先策略。
# 只有本地模型不可用或能力不足时才回退到云端 API。
# 云端结果会回流到本地主脑进行整合。
TASK_ROUTING_PREFERENCES: Dict[TaskType, List[str]] = {
    # 本地主脑优先，API 专科后备
    # LOCAL-BRAIN-FIRST: hf_local (HuggingFace local models) are checked after ollama
    # 2026-05-29: 新增 minimax/step/mimo 三个国产提供商
    # 2026-07-10: 新增 meta(Muse Spark 1.1,agentic/多模态/1M ctx)——
    # 定位在专有兜底梯队,agentic 任务(AGENT_CONTROL/CODING/PLANNING)优先级靠前
    TaskType.REASONING:      ["ollama", "hf_local", "anthropic", "openai", "meta", "deepseek", "google", "qwen", "step"],
    TaskType.FAST_RESPONSE:  ["ollama", "hf_local", "deepseek", "mimo", "groq", "google", "openai", "zhipu"],
    TaskType.CODING:         ["ollama", "hf_local", "deepseek", "qwen", "anthropic", "openai", "meta", "step", "mimo"],
    TaskType.CREATIVE:       ["ollama", "hf_local", "openai", "anthropic", "mistral", "deepseek", "minimax"],
    TaskType.ANALYSIS:       ["ollama", "hf_local", "anthropic", "openai", "meta", "deepseek", "google", "perplexity", "qwen", "step"],
    TaskType.PLANNING:       ["ollama", "hf_local", "anthropic", "openai", "meta", "deepseek", "xai", "qwen", "minimax", "step"],
    TaskType.AGENT_CONTROL:  ["ollama", "hf_local", "anthropic", "openai", "meta", "deepseek", "minimax", "step"],
    TaskType.GENERAL:        ["ollama", "hf_local", "openai", "anthropic", "meta", "deepseek", "google", "qwen", "zhipu", "minimax", "step", "mimo"],
}

# ───────────────────────────────────────────────────────────────────────────
# 开源优先策略（OPEN-SOURCE-FIRST）
# ───────────────────────────────────────────────────────────────────────────
# 用户设计：以开源模型为主。本地原生多模态主脑(ollama/hf_local)是基座；
# 云端调用也优先开源模型 API（DeepSeek/Qwen/GLM/Llama-via-groq 等），
# 专有模型(OpenAI/Anthropic/Google/xAI)作为可选高端兜底，排在最后。
#
# 当 GALAXY_OPENSOURCE_FIRST != "false"（默认开启）时，route() 会把开源
# 提供商整体提到专有提供商之前，同时严格保持各自原有的任务偏好相对顺序。
OPEN_SOURCE_PROVIDERS: set = {
    "ollama",      # 本地原生多模态主脑（Gemma4 / MiniCPM-o）
    "hf_local",    # 本地 HuggingFace 模型
    "deepseek",    # DeepSeek（开源权重）
    "qwen",        # 通义千问（开源权重）
    "zhipu",       # 智谱 GLM（开源权重）
    "groq",        # Groq 托管 Llama 等开源模型
    "minimax",     # MiniMax（部分开源）
    "step",        # 阶跃 StepFun
    "mimo",        # 小米 MiMo（开源）
    "moonshot",    # Kimi / Moonshot（Kimi-K2 开源）
    "mistral",     # Mistral（开源权重）
    "oneapi",      # OneAPI 聚合层（通常聚合开源模型）
}

# 专有闭源提供商（仅作高端兜底，开源优先时排最后）
PROPRIETARY_PROVIDERS: set = {
    "openai", "anthropic", "google", "xai", "perplexity",
}


def reorder_open_source_first(provider_order: List[str]) -> List[str]:
    """把开源提供商整体前移到专有提供商之前，保持各自原相对顺序（稳定排序）。

    纯函数、无副作用，便于单测。未知提供商按"开源"处理（更符合本仓库以开源
    自托管/聚合为主的现状），不会被错误地降级到专有兜底之后。
    """
    open_src = [p for p in provider_order if p not in PROPRIETARY_PROVIDERS]
    proprietary = [p for p in provider_order if p in PROPRIETARY_PROVIDERS]
    return open_src + proprietary


# ───────────────────────────────────────────────────────────────────────────
# 角色 → 脑 绑定（大小模型配合的执行层映射）
# ───────────────────────────────────────────────────────────────────────────
# Octo 式多 Agent 协作里，每个角色绑定"最便宜够用"的脑：
#   - 执行/感知类角色 → 本地小模型优先（便宜、私密、够用）
#   - 审核/推理/协调类角色 → 开源大模型 API 优先（更强、攻坚/把关）
# 返回值由 select_brain_for_role() 解析为具体 (provider, model)。
ROLE_BRAIN_HINTS: Dict[str, Dict[str, Any]] = {
    # 重角色：需要强推理 / 质量把关 → 倾向云端开源大模型
    "critic":      {"prefer_local": False, "task_type": TaskType.REASONING, "min_complexity": 0.7},
    "reviewer":    {"prefer_local": False, "task_type": TaskType.REASONING, "min_complexity": 0.7},
    "reasoner":    {"prefer_local": False, "task_type": TaskType.REASONING, "min_complexity": 0.7},
    "coordinator": {"prefer_local": False, "task_type": TaskType.PLANNING,  "min_complexity": 0.6},
    "planner":     {"prefer_local": False, "task_type": TaskType.PLANNING,  "min_complexity": 0.6},
    "analyst":     {"prefer_local": False, "task_type": TaskType.ANALYSIS,  "min_complexity": 0.6},
    # 轻角色：执行/产出/感知 → 倾向本地小模型
    "executor":    {"prefer_local": True,  "task_type": TaskType.FAST_RESPONSE, "min_complexity": 0.0},
    "worker":      {"prefer_local": True,  "task_type": TaskType.GENERAL,       "min_complexity": 0.0},
    "researcher":  {"prefer_local": True,  "task_type": TaskType.GENERAL,       "min_complexity": 0.0},
    "coder":       {"prefer_local": True,  "task_type": TaskType.CODING,        "min_complexity": 0.3},
    "writer":      {"prefer_local": True,  "task_type": TaskType.CREATIVE,      "min_complexity": 0.0},
}

# ───────────────────────────────────────────────────────────────────────────
# 做任务的"按实际情况选模型"——能力质量分层（粗粒度，可经 env 覆盖）
# ───────────────────────────────────────────────────────────────────────────
# 用户规则：做任务时【能力最强优先】，适度看 token，按需看延迟。
# 这里给每个提供商一个粗略"能力档"（3=前沿/最强, 2=强, 1=本地轻量）。
# 注意：这是质量导向，区别于 TASK_ROUTING_PREFERENCES（那是交流基座的本地/开源优先）。
# DeepSeek/Qwen/GLM 等强开源模型同列 tier 3，确保"以开源为主"也能拿到最强档。
PROVIDER_QUALITY_TIER: Dict[str, int] = {
    # tier 3 —— 前沿能力（含强开源大模型）
    "anthropic": 3, "openai": 3, "google": 3, "xai": 3,
    "deepseek": 3, "qwen": 3, "zhipu": 3,
    # tier 2 —— 强
    "minimax": 2, "step": 2, "moonshot": 2, "mistral": 2,
    "groq": 2, "mimo": 2, "perplexity": 2, "oneapi": 2,
    # tier 1 —— 本地轻量（无 GPU 笔电主脑）
    "ollama": 1, "hf_local": 1,
}


def _provider_quality_tier(name: str) -> int:
    """读提供商能力档；支持 env 覆盖 GALAXY_QUALITY_TIER_<PROVIDER>=N。"""
    import os as _os
    ov = _os.environ.get(f"GALAXY_QUALITY_TIER_{name.upper()}")
    if ov:
        try:
            return int(ov)
        except ValueError:
            pass
    return PROVIDER_QUALITY_TIER.get(name, 2)


# 提供商 → 推荐模型 (2026-05-29 全面更新)
PROVIDER_MODEL_MAP: Dict[str, Dict[TaskType, str]] = {
    "openai": {
        # GPT-5.6 家族(2026-07-09 GA):gpt-5.6 = 旗舰 Sol 的别名(1.05M ctx/128K out);
        # terra=日常均衡($2.5/$15);luna=快而省($1/$6)。
        TaskType.REASONING:     "gpt-5.6",
        TaskType.FAST_RESPONSE: "gpt-5.6-luna",
        TaskType.CODING:        "gpt-5.6",
        TaskType.CREATIVE:      "gpt-5.6",
        TaskType.ANALYSIS:      "gpt-5.6",
        TaskType.PLANNING:      "gpt-5.6",
        TaskType.AGENT_CONTROL: "gpt-5.6",
        TaskType.GENERAL:       "gpt-5.6-terra",
    },
    "anthropic": {
        TaskType.REASONING:     "claude-opus-4-8-20250529",
        TaskType.FAST_RESPONSE: "claude-sonnet-5",
        TaskType.CODING:        "claude-sonnet-5",
        TaskType.CREATIVE:      "claude-opus-4-8-20250529",
        TaskType.ANALYSIS:      "claude-opus-4-8-20250529",
        TaskType.PLANNING:      "claude-opus-4-8-20250529",
        TaskType.AGENT_CONTROL: "claude-sonnet-5",
        TaskType.GENERAL:       "claude-sonnet-5",
    },
    "google": {
        # 注:gemini-3.5-pro 延期到 2026-07-17 才发布——此前表里引用它会 404。
        # 现全走 GA 的 3.5-flash;Pro 上线后把 CODING/PLANNING/AGENT 升回去。
        TaskType.REASONING:     "gemini-3.5-flash",
        TaskType.FAST_RESPONSE: "gemini-3.5-flash",
        TaskType.CODING:        "gemini-3.5-flash",
        TaskType.CREATIVE:      "gemini-3.5-flash",
        TaskType.ANALYSIS:      "gemini-3.5-flash",
        TaskType.PLANNING:      "gemini-3.5-flash",
        TaskType.AGENT_CONTROL: "gemini-3.5-flash",
        TaskType.GENERAL:       "gemini-3.5-flash",
    },
    "meta": {
        # Muse Spark 1.1(2026-07-09,Meta Superintelligence Labs):Llama 后继,
        # Meta Model API 首发唯一模型。多模态推理+agentic(工具/电脑使用/编码),
        # 1M ctx,OpenAI SDK 兼容(api.meta.ai/v1),$1.25/$4.25 每 M tokens。
        TaskType.REASONING:     "muse-spark-1.1",
        TaskType.FAST_RESPONSE: "muse-spark-1.1",
        TaskType.CODING:        "muse-spark-1.1",
        TaskType.CREATIVE:      "muse-spark-1.1",
        TaskType.ANALYSIS:      "muse-spark-1.1",
        TaskType.PLANNING:      "muse-spark-1.1",
        TaskType.AGENT_CONTROL: "muse-spark-1.1",
        TaskType.GENERAL:       "muse-spark-1.1",
    },
    "xai": {
        TaskType.REASONING:     "grok-4.5",
        TaskType.FAST_RESPONSE: "grok-4.5",
        TaskType.CODING:        "grok-4.5",
        TaskType.CREATIVE:      "grok-4.5",
        TaskType.ANALYSIS:      "grok-4.5",
        TaskType.PLANNING:      "grok-4.5",
        TaskType.AGENT_CONTROL: "grok-4.5",
        TaskType.GENERAL:       "grok-4.5",
    },
    "mistral": {
        TaskType.REASONING:     "mistral-large-3",
        TaskType.FAST_RESPONSE: "mistral-large-3",
        TaskType.CODING:        "mistral-large-3",
        TaskType.CREATIVE:      "mistral-large-3",
        TaskType.ANALYSIS:      "mistral-large-3",
        TaskType.PLANNING:      "mistral-large-3",
        TaskType.AGENT_CONTROL: "mistral-large-3",
        TaskType.GENERAL:       "mistral-large-3",
    },
    "deepseek": {
        TaskType.REASONING:     "deepseek-v4-pro",
        TaskType.FAST_RESPONSE: "deepseek-v4-flash",
        TaskType.CODING:        "deepseek-v4-pro",
        TaskType.CREATIVE:      "deepseek-v4-pro",
        TaskType.ANALYSIS:      "deepseek-v4-pro",
        TaskType.PLANNING:      "deepseek-v4-pro",
        TaskType.AGENT_CONTROL: "deepseek-v4-pro",
        TaskType.GENERAL:       "deepseek-v4-pro",
    },
    "qwen": {
        TaskType.REASONING:     "qwen3.7-max",
        TaskType.CODING:        "qwen3.7-coder",
        TaskType.FAST_RESPONSE: "qwen-flash",
        TaskType.GENERAL:       "qwen3.7-max",
        TaskType.ANALYSIS:      "qwen3.7-max",
        TaskType.PLANNING:      "qwen3.7-max",
        TaskType.AGENT_CONTROL: "qwen3.7-max",
    },
    "zhipu": {
        TaskType.REASONING:     "glm-5.1",
        TaskType.GENERAL:       "glm-5.1",
        TaskType.ANALYSIS:      "glm-5.1",
        TaskType.CODING:        "glm-5.1",
        TaskType.FAST_RESPONSE: "glm-5.1-flash",
        TaskType.CREATIVE:      "glm-5.1",
        TaskType.PLANNING:      "glm-5.1",
    },
    "minimax": {
        TaskType.REASONING:     "minimax-m2.7",
        TaskType.FAST_RESPONSE: "minimax-m2.7",
        TaskType.CODING:        "minimax-m2.7",
        TaskType.CREATIVE:      "minimax-m2.7",
        TaskType.ANALYSIS:      "minimax-m2.7",
        TaskType.PLANNING:      "minimax-m2.7",
        TaskType.AGENT_CONTROL: "minimax-m2.7",
        TaskType.GENERAL:       "minimax-m2.7",
    },
    "step": {
        TaskType.REASONING:     "step-3.7-flash",
        TaskType.FAST_RESPONSE: "step-3.7-turbo",
        TaskType.CODING:        "step-3.7-flash",
        TaskType.CREATIVE:      "step-3.7-flash",
        TaskType.ANALYSIS:      "step-3.7-flash",
        TaskType.PLANNING:      "step-3.7-flash",
        TaskType.AGENT_CONTROL: "step-3.7-flash",
        TaskType.GENERAL:       "step-3.7-flash",
    },
    "mimo": {
        TaskType.REASONING:     "mimo-v2.5-pro",
        TaskType.FAST_RESPONSE: "mimo-v2.5-lite",
        TaskType.CODING:        "mimo-v2.5-pro",
        TaskType.CREATIVE:      "mimo-v2.5-pro",
        TaskType.ANALYSIS:      "mimo-v2.5-pro",
        TaskType.PLANNING:      "mimo-v2.5-pro",
        TaskType.AGENT_CONTROL: "mimo-v2.5-pro",
        TaskType.GENERAL:       "mimo-v2.5-pro",
    },
    "moonshot": {
        # Kimi K2 系取代老 moonshot-v1-*:k2.6=最新最强(代码/agent);
        # k2.5=原生多模态 256K 长上下文(2026-01 开源权重)。
        TaskType.GENERAL:       "kimi-k2.6",
        TaskType.CODING:        "kimi-k2.6",
        TaskType.ANALYSIS:      "kimi-k2.5",
        TaskType.FAST_RESPONSE: "kimi-k2.5",
    },
    "perplexity": {
        TaskType.REASONING:     "sonar-deep-research",
        TaskType.ANALYSIS:      "sonar-pro",
        TaskType.GENERAL:       "sonar-pro",
    },
    "groq": {
        TaskType.FAST_RESPONSE: "llama-3.3-70b-versatile",
        TaskType.GENERAL:       "llama-3.3-70b-versatile",
    },
    "ollama": {
        TaskType.REASONING:     "gemma4:12b",
        TaskType.FAST_RESPONSE: "gemma4:e4b",
        TaskType.CODING:        "gemma4:12b",
        TaskType.CREATIVE:      "gemma4:12b",
        TaskType.ANALYSIS:      "gemma4:26b",
        TaskType.PLANNING:      "gemma4:26b",
        TaskType.AGENT_CONTROL: "gemma4:12b",
        TaskType.GENERAL:       "gemma4:e4b",
    },
    "hf_local": {
        TaskType.REASONING:     "Qwen/Qwen2.5-14B-Instruct",
        TaskType.FAST_RESPONSE: "Qwen/Qwen2.5-3B-Instruct",
        TaskType.CODING:        "Qwen/Qwen2.5-Coder-14B-Instruct",
        TaskType.CREATIVE:      "Qwen/Qwen2.5-14B-Instruct",
        TaskType.ANALYSIS:      "Qwen/Qwen2.5-14B-Instruct",
        TaskType.PLANNING:      "Qwen/Qwen2.5-14B-Instruct",
        TaskType.AGENT_CONTROL: "Qwen/Qwen2.5-14B-Instruct",
        TaskType.GENERAL:       "Qwen/Qwen2.5-14B-Instruct",
    },
}


# ───────────────────── 提供商适配器 ─────────────────────

class ProviderCircuitBreaker:
    """
    提供商级别断路器

    状态：CLOSED → OPEN → HALF_OPEN → CLOSED
    - CLOSED: 正常调用
    - OPEN: 连续失败达到阈值，拒绝调用，等待恢复
    - HALF_OPEN: 恢复期，允许少量试探性调用
    """

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: float = 60.0, half_open_max_calls: int = 2):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._consecutive_failures = 0
        self._state = "closed"  # closed, open, half_open
        self._last_failure_time = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> str:
        if self._state == "open":
            # 检查是否应该进入半开状态
            if time.time() - self._last_failure_time >= self.recovery_timeout:
                self._state = "half_open"
                self._half_open_calls = 0
                logger.info(f"断路器 [{self.name}] OPEN → HALF_OPEN (尝试恢复)")
        return self._state

    def allow_request(self) -> bool:
        """是否允许请求通过"""
        s = self.state
        if s == "closed":
            return True
        if s == "half_open":
            return self._half_open_calls < self.half_open_max_calls
        return False  # open

    def record_success(self):
        """记录成功调用"""
        if self._state == "half_open":
            self._consecutive_failures = 0
            self._state = "closed"
            logger.info(f"断路器 [{self.name}] HALF_OPEN → CLOSED (恢复成功)")
        else:
            self._consecutive_failures = 0

    def record_failure(self):
        """记录失败调用"""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()

        if self._state == "half_open":
            self._half_open_calls += 1
            if self._half_open_calls >= self.half_open_max_calls:
                self._state = "open"
                logger.warning(f"断路器 [{self.name}] HALF_OPEN → OPEN (恢复失败)")
        elif self._consecutive_failures >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                f"断路器 [{self.name}] CLOSED → OPEN "
                f"(连续 {self._consecutive_failures} 次失败)"
            )

    def to_dict(self) -> Dict:
        return {
            "state": self.state,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class BaseProviderAdapter:
    """提供商适配器基类"""

    DEFAULT_TIMEOUT = 30.0    # 默认请求超时
    MAX_RETRIES = 2           # 最大重试次数
    RETRY_BASE_DELAY = 1.0    # 重试基础延迟

    # HTTP status codes that are safe to retry (transient errors)
    _RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

    async def _post_with_retry(
        self,
        url: str,
        headers: Dict[str, str],
        body: Dict[str, Any],
    ) -> httpx.Response:
        """POST request with automatic retry on transient failures (timeout, 5xx, 429).

        Uses exponential backoff: RETRY_BASE_DELAY * 2^attempt seconds between retries.
        Falls through to raise on non-retryable errors immediately.
        """
        client = await self._get_client()
        last_exc: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                resp = await client.post(url, headers=headers, json=body)
                if resp.status_code in self._RETRYABLE_STATUS_CODES and attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Retryable HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                        resp.status_code, self.config.name, attempt + 1, self.MAX_RETRIES + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "Timeout from %s (attempt %d/%d), retrying in %.1fs",
                        self.config.name, attempt + 1, self.MAX_RETRIES + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except httpx.HTTPStatusError:
                # Non-retryable HTTP error, raise immediately
                raise
        # Should not reach here, but just in case
        if last_exc:
            raise last_exc
        raise RuntimeError(f"Exhausted retries for {self.config.name}")

    async def chat(self, messages: List[Dict], model: str,
                   tools: Optional[List[Dict]] = None,
                   temperature: float = 0.7,
                   max_tokens: int = 4096,
                   response_format: Optional[Dict] = None,
                   **kwargs) -> LLMResponse:
        raise NotImplementedError(
            f"Provider adapter '{self.config.name}' 未实现 chat()，"
            f"请使用具体的适配器子类 (OpenAI/Anthropic/Google/DeepSeek)"
        )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class OpenAIAdapter(BaseProviderAdapter):
    """OpenAI / OpenAI-compatible adapter"""

    async def chat(self, messages, model, tools=None,
                   temperature=0.7, max_tokens=4096,
                   response_format=None, **kwargs) -> LLMResponse:
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools
        if response_format:
            body["response_format"] = response_format

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/chat/completions",
            headers=headers, body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})
        tool_calls = None
        if choice["message"].get("tool_calls"):
            tool_calls = [tc for tc in choice["message"]["tool_calls"]]

        return LLMResponse(
            content=choice["message"].get("content") or "",
            provider=self.config.name,
            model=model,
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=latency,
            tool_calls=tool_calls,
            raw_response=data,
        )


class AnthropicAdapter(BaseProviderAdapter):
    """Anthropic Claude adapter (Messages API)"""

    async def chat(self, messages, model, tools=None,
                   temperature=0.7, max_tokens=4096,
                   response_format=None, **kwargs) -> LLMResponse:
        headers = {
            "x-api-key": self.config.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        # 从 messages 提取 system
        system_text = ""
        user_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                user_messages.append(m)

        body: Dict[str, Any] = {
            "model": model,
            "messages": user_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_text.strip():
            body["system"] = system_text.strip()
        if tools:
            # 转换 OpenAI tool 格式 → Anthropic tool 格式
            body["tools"] = self._convert_tools(tools)

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/messages",
            headers=headers, body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        content = ""
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {
                        "name": block["name"],
                        "arguments": json.dumps(block["input"]),
                    }
                })

        usage = data.get("usage", {})
        return LLMResponse(
            content=content,
            provider=self.config.name,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=latency,
            tool_calls=tool_calls if tool_calls else None,
            raw_response=data,
        )

    @staticmethod
    def _convert_tools(openai_tools: List[Dict]) -> List[Dict]:
        """OpenAI tool format → Anthropic tool format"""
        anthropic_tools = []
        for t in openai_tools:
            if t.get("type") == "function":
                fn = t["function"]
                anthropic_tools.append({
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                })
        return anthropic_tools


class DeepSeekAdapter(OpenAIAdapter):
    """DeepSeek uses OpenAI-compatible API"""
    pass


class GroqAdapter(OpenAIAdapter):
    """Groq uses OpenAI-compatible API"""
    pass


class OllamaAdapter(BaseProviderAdapter):
    """Ollama local model adapter"""

    @staticmethod
    def _to_ollama_messages(messages):
        """把消息规范成 Ollama 原生格式，让本地多模态模型(Gemma4/MiniCPM-o)真正"看到"图像。

        Ollama /api/chat 的图像约定：在 message 上挂 ``images: ["<base64>", ...]``（纯 base64，
        不含 data: 前缀）。上游可能用 OpenAI 风格的 ``content: [{type:"text"...},
        {type:"image_url", image_url:{url:"data:image/..;base64,XXXX"}}]``，也可能已带 ``images``。
        这里统一抽取：文本部分拼回 content 字符串，图像部分收进 images 数组。无图则原样返回。
        """
        out = []
        for m in messages:
            if not isinstance(m, dict):
                out.append(m)
                continue
            content = m.get("content")
            imgs = list(m.get("images") or [])
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if not isinstance(part, dict):
                        text_parts.append(str(part))
                        continue
                    ptype = part.get("type")
                    if ptype == "text":
                        text_parts.append(part.get("text", ""))
                    elif ptype in ("image_url", "image"):
                        url = ""
                        if isinstance(part.get("image_url"), dict):
                            url = part["image_url"].get("url", "")
                        else:
                            url = part.get("image_url") or part.get("data") or part.get("image", "")
                        if isinstance(url, str) and url:
                            # 去掉 data:image/...;base64, 前缀
                            imgs.append(url.split(",", 1)[1] if url.startswith("data:") else url)
                new_m = {**m, "content": "\n".join(t for t in text_parts if t)}
            else:
                new_m = {**m}
            if imgs:
                new_m["images"] = imgs
            elif "images" in new_m and not new_m["images"]:
                new_m.pop("images", None)
            out.append(new_m)
        return out

    async def chat(self, messages, model, tools=None,
                   temperature=0.7, max_tokens=4096,
                   response_format=None, **kwargs) -> LLMResponse:
        body = {
            "model": model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        # 调用点兜底:即使 config.base_url 因某条边缘路径被置空/缺协议头,
        # 也在此归一,绝不把坏 URL 交给 httpx(否则炸 "Request URL is missing
        # an 'http://' or 'https://' protocol")。
        _base = (self.config.base_url or "").strip() or "http://localhost:11434"
        if not _base.startswith(("http://", "https://")):
            _base = f"http://{_base}"
        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{_base}/api/chat",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        return LLMResponse(
            content=data.get("message", {}).get("content", ""),
            provider=self.config.name,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=latency,
            raw_response=data,
        )


# OpenAI-compatible adapters — no additional code needed, all reuse OpenAIAdapter
class GoogleAdapter(OpenAIAdapter):
    """Google Gemini via OpenAI-compatible endpoint (generativelanguage.googleapis.com)"""
    pass


class GrokAdapter(OpenAIAdapter):
    """xAI Grok via OpenAI-compatible API (api.x.ai)"""
    pass


class MetaAdapter(OpenAIAdapter):
    """Meta Muse Spark via OpenAI-compatible Meta Model API (api.meta.ai)"""
    pass


class MistralAdapter(OpenAIAdapter):
    """Mistral AI via OpenAI-compatible API (api.mistral.ai)"""
    pass


class QwenAdapter(OpenAIAdapter):
    """Alibaba Qwen via Together AI OpenAI-compatible endpoint"""
    pass


class ZhipuAdapter(OpenAIAdapter):
    """Zhipu GLM via OpenAI-compatible API (open.bigmodel.cn)"""
    pass


class MoonshotAdapter(OpenAIAdapter):
    """Moonshot Kimi via OpenAI-compatible API (api.moonshot.cn)"""
    pass


class PerplexityAdapter(OpenAIAdapter):
    """Perplexity Sonar via OpenAI-compatible API (api.perplexity.ai)"""
    pass


class MiniMaxAdapter(OpenAIAdapter):
    """MiniMax via OpenAI-compatible API (api.minimax.chat)"""
    pass


class StepAdapter(OpenAIAdapter):
    """阶跃星辰 Step via OpenAI-compatible API (api.stepfun.com)"""
    pass


class MiMoAdapter(OpenAIAdapter):
    """小米 MiMo via OpenAI-compatible API (api.xiaomimimo.com)"""
    pass


# ───────────────────── 主路由器 ─────────────────────

ADAPTER_MAP = {
    "openai":     OpenAIAdapter,
    "anthropic":  AnthropicAdapter,
    "google":     GoogleAdapter,
    "xai":        GrokAdapter,
    "mistral":    MistralAdapter,
    "deepseek":   DeepSeekAdapter,
    "qwen":       QwenAdapter,
    "zhipu":      ZhipuAdapter,
    "minimax":    MiniMaxAdapter,
    "step":       StepAdapter,
    "mimo":       MiMoAdapter,
    "moonshot":   MoonshotAdapter,
    "perplexity": PerplexityAdapter,
    "groq":       GroqAdapter,
    "ollama":     OllamaAdapter,
    "hf_local":   OpenAIAdapter,
}


# PR-515 / GAP-512-009: MultiLLMRouter is the MODEL SELECTION AUTHORITY
# (distinct from CommandRouter's COMMAND_ORCHESTRATION_AUTHORITY).
MODEL_SELECTION_AUTHORITY_INTEGRATED: str = (
    "MULTI_LLM_ROUTER::MODEL_SELECTION_AUTHORITY_INTEGRATED_V1: "
    "core/multi_llm_router.py is the canonical model-selection authority "
    "for multi-model provider selection.  "
    "This is NOT command orchestration authority — that belongs to "
    "core.command_router.CommandRouter.  "
    "PR-515 CriticalPathHarness records model-selection decisions."
)

# DEPRECATED-COMPAT: old name retained for backward compatibility.
# Use MODEL_SELECTION_AUTHORITY_INTEGRATED for new code.
CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED: str = MODEL_SELECTION_AUTHORITY_INTEGRATED


class MultiLLMRouter:
    """
    多 LLM 智能路由器

    功能：
    - 自动发现已配置的提供商（通过环境变量）
    - 根据任务类型智能选择提供商和模型
    - 故障转移：如果首选提供商失败，自动尝试下一个
    - 延迟跟踪和健康检查
    - 统一的调用接口
    """

    def __init__(self):
        self.providers: Dict[str, ProviderConfig] = {}
        self.adapters: Dict[str, BaseProviderAdapter] = {}
        self.circuit_breakers: Dict[str, ProviderCircuitBreaker] = {}
        self.call_history: List[Dict] = []
        self._lock = asyncio.Lock()
        # PR86: 最近一次路由决策（供 OpenClawd 日志使用）
        self._last_provider: str = ""
        self._last_model: str = ""
        self._discover_providers()
        # 为每个提供商创建断路器
        for name in self.providers:
            self.circuit_breakers[name] = ProviderCircuitBreaker(name)

    def _get_key(self, key_name: str) -> str:
        """配置优先级: Dashboard > CredentialVault > ENV（PR86）

        key_name 是内部短 provider 名(如 "deepseek")，与 .env/os.environ 里的
        真实长名(如 "DEEPSEEK_API_KEY")不是一回事——见模块级
        _PROVIDER_ENV_KEY_MAP 顶部注释：之前三层查找全部只按短名查，从未真正
        从 .env/环境变量取到过值。这里同时尝试短名(保留，兼容任何显式按短名
        写入 Dashboard/Vault 的历史数据)和真实长名(修复 .env/环境变量这条路)。
        """
        real_env_key = _PROVIDER_ENV_KEY_MAP.get(key_name, key_name)
        # 1. Dashboard 配置（最高优先级）— 通过 UnifiedConfig 获取
        try:
            from core.unified_config import config as _cfg
            # Dashboard 将 API keys 存储在 llm.providers.<name>.api_key 路径
            val = _cfg.get(f"llm.providers.{key_name}.api_key", "")
            if not val:
                val = _cfg.get(f"api_keys.{key_name}", "")
            if not val and real_env_key != key_name:
                # 修复:.env/UnifiedConfig._load_env() 按真实长名(小写)存储，
                # 短名从未命中过——补上按长名查询。
                val = _cfg.get(f"api_keys.{real_env_key}", "")
            if val and not str(val).startswith("your-"):
                return str(val)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        # 2. CredentialVault
        try:
            from core.credential_vault import get_vault
            val = get_vault().get_credential(key_name, actor="llm_router")
            if val:
                return val
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        # 3. 环境变量（兜底）—— 修复:优先用真实长名查(.env/系统环境变量都是
        # 这个约定)，短名查询保留作最后兜底(不改变既有行为)。
        val = os.environ.get(real_env_key, "")
        if val:
            return val
        return os.environ.get(key_name.upper() if "_" in key_name else key_name, "")

    @staticmethod
    def _normalize_base_url(raw: str) -> str:
        """确保 URL 带 http(s):// 协议头。

        真机复现过:用户在面板「模型」tab 填 OLLAMA_URL/ONEAPI_URL 时只填了
        host:port(如 "localhost:11434"),没带协议头。这个值不做任何校验就被
        原样存进 base_url,直到实际发起请求时 httpx 才会炸
        ``InvalidURL: Request URL is missing an 'http://' or 'https://' protocol.``——
        用户看到的只是一句"LLM 调用失败",完全不知道是哪个字段少打了几个字符。
        这里在读到手动配置的 URL 时统一兜底补全协议头，而不是要求每个调用点
        都自己记得判断。
        """
        raw = (raw or "").strip()
        if raw and not raw.startswith(("http://", "https://")):
            raw = f"http://{raw}"
        return raw

    @staticmethod
    def _internal_hf_adapter_alive(base_url: str) -> bool:
        """探测 hf_local 内部适配服务是否真的在监听(见 _discover_providers)。"""
        try:
            import httpx
            root = base_url.split("/v1/")[0]
            httpx.get(root, timeout=1.0)
            return True
        except Exception:
            return False

    def _discover_providers(self):
        """从配置源自动发现并注册提供商（Dashboard > ENV > defaults）（PR86）"""

        # OpenAI
        key = self._get_key("openai")
        if not key:
            key = os.environ.get("OPENAI_API_KEY", "")
        if key and not key.startswith("your-"):
            # OPENAI_API_BASE="" (面板保存空值)会让 .get(k, default) 返回 ""——
            # 显式回退默认地址,避免 base_url 为空导致请求时炸缺协议头。
            base = (self._get_key("openai_base") or os.environ.get("OPENAI_API_BASE", "") or "").strip()
            if not base:
                base = "https://api.openai.com/v1"
            cfg = ProviderConfig(
                name="openai", api_key=key, base_url=base,
                models=["gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-4o"],
                default_model="gpt-5.6",
                cost_per_1k_input=0.005, cost_per_1k_output=0.015,
                multimodal=True, env_key="OPENAI_API_KEY",
            )
            self.providers["openai"] = cfg
            self.adapters["openai"] = OpenAIAdapter(cfg)

        # Anthropic
        key = self._get_key("anthropic")
        if not key:
            key = os.environ.get("ANTHROPIC_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="anthropic", api_key=key,
                base_url="https://api.anthropic.com/v1",
                models=["claude-opus-4-8-20250529", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
                default_model="claude-sonnet-5",
                cost_per_1k_input=0.003, cost_per_1k_output=0.015,
                multimodal=True, env_key="ANTHROPIC_API_KEY",
            )
            self.providers["anthropic"] = cfg
            self.adapters["anthropic"] = AnthropicAdapter(cfg)

        # Google Gemini (OpenAI-compatible endpoint)
        key = self._get_key("google")
        if not key:
            key = os.environ.get("GOOGLE_API_KEY", "") or os.environ.get("GEMINI_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="google", api_key=key,
                base_url="https://generativelanguage.googleapis.com/v1beta/openai",
                models=["gemini-3.5-flash", "gemini-3.5-pro", "gemini-2.5-pro"],
                default_model="gemini-3.5-flash",
                cost_per_1k_input=0.00125, cost_per_1k_output=0.005,
                multimodal=True, env_key="GOOGLE_API_KEY",
            )
            self.providers["google"] = cfg
            self.adapters["google"] = GoogleAdapter(cfg)

        # xAI Grok
        key = self._get_key("xai")
        if not key:
            key = os.environ.get("XAI_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="xai", api_key=key,
                base_url="https://api.x.ai/v1",
                models=["grok-4.5", "grok-4.3"],
                default_model="grok-4.5",
                cost_per_1k_input=0.005, cost_per_1k_output=0.015,
                multimodal=True, env_key="XAI_API_KEY",
            )
            self.providers["xai"] = cfg
            self.adapters["xai"] = GrokAdapter(cfg)

        # Meta Muse Spark(Meta Model API,2026-07-09 公测)
        key = self._get_key("meta")
        if not key:
            key = os.environ.get("META_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="meta", api_key=key,
                base_url="https://api.meta.ai/v1",
                models=["muse-spark-1.1"],
                default_model="muse-spark-1.1",
                max_tokens=8192,
                cost_per_1k_input=0.00125, cost_per_1k_output=0.00425,
                multimodal=True, supports_vision=True,
                env_key="META_API_KEY",
            )
            self.providers["meta"] = cfg
            self.adapters["meta"] = MetaAdapter(cfg)

        # Mistral
        key = self._get_key("mistral")
        if not key:
            key = os.environ.get("MISTRAL_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="mistral", api_key=key,
                base_url="https://api.mistral.ai/v1",
                models=["mistral-large-3", "mistral-medium-3", "mistral-large-2"],
                default_model="mistral-large-3",
                cost_per_1k_input=0.002, cost_per_1k_output=0.006,
                multimodal=True, env_key="MISTRAL_API_KEY",
            )
            self.providers["mistral"] = cfg
            self.adapters["mistral"] = MistralAdapter(cfg)

        # DeepSeek (V4-Pro: 2026-04-24发布, 2026-05-22永久降价75%)
        key = self._get_key("deepseek")
        if not key:
            key = os.environ.get("DEEPSEEK_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="deepseek", api_key=key,
                base_url="https://api.deepseek.com/v1",
                models=["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
                default_model="deepseek-v4-pro",
                cost_per_1k_input=0.000025, cost_per_1k_output=0.00006,
                multimodal=False, env_key="DEEPSEEK_API_KEY",
            )
            self.providers["deepseek"] = cfg
            self.adapters["deepseek"] = DeepSeekAdapter(cfg)

        # Qwen 3.7 Max (阿里云, 2026-05-20发布, 1M上下文)
        key = self._get_key("qwen")
        if not key:
            key = os.environ.get("QWEN_API_KEY", "") or os.environ.get("DASHSCOPE_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="qwen", api_key=key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                models=["qwen3.7-max", "qwen3.7-coder", "qwen3-235b-a22b"],
                default_model="qwen3.7-max",
                cost_per_1k_input=0.0025, cost_per_1k_output=0.0075,
                multimodal=True, env_key="QWEN_API_KEY",
            )
            self.providers["qwen"] = cfg
            self.adapters["qwen"] = QwenAdapter(cfg)

        # Zhipu GLM-5.1 (智谱AI, 2026-04-08发布, 开源, 2026-05-22高速版400tokens/s)
        key = self._get_key("zhipu")
        if not key:
            key = os.environ.get("ZHIPU_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="zhipu", api_key=key,
                base_url="https://open.bigmodel.cn/api/paas/v4",
                models=["glm-5.1", "glm-5.1-flash", "glm-4-plus"],
                default_model="glm-5.1",
                cost_per_1k_input=0.001, cost_per_1k_output=0.001,
                multimodal=True, env_key="ZHIPU_API_KEY",
            )
            self.providers["zhipu"] = cfg
            self.adapters["zhipu"] = ZhipuAdapter(cfg)

        # MiniMax M2.7 (2026-03-18发布, 支持Agent自主规划多工具调用)
        key = self._get_key("minimax")
        if not key:
            key = os.environ.get("MINIMAX_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="minimax", api_key=key,
                base_url="https://api.minimax.chat/v1",
                models=["minimax-m2.7", "minimax-m2.5", "minimax-text-01"],
                default_model="minimax-m2.7",
                cost_per_1k_input=0.001, cost_per_1k_output=0.004,
                multimodal=False, env_key="MINIMAX_API_KEY",
            )
            self.providers["minimax"] = cfg
            self.adapters["minimax"] = MiniMaxAdapter(cfg)

        # Step 3.7 Flash (阶跃星辰, 2026-05-29发布并开源, 稀疏MoE 196B总参/11B激活, 原生多模态Agent)
        key = self._get_key("step")
        if not key:
            key = os.environ.get("STEP_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="step", api_key=key,
                base_url="https://api.stepfun.com/v1",
                models=["step-3.7-flash", "step-3.7-turbo", "step-3.7-mini"],
                default_model="step-3.7-flash",
                cost_per_1k_input=0.001, cost_per_1k_output=0.004,
                multimodal=True, env_key="STEP_API_KEY",
            )
            self.providers["step"] = cfg
            self.adapters["step"] = StepAdapter(cfg)

        # MiMo V2.5 Pro (小米, 2026-04-22公测, 256K上下文, 强化学习Agent, 2026-05-27降价99%)
        key = self._get_key("mimo")
        if not key:
            key = os.environ.get("MIMO_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="mimo", api_key=key,
                # 联网核实:小米 MiMo 官方 OpenAI 兼容端点是 api.xiaomimimo.com，
                # 不是 api.mimo.ai(后者不解析/不是小米的域名)——key 填得再对，
                # 域名错了也是每次都连接失败，跟没配 key 看起来一模一样。
                base_url="https://api.xiaomimimo.com/v1",
                models=["mimo-v2.5-pro", "mimo-v2.5-standard", "mimo-v2.5-lite"],
                default_model="mimo-v2.5-pro",
                cost_per_1k_input=0.00002, cost_per_1k_output=0.00008,
                multimodal=False, env_key="MIMO_API_KEY",
            )
            self.providers["mimo"] = cfg
            self.adapters["mimo"] = MiMoAdapter(cfg)

        # Moonshot Kimi
        key = self._get_key("moonshot")
        if not key:
            key = os.environ.get("MOONSHOT_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="moonshot", api_key=key,
                base_url="https://api.moonshot.cn/v1",
                models=["kimi-k2.6", "kimi-k2.5", "moonshot-v1-128k"],
                default_model="kimi-k2.6",
                cost_per_1k_input=0.002, cost_per_1k_output=0.002,
                multimodal=False, env_key="MOONSHOT_API_KEY",
            )
            self.providers["moonshot"] = cfg
            self.adapters["moonshot"] = MoonshotAdapter(cfg)

        # Perplexity Sonar
        key = self._get_key("perplexity")
        if not key:
            key = os.environ.get("PERPLEXITY_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="perplexity", api_key=key,
                base_url="https://api.perplexity.ai",
                models=["sonar-pro", "sonar-deep-research", "sonar-reasoning-pro", "sonar"],
                default_model="sonar-pro",
                cost_per_1k_input=0.001, cost_per_1k_output=0.001,
                supports_tools=False, multimodal=False, env_key="PERPLEXITY_API_KEY",
            )
            self.providers["perplexity"] = cfg
            self.adapters["perplexity"] = PerplexityAdapter(cfg)

        # Groq
        key = self._get_key("groq")
        if not key:
            key = os.environ.get("GROQ_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="groq", api_key=key,
                base_url="https://api.groq.com/openai/v1",
                models=["llama-3.3-70b-versatile"],
                default_model="llama-3.3-70b-versatile",
                cost_per_1k_input=0.00059, cost_per_1k_output=0.00079,
                supports_tools=True, multimodal=False, env_key="GROQ_API_KEY",
            )
            self.providers["groq"] = cfg
            self.adapters["groq"] = GroqAdapter(cfg)

        # Ollama (local) — PR-HA: upgraded to first-class multimodal-capable local provider
        ollama_url = self._normalize_base_url(self._get_key("ollama"))
        if not ollama_url:
            ollama_url = self._normalize_base_url(os.environ.get("OLLAMA_URL", ""))
        ollama_default_url = "http://localhost:11434"
        if not ollama_url:
            # 尝试默认地址
            try:
                import httpx
                r = httpx.get(f"{ollama_default_url}/api/tags", timeout=2.0)
                if r.status_code == 200:
                    ollama_url = ollama_default_url
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)
        if ollama_url and not ollama_url.startswith("your-"):
            # 检测 Ollama 实际可用的模型（包括 VLM）
            detected_models = ["gemma4:12b", "gemma4:e4b"]
            try:
                import httpx
                r = httpx.get(f"{ollama_url}/api/tags", timeout=3.0)
                if r.status_code == 200:
                    detected_models = [m["name"] for m in r.json().get("models", [])]
                    if not detected_models:
                        detected_models = ["gemma4:12b"]
            except Exception as exc:
                logger.warning("Exception suppressed: %s", exc)

            # AI 主脑：用户在启动时选定的模型(OLLAMA_MODEL，见 core.model_selection)作为默认主脑。
            # 把它提到 models 列表最前并设为 default_model；未设置则回退第一个已安装模型。
            _main_brain = os.environ.get("OLLAMA_MODEL", "").strip()
            if _main_brain:
                _norm = lambda s: s.split(":")[0]  # noqa: E731
                if not any(m == _main_brain or _norm(m) == _norm(_main_brain) for m in detected_models):
                    detected_models = [_main_brain] + detected_models
                else:
                    detected_models = sorted(
                        detected_models,
                        key=lambda m: 0 if (m == _main_brain or _norm(m) == _norm(_main_brain)) else 1,
                    )
            _default_model = _main_brain or (detected_models[0] if detected_models else "gemma4:e2b")

            cfg = ProviderConfig(
                name="ollama", api_key="", base_url=ollama_url,
                models=detected_models,
                default_model=_default_model,
                supports_tools=True, supports_json_mode=True,
                multimodal=True,  # PR-HA: Ollama now marked multimodal-capable
                env_key="OLLAMA_URL",
                # PR-HA: 新增字段
                source_type="local",
                hardware_tier="gpu_full",
                supports_vision=True,   # llava / bakllava via Ollama
                supports_audio=False,
                kv_cache_enabled=True,
                prefix_cache_enabled=False,
                quantization="none",  # 由 Ollama 内部管理
            )
            self.providers["ollama"] = cfg
            self.adapters["ollama"] = OllamaAdapter(cfg)

        # HuggingFace Local Models (as independent provider)
        try:
            from core.huggingface_model_manager import (
                get_hf_model_manager,
                ModelFamily,
            )

            hf_mgr = get_hf_model_manager()
            local_llm_models = hf_mgr.list_local_models(family=ModelFamily.LLM)
            hf_base_url = "http://localhost:16201/v1/hf"  # Galaxy internal API
            # hf_local 排在偏好列表里紧跟 ollama 之后(见 PREFERRED_PROVIDER_ORDER)。
            # 这个内部适配服务(:16201)从未被实现过 —— 若仍无条件注册,一旦真的
            # 触发到 hf_local 兜底,连的是一个根本没监听的端口,只会拿到连接失败,
            # 而不是继续往下一个 provider 退——静默变成"看似失败模型探测"。这里
            # 先探一下这个内部端口是否真的活着,不活就不注册,让偏好列表自然跳过它。
            if local_llm_models and self._internal_hf_adapter_alive(hf_base_url):
                hf_model_ids = [m.model_id for m in local_llm_models]
                hf_default = hf_model_ids[0] if hf_model_ids else ""
                cfg = ProviderConfig(
                    name="hf_local",
                    api_key="",
                    base_url=hf_base_url,
                    models=hf_model_ids,
                    default_model=hf_default,
                    supports_tools=True,
                    supports_json_mode=False,
                    multimodal=True,
                    env_key="",
                    source_type="local",
                    hardware_tier="gpu_full",
                    supports_vision=True,
                )
                self.providers["hf_local"] = cfg
                self.adapters["hf_local"] = OpenAIAdapter(cfg)
                logger.info(
                    "HF 本地模型提供商已注册: %d 个模型", len(hf_model_ids)
                )
            elif local_llm_models:
                logger.debug(
                    "跳过 hf_local 注册:内部适配服务(%s)未运行,避免偏好列表命中它时"
                    "连接失败(而非正常跳到下一个 provider)", hf_base_url,
                )
        except Exception as exc:
            logger.debug("HF 本地模型提供商注册失败 (非致命): %s", exc)

        # OneAPI fallback
        oneapi_key = self._get_key("oneapi")
        if not oneapi_key:
            oneapi_key = os.environ.get("ONEAPI_API_KEY", "")
        oneapi_url = self._normalize_base_url(self._get_key("oneapi_url"))
        if not oneapi_url:
            oneapi_url = self._normalize_base_url(os.environ.get("ONEAPI_URL", ""))
        if oneapi_key and not oneapi_key.startswith("your-") and oneapi_url:
            models = self._discover_oneapi_models(oneapi_url, oneapi_key)
            cfg = ProviderConfig(
                name="oneapi", api_key=oneapi_key,
                base_url=f"{oneapi_url}/v1",
                models=models,
                default_model=models[0] if models else "gpt-4o",
                env_key="ONEAPI_API_KEY",
            )
            self.providers["oneapi"] = cfg
            self.adapters["oneapi"] = OpenAIAdapter(cfg)

        logger.info(
            f"LLM 路由器已初始化（配置优先级: Dashboard > ENV），发现 {len(self.providers)} 个提供商: "
            f"{list(self.providers.keys())}"
        )

    def _discover_oneapi_models(self, base_url: str, api_key: str) -> List[str]:
        """从 config/api_config.json 读取已配置模型，并尝试通过 /v1/models 动态补充"""
        models: List[str] = []

        # 1. 读取 config/api_config.json 中预配置的模型
        try:
            config_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config", "api_config.json"
            )
            with open(config_path, "r", encoding="utf-8") as f:
                api_cfg = json.load(f)
            configured = api_cfg.get("oneapi", {}).get("models", [])
            if isinstance(configured, list):
                models.extend(configured)
        except Exception as e:
            logger.debug(f"Could not load config/api_config.json for OneAPI models: {e}")

        # 2. 动态发现：调用 /v1/models
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(
                    f"{base_url}/v1/models",
                    headers={"Authorization": f"Bearer {api_key}"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    remote_ids = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and "id" in m]
                    for mid in remote_ids:
                        if mid not in models:
                            models.append(mid)
        except Exception as e:
            logger.debug(f"OneAPI /v1/models discovery failed (non-fatal): {e}")

        # 3. 若仍为空，使用保守默认值
        if not models:
            models = ["gpt-4o", "gpt-4o-mini"]
            logger.debug("OneAPI: falling back to default model list")

        return models

    # ───────── 复杂度评估 ─────────

    def _compute_complexity_vector(
        self, messages: List[Dict], tools: Optional[List[Dict]] = None,
    ):
        """量化评估任务复杂度，返回 ComplexityVector (Pydantic model)

        5 维向量加权求和：
          - 上下文长度 (0.15)
          - 逻辑深度 (0.25)
          - 领域专业度 (0.20)
          - 精度要求 (0.20)
          - 工具需求 (0.20)
        """
        from core.schemas.routing import ComplexityVector

        # 拼接全部文本
        full_text = " ".join(m.get("content", "") for m in messages if isinstance(m.get("content"), str))
        text_lower = full_text.lower()
        char_count = len(full_text)

        # ── 维度 1: 上下文长度 (weight=0.15) ──
        # 粗略估算 token ≈ char_count / 3 (中文) 或 char_count / 4 (英文)
        estimated_tokens = char_count / 3.5
        dim_context = min(1.0, estimated_tokens / 8000)

        # ── 维度 2: 逻辑深度 (weight=0.25) ──
        logic_keywords = [
            "如果", "那么", "否则", "但是", "然而", "因为", "所以", "首先", "其次", "最后",
            "假设", "前提", "推导", "证明", "递归", "循环", "回溯", "遍历", "迭代",
            "条件", "判断", "分支", "嵌套", "复杂", "步骤", "流程", "逻辑",
            "if", "then", "else", "while", "for", "because", "therefore",
            "first", "second", "finally", "assume", "prove", "recursive",
            "algorithm", "iterate", "traverse", "backtrack",
        ]
        logic_hits = sum(1 for kw in logic_keywords if kw in text_lower)
        dim_logic = min(1.0, logic_hits / 6)

        # ── 维度 3: 领域专业度 (weight=0.20) ──
        domain_keywords = [
            # 代码 (含中文编程术语)
            "def ", "class ", "import ", "function", "async", "await", "return",
            "try:", "except", "raise", "lambda", "yield",
            "python", "java", "rust", "typescript", "javascript",
            "实现", "编程", "代码", "函数", "接口", "模块", "编译", "调试",
            "算法", "数据结构", "排序", "求解", "优化", "注解", "类型",
            "测试", "单元测试", "集成测试",
            # 数学
            "∑", "∫", "∂", "矩阵", "向量", "微分", "积分", "概率",
            "matrix", "vector", "derivative", "integral", "probability",
            # 专业
            "API", "SDK", "协议", "架构", "数据库", "索引", "并发", "事务",
            "database", "index", "concurrent", "transaction",
            "机器学习", "深度学习", "神经网络", "模型训练",
        ]
        domain_hits = sum(1 for kw in domain_keywords if kw in full_text.lower())
        dim_domain = min(1.0, domain_hits / 5)

        # ── 维度 4: 精度要求 (weight=0.20) ──
        precision_keywords = [
            "精确", "准确", "正确", "严格", "必须", "确保", "验证", "要求",
            "支持", "完整", "兼容", "标准", "规范",
            "exact", "precise", "correct", "strict", "must", "verify",
            "bug", "错误", "修复", "fix", "debug", "require",
        ]
        precision_hits = sum(1 for kw in precision_keywords if kw in text_lower)
        dim_precision = min(1.0, precision_hits / 4)

        # ── 维度 5: 工具需求 (weight=0.20) ──
        tool_keywords = [
            "文件", "目录", "搜索", "执行", "运行", "安装", "设备", "屏幕",
            "file", "directory", "search", "execute", "run", "install", "device", "screen",
            "打开", "关闭", "截图", "发送", "下载", "上传",
        ]
        tool_text_hits = sum(1 for kw in tool_keywords if kw in text_lower)
        has_tools = 1.0 if tools and len(tools) > 0 else 0.0
        dim_tools = min(1.0, max(tool_text_hits / 3, has_tools))

        # ── 返回结构化向量 ──
        return ComplexityVector(
            context_length=round(dim_context, 3),
            logic_depth=round(dim_logic, 3),
            domain_expertise=round(dim_domain, 3),
            precision_requirement=round(dim_precision, 3),
            tool_needs=round(dim_tools, 3),
        )

    def _compute_complexity_score(
        self, messages: List[Dict], tools: Optional[List[Dict]] = None,
    ) -> float:
        """兼容接口 — 返回加权分数 (float 0.0-1.0)"""
        return self._compute_complexity_vector(messages, tools).weighted_score

    # ───────── 路由决策 ─────────

    def classify_task(self, messages: List[Dict], hint: Optional[str] = None) -> TaskType:
        """根据消息内容分类任务类型"""
        if hint:
            try:
                return TaskType(hint)
            except ValueError:
                pass

        # 分析最后一条用户消息
        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "").lower()
                break

        # 加权关键词 → 任务类型 (keyword, weight)
        weighted_patterns: Dict[TaskType, List[tuple]] = {
            TaskType.CODING: [
                ("代码", 2), ("编程", 2), ("函数", 2), ("类", 1), ("bug", 3),
                ("code", 3), ("implement", 3), ("debug", 3), ("function", 2),
                ("class", 1), ("api", 2), ("脚本", 2), ("script", 2),
            ],
            TaskType.REASONING: [
                ("为什么", 3), ("推理", 3), ("解释", 2), ("分析原因", 3),
                ("why", 3), ("reason", 3), ("explain", 2), ("思考", 2),
                ("逻辑", 3), ("论证", 2),
            ],
            TaskType.PLANNING: [
                ("计划", 3), ("规划", 3), ("步骤", 2), ("方案", 2),
                ("plan", 3), ("strategy", 3), ("分解", 2), ("目标", 1),
                ("路线图", 3), ("roadmap", 3),
            ],
            TaskType.CREATIVE: [
                ("创作", 3), ("写", 1), ("故事", 3), ("诗", 3),
                ("write", 1), ("create", 2), ("creative", 3),
                ("设计", 2), ("文章", 2), ("作文", 3),
            ],
            TaskType.ANALYSIS: [
                ("分析", 3), ("数据", 2), ("报告", 2), ("统计", 3),
                ("analyze", 3), ("data", 2), ("report", 2),
                ("评估", 2), ("比较", 2),
            ],
            TaskType.AGENT_CONTROL: [
                ("agent", 3), ("执行", 1), ("控制", 2), ("设备", 2),
                ("节点", 2), ("device", 3), ("node", 2),
                ("命令", 2), ("command", 2),
            ],
        }

        scores: Dict[TaskType, float] = {}
        for task_type, weighted_keywords in weighted_patterns.items():
            total_weight = sum(w for _, w in weighted_keywords)
            score = sum(w for kw, w in weighted_keywords if kw in last_user_msg)
            if score > 0:
                # Normalize by total possible weight
                scores[task_type] = score / max(total_weight, 1)

        if scores:
            return max(scores, key=scores.get)

        return TaskType.GENERAL

    def select_model_by_complexity(
        self, provider_name: str, task_type: TaskType, complexity: float
    ) -> str:
        """根据复杂度选择模型 — 简单任务用轻量模型，复杂任务用强模型"""
        provider_models = PROVIDER_MODEL_MAP.get(provider_name, {})
        default = self.providers[provider_name].default_model

        # 本地单主脑(ollama/hf_local):用户启动时只选/只拉了一个模型
        # (OLLAMA_MODEL → default_model)。静态 per-task 映射假设装了 12b/e4b 全家桶,
        # 但本地通常只装了所选那一个 → 若按映射去调用未安装的 tag 会 404
        # (实测:选了 e2b,却按映射调 gemma4:12b → 404 全部失败)。
        # 故本地主脑一律用所选模型,不按复杂度在不存在的 tag 间换挡。
        if provider_name in ("ollama", "hf_local") and default:
            return default

        if complexity < 0.3:
            # LIGHT — 优先选快速/轻量模型
            return provider_models.get(TaskType.FAST_RESPONSE, default)
        elif complexity < 0.6:
            # MEDIUM — 用任务类型推荐的模型
            return provider_models.get(task_type, default)
        else:
            # HEAVY/EXPERT — 优先选推理/重型模型
            heavy_model = provider_models.get(TaskType.REASONING, default)
            return heavy_model

    def route(self, task_type: TaskType,
              preferred_provider: Optional[str] = None,
              complexity_score: float = 0.5) -> RoutingDecision:
        """
        根据任务类型 + 复杂度评分做出路由决策

        优先级：
        1. 用户指定的提供商
        2. 任务类型推荐的提供商（跳过不可用的）
        3. 任意可用提供商

        complexity_score: 0.0-1.0，影响模型等级选择

        LOCAL-BRAIN-FIRST: 当环境变量 USE_LOCAL_BRAIN_FIRST=true 时，
        优先检查本地 Ollama 是否可用，若可用则路由到本地主脑。
        """
        # ── 本地主脑优先检查 ───────────────────────────────────────────────
        # 若未强制指定提供商且启用了本地主脑优先策略
        if not preferred_provider and os.environ.get("USE_LOCAL_BRAIN_FIRST", "").lower() == "true":
            # 检查 Ollama 是否健康可用
            if "ollama" in self.providers:
                ollama_prov = self.providers["ollama"]
                if ollama_prov.is_available():
                    model = self.select_model_by_complexity("ollama", task_type, complexity_score)
                    return RoutingDecision(
                        provider="ollama", model=model,
                        reason=f"本地主脑优先: Ollama 可用，任务类型 [{task_type.value}] 复杂度 {complexity_score:.2f}",
                        alternatives=[
                            f"{name}:{self.select_model_by_complexity(name, task_type, complexity_score)}"
                            for name in TASK_ROUTING_PREFERENCES.get(task_type, [])
                            if name in self.providers and name != "ollama"
                            and self.providers[name].is_available()
                        ],
                    )
            # 检查 HF 本地模型是否可用
            if "hf_local" in self.providers:
                hf_prov = self.providers["hf_local"]
                if hf_prov.is_available() and hf_prov.models:
                    model = self.select_model_by_complexity("hf_local", task_type, complexity_score)
                    if not model or model not in hf_prov.models:
                        model = hf_prov.default_model or hf_prov.models[0]
                    return RoutingDecision(
                        provider="hf_local", model=model,
                        reason=f"本地主脑优先: HuggingFace 本地模型 [{model}] 可用，任务类型 [{task_type.value}] 复杂度 {complexity_score:.2f}",
                        alternatives=[
                            f"{name}:{self.select_model_by_complexity(name, task_type, complexity_score)}"
                            for name in TASK_ROUTING_PREFERENCES.get(task_type, [])
                            if name in self.providers and name != "hf_local"
                            and self.providers[name].is_available()
                        ],
                    )

        if preferred_provider and preferred_provider in self.providers:
            prov = self.providers[preferred_provider]
            if prov.is_available():
                model = self.select_model_by_complexity(
                    preferred_provider, task_type, complexity_score
                )
                return RoutingDecision(
                    provider=preferred_provider, model=model,
                    reason=f"用户指定提供商: {preferred_provider} (复杂度: {complexity_score:.2f})",
                )

        # 按任务偏好排序
        preferred_order = TASK_ROUTING_PREFERENCES.get(task_type, [])
        # 开源优先（默认开启）：把开源提供商整体提到专有之前，保持原相对顺序。
        # 本地 ollama/hf_local 本就在偏好表最前，因此本地优先不受影响。
        if os.environ.get("GALAXY_OPENSOURCE_FIRST", "true").lower() != "false":
            preferred_order = reorder_open_source_first(list(preferred_order))
        alternatives = []

        for provider_name in preferred_order:
            if provider_name not in self.providers:
                continue
            prov = self.providers[provider_name]
            if (not prov.is_available()):
                continue

            model = self.select_model_by_complexity(
                provider_name, task_type, complexity_score
            )
            if not alternatives:
                selected = RoutingDecision(
                    provider=provider_name, model=model,
                    reason=f"任务类型 [{task_type.value}] 复杂度 {complexity_score:.2f}",
                )
            alternatives.append(f"{provider_name}:{model}")

        if alternatives:
            selected.alternatives = alternatives[1:]  # 排除已选的第一个
            return selected

        # fallback: 选择任意可用提供商
        for name, prov in self.providers.items():
            if prov.is_available():
                return RoutingDecision(
                    provider=name, model=prov.default_model,
                    reason=f"Fallback: 唯一可用提供商 {name}",
                )

        # 无可用提供商 — 返回指向 none 的降级路由决策
        logger.error("没有可用的 LLM 提供商")
        return RoutingDecision(
            provider="none", model="none",
            reason="无可用提供商，请在 Dashboard 配置 API Key",
        )

    # ───────── 做任务：按实际情况选模型（fit-based） ─────────

    def select_brain_for_task(
        self,
        task_type: TaskType,
        complexity_score: float = 0.5,
        *,
        has_multimodal: bool = False,
        needs_timely: bool = False,
        prefer_local: bool = False,
    ) -> RoutingDecision:
        """做任务时的"按实际情况"选模型（区别于交流基座的开源/本地优先）。

        用户规则（优先级）：
          1. 主    — 完成质量/能力最强优先（quality tier × 复杂度）
          2. 次    — 适度看 token 成本（同档次内便宜优先）
          3. 条件  — 仅当任务需要及时响应(needs_timely)才把延迟纳入
        硬约束：
          - 只在【已填 key 且健康】的提供商里选（没填的不在 self.providers）
          - 有多模态输入 → 只在多模态可用的提供商里选
          - 同档次平局：开源/本地优先（平局打破，而非无脑前移）

        Returns:
            RoutingDecision(provider, model, reason)；无候选时 provider="none"。
        """
        import os as _os

        # ── 候选 = 已填 key + 健康 + 有 adapter（没填的天然不在 providers）──
        candidates = [
            name for name, cfg in self.providers.items()
            if cfg.is_available() and self.adapters.get(name) is not None
        ]
        # ── 模态硬过滤 ──
        if has_multimodal:
            mm = [n for n in candidates if getattr(self.providers[n], "multimodal", False)]
            if mm:
                candidates = mm
        if not candidates:
            return RoutingDecision(provider="none", model="none", reason="无已配置可用提供商")

        # 权重（可经 env 微调）
        try:
            token_weight = float(_os.environ.get("GALAXY_ROUTE_TOKEN_WEIGHT", "0.6"))
        except ValueError:
            token_weight = 0.6
        try:
            latency_weight = float(_os.environ.get("GALAXY_ROUTE_LATENCY_WEIGHT", "0.5"))
        except ValueError:
            latency_weight = 0.5

        task_pref = TASK_ROUTING_PREFERENCES.get(task_type, [])
        # 成本/延迟归一化基准（避免量纲压过质量）
        max_cost = max(
            (self.providers[n].cost_per_1k_output for n in candidates), default=0.0
        ) or 1.0
        max_lat = max(
            (self.providers[n].latency_avg_ms for n in candidates), default=0.0
        ) or 1.0

        def _score(name: str) -> float:
            cfg = self.providers[name]
            quality = _provider_quality_tier(name)             # 1..3
            # 任务相关度：在该任务偏好表里 = 更贴合
            task_fit = 1.0 if name in task_pref else 0.6
            # 主：质量 × (0.5+复杂度) —— 越难越看重质量
            score = quality * (0.5 + complexity_score) * task_fit
            # 次：适度 token（同档次便宜优先）
            score -= token_weight * (cfg.cost_per_1k_output / max_cost)
            # 条件：仅任务需要及时响应时计入延迟
            if needs_timely:
                score -= latency_weight * (cfg.latency_avg_ms / max_lat)
            # 平局打破：开源/本地 + 显式本地偏好
            if name in OPEN_SOURCE_PROVIDERS:
                score += 0.15
            if prefer_local and name in ("ollama", "hf_local"):
                score += 0.5
            return score

        best = max(candidates, key=_score)
        model = self.select_model_by_complexity(best, task_type, complexity_score)
        if best == "hf_local" and (not model or model not in self.providers[best].models):
            model = self.providers[best].default_model or (
                self.providers[best].models[0] if self.providers[best].models else model
            )
        return RoutingDecision(
            provider=best, model=model,
            reason=(
                f"fit-based: {best}:{model} quality={_provider_quality_tier(best)} "
                f"task={task_type.value} complexity={complexity_score:.2f} "
                f"mm={has_multimodal} timely={needs_timely}"
            ),
        )

    # ───────── 角色 → 脑 绑定（大小模型配合） ─────────

    def select_brain_for_role(
        self,
        role: str,
        complexity_score: float = 0.5,
        task_type: Optional[TaskType] = None,
    ) -> RoutingDecision:
        """为一个协作角色选择"最便宜够用"的脑（provider + model）。

        实现"大小模型配合"的执行层：
          - 轻角色(executor/worker/researcher...) → 本地小模型优先；
          - 重角色(critic/reviewer/reasoner/coordinator...) → 开源大模型 API 优先。

        Args:
            role: 角色名（见 ROLE_BRAIN_HINTS），未知角色按 GENERAL/本地优先处理。
            complexity_score: 任务复杂度，影响同一 provider 内的模型大小选择。
            task_type: 显式任务类型；为 None 时用角色提示里的默认 task_type。

        Returns:
            RoutingDecision(provider, model, reason)；无可用提供商时 provider="none"。
        """
        hint = ROLE_BRAIN_HINTS.get(
            role, {"prefer_local": True, "task_type": TaskType.GENERAL, "min_complexity": 0.0}
        )
        eff_task = task_type or hint["task_type"]
        # 重角色用 max(任务复杂度, 角色最低复杂度) 确保选到足够强的模型
        eff_complexity = max(complexity_score, hint.get("min_complexity", 0.0))

        # 大小模型配合：
        #   - 轻角色(executor/worker...) → 本地小模型【硬】优先（这是设计意图：本地做，
        #     云端审；不让云端强模型抢走 executor），无本地时才 fit-based。
        #   - 重角色(critic/reviewer...) → fit-based 质量优先。
        def _avail(name: str) -> bool:
            return (
                name in self.providers
                and self.providers[name].is_available()
                and self.adapters.get(name) is not None
            )

        if hint["prefer_local"]:
            for local in ("ollama", "hf_local"):
                if _avail(local):
                    model = self.select_model_by_complexity(local, eff_task, eff_complexity)
                    if local == "hf_local" and (not model or model not in self.providers[local].models):
                        model = self.providers[local].default_model or (
                            self.providers[local].models[0] if self.providers[local].models else model
                        )
                    return RoutingDecision(
                        provider=local, model=model,
                        reason=f"角色[{role}] 轻角色(本地小模型优先): {local}:{model} task={eff_task.value}",
                    )

        decision = self.select_brain_for_task(eff_task, complexity_score=eff_complexity)
        if decision.provider != "none":
            role_kind = "轻角色(无本地→fit)" if hint["prefer_local"] else "重角色(质量优先)"
            decision.reason = f"角色[{role}] {role_kind} → {decision.reason}"
            return decision

        # 无候选 → 退回通用 route()
        return self.route(eff_task, complexity_score=eff_complexity)

    # ───────── 本地主脑优先路由 ─────────

    async def route_local_brain_first(self, task_type: TaskType, messages: List[Dict],
                                      has_multimodal: bool = False) -> RoutingDecision:
        """本地主脑优先路由

        路由策略：
        1. 检查 Ollama 是否可用（健康 + 有模型）
        2. 检查 Hugging Face 本地模型是否可用
        3. 硬件画像评估（VRAM 够不够运行目标模型）
        4. 本地可用 → 选本地主脑
        5. 本地不可用 / 能力不足 → 升级到云端 API
        6. 云端结果回流本地主脑整合（由调用方处理）

        Args:
            task_type: 任务类型
            messages: 消息列表（用于复杂度评估）
            has_multimodal: 是否包含多模态输入

        Returns:
            RoutingDecision: 路由决策，本地优先
        """
        # 1. 计算复杂度
        complexity = self._compute_complexity_score(messages)

        # 2. 检查 Ollama 本地主脑
        if "ollama" in self.providers:
            ollama_prov = self.providers["ollama"]
            if ollama_prov.is_available():
                model = self.select_model_by_complexity("ollama", task_type, complexity)
                # 收集云端后备方案
                cloud_fallbacks = [
                    f"{name}:{self.select_model_by_complexity(name, task_type, complexity)}"
                    for name in TASK_ROUTING_PREFERENCES.get(task_type, [])
                    if name in self.providers and name != "ollama"
                    and self.providers[name].is_available()
                ]
                return RoutingDecision(
                    provider="ollama",
                    model=model,
                    reason=(
                        f"本地主脑优先路由: Ollama 本地模型 [{model}] "
                        f"任务类型 [{task_type.value}] 复杂度 {complexity:.2f}"
                    ),
                    alternatives=cloud_fallbacks,
                )

        # 3. 检查 HuggingFace 本地模型 (hf_local)
        if "hf_local" in self.providers:
            hf_prov = self.providers["hf_local"]
            if hf_prov.is_available() and hf_prov.models:
                model = self.select_model_by_complexity("hf_local", task_type, complexity)
                # Use the first available HF local model as default
                if not model or model not in hf_prov.models:
                    model = hf_prov.default_model or hf_prov.models[0]
                cloud_fallbacks = [
                    f"{name}:{self.select_model_by_complexity(name, task_type, complexity)}"
                    for name in TASK_ROUTING_PREFERENCES.get(task_type, [])
                    if name in self.providers and name != "hf_local"
                    and self.providers[name].is_available()
                ]
                return RoutingDecision(
                    provider="hf_local",
                    model=model,
                    reason=(
                        f"本地主脑优先路由: HuggingFace 本地模型 [{model}] "
                        f"任务类型 [{task_type.value}] 复杂度 {complexity:.2f}"
                    ),
                    alternatives=cloud_fallbacks,
                )

        # 4. 检查 HF 本地模型（通过 oneapi 或直连）
        if "oneapi" in self.providers:
            oneapi_prov = self.providers["oneapi"]
            if oneapi_prov.is_available():
                model = self.select_model_by_complexity("oneapi", task_type, complexity)
                return RoutingDecision(
                    provider="oneapi",
                    model=model,
                    reason=(
                        f"本地主脑优先路由: OneAPI 本地模型 [{model}] "
                        f"任务类型 [{task_type.value}] 复杂度 {complexity:.2f}"
                    ),
                )

        # 4. 本地主脑不可用 → 升级到云端
        # 明确告警（而非静默回落）：本地主脑预期可用却未就绪时，提示用户检查
        # Ollama / 模型 tag（最常见是模型未 pull 或 tag 名不对），便于排查
        # "看着配了本地原生多模态、实际一直走云端" 的情况。
        _local_present = any(
            p in self.providers and self.providers[p].is_available()
            for p in ("ollama", "hf_local")
        )
        if not _local_present:
            logger.warning(
                "LOCAL-BRAIN-FIRST: 本地主脑不可用(ollama/hf_local 未就绪)，本次回落云端。"
                "请检查 `ollama list` 是否含所需模型(如 gemma4:12b / openbmb/minicpm-o4.5)、"
                "Ollama 是否在 %s 运行。",
                getattr(self, "ollama_url", "localhost:11434"),
            )
        # 如果有多模态输入，先尝试多模态路由
        if has_multimodal:
            decision = self.route_multimodal_first(
                active_modalities=["image"], task_type=task_type, complexity_score=complexity
            )
            if decision.provider != "none":
                decision.reason = f"本地主脑优先: 本地不可用，升级到云端多模态 → {decision.reason}"
                return decision

        # 5. 标准云端路由
        decision = self.route(task_type, complexity_score=complexity)
        if decision.provider != "none":
            decision.reason = f"本地主脑优先: 本地不可用，升级到云端 → {decision.reason}"
        return decision

    def route_multimodal_first(
        self,
        active_modalities: Optional[List[str]] = None,
        task_type: TaskType = TaskType.GENERAL,
        complexity_score: float = 0.5,
    ) -> RoutingDecision:
        """Native-multimodal-first routing policy (PR-20).

        Implements a three-tier routing hierarchy for requests that carry
        multimodal perception input:

        1. **Native multimodal** — provider with ``multimodal=True`` and
           ``status != DOWN``.  Returns immediately on first match.
        2. **Partial / text-capable** — any available provider even if it
           lacks native multimodal support.  Uses ``task_type`` routing.
           The caller is responsible for feeding derived ``fusion_summary``
           text as the model input (see :attr:`OpenClawd._fusion_suffix`).
        3. **Advisory / no-op** — returned when no provider is reachable at all.

        The ``RoutingDecision.reason`` field encodes the tier selected and
        which modalities drove the choice, making the decision auditable via
        the :class:`~core.schemas.unified_control_plan.UnifiedControlPlan`.

        Parameters
        ----------
        active_modalities:
            List of modality strings present in the current perception state
            (e.g. ``["image", "audio"]``).  ``None`` or empty list indicates
            a text-only request.
        task_type:
            Task type hint for tie-breaking among multimodal providers.
        complexity_score:
            Complexity score ``[0.0, 1.0]`` used by model-tier selection.

        Returns
        -------
        RoutingDecision
            Always returns a decision; ``provider="none"`` signals advisory/no-op.
        """
        modalities = active_modalities or []

        # ── Tier 1: native multimodal-capable providers ──────────────────────
        mm_candidates: List[RoutingDecision] = []
        for name, prov in self.providers.items():
            if (not prov.is_available()):
                continue
            if not prov.multimodal:
                continue
            model = self.select_model_by_complexity(name, task_type, complexity_score)
            modality_str = "+".join(modalities) if modalities else "generic"
            mm_candidates.append(
                RoutingDecision(
                    provider=name,
                    model=model,
                    reason=(
                        f"native_multimodal_first: tier=1 provider={name} "
                        f"modalities=[{modality_str}] complexity={complexity_score:.2f}"
                    ),
                    alternatives=[],
                )
            )

        if mm_candidates:
            # Prefer providers that appear early in the task routing preference order.
            preferred_order = TASK_ROUTING_PREFERENCES.get(task_type, [])
            preferred_index: Dict[str, int] = {
                name: idx for idx, name in enumerate(preferred_order)
            }
            ordered = sorted(
                mm_candidates,
                key=lambda d: preferred_index.get(d.provider, len(preferred_order)),
            )
            best = ordered[0]
            best.alternatives = [f"{d.provider}:{d.model}" for d in ordered[1:]]
            return best

        # ── Tier 2: no native multimodal provider available ──────────────────
        # Route to any available provider using standard task routing.
        # The caller is responsible for using fusion_summary as the model input.
        tier2 = self.route(task_type=task_type, complexity_score=complexity_score)
        if tier2.provider != "none":
            modality_str = "+".join(modalities) if modalities else "none"
            tier2.reason = (
                f"native_multimodal_first: tier=2 native_unavailable "
                f"modalities=[{modality_str}] fallback_provider={tier2.provider} "
                f"degraded_to=text_capable"
            )
            return tier2

        # ── Tier 3: advisory / no-op ──────────────────────────────────────────
        return RoutingDecision(
            provider="none",
            model="none",
            reason=(
                "native_multimodal_first: tier=3 advisory "
                "no_providers_available degraded_to=no_op"
            ),
        )

    def route_with_cost_policy(
        self,
        task_type: TaskType,
        complexity_score: float = 0.5,
        cost_weight: float = 0.3,
        llm_hint: Optional[Dict[str, Any]] = None,
    ) -> RoutingDecision:
        """
        组合策略路由：任务类型 + 成本效益加权评分。

        规则选择具有最高权威性；LLM 微调仅允许在规则选定的候选集内
        调整/追加约束（不可替换规则选定的 provider/model）。

        Args:
            task_type:        任务类型（来自规则引擎，权威）
            complexity_score: 复杂度评分
            cost_weight:      成本权重 0.0-1.0（默认 0.3，越高越偏向低成本提供商）
            llm_hint:         LLM 微调建议（可选）。格式：
                              {"preferred_provider": "...", "model_override": "...", "temperature": ...}
                              注意：preferred_provider 仅在规则候选列表内有效（否则忽略）；
                              model_override 仅在规则已选提供商内有效。

        Returns:
            RoutingDecision（规则主导，LLM 建议在守护轨道内应用）
        """
        # ── 1. 规则主路由 ─────────────────────────────────────────────────────
        preferred_order = TASK_ROUTING_PREFERENCES.get(task_type, [])

        # 计算每个候选提供商的综合得分（任务适配度 + 成本效益）
        candidates: List[Dict[str, Any]] = []
        for rank, provider_name in enumerate(preferred_order):
            if provider_name not in self.providers:
                continue
            prov = self.providers[provider_name]
            if (not prov.is_available()):
                continue

            model = self.select_model_by_complexity(provider_name, task_type, complexity_score)

            # 任务适配得分（按 TASK_ROUTING_PREFERENCES 排名越前分越高）
            task_score = max(0.0, 1.0 - rank * 0.2)

            # 成本效益得分（成本越低分越高）
            avg_cost = (prov.cost_per_1k_input + prov.cost_per_1k_output) / 2
            # 归一化成本得分：假设 0.01 $/1k 作为参考上限
            cost_score = max(0.0, 1.0 - min(avg_cost / 0.01, 1.0))

            # 综合得分 = 任务适配 * (1-cost_weight) + 成本效益 * cost_weight
            composite = task_score * (1.0 - cost_weight) + cost_score * cost_weight

            candidates.append({
                "provider": provider_name,
                "model": model,
                "composite": composite,
                "task_score": task_score,
                "cost_score": cost_score,
            })

        if not candidates:
            # 无候选 → 回退到原始 route()
            return self.route(task_type, complexity_score=complexity_score)

        # 按综合得分排序，取最优
        candidates.sort(key=lambda x: x["composite"], reverse=True)
        best = candidates[0]
        selected_provider = best["provider"]
        selected_model = best["model"]

        # ── 2. LLM 微调（仅允许在规则守护轨道内调整）────────────────────────
        if llm_hint:
            hint_provider = llm_hint.get("preferred_provider", "")
            hint_model = llm_hint.get("model_override", "")

            # 微调规则 A: 仅允许从规则候选列表中的提供商中替换（不允许引入规则列表外的提供商）
            rule_providers = {c["provider"] for c in candidates}
            if hint_provider and hint_provider in rule_providers:
                # 在规则列表内找到对应候选，更新选择
                for c in candidates:
                    if c["provider"] == hint_provider:
                        selected_provider = c["provider"]
                        selected_model = c["model"]
                        logger.info(
                            "LLM 微调建议已采纳（规则守护）: provider=%s", hint_provider
                        )
                        break
            elif hint_provider:
                logger.debug(
                    "LLM 微调建议已拒绝（提供商不在规则列表内）: %s not in %s",
                    hint_provider, rule_providers,
                )

            # 微调规则 B: 模型覆盖仅允许在规则选定的提供商内切换
            if hint_model and selected_provider in self.providers:
                allowed_models = self.providers[selected_provider].models
                if hint_model in allowed_models:
                    selected_model = hint_model
                    logger.info("LLM 微调建议已采纳（模型守护）: model=%s", hint_model)
                else:
                    logger.debug(
                        "LLM 微调建议已拒绝（模型不在该提供商允许列表内）: %s", hint_model
                    )

        reason = (
            f"策略路由: 任务类型 [{task_type.value}] "
            f"复杂度 {complexity_score:.2f} 成本权重 {cost_weight:.2f}"
        )
        alternatives = [
            f"{c['provider']}:{c['model']}"
            for c in candidates
            if c["provider"] != selected_provider
        ]
        return RoutingDecision(
            provider=selected_provider,
            model=selected_model,
            reason=reason,
            alternatives=alternatives,
        )

    # ───────── Identity injection helper ─────────

    def _inject_identity_to_messages(self, messages: List[Dict]) -> List[Dict]:
        """Inject Agent identity into system prompt.

        PR-STABILITY-IDENTITY: Prepends the Agent's self-description
        to the system message so the model knows who it is.
        """
        try:
            from core.agent_identity_memory import get_identity_memory  # noqa: PLC0415

            identity = get_identity_memory()
            identity_text = identity.get_system_prompt_addition()
            has_system = False
            for msg in messages:
                if msg.get("role") == "system":
                    existing = msg.get("content", "")
                    if identity_text not in existing:
                        msg["content"] = existing + "\n\n" + identity_text
                    has_system = True
                    break
            if not has_system and identity_text:
                messages = [{"role": "system", "content": identity_text}] + list(messages)
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        return messages

    # ───────── 统一调用入口 ─────────

    async def chat(
        self,
        messages: List[Dict],
        task_type: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        auto_failover: bool = True,
        **kwargs,
    ) -> LLMResponse:
        """
        统一 Chat 接口，智能路由 + 故障转移

        Args:
            messages: 消息列表
            task_type: 任务类型 hint（可选，自动推断）
            provider: 强制指定提供商（可选）
            model: 强制指定模型（可选）
            tools: 工具列表
            temperature: 温度
            max_tokens: 最大 token
            response_format: 响应格式
            auto_failover: 是否自动故障转移
        """
        # PR-STABILITY-IDENTITY: Inject Agent identity into system prompt
        messages = self._inject_identity_to_messages(messages)

        # 1. 分类任务 + 复杂度评估（结构化向量）
        classified = self.classify_task(messages, task_type)
        cv = self._compute_complexity_vector(messages, tools)
        complexity = cv.weighted_score
        logger.info(f"任务分类: {classified.value} | 复杂度: {complexity} | 等级: {cv.tier.value}")

        # 2. 路由决策（综合任务类型 + 复杂度）
        decision = self.route(classified, provider, complexity_score=complexity)
        logger.info(f"路由决策: {decision.provider}:{decision.model} ({decision.reason})")

        # 如果用户强制指定了 model，覆盖
        if model:
            decision.model = model

        # 3. 尝试调用（带故障转移）
        tried_providers = []
        candidates = [f"{decision.provider}:{decision.model}"]
        candidates.extend(decision.alternatives)

        for candidate in candidates:
            prov_name, mdl = candidate.split(":", 1) if ":" in candidate else (candidate, None)
            if prov_name not in self.adapters:
                continue
            if mdl is None:
                mdl = self.providers[prov_name].default_model

            adapter = self.adapters[prov_name]
            tried_providers.append(prov_name)

            # 断路器检查
            cb = self.circuit_breakers.get(prov_name)
            if cb and not cb.allow_request():
                logger.info(f"断路器拒绝: {prov_name} (状态: {cb.state})")
                continue

            try:
                response = await adapter.chat(
                    messages=messages, model=mdl, tools=tools,
                    temperature=temperature, max_tokens=max_tokens,
                    response_format=response_format, **kwargs,
                )

                # 更新状态 + 断路器
                self.providers[prov_name].success_count += 1
                self.providers[prov_name].last_used = time.time()
                self.providers[prov_name].latency_avg_ms = (
                    self.providers[prov_name].latency_avg_ms * 0.8
                    + response.latency_ms * 0.2
                )
                if self.providers[prov_name].status in (ProviderStatus.DEGRADED, ProviderStatus.DOWN):
                    # DOWN 也要能被调用成功后清回 HEALTHY(冷却期过后 is_available()
                    # 已经放行让它重新当候选，调用真的成功了就该把状态本身也纠正过来，
                    # 而不是让 get_status()/面板一直显示"down"，直到进程重启为止)。
                    self.providers[prov_name].status = ProviderStatus.HEALTHY
                    self.providers[prov_name].error_count = 0
                    self.providers[prov_name].down_since = 0.0
                if cb:
                    cb.record_success()

                # PR86: 记录本次调用的 provider/model，供 OpenClawd 日志使用
                self._last_provider = prov_name
                self._last_model = mdl
                fallback_used = len(tried_providers) > 1
                if fallback_used:
                    logger.info(
                        "LLM 路由 fallback 生效 | 尝试顺序: %s -> 最终: %s:%s",
                        tried_providers[:-1], prov_name, mdl,
                    )

                # 记录成本（非阻塞，失败不影响主流程）
                try:
                    from core.cost_tracker import get_cost_tracker
                    prov_cfg = self.providers[prov_name]
                    get_cost_tracker().record(
                        provider=prov_name,
                        model=mdl,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        task_type=classified.value,
                        latency_ms=response.latency_ms,
                        success=True,
                        cost_per_1k_input=prov_cfg.cost_per_1k_input,
                        cost_per_1k_output=prov_cfg.cost_per_1k_output,
                    )
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)

                # 记录调用历史（含结构化复杂度）
                self.call_history.append({
                    "provider": prov_name,
                    "model": mdl,
                    "task_type": classified.value,
                    "complexity": complexity,
                    "model_tier": cv.tier.value,
                    "complexity_vector": cv.model_dump(),
                    "latency_ms": response.latency_ms,
                    "tokens": response.input_tokens + response.output_tokens,
                    "timestamp": time.time(),
                    "success": True,
                })
                if len(self.call_history) > 500:
                    self.call_history = self.call_history[-500:]

                logger.info(
                    f"LLM 调用成功: {prov_name}:{mdl} | "
                    f"{response.latency_ms:.0f}ms | "
                    f"{response.input_tokens}+{response.output_tokens} tokens"
                )
                return response

            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
                self.providers[prov_name].error_count += 1
                self.providers[prov_name].last_error = str(e)
                if cb:
                    cb.record_failure()
                if self.providers[prov_name].error_count >= 5:
                    self.providers[prov_name].status = ProviderStatus.DOWN
                    self.providers[prov_name].down_since = time.time()
                else:
                    self.providers[prov_name].status = ProviderStatus.DEGRADED

                logger.warning(f"LLM 调用失败 [{prov_name}:{mdl}]: {e}")

                self.call_history.append({
                    "provider": prov_name, "model": mdl,
                    "task_type": classified.value,
                    "timestamp": time.time(), "success": False,
                    "error": str(e),
                })

                if not auto_failover:
                    raise

                continue

        # 优雅降级：返回标准化错误响应而非崩溃
        logger.error(f"所有提供商调用失败: {tried_providers}")
        return LLMResponse(
            content=f"所有 AI 服务暂时不可用（已尝试: {', '.join(tried_providers)}），请检查 API Key 配置后重试。",
            provider="none",
            model="none",
            input_tokens=0,
            output_tokens=0,
            tool_calls=None,
        )

    # ───────── JSON 模式快捷方法 ─────────

    async def chat_json(self, messages: List[Dict], schema_hint: str = "",
                        **kwargs) -> Dict:
        """调用 LLM 并解析 JSON 响应"""
        if schema_hint:
            messages = list(messages)
            messages.append({
                "role": "user",
                "content": f"请以 JSON 格式返回结果。结构: {schema_hint}",
            })

        resp = await self.chat(messages, **kwargs)
        # 尝试从响应中提取 JSON
        text = resp.content.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        try:
            return json.loads(text.strip())
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"chat_json 解析失败: {e}，text[:200]={text[:200]}")
            return {"error": "JSON 解析失败", "raw": text[:500]}

    # ───────── 状态查询 ─────────

    def get_status(self) -> Dict[str, Any]:
        """获取路由器状态"""
        providers_status = {}
        for name, prov in self.providers.items():
            cb = self.circuit_breakers.get(name)
            providers_status[name] = {
                "status": prov.status.value,
                "models": prov.models,
                "default_model": prov.default_model,
                "success_count": prov.success_count,
                "error_count": prov.error_count,
                "latency_avg_ms": round(prov.latency_avg_ms, 1),
                "last_error": prov.last_error,
                "circuit_breaker": cb.to_dict() if cb else None,
            }

        recent = self.call_history[-20:]
        return {
            "total_providers": len(self.providers),
            "healthy_providers": sum(
                1 for p in self.providers.values()
                if p.status == ProviderStatus.HEALTHY
            ),
            "providers": providers_status,
            "total_calls": len(self.call_history),
            "recent_calls": recent,
        }

    async def health_check(self) -> Dict[str, str]:
        """对所有提供商做健康检查"""
        results = {}
        for name, adapter in self.adapters.items():
            try:
                resp = await adapter.chat(
                    messages=[{"role": "user", "content": "ping"}],
                    model=self.providers[name].default_model,
                    max_tokens=5,
                )
                results[name] = "healthy"
                self.providers[name].status = ProviderStatus.HEALTHY
                self.providers[name].error_count = 0
            except Exception as e:
                logger.debug("Fallback triggered: %s", e)
                results[name] = f"error: {e}"
                self.providers[name].status = ProviderStatus.DOWN
                self.providers[name].down_since = time.time()
        return results

    # ───────── LLMManager 兼容接口 ─────────
    # 使 MultiLLMRouter 可以作为 LLMManager 的替代品使用，
    # 保持与 scheduler 和 chat.py 的接口兼容。

    def is_available(self) -> bool:
        """检查是否有可用的 LLM Provider"""
        return len(self.providers) > 0

    def get_default_model(self) -> str:
        """获取默认模型名"""
        if self.providers:
            first = next(iter(self.providers.values()))
            return first.default_model
        return "gpt-4o"

    def get_provider_status(self) -> list:
        """获取所有 Provider 状态（兼容 LLMManager 格式）"""
        result = []
        for name, prov in self.providers.items():
            result.append({
                "provider": name,
                "model": prov.default_model,
                "models": prov.models,
                "source": "env/vault",
                "active": prov.is_available(),
                "available": prov.is_available(),
                "supports_tools": prov.supports_tools,
                "multimodal": prov.multimodal,
                "env_key": prov.env_key,
            })
        return result

    async def chat_completion(
        self,
        messages: list,
        tools: list = None,
        model_alias: str = None,
        task_type: str = None,
        **kwargs,
    ):
        """
        OpenAI 兼容的 chat completion 接口。
        内部调用 self.chat() 并将 LLMResponse 转为 OpenAI 格式，
        使 scheduler 等依赖 .choices[0].message 格式的模块无需修改。
        """
        resp = await self.chat(
            messages=messages,
            tools=tools,
            model=model_alias,
            task_type=task_type,
            **{k: v for k, v in kwargs.items() if k in (
                "temperature", "max_tokens", "response_format",
                "auto_failover", "provider", "tool_choice",
            )},
        )

        # 如果 raw_response 存在且有标准 OpenAI 格式，直接用它
        if resp.raw_response and "choices" in resp.raw_response:
            return _OpenAICompatResponse(resp.raw_response, resp.model)

        # 否则手动构建 OpenAI 兼容结构
        message_dict = {"role": "assistant", "content": resp.content}
        if resp.tool_calls:
            message_dict["tool_calls"] = resp.tool_calls

        return _OpenAICompatResponse({
            "choices": [{"message": message_dict, "finish_reason": "stop"}],
            "model": resp.model,
            "usage": {
                "prompt_tokens": resp.input_tokens,
                "completion_tokens": resp.output_tokens,
            },
        }, resp.model)

    async def chat_with_tools(
        self,
        messages: List[Dict],
        task_type: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs,
    ) -> LLMResponse:
        """
        工具感知聊天统一入口别名（PR-3 向后兼容）。

        与 UnifiedLLMRouter.chat_with_tools() 签名对齐，使调用方无论持有
        UnifiedLLMRouter 还是 MultiLLMRouter（降级场景）都可通过同一方法名
        发起工具感知聊天请求，无需在调用方做类型判断。

        直接委派到 self.chat()，保持与现有路由逻辑（provider 选择、故障转移）
        完全一致。
        """
        return await self.chat(
            messages=messages,
            task_type=task_type,
            provider=provider,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

    async def refresh_providers(self) -> Dict[str, Any]:
        """热刷新所有提供商 — 重新从环境变量/CredentialVault 扫描 Key

        当用户在 Dashboard 保存 API Key 后调用此方法，Router 即时感知变化。
        返回: {"added": [...], "removed": [...], "kept": [...], "total": N}
        """
        old_names = set(self.providers.keys())

        # 关闭所有现有 adapter 连接
        for adapter in self.adapters.values():
            try:
                await adapter.close()
            except Exception as e:
                logger.debug(f"关闭 adapter 时出错: {e}")

        # 清空
        self.providers.clear()
        self.adapters.clear()
        self.circuit_breakers.clear()

        # 重新发现——_discover_providers() 是同步方法,内部对 Ollama/OneAPI 等
        # 做阻塞 httpx.get(timeout=2~5s) 网络探测。refresh_providers() 本身是
        # async 方法,若直接同步调用,会在探测耗时的整个窗口内冻结共享事件循环，
        # 期间任何其它并发请求(包括完全无关的轻量端点)都会被阻塞排队——这正是
        # "保存模型 API Key 后其它请求集体卡几秒"的根因。offload 到线程,不阻塞
        # 事件循环。
        await asyncio.to_thread(self._discover_providers)

        # 为新发现的提供商创建断路器
        for name in self.providers:
            self.circuit_breakers[name] = ProviderCircuitBreaker(name)

        new_names = set(self.providers.keys())
        added = new_names - old_names
        removed = old_names - new_names
        kept = new_names & old_names

        logger.info(
            f"LLM 路由器已刷新: 新增 {list(added)}, 移除 {list(removed)}, "
            f"保留 {list(kept)}, 总计 {len(self.providers)} 个提供商"
        )
        return {
            "added": list(added),
            "removed": list(removed),
            "kept": list(kept),
            "total": len(self.providers),
        }

    async def close(self):
        for adapter in self.adapters.values():
            await adapter.close()


class _OpenAICompatResponse:
    """
    将 dict 包装为 OpenAI SDK 风格的响应对象，
    支持 response.choices[0].message.content / .tool_calls 访问。
    """

    def __init__(self, data: dict, model: str = ""):
        self._data = data
        self.model = model or data.get("model", "")
        self.choices = [_OpenAICompatChoice(c) for c in data.get("choices", [])]
        usage = data.get("usage", {})
        self.usage = _OpenAICompatUsage(usage) if usage else None


class _OpenAICompatUsage:
    def __init__(self, data: dict):
        self.prompt_tokens = data.get("prompt_tokens", 0)
        self.completion_tokens = data.get("completion_tokens", 0)
        self.total_tokens = self.prompt_tokens + self.completion_tokens


class _OpenAICompatChoice:
    def __init__(self, data: dict):
        msg = data.get("message", {})
        self.message = _OpenAICompatMessage(msg)
        self.finish_reason = data.get("finish_reason", "stop")


class _OpenAICompatMessage:
    def __init__(self, data: dict):
        self.role = data.get("role", "assistant")
        self.content = data.get("content", "")
        raw_tool_calls = data.get("tool_calls")
        if raw_tool_calls:
            self.tool_calls = [_OpenAICompatToolCall(tc) for tc in raw_tool_calls]
        else:
            self.tool_calls = None


class _OpenAICompatToolCall:
    def __init__(self, data: dict):
        self.id = data.get("id", "")
        self.type = data.get("type", "function")
        func = data.get("function", {})
        self.function = _OpenAICompatFunction(func)


class _OpenAICompatFunction:
    def __init__(self, data: dict):
        self.name = data.get("name", "")
        self.arguments = data.get("arguments", "{}")


# ───────────────────── 单例 ─────────────────────

_router_instance: Optional[MultiLLMRouter] = None


def get_llm_router() -> MultiLLMRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = MultiLLMRouter()
    return _router_instance


async def refresh_llm_router() -> Dict[str, Any]:
    """便捷函数：刷新全局 LLM 路由器的提供商列表"""
    router = get_llm_router()
    return await router.refresh_providers()
