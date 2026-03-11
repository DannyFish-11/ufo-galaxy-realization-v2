"""
Galaxy - core.unified 统一入口包
==================================

对外暴露统一的 LLM Router 和 Config Manager 入口。

LLM Router:
    from core.unified import get_unified_llm_router, UnifiedLLMRouter

Config Manager:
    from core.unified import get_unified_config, UnifiedConfigManager
"""

from core.unified.llm_router import UnifiedLLMRouter, get_unified_llm_router
from core.unified.config_manager import UnifiedConfigManager, get_unified_config

__all__ = [
    "UnifiedLLMRouter",
    "get_unified_llm_router",
    "UnifiedConfigManager",
    "get_unified_config",
]
