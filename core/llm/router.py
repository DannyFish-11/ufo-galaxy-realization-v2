"""
core/llm/router.py — Multi-LLM Router Facade
=============================================

**Batch PR-5: Multi-LLM routing decomposition**

This module is the canonical facade entry point for the multi-LLM routing
layer.  It re-exports ``MultiLLMRouter`` and the public factory functions
:func:`get_llm_router` and :func:`refresh_llm_router` from the canonical
implementation in ``core.multi_llm_router``.

Authority sentinel
------------------
``LLM_ROUTER_AUTHORITY = "core.llm.router"``

All downstream code should import from ``core.llm.router`` (or the package
root ``core.llm``) rather than reaching directly into
``core.multi_llm_router``.
"""
from __future__ import annotations

# ── module authority sentinel ─────────────────────────────────────────────
LLM_ROUTER_AUTHORITY: str = "core.llm.router"
"""Sentinel: core.llm.router is the canonical multi-LLM router facade.

Import this symbol to declare that a call site is using the canonical
multi-LLM routing entry point.
"""

# ── re-export from canonical implementation ───────────────────────────────
from core.multi_llm_router import (  # noqa: F401
    MultiLLMRouter,
    TaskType,
    ProviderStatus,
    ProviderConfig,
    RoutingDecision,
    LLMResponse,
    get_llm_router,
    refresh_llm_router,
)

__all__ = [
    "LLM_ROUTER_AUTHORITY",
    "MultiLLMRouter",
    "TaskType",
    "ProviderStatus",
    "ProviderConfig",
    "RoutingDecision",
    "LLMResponse",
    "get_llm_router",
    "refresh_llm_router",
]
