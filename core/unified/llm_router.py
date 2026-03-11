"""
core/unified/llm_router.py
===========================
Galaxy 系统统一 LLM 路由器入口（单例门面）。

委托 core.multi_llm_router.MultiLLMRouter 处理实际的模型路由，
提供强类型接口（UnifiedLLMRequest / UnifiedLLMResponse）和结构化日志。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from .exceptions import LLMProviderError, LLMRouterError, NoAvailableProviderError
from .models import LLMRequest, LLMResponse, LLMTaskType

logger = logging.getLogger("Galaxy.Unified.LLMRouter")


class UnifiedLLMRouter:
    """
    统一 LLM 路由器门面（进程级单例）。

    公开 API：
        chat(request: LLMRequest) -> LLMResponse
        chat_raw(messages, task_type, ...) -> LLMResponse
        get_status() -> Dict[str, Any]
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
        self._initialized = True

        logger.info(
            "UnifiedLLMRouter initialized",
            extra={"event": "init", "backend": type(self._backend).__name__},
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
    # 公开接口
    # ------------------------------------------------------------------

    async def chat(self, request: LLMRequest) -> LLMResponse:
        """
        使用统一 LLMRequest 模型发起 LLM 对话请求。

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

        # 将 LLMTaskType 映射到 core.multi_llm_router 的 TaskType
        task_type_str = request.task_type if isinstance(request.task_type, str) else request.task_type.value

        start = time.monotonic()
        try:
            result = await self._backend.chat(
                messages=request.messages,
                task_type=task_type_str,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                preferred_provider=request.preferred_provider,
            )
        except Exception as exc:
            raise LLMProviderError(provider="multi_llm_router", reason=str(exc)) from exc

        latency_ms = (time.monotonic() - start) * 1000

        # 解析 result（multi_llm_router 返回 dict 或对象）
        if isinstance(result, dict):
            content = result.get("content") or result.get("text") or str(result)
            provider = result.get("provider", "unknown")
            model = result.get("model", "unknown")
            usage = result.get("usage", {})
        else:
            content = getattr(result, "content", str(result))
            provider = getattr(result, "provider", "unknown")
            model = getattr(result, "model", "unknown")
            usage = getattr(result, "usage", {})

        return LLMResponse(
            request_id=request.request_id,
            provider=provider,
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
        """返回 LLM 提供商状态信息。"""
        if self._backend is None:
            return {"available": False, "providers": []}

        try:
            if hasattr(self._backend, "get_status"):
                raw = self._backend.get_status()
                if isinstance(raw, dict):
                    return raw
            if hasattr(self._backend, "providers"):
                providers = [
                    {
                        "name": p.name if hasattr(p, "name") else str(p),
                        "status": p.status.value if hasattr(p, "status") else "unknown",
                    }
                    for p in self._backend.providers.values()
                ]
                return {"available": True, "providers": providers}
        except Exception as exc:
            logger.warning(
                "Failed to get LLM status",
                extra={"event": "status_error", "reason": str(exc)},
            )

        return {"available": True, "providers": []}


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
