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
    # 运行时状态
    status: ProviderStatus = ProviderStatus.HEALTHY
    latency_avg_ms: float = 0.0
    error_count: int = 0
    success_count: int = 0
    last_error: Optional[str] = None
    last_used: float = 0.0


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

# 任务类型 → 提供商优先级
# Ollama is placed at the end of GENERAL preferences as a local-last fallback.
# Remote API providers are preferred for higher-quality results.
TASK_ROUTING_PREFERENCES: Dict[TaskType, List[str]] = {
    TaskType.REASONING:      ["anthropic", "openai", "google", "deepseek", "xai"],
    TaskType.FAST_RESPONSE:  ["deepseek", "groq", "google", "openai", "moonshot"],
    TaskType.CODING:         ["deepseek", "qwen", "anthropic", "openai"],
    TaskType.CREATIVE:       ["openai", "anthropic", "mistral", "deepseek"],
    TaskType.ANALYSIS:       ["anthropic", "openai", "google", "perplexity", "deepseek"],
    TaskType.PLANNING:       ["anthropic", "openai", "xai", "deepseek"],
    TaskType.AGENT_CONTROL:  ["anthropic", "openai", "deepseek"],
    TaskType.GENERAL:        ["openai", "anthropic", "deepseek", "google", "ollama"],
}

