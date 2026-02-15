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

class BaseProviderAdapter:
    """提供商适配器基类"""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
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
        self.call_history: List[Dict] = []
        self._lock = asyncio.Lock()
        self._discover_providers()

    def _discover_providers(self):
        """从环境变量自动发现并注册提供商"""

        # OpenAI
        key = os.environ.get("OPENAI_API_KEY", "")
        if key and not key.startswith("your-"):
            base = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1")
            cfg = ProviderConfig(
                name="openai", api_key=key, base_url=base,
                models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
                default_model="gpt-4o",
                cost_per_1k_input=0.005, cost_per_1k_output=0.015,
            )
            self.providers["openai"] = cfg
            self.adapters["openai"] = OpenAIAdapter(cfg)

        # Anthropic
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
        oneapi_key = os.environ.get("ONEAPI_API_KEY", "")
        oneapi_url = os.environ.get("ONEAPI_URL", "")
        if oneapi_key and not oneapi_key.startswith("your-") and oneapi_url:
            cfg = ProviderConfig(
                name="oneapi", api_key=oneapi_key,
                base_url=f"{oneapi_url}/v1",
                models=["gpt-4o", "gpt-4o-mini"],
                default_model="gpt-4o",
            )
            self.providers["oneapi"] = cfg
            self.adapters["oneapi"] = OpenAIAdapter(cfg)

        logger.info(
            f"LLM 路由器已初始化，发现 {len(self.providers)} 个提供商: "
            f"{list(self.providers.keys())}"
        )

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

        # 关键词 → 任务类型
        patterns = {
            TaskType.CODING: [
                "代码", "编程", "函数", "类", "bug", "code", "implement",
                "debug", "function", "class", "api", "脚本", "script",
            ],
            TaskType.REASONING: [
                "为什么", "推理", "解释", "分析原因", "why", "reason",
                "explain", "思考", "逻辑", "论证",
            ],
            TaskType.PLANNING: [
                "计划", "规划", "步骤", "方案", "plan", "strategy",
                "分解", "目标", "路线图", "roadmap",
            ],
            TaskType.CREATIVE: [
                "创作", "写", "故事", "诗", "write", "create",
                "creative", "设计", "文章", "作文",
            ],
            TaskType.ANALYSIS: [
                "分析", "数据", "报告", "统计", "analyze", "data",
                "report", "评估", "比较",
            ],
            TaskType.AGENT_CONTROL: [
                "agent", "执行", "控制", "设备", "节点", "device",
                "node", "命令", "command",
            ],
        }

        scores: Dict[TaskType, int] = {}
        for task_type, keywords in patterns.items():
            score = sum(1 for kw in keywords if kw in last_user_msg)
            if score > 0:
                scores[task_type] = score

        if scores:
            return max(scores, key=scores.get)

        return TaskType.GENERAL

    def route(self, task_type: TaskType,
              preferred_provider: Optional[str] = None) -> RoutingDecision:
        """
        根据任务类型做出路由决策

        优先级：
        1. 用户指定的提供商
        2. 任务类型推荐的提供商（跳过不可用的）
        3. 任意可用提供商
        """
        if preferred_provider and preferred_provider in self.providers:
            prov = self.providers[preferred_provider]
            if prov.status != ProviderStatus.DOWN:
                model = PROVIDER_MODEL_MAP.get(preferred_provider, {}).get(
                    task_type, prov.default_model
                )
                return RoutingDecision(
                    provider=preferred_provider, model=model,
                    reason=f"用户指定提供商: {preferred_provider}",
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

            model = PROVIDER_MODEL_MAP.get(provider_name, {}).get(
                task_type, prov.default_model
            )
            if not alternatives:
                selected = RoutingDecision(
                    provider=provider_name, model=model,
                    reason=f"任务类型 [{task_type.value}] 最佳匹配",
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
        # 1. 分类任务
        classified = self.classify_task(messages, task_type)
        logger.info(f"任务分类: {classified.value}")

        # 2. 路由决策
        decision = self.route(classified, provider)
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

            try:
                response = await adapter.chat(
                    messages=messages, model=mdl, tools=tools,
                    temperature=temperature, max_tokens=max_tokens,
                    response_format=response_format, **kwargs,
                )

                # 更新状态
                self.providers[prov_name].success_count += 1
                self.providers[prov_name].last_used = time.time()
                self.providers[prov_name].latency_avg_ms = (
                    self.providers[prov_name].latency_avg_ms * 0.8
                    + response.latency_ms * 0.2
                )
                if self.providers[prov_name].status == ProviderStatus.DEGRADED:
                    self.providers[prov_name].status = ProviderStatus.HEALTHY

                # 记录调用历史
                self.call_history.append({
                    "provider": prov_name,
                    "model": mdl,
                    "task_type": classified.value,
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
            providers_status[name] = {
                "status": prov.status.value,
                "models": prov.models,
                "default_model": prov.default_model,
                "success_count": prov.success_count,
                "error_count": prov.error_count,
                "latency_avg_ms": round(prov.latency_avg_ms, 1),
                "last_error": prov.last_error,
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

    async def close(self):
        for adapter in self.adapters.values():
            await adapter.close()


# ───────────────────── 单例 ─────────────────────

_router_instance: Optional[MultiLLMRouter] = None


def get_llm_router() -> MultiLLMRouter:
    global _router_instance
    if _router_instance is None:
        _router_instance = MultiLLMRouter()
    return _router_instance
