"""
core/unified/llm_router.py
===========================
Galaxy 系统统一 LLM 路由器入口（单例门面）。

PR-3 Provider-Routing-Closure 扩展：
  - 主编排层唯一合法模型访问入口（OpenClawd 及所有内部路径必须经由此处）
  - chat_with_tools() — 工具感知聊天统一入口（替代直接调用 MultiLLMRouter.chat()）
  - compute_complexity_vector() — 复杂度分析代理（避免主链穿透访问 _backend）
  - get_execution_backend() — 暴露底层 MultiLLMRouter，仅限极少数必要内部调用

Block-6 扩展：
  - 策略驱动路由（config/llm_routing_policy.yaml）
  - 路由遥测（成功率、延迟、fallback 率、成本）
  - 成本预算 / SLO 阈值执行（超限优雅降级）

Provider 层级（PR-3 明确）：
  UnifiedLLMRouter (本模块)          ← 唯一策略 + 遥测入口
    └─ MultiLLMRouter (_backend)     ← 执行层：provider 选择、故障转移
         ├─ OpenAI / Claude / Gemini ← 远程 API provider
         ├─ DeepSeek / Mistral / Groq ← 远程 API provider
         ├─ Ollama                    ← Local LLM provider（已纳入策略层治理）
         └─ OneAPI                    ← 聚合 / 代理 provider

Local VLM / multimodal provider 当前作为扩展能力（非主链），
通过 MultimodalBus 在 OpenClawd 感知层接入，不经由此路由器，
角色已在 core/openclawd.py 中明确为"host-perception 扩展层"。

委托 core.multi_llm_router.MultiLLMRouter 处理实际的模型路由，
提供强类型接口（LLMRequest / LLMResponse）和结构化日志。
"""

from __future__ import annotations

# PR-3: Unified provider routing closure authority sentinel.
UNIFIED_LLM_ROUTER_AUTHORITY: str = (
    "UNIFIED_LLM_ROUTER::PR3_PROVIDER_ROUTING_CLOSURE: "
    "core/unified/llm_router.py (UnifiedLLMRouter) is the sole legitimate "
    "model-access entry point for the main orchestration layer (OpenClawd "
    "and all paths originating from it).  Direct calls to "
    "core.multi_llm_router.get_llm_router() from the orchestration layer "
    "are prohibited; use self._get_router() / get_unified_llm_router() "
    "and call chat_with_tools() / chat_raw() / chat() through the unified "
    "router.  MultiLLMRouter is the execution backend; it is not a peer "
    "entry point.  Local LLM (Ollama) is governed by the unified policy "
    "layer as a registered backend provider.  Local VLM / multimodal "
    "providers are extension-layer capabilities (non-main-chain), not "
    "governed by this router.  Closes PR-3."
)

import asyncio
import collections
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from .exceptions import LLMProviderError, LLMRouterError, NoAvailableProviderError
from .models import LLMRequest, LLMResponse, LLMTaskType

logger = logging.getLogger("Galaxy.Unified.LLMRouter")

# ============================================================================
# 路由策略加载
# ============================================================================

_POLICY_PATH = Path(__file__).parent.parent.parent / "config" / "llm_routing_policy.yaml"


def _load_routing_policy() -> Dict[str, Any]:
    """加载 config/llm_routing_policy.yaml；不存在时返回空策略。"""
    if not _YAML_AVAILABLE:
        logger.debug("PyYAML not installed; routing policy disabled")
        return {}
    if not _POLICY_PATH.exists():
        logger.debug("llm_routing_policy.yaml not found at %s", _POLICY_PATH)
        return {}
    try:
        with _POLICY_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        logger.info("LLM routing policy loaded from %s", _POLICY_PATH)
        return data
    except Exception as exc:
        logger.warning("Failed to load routing policy: %s", exc)
        return {}


# ============================================================================
# 路由遥测
# ============================================================================

_TELEMETRY_WINDOW = 100  # 保留最近 N 次调用的滑动窗口


