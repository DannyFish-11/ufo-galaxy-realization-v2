"""
多 LLM 智能路由器 (Multi-LLM Router)
=====================================

真正的多提供商路由，直接调用 OpenAI / Claude / Gemini / DeepSeek / Ollama，
根据任务类型智能选择最优模型，支持故障转移和负载均衡。
"""

import asyncio
import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from core.credential_vault import PLACEHOLDER_PREFIXES
from core.model_catalog import SLOT_REASONING
from core.model_openness import treat_as_open_source as _treat_as_open_source

logger = logging.getLogger("Galaxy.LLMRouter")


# ───────────────────── 数据模型 ─────────────────────


class TaskType(Enum):
    """任务类型 → 决定模型选择策略"""

    REASONING = "reasoning"  # 复杂推理 → 强模型
    FAST_RESPONSE = "fast_response"  # 快速问答 → 快模型
    CODING = "coding"  # 代码生成 → 代码模型
    CREATIVE = "creative"  # 创作 → 创意模型
    ANALYSIS = "analysis"  # 分析 → 均衡模型
    PLANNING = "planning"  # 规划 → 强推理模型
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
    multimodal: bool = False  # 是否原生支持多模态（图像/音频/视频输入）
    env_key: str = ""  # 对应的环境变量名（用于可用性提示）
    # PR-HA: 硬件感知 + 多模态优先新增字段
    source_type: str = "api"  # "api" / "local" / "hf_local" / "oneapi"
    hardware_tier: str = "remote"  # "gpu_full" / "gpu_quantized" / "cpu" / "remote"
    supports_vision: bool = False  # 是否支持图像输入（VLM能力）
    supports_audio: bool = False  # 是否支持音频输入
    kv_cache_enabled: bool = False  # 是否启用KV cache（借鉴vLLM）
    prefix_cache_enabled: bool = False  # 是否启用前缀缓存（借鉴SGLang RadixAttention）
    quantization: str = "none"  # "none" / "q4" / "q5" / "q8" / "awq" / "gptq"
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
        路径】——route()/route_multimodal_first()/select_brain_for_task() 等
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
    # L2 级联路由元数据
    cascade_stage: int = 0  # 0-based:第几档答出来的(0=最便宜那档)
    cascade_escalated: bool = False  # 是否发生过升级(便宜档不合格才升到更贵档)


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
    "agnes": "AGNES_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "qwen": "QWEN_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
    "minimax": "MINIMAX_API_KEY",
    "step": "STEP_API_KEY",
    "mimo": "MIMO_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
    "perplexity": "PERPLEXITY_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
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
    # 2026-07-15: 移除 "hf_local"——其内部适配器从未被实现过,故永远不会注册,
    #   却曾占据每个列表的第 2 位,污染自动选择顺序。发现/注册代码保留在别处,
    #   仅从偏好列表里剔除。每个列表仍以本地 ollama 主脑打头。
    # 2026-07-15: 把已注册但从未进偏好列表的 agnes/moonshot/openrouter 接入自动路由——
    #   agnes(免费+多模态+工具)排在便宜开源之后、专有之前;moonshot(Kimi)入
    #   CODING/GENERAL/FAST_RESPONSE 尾;openrouter(聚合器)入 GENERAL/ANALYSIS 尾。
    # 2026-05-29: 新增 minimax/step/mimo 三个国产提供商
    # 2026-07-10: 新增 meta(Muse Spark 1.1,agentic/多模态/1M ctx)——
    # 定位在专有兜底梯队,agentic 任务(AGENT_CONTROL/CODING/PLANNING)优先级靠前
    # xai 补入:策略层 YAML 的 reasoning 一直有它,执行层这张表却没有 —— 两份真相里
    # 只存在于一侧的 provider,在另一条路上等于不存在。已加守卫测试防止再漂。
    TaskType.REASONING: ["ollama", "anthropic", "openai", "meta", "deepseek", "google", "qwen", "step", "xai"],
    TaskType.FAST_RESPONSE: ["ollama", "deepseek", "mimo", "agnes", "groq", "google", "openai", "zhipu", "moonshot"],
    TaskType.CODING: ["ollama", "deepseek", "qwen", "anthropic", "openai", "meta", "step", "mimo", "moonshot"],
    TaskType.CREATIVE: ["ollama", "openai", "anthropic", "mistral", "deepseek", "minimax"],
    TaskType.ANALYSIS: [
        "ollama",
        "anthropic",
        "openai",
        "meta",
        "deepseek",
        "google",
        "perplexity",
        "qwen",
        "step",
        "openrouter",
    ],
    TaskType.PLANNING: [
        "ollama",
        "anthropic",
        "openai",
        "meta",
        "deepseek",
        "xai",
        "qwen",
        "minimax",
        "step",
    ],
    TaskType.AGENT_CONTROL: ["ollama", "anthropic", "openai", "meta", "deepseek", "minimax", "step"],
    TaskType.GENERAL: [
        "ollama",
        "openai",
        "anthropic",
        "meta",
        "deepseek",
        "agnes",
        "google",
        "qwen",
        "zhipu",
        "minimax",
        "step",
        "mimo",
        "moonshot",
        "openrouter",
    ],
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
    "ollama",  # 本地原生多模态主脑（Gemma4 / MiniCPM-o）
    "hf_local",  # 本地 HuggingFace 模型
    "local_openai",  # 本地 OpenAI 兼容服务(llama.cpp SYCL/Vulkan、OpenVINO Model Server)
    "agnes",  # Agnes AI（全模态免费 API，开放/免费档友好）
    "deepseek",  # DeepSeek（开源权重）
    "qwen",  # 通义千问（开源权重）
    "zhipu",  # 智谱 GLM（开源权重）
    "groq",  # Groq 托管 Llama 等开源模型
    "minimax",  # MiniMax（部分开源）
    "step",  # 阶跃 StepFun
    "mimo",  # 小米 MiMo（开源）
    "moonshot",  # Kimi / Moonshot（Kimi-K2 开源）
    "mistral",  # Mistral（开源权重）
    "oneapi",  # OneAPI 聚合层（通常聚合开源模型）
}

# 专有闭源提供商（仅作高端兜底，开源优先时排最后）
PROPRIETARY_PROVIDERS: set = {
    "openai",
    "anthropic",
    "google",
    "xai",
    "perplexity",
}


