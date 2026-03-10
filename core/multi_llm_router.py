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

# 任务类型 → 提供商优先级
TASK_ROUTING_PREFERENCES: Dict[TaskType, List[str]] = {
    TaskType.REASONING:      ["anthropic", "openai", "deepseek"],
    TaskType.FAST_RESPONSE:  ["deepseek", "groq", "openai"],
    TaskType.CODING:         ["deepseek", "anthropic", "openai"],
    TaskType.CREATIVE:       ["openai", "anthropic", "deepseek"],
    TaskType.ANALYSIS:       ["anthropic", "openai", "deepseek"],
    TaskType.PLANNING:       ["anthropic", "openai", "deepseek"],
    TaskType.AGENT_CONTROL:  ["anthropic", "openai", "deepseek"],
    TaskType.GENERAL:        ["openai", "anthropic", "deepseek"],
}

# 提供商 → 推荐模型
PROVIDER_MODEL_MAP: Dict[str, Dict[TaskType, str]] = {
    "openai": {
        TaskType.REASONING:     "gpt-4o",
        TaskType.FAST_RESPONSE: "gpt-4o-mini",
        TaskType.CODING:        "gpt-4o",
        TaskType.CREATIVE:      "gpt-4o",
        TaskType.ANALYSIS:      "gpt-4o",
        TaskType.PLANNING:      "gpt-4o",
        TaskType.AGENT_CONTROL: "gpt-4o",
        TaskType.GENERAL:       "gpt-4o-mini",
    },
    "anthropic": {
        TaskType.REASONING:     "claude-sonnet-4-5-20250929",
        TaskType.FAST_RESPONSE: "claude-haiku-4-5-20251001",
        TaskType.CODING:        "claude-sonnet-4-5-20250929",
        TaskType.CREATIVE:      "claude-sonnet-4-5-20250929",
        TaskType.ANALYSIS:      "claude-sonnet-4-5-20250929",
        TaskType.PLANNING:      "claude-sonnet-4-5-20250929",
        TaskType.AGENT_CONTROL: "claude-sonnet-4-5-20250929",
        TaskType.GENERAL:       "claude-haiku-4-5-20251001",
    },
    "deepseek": {
        TaskType.REASONING:     "deepseek-reasoner",
        TaskType.FAST_RESPONSE: "deepseek-chat",
        TaskType.CODING:        "deepseek-chat",
        TaskType.CREATIVE:      "deepseek-chat",
        TaskType.ANALYSIS:      "deepseek-reasoner",
        TaskType.PLANNING:      "deepseek-reasoner",
        TaskType.AGENT_CONTROL: "deepseek-chat",
        TaskType.GENERAL:       "deepseek-chat",
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

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.config.timeout)
        return self._client

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
        client = await self._get_client()
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
        resp = await client.post(
            f"{self.config.base_url}/chat/completions",
            headers=headers, json=body,
        )
        latency = (time.monotonic() - t0) * 1000
        resp.raise_for_status()
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
        client = await self._get_client()
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
        resp = await client.post(
            f"{self.config.base_url}/messages",
            headers=headers, json=body,
        )
        latency = (time.monotonic() - t0) * 1000
        resp.raise_for_status()
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
        client = await self._get_client()
        body = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }

        t0 = time.monotonic()
        resp = await client.post(
            f"{self.config.base_url}/api/chat",
            json=body,
        )
        latency = (time.monotonic() - t0) * 1000
        resp.raise_for_status()
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


# ───────────────────── 主路由器 ─────────────────────

ADAPTER_MAP = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "deepseek": DeepSeekAdapter,
    "groq": GroqAdapter,
    "ollama": OllamaAdapter,
}


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
        self._discover_providers()
        # 为每个提供商创建断路器
        for name in self.providers:
            self.circuit_breakers[name] = ProviderCircuitBreaker(name)

    def _get_key(self, key_name: str) -> str:
        """优先从 CredentialVault 获取密钥，若不可用则回退环境变量"""
        try:
            from core.credential_vault import get_vault
            val = get_vault().get_credential(key_name, actor="llm_router")
            if val:
                return val
        except Exception:
            pass
        return os.environ.get(key_name.upper() if "_" in key_name else key_name, "")

    def _discover_providers(self):
        """从环境变量（或 CredentialVault）自动发现并注册提供商"""

        # OpenAI
        key = self._get_key("openai")
        if not key:
            key = os.environ.get("OPENAI_API_KEY", "")
        if key and not key.startswith("your-"):
            base = self._get_key("openai_base") or os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
            cfg = ProviderConfig(
                name="openai", api_key=key, base_url=base,
                models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
                default_model="gpt-4o",
                cost_per_1k_input=0.005, cost_per_1k_output=0.015,
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
                models=["claude-sonnet-4-5-20250929", "claude-haiku-4-5-20251001"],
                default_model="claude-sonnet-4-5-20250929",
                cost_per_1k_input=0.003, cost_per_1k_output=0.015,
            )
            self.providers["anthropic"] = cfg
            self.adapters["anthropic"] = AnthropicAdapter(cfg)

        # DeepSeek
        key = self._get_key("deepseek")
        if not key:
            key = os.environ.get("DEEPSEEK_API_KEY", "")
        if key and not key.startswith("your-"):
            cfg = ProviderConfig(
                name="deepseek", api_key=key,
                base_url="https://api.deepseek.com/v1",
                models=["deepseek-chat", "deepseek-reasoner"],
                default_model="deepseek-chat",
                cost_per_1k_input=0.00014, cost_per_1k_output=0.00028,
            )
            self.providers["deepseek"] = cfg
            self.adapters["deepseek"] = DeepSeekAdapter(cfg)

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
                supports_tools=True,
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
            )
            self.providers["oneapi"] = cfg
            self.adapters["oneapi"] = OpenAIAdapter(cfg)

        logger.info(
            f"LLM 路由器已初始化，发现 {len(self.providers)} 个提供商: "
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

    def _compute_complexity_score(
        self, messages: List[Dict], tools: Optional[List[Dict]] = None
    ) -> float:
        """量化评估任务复杂度 (0.0-1.0)

        5 维向量加权求和：
          - 上下文长度 (0.15)
          - 逻辑深度 (0.25)
          - 领域专业度 (0.20)
          - 精度要求 (0.20)
          - 工具需求 (0.20)
        """
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

        # ── 加权求和 ──
        score = (
            0.15 * dim_context
            + 0.25 * dim_logic
            + 0.20 * dim_domain
            + 0.20 * dim_precision
            + 0.20 * dim_tools
        )
        return round(min(1.0, score), 3)

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

    def _select_model_by_complexity(
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
                model = self._select_model_by_complexity(
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

            model = self._select_model_by_complexity(
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

        raise RuntimeError("没有可用的 LLM 提供商，请检查 API Key 配置")

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
        # 1. 分类任务 + 复杂度评估
        classified = self.classify_task(messages, task_type)
        complexity = self._compute_complexity_score(messages, tools)
        logger.info(f"任务分类: {classified.value} | 复杂度: {complexity}")

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

                # 记录调用历史
                self.call_history.append({
                    "provider": prov_name,
                    "model": mdl,
                    "task_type": classified.value,
                    "complexity": complexity,
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

        raise RuntimeError(
            f"所有提供商调用失败 (已尝试: {tried_providers})，请检查 API Key"
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
        return json.loads(text.strip())

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
                "source": "env/vault",
                "active": prov.status != ProviderStatus.DOWN,
                "supports_tools": prov.supports_tools,
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
