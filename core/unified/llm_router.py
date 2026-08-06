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

import collections  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import logging  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import threading  # noqa: E402  哨兵权威声明置顶是本仓设计习语
import time  # noqa: E402  哨兵权威声明置顶是本仓设计习语
from dataclasses import dataclass, field  # noqa: E402  哨兵权威声明置顶是本仓设计习语
from pathlib import Path  # noqa: E402  哨兵权威声明置顶是本仓设计习语
from typing import Any, Dict, List, Optional, Tuple  # noqa: E402  哨兵权威声明置顶是本仓设计习语

try:
    import yaml

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

from .exceptions import LLMProviderError, NoAvailableProviderError  # noqa: E402  哨兵权威声明置顶是本仓设计习语
from .models import LLMRequest, LLMResponse, LLMTaskType  # noqa: E402  哨兵权威声明置顶是本仓设计习语

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
                provider,
                tel.avg_latency_ms(),
                max_latency,
            )
            return True
        if tel.success_rate() < min_success:
            logger.warning(
                "Provider %s SLO success_rate violated: %.2f < %.2f",
                provider,
                tel.success_rate(),
                min_success,
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
    provider_rates: Optional[Dict[str, float]] = None,
    tool_capable: Optional[Dict[str, bool]] = None,
) -> Tuple[List[str], Optional[Dict[str, Any]]]:
    """
    按策略为给定任务类型返回提供商顺序列表和对应的 SLO/预算约束。

    Args:
        provider_rates: ``provider → 每 1k token 实际单价(USD)``。给了就据此做**成本
            降级**;不给(或某家不在表里)则该家不参与成本降级 —— 单价未知不等于超预算。
        tool_capable: ``provider → 是否支持工具调用``。给了就据此执行策略里的
            ``constraints.require_tools``;查不到的一律当作支持(保守放行,不错杀)。

    Returns:
        (ordered_provider_list, slo_dict_or_None)
    """
    task_routing: Dict[str, Any] = policy.get("task_routing", {})
    rule: Dict[str, Any] = task_routing.get(task_type, {})

    priorities: List[str] = list(rule.get("priorities", []))
    fallback: List[str] = list(rule.get("fallback_chain", policy.get("global_fallback_chain", [])))
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

    # 成本降级:超出本任务 cost_budget 的提供商往后排。
    #
    # 策略 YAML 对 global_slo.max_cost_per_1k_tokens 的注释写着"超过此值触发降级",
    # 但在此之前**没有任何东西会降级** —— cost_budget 整体是装饰性的(详见
    # _check_cost_budget 的说明)。这里按 SLO 降级那一套完全相同的做法补上:只重排,
    # 不删除。贵的那家仍然可用,只是不再优先;真到只剩它,照样会被调用。
    #
    # 单价未知的一律**不罚**:PROVIDER_REGISTRY 里 openrouter 这类聚合器单价写 0
    # (真实成本随所选底层模型浮动),把"查不到"当成"超预算"会错杀。
    # 与 SLO 降级的一处**有意的不对称**:显式指定的 provider 豁免成本降级,但不豁免 SLO
    # 降级。理由是两者的性质不同 —— SLO 降级的依据是"这家实测正在坏"(高延迟/低成功率),
    # 那是覆盖显式选择的正当理由;成本只是默认偏好,调用方既然点名要这家,预算不该悄悄把
    # 它挪到队尾。不写下来的话,下一个人会以为这是漏掉了。
    if provider_rates:
        ceiling = _cost_ceiling(task_type, policy)
        if ceiling != float("inf"):
            affordable, pricey = [], []
            for p in priorities:
                rate = provider_rates.get(p)
                if rate is not None and rate > ceiling and p != preferred_provider:
                    pricey.append(p)
                else:
                    affordable.append(p)
            if pricey:
                logger.info(
                    "Cost degradation for task_type=%s: %s exceed %.4f USD/1k, deprioritised",
                    task_type,
                    pricey,
                    ceiling,
                )
            priorities = affordable + pricey

    # constraints.require_tools:不支持工具调用的提供商往后排。
    #
    # 这个字段在策略 YAML 的"字段说明"里明写着是可选约束之一,agent_control 也确实设了
    # require_tools: true,但在此之前**全仓库没有任何地方读它**(grep 零命中)。
    #
    # 今天还没被违反 —— registry 里唯一 supports_tools=False 的是 perplexity,而它不在
    # agent_control 的 priorities 里。所以这是个**潜在**缺口而非现行故障。但它离故障只有
    # 一次 YAML 编辑的距离:perplexity 是搜索型 provider,往 agent 任务里加它相当自然,
    # 加完之后工具调用会静默失败,而策略里那句 require_tools: true 全程无声。
    #
    # 同样只重排不删除:排最后仍可能被调用,但至少不会白费第一次尝试,而且现在会有告警。
    if tool_capable and (rule.get("constraints") or {}).get("require_tools"):
        capable, incapable = [], []
        for p in priorities:
            # 查不到的当作支持:registry 的 supports_tools 默认就是 True,把"不知道"
            # 当成"不支持"会把绝大多数 provider 误伤。
            if tool_capable.get(p, True):
                capable.append(p)
            else:
                incapable.append(p)
        if incapable:
            logger.warning(
                "task_type=%s 要求工具调用(require_tools),但 %s 不支持 —— 已排到末位",
                task_type,
                incapable,
            )
        priorities = capable + incapable

    # 合并 fallback（去重保序）
    seen = set(priorities)
    for p in fallback:
        if p not in seen:
            priorities.append(p)
            seen.add(p)

    return priorities, slo


