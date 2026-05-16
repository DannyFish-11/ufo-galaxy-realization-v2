"""
LEGACY — core.llm_manager

此模块作为 legacy 兼容入口保留，内部委派到
``core.unified.llm_router.UnifiedLLMRouter``（进程级单例）。

迁移路径：
    旧：from core.llm_manager import LLMManager, llm_manager
    新：from core.unified import get_unified_llm_router
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

logger = logging.getLogger("Galaxy.LLMManager.Legacy")


# ---------------------------------------------------------------------------
# 保留数据模型以维持向后兼容（部分测试直接引用）
# ---------------------------------------------------------------------------


class ModelConfig(BaseModel):
    provider: str = "oneapi"
    model_name: str
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    max_tokens: int = 4096
    temperature: float = 0.7


class TokenUsage(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    total_cost: float
    timestamp: str


# ---------------------------------------------------------------------------
# LLMManager — legacy 委派层
# ---------------------------------------------------------------------------


class LLMManager:
    """
    Legacy LLM 管理器（委派到 UnifiedLLMRouter）。

    保持原有方法签名兼容，所有实际逻辑委派到
    ``core.unified.llm_router.UnifiedLLMRouter`` 单例。
    """

    def __init__(self, config_path: str = "config.json") -> None:
        self._config_path = config_path
        self._router = self._get_router()
        logger.info(
            "LLMManager (legacy) initialized — delegating to UnifiedLLMRouter",
            extra={"event": "init"},
        )

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    @staticmethod
    def _get_router() -> Any:
        """返回进程级 UnifiedLLMRouter 单例。"""
        from core.unified.llm_router import get_unified_llm_router  # lazy import
        return get_unified_llm_router()

    @property
    def _backend(self) -> Any:
        """后端 MultiLLMRouter（UnifiedLLMRouter 的底层实现）。"""
        return self._router._backend  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # 公开 API（保持原有签名）
    # ------------------------------------------------------------------

    def get_client(self) -> Any:
        """
        获取可用 LLM 客户端。

        委派到后端适配器的第一个可用客户端。
        如无可用提供商则抛出 ValueError。
        """
        if self._backend is None:
            raise ValueError(
                "无可用 LLM。请配置以下任一:\n"
                "1. config.json → oneapi_base_url + oneapi_key\n"
                "2. .env → OPENAI_API_KEY / DEEPSEEK_API_KEY / GROQ_API_KEY 等"
            )
        # MultiLLMRouter 将 adapters 挂在 .adapters 字典，返回第一个
        adapters = getattr(self._backend, "adapters", {})
        if adapters:
            first = next(iter(adapters.values()))
            client = getattr(first, "client", None)
            if client is not None:
                return client
        raise ValueError("无可用 LLM 客户端，请检查 API Key 配置。")

    def get_default_model(self) -> str:
        """返回当前默认模型名。"""
        return self._router.get_default_model()

    async def chat_completion(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        model_alias: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        """
        统一 Chat Completion（OpenAI 兼容格式）。

        委派到 UnifiedLLMRouter.chat_completion()。
        """
        return await self._router.chat_completion(
            messages=messages,
            tools=tools,
            model_alias=model_alias,
            **kwargs,
        )

    async def simple_chat(
        self,
        user_message: str,
        system_prompt: Optional[str] = None,
    ) -> str:
        """简单对话 — 返回纯文本回复。"""
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})
        resp = await self.chat_completion(messages=messages)
        return resp.choices[0].message.content or ""

    def reload(self) -> None:
        """热重载：刷新底层路由器的提供商配置。"""
        import asyncio

        backend = self._backend
        if backend is not None and hasattr(backend, "refresh_providers"):
            try:
                try:
                    loop = asyncio.get_running_loop()
                    # There is a running event loop — schedule as a task.
                    loop.create_task(backend.refresh_providers())
                except RuntimeError:
                    # No running event loop — create a new one for this call.
                    asyncio.run(backend.refresh_providers())
            except Exception as exc:
                logger.warning(
                    "LLMManager reload failed",
                    extra={"event": "reload_error", "reason": str(exc)},
                )
        logger.info("LLMManager reload triggered", extra={"event": "reload"})

    def is_available(self) -> bool:
        """检查是否有可用的 LLM 提供商。"""
        return self._router.is_available()

    def get_provider_status(self) -> List[Dict[str, Any]]:
        """获取所有 Provider 状态（保持原有 list 格式兼容性）。"""
        status = self._router.get_status()
        raw_providers = status.get("providers", [])

        # MultiLLMRouter 的 providers 是 dict {name: config}，需转换为 list
        if isinstance(raw_providers, dict):
            return [
                {
                    "provider": name,
                    "model": info.get("default_model", "unknown") if isinstance(info, dict) else getattr(info, "default_model", "unknown"),
                    "source": "multi_llm_router",
                    "active": True,
                    "status": info.get("status", "healthy") if isinstance(info, dict) else getattr(getattr(info, "status", None), "value", "healthy"),
                }
                for name, info in raw_providers.items()
            ]
        if isinstance(raw_providers, list):
            return raw_providers
        return []

    def get_usage_summary(self) -> Dict[str, Any]:
        """获取 Token 使用统计（从底层 backend 聚合）。"""
        backend = self._backend
        if backend is not None and hasattr(backend, "get_usage_summary"):
            try:
                return backend.get_usage_summary()  # type: ignore[return-value]
            except Exception:
                pass
        return {"total_cost": 0.0, "by_model": {}, "history_count": 0}


# ---------------------------------------------------------------------------
# 模块级单例（供 `from core.llm_manager import llm_manager` 使用）
# ---------------------------------------------------------------------------

llm_manager: LLMManager = LLMManager()

