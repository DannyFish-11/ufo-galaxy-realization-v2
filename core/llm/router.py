"""
core/llm/router.py — Multi-LLM Router (package entry point).

The canonical implementation lives in ``core.multi_llm_router``.
This module re-exports the router for the package-based import path.
"""
from core.multi_llm_router import MultiLLMRouter, TaskType, ProviderStatus, ProviderConfig  # noqa: F401

__all__ = ["MultiLLMRouter", "TaskType", "ProviderStatus", "ProviderConfig"]