@dataclass
class _ProviderTelemetry:
    """单一提供商的滑动窗口遥测数据（线程安全）。"""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)
    # 每次调用 (success: bool, latency_ms: float, cost_usd: float)
    _history: collections.deque = field(
        default_factory=lambda: collections.deque(maxlen=_TELEMETRY_WINDOW),
        repr=False,
        compare=False,
    )
    total_calls: int = 0
    total_fallbacks: int = 0

    def record(self, success: bool, latency_ms: float, cost_usd: float, is_fallback: bool = False) -> None:
        with self._lock:
            self._history.append((success, latency_ms, cost_usd))
            self.total_calls += 1
            if is_fallback:
                self.total_fallbacks += 1

    def success_rate(self) -> float:
        with self._lock:
            if not self._history:
                return 1.0
            successes = sum(1 for s, _, __ in self._history if s)
            return successes / len(self._history)

    def avg_latency_ms(self) -> float:
        with self._lock:
            if not self._history:
                return 0.0
            return sum(lat for _, lat, __ in self._history) / len(self._history)

    def fallback_rate(self) -> float:
        with self._lock:
            if self.total_calls == 0:
                return 0.0
            return self.total_fallbacks / self.total_calls

    def avg_cost_usd(self) -> float:
        with self._lock:
            if not self._history:
                return 0.0
            return sum(c for _, __, c in self._history) / len(self._history)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_calls": self.total_calls,
            "total_fallbacks": self.total_fallbacks,
            "success_rate": round(self.success_rate(), 4),
            "avg_latency_ms": round(self.avg_latency_ms(), 2),
            "fallback_rate": round(self.fallback_rate(), 4),
            "avg_cost_usd_per_call": round(self.avg_cost_usd(), 6),
        }


class RoutingTelemetry:
    """跨提供商路由遥测聚合（单例）。"""

    _instance: Optional["RoutingTelemetry"] = None

    def __new__(cls) -> "RoutingTelemetry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._providers: Dict[str, _ProviderTelemetry] = {}
            cls._instance._global_lock = threading.Lock()
        return cls._instance

    def _get_or_create(self, provider: str) -> _ProviderTelemetry:
        with self._global_lock:
            if provider not in self._providers:
                self._providers[provider] = _ProviderTelemetry()
            return self._providers[provider]

    def record(
        self,
        provider: str,
        success: bool,
        latency_ms: float,
        cost_usd: float = 0.0,
        is_fallback: bool = False,
    ) -> None:
        self._get_or_create(provider).record(success, latency_ms, cost_usd, is_fallback)

    def get_metrics(self) -> Dict[str, Any]:
        with self._global_lock:
            return {p: t.to_dict() for p, t in self._providers.items()}

    def is_slo_violated(self, provider: str, policy_slo: Dict[str, Any]) -> bool:
        """根据 policy SLO 字典判断提供商是否违反 SLO。"""
        tel = self._providers.get(provider)
        if tel is None:
            return False
        if tel.total_calls < 3:
            return False  # 样本太少，不裁决

        max_latency = policy_slo.get("max_latency_ms", 30000)
        min_success = policy_slo.get("min_success_rate", 0.90)

        if tel.avg_latency_ms() > max_latency:
            logger.warning(
                "Provider %s SLO latency violated: %.0f > %.0f ms",
                provider, tel.avg_latency_ms(), max_latency,
            )
            return True
        if tel.success_rate() < min_success:
            logger.warning(
                "Provider %s SLO success_rate violated: %.2f < %.2f",
                provider, tel.success_rate(), min_success,
            )
            return True
        return False


def get_routing_telemetry() -> RoutingTelemetry:
    """返回全局 RoutingTelemetry 单例。"""
    return RoutingTelemetry()


def reset_routing_telemetry() -> None:
    """重置全局遥测单例（测试用）。"""
    RoutingTelemetry._instance = None


# ============================================================================
# 策略决策
# ============================================================================


