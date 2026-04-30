"""
core/llm — Multi-LLM Router Package
=====================================

**Batch PR-5: Multi-LLM routing decomposition**
**L1: Unify LLM routing under a single router authority**
**L2: Canonicalize model supply truth, provider ordering, and fallback legality**
**L3: Canonicalize cognitive input assembly under a single context authority**
**L4: Close the final cognitive authority boundary**

This package decomposes the multi-LLM routing layer into explicit, testable
submodules while preserving the public API of ``core.multi_llm_router``.

Submodule responsibilities
--------------------------
route_authority.py
    **L1 canonical LLM routing authority**.  :class:`LLMRouteAuthority` is the
    single gate through which all LLM model-selection decisions must pass.
    Public factory: :func:`get_llm_route_authority`.
    Sentinel: ``LLM_ROUTE_AUTHORITY = "core.llm.route_authority.LLMRouteAuthority"``.

supply_authority.py
    **L2 canonical LLM supply authority**.  :class:`LLMSupplyAuthority` sits
    between the L1 routing authority and provider execution.  It enforces
    explicit provider ordering, explicit fallback legality, and produces a
    canonical :class:`SupplyResolutionResult` that makes it clear which
    provider/model was requested, which was supplied, and why any fallback
    was legal.  Public factory: :func:`get_llm_supply_authority`.
    Sentinel: ``LLM_SUPPLY_AUTHORITY = "core.llm.supply_authority.LLMSupplyAuthority"``.

context_authority.py
    **L3 canonical cognitive input assembly authority**.
    :class:`CognitiveContextAuthority` is the single gate through which all
    cognitive input assembly (prompt, memory, tools, runtime state, policy
    constraints, continuity context, execution metadata) must pass before
    provider formatting and model invocation.  Public factory:
    :func:`get_cognitive_context_authority`.
    Sentinel:
    ``LLM_CONTEXT_AUTHORITY = "core.llm.context_authority.CognitiveContextAuthority"``.

execution_authority.py
    **L4 canonical cognitive execution semantics authority**.
    :class:`CognitiveExecutionAuthority` is the single gate through which all
    LLM invocations must pass after L3 context assembly and L2 supply
    resolution.  It verifies that both upstream authorities were used, delegates
    raw execution to the provider adapter, and normalizes output under
    center-owned semantics.  Public factory:
    :func:`get_cognitive_execution_authority`.
    Sentinel:
    ``LLM_EXECUTION_AUTHORITY =
    "core.llm.execution_authority.CognitiveExecutionAuthority"``.

router.py
    Facade and authority sentinel for ``MultiLLMRouter``.  Public factory
    functions :func:`get_llm_router` and :func:`refresh_llm_router` live here.

policies.py
    Provider selection policy: ``TASK_ROUTING_PREFERENCES``, ``PROVIDER_MODEL_MAP``,
    and ``PolicyBasedSelector``.

failover.py
    Failover / circuit-breaker strategy: ``ProviderCircuitBreaker``,
    ``FailoverStrategy``, ``RetryPolicy``.

providers/
    Provider adapter classes: ``BaseProviderAdapter``, ``OpenAIAdapter``,
    ``AnthropicAdapter``, and all other provider-specific adapters.

Authority sentinels
-------------------
``LLM_ROUTE_AUTHORITY = "core.llm.route_authority.LLMRouteAuthority"``
    **Primary (L1)** — the single canonical LLM routing authority.  All
    model-selection decisions must pass through :class:`LLMRouteAuthority`
    before reaching provider supply.

``LLM_SUPPLY_AUTHORITY = "core.llm.supply_authority.LLMSupplyAuthority"``
    **Supply (L2)** — the single canonical LLM supply authority.  Sits between
    L1 route intent and provider execution.  Enforces explicit provider ordering
    and fallback legality.

``LLM_CONTEXT_AUTHORITY = "core.llm.context_authority.CognitiveContextAuthority"``
    **Context (L3)** — the single canonical cognitive input assembly authority.
    All prompt, memory, tool, runtime, continuity, and metadata inputs must be
    assembled through :class:`CognitiveContextAuthority` before provider
    formatting and execution.

``LLM_EXECUTION_AUTHORITY =
"core.llm.execution_authority.CognitiveExecutionAuthority"``
    **Execution (L4)** — the single canonical cognitive execution semantics
    authority.  All LLM invocations must pass through
    :class:`CognitiveExecutionAuthority` after L3 assembly and L2 supply
    resolution.  Providers contribute raw execution only; response
    normalization and output interpretation are performed here under
    center-owned semantics.

``LLM_ROUTING_PACKAGE_AUTHORITY = "core.llm"``
    Package-level sentinel (PR-5).

Backward compatibility
----------------------
All public symbols from ``core.multi_llm_router`` are re-exported here.

    from core.llm import MultiLLMRouter, TaskType, get_llm_router

For new code, prefer the canonical authority entry points:

    from core.llm import get_llm_route_authority, LLMRouteRequest
    from core.llm import get_llm_supply_authority, FallbackLegality
    from core.llm import get_cognitive_context_authority, CognitiveContextRequest
    from core.llm import get_cognitive_execution_authority, CognitiveExecutionRequest
"""
from __future__ import annotations

