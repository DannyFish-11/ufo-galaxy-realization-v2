"""
core/llm — Multi-LLM Router Package
=====================================

This package provides the multi-LLM routing layer that supports intelligent
selection and fallback across multiple LLM providers.

The implementation is in ``core.multi_llm_router`` (the original module),
which is re-exported here for the new canonical package path.

Primary exports:
- MultiLLMRouter: Main router class
- TaskType: Task type classification enum
- ProviderStatus: Provider health status enum
- ProviderConfig: Provider configuration dataclass

For new code, prefer importing from ``core.llm`` rather than
``core.multi_llm_router`` directly.
"""
from core.multi_llm_router import (  # noqa: F401
    MultiLLMRouter,
    TaskType,
    ProviderStatus,
    ProviderConfig,
)

try:
    from core.multi_llm_router import __all__
except ImportError:
    __all__ = ["MultiLLMRouter", "TaskType", "ProviderStatus", "ProviderConfig"]