def _cost_ceiling(task_type: str, policy: Dict[str, Any]) -> float:
    """本任务类型允许的每 1k token 上限(USD)。任务级优先,否则用全局,再否则无上限。"""
    rule = policy.get("task_routing", {}).get(task_type, {})
    budget = rule.get("cost_budget") or {}
    global_budget = policy.get("global_slo", {})
    return float(
        budget.get(
            "max_cost_per_1k_tokens",
            global_budget.get("max_cost_per_1k_tokens", float("inf")),
        )
    )


def _check_cost_budget(
    estimated_cost: float,
    task_type: str,
    policy: Dict[str, Any],
) -> bool:
    """返回 True 表示费用在预算内，False 表示超预算。

    这个函数本身一直是对的,而且 tests/test_pr6_block6.py 用手挑的数值(0.10/0.20 对
    0.15 的上限)单测过它。**出问题的是喂给它的东西**:调用方
    ``_estimate_cost_per_1k()`` 原先返回的就是本任务的 ``cost_budget
    .max_cost_per_1k_tokens`` —— 也就是上限自己。于是这里恒等于 ``x <= x``,在任何
    (任务, 提供商) 组合下都判"在预算内",整个成本预算层是个空转:

    * 上面那句超预算告警**不可达**;
    * 记进遥测的 ``cost_usd`` 是 ``tokens/1000 × 上限``,同一任务下每家完全相同 ——
      免费的 ollama 与 0.003/1k 的 anthropic 被记成一样贵(reasoning 下都是 0.15)。

    "单元测试过了、集成起来是空的"正是这个 bug 能活下来的原因:单测只证明了函数,没有
    证明接线。现在 ``_estimate_cost_per_1k()`` 改为取**该提供商的真实单价**,这里才有
    意义。
    """
    return estimated_cost <= _cost_ceiling(task_type, policy)


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

        # PR-6: L1/L2/L3 cognitive authority — lazy-initialised on first use
        # so that import-time errors in the authority modules never prevent
        # the router from initialising.
        self._l1_authority: Any = None  # LLMRouteAuthority (L1)
        self._l2_authority: Any = None  # LLMSupplyAuthority (L2)
        self._l3_authority: Any = None  # CognitiveContextAuthority (L3)

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
    # PR-6: L1 / L2 / L3 cognitive authority helpers
    # ------------------------------------------------------------------

    def _get_l1_route_authority(self) -> Any:
        """Lazy-load and return the L1 :class:`LLMRouteAuthority` singleton."""
        if self._l1_authority is None:
            try:
                from core.llm.route_authority import get_llm_route_authority

                self._l1_authority = get_llm_route_authority()
            except Exception as exc:  # pragma: no cover
                logger.debug("L1 route authority unavailable: %s", exc)
        return self._l1_authority

    def _get_l2_supply_authority(self) -> Any:
        """Lazy-load and return the L2 :class:`LLMSupplyAuthority` singleton."""
        if self._l2_authority is None:
            try:
                from core.llm.supply_authority import get_llm_supply_authority

                self._l2_authority = get_llm_supply_authority()
            except Exception as exc:  # pragma: no cover
                logger.debug("L2 supply authority unavailable: %s", exc)
        return self._l2_authority

    def _get_l3_context_authority(self) -> Any:
        """Lazy-load and return the L3 :class:`CognitiveContextAuthority` singleton."""
        if self._l3_authority is None:
            try:
                from core.llm.context_authority import get_cognitive_context_authority

                self._l3_authority = get_cognitive_context_authority()
            except Exception as exc:  # pragma: no cover
                logger.debug("L3 context authority unavailable: %s", exc)
        return self._l3_authority

    def _consult_l1_route(
        self,
        task_type_str: str,
        preferred_provider: Optional[str],
    ) -> Tuple[Optional[str], Optional[str], List[str], Any]:
        """Consult the L1 route authority for a canonical routing decision.

        Returns ``(provider, model, alternatives, decision_object)``.  On any
        error the original ``preferred_provider`` is returned and the decision
        object is ``None`` so that callers fall back to the existing policy
        layer gracefully.
        """
        l1 = self._get_l1_route_authority()
        if l1 is None:
            return preferred_provider, None, [], None
        try:
            from core.llm.route_authority import LLMRouteRequest as _L1RouteRequest

            decision = l1.resolve(
                _L1RouteRequest(
                    task_type=task_type_str,
                    complexity=0.5,
                    preferred_provider=preferred_provider,
                )
            )
            alternatives: List[str] = list(getattr(decision, "alternatives", []) or [])
            logger.debug(
                "L1 route authority: provider=%s model=%s",
                decision.provider,
                decision.model,
            )
            return decision.provider, decision.model, alternatives, decision
        except Exception as exc:
            logger.debug("L1 route authority error (non-fatal): %s", exc)
            return preferred_provider, None, [], None

    def _consult_l2_supply(
        self,
        route_decision: Any,
    ) -> Tuple[Optional[str], Optional[str], bool]:
        """Consult the L2 supply authority to validate the route decision.

        Returns ``(supplied_provider, supplied_model, is_satisfied)``.  When
        the authority is unavailable or raises, returns ``(None, None, False)``
        so that callers fall back gracefully.
        """
        if route_decision is None:
            return None, None, False
        l2 = self._get_l2_supply_authority()
        if l2 is None:
            return None, None, False
        try:
            supply_state = self._build_backend_supply_state()
            if supply_state is None:
                # 供给状态问不出来 —— 跳过 L2，别把"没问出来"当成"没有供给"。
                return None, None, False
            result = l2.resolve_supply(route_decision, supply_state)
            logger.debug(
                "L2 supply authority: satisfied=%s supplied=%s/%s fallback=%s",
                result.is_satisfied,
                result.supplied_provider,
                result.supplied_model,
                result.fallback_legality,
            )
            if result.is_satisfied:
                return result.supplied_provider, result.supplied_model, True
            return None, None, False
        except Exception as exc:
            logger.debug("L2 supply authority error (non-fatal): %s", exc)
            return None, None, False

    def _build_backend_supply_state(self) -> Optional[Dict[str, Any]]:
        """Build a minimal supply-state dict from the backend's provider status.

        This feeds into :meth:`_consult_l2_supply` so that the L2 authority
        can reason about real provider availability.
        """
        # 这里是"确实没有后端"（确定的空）；except 那里是"没问出来"（None）。
        if self._backend is None:
            return {}
        try:
            status = self.get_status()
            providers_raw = status.get("providers", []) or []
            providers_dict: Dict[str, Any] = {}
            available: List[str] = []
            for p in providers_raw:
                if not isinstance(p, dict):
                    continue
                pid = p.get("name", "")
                if not pid:
                    continue
                health = str(p.get("status", "unknown")).lower()
                providers_dict[pid] = {
                    "provider_id": pid,
                    "health_status": health,
                    "available_models": [],
                }
                if health not in ("down", "unavailable", "error"):
                    available.append(pid)
            return {
                "providers": providers_dict,
                "available_provider_ids": available,
                "fallback_candidates": available,
            }
        except Exception as exc:  # noqa: BLE001
            # None = 没问出来；{} = 问过了确实没有。同值的话 L2 会把查询异常
            # 判成"无供给"→ is_satisfied=False → 静默降级，而后端可能好端端的。
            logger.warning("后端供给状态查询失败，本次跳过 L2 供给权威（不等于无供给）：%s", exc)
            return None

    def _enrich_l3_context(
        self,
        messages: List[Dict[str, Any]],
        task_type: str,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Enrich *messages* through the L3 cognitive context authority.

        Decomposes the existing message list into L3 request fields
        (system_prefix, conversation_history, user_message), passes them
        through :class:`~core.llm.context_authority.CognitiveContextAuthority`,
        and returns the assembled canonical message list.

        Returns the original *messages* unchanged on any error or when the
        assembly produces empty output, so callers are never left without a
        valid message list.
        """
        if not messages:
            return messages
        l3 = self._get_l3_context_authority()
        if l3 is None:
            return messages
        try:
            from core.llm.context_authority import CognitiveContextRequest

            system_prefix: Optional[str] = None
            history: List[Dict[str, Any]] = []

            for msg in messages:
                role = msg.get("role", "") if isinstance(msg, dict) else str(getattr(msg, "role", ""))
                content = msg.get("content", "") if isinstance(msg, dict) else str(getattr(msg, "content", ""))
                if role == "system" and system_prefix is None:
                    system_prefix = content
                else:
                    history.append(msg)

            # The last user-role message becomes the current user_message;
            # the remainder is treated as conversation history.
            user_message: Optional[str] = None
            for i in range(len(history) - 1, -1, -1):
                msg = history[i]
                role = msg.get("role", "") if isinstance(msg, dict) else str(getattr(msg, "role", ""))
                if role == "user":
                    user_message = msg.get("content", "") if isinstance(msg, dict) else str(getattr(msg, "content", ""))
                    history = history[:i] + history[i + 1 :]
                    break

            ctx_request = CognitiveContextRequest(
                task_type=task_type,
                system_prefix=system_prefix,
                conversation_history=history or None,
                tool_manifest=tools,
                user_message=user_message,
            )
            assembly = l3.assemble(ctx_request)
            if assembly.messages:
                logger.debug(
                    "L3 context authority enriched messages: %d → %d",
                    len(messages),
                    len(assembly.messages),
                )
                return list(assembly.messages)
        except Exception as exc:
            logger.debug("L3 context authority error (non-fatal): %s", exc)
        return messages

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
            provider_rates=self._provider_rates(),
            tool_capable=self._tool_capable(),
        )

    def _tool_capable(self) -> Dict[str, bool]:
        """``provider → 是否支持工具调用``,取自执行层 registry 的 ``supports_tools``。"""
        caps: Dict[str, bool] = {}
        providers = getattr(self._backend, "providers", None)
        if not isinstance(providers, dict):
            return caps
        for name, cfg in providers.items():
            val = getattr(cfg, "supports_tools", None)
            if isinstance(val, bool):
                caps[str(name)] = val
        return caps

    def _provider_rates(self) -> Dict[str, float]:
        """``provider → 每 1k token 单价(USD)``,取自执行层 registry 的真实报价。

        单价就在 ``core.multi_llm_router.PROVIDER_REGISTRY`` 每家的 ``cost_in`` /
        ``cost_out`` 里,经 ``ProviderConfig.cost_per_1k_input/output`` 暴露 ——
        统一层此前完全没用它,自己拿"预算上限"当"实际成本"(见
        ``_check_cost_budget`` 的说明)。

        取**输出单价**作为该家的代表单价:输出恒贵于输入,拿它跟上限比是保守的一侧,
        不会把超预算的一家漏判成便宜。单价为 0 的两类都合理地不被罚 —— ollama 本地
        确实免费,openrouter 这类聚合器写 0 是因为真实成本随所选底层模型浮动。
        """
        rates: Dict[str, float] = {}
        backend = self._backend
        providers = getattr(backend, "providers", None)
        if not isinstance(providers, dict):
            return rates
        for name, cfg in providers.items():
            out = getattr(cfg, "cost_per_1k_output", None)
            inp = getattr(cfg, "cost_per_1k_input", None)
            rate = out if out is not None else inp
            if rate is not None:
                try:
                    rates[str(name)] = float(rate)
                except (TypeError, ValueError):
                    continue
        return rates

    def _estimate_cost_per_1k(self, provider: str, task_type_str: str) -> Optional[float]:
        """该提供商的每 1k token 单价(USD);查不到返回 ``None``。

        原实现忽略 ``provider`` 参数,返回的是本任务 ``cost_budget`` 的**上限**,于是
        ``_check_cost_budget(上限, ...)`` 恒为真、成本层全程空转,而遥测里每家的成本
        都被记成同一个数(免费的 ollama 与 anthropic 一样贵)。

        返回 ``None`` 而不是 0.0 或上限,是为了让调用方能区分"这家免费"和"查不到单价"
        —— 两者都返回 0 的话,预算判定又会变成一句无意义的恒真。
        """
        return self._provider_rates().get(provider)

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def chat(self, request=None, *args, **kwargs) -> LLMResponse:
        """
        使用统一 LLMRequest 模型发起 LLM 对话请求（策略驱动 + 遥测 + 预算执行）。

        PR-6 扩展：在现有策略层之上按顺序调用 L3 / L1 / L2 认知权威，
        以便 model-selection 和 context-assembly 具有规范权威语义。
        所有权威调用均为非破坏性：若不可用或抛出异常，则静默降级为既有策略路径。

        Args:
            request: LLMRequest Pydantic 模型实例；或（向后兼容）messages 列表。

        向后兼容适配：大量调用方按 MultiLLMRouter 签名调用
        ``chat(messages, temperature=, max_tokens=, task_type=, provider=, model=, tools=)``。
        由于 _get_router() 默认返回 UnifiedLLMRouter，若不适配这些调用会因
        "unexpected keyword argument 'temperature'" 而在对话/任务全路径崩溃。
        这里做无损适配：仅当 request 非 LLMRequest 时才转换；带 tools 时委派给
        messages 兼容的 chat_with_tools()。原 LLMRequest 调用方完全不受影响。

        Returns:
            LLMResponse Pydantic 模型实例。
        """
        if not isinstance(request, LLMRequest):
            _messages = request if isinstance(request, list) else kwargs.pop("messages", None)
            if _messages is None:
                raise TypeError("chat() requires an LLMRequest or a messages list")
            _tools = kwargs.pop("tools", None)
            if _tools:
                # 带 tools → 委派到 messages 兼容的 chat_with_tools（provider/model/
                # task_type/temperature/max_tokens 仍在 kwargs 中透传）。
                return await self.chat_with_tools(messages=list(_messages), tools=_tools, **kwargs)
            _task_type = kwargs.pop("task_type", None) or "general"
            if not isinstance(_task_type, str):
                _task_type = getattr(_task_type, "value", str(_task_type))
            request = LLMRequest(
                messages=list(_messages),
                task_type=_task_type,
                preferred_provider=(kwargs.pop("provider", None) or kwargs.pop("preferred_provider", None)),
                temperature=float(kwargs.pop("temperature", 0.7)),
                max_tokens=int(kwargs.pop("max_tokens", 2048)),
            )
            kwargs.pop("model", None)  # LLMRequest 无显式 model 字段，由 provider/策略决定

        if self._backend is None:
            raise NoAvailableProviderError(task_type=request.task_type)

        task_type_str = request.task_type if isinstance(request.task_type, str) else request.task_type.value

        # ── PR-6 L3: Enrich messages through the canonical context authority ──
        enriched_messages = self._enrich_l3_context(
            messages=list(request.messages),
            task_type=task_type_str,
        )

        # ── PR-6 L1: Consult the canonical route authority ────────────────────
        l1_provider, _l1_model, l1_alternatives, l1_decision = self._consult_l1_route(
            task_type_str, request.preferred_provider
        )

        # ── PR-6 L2: Validate supply against the L1 route decision ───────────
        l2_provider, _l2_model, l2_satisfied = self._consult_l2_supply(l1_decision)

        # ── Determine effective preferred provider ────────────────────────────
        # Priority: L2 supplied → L1 route → original preferred
        effective_preferred: Optional[str] = (
            l2_provider if l2_satisfied and l2_provider else l1_provider if l1_provider else request.preferred_provider
        )

        # 策略：获取提供商优先顺序（保留既有 SLO / fallback 语义）
        provider_order, slo = self._get_provider_order(task_type_str, effective_preferred)

        start = time.monotonic()
        result = None
        used_provider = "unknown"
        is_fallback = False
        last_exc: Optional[Exception] = None

        # 若策略无可用提供商列表，回退到单次无偏好调用
        _effective_order: List[Optional[str]] = list(provider_order) if provider_order else [effective_preferred]

        # 尝试按策略顺序逐个提供商
        for idx, provider in enumerate(_effective_order):
            _preferred = provider or effective_preferred
            try:
                # MultiLLMRouter.chat 的强制提供商参数名是 `provider`;此前传
                # `preferred_provider=` 被 **kwargs 静默吞掉 → 本循环的策略优先
                # 顺序/逐级降级完全不生效,backend 每次都自主路由(且首轮即"成功",
                # used_provider 记录也失真)。
                result = await self._backend.chat(
                    messages=enriched_messages,
                    task_type=task_type_str,
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    provider=_preferred,
                )
                used_provider = provider or "unknown"
                is_fallback = idx > 0
                break
            except Exception as exc:
                logger.debug("Fallback triggered: %s", exc)
                last_exc = exc
                logger.warning(
                    "LLM provider %s failed (attempt %d/%d): %s",
                    provider,
                    idx + 1,
                    len(_effective_order),
                    exc,
                )
                continue

        if result is None:
            latency_ms = (time.monotonic() - start) * 1000
            self._telemetry.record("unknown", success=False, latency_ms=latency_ms, is_fallback=False)
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

        # 估算成本（基于 token 用量与该提供商的真实单价）
        total_tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else getattr(usage, "total_tokens", 0)
        cost_per_1k = self._estimate_cost_per_1k(provider_name, task_type_str)
        estimated_cost = (total_tokens / 1000.0) * cost_per_1k if cost_per_1k is not None else 0.0

        # 预算检查（超限记录警告，但不中断已完成的调用）
        if self._policy and cost_per_1k is not None:
            if not _check_cost_budget(cost_per_1k, task_type_str, self._policy):
                logger.warning(
                    "LLM cost budget exceeded for task_type=%s provider=%s cost_per_1k=%.4f ceiling=%.4f",
                    task_type_str,
                    provider_name,
                    cost_per_1k,
                    _cost_ceiling(task_type_str, self._policy),
                )
        elif self._policy:
            # 单价查不到时如实说"没评估",而不是当成通过 —— 后者正是原实现的毛病:
            # 判定永远为真,于是看日志的人以为预算一直守着。
            logger.debug(
                "Cost budget not evaluated for provider=%s (单价未知,未参与预算判定)",
                provider_name,
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
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        return True

    def get_default_model(self) -> str:
        """返回当前默认模型名称。"""
        if self._backend is None:
            return "gpt-4o"
        try:
            if hasattr(self._backend, "get_default_model"):
                return str(self._backend.get_default_model())
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
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

        PR-6 扩展：在策略层之前依次调用 L3 / L1 / L2 认知权威，以便
        model-selection 和 context-assembly 具有规范权威语义。
        所有权威调用均为非破坏性：若不可用或抛出异常，则静默降级为既有策略路径。

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

        task_type_str = task_type or "general"

        # ── PR-6 L3: Enrich messages through the canonical context authority ──
        enriched_messages = self._enrich_l3_context(
            messages=list(messages),
            task_type=task_type_str,
            tools=tools,
        )

        # ── PR-6 L1: Consult the canonical route authority ────────────────────
        l1_provider, _l1_model, _l1_alternatives, l1_decision = self._consult_l1_route(task_type_str, provider)

        # ── PR-6 L2: Validate supply against the L1 route decision ───────────
        l2_provider, _l2_model, l2_satisfied = self._consult_l2_supply(l1_decision)

        # ── Determine effective preferred provider ────────────────────────────
        # Priority: L2 supplied → L1 route → caller-specified
        effective_provider: Optional[str] = (
            l2_provider if l2_satisfied and l2_provider else l1_provider if l1_provider else provider
        )

        # 应用策略层：获取首选 provider（统一策略层职责）
        _provider_order, _slo = self._get_provider_order(
            task_type_str,
            preferred_provider=effective_provider,
        )
        # 【故障转移修复】此前只取 _provider_order[0] 强制成单一 provider,导致执行层
        # route() 返回它时 alternatives 为空、无从兜底 —— 工具路径中途失败即降级。
        # 现改为【沿策略顺序逐个尝试】:某候选抛异常或软降级(provider=="none")就换
        # 下一个,首个真成功即返回。强制 model 只对首选生效;换 provider 时让其自选默认
        # 模型(原 model 名对新 provider 无意义)。
        _candidates: List[Optional[str]] = (
            list(_provider_order) if _provider_order else ([effective_provider] if effective_provider else [None])
        )

        def _is_soft_failure(res: Any) -> bool:
            if res is None:
                return True
            p = getattr(res, "provider", None)
            return p is None or str(p).lower() in ("none", "")

        last_result: Any = None
        last_exc: Optional[Exception] = None
        for _idx, _cand in enumerate(_candidates):
            start = time.monotonic()
            try:
                result = await self._backend.chat(
                    messages=enriched_messages,
                    task_type=task_type_str,
                    provider=_cand,
                    model=model if _idx == 0 else None,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )
                latency_ms = (time.monotonic() - start) * 1000
                if _is_soft_failure(result):
                    # 软降级:该候选没答出来,记失败并换下一个。
                    last_result = result
                    self._telemetry.record(_cand or "unknown", success=False, latency_ms=latency_ms)
                    logger.debug("chat_with_tools 候选 %s 软降级,换下一个", _cand)
                    continue
                _actual_provider = getattr(result, "provider", _cand or "unknown")
                is_fallback = _idx > 0 or bool(_cand and _actual_provider != _cand)
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
                        "preferred_provider": _cand,
                        "actual_provider": _actual_provider,
                        "model": getattr(result, "model", "unknown"),
                        "latency_ms": round(latency_ms, 2),
                        "is_fallback": is_fallback,
                        "has_tools": bool(tools),
                    },
                )
                return result
            except Exception as exc:  # noqa: BLE001
                latency_ms = (time.monotonic() - start) * 1000
                last_exc = exc
                self._telemetry.record(_cand or "unknown", success=False, latency_ms=latency_ms)
                logger.debug("chat_with_tools 候选 %s 失败,换下一个: %s", _cand, exc)
                continue

        # 所有候选都没答出来:契约统一 —— 有软降级结果就返回它(与 MultiLLMRouter.chat
        # 的软返回一致,不抛给上层),否则(纯异常无软结果)才抛。
        if last_result is not None:
            return last_result
        raise last_exc if last_exc is not None else NoAvailableProviderError(task_type=task_type)

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
