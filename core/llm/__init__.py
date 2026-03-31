"""
core/llm — Multi-LLM Router Package
=====================================

**Batch PR-5: Multi-LLM routing decomposition**

This package decomposes the multi-LLM routing layer into explicit, testable
submodules while preserving the public API of ``core.multi_llm_router``.

Submodule responsibilities
--------------------------
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

Authority sentinel
------------------
``LLM_ROUTING_PACKAGE_AUTHORITY = "core.llm"``

Backward compatibility
----------------------
All public symbols from ``core.multi_llm_router`` are re-exported here.

    from core.llm import MultiLLMRouter, TaskType, get_llm_router
"""
from __future__ import annotations

# ── package authority sentinel ────────────────────────────────────────────
LLM_ROUTING_PACKAGE_AUTHORITY: str = "core.llm"
"""Sentinel: core.llm is the canonical multi-LLM routing package.

Import to assert that a call site is using the decomposed LLM routing
package rather than reaching directly into core.multi_llm_router internals.
"""

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
    # main router
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