# ── package authority sentinel ────────────────────────────────────────────
LLM_ROUTING_PACKAGE_AUTHORITY: str = "core.llm"
"""Sentinel: core.llm is the canonical multi-LLM routing package.

Import to assert that a call site is using the decomposed LLM routing
package rather than reaching directly into core.multi_llm_router internals.
"""

# ── L1 canonical routing authority (primary entry point) ─────────────────
from core.llm.route_authority import (  # noqa: F401
    LLM_ROUTE_AUTHORITY,
    LLMRouteRequest,
    LLMRouteDecision,
    LLMRouteAuthority,
    get_llm_route_authority,
    refresh_llm_route_authority,
)

# ── L2 canonical supply authority ─────────────────────────────────────────
from core.llm.supply_authority import (  # noqa: F401
    LLM_SUPPLY_AUTHORITY,
    FallbackLegality,
    ProviderOrderingPolicy,
    SupplyResolutionStep,
    SupplyResolutionResult,
    LLMSupplyAuthority,
    get_llm_supply_authority,
    refresh_llm_supply_authority,
)

# ── L3 canonical cognitive input assembly authority ───────────────────────
from core.llm.context_authority import (  # noqa: F401
    LLM_CONTEXT_AUTHORITY,
    CognitiveContextRequest,
    CognitiveContextAssembly,
    CognitiveContextAuthority,
    get_cognitive_context_authority,
    refresh_cognitive_context_authority,
)

# ── L4 canonical cognitive execution semantics authority ──────────────────
from core.llm.execution_authority import (  # noqa: F401
    LLM_EXECUTION_AUTHORITY,
    CognitiveExecutionRequest,
    CognitiveExecutionResult,
    CognitiveExecutionAuthority,
    get_cognitive_execution_authority,
    refresh_cognitive_execution_authority,
)

# ── backward-compat re-exports from canonical implementation ─────────────
from core.multi_llm_router import (  # noqa: F401
    MultiLLMRouter,
    TaskType,
    ProviderStatus,
    ProviderConfig,
    RoutingDecision,
    LLMResponse,
    get_llm_router,
    refresh_llm_router,
    TASK_ROUTING_PREFERENCES,
    PROVIDER_MODEL_MAP,
)

__all__ = [
    # package sentinel
    "LLM_ROUTING_PACKAGE_AUTHORITY",
    # L1 canonical routing authority
    "LLM_ROUTE_AUTHORITY",
    "LLMRouteRequest",
    "LLMRouteDecision",
    "LLMRouteAuthority",
    "get_llm_route_authority",
    "refresh_llm_route_authority",
    # L2 canonical supply authority
    "LLM_SUPPLY_AUTHORITY",
    "FallbackLegality",
    "ProviderOrderingPolicy",
    "SupplyResolutionStep",
    "SupplyResolutionResult",
    "LLMSupplyAuthority",
    "get_llm_supply_authority",
    "refresh_llm_supply_authority",
    # L3 canonical cognitive input assembly authority
    "LLM_CONTEXT_AUTHORITY",
    "CognitiveContextRequest",
    "CognitiveContextAssembly",
    "CognitiveContextAuthority",
    "get_cognitive_context_authority",
    "refresh_cognitive_context_authority",
    # L4 canonical cognitive execution semantics authority
    "LLM_EXECUTION_AUTHORITY",
    "CognitiveExecutionRequest",
    "CognitiveExecutionResult",
    "CognitiveExecutionAuthority",
    "get_cognitive_execution_authority",
    "refresh_cognitive_execution_authority",
    # main router (legacy compat supply layer)
    "MultiLLMRouter",
    "get_llm_router",
    "refresh_llm_router",
    # task / provider types
    "TaskType",
    "ProviderStatus",
    "ProviderConfig",
    # response / routing types
    "RoutingDecision",
    "LLMResponse",
    # routing tables
    "TASK_ROUTING_PREFERENCES",
    "PROVIDER_MODEL_MAP",
]
