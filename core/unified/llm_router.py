"""
Galaxy - 统一 LLM Router
==========================

统一入口：`core.unified.llm_router.UnifiedLLMRouter`

设计：
- `UnifiedLLMRouter` 是对 `MultiLLMRouter` 的薄包装，暴露相同接口
- `get_unified_llm_router()` 返回全局单例
- 旧模块（`core/llm_manager.py`）委派至此处

使用方法：
    from core.unified.llm_router import UnifiedLLMRouter, get_unified_llm_router

    router = get_unified_llm_router()
    response = await router.chat_completion(messages=[...])
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Unified.LLMRouter")

# ───────────────────── 内部引用底层实现 ─────────────────────
from core.multi_llm_router import MultiLLMRouter, LLMResponse, get_llm_router


class UnifiedLLMRouter:
    """
    统一 LLM 路由器

    薄包装层，委派所有调用给 `MultiLLMRouter`。
    对外暴露与 `MultiLLMRouter` 完全兼容的接口，同时在日志中标记来源。

    所有调用方统一使用此类，底层实现保留在 `core.multi_llm_router`。
    """

    def __init__(self) -> None:
        self._router: MultiLLMRouter = get_llm_router()
        logger.info("UnifiedLLMRouter 初始化完成，委派至 MultiLLMRouter")

    # ──────────────── 核心接口 ────────────────

    def is_available(self) -> bool:
        """检查是否存在可用 LLM 提供商"""
        return self._router.is_available()

    def get_default_model(self) -> str:
        """返回当前默认模型名称"""
        return self._router.get_default_model()

    async def chat_completion(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        model_alias: Optional[str] = None,
        task_type: Optional[str] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        统一 Chat Completion 接口

        兼容 `MultiLLMRouter.chat_completion` 签名，可在调用侧无缝替换。
        """
        return await self._router.chat_completion(
            messages=messages,
            tools=tools,
            model_alias=model_alias,
            task_type=task_type,
            **kwargs,
        )

    async def chat(
        self,
        messages: List[Dict],
        task_type: Optional[str] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None,
        auto_failover: bool = True,
        **kwargs,
    ) -> LLMResponse:
        """
        统一 Chat 接口，智能路由 + 故障转移

        完全委派给 `MultiLLMRouter.chat`。
        """
        return await self._router.chat(
            messages=messages,
            task_type=task_type,
            provider=provider,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            auto_failover=auto_failover,
            **kwargs,
        )

    # ──────────────── 状态与管理 ────────────────

    def get_status(self) -> Dict[str, Any]:
        """获取路由器运行状态"""
        return self._router.get_status()

    def get_provider_status(self) -> list:
        """获取所有提供商状态列表"""
        return self._router.get_provider_status()

    async def health_check(self) -> Dict[str, str]:
        """对所有提供商执行健康检查"""
        return await self._router.health_check()

    async def refresh_providers(self) -> Dict[str, Any]:
        """刷新提供商列表（重新从环境变量发现）"""
        return await self._router.refresh_providers()

    async def close(self) -> None:
        """释放底层 HTTP 连接池"""
        await self._router.close()

    # ──────────────── 底层访问 ────────────────

    @property
    def underlying(self) -> MultiLLMRouter:
        """返回底层 MultiLLMRouter 实例（供需要直接访问的场景使用）"""
        return self._router


# ───────────────────── 全局单例 ─────────────────────

_unified_router_instance: Optional[UnifiedLLMRouter] = None


def get_unified_llm_router() -> UnifiedLLMRouter:
    """
    获取全局 UnifiedLLMRouter 单例

    Returns:
        UnifiedLLMRouter: 全局单例实例
    """
    global _unified_router_instance
    if _unified_router_instance is None:
        _unified_router_instance = UnifiedLLMRouter()
    return _unified_router_instance