def _resolve_provider_order(
    task_type: str,
    policy: Dict[str, Any],
    telemetry: RoutingTelemetry,
    preferred_provider: Optional[str] = None,
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """
    按策略为给定任务类型返回提供商顺序列表和对应的 SLO/预算约束。

    Returns:
        (ordered_provider_list, slo_dict_or_None)
    """
    task_routing: Dict[str, Any] = policy.get("task_routing", {})
    rule: Dict[str, Any] = task_routing.get(task_type, {})

    priorities: List[str] = list(rule.get("priorities", []))
    fallback: List[str] = list(
        rule.get("fallback_chain", policy.get("global_fallback_chain", []))
    )
    slo: Optional[Dict[str, Any]] = rule.get("slo") or policy.get("global_slo")

    # 如果有明确偏好提供商，排到首位
    if preferred_provider and preferred_provider not in priorities:
        priorities.insert(0, preferred_provider)
    elif preferred_provider and preferred_provider in priorities:
        priorities.remove(preferred_provider)
        priorities.insert(0, preferred_provider)

    # 过滤 SLO 违规的提供商（移到 fallback）
    if slo:
        ok, degraded = [], []
        for p in priorities:
            if telemetry.is_slo_violated(p, slo):
                degraded.append(p)
            else:
                ok.append(p)
        priorities = ok + degraded

    # 合并 fallback（去重保序）
    seen = set(priorities)
    for p in fallback:
        if p not in seen:
            priorities.append(p)
            seen.add(p)

    return priorities, slo


def _check_cost_budget(
    estimated_cost: float,
    task_type: str,
    policy: Dict[str, Any],
) -> bool:
    """返回 True 表示费用在预算内，False 表示超预算。"""
    task_routing = policy.get("task_routing", {})
    rule = task_routing.get(task_type, {})
    budget = rule.get("cost_budget") or {}
    global_budget = policy.get("global_slo", {})

    max_cost = budget.get(
        "max_cost_per_1k_tokens",
        global_budget.get("max_cost_per_1k_tokens", float("inf")),
    )
    return estimated_cost <= max_cost


# ============================================================================
# OpenAI 兼容结构（供 chat_completion 回退路径使用）
# ============================================================================


class _CompatMessage:
    """OpenAI 兼容的 message 对象。"""

    role: str = "assistant"
    tool_calls: None = None

    def __init__(self, content: str) -> None:
        self.content = content


class _CompatChoice:
    """OpenAI 兼容的 choice 对象。"""

    finish_reason: str = "stop"

    def __init__(self, content: str) -> None:
        self.message = _CompatMessage(content)


class _CompatUsage:
    """OpenAI 兼容的 usage 对象。"""

    def __init__(self, usage: Dict[str, Any]) -> None:
        self.prompt_tokens: int = usage.get("prompt_tokens", 0)
        self.completion_tokens: int = usage.get("completion_tokens", 0)
        self.total_tokens: int = usage.get("total_tokens", 0)


class _CompatResponse:
    """OpenAI 兼容的 response 对象（供依赖 .choices[0].message 的模块使用）。"""

    def __init__(self, content: str, model: str, usage: Dict[str, Any]) -> None:
        self.choices: List[_CompatChoice] = [_CompatChoice(content)]
        self.model: str = model
        self.usage: _CompatUsage = _CompatUsage(usage)


class UnifiedLLMRouter:
    """
    统一 LLM 路由器门面（进程级单例）。

    Block-6 扩展：
      - policy-driven routing (config/llm_routing_policy.yaml)
      - routing telemetry (success_rate / latency / fallback_rate / cost)
      - cost budget + SLO threshold enforcement with graceful fallback

    公开 API：
        chat(request: LLMRequest) -> LLMResponse
        chat_raw(messages, task_type, ...) -> LLMResponse
        get_status() -> Dict[str, Any]
        get_telemetry() -> Dict[str, Any]
        get_policy() -> Dict[str, Any]
    """

    _instance: Optional["UnifiedLLMRouter"] = None

    def __new__(cls) -> "UnifiedLLMRouter":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:  # type: ignore[has-type]
            return

        self._backend = self._load_backend()
        self._policy: Dict[str, Any] = _load_routing_policy()
        self._telemetry: RoutingTelemetry = get_routing_telemetry()
        self._initialized = True

        logger.info(
            "UnifiedLLMRouter initialized",
            extra={
                "event": "init",
                "backend": type(self._backend).__name__,
                "policy_loaded": bool(self._policy),
            },
        )

    # ------------------------------------------------------------------
    # 内部：加载后端实现
    # ------------------------------------------------------------------

    @staticmethod
    def _load_backend() -> Any:
        """加载 MultiLLMRouter 后端。"""
        try:
            from core.multi_llm_router import get_llm_router  # type: ignore
            router = get_llm_router()
            logger.info(
                "Using core.multi_llm_router as LLM backend",
                extra={"event": "backend_loaded"},
            )
            return router
        except Exception as exc:
            logger.warning(
                "core.multi_llm_router not available",
                extra={"event": "backend_unavailable", "reason": str(exc)},
            )
            return None

    # ------------------------------------------------------------------
    # 策略辅助
    # ------------------------------------------------------------------

    def _get_provider_order(
        self,
        task_type_str: str,
        preferred_provider: Optional[str] = None,
    ) -> Tuple[List[str], Optional[Dict[str, Any]]]:
        """返回 (provider_order, slo_dict)，遵循路由策略。"""
        return _resolve_provider_order(
            task_type=task_type_str,
            policy=self._policy,
            telemetry=self._telemetry,
            preferred_provider=preferred_provider,
        )

    def _estimate_cost_per_1k(self, provider: str, task_type_str: str) -> float:
        """从策略中读取估算的每 1k token 成本（若无配置则返回 0）。"""
        task_routing = self._policy.get("task_routing", {})
        rule = task_routing.get(task_type_str, {})
        budget = rule.get("cost_budget") or {}
        return float(budget.get("max_cost_per_1k_tokens", 0.0))

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """
        使用统一 LLMRequest 模型发起 LLM 对话请求（策略驱动 + 遥测 + 预算执行）。

        Args:
            request: LLMRequest Pydantic 模型实例。

        Returns:
            LLMResponse Pydantic 模型实例。

        Raises:
            NoAvailableProviderError: 没有可用的 LLM 提供商。
            LLMProviderError: 提供商调用失败。
        """
        if self._backend is None:
            raise NoAvailableProviderError(task_type=request.task_type)

        task_type_str = (
            request.task_type
            if isinstance(request.task_type, str)
            else request.task_type.value
        )

        # 策略：获取提供商优先顺序
        provider_order, slo = self._get_provider_order(
            task_type_str, request.preferred_provider
        )

        start = time.monotonic()
        result = None
        used_provider = "unknown"
        is_fallback = False
        last_exc: Optional[Exception] = None

        # 若策略无可用提供商列表，回退到单次无偏好调用
        _effective_order: List[Optional[str]] = (
            list(provider_order) if provider_order else [request.preferred_provider]
        )

        # 尝试按策略顺序逐个提供商
        for idx, provider in enumerate(_effective_order):
            _preferred = provider or request.preferred_provider
            try:
                result = await self._backend.chat(
                    messages=request.messages,
                    task_type=task_type_str,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    preferred_provider=_preferred,
                )
                used_provider = provider or "unknown"
                is_fallback = idx > 0
                break
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM provider %s failed (attempt %d/%d): %s",
                    provider, idx + 1, len(_effective_order), exc,
                )
                continue

        if result is None:
            latency_ms = (time.monotonic() - start) * 1000
            self._telemetry.record(
                "unknown", success=False, latency_ms=latency_ms, is_fallback=False
            )
            raise LLMProviderError(
                provider="all",
                reason=str(last_exc) if last_exc else "all providers failed",
            )

        latency_ms = (time.monotonic() - start) * 1000

        # 解析 result（multi_llm_router 返回 dict 或对象）
        if isinstance(result, dict):
            content = result.get("content") or result.get("text") or str(result)
            provider_name = result.get("provider", used_provider)
            model = result.get("model", "unknown")
            usage = result.get("usage", {})
        else:
            content = getattr(result, "content", str(result))
            provider_name = getattr(result, "provider", used_provider)
            model = getattr(result, "model", "unknown")
            usage = getattr(result, "usage", {})

        # 估算成本（基于 token 用量）
        total_tokens = (
            usage.get("total_tokens", 0)
            if isinstance(usage, dict)
            else getattr(usage, "total_tokens", 0)
        )
        cost_per_1k = self._estimate_cost_per_1k(provider_name, task_type_str)
        estimated_cost = (total_tokens / 1000.0) * cost_per_1k

        # 预算检查（超限记录警告，但不中断已完成的调用）
        if self._policy and not _check_cost_budget(cost_per_1k, task_type_str, self._policy):
            logger.warning(
                "LLM cost budget exceeded for task_type=%s provider=%s cost_per_1k=%.4f",
                task_type_str, provider_name, cost_per_1k,
            )

        # 记录遥测
        self._telemetry.record(
            provider=provider_name,
            success=True,
            latency_ms=latency_ms,
            cost_usd=estimated_cost,
            is_fallback=is_fallback,
        )

        logger.info(
            "LLM chat completed",
            extra={
                "event": "llm_chat_done",
                "task_type": task_type_str,
                "provider": provider_name,
                "model": model,
                "latency_ms": round(latency_ms, 2),
                "is_fallback": is_fallback,
                "tokens": total_tokens,
            },
        )

        return LLMResponse(
            request_id=request.request_id,
            provider=provider_name,
            model=model,
            content=content,
            usage=usage if isinstance(usage, dict) else {},
            latency_ms=latency_ms,
            success=True,
        )

    async def chat_raw(
        self,
        messages: List[Dict[str, str]],
        task_type: "str | LLMTaskType" = LLMTaskType.GENERAL,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        preferred_provider: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """
        便捷方法：直接传入 messages 列表，无需构造 LLMRequest 对象。
        """
        request = LLMRequest(
            messages=messages,
            task_type=task_type,
            max_tokens=max_tokens,
            temperature=temperature,
            preferred_provider=preferred_provider,
            metadata=metadata or {},
        )
        return await self.chat(request)

    def get_status(self) -> Dict[str, Any]:
        """返回 LLM 提供商状态信息（含遥测快照）。"""
        base: Dict[str, Any] = {"available": False, "providers": []}
        if self._backend is None:
            return base

        try:
            if hasattr(self._backend, "get_status"):
                raw = self._backend.get_status()
                if isinstance(raw, dict):
                    base = raw
            elif hasattr(self._backend, "providers"):
                providers = [
                    {
                        "name": p.name if hasattr(p, "name") else str(p),
                        "status": p.status.value if hasattr(p, "status") else "unknown",
                    }
                    for p in self._backend.providers.values()
                ]
                base = {"available": True, "providers": providers}
            else:
                base = {"available": True, "providers": []}
        except Exception as exc:
            logger.warning(
                "Failed to get LLM status",
                extra={"event": "status_error", "reason": str(exc)},
            )

        base["telemetry"] = self._telemetry.get_metrics()
        base["policy_loaded"] = bool(self._policy)
        return base

    def get_telemetry(self) -> Dict[str, Any]:
        """返回所有提供商的路由遥测指标快照。"""
        return self._telemetry.get_metrics()

    def get_policy(self) -> Dict[str, Any]:
        """返回当前加载的路由策略（只读副本）。"""
        return dict(self._policy)

    def reload_policy(self) -> None:
        """重新加载路由策略文件（运行时热更新）。"""
        self._policy = _load_routing_policy()
        logger.info("LLM routing policy reloaded", extra={"event": "policy_reloaded"})

    # ------------------------------------------------------------------
    # 代理方法（供 legacy 模块兼容使用）
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """检查是否有可用的 LLM 提供商。"""
        if self._backend is None:
            return False
        try:
            if hasattr(self._backend, "is_available"):
                return bool(self._backend.is_available())
        except Exception:
            pass
        return True

    def get_default_model(self) -> str:
        """返回当前默认模型名称。"""
        if self._backend is None:
            return "gpt-4o"
        try:
            if hasattr(self._backend, "get_default_model"):
                return str(self._backend.get_default_model())
        except Exception:
            pass
        return "gpt-4o"

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model_alias: Optional[str] = None,
        task_type: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """
        OpenAI 兼容的 chat_completion 代理方法。

        委派到后端 MultiLLMRouter.chat_completion()（若可用），
        否则通过 self.chat_raw() 并返回 OpenAI 兼容结构。
        """
        if self._backend is not None and hasattr(self._backend, "chat_completion"):
            return await self._backend.chat_completion(
                messages=messages,
                tools=tools,
                model_alias=model_alias,
                task_type=task_type,
                **kwargs,
            )

        # 无 chat_completion 时回退到统一 chat 接口
        llm_resp = await self.chat_raw(
            messages=messages,
            task_type=task_type or "general",
            max_tokens=kwargs.get("max_tokens", 2048),
            temperature=kwargs.get("temperature", 0.7),
        )

        return _CompatResponse(
            content=llm_resp.content,
            model=llm_resp.model,
            usage=llm_resp.usage,
        )

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        task_type: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> Any:
        """
        工具感知聊天统一入口（PR-3 provider routing closure）。

        接受与 MultiLLMRouter.chat() 相同的关键字参数，通过统一策略层和
        遥测层透明委派到 _backend.chat()，返回 MultiLLMRouter.LLMResponse。

        这是主编排层（OpenClawd / AgentFactory / _react_loop 等）调用带工具
        的 LLM 时应使用的**唯一合法入口**，以确保所有调用都经过统一路由策略和
        遥测记录，不可绕过。

        设计原则：
        - 统一策略层负责决定**首选 provider**（来自 llm_routing_policy.yaml 或默认偏好）
        - 执行层（MultiLLMRouter._backend）负责**故障转移**（auto_failover=True 默认行为）
        - 避免在统一层和执行层之间出现双重 fallback 循环

        Args:
            messages:     对话消息列表
            task_type:    任务类型字符串（与 MultiLLMRouter.TaskType 值对齐）
            provider:     强制指定提供商（可选，覆盖策略选择）
            model:        强制指定模型名（可选）
            tools:        工具函数定义列表（OpenAI function-calling 格式）
            temperature:  采样温度
            max_tokens:   最大生成 token 数
            **kwargs:     其余参数透传给 _backend.chat()

        Returns:
            MultiLLMRouter.LLMResponse  —— 保持与既有调用方的向后兼容。

        Raises:
            NoAvailableProviderError: 没有可用后端。
        """
        if self._backend is None:
            raise NoAvailableProviderError(task_type=task_type)

        # 应用策略层：获取首选 provider（统一策略层职责）
        task_type_str = task_type or "general"
        _provider_order, _slo = self._get_provider_order(
            task_type_str,
            preferred_provider=provider,
        )
        # 取策略层最优先 provider；若无策略顺序（空列表或 None）则使用调用方明确指定的（可为 None）。
        # `_provider_order[0]` is safe here because we only access index 0 when the list is
        # non-empty (truthy), which is guaranteed by the `if _provider_order` guard.
        _effective_provider = _provider_order[0] if _provider_order else provider

        start = time.monotonic()
        try:
            # 执行层（MultiLLMRouter）负责 provider 内部故障转移（auto_failover 默认 True）
            result = await self._backend.chat(
                messages=messages,
                task_type=task_type_str,
                provider=_effective_provider,
                model=model,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            latency_ms = (time.monotonic() - start) * 1000
            _actual_provider = getattr(result, "provider", _effective_provider or "unknown")
            is_fallback = bool(_effective_provider and _actual_provider != _effective_provider)
            self._telemetry.record(
                provider=_actual_provider,
                success=True,
                latency_ms=latency_ms,
                is_fallback=is_fallback,
            )
            logger.info(
                "chat_with_tools completed",
                extra={
                    "event": "chat_with_tools_done",
                    "task_type": task_type_str,
                    "preferred_provider": _effective_provider,
                    "actual_provider": _actual_provider,
                    "model": getattr(result, "model", "unknown"),
                    "latency_ms": round(latency_ms, 2),
                    "is_fallback": is_fallback,
                    "has_tools": bool(tools),
                },
            )
            return result
        except Exception as exc:
            latency_ms = (time.monotonic() - start) * 1000
            self._telemetry.record(
                _effective_provider or "unknown",
                success=False,
                latency_ms=latency_ms,
            )
            raise

    def compute_complexity_vector(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        """
        任务复杂度向量计算（PR-3 统一入口代理）。

        委派到 _backend._compute_complexity_vector()（若可用），否则返回
        一个静态默认 ComplexityVector（中等复杂度）。

        统一层提供此方法，使得调用方无需直接访问 _backend 来计算复杂度，
        从而避免主编排层内部出现 `router._backend._compute_complexity_vector()`
        等穿透性调用。
        """
        if self._backend is not None and hasattr(self._backend, "_compute_complexity_vector"):
            return self._backend._compute_complexity_vector(messages, tools)
        # 降级：无后端时返回中等复杂度占位对象
        try:
            from core.schemas.routing import ComplexityVector
            return ComplexityVector(
                context_length=0.5,
                logic_depth=0.5,
                domain_expertise=0.5,
                precision_requirement=0.5,
                tool_needs=0.5,
            )
        except Exception:
            return None

    def get_execution_backend(self) -> Any:
        """
        返回底层执行后端（MultiLLMRouter）。

        仅用于极少数需要直接访问执行层（如复杂度分析、断路器状态检查等）
        的内部调用。主编排层的模型访问必须通过 chat_with_tools() / chat_raw()
        / chat() 进行，而不是直接调用 _backend.chat()。
        """
        return self._backend


# ============================================================================
# 进程级单例访问函数
# ============================================================================


_router: Optional[UnifiedLLMRouter] = None


def get_unified_llm_router() -> UnifiedLLMRouter:
    """返回进程级 UnifiedLLMRouter 单例。"""
    global _router
    if _router is None:
        _router = UnifiedLLMRouter()
    return _router


def reset_unified_llm_router() -> None:
    """重置 UnifiedLLMRouter 单例（测试用）。"""
    global _router
    _router = None
    UnifiedLLMRouter._instance = None