# 提供商 → 推荐模型
PROVIDER_MODEL_MAP: Dict[str, Dict[TaskType, str]] = {
    "openai": {
        TaskType.REASONING:     "gpt-5.4-thinking",
        TaskType.FAST_RESPONSE: "gpt-4o-mini",
        TaskType.CODING:        "gpt-5.4",
        TaskType.CREATIVE:      "gpt-5.4",
        TaskType.ANALYSIS:      "gpt-5.4",
        TaskType.PLANNING:      "gpt-5.4-thinking",
        TaskType.AGENT_CONTROL: "gpt-5.4",
        TaskType.GENERAL:       "gpt-5.4",
    },
    "anthropic": {
        TaskType.REASONING:     "claude-opus-4.6",
        TaskType.FAST_RESPONSE: "claude-sonnet-4.6",
        TaskType.CODING:        "claude-sonnet-4.6",
        TaskType.CREATIVE:      "claude-opus-4.6",
        TaskType.ANALYSIS:      "claude-opus-4.6",
        TaskType.PLANNING:      "claude-opus-4.6",
        TaskType.AGENT_CONTROL: "claude-sonnet-4.6",
        TaskType.GENERAL:       "claude-sonnet-4.6",
    },
    "google": {
        TaskType.REASONING:     "gemini-3.1-deep-think",
        TaskType.FAST_RESPONSE: "gemini-3.1-flash",
        TaskType.CODING:        "gemini-3.1-pro",
        TaskType.CREATIVE:      "gemini-3.1-pro",
        TaskType.ANALYSIS:      "gemini-3.1-deep-think",
        TaskType.PLANNING:      "gemini-3.1-deep-think",
        TaskType.AGENT_CONTROL: "gemini-3.1-pro",
        TaskType.GENERAL:       "gemini-3.1-flash",
    },
    "xai": {
        TaskType.REASONING:     "grok-4.20",
        TaskType.FAST_RESPONSE: "grok-4.20",
        TaskType.CODING:        "grok-4.20",
        TaskType.CREATIVE:      "grok-4.20",
        TaskType.ANALYSIS:      "grok-4.20",
        TaskType.PLANNING:      "grok-4.20",
        TaskType.AGENT_CONTROL: "grok-4.20",
        TaskType.GENERAL:       "grok-4.20",
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
        TaskType.REASONING:     "deepseek-ai/DeepSeek-V3.2",
        TaskType.FAST_RESPONSE: "deepseek-ai/DeepSeek-V3.2",
        TaskType.CODING:        "deepseek-ai/DeepSeek-V3.2",
        TaskType.CREATIVE:      "deepseek-ai/DeepSeek-V3.2",
        TaskType.ANALYSIS:      "deepseek-ai/DeepSeek-V3.2",
        TaskType.PLANNING:      "deepseek-ai/DeepSeek-V3.2",
        TaskType.AGENT_CONTROL: "deepseek-ai/DeepSeek-V3.2",
        TaskType.GENERAL:       "deepseek-ai/DeepSeek-V3.2",
    },
    "qwen": {
        TaskType.CODING:        "Qwen/Qwen3.5-397B-A17B-Coder",
        TaskType.FAST_RESPONSE: "Qwen/Qwen3.5-397B-A17B",
        TaskType.GENERAL:       "Qwen/Qwen3.5-397B-A17B",
        TaskType.ANALYSIS:      "Qwen/Qwen3.5-397B-A17B",
    },
    "zhipu": {
        TaskType.GENERAL:       "glm-4.6",
        TaskType.ANALYSIS:      "glm-4.6",
        TaskType.CODING:        "glm-4.6",
        TaskType.FAST_RESPONSE: "glm-4-flash",
    },
    "moonshot": {
        TaskType.GENERAL:       "moonshot-v1-128k",
        TaskType.ANALYSIS:      "moonshot-v1-256k",
        TaskType.FAST_RESPONSE: "moonshot-v1-32k",
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
        TaskType.GENERAL: "llama3",
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

    async def chat(self, messages, model, tools=None,
                   temperature=0.7, max_tokens=4096,
                   response_format=None, **kwargs) -> LLMResponse:
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        t0 = time.monotonic()
        resp = await self._post_with_retry(
            f"{self.config.base_url}/api/chat",
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
    "moonshot":   MoonshotAdapter,
    "perplexity": PerplexityAdapter,
    "groq":       GroqAdapter,
    "ollama":     OllamaAdapter,
}


# PR-515 / GAP-512-009: MultiLLMRouter is the routing authority for
# multi-model provider and model selection.  CriticalPathHarness (Layer 15)
# records routing decisions so they are canonical-runtime-inspectable.
CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED: str = (
    "MULTI_LLM_ROUTER::CRITICAL_PATH_ROUTING_AUTHORITY_INTEGRATED_V1: "
    "core/multi_llm_router.py is the canonical routing authority for "
    "multi-model provider selection.  PR-515 CriticalPathHarness records "
    "routing decisions at the OpenClawd integration point so they are "
    "operator-inspectable without competing with MultiLLMRouter authority. "
    "Closes GAP-512-009."
)


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
        """配置优先级: Dashboard > CredentialVault > ENV（PR86）"""
        # 1. Dashboard 配置（最高优先级）— 通过 UnifiedConfig 获取
        try:
            from core.unified_config import config as _cfg
            # Dashboard 将 API keys 存储在 llm.providers.<name>.api_key 路径
            val = _cfg.get(f"llm.providers.{key_name}.api_key", "")
            if not val:
                val = _cfg.get(f"api_keys.{key_name}", "")
            if val and not str(val).startswith("your-"):
                return str(val)
        except Exception:
            pass
        # 2. CredentialVault
        try:
            from core.credential_vault import get_vault
            val = get_vault().get_credential(key_name, actor="llm_router")
            if val:
                return val
        except Exception:
            pass
        # 3. 环境变量（兜底）
        return os.environ.get(key_name.upper() if "_" in key_name else key_name, "")

    def _discover_providers(self):
        """从配置源自动发现并注册提供商（Dashboard > ENV > defaults）（PR86）"""

        # OpenAI
        key = self._get_key("openai")
        if not key:
            key = os.environ.get("OPENAI_API_KEY", "")
        if key and not key.startswith("your-"):
            base = self._get_key("openai_base") or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
            cfg = ProviderConfig(
                name="openai", api_key=key, base_url=base,
                models=["gpt-5.4", "gpt-5.4-thinking", "gpt-5.4-pro", "gpt-4.1", "gpt-4o", "gpt-4o-mini"],
                default_model="gpt-5.4",
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
                models=["claude-opus-4.6", "claude-sonnet-4.6", "claude-haiku-4-5-20251001"],
                default_model="claude-sonnet-4.6",
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
                models=["gemini-3.1-pro", "gemini-3.1-flash", "gemini-3.1-deep-think", "gemini-2.5-pro"],
                default_model="gemini-3.1-pro",
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
                models=["grok-4.20", "grok-4.20-beta"],
                default_model="grok-4.20",
                cost_per_1k_input=0.005, cost_per_1k_output=0.015,
                multimodal=True, env_key="XAI_API_KEY",
            )
            self.providers["xai"] = cfg
            self.adapters["xai"] = GrokAdapter(cfg)

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

        # DeepSeek
        key = self._get_key("deepseek")
        if not key:
            key = os.environ.get("DEEPSEEK_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="deepseek", api_key=key,
                base_url="https://api.deepseek.com/v1",
                models=["deepseek-ai/DeepSeek-V3.2", "deepseek-ai/DeepSeek-V3", "deepseek-chat", "deepseek-reasoner"],
                default_model="deepseek-ai/DeepSeek-V3.2",
                cost_per_1k_input=0.00014, cost_per_1k_output=0.00028,
                multimodal=False, env_key="DEEPSEEK_API_KEY",
            )
            self.providers["deepseek"] = cfg
            self.adapters["deepseek"] = DeepSeekAdapter(cfg)

        # Qwen (via Together AI)
        key = self._get_key("qwen")
        if not key:
            key = os.environ.get("QWEN_API_KEY", "") or os.environ.get("TOGETHER_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="qwen", api_key=key,
                base_url="https://api.together.xyz/v1",
                models=["Qwen/Qwen3.5-397B-A17B", "Qwen/Qwen3.5-397B-A17B-Coder", "Qwen/Qwen3-235B-A22B"],
                default_model="Qwen/Qwen3.5-397B-A17B",
                cost_per_1k_input=0.0018, cost_per_1k_output=0.0018,
                multimodal=False, env_key="QWEN_API_KEY",
            )
            self.providers["qwen"] = cfg
            self.adapters["qwen"] = QwenAdapter(cfg)

        # Zhipu GLM
        key = self._get_key("zhipu")
        if not key:
            key = os.environ.get("ZHIPU_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="zhipu", api_key=key,
                base_url="https://open.bigmodel.cn/api/paas/v4",
                models=["glm-4.6", "glm-4-flash"],
                default_model="glm-4.6",
                cost_per_1k_input=0.001, cost_per_1k_output=0.001,
                multimodal=True, env_key="ZHIPU_API_KEY",
            )
            self.providers["zhipu"] = cfg
            self.adapters["zhipu"] = ZhipuAdapter(cfg)

        # Moonshot Kimi
        key = self._get_key("moonshot")
        if not key:
            key = os.environ.get("MOONSHOT_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="moonshot", api_key=key,
                base_url="https://api.moonshot.cn/v1",
                models=["moonshot-v1-128k", "moonshot-v1-32k", "moonshot-v1-256k"],
                default_model="moonshot-v1-128k",
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

        # Ollama (local)
        ollama_url = self._get_key("ollama")
        if not ollama_url:
            ollama_url = os.environ.get("OLLAMA_URL", "")
        if ollama_url and not ollama_url.startswith("your-"):
            cfg = ProviderConfig(
                name="ollama", api_key="", base_url=ollama_url,
                models=["llama3", "mistral", "codellama"],
                default_model="llama3",
                supports_tools=False, supports_json_mode=False,
                multimodal=False, env_key="OLLAMA_URL",
            )
            self.providers["ollama"] = cfg
            self.adapters["ollama"] = OllamaAdapter(cfg)

        # OneAPI fallback
        oneapi_key = self._get_key("oneapi")
        if not oneapi_key:
            oneapi_key = os.environ.get("ONEAPI_API_KEY", "")
        oneapi_url = self._get_key("oneapi_url")
        if not oneapi_url:
            oneapi_url = os.environ.get("ONEAPI_URL", "")
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
        """
        if preferred_provider and preferred_provider in self.providers:
            prov = self.providers[preferred_provider]
            if prov.status != ProviderStatus.DOWN:
                model = self.select_model_by_complexity(
                    preferred_provider, task_type, complexity_score
                )
                return RoutingDecision(
                    provider=preferred_provider, model=model,
                    reason=f"用户指定提供商: {preferred_provider} (复杂度: {complexity_score:.2f})",
                )

        # 按任务偏好排序
        preferred_order = TASK_ROUTING_PREFERENCES.get(task_type, [])
        alternatives = []

        for provider_name in preferred_order:
            if provider_name not in self.providers:
                continue
            prov = self.providers[provider_name]
            if prov.status == ProviderStatus.DOWN:
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
            if prov.status != ProviderStatus.DOWN:
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
        """
        if preferred_provider and preferred_provider in self.providers:
            prov = self.providers[preferred_provider]
            if prov.status != ProviderStatus.DOWN:
                model = self.select_model_by_complexity(
                    preferred_provider, task_type, complexity_score
                )
                return RoutingDecision(
                    provider=preferred_provider, model=model,
                    reason=f"用户指定提供商: {preferred_provider} (复杂度: {complexity_score:.2f})",
                )

        # 按任务偏好排序
        preferred_order = TASK_ROUTING_PREFERENCES.get(task_type, [])
        alternatives = []

        for provider_name in preferred_order:
            if provider_name not in self.providers:
                continue
            prov = self.providers[provider_name]
            if prov.status == ProviderStatus.DOWN:
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
            if prov.status != ProviderStatus.DOWN:
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
            if prov.status == ProviderStatus.DOWN:
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
            if prov.status == ProviderStatus.DOWN:
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
                if self.providers[prov_name].status == ProviderStatus.DEGRADED:
                    self.providers[prov_name].status = ProviderStatus.HEALTHY
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
                except Exception:
                    pass

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
                self.providers[prov_name].error_count += 1
                self.providers[prov_name].last_error = str(e)
                if cb:
                    cb.record_failure()
                if self.providers[prov_name].error_count >= 5:
                    self.providers[prov_name].status = ProviderStatus.DOWN
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
                results[name] = f"error: {e}"
                self.providers[name].status = ProviderStatus.DOWN
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
                "active": prov.status != ProviderStatus.DOWN,
                "available": prov.status != ProviderStatus.DOWN,
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

        # 重新发现
        self._discover_providers()

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