def reorder_open_source_first(provider_order: List[str]) -> List[str]:
    """把开源提供商整体前移到专有提供商之前，保持各自原相对顺序（稳定排序）。

    纯函数、无副作用，便于单测。未知提供商按"开源"处理（更符合本仓库以开源
    自托管/聚合为主的现状），不会被错误地降级到专有兜底之后。

    刻意保持 **provider 粗粒度**，不改成按模型判
    ------------------------------------------------
    "按模型区分开闭源"这件事落在 ``_score()``（见 core/model_openness.py），不落在这里，
    原因是本函数是**预排序**：调用它时具体型号还没选出来（型号由后面的
    ``select_model_by_complexity()`` 按复杂度决定），此处没有可判的模型。真正的细判在
    ``_score()`` 里做，那时型号已知。

    因此别把这里"顺手改成"按模型判——那需要把型号解析器传进来，而它与本函数在
    ``route()`` 里的调用位置（候选还是一串纯 provider 名）不匹配。两处对**未登记**
    provider 的结论一致（都按开源），所以粗粒度预排序 + 细粒度打分不会互相打架。
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
    "critic": {"prefer_local": False, "task_type": TaskType.REASONING, "min_complexity": 0.7},
    "reviewer": {"prefer_local": False, "task_type": TaskType.REASONING, "min_complexity": 0.7},
    "reasoner": {"prefer_local": False, "task_type": TaskType.REASONING, "min_complexity": 0.7},
    "coordinator": {"prefer_local": False, "task_type": TaskType.PLANNING, "min_complexity": 0.6},
    "planner": {"prefer_local": False, "task_type": TaskType.PLANNING, "min_complexity": 0.6},
    "analyst": {"prefer_local": False, "task_type": TaskType.ANALYSIS, "min_complexity": 0.6},
    # 轻角色：执行/产出/感知 → 倾向本地小模型
    "executor": {"prefer_local": True, "task_type": TaskType.FAST_RESPONSE, "min_complexity": 0.0},
    "worker": {"prefer_local": True, "task_type": TaskType.GENERAL, "min_complexity": 0.0},
    "researcher": {"prefer_local": True, "task_type": TaskType.GENERAL, "min_complexity": 0.0},
    "coder": {"prefer_local": True, "task_type": TaskType.CODING, "min_complexity": 0.3},
    "writer": {"prefer_local": True, "task_type": TaskType.CREATIVE, "min_complexity": 0.0},
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
    "anthropic": 3,
    "openai": 3,
    "google": 3,
    "xai": 3,
    "deepseek": 3,
    "qwen": 3,
    "zhipu": 3,
    # tier 2 —— 强
    "minimax": 2,
    "step": 2,
    "moonshot": 2,
    "mistral": 2,
    "groq": 2,
    "mimo": 2,
    "perplexity": 2,
    "oneapi": 2,
    "agnes": 2,
    "openrouter": 2,
    # tier 1 —— 本地轻量（无 GPU 笔电主脑）
    "ollama": 1,
    "hf_local": 1,
    "local_openai": 1,
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
        # GPT-5.6 家族(2026-07-09 GA,2026-08-15 联网复核型号 id 仍正确):
        # gpt-5.6 = 旗舰 Sol 的别名(1.05M ctx/128K out);terra=日常均衡;
        # luna=快而省。价位在 2026-07-30 降过一轮(terra -20%、luna -80%,
        # sol 未变)——型号 id 不受影响,这里不复述具体数字,理由同 deepseek
        # 那条注释:没有一手定价页确认前不改会影响路由的 cost_in/cost_out。
        TaskType.REASONING: "gpt-5.6",
        TaskType.FAST_RESPONSE: "gpt-5.6-luna",
        TaskType.CODING: "gpt-5.6",
        TaskType.CREATIVE: "gpt-5.6",
        TaskType.ANALYSIS: "gpt-5.6",
        TaskType.PLANNING: "gpt-5.6",
        TaskType.AGENT_CONTROL: "gpt-5.6",
        TaskType.GENERAL: "gpt-5.6-terra",
    },
    "anthropic": {
        TaskType.REASONING: "claude-opus-5",
        TaskType.FAST_RESPONSE: "claude-sonnet-5",
        TaskType.CODING: "claude-sonnet-5",
        TaskType.CREATIVE: "claude-opus-5",
        TaskType.ANALYSIS: "claude-opus-5",
        TaskType.PLANNING: "claude-opus-5",
        TaskType.AGENT_CONTROL: "claude-sonnet-5",
        TaskType.GENERAL: "claude-sonnet-5",
    },
    "google": {
        # 注:gemini-3.5-pro 延期到 2026-07-17 才发布——此前表里引用它会 404。
        # 现全走 GA 的 3.5-flash;Pro 上线后把 CODING/PLANNING/AGENT 升回去。
        TaskType.REASONING: "gemini-3.5-flash",
        TaskType.FAST_RESPONSE: "gemini-3.5-flash",
        TaskType.CODING: "gemini-3.5-flash",
        TaskType.CREATIVE: "gemini-3.5-flash",
        TaskType.ANALYSIS: "gemini-3.5-flash",
        TaskType.PLANNING: "gemini-3.5-flash",
        TaskType.AGENT_CONTROL: "gemini-3.5-flash",
        TaskType.GENERAL: "gemini-3.5-flash",
    },
    "meta": {
        # 对齐 PROVIDER_REGISTRY['meta'] 的真实模型名(api.llama.com/compat/v1)。
        # 此前全部映射到 "muse-spark-1.1" —— registry 注释已明确它【并非真实模型】,
        # 而 map 对每个 TaskType 都有值、消费方永远取 map 值(不落到 default_model),
        # 于是每个走 meta 的请求都拿假模型名去请求 → 400/404、provider 被判 DOWN。
        # 重档用 Maverick(旗舰),快档用 Scout(轻量)。
        TaskType.REASONING: "Llama-4-Maverick-17B-128E-Instruct-FP8",
        TaskType.FAST_RESPONSE: "Llama-4-Scout-17B-16E-Instruct-FP8",
        TaskType.CODING: "Llama-4-Maverick-17B-128E-Instruct-FP8",
        TaskType.CREATIVE: "Llama-4-Maverick-17B-128E-Instruct-FP8",
        TaskType.ANALYSIS: "Llama-4-Maverick-17B-128E-Instruct-FP8",
        TaskType.PLANNING: "Llama-4-Maverick-17B-128E-Instruct-FP8",
        TaskType.AGENT_CONTROL: "Llama-4-Maverick-17B-128E-Instruct-FP8",
        TaskType.GENERAL: "Llama-4-Scout-17B-16E-Instruct-FP8",
    },
    "xai": {
        # Grok 4.6(联网核实 2026-08-12 发布,多源交叉确认):同 4.5 的 V9 基座/1.5T
        # 参数,靠后训练(SFT+RL)提升而非放大规模;500K 上下文,$2/M 输入 $6/M 输出。
        # Artificial Analysis Intelligence Index 与 GPT-5.6 Sol 打平,是当前智能
        # 前沿里最便宜的一档 —— 升为默认档,4.5 仍是有效型号,保留在 registry 里
        # 作为该家自己的旧档回退(不是"已下线,不该出现"那种要清掉的幽灵)。
        TaskType.REASONING: "grok-4.6",
        TaskType.FAST_RESPONSE: "grok-4.6",
        TaskType.CODING: "grok-4.6",
        TaskType.CREATIVE: "grok-4.6",
        TaskType.ANALYSIS: "grok-4.6",
        TaskType.PLANNING: "grok-4.6",
        TaskType.AGENT_CONTROL: "grok-4.6",
        TaskType.GENERAL: "grok-4.6",
    },
    "mistral": {
        TaskType.REASONING: "mistral-large-3",
        TaskType.FAST_RESPONSE: "mistral-large-3",
        TaskType.CODING: "mistral-large-3",
        TaskType.CREATIVE: "mistral-large-3",
        TaskType.ANALYSIS: "mistral-large-3",
        TaskType.PLANNING: "mistral-large-3",
        TaskType.AGENT_CONTROL: "mistral-large-3",
        TaskType.GENERAL: "mistral-large-3",
    },
    "deepseek": {
        TaskType.REASONING: "deepseek-v4-pro",
        TaskType.FAST_RESPONSE: "deepseek-v4-flash",
        TaskType.CODING: "deepseek-v4-pro",
        TaskType.CREATIVE: "deepseek-v4-pro",
        TaskType.ANALYSIS: "deepseek-v4-pro",
        TaskType.PLANNING: "deepseek-v4-pro",
        TaskType.AGENT_CONTROL: "deepseek-v4-pro",
        TaskType.GENERAL: "deepseek-v4-pro",
    },
    "qwen": {
        TaskType.REASONING: "qwen3.8-max",
        TaskType.CODING: "qwen3.8-coder",
        TaskType.FAST_RESPONSE: "qwen-flash",
        TaskType.GENERAL: "qwen3.8-max",
        TaskType.ANALYSIS: "qwen3.8-max",
        TaskType.PLANNING: "qwen3.8-max",
        TaskType.AGENT_CONTROL: "qwen3.8-max",
    },
    "zhipu": {
        TaskType.REASONING: "glm-5.2",
        TaskType.GENERAL: "glm-5.2",
        TaskType.ANALYSIS: "glm-5.2",
        TaskType.CODING: "glm-5.2",
        TaskType.FAST_RESPONSE: "glm-5.1-flash",
        TaskType.CREATIVE: "glm-5.2",
        TaskType.PLANNING: "glm-5.2",
    },
    "minimax": {
        # 对齐 PROVIDER_REGISTRY['minimax'].models(大小写敏感的官方 id):
        # 此前用小写 "minimax-m2.7"(registry 里根本没有此拼写)→ 请求即 404。
        # 重档 MiniMax-M3(default),快档 MiniMax-M2.7。
        TaskType.REASONING: "MiniMax-M3",
        TaskType.FAST_RESPONSE: "MiniMax-M2.7",
        TaskType.CODING: "MiniMax-M3",
        TaskType.CREATIVE: "MiniMax-M3",
        TaskType.ANALYSIS: "MiniMax-M3",
        TaskType.PLANNING: "MiniMax-M3",
        TaskType.AGENT_CONTROL: "MiniMax-M3",
        TaskType.GENERAL: "MiniMax-M2.7",
    },
    "step": {
        TaskType.REASONING: "step-3.7-flash",
        TaskType.FAST_RESPONSE: "step-3.7-turbo",
        TaskType.CODING: "step-3.7-flash",
        TaskType.CREATIVE: "step-3.7-flash",
        TaskType.ANALYSIS: "step-3.7-flash",
        TaskType.PLANNING: "step-3.7-flash",
        TaskType.AGENT_CONTROL: "step-3.7-flash",
        TaskType.GENERAL: "step-3.7-flash",
    },
    "mimo": {
        TaskType.REASONING: "mimo-v2.5-pro",
        TaskType.FAST_RESPONSE: "mimo-v2.5-lite",
        TaskType.CODING: "mimo-v2.5-pro",
        TaskType.CREATIVE: "mimo-v2.5-pro",
        TaskType.ANALYSIS: "mimo-v2.5-pro",
        TaskType.PLANNING: "mimo-v2.5-pro",
        TaskType.AGENT_CONTROL: "mimo-v2.5-pro",
        TaskType.GENERAL: "mimo-v2.5-pro",
    },
    "moonshot": {
        # Kimi K2 系取代老 moonshot-v1-*:k2.6=最新最强(代码/agent);
        # k2.5=原生多模态 256K 长上下文(2026-01 开源权重)。
        TaskType.GENERAL: "kimi-k3",
        TaskType.CODING: "kimi-k3",
        TaskType.ANALYSIS: "kimi-k2.6",
        TaskType.FAST_RESPONSE: "kimi-k2.6",
    },
    "agnes": {
        # 免费全模态,默认走 2.5-flash;直连路径据此解析出具体模型串。
        TaskType.FAST_RESPONSE: "agnes-2.5-flash",
        TaskType.GENERAL: "agnes-2.5-flash",
    },
    "openrouter": {
        # 聚合器,"auto" 让 OpenRouter 自选底层模型。
        TaskType.ANALYSIS: "openrouter/auto",
        TaskType.GENERAL: "openrouter/auto",
    },
    "perplexity": {
        TaskType.REASONING: "sonar-deep-research",
        TaskType.ANALYSIS: "sonar-pro",
        TaskType.GENERAL: "sonar-pro",
    },
    "groq": {
        TaskType.FAST_RESPONSE: "llama-3.3-70b-versatile",
        TaskType.GENERAL: "llama-3.3-70b-versatile",
    },
    "ollama": {
        TaskType.REASONING: "gemma4:12b",
        TaskType.FAST_RESPONSE: "gemma4:e4b",
        TaskType.CODING: "gemma4:12b",
        TaskType.CREATIVE: "gemma4:12b",
        TaskType.ANALYSIS: "gemma4:26b",
        TaskType.PLANNING: "gemma4:26b",
        TaskType.AGENT_CONTROL: "gemma4:12b",
        TaskType.GENERAL: "gemma4:e4b",
    },
    "hf_local": {
        TaskType.REASONING: "Qwen/Qwen2.5-14B-Instruct",
        TaskType.FAST_RESPONSE: "Qwen/Qwen2.5-3B-Instruct",
        TaskType.CODING: "Qwen/Qwen2.5-Coder-14B-Instruct",
        TaskType.CREATIVE: "Qwen/Qwen2.5-14B-Instruct",
        TaskType.ANALYSIS: "Qwen/Qwen2.5-14B-Instruct",
        TaskType.PLANNING: "Qwen/Qwen2.5-14B-Instruct",
        TaskType.AGENT_CONTROL: "Qwen/Qwen2.5-14B-Instruct",
        TaskType.GENERAL: "Qwen/Qwen2.5-14B-Instruct",
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

    def __init__(
        self, name: str, failure_threshold: int = 5, recovery_timeout: float = 60.0, half_open_max_calls: int = 2
    ):
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
            logger.warning(f"断路器 [{self.name}] CLOSED → OPEN " f"(连续 {self._consecutive_failures} 次失败)")

    def to_dict(self) -> Dict:
        return {
            "state": self.state,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
        }


class BaseProviderAdapter:
    """提供商适配器基类"""

    DEFAULT_TIMEOUT = 30.0  # 默认请求超时
    MAX_RETRIES = 2  # 最大重试次数
    RETRY_BASE_DELAY = 1.0  # 重试基础延迟

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
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Retryable HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                        resp.status_code,
                        self.config.name,
                        attempt + 1,
                        self.MAX_RETRIES + 1,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                return resp
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        "Timeout from %s (attempt %d/%d), retrying in %.1fs",
                        self.config.name,
                        attempt + 1,
                        self.MAX_RETRIES + 1,
                        delay,
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

    async def chat(
        self,
        messages: List[Dict],
        model: str,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        **kwargs,
    ) -> LLMResponse:
        raise NotImplementedError(
            f"Provider adapter '{self.config.name}' 未实现 chat()，"
            f"请使用具体的适配器子类 (OpenAI/Anthropic/Google/DeepSeek)"
        )

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class OpenAIAdapter(BaseProviderAdapter):
    """OpenAI / OpenAI-compatible adapter"""

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
        headers = {"Content-Type": "application/json"}
        # 无鉴权的自托管服务(llama.cpp server / OpenVINO Model Server 默认不开
        # 鉴权)把 api_key 留空。此时**不能**照发 "Bearer " —— httpx 会在发出前就
        # 抛 LocalProtocolError: Illegal header value b'Bearer '。真实调用实测:
        # 一个 api_key="" 的 OpenAI 兼容 provider 每一次请求都在这一步直接炸,
        # 连不上服务器,报错还长得像网络问题。留空就干脆不带这个头。
        if (self.config.api_key or "").strip():
            headers["Authorization"] = f"Bearer {self.config.api_key}"
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

        # 真流式:消费端挂了 TokenStream 且不是结构化输出请求时,SSE 边生成边吐字。
        # 任何流式失败都作废已流出内容并退回下面的非流式老路径(行为兜底不变)。
        _sink = kwargs.get("stream")
        if _sink is not None and response_format is None:
            try:
                return await self._chat_streaming(
                    headers=headers,
                    body=body,
                    model=model,
                    sink=_sink,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("OpenAI 兼容流式失败,退回非流式: %s", exc)
                try:
                    _sink.reset()
                except Exception:  # noqa: BLE001
                    pass

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/chat/completions",
            headers=headers,
            body=body,
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

    @staticmethod
    def _merge_tool_call_delta(acc: Dict[int, Dict[str, Any]], delta_tc: Dict[str, Any]) -> None:
        """把一条流式 tool_call 增量并进按 index 聚合的累积表。

        OpenAI 流式协议:tool_calls 增量按 ``index`` 定位;首个增量带 id/name,
        后续增量只带 ``function.arguments`` 的字符串片段,需按序拼接。
        """
        idx = int(delta_tc.get("index", 0) or 0)
        slot = acc.setdefault(
            idx,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )
        if delta_tc.get("id"):
            slot["id"] = delta_tc["id"]
        if delta_tc.get("type"):
            slot["type"] = delta_tc["type"]
        fn = delta_tc.get("function") or {}
        if fn.get("name"):
            slot["function"]["name"] = fn["name"]
        if fn.get("arguments"):
            slot["function"]["arguments"] += fn["arguments"]

    async def _chat_streaming(self, *, headers, body, model, sink) -> LLMResponse:
        """OpenAI 兼容 SSE 真流式:content 增量喂 sink,tool_calls 增量按 index 组装。

        只把【正文】流出给用户;工具调用参数片段绝不进 sink。usage 仅在服务端支持
        ``stream_options.include_usage`` 时可得,拿不到就记 0(成本统计的已知取舍)。
        """
        stream_body = {**body, "stream": True, "stream_options": {"include_usage": True}}
        client = await self._get_client()
        t0 = time.monotonic()
        content_parts: List[str] = []
        tool_acc: Dict[int, Dict[str, Any]] = {}
        usage: Dict[str, Any] = {}
        async with client.stream(
            "POST",
            f"{self.config.base_url}/chat/completions",
            headers=headers,
            json=stream_body,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = (line or "").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except (ValueError, TypeError):
                    continue
                if isinstance(chunk.get("usage"), dict):
                    usage = chunk["usage"]
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                piece = delta.get("content")
                if piece:
                    content_parts.append(piece)
                    sink.feed(piece)
                for delta_tc in delta.get("tool_calls") or []:
                    if isinstance(delta_tc, dict):
                        self._merge_tool_call_delta(tool_acc, delta_tc)
        latency = (time.monotonic() - t0) * 1000
        tool_calls = [tool_acc[i] for i in sorted(tool_acc)] or None
        return LLMResponse(
            content="".join(content_parts),
            provider=self.config.name,
            model=model,
            input_tokens=int(usage.get("prompt_tokens", 0) or 0),
            output_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_ms=latency,
            tool_calls=tool_calls,
            raw_response=None,  # 流式无整包 JSON;下游一律以 LLMResponse 字段为准
        )


class AnthropicAdapter(BaseProviderAdapter):
    """Anthropic Claude adapter (Messages API)"""

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
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
            headers=headers,
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        content = ""
        tool_calls = []
        for block in data.get("content", []):
            if block["type"] == "text":
                content += block["text"]
            elif block["type"] == "tool_use":
                tool_calls.append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    }
                )

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
                anthropic_tools.append(
                    {
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
                    }
                )
        return anthropic_tools


class OllamaAdapter(BaseProviderAdapter):
    """Ollama local model adapter

    工具调用双协议:
      1. **原生 function calling**(qwen/minicpm/llama3.1 等带工具模板的模型):
         tools 随请求体,解析 message.tool_calls。
      2. **文本协议兜底**(gemma 系等无工具模板的模型,Ollama 回 400
         "does not support tools"):把工具清单注入系统消息,约定模型用一行
         JSON ``{"tool_call": {"name": ..., "arguments": {...}}}`` 表达调用,
         从回复文本解析并归一成 OpenAI 形状——gemma 也能真正调工具
         (表达力略逊原生,但完整可用)。一旦某模型判定为无模板,按模型名
         缓存,后续请求直接走文本协议,不再吃 400 往返。
    """

    #: 已判定不支持原生工具的模型(进程内缓存,免每次吃 400)
    _text_protocol_models: set = set()

    _TEXT_TOOL_INSTRUCTION = (
        "你可以调用以下工具来完成任务。工具清单(JSON Schema):\n{tool_specs}\n"
        "调用规则:需要调用工具时,只输出一行 JSON(不要任何其它文字、"
        "不要代码围栏):\n"
        '{{"tool_call": {{"name": "<工具名>", "arguments": {{<参数>}}}}}}\n'
        "工具结果会以 [工具结果] 消息回给你;不需要工具时直接正常回答。"
    )

    @classmethod
    def _tools_prompt(cls, tools: List[Dict]) -> str:
        specs = []
        for t in tools or []:
            fn = t.get("function") if isinstance(t, dict) else None
            if isinstance(fn, dict):
                specs.append(
                    {
                        "name": fn.get("name", ""),
                        "description": (fn.get("description") or "")[:200],
                        "parameters": fn.get("parameters") or {},
                    }
                )
        return cls._TEXT_TOOL_INSTRUCTION.format(tool_specs=json.dumps(specs, ensure_ascii=False))

    @classmethod
    def _inject_text_tools(cls, messages: List[Dict], tools: List[Dict]) -> List[Dict]:
        """把工具清单作为系统消息注入(紧跟首条 system 之后,前缀尽量稳定)。"""
        tool_msg = {"role": "system", "content": cls._tools_prompt(tools)}
        out = list(messages)
        idx = 1 if (out and out[0].get("role") == "system") else 0
        out.insert(idx, tool_msg)
        return out

    @staticmethod
    def _textualize_tool_history(messages: List[Dict]) -> List[Dict]:
        """文本协议模型看不懂 role=tool / assistant.tool_calls——把工具轮历史
        转成纯文本(assistant 的调用还原成它当初输出的 JSON 行;tool 结果转
        user 的 [工具结果] 消息),模板不炸、上下文语义不丢。"""
        out: List[Dict] = []
        for m in messages:
            if not isinstance(m, dict):
                out.append(m)
                continue
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                lines = []
                for tc in m["tool_calls"]:
                    fn = (tc or {}).get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (ValueError, TypeError):
                            args = {}
                    lines.append(
                        json.dumps(
                            {"tool_call": {"name": fn.get("name", ""), "arguments": args or {}}}, ensure_ascii=False
                        )
                    )
                content = (m.get("content") or "").strip()
                out.append({"role": "assistant", "content": (content + "\n" if content else "") + "\n".join(lines)})
            elif role == "tool":
                out.append({"role": "user", "content": f"[工具结果] {m.get('content', '')}"})
            else:
                out.append(m)
        return out

    @staticmethod
    def _parse_text_tool_calls(content: str) -> Optional[List[Dict]]:
        """从回复文本解析 {"tool_call": {...}} 调用(容忍前后缀文字/代码围栏),
        归一成 OpenAI 形状。没有合法调用返回 None(当普通回答)。"""
        if not content or '"tool_call"' not in content:
            return None
        calls: List[Dict] = []
        i = 0
        while True:
            k = content.find('"tool_call"', i)
            if k < 0:
                break
            start = content.rfind("{", 0, k)
            if start < 0:
                i = k + 11
                continue
            depth = 0
            end = -1
            for j in range(start, len(content)):
                if content[j] == "{":
                    depth += 1
                elif content[j] == "}":
                    depth -= 1
                    if depth == 0:
                        end = j
                        break
            if end < 0:
                break
            try:
                obj = json.loads(content[start : end + 1])
                tc = obj.get("tool_call") or {}
                name = tc.get("name", "")
                if name:
                    calls.append(
                        {
                            "id": f"ollama_text_call_{len(calls)}_{name}",
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False),
                            },
                        }
                    )
            except (ValueError, TypeError):
                pass
            i = end + 1 if end >= 0 else k + 11
        return calls or None

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

    @staticmethod
    def _normalize_tool_calls(raw_calls: Any) -> Optional[List[Dict]]:
        """Ollama 原生 tool_calls → OpenAI 形状(下游 ReAct 统一按此消费)。

        差异:Ollama 的 function.arguments 是 **dict**(OpenAI 是 JSON 字符串),
        且不带 id。这里统一转字符串 + 合成 id,让 openclawd 的
        ``json.loads(fn["arguments"])`` 两家通吃。
        """
        if not raw_calls:
            return None
        out: List[Dict] = []
        for i, tc in enumerate(raw_calls):
            fn = (tc or {}).get("function") or {}
            args = fn.get("arguments")
            if isinstance(args, (dict, list)):
                args = json.dumps(args, ensure_ascii=False)
            elif not isinstance(args, str):
                args = "{}"
            out.append(
                {
                    "id": tc.get("id") or f"ollama_call_{i}_{fn.get('name', '')}",
                    "type": "function",
                    "function": {"name": fn.get("name", ""), "arguments": args},
                }
            )
        return out or None

    @staticmethod
    def _is_tools_unsupported_error(exc: Exception) -> bool:
        """Ollama 对无工具模板的模型(如 gemma 系)回 400 'does not support tools'。"""
        try:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
                return exc.response.status_code == 400 and "tool" in exc.response.text.lower()
        except Exception:  # noqa: BLE001
            pass
        return False

    async def chat(
        self, messages, model, tools=None, temperature=0.7, max_tokens=4096, response_format=None, **kwargs
    ) -> LLMResponse:
        # 模型常驻不卸载(-1):Ollama 默认几分钟不用就卸出内存,下次请求整段
        # 冷加载——真机"等待窗口未响应/像冷启动"的来源。按请求带上,即使
        # ollama serve 是安装器自启的(拿不到我们 spawn 时的环境变量)也生效。
        # 纯数字须转 int(JSON number;裸 "-1" 字符串无时长单位会解析失败),
        # "10m" 之类的时长字符串原样透传。
        _keep_alive: Any = os.environ.get("GALAXY_OLLAMA_KEEP_ALIVE", "-1")
        try:
            _keep_alive = int(_keep_alive)
        except (TypeError, ValueError):
            pass
        _options: Dict[str, Any] = {"temperature": temperature, "num_predict": max_tokens}
        # num_ctx 显式设置:系统提示+工具定义+记忆+历史很容易超过模型默认上下文
        # (常为 4096),一旦溢出 Ollama 滑窗截断 → 前缀 KV 缓存每轮全废 → 每轮
        # ReAct 全量重预填,CPU 机上就是"越聊越慢"。默认 8192;设 0/空 则不传
        # (回到模型默认)。
        try:
            _num_ctx = int(os.environ.get("GALAXY_OLLAMA_NUM_CTX", "8192"))
            if _num_ctx > 0:
                _options["num_ctx"] = _num_ctx
        except (TypeError, ValueError):
            _options["num_ctx"] = 8192
        body = {
            "model": model,
            "messages": self._to_ollama_messages(messages),
            "stream": False,
            "options": _options,
            "keep_alive": _keep_alive,
        }
        # 原生 function calling:Ollama /api/chat 支持 OpenAI 形状的 tools
        # (qwen/minicpm/llama3.1 等带工具模板的模型)。此前适配器收了 tools
        # 却不发——本地主脑从来"看不到"工具,整个 ReAct 工具层对 Ollama 是哑的。
        if tools:
            body["tools"] = tools

        # 调用点兜底:即使 config.base_url 因某条边缘路径被置空/缺协议头,
        # 也在此归一,绝不把坏 URL 交给 httpx(否则炸 "Request URL is missing
        # an 'http://' or 'https://' protocol")。
        _base = (self.config.base_url or "").strip() or "http://localhost:11434"
        if not _base.startswith(("http://", "https://")):
            _base = f"http://{_base}"

        # 已知无工具模板的模型(gemma 系,进程内缓存):直接走文本协议,
        # 不再吃一次 400 往返。
        if tools and model in type(self)._text_protocol_models:
            return await self._chat_text_protocol(
                base=_base,
                messages=messages,
                model=model,
                tools=tools,
                options=_options,
                keep_alive=_keep_alive,
                sink=kwargs.get("stream"),
            )

        # 真流式:消费端挂了 TokenStream 时走 NDJSON 流(CPU 慢速生成下体感差异
        # 最大的一段——首句几秒就能上屏,不用等整段几十秒)。失败作废已流出内容,
        # 退回下面的非流式老路径。
        _sink = kwargs.get("stream")
        if _sink is not None:
            try:
                return await self._chat_streaming(
                    base=_base,
                    body=body,
                    model=model,
                    sink=_sink,
                )
            except Exception as exc:  # noqa: BLE001
                if self._is_tools_unsupported_error(exc) and "tools" in body:
                    # 模型无工具模板(gemma 系):切文本协议重试——工具清单注入
                    # 提示词、从文本解析 JSON 调用,gemma 也能真正调工具。
                    logger.info(
                        "Ollama 模型 %s 不支持原生工具,切文本协议工具兜底",
                        model,
                    )
                    try:
                        _sink.reset()
                    except Exception:  # noqa: BLE001
                        pass
                    return await self._chat_text_protocol(
                        base=_base,
                        messages=messages,
                        model=model,
                        tools=tools,
                        options=_options,
                        keep_alive=_keep_alive,
                        sink=_sink,
                    )
                logger.info("Ollama 流式失败,退回非流式: %s", exc)
                try:
                    _sink.reset()
                except Exception:  # noqa: BLE001
                    pass

        t0 = time.monotonic()
        try:
            resp = await self._post_with_retry(
                f"{_base}/api/chat",
                headers={"Content-Type": "application/json"},
                body=body,
            )
        except httpx.HTTPStatusError as exc:
            if not (self._is_tools_unsupported_error(exc) and "tools" in body):
                raise
            logger.info(
                "Ollama 模型 %s 不支持原生工具,切文本协议工具兜底",
                model,
            )
            return await self._chat_text_protocol(
                base=_base,
                messages=messages,
                model=model,
                tools=tools,
                options=_options,
                keep_alive=_keep_alive,
                sink=kwargs.get("stream"),
            )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()

        _msg = data.get("message", {}) or {}
        return LLMResponse(
            content=_msg.get("content", ""),
            provider=self.config.name,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=latency,
            tool_calls=self._normalize_tool_calls(_msg.get("tool_calls")),
            raw_response=data,
        )

    async def _chat_text_protocol(
        self,
        *,
        base,
        messages,
        model,
        tools,
        options,
        keep_alive,
        sink=None,
    ) -> LLMResponse:
        """文本协议工具兜底:无工具模板模型(gemma 系)的完整工具调用通路。

        - 工具清单注入系统消息;工具轮历史文本化(模板不炸);
        - 非流式请求(避免半截 JSON 泄进面板气泡);
        - 回复里解析到 {"tool_call": ...} → 归一成 OpenAI 形状返回给 ReAct;
          没解析到 → 普通回答,整段补喂 sink(伪流式,面板仍有字)。
        """
        type(self)._text_protocol_models.add(model)
        msgs = self._inject_text_tools(self._textualize_tool_history(messages), tools)
        body = {
            "model": model,
            "messages": self._to_ollama_messages(msgs),
            "stream": False,
            "options": options,
            "keep_alive": keep_alive,
        }
        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{base}/api/chat",
            headers={"Content-Type": "application/json"},
            body=body,
        )
        latency = (time.monotonic() - t0) * 1000
        data = resp.json()
        _msg = data.get("message", {}) or {}
        content = _msg.get("content", "") or ""
        tool_calls = self._parse_text_tool_calls(content)
        if tool_calls is None and sink is not None:
            try:
                sink.feed(content)
            except Exception:  # noqa: BLE001
                pass
        return LLMResponse(
            # 解析到调用时正文置空:JSON 调用行是协议载荷,不是给用户看的话
            content="" if tool_calls else content,
            provider=self.config.name,
            model=model,
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=latency,
            tool_calls=tool_calls,
            raw_response=data,
        )

    async def _chat_streaming(self, *, base, body, model, sink) -> LLMResponse:
        """Ollama /api/chat NDJSON 真流式:每行一个 JSON 块,message.content 是增量;
        末块 done=true 携带 prompt_eval_count/eval_count(token 统计不丢)。"""
        stream_body = {**body, "stream": True}
        client = await self._get_client()
        t0 = time.monotonic()
        content_parts: List[str] = []
        raw_tool_calls: List[Dict] = []
        final: Dict[str, Any] = {}
        async with client.stream(
            "POST",
            f"{base}/api/chat",
            headers={"Content-Type": "application/json"},
            json=stream_body,
        ) as resp:
            if getattr(resp, "status_code", 200) >= 400:
                # 让 chat() 的"模型不支持工具 → 去工具重试"能拿到响应体判因
                await resp.aread()
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                line = (line or "").strip()
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except (ValueError, TypeError):
                    continue
                _cmsg = chunk.get("message") or {}
                piece = _cmsg.get("content", "")
                if piece:
                    content_parts.append(piece)
                    sink.feed(piece)
                # 工具调用块:Ollama 流式在(通常是末尾的)块上整只给出
                # message.tool_calls,不是 OpenAI 式碎片增量——直接收集,
                # 绝不喂 sink(工具调用不是正文)。
                if _cmsg.get("tool_calls"):
                    raw_tool_calls.extend(_cmsg["tool_calls"])
                if chunk.get("done"):
                    final = chunk
        latency = (time.monotonic() - t0) * 1000
        return LLMResponse(
            content="".join(content_parts),
            provider=self.config.name,
            model=model,
            input_tokens=int(final.get("prompt_eval_count", 0) or 0),
            output_tokens=int(final.get("eval_count", 0) or 0),
            latency_ms=latency,
            tool_calls=self._normalize_tool_calls(raw_tool_calls),
            raw_response=final or None,
        )


# ───────────────────── 主路由器 ─────────────────────

# L1 收口:协议 → 适配器工厂。此前每个 OpenAI 兼容提供商都有一个空壳子类
# (class DeepSeekAdapter(OpenAIAdapter): pass …共 12 个),纯冗余。现在按【协议】
# 选适配器:openai 兼容全用 OpenAIAdapter、anthropic 用 AnthropicAdapter、
# 本地 ollama 用 OllamaAdapter。新增一个 OpenAI 兼容提供商不再需要建类。
_ADAPTER_BY_PROTOCOL: Dict[str, type] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "ollama": OllamaAdapter,
}

# 兼容:老代码/外部若按名取适配器类,仍可用(全部收敛到真实类,不再指向空壳)。
ADAPTER_MAP = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "google": OpenAIAdapter,
    "xai": OpenAIAdapter,
    "meta": OpenAIAdapter,
    "mistral": OpenAIAdapter,
    "agnes": OpenAIAdapter,
    "deepseek": OpenAIAdapter,
    "qwen": OpenAIAdapter,
    "zhipu": OpenAIAdapter,
    "minimax": OpenAIAdapter,
    "step": OpenAIAdapter,
    "mimo": OpenAIAdapter,
    "moonshot": OpenAIAdapter,
    "perplexity": OpenAIAdapter,
    "groq": OpenAIAdapter,
    "openrouter": OpenAIAdapter,
    "ollama": OllamaAdapter,
    "hf_local": OpenAIAdapter,
}

# ───────────────────────────────────────────────────────────────────────────
# L1 声明式提供商注册表(单一属主)
# ───────────────────────────────────────────────────────────────────────────
# 此前 _discover_providers 里 15 个云端提供商各是一段几乎一字不差的 16 行复制
# (key=_get_key(); if key: cfg=ProviderConfig(...); adapters[x]=XAdapter(cfg))。
# 现把"给个 key 就注册"的标准 OpenAI/Anthropic 兼容提供商全部收敛成【一张数据表】,
# _register_from_registry() 从表循环派生 —— 新增提供商 = 表里加一行。
#
# 特殊发现逻辑(本地探测/动态模型列表)的 ollama / hf_local / oneapi 不入表,仍走
# 各自的专门发现分支。
#
# 字段(name/env_key/base_url/models/default_model/cost_in/cost_out 必填,其余可省):
#   protocol   "openai"(默认) | "anthropic" —— 决定用哪个适配器
#   alt_env    备用环境变量名列表(如 qwen 的 DASHSCOPE_API_KEY、google 的 GEMINI_API_KEY)
#   base_env / base_key  用环境变量 / Dashboard 短键覆盖 base_url(openai 的 OPENAI_API_BASE)
#   extra      透传给 ProviderConfig 的其它非默认字段(multimodal / supports_tools /
#              supports_vision / max_tokens 等)
PROVIDER_REGISTRY: List[Dict[str, Any]] = [
    {
        "name": "openai",
        "env_key": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "base_env": "OPENAI_API_BASE",
        "base_key": "openai_base",
        "models": ["gpt-5.6", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-4o"],
        "default_model": "gpt-5.6",
        # 双工(语音实时)型号。与上面的文本型号分开列：两者走的是不同接口
        # (Realtime WebSocket vs Chat Completions),上游的下线节奏也不同 ——
        # 此前 voice_duplex_session 把型号写死在代码里、不在本 registry 中,
        # 于是 verify_provider_apis.py 的上游比对完全覆盖不到它,漂移无人发现。
        "realtime_models": ["gpt-realtime"],
        "default_realtime_model": "gpt-realtime",
        "cost_in": 0.005,
        "cost_out": 0.015,
        "extra": {"multimodal": True},
    },
    {
        "name": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5-20251001"],
        "default_model": "claude-sonnet-5",
        "cost_in": 0.003,
        "cost_out": 0.015,
        "extra": {"multimodal": True},
    },
    {
        "name": "google",
        "env_key": "GOOGLE_API_KEY",
        "alt_env": ["GEMINI_API_KEY"],
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-3.5-flash", "gemini-3.5-pro", "gemini-2.5-pro"],
        "default_model": "gemini-3.5-flash",
        # Live API(BidiGenerateContent)的原生音频型号,同样与文本型号分开维护。
        "realtime_models": ["gemini-2.5-flash-native-audio-preview-12-2025"],
        "default_realtime_model": "gemini-2.5-flash-native-audio-preview-12-2025",
        # Live API 的 WebSocket 接口版本。官方文档现给 v1beta;v1alpha 仅用于
        # affective dialog / proactive audio 等尚未升级的特性。做成字段而非写死,
        # 是因为这个版本号历史上换过,写死在 URL 里会再次悄悄过期。
        "realtime_api_version": "v1beta",
        "cost_in": 0.00125,
        "cost_out": 0.005,
        "extra": {"multimodal": True},
    },
    {
        # Grok 4.6 —— 联网核实,2026-08-12 发布,xAI 官方 API / OpenRouter / Cursor /
        # Vercel / Cloudflare 同步上线,base_url/协议与 4.5 一致(同一 provider,
        # 只是新模型 id),不是猜的命名惯例延伸。
        "name": "xai",
        "env_key": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-4.6", "grok-4.5", "grok-4.3"],
        "default_model": "grok-4.6",
        "cost_in": 0.002,
        "cost_out": 0.006,
        "extra": {"multimodal": True},
    },
    {
        # Meta Llama API(联网核实 llama.developer.meta.com 官方文档):OpenAI 兼容 base
        # 是 api.llama.com/compat/v1,不是 api.meta.ai;"muse-spark" 并非真实模型,
        # 改用官方 Llama-4 模型名。注意:Meta 已于 2026-07-06 起【收尾 Llama API 公测】
        # (仅美区 waitlist),该 provider 实际多半不可用——保留正确配置,能用则用,
        # 不能用则由 verify_provider 如实报错、路由自动跳过。
        "name": "meta",
        "env_key": "META_API_KEY",
        "base_url": "https://api.llama.com/compat/v1",
        "models": ["Llama-4-Maverick-17B-128E-Instruct-FP8", "Llama-4-Scout-17B-16E-Instruct-FP8"],
        "default_model": "Llama-4-Maverick-17B-128E-Instruct-FP8",
        "cost_in": 0.00125,
        "cost_out": 0.00425,
        "extra": {"multimodal": True, "supports_vision": True, "max_tokens": 8192},
    },
    {
        # Agnes AI:全模态免费 API(2026),OpenAI 兼容协议。
        # agnes-2.5-flash 2026-07-13 发布(agentic/编码强化,免费不限量);
        # 2.0 仍可用作兜底(256K 上下文/64K 输出,免费档 20 RPM)。
        # 2.5 的准确串遵循官方命名规约(1.5→2.0→2.5),若有出入由 L4
        # 模型名单自动同步(/models 对账)+ 面板 verify_provider 试调纠正。
        # 图像(agnes-image-2.x)/视频(agnes-video-v2.0)模型不入聊天路由,
        # 属扩展层能力,按需另接。
        "name": "agnes",
        "env_key": "AGNES_API_KEY",
        "base_url": "https://apihub.agnes-ai.com/v1",
        "models": ["agnes-2.5-flash", "agnes-2.0-flash"],
        "default_model": "agnes-2.5-flash",
        "cost_in": 0.0,
        "cost_out": 0.0,
        "extra": {"multimodal": True, "supports_vision": True, "supports_tools": True},
    },
    {
        "name": "mistral",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-3", "mistral-medium-3", "mistral-large-2"],
        "default_model": "mistral-large-3",
        "cost_in": 0.002,
        "cost_out": 0.006,
        "extra": {"multimodal": True},
    },
    {
        # deepseek-v4-pro 型号 id 本身核对过仍然正确(2026-08-15 联网核实,当前上游
        # 快照 deepseek-v4-pro-0813)。但多个第三方计费站点显示价格明显上调过
        # (缓存未命中输入/输出都涨到原来的十几倍),而这里 cost_in/cost_out 是
        # cost_budget SLO 用来做路由判断的字段——没有拿到官方一手定价页确认具体
        # 数字前,宁可不动这两个值,也不要把聚合站估算塞进一个会影响路由行为的
        # 字段。要拿准确数字,配好 DEEPSEEK_API_KEY 跑一次
        # verify_provider_apis.py --only deepseek(它走的是路由器自己的请求链路,
        # 不是这里去猜)。即便按查到的高估计,换算下来仍远低于本仓各任务类型的
        # cost_budget 阈值,不会现在就影响路由结果。
        "name": "deepseek",
        "env_key": "DEEPSEEK_API_KEY",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-v4-pro", "deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner"],
        "default_model": "deepseek-v4-pro",
        "cost_in": 0.000025,
        "cost_out": 0.00006,
    },
    {
        "name": "qwen",
        "env_key": "QWEN_API_KEY",
        "alt_env": ["DASHSCOPE_API_KEY"],
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.8-max", "qwen3.8-coder", "qwen-flash", "qwen3.7-max", "qwen3.7-coder", "qwen3-235b-a22b"],
        "default_model": "qwen3.8-max",
        "cost_in": 0.0025,
        "cost_out": 0.0075,
        "extra": {"multimodal": True},
    },
    {
        # 查过 GLM-5.3(2026-08-15 联网核实,发布于 2026-08-14):**刻意不加进 models**。
        # 它目前只通过 GLM Coding Plan / 编码 CLI 发布,权重还差两周才放出,标准
        # open.bigmodel.cn 端点(本 provider 实际调用的那个)上的公开 model id 与
        # 独立计费"仍在安全评审后才放出"——不是本仓命名惯例推出来的猜测,是查到
        # 它现在**还没有**。这种时候加进去,后果和本轮修的那 8 处"清单声称有、
        # 实际没有"是同一类:选路成功,直到真发请求才 404。等它经标准 API 开放,
        # 用 verify_provider_apis.py --only zhipu 核验后再升,不要提前抄。
        "name": "zhipu",
        "env_key": "ZHIPU_API_KEY",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-5.2", "glm-5.1", "glm-5.1-flash", "glm-4-plus"],
        "default_model": "glm-5.2",
        "cost_in": 0.001,
        "cost_out": 0.001,
        "extra": {"multimodal": True},
    },
    {
        # 官方 OpenAI 兼容端点(联网核实 platform.minimax.io 官方文档):base 是
        # api.minimax.io/v1,不是旧的 api.minimax.chat(已非官方端点)。当前主力
        # MiniMax-M3(1M 上下文·agentic),M2.7/M2.5 仍在。模型名大小写按官方。
        "name": "minimax",
        "env_key": "MINIMAX_API_KEY",
        "base_url": "https://api.minimax.io/v1",
        "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.5"],
        "default_model": "MiniMax-M3",
        "cost_in": 0.001,
        "cost_out": 0.004,
        "extra": {"multimodal": True},
    },
    {
        "name": "step",
        "env_key": "STEP_API_KEY",
        "base_url": "https://api.stepfun.com/v1",
        "models": ["step-3.7-flash", "step-3.7-turbo", "step-3.7-mini"],
        "default_model": "step-3.7-flash",
        "cost_in": 0.001,
        "cost_out": 0.004,
        "extra": {"multimodal": True},
    },
    {
        "name": "mimo",
        "env_key": "MIMO_API_KEY",
        "base_url": "https://api.xiaomimimo.com/v1",
        "models": ["mimo-v2.5-pro", "mimo-v2.5-standard", "mimo-v2.5-lite"],
        "default_model": "mimo-v2.5-pro",
        "cost_in": 0.00002,
        "cost_out": 0.00008,
    },
    {
        "name": "moonshot",
        "env_key": "MOONSHOT_API_KEY",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k3", "kimi-k2.6", "kimi-k2.5", "moonshot-v1-128k"],
        "default_model": "kimi-k3",
        "cost_in": 0.002,
        "cost_out": 0.002,
    },
    {
        "name": "perplexity",
        "env_key": "PERPLEXITY_API_KEY",
        # SONAR_API_KEY 是面板公开的别名,"已配置"角标本就认它;缺了这行会导致
        # 面板亮绿标而路由器不读 → 密钥静默失效(见 tests/test_panel_api_key_routing.py)
        "alt_env": ["SONAR_API_KEY"],
        "base_url": "https://api.perplexity.ai",
        "models": ["sonar-pro", "sonar-deep-research", "sonar-reasoning-pro", "sonar"],
        "default_model": "sonar-pro",
        "cost_in": 0.001,
        "cost_out": 0.001,
        "extra": {"supports_tools": False},
    },
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile"],
        "default_model": "llama-3.3-70b-versatile",
        "cost_in": 0.00059,
        "cost_out": 0.00079,
        "extra": {"supports_tools": True},
    },
    {
        # OpenRouter:OpenAI 兼容的聚合器,"openrouter/auto" 让其自选底层模型。
        # cost 0 为占位——真实成本随所选底层模型浮动,由计费层回填。
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "models": ["openrouter/auto"],
        "default_model": "openrouter/auto",
        "cost_in": 0.0,
        "cost_out": 0.0,
        # extra 会被 **unpack 进 ProviderConfig,只能用其合法字段;聚合器语义用
        # source_type="api" 即可(无 aggregator 字段,误用会让整个路由器构造崩溃)。
        "extra": {"supports_tools": True},
    },
]


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
            if val and not str(val).lower().startswith(PLACEHOLDER_PREFIXES):
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
        # 这个约定)，短名查询保留作最后兜底(不改变既有行为)。同样要过滤占位符
        # (.env.example 里未编辑的模板值,如 "your_deepseek_api_key_here"),否则
        # 这条兜底路径会把模板文字当真密钥返回,provider 照样被注册、真实调用
        # 必然认证失败。
        val = os.environ.get(real_env_key, "")
        if val and not val.lower().startswith(PLACEHOLDER_PREFIXES):
            return val
        val = os.environ.get(key_name.upper() if "_" in key_name else key_name, "")
        if val and not val.lower().startswith(PLACEHOLDER_PREFIXES):
            return val
        return ""

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

    @staticmethod
    def _probe_openai_compatible(base_url: str) -> List[str]:
        """探 OpenAI 兼容服务是否在监听,并把它**实际托管**的模型 id 拿回来。

        探不到就返回空表 → 调用方不注册这个 provider。理由与 hf_local 那处同源:
        注册一个没人监听的端点，偏好列表命中它时拿到的是连接失败，而不是继续往
        下一个 provider 退 —— 静默变成"模型探测失败"，看不出根因是端点根本没起。

        顺带解决"模型 id 得手填"的问题:llama.cpp server 与 OpenVINO Model Server
        都实现了 ``GET /v1/models``,直接问它托管的是什么,比让用户抄一遍准。
        """
        try:
            import httpx

            r = httpx.get(f"{base_url}/models", timeout=2.0)
            if r.status_code != 200:
                return []
            data = r.json().get("data", [])
            return [str(m.get("id", "")).strip() for m in data if str(m.get("id", "")).strip()]
        except Exception as exc:  # noqa: BLE001
            logger.debug("本地 OpenAI 兼容服务探测失败(%s): %s", base_url, exc)
            return []

    def _register_local_openai(self) -> None:
        """注册「本地 OpenAI 兼容服务」——Intel 核显那一侧就走这条路接进来。

        为什么不写新后端:``VLLMBackend`` 名字叫 vllm,实质是**通用 OpenAI 兼容
        客户端**(只往 ``{base_url}/v1/chat/completions`` 发)。llama.cpp server 的
        SYCL / Vulkan 后端、OpenVINO Model Server 都讲同一套协议,起一个服务、
        把地址填进来即可,``BACKEND_REGISTRY`` 一个字不用加。

        (原打算走 IPEX-LLM,查下来那条路是死的:``intel/ipex-llm`` README 第一行
        是 THIS PROJECT IS ARCHIVED,并注明"已被识别为存在已知安全问题";社区 fork
        的验证模型列表停在 Qwen2.5 / MiniCPM-o-2.6,认不了新架构。)
        """
        raw = os.environ.get("GALAXY_LOCAL_OPENAI_URL", "").strip()
        if not raw:
            return
        base = raw.rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = f"http://{base}"
        if not base.endswith("/v1"):
            base = f"{base}/v1"

        served = self._probe_openai_compatible(base)
        if not served:
            logger.info("本地 OpenAI 兼容服务(%s)未响应 /models —— 不注册,偏好列表自然跳过它", base)
            return

        # 显式指定优先(用户可能在一个服务上托管多个模型);否则用它自报的第一个。
        want = os.environ.get("GALAXY_LOCAL_OPENAI_MODEL", "").strip()
        default_model = want if want in served else served[0]
        if want and want != default_model:
            logger.warning(
                "GALAXY_LOCAL_OPENAI_MODEL=%r 不在服务 %s 托管的模型里(%s),改用 %r",
                want,
                base,
                ", ".join(served),
                default_model,
            )

        cfg = ProviderConfig(
            name="local_openai",
            # 留空即"这台服务不开鉴权" —— 适配器据此不带 Authorization 头。
            # 早先这里塞过一个 "not-needed" 占位符,那是在绕开适配器的空值缺陷,
            # 而不是在描述事实;缺陷已在 OpenAIAdapter 里修掉,这里如实留空。
            api_key=os.environ.get("GALAXY_LOCAL_OPENAI_KEY", "").strip(),
            base_url=base,
            models=served,
            default_model=default_model,
            supports_tools=True,
            supports_json_mode=False,
            multimodal=True,
            env_key="GALAXY_LOCAL_OPENAI_URL",
            source_type="local",
            # 核显/量化档:比独显满血弱,但仍是本地,不该被当成远端。
            hardware_tier="gpu_quantized",
            supports_vision=True,
            supports_audio=True,
            quantization="q4",
        )
        self.providers["local_openai"] = cfg
        self.adapters["local_openai"] = OpenAIAdapter(cfg)
        logger.info("本地 OpenAI 兼容服务已注册: %s (%d 个模型, 默认 %s)", base, len(served), default_model)

    def _register_from_registry(self) -> None:
        """L1:从 PROVIDER_REGISTRY 循环注册标准 OpenAI/Anthropic 兼容提供商。

        等价于此前 15 段复制粘贴的发现逻辑,单一属主:
        - key 优先级:_get_key(短名) > env_key > alt_env 里的备用变量;
        - key 为空或以 "your-" 占位符开头则跳过该提供商;
        - base_url 允许被 base_key(Dashboard 短键)或 base_env(环境变量)覆盖,
          两者都空则用表里的默认 base_url;
        - 按 protocol 选适配器(openai/anthropic),extra 里的字段透传给 ProviderConfig。
        """
        for spec in PROVIDER_REGISTRY:
            name = spec["name"]
            key = self._get_key(name)
            if not key:
                for envk in [spec["env_key"], *spec.get("alt_env", [])]:
                    key = os.environ.get(envk, "")
                    if key:
                        break
            if not key or key.lower().startswith(PLACEHOLDER_PREFIXES):
                continue
            base = spec["base_url"]
            base_key = spec.get("base_key")
            base_env = spec.get("base_env")
            if base_key or base_env:
                override = self._get_key(base_key) if base_key else ""
                if not override and base_env:
                    override = os.environ.get(base_env, "")
                override = (override or "").strip()
                if override:
                    base = override
            cfg = ProviderConfig(
                name=name,
                api_key=key,
                base_url=base,
                models=list(spec["models"]),
                default_model=spec["default_model"],
                cost_per_1k_input=spec["cost_in"],
                cost_per_1k_output=spec["cost_out"],
                env_key=spec["env_key"],
                **spec.get("extra", {}),
            )
            self.providers[name] = cfg
            adapter_cls = _ADAPTER_BY_PROTOCOL.get(spec.get("protocol", "openai"), OpenAIAdapter)
            self.adapters[name] = adapter_cls(cfg)

    def _discover_providers(self):
        """从配置源自动发现并注册提供商（Dashboard > ENV > defaults）（PR86）"""

        # L1:标准 OpenAI/Anthropic 兼容提供商全部从 PROVIDER_REGISTRY 循环派生
        self._register_from_registry()

        # 本地 OpenAI 兼容服务(Intel 核显侧的 llama.cpp SYCL/Vulkan 或 OpenVINO
        # Model Server)。没配 GALAXY_LOCAL_OPENAI_URL 时整段是空转,不影响任何现状。
        self._register_local_openai()

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
        if ollama_url and not ollama_url.lower().startswith(PLACEHOLDER_PREFIXES):
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
                name="ollama",
                api_key="",
                base_url=ollama_url,
                models=detected_models,
                default_model=_default_model,
                supports_tools=True,
                supports_json_mode=True,
                multimodal=True,  # PR-HA: Ollama now marked multimodal-capable
                env_key="OLLAMA_URL",
                # PR-HA: 新增字段
                source_type="local",
                hardware_tier="gpu_full",
                supports_vision=True,  # llava / bakllava via Ollama
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
                ModelFamily,
                get_hf_model_manager,
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
                logger.info("HF 本地模型提供商已注册: %d 个模型", len(hf_model_ids))
            elif local_llm_models:
                logger.debug(
                    "跳过 hf_local 注册:内部适配服务(%s)未运行,避免偏好列表命中它时"
                    "连接失败(而非正常跳到下一个 provider)",
                    hf_base_url,
                )
        except Exception as exc:
            logger.debug("HF 本地模型提供商注册失败 (非致命): %s", exc)

        # OneAPI fallback
        oneapi_key = self._get_key("oneapi")
        if not oneapi_key:
            # 与 _get_key() 自身的环境变量兜底层(约 1734-1737 行)同一模式:直接
            # os.environ 兜底会绕开 _get_key() 内部已做的 PLACEHOLDER_PREFIXES 过滤,
            # 必须在这里重新过滤一遍,否则 .env.example 里的
            # "your_oneapi_api_key_here" 会被当成真实密钥注册 provider。
            raw = os.environ.get("ONEAPI_API_KEY", "")
            if raw and not raw.lower().startswith(PLACEHOLDER_PREFIXES):
                oneapi_key = raw
        oneapi_url = self._normalize_base_url(self._get_key("oneapi_url"))
        if not oneapi_url:
            oneapi_url = self._normalize_base_url(os.environ.get("ONEAPI_URL", ""))
        if oneapi_key and not oneapi_key.lower().startswith(PLACEHOLDER_PREFIXES) and oneapi_url:
            models = self._discover_oneapi_models(oneapi_url, oneapi_key)
            cfg = ProviderConfig(
                name="oneapi",
                api_key=oneapi_key,
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
            config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config", "api_config.json")
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
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
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
            "如果",
            "那么",
            "否则",
            "但是",
            "然而",
            "因为",
            "所以",
            "首先",
            "其次",
            "最后",
            "假设",
            "前提",
            "推导",
            "证明",
            "递归",
            "循环",
            "回溯",
            "遍历",
            "迭代",
            "条件",
            "判断",
            "分支",
            "嵌套",
            "复杂",
            "步骤",
            "流程",
            "逻辑",
            "if",
            "then",
            "else",
            "while",
            "for",
            "because",
            "therefore",
            "first",
            "second",
            "finally",
            "assume",
            "prove",
            "recursive",
            "algorithm",
            "iterate",
            "traverse",
            "backtrack",
        ]
        logic_hits = sum(1 for kw in logic_keywords if kw in text_lower)
        dim_logic = min(1.0, logic_hits / 6)

        # ── 维度 3: 领域专业度 (weight=0.20) ──
        domain_keywords = [
            # 代码 (含中文编程术语)
            "def ",
            "class ",
            "import ",
            "function",
            "async",
            "await",
            "return",
            "try:",
            "except",
            "raise",
            "lambda",
            "yield",
            "python",
            "java",
            "rust",
            "typescript",
            "javascript",
            "实现",
            "编程",
            "代码",
            "函数",
            "接口",
            "模块",
            "编译",
            "调试",
            "算法",
            "数据结构",
            "排序",
            "求解",
            "优化",
            "注解",
            "类型",
            "测试",
            "单元测试",
            "集成测试",
            # 数学
            "∑",
            "∫",
            "∂",
            "矩阵",
            "向量",
            "微分",
            "积分",
            "概率",
            "matrix",
            "vector",
            "derivative",
            "integral",
            "probability",
            # 专业
            "API",
            "SDK",
            "协议",
            "架构",
            "数据库",
            "索引",
            "并发",
            "事务",
            "database",
            "index",
            "concurrent",
            "transaction",
            "机器学习",
            "深度学习",
            "神经网络",
            "模型训练",
        ]
        domain_hits = sum(1 for kw in domain_keywords if kw in full_text.lower())
        dim_domain = min(1.0, domain_hits / 5)

        # ── 维度 4: 精度要求 (weight=0.20) ──
        precision_keywords = [
            "精确",
            "准确",
            "正确",
            "严格",
            "必须",
            "确保",
            "验证",
            "要求",
            "支持",
            "完整",
            "兼容",
            "标准",
            "规范",
            "exact",
            "precise",
            "correct",
            "strict",
            "must",
            "verify",
            "bug",
            "错误",
            "修复",
            "fix",
            "debug",
            "require",
        ]
        precision_hits = sum(1 for kw in precision_keywords if kw in text_lower)
        dim_precision = min(1.0, precision_hits / 4)

        # ── 维度 5: 工具需求 (weight=0.20) ──
        tool_keywords = [
            "文件",
            "目录",
            "搜索",
            "执行",
            "运行",
            "安装",
            "设备",
            "屏幕",
            "file",
            "directory",
            "search",
            "execute",
            "run",
            "install",
            "device",
            "screen",
            "打开",
            "关闭",
            "截图",
            "发送",
            "下载",
            "上传",
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
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
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
                # content 可能是 str,也可能是 OpenAI-vision 的分段 list
                # ([{type:text,...},{type:image_url,...}])——本 router 明确支持后者。
                # 直接 .lower() 会在 list 上 AttributeError,把整个 chat() 在路由前
                # 就打断(多模态 ambient 决策因此每次静默丢失画面输入)。先归一化。
                _content = m.get("content", "")
                if isinstance(_content, str):
                    last_user_msg = _content.lower()
                elif isinstance(_content, list):
                    last_user_msg = " ".join(
                        p.get("text", "") for p in _content if isinstance(p, dict) and p.get("type") == "text"
                    ).lower()
                break

        # 加权关键词 → 任务类型 (keyword, weight)
        weighted_patterns: Dict[TaskType, List[tuple]] = {
            TaskType.CODING: [
                ("代码", 2),
                ("编程", 2),
                ("函数", 2),
                ("类", 1),
                ("bug", 3),
                ("code", 3),
                ("implement", 3),
                ("debug", 3),
                ("function", 2),
                ("class", 1),
                ("api", 2),
                ("脚本", 2),
                ("script", 2),
            ],
            TaskType.REASONING: [
                ("为什么", 3),
                ("推理", 3),
                ("解释", 2),
                ("分析原因", 3),
                ("why", 3),
                ("reason", 3),
                ("explain", 2),
                ("思考", 2),
                ("逻辑", 3),
                ("论证", 2),
            ],
            TaskType.PLANNING: [
                ("计划", 3),
                ("规划", 3),
                ("步骤", 2),
                ("方案", 2),
                ("plan", 3),
                ("strategy", 3),
                ("分解", 2),
                ("目标", 1),
                ("路线图", 3),
                ("roadmap", 3),
            ],
            TaskType.CREATIVE: [
                ("创作", 3),
                ("写", 1),
                ("故事", 3),
                ("诗", 3),
                ("write", 1),
                ("create", 2),
                ("creative", 3),
                ("设计", 2),
                ("文章", 2),
                ("作文", 3),
            ],
            TaskType.ANALYSIS: [
                ("分析", 3),
                ("数据", 2),
                ("报告", 2),
                ("统计", 3),
                ("analyze", 3),
                ("data", 2),
                ("report", 2),
                ("评估", 2),
                ("比较", 2),
            ],
            TaskType.AGENT_CONTROL: [
                ("agent", 3),
                ("执行", 1),
                ("控制", 2),
                ("设备", 2),
                ("节点", 2),
                ("device", 3),
                ("node", 2),
                ("命令", 2),
                ("command", 2),
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

    def select_model_by_complexity(self, provider_name: str, task_type: TaskType, complexity: float) -> str:
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

    def route(
        self, task_type: TaskType, preferred_provider: Optional[str] = None, complexity_score: float = 0.5
    ) -> RoutingDecision:
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
                        provider="ollama",
                        model=model,
                        reason=f"本地主脑优先: Ollama 可用，任务类型 [{task_type.value}] 复杂度 {complexity_score:.2f}",
                        alternatives=[
                            f"{name}:{self.select_model_by_complexity(name, task_type, complexity_score)}"
                            for name in TASK_ROUTING_PREFERENCES.get(task_type, [])
                            if name in self.providers and name != "ollama" and self.providers[name].is_available()
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
                        provider="hf_local",
                        model=model,
                        reason=f"本地主脑优先: HuggingFace 本地模型 [{model}] 可用，"
                        f"任务类型 [{task_type.value}] 复杂度 {complexity_score:.2f}",
                        alternatives=[
                            f"{name}:{self.select_model_by_complexity(name, task_type, complexity_score)}"
                            for name in TASK_ROUTING_PREFERENCES.get(task_type, [])
                            if name in self.providers and name != "hf_local" and self.providers[name].is_available()
                        ],
                    )

        if preferred_provider and preferred_provider in self.providers:
            prov = self.providers[preferred_provider]
            if prov.is_available():
                model = self.select_model_by_complexity(preferred_provider, task_type, complexity_score)
                return RoutingDecision(
                    provider=preferred_provider,
                    model=model,
                    reason=f"用户指定提供商: {preferred_provider} (复杂度: {complexity_score:.2f})",
                )

        # 按任务偏好排序
        preferred_order = TASK_ROUTING_PREFERENCES.get(task_type, [])
        # 开源优先（默认开启）：把开源提供商整体提到专有之前，保持原相对顺序。
        # 本地 ollama/hf_local 本就在偏好表最前，因此本地优先不受影响。
        if os.environ.get("GALAXY_OPENSOURCE_FIRST", "true").lower() != "false":
            preferred_order = reorder_open_source_first(list(preferred_order))
        # L3 bandit:按历史表现(成功率/延迟/成本)自适应重排候选;样本不足自动退回
        # 原序(冷启动零行为变化),因此不影响本地/开源优先的既有精排。
        preferred_order = self._bandit_reorder(list(preferred_order), task_type)
        alternatives = []

        for provider_name in preferred_order:
            if provider_name not in self.providers:
                continue
            prov = self.providers[provider_name]
            if not prov.is_available():
                continue

            model = self.select_model_by_complexity(provider_name, task_type, complexity_score)
            if not alternatives:
                selected = RoutingDecision(
                    provider=provider_name,
                    model=model,
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
                    provider=name,
                    model=prov.default_model,
                    reason=f"Fallback: 唯一可用提供商 {name}",
                )

        # 无可用提供商 — 返回指向 none 的降级路由决策
        logger.error("没有可用的 LLM 提供商")
        return RoutingDecision(
            provider="none",
            model="none",
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
            name for name, cfg in self.providers.items() if cfg.is_available() and self.adapters.get(name) is not None
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
        max_cost = max((self.providers[n].cost_per_1k_output for n in candidates), default=0.0) or 1.0
        max_lat = max((self.providers[n].latency_avg_ms for n in candidates), default=0.0) or 1.0

        # 实测表现(L3 bandit 的历史统计)。此前这条打分【完全没接】bandit——它只吃
        # 手工维护的 PROVIDER_QUALITY_TIER,而 bandit 全仓只在 route() 里被调用一处。
        # 于是 agent 团队选脑(agent_team → select_brain_for_role → 本函数)走的这条路,
        # 拿不到任何真实成功率/延迟/成本反馈,全凭手写档位。所有者原话:「这玩意不应该
        # 交给智能路由自己选吗」——接上之后,手写档位退化为【冷启动先验】,有实测数据时
        # 由实测修正它。
        _bstats, _btotal = self._bandit_stats(task_type)
        try:
            observed_weight = float(_os.environ.get("GALAXY_ROUTE_OBSERVED_WEIGHT", "1.0"))
        except ValueError:
            observed_weight = 1.0

        def _score(name: str) -> float:
            cfg = self.providers[name]
            quality = _provider_quality_tier(name)  # 1..3(冷启动先验)
            # 任务相关度：在该任务偏好表里 = 更贴合
            task_fit = 1.0 if name in task_pref else 0.6
            # 主：质量 × (0.5+复杂度) —— 越难越看重质量
            score = quality * (0.5 + complexity_score) * task_fit
            # 次：适度 token（同档次便宜优先）
            score -= token_weight * (cfg.cost_per_1k_output / max_cost)
            # 条件：仅任务需要及时响应时计入延迟
            if needs_timely:
                score -= latency_weight * (cfg.latency_avg_ms / max_lat)
            # 实测修正:_bandit_score 的利用项是"成功率 − 延迟/成本/啰嗦惩罚",落在
            # [0,1]；以 0.5 为中线,好于中线加分、差于中线减分。
            # 没试过的 provider(+inf)【不参与】——这里与 route() 里的乐观初始化刻意不同:
            # route() 只有顺序这一个信号,把没试过的排前面才有机会被探索;而本函数已有
            # 静态档位当先验,再让 +inf 压过一切,等于让"从未试过"直接抢走一整个 agent
            # 的活,一次坏选择的代价远高于少探索一次。
            if _btotal:  # 0 = 样本不足(_bandit_stats 已判);此时完全按静态先验走
                b = self._bandit_score(name, _bstats, _btotal)
                if b != float("inf"):
                    score += observed_weight * (min(1.0, b) - 0.5)
            # 平局打破：开源/本地 + 显式本地偏好
            #
            # 按【模型】判开源,不按 provider 猜(见 core/model_openness.py)。原先这里
            # 是 `name in OPEN_SOURCE_PROVIDERS`,与 reorder_open_source_first() 对
            # "未登记"的处理正好相反(那边注释明写未知按开源处理、这边不给加分),同一个
            # provider 排序时算开源、打分时算非开源。改走同一个判定入口消除该矛盾;
            # 顺带修正 moonshot 这种一家兼有两种权重状态的:kimi-k2.* 是开放权重,
            # moonshot-v1-* 是闭源,而整家被登记成开源,后者一直在白拿这份加分。
            if _treat_as_open_source(
                name,
                self.select_model_by_complexity(name, task_type, complexity_score),
                open_source_providers=frozenset(OPEN_SOURCE_PROVIDERS),
                proprietary_providers=frozenset(PROPRIETARY_PROVIDERS),
            ):
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
            provider=best,
            model=model,
            reason=(
                f"fit-based: {best}:{model} quality={_provider_quality_tier(best)} "
                f"task={task_type.value} complexity={complexity_score:.2f} "
                f"mm={has_multimodal} timely={needs_timely}"
            ),
        )

    # ───────── 本地槽位解析（一个模型还是两个，上层写法一样） ─────────

    def _provider_serving(self, tag: str) -> Optional[Tuple[str, str]]:
        """哪个**本地** provider 托管着这个目录 tag,以及**该向它报哪个模型 id**。

        返回 ``(provider_name, model_id)``;没人托管返回 None。

        两个 id 常常不是一回事:目录里叫 ``openbmb/minicpm-o4.5``,而 OpenVINO
        Model Server 或 llama.cpp server 会按自己那套命名报(如
        ``MiniCPM-o-4_5-int4-ov``)。按目录 tag 去调它只会 404。所以匹配三级:

        1. 名字对得上(精确 / Ollama 的根名松匹配,与 ``_discover_providers`` 里
           主脑归并同一套口径);
        2. 用户**显式声明**了这台服务伺候的是哪个目录型号
           (``GALAXY_LOCAL_OPENAI_SERVES``)—— 只有起服务的人知道自己装的是什么,
           这里不猜;
        3. 都不满足 → None,交回原路径。

        按 ``source_type`` 找,不写死 provider 名单 —— Intel 侧那台 OpenAI 兼容
        服务(``local_openai``)是配出来的,写死名单它就永远进不来。
        """
        declared = os.environ.get("GALAXY_LOCAL_OPENAI_SERVES", "").strip()
        root = tag.split(":")[0]
        for name, cfg in self.providers.items():
            if cfg.source_type not in ("local", "hf_local"):
                continue
            if self.adapters.get(name) is None or not cfg.is_available():
                continue
            if tag == cfg.default_model or tag in cfg.models:
                return (name, tag)
            matched = next((m for m in cfg.models if m == tag or m.split(":")[0] == root), None)
            if matched:
                return (name, matched)
            if name == "local_openai" and declared and declared == tag and cfg.default_model:
                # 声明过:目录 tag 归本档,实际调用报服务自己那套 id。
                return (name, cfg.default_model)
        return None

    def _local_by_slot(self, slot_role: str, *, role: str, task: TaskType) -> Optional[RoutingDecision]:
        """按主脑名册的**槽位**取本地模型;取不到返回 None 交回原路径。

        为什么非要有这一步:原来本地这一支是 ``for local in ("ollama","hf_local")``
        取第一个可用的 provider,再由 ``select_model_by_complexity`` 对本地**一律
        早退回 default_model**。也就是说本地侧根本没有"哪个模型"这个概念 ——
        配了两个本地模型(感知位 + 推理位)时,两个角色会解析到同一个 default_model,
        ``ROLE_BRAIN_HINTS`` 里的角色区分在本地这边落不了地。

        云端那半边一个字不动:重角色(critic/reviewer/reasoner/coordinator/planner/
        analyst)是 ``prefer_local: False`` 的**常驻归属**,压根走不到这里。
        """
        try:
            from core.model_catalog import model_for_role  # noqa: PLC0415

            tag = model_for_role(slot_role)
        except Exception as exc:  # noqa: BLE001
            logger.debug("槽位解析不可用(回落原本地路径): %s", exc)
            return None
        if not tag:
            return None
        hosted = self._provider_serving(tag)
        if hosted is None:
            # 槽位指定的模型没有任何本地 provider 托管 —— 多半是那一位还没装/没起。
            # 这里**不**静默改派给另一个本地模型:那正是"选了两个模型却全落到一个
            # 上"的形状。交回原路径,由它按可用性决定。
            #
            # 但"交回原路径"本身必须**响亮**。真实路径实测:C 档下推理位没起时,
            # 这里返回 None,下游按可用性 fit-based 又把活派给了感知位 —— 结果和
            # 静默改派一模一样,而唯一的痕迹是一行 debug。用户看到的是"两个模型
            # 都配好了、系统也在跑",实际那一位从没上过岗。
            #
            # 每个 (槽位, tag) 只喊一次:这条路径每次路由都会走到,喊满屏等于没喊。
            warned = getattr(self, "_warned_unhosted_slots", None)
            if warned is None:
                warned = set()
                self._warned_unhosted_slots = warned
            if (slot_role, tag) not in warned:
                warned.add((slot_role, tag))
                logger.warning(
                    "本地[%s]槽位配的是 %s,但没有任何本地 provider 托管它 —— 这一位没上岗。"
                    "本次按可用性回落(很可能落到另一个本地模型上,失去两位分工的意义)。"
                    "检查:该模型是否已装/服务是否已起;若服务按自己那套命名报模型 id,"
                    "用 GALAXY_LOCAL_OPENAI_SERVES 声明它伺候的是哪个目录型号。",
                    slot_role,
                    tag,
                )
            return None
        provider, model_id = hosted
        return RoutingDecision(
            provider=provider,
            model=model_id,
            reason=f"角色[{role}] 轻角色→本地[{slot_role}]槽位: {provider}:{model_id} task={task.value}",
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
        hint = ROLE_BRAIN_HINTS.get(role, {"prefer_local": True, "task_type": TaskType.GENERAL, "min_complexity": 0.0})
        eff_task = task_type or hint["task_type"]
        # 重角色用 max(任务复杂度, 角色最低复杂度) 确保选到足够强的模型
        eff_complexity = max(complexity_score, hint.get("min_complexity", 0.0))

        # 大小模型配合：
        #   - 轻角色(executor/worker...) → 本地小模型【硬】优先（这是设计意图：本地做，
        #     云端审；不让云端强模型抢走 executor），无本地时才 fit-based。
        #   - 重角色(critic/reviewer...) → fit-based 质量优先。
        def _avail(name: str) -> bool:
            return (
                name in self.providers and self.providers[name].is_available() and self.adapters.get(name) is not None
            )

        if hint["prefer_local"]:
            # 先按**槽位**要人:agent 角色干的是文本/工具的活 → 推理位。
            # 单模型档时推理位就是那个唯一的模型,解析结果与下面的旧路径一致。
            slotted = self._local_by_slot(SLOT_REASONING, role=role, task=eff_task)
            if slotted is not None:
                return slotted
            for local in ("ollama", "hf_local"):
                if _avail(local):
                    model = self.select_model_by_complexity(local, eff_task, eff_complexity)
                    if local == "hf_local" and (not model or model not in self.providers[local].models):
                        model = self.providers[local].default_model or (
                            self.providers[local].models[0] if self.providers[local].models else model
                        )
                    return RoutingDecision(
                        provider=local,
                        model=model,
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

    async def route_local_brain_first(
        self, task_type: TaskType, messages: List[Dict], has_multimodal: bool = False
    ) -> RoutingDecision:
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
                    if name in self.providers and name != "ollama" and self.providers[name].is_available()
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
                    if name in self.providers and name != "hf_local" and self.providers[name].is_available()
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
        _local_present = any(p in self.providers and self.providers[p].is_available() for p in ("ollama", "hf_local"))
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
            if not prov.is_available():
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
            preferred_index: Dict[str, int] = {name: idx for idx, name in enumerate(preferred_order)}
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
            reason=("native_multimodal_first: tier=3 advisory " "no_providers_available degraded_to=no_op"),
        )

    # route_with_cost_policy() 已删除(约 110 行)。
    #
    # 依据:① 全仓零外部引用(无测试/文档/治理哨兵提及);② 它的成本策略已被
    # UnifiedLLMRouter + config/llm_routing_policy.yaml 真实承担 —— 那边按任务类型
    # 配 cost_budget.max_cost_per_1k_tokens,_check_cost_budget() 在
    # core/unified/llm_router.py:788 被真实调用,经 openclawd.py:1263 进入;
    # ③ 它的打分是 select_brain_for_task() 的较弱重复(没有质量档、没有实测表现、
    # 没有按模型判开闭源)。把它接上等于造出第二套互相竞争的成本策略 —— 正是本轮
    # 合并 7 份重复助手要消除的那类漂移。
    # 它独有的 llm_hint 护栏(LLM 建议只能在规则选定候选集内生效)在统一层已有等价
    # 实现(llm_router.py:257-261 只在已知优先级内重排)。
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

    # ─────────────────── L2 级联路由(FrugalGPT) ───────────────────
    @staticmethod
    def _default_answer_adequate(response: "LLMResponse", min_chars: int = 1) -> bool:
        """默认质量判据:答案非空、达到最小长度、不是明显的失败/拒答。级联路由用它
        判断"便宜模型这次答得够不够好、要不要升级到更贵的下一档"。"""
        try:
            text = (response.content or "").strip()
        except Exception:  # noqa: BLE001
            return False
        if len(text) < max(1, min_chars):
            return False
        low = text.lower()
        bad_markers = (
            "i cannot",
            "i can't help",
            "as an ai language model",
            "i'm unable to",
            "无法回答",
            "抱歉，我不能",
            "对不起，我无法",
            "error:",
            "internal server error",
            "rate limit",
        )
        if any(m in low for m in bad_markers):
            return False
        return True

    @staticmethod
    def _capability_floor_for_complexity(complexity: float) -> int:
        """把任务复杂度(0..1)映射到【最低能力档】。要点:难任务直接从强档起步,不在注定
        答不好的便宜档上白白试错一轮——这正是"按任务实际情况来"而非一律盲目从最便宜档试。
          complexity ≥ 0.70 → 档 3(前沿/强开源)
          complexity ≥ 0.35 → 档 2(强)
          否则              → 档 1(本地轻量也够)
        可用 GALAXY_CASCADE_FLOOR_HI / _MID 覆写阈值。"""
        try:
            hi = float(os.environ.get("GALAXY_CASCADE_FLOOR_HI", "0.70") or "0.70")
            mid = float(os.environ.get("GALAXY_CASCADE_FLOOR_MID", "0.35") or "0.35")
        except ValueError:
            hi, mid = 0.70, 0.35
        if complexity >= hi:
            return 3
        if complexity >= mid:
            return 2
        return 1

    def _cost_ordered_ladder(
        self, task_type: TaskType, max_stages: int = 3, require_multimodal: bool = False, min_tier: int = 1
    ) -> List[Tuple[str, str]]:
        """构造【便宜→贵】的候选梯队 [(provider, model), ...]:先按能力档下限 min_tier 过滤
        (任务难就不带本地轻量档,避免注定失败的一轮),再在合格集合里按 cost_per_1k_output
        升序(便宜的强开源如 deepseek 天然靠前 → 既够强又省钱),require_multimodal 时只保留
        多模态提供商,每档用它对该任务的推荐模型(无则 default),最多 max_stages 档。

        兜底:若没有任何提供商达到 min_tier(例如只配了本地模型),降级忽略下限用全量可用集合
        ——宁可用弱档兜底,也不空手而归。"""

        def _pool(floor: int) -> List["ProviderConfig"]:
            return [
                cfg
                for name, cfg in self.providers.items()
                if name in self.adapters
                and cfg.is_available()
                and (not require_multimodal or cfg.multimodal)
                and _provider_quality_tier(name) >= floor
            ]

        avail = _pool(min_tier)
        if not avail and min_tier > 1:
            avail = _pool(1)  # 达不到能力下限 → 降级兜底,不返回空
            if avail:
                logger.info("级联路由:无提供商达能力档 %d,降级用全量可用集合兜底", min_tier)
        avail.sort(key=lambda c: (c.cost_per_1k_output, c.cost_per_1k_input))
        ladder: List[Tuple[str, str]] = []
        for cfg in avail[: max(1, max_stages)]:
            model = PROVIDER_MODEL_MAP.get(cfg.name, {}).get(task_type) or cfg.default_model
            ladder.append((cfg.name, model))
        return ladder

    async def chat_cascade(
        self,
        messages: List[Dict],
        task_type: TaskType = TaskType.GENERAL,
        *,
        judge: Optional[Callable[["LLMResponse"], bool]] = None,
        max_stages: int = 3,
        min_chars: int = 1,
        complexity: Optional[float] = None,
        require_multimodal: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[List[Dict]] = None,
        **kwargs,
    ) -> Optional["LLMResponse"]:
        """L2 级联路由(任务感知的 FrugalGPT):按任务【实际复杂度】定起步档,再便宜→贵升级。

        改造要点(不再一律从最便宜档盲试):先估任务复杂度(complexity 不给则从 messages 估),
        映射出【最低能力档】——难任务直接从强档起步,跳过注定答不好的便宜档,省掉白试的一轮;
        简单任务仍从最便宜档起。合格判据的最小长度也随复杂度自适应收紧(难任务不接受一句话敷衍)。

        judge(response)->bool:自定义质量判据;缺省用 _default_answer_adequate。返回第一个
        合格答案(带 cascade_stage/cascade_escalated 元数据);全档都不合格则返回最后(最强)
        那档的答案;完全无可用提供商返回 None。每次调用都记进 call_history 供 L3 反哺。
        """
        if complexity is None:
            try:
                complexity = float(self._compute_complexity_score(messages, tools))
            except Exception:  # noqa: BLE001
                complexity = 0.5
        complexity = min(1.0, max(0.0, complexity))
        floor = self._capability_floor_for_complexity(complexity)
        ladder = self._cost_ordered_ladder(
            task_type,
            max_stages,
            require_multimodal,
            min_tier=floor,
        )
        if not ladder:
            logger.warning("级联路由:无可用提供商")
            return None
        # 合格门槛随复杂度自适应:难任务不接受一句话敷衍(最多抬到 ~24 字)。
        eff_min_chars = max(min_chars, int(round(complexity * 24)))
        logger.info(
            "级联路由:复杂度 %.2f → 能力档下限 %d,起步梯队 %s(min_chars=%d)",
            complexity,
            floor,
            [p for p, _ in ladder],
            eff_min_chars,
        )
        verdict = judge or (lambda r: self._default_answer_adequate(r, eff_min_chars))
        # 真流式:级联升级会作废上一档已流出的草稿(消费端清屏/掐断朗读重来)。
        _sink = kwargs.get("stream")
        last: Optional[LLMResponse] = None
        for stage, (provider, model) in enumerate(ladder):
            adapter = self.adapters.get(provider)
            if adapter is None:
                continue
            if _sink is not None and _sink.chars:
                _sink.reset()  # 上一档流出过内容 → 换档前作废
            try:
                resp = await adapter.chat(
                    messages,
                    model,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
            except Exception as exc:  # noqa: BLE001
                logger.info("级联第 %d 档 %s:%s 调用失败,升级: %s", stage, provider, model, exc)
                self._record_call(provider, model, task_type, None, success=False)
                continue
            self._record_call(provider, model, task_type, resp, success=True)
            last = resp
            try:
                ok = bool(verdict(resp))
            except Exception:  # noqa: BLE001
                ok = True  # 判据自身出错不阻塞,视为合格
            if ok:
                resp.cascade_stage = stage
                resp.cascade_escalated = stage > 0
                self._last_provider = provider
                logger.info(
                    "级联路由:第 %d 档 %s:%s 合格返回 %s",
                    stage,
                    provider,
                    model,
                    "(便宜档一次命中)" if stage == 0 else "(升级后命中)",
                )
                return resp
            logger.info("级联第 %d 档 %s:%s 答案不合格,升级", stage, provider, model)
        if last is not None:
            last.cascade_stage = len(ladder) - 1
            last.cascade_escalated = len(ladder) > 1
        return last

    def _record_call(
        self, provider: str, model: str, task_type: TaskType, response: Optional["LLMResponse"], success: bool
    ) -> None:
        """统一记 call_history(供 L3 bandit 反哺决策),字段与既有 chat() 记录对齐,并补
        cost(成本感知排序用)。全程 try/except,绝不阻塞主流程。"""
        try:
            cfg = self.providers.get(provider)
            itok = int(getattr(response, "input_tokens", 0) or 0)
            otok = int(getattr(response, "output_tokens", 0) or 0)
            cost = 0.0
            if cfg:
                cost = (itok / 1000.0) * cfg.cost_per_1k_input + (otok / 1000.0) * cfg.cost_per_1k_output
            self.call_history.append(
                {
                    "provider": provider,
                    "model": model,
                    "task_type": task_type.value if hasattr(task_type, "value") else str(task_type),
                    "latency_ms": float(getattr(response, "latency_ms", 0.0) or 0.0),
                    "tokens": itok + otok,
                    "tokens_out": otok,
                    "cost": round(cost, 6),
                    "timestamp": time.time(),
                    "success": bool(success),
                }
            )
            if len(self.call_history) > 500:
                self.call_history = self.call_history[-500:]
            if cfg:
                if success:
                    cfg.success_count += 1
                    cfg.last_used = time.time()
                else:
                    cfg.error_count += 1
            # 任务成本账本:所有 LLM 调用都经此漏斗,顺手记进当前任务账单
            # (无在途账单时静默无操作;账本故障绝不反噬)。
            try:
                from core.task_cost_ledger import add_llm_usage

                add_llm_usage(provider, itok, otok, cost)
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            pass

    # ─────────────────── L3 bandit 自适应排序 ───────────────────
    def _provider_stats(self, task_type: Optional[TaskType] = None) -> Dict[str, Dict[str, float]]:
        """从 call_history 聚合每个 provider 的表现:
        {provider: {calls, successes, latency_sum, cost_sum}}。task_type 给定时只统计
        该任务的调用(粒度更贴切);None 则统计全量历史(任务级样本不足时的兜底)。"""
        tt = task_type.value if hasattr(task_type, "value") else task_type
        stats: Dict[str, Dict[str, float]] = {}
        for rec in getattr(self, "call_history", None) or []:
            if tt is not None and rec.get("task_type") != tt:
                continue
            p = rec.get("provider")
            if not p:
                continue
            s = stats.setdefault(
                p, {"calls": 0.0, "successes": 0.0, "latency_sum": 0.0, "cost_sum": 0.0, "tokens_out_sum": 0.0}
            )
            s["calls"] += 1
            if rec.get("success"):
                s["successes"] += 1
            s["latency_sum"] += float(rec.get("latency_ms", 0.0) or 0.0)
            s["cost_sum"] += float(rec.get("cost", 0.0) or 0.0)
            s["tokens_out_sum"] += float(rec.get("tokens_out", 0.0) or 0.0)
        return stats

    def _bandit_score(
        self,
        name: str,
        stats: Dict[str, Dict[str, float]],
        total: int,
        *,
        latency_weight: float = 0.2,
        cost_weight: float = 0.1,
        verbosity_weight: float = 0.1,
        explore_c: float = 1.4,
    ) -> float:
        """UCB1 式打分:利用项(成功率 − 延迟/成本/啰嗦惩罚)＋ 探索项。未试过的 provider
        返回 +inf(乐观初始化,保证每个都至少被探索一次)。惩罚做相对归一化,避免任何
        单项的绝对量级压过成功率主信号。

        啰嗦惩罚(token 效率,Grok 4.5 的核心洞见):同样把事办成,平均输出 token
        越多的 provider 越吃亏——本地 CPU 上输出 token ≈ 等待秒数,云端 ≈ 账单。
        北极星是"任务总消耗",不是单次速度。"""
        s = stats.get(name)
        if not s or s["calls"] == 0:
            return float("inf")
        n = s["calls"]
        success_rate = s["successes"] / n
        avg_latency = s["latency_sum"] / n
        avg_cost = s["cost_sum"] / n
        avg_tokens_out = s.get("tokens_out_sum", 0.0) / n
        lat_pen = latency_weight * min(1.0, avg_latency / 5000.0)  # 5s 封顶
        cost_pen = cost_weight * min(1.0, avg_cost / 0.05)  # 0.05/次 封顶
        verb_pen = verbosity_weight * min(1.0, avg_tokens_out / 2000.0)  # 2k tok/次 封顶
        exploit = max(0.0, success_rate - lat_pen - cost_pen - verb_pen)
        explore = explore_c * math.sqrt(math.log(max(total, 1) + 1.0) / n)
        return exploit + explore

    BANDIT_MIN_SAMPLES: int = 5

    def _bandit_stats(
        self, task_type: Optional[TaskType] = None, *, min_samples: Optional[int] = None
    ) -> Tuple[Dict[str, Dict[str, float]], int]:
        """取 bandit 统计,带两级样本回退:任务级不足 → 退全量历史;全量也不足 → 返回空。

        这段回退逻辑原本只长在 ``_bandit_reorder`` 里。``select_brain_for_task`` 接实测
        表现时我把它**抄了一遍**,还把 5 写成了字面量,而这边是 ``min_samples`` 参数 ——
        两处一旦不同步就会出现"重排认为样本够、打分认为不够"的分裂。提成一个方法,
        阈值收敛到 ``BANDIT_MIN_SAMPLES`` 一处。

        Returns:
            ``(stats, total)``;``total == 0`` 表示样本不足,调用方应退回各自的静态行为。
        """
        floor = self.BANDIT_MIN_SAMPLES if min_samples is None else min_samples
        stats = self._provider_stats(task_type)
        total = int(sum(s["calls"] for s in stats.values()))
        if total < floor:
            stats = self._provider_stats(None)
            total = int(sum(s["calls"] for s in stats.values()))
            if total < floor:
                return {}, 0
        return stats, total

    def _bandit_reorder(
        self, candidates: List[str], task_type: Optional[TaskType] = None, *, min_samples: Optional[int] = None
    ) -> List[str]:
        """按 UCB1 打分对候选 provider 列表做自适应重排(表现好的上浮,同时保留探索)。
        冷启动零回归:GALAXY_BANDIT_ROUTING=false 关闭;任务级样本不足退回全量历史,
        全量也不足(< min_samples)则原样返回。稳定排序,同分保持传入顺序。"""
        if not candidates or os.environ.get("GALAXY_BANDIT_ROUTING", "true").lower() == "false":
            return candidates
        stats, total = self._bandit_stats(task_type, min_samples=min_samples)
        if not total:
            return list(candidates)
        scored = [self._bandit_score(n, stats, total) for n in candidates]
        # sorted 稳定:同分保持原相对顺序;-score 让高分(含 +inf 未试过)排前。
        order = sorted(range(len(candidates)), key=lambda i: -scored[i])
        return [candidates[i] for i in order]

    def routing_stats(self, task_type: Optional[TaskType] = None) -> List[Dict[str, Any]]:
        """可观测:导出每个 provider 的聚合表现 + 当前 bandit 分(供面板/诊断查看
        "反哺决策"的实际依据)。按 bandit 分降序。"""
        stats = self._provider_stats(task_type)
        total = int(sum(s["calls"] for s in stats.values()))
        out: List[Dict[str, Any]] = []
        for name, s in stats.items():
            n = s["calls"] or 1
            out.append(
                {
                    "provider": name,
                    "calls": int(s["calls"]),
                    "success_rate": round(s["successes"] / n, 4),
                    "avg_latency_ms": round(s["latency_sum"] / n, 1),
                    "avg_cost": round(s["cost_sum"] / n, 6),
                    "bandit_score": self._bandit_score(name, stats, total),
                }
            )
        out.sort(key=lambda d: -d["bandit_score"])
        # +inf 不便于 JSON 序列化,导出前替换为 None 标记"未试过/待探索"。
        for d in out:
            if d["bandit_score"] == float("inf"):
                d["bandit_score"] = None
        return out

    # ─────────────────── L4 模型名单自动同步(/models 端点对账) ───────────────────
    @staticmethod
    def _model_matches(configured: str, live_ids: "set") -> bool:
        """配置里的模型名是否仍能对应到端点实际返回的某个 id。做带边界的前缀匹配,
        以吃下版本后缀(gpt-5.6 ↔ gpt-5.6-2026-01)和 ollama 的 tag(gemma4:e2b ↔
        gemma4:e2b:latest / 同 root),但不至于 gpt-4 误配 gpt-4o。"""
        c = (configured or "").strip()
        if not c:
            return False
        if c in live_ids:
            return True
        croot = c.split(":")[0]
        for lid in live_ids:
            if lid == c or lid.startswith(c + "-") or c.startswith(lid + "-"):
                return True
            if lid.startswith(c + ":") or lid.split(":")[0] == croot:
                return True
        return False

    async def _fetch_live_models(self, name: str) -> Optional[List[str]]:
        """查询单个 provider 的模型名单端点(协议感知:ollama→/api/tags,
        anthropic→/models(x-api-key),其余 OpenAI 兼容→/models(Bearer))。
        返回实际可用的 id 列表;不可达/异常返回 None(与"端点返回空列表"区分开)。"""
        cfg = self.providers.get(name)
        adapter = self.adapters.get(name)
        if cfg is None or adapter is None or not cfg.base_url:
            return None
        base = cfg.base_url.rstrip("/")
        if isinstance(adapter, OllamaAdapter):
            url, headers = f"{base}/api/tags", {}
        elif isinstance(adapter, AnthropicAdapter):
            url = f"{base}/models"
            headers = {"x-api-key": cfg.api_key, "anthropic-version": "2023-06-01"}
        else:
            url = f"{base}/models"
            headers = {"Authorization": f"Bearer {cfg.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=min(cfg.timeout or 10.0, 10.0)) as client:
                r = await client.get(url, headers=headers)
            if r.status_code != 200:
                logger.debug("模型名单同步:%s HTTP %s", name, r.status_code)
                return None
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            logger.debug("模型名单同步:%s 查询失败: %s", name, exc)
            return None
        return self._parse_model_list(data)

    @staticmethod
    def _parse_model_list(data: Any) -> List[str]:
        """把不同端点形状统一解析成 id 列表:ollama {models:[{name}]}、
        OpenAI {data:[{id}]}、Anthropic {data:[{id}]}、或裸列表。"""
        ids: List[str] = []
        if isinstance(data, dict) and "models" in data:  # ollama /api/tags
            for m in data.get("models") or []:
                mid = (m.get("name") if isinstance(m, dict) else "") or ""
                if mid:
                    ids.append(mid)
            return ids
        items = data.get("data", data) if isinstance(data, dict) else data
        for it in items or []:
            if isinstance(it, dict):
                mid = it.get("id") or it.get("name") or ""
            elif isinstance(it, str):
                mid = it
            else:
                mid = ""
            if mid:
                ids.append(mid)
        return ids

    def _reconcile_one(self, name: str, live: List[str], *, apply: bool, max_add: int) -> Dict[str, Any]:
        """把单个 provider 的 cfg.models 与实际 live 名单对账。返回诊断报告;
        apply=True 时就地修正 cfg(剪掉失效项、补进新发现项、必要时改 default_model)。
        剪枝绝不把名单清空(端点抽风也不至于让 provider 失去所有模型)。"""
        cfg = self.providers[name]
        live_set = set(live)
        configured = list(cfg.models)
        valid = [m for m in configured if self._model_matches(m, live_set)]
        stale = [m for m in configured if m not in valid]
        # 新发现:live 里、当前配置尚未覆盖到的 id
        newly = [lid for lid in live if not any(self._model_matches(m, {lid}) for m in configured)]
        report = {
            "provider": name,
            "live_count": len(live),
            "configured": configured,
            "valid": valid,
            "stale": stale,
            "newly_available": newly[:max_add],
            "applied": False,
        }
        if not apply:
            return report
        new_models = valid + [m for m in newly[:max_add] if m not in valid]
        if not new_models:
            # 端点没给出任何能对应上的模型(可能鉴权失败/形状异常)→ 保守不动
            report["applied"] = False
            return report
        cfg.models = new_models
        if cfg.default_model not in new_models:
            cfg.default_model = new_models[0]
            report["default_model_repaired"] = cfg.default_model
        report["applied"] = True
        return report

    async def sync_model_lists(
        self, *, apply: bool = False, only: Optional[List[str]] = None, max_add: int = 20
    ) -> Dict[str, Any]:
        """L4 模型名单自动同步:对每个可用 provider 查询其 /models 端点,与硬编码的
        ProviderConfig.models 对账。apply=False(默认)只出对账报告;apply=True 就地
        剪掉失效模型、补进新发现模型、修复失效的 default_model。不可达的 provider
        跳过(不误删其配置名单)。并发查询,整体不阻塞。"""
        names = [
            n for n in (only or list(self.providers.keys())) if n in self.providers and self.providers[n].is_available()
        ]
        results = await asyncio.gather(*(self._fetch_live_models(n) for n in names), return_exceptions=True)
        reports: List[Dict[str, Any]] = []
        unreachable: List[str] = []
        for n, live in zip(names, results):
            if isinstance(live, Exception) or live is None:
                unreachable.append(n)
                continue
            reports.append(self._reconcile_one(n, live, apply=apply, max_add=max_add))
        return {
            "applied": apply,
            "checked": len(names),
            "reconciled": reports,
            "unreachable": unreachable,
        }

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

        # 真流式:failover 换 provider 前作废已流出的半截内容(消费端清屏重来)。
        _sink = kwargs.get("stream")

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
                    messages=messages,
                    model=mdl,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    **kwargs,
                )

                # 更新状态 + 断路器
                self.providers[prov_name].success_count += 1
                self.providers[prov_name].last_used = time.time()
                self.providers[prov_name].latency_avg_ms = (
                    self.providers[prov_name].latency_avg_ms * 0.8 + response.latency_ms * 0.2
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
                        tried_providers[:-1],
                        prov_name,
                        mdl,
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
                self.call_history.append(
                    {
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
                    }
                )
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
                if _sink is not None and _sink.chars:
                    try:
                        _sink.reset()  # 半截草稿作废,下一个候选重新流
                    except Exception:  # noqa: BLE001
                        pass
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

                self.call_history.append(
                    {
                        "provider": prov_name,
                        "model": mdl,
                        "task_type": classified.value,
                        "timestamp": time.time(),
                        "success": False,
                        "error": str(e),
                    }
                )

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

    async def chat_json(self, messages: List[Dict], schema_hint: str = "", **kwargs) -> Dict:
        """调用 LLM 并解析 JSON 响应"""
        if schema_hint:
            messages = list(messages)
            messages.append(
                {
                    "role": "user",
                    "content": f"请以 JSON 格式返回结果。结构: {schema_hint}",
                }
            )

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
            "healthy_providers": sum(1 for p in self.providers.values() if p.status == ProviderStatus.HEALTHY),
            "providers": providers_status,
            "total_calls": len(self.call_history),
            "recent_calls": recent,
        }

    async def health_check(self) -> Dict[str, str]:
        """对所有提供商做健康检查"""
        results = {}
        for name, adapter in list(self.adapters.items()):
            try:
                await adapter.chat(
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
            result.append(
                {
                    "provider": name,
                    "model": prov.default_model,
                    "models": prov.models,
                    "source": "env/vault",
                    "active": prov.is_available(),
                    "available": prov.is_available(),
                    "supports_tools": prov.supports_tools,
                    "multimodal": prov.multimodal,
                    "env_key": prov.env_key,
                }
            )
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
            **{
                k: v
                for k, v in kwargs.items()
                if k
                in (
                    "temperature",
                    "max_tokens",
                    "response_format",
                    "auto_failover",
                    "provider",
                    "tool_choice",
                )
            },
        )

        # 如果 raw_response 存在且有标准 OpenAI 格式，直接用它
        if resp.raw_response and "choices" in resp.raw_response:
            return _OpenAICompatResponse(resp.raw_response, resp.model)

        # 否则手动构建 OpenAI 兼容结构
        message_dict = {"role": "assistant", "content": resp.content}
        if resp.tool_calls:
            message_dict["tool_calls"] = resp.tool_calls

        return _OpenAICompatResponse(
            {
                "choices": [{"message": message_dict, "finish_reason": "stop"}],
                "model": resp.model,
                "usage": {
                    "prompt_tokens": resp.input_tokens,
                    "completion_tokens": resp.output_tokens,
                },
            },
            resp.model,
        )

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
        for adapter in list(self.adapters.values()):
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
        for adapter in list(self.adapters.values()):
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


# ── 后台刷新调度(保存配置路由的快速返回依赖此处)──────────────────────────
# 根因(Windows 真机日志实证):POST /api/config 此前同步 await refresh_llm_router()
# ——内部对 Ollama/OneAPI 等做 2~5s/个的真实网络探测,离线机器上整个刷新轻松
# 超过 8s。而 Electron 主进程 fetchWithRetry 的单次尝试硬上限恰是 8s(abort 后
# 2.5s 重试、60s 总预算)——于是保存请求永远在"后端还没答完就被掐断重发"里
# 打转:面板卡在「保存中…/仍在保存中」直至 60s 预算耗尽报错;每次 abort 都留下
# 一个已断开的连接,后端稍后写响应体就炸出 "Cannot call write() when UVStream
# is closing"(与断开写错误连锁,时间线完全吻合)。
# 修复:保存路由只【调度】刷新立即返回;需要刷新结果的端点(verify-provider)
# 用 wait_llm_router_refresh() 有界等待,两边都不会无限悬挂。
_refresh_task: Optional["asyncio.Task"] = None


def schedule_llm_router_refresh() -> "asyncio.Task":
    """在后台调度一次路由器热刷新(去重:已有进行中的任务则直接复用)。"""
    global _refresh_task
    if _refresh_task is not None and not _refresh_task.done():
        return _refresh_task

    async def _run():
        try:
            return await refresh_llm_router()
        except Exception as exc:  # noqa: BLE001 — 后台任务,异常只记日志不上抛
            logger.warning("LLM 路由后台刷新失败(下次保存/探测会重试): %s", exc)
            return None

    _refresh_task = asyncio.get_running_loop().create_task(_run())
    return _refresh_task


async def wait_llm_router_refresh(timeout: float = 8.0) -> bool:
    """有界等待进行中的后台刷新完成;无进行中任务视为已完成。

    返回 True=刷新已完成(或本就没有待完成的刷新);False=超时仍未完成
    (shield 保护任务本体继续在后台跑完,不因等待方超时而被取消)。
    """
    task = _refresh_task
    if task is None or task.done():
        return True
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
        return True
    except asyncio.TimeoutError:
        return False
