"""
core/llm/providers — LLM Provider Adapters Sub-package
=======================================================

**Batch PR-5: Multi-LLM routing decomposition**

This sub-package re-exports all provider adapter classes from
``core.multi_llm_router`` under the canonical package-based import path.

Authority sentinel
------------------
``LLM_PROVIDERS_AUTHORITY = "core.llm.providers"``

Exported adapters
-----------------
``BaseProviderAdapter``   — abstract base class for all provider adapters
``OpenAIAdapter``         — OpenAI-compatible adapter (GPT-4o, o1, …)
``AnthropicAdapter``      — Anthropic Claude adapter
``DeepSeekAdapter``       — DeepSeek (OpenAI-compat) adapter
``GroqAdapter``           — Groq (OpenAI-compat) adapter
``OllamaAdapter``         — Ollama (local LLM) adapter
``GoogleAdapter``         — Google Gemini adapter
``GrokAdapter``           — xAI Grok adapter
``MistralAdapter``        — Mistral AI adapter
``QwenAdapter``           — Alibaba Qwen adapter
``ZhipuAdapter``          — Zhipu GLM adapter
``MoonshotAdapter``       — Moonshot Kimi adapter
``PerplexityAdapter``     — Perplexity AI adapter

For new code, prefer importing from ``core.llm.providers`` rather than
``core.multi_llm_router`` directly.
"""
from __future__ import annotations

from core.multi_llm_router import (  # noqa: F401
    BaseProviderAdapter,
    OpenAIAdapter,
    AnthropicAdapter,
    OllamaAdapter,
    ProviderConfig,
    ProviderStatus,
    LLMResponse,
    RoutingDecision,
)

# L1 收口:此前每个 OpenAI 兼容提供商都有一个空壳适配器子类(DeepSeekAdapter 等,
# 全是 `class X(OpenAIAdapter): pass`),已按【协议→适配器工厂】收敛掉。这里把旧类名
# 保留为 OpenAIAdapter 的别名,任何历史 `from core.llm.providers import DeepSeekAdapter`
# 仍照常可用(__all__ 里这些名字也依旧解析),只是不再是独立的空壳类。
DeepSeekAdapter = OpenAIAdapter
GroqAdapter = OpenAIAdapter
GoogleAdapter = OpenAIAdapter
GrokAdapter = OpenAIAdapter
MistralAdapter = OpenAIAdapter
QwenAdapter = OpenAIAdapter
ZhipuAdapter = OpenAIAdapter
MoonshotAdapter = OpenAIAdapter
PerplexityAdapter = OpenAIAdapter

# ── sub-package authority sentinel ────────────────────────────────────────
LLM_PROVIDERS_AUTHORITY: str = "core.llm.providers"
"""Sentinel: core.llm.providers is the canonical LLM provider adapters module.

Import this symbol to assert that a call site is using the decomposed
provider adapters module rather than reaching directly into
core.multi_llm_router.
"""

__all__ = [
    "LLM_PROVIDERS_AUTHORITY",
    # base
    "BaseProviderAdapter",
    # concrete adapters
    "OpenAIAdapter",
    "AnthropicAdapter",
    "DeepSeekAdapter",
    "GroqAdapter",
    "OllamaAdapter",
    "GoogleAdapter",
    "GrokAdapter",
    "MistralAdapter",
    "QwenAdapter",
    "ZhipuAdapter",
    "MoonshotAdapter",
    "PerplexityAdapter",
    # config / response types
    "ProviderConfig",
    "ProviderStatus",
    "LLMResponse",
    "RoutingDecision",
]
