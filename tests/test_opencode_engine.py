"""
tests/test_opencode_engine.py
==============================

OpenCodeEngine 单元测试 - 覆盖成功路径和失败路径。

运行方式：
    python -m pytest tests/test_opencode_engine.py -v --tb=short
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# 预先导入 core.multi_llm_router，使其进入 sys.modules，
# 这样 patch("core.multi_llm_router.get_llm_router") 才能正确解析目标路径。
import core.multi_llm_router as _mlr  # noqa: F401
from core.multi_llm_router import LLMResponse, ProviderStatus


# ---------------------------------------------------------------------------
# 辅助 fixture
# ---------------------------------------------------------------------------


def _make_engine():
    """创建一个全新的 OpenCodeEngine 实例（不读取环境变量）。"""
    # 清空相关 env vars，确保测试隔离
    os.environ.pop("OPENCODE_PROVIDER", None)
    os.environ.pop("OPENCODE_MODEL", None)
    os.environ.pop("OPENCODE_TIMEOUT", None)
    from core.opencode_engine import OpenCodeEngine
    return OpenCodeEngine()


def _make_llm_response(content: str, provider: str = "openai", model: str = "gpt-4o") -> LLMResponse:
    """构造一个 MultiLLMRouter LLMResponse 对象。"""
    return LLMResponse(
        content=content,
        provider=provider,
        model=model,
        input_tokens=100,
        output_tokens=200,
        latency_ms=500.0,
    )


# ---------------------------------------------------------------------------
# _extract_code 辅助函数测试
# ---------------------------------------------------------------------------


class TestExtractCode:
    def test_extracts_fenced_block(self):
        from core.opencode_engine import _extract_code
        raw = "Here is the code:\n```python\nprint('hello')\n```\nDone."
        assert _extract_code(raw, "python") == "print('hello')"

    def test_returns_raw_when_no_fence(self):
        from core.opencode_engine import _extract_code
        raw = "print('hello')"
        assert _extract_code(raw, "python") == "print('hello')"

    def test_extracts_first_block_only(self):
        from core.opencode_engine import _extract_code
        raw = "```python\nx = 1\n```\n```python\ny = 2\n```"
        assert _extract_code(raw, "python") == "x = 1"


# ---------------------------------------------------------------------------
# generate_code_async - 成功路径
# ---------------------------------------------------------------------------


class TestGenerateCodeAsyncSuccess:

    @pytest.mark.asyncio
    async def test_returns_real_code_not_todo(self):
        """LLM 提供真实代码时，结果不含 TODO 占位符。"""
        engine = _make_engine()
        fake_code = "```python\ndef hello():\n    return 'world'\n```"
        llm_resp = _make_llm_response(fake_code)

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {
                "openai": MagicMock(status=MagicMock(value="healthy"))
            }
            # 让 status != DOWN
            router.providers["openai"].status = ProviderStatus.HEALTHY
            router.chat = AsyncMock(return_value=llm_resp)
            router.get_status = MagicMock(return_value={"total_providers": 1, "healthy_providers": 1})
            mock_get_router.return_value = router

            result = await engine.generate_code_async(
                prompt="write a hello function",
                language="python",
            )

        assert result.success is True
        assert "TODO" not in result.code
        assert "hello" in result.code
        assert result.provider == "openai"
        assert result.model == "gpt-4o"
        assert result.latency_ms > 0
        assert result.error == ""

    @pytest.mark.asyncio
    async def test_respects_configured_provider_and_model(self):
        """generate_code_async 应将 provider/model 传递给 router.chat。"""
        engine = _make_engine()
        engine._configured_provider = "deepseek"
        engine._configured_model = "deepseek-coder"
        llm_resp = _make_llm_response("```python\nx=1\n```", provider="deepseek", model="deepseek-coder")

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {"deepseek": MagicMock(status=ProviderStatus.HEALTHY)}
            router.chat = AsyncMock(return_value=llm_resp)
            router.get_status = MagicMock(return_value={"total_providers": 1, "healthy_providers": 1})
            mock_get_router.return_value = router

            result = await engine.generate_code_async(prompt="x=1", language="python")

        assert result.success is True
        # 确认传入的 provider/model 是配置值
        call_kwargs = router.chat.call_args
        assert call_kwargs.kwargs.get("provider") == "deepseek"
        assert call_kwargs.kwargs.get("model") == "deepseek-coder"

    @pytest.mark.asyncio
    async def test_result_appended_to_history(self):
        engine = _make_engine()
        llm_resp = _make_llm_response("```python\npass\n```")

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {"openai": MagicMock(status=ProviderStatus.HEALTHY)}
            router.chat = AsyncMock(return_value=llm_resp)
            router.get_status = MagicMock(return_value={"total_providers": 1, "healthy_providers": 1})
            mock_get_router.return_value = router

            assert len(engine.generation_history) == 0
            await engine.generate_code_async(prompt="pass", language="python")

        assert len(engine.generation_history) == 1


# ---------------------------------------------------------------------------
# generate_code_async - 失败路径
# ---------------------------------------------------------------------------


class TestGenerateCodeAsyncFailure:

    @pytest.mark.asyncio
    async def test_no_providers_returns_clear_error(self):
        """没有配置任何 API Key 时，返回明确错误而非 TODO 代码。"""
        engine = _make_engine()

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {}  # 空，无提供商
            mock_get_router.return_value = router

            result = await engine.generate_code_async(
                prompt="write a function",
                language="python",
            )

        assert result.success is False
        assert result.code == ""
        assert "API Key" in result.error or "提供商" in result.error
        assert "TODO" not in result.code

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self):
        """LLM 超时时，返回带明确错误信息的失败结果。"""
        engine = _make_engine()
        engine._timeout = 0.001  # 极短超时

        async def _slow_chat(*args, **kwargs):
            await asyncio.sleep(0.1)  # 远超超时

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {"openai": MagicMock(status=ProviderStatus.HEALTHY)}
            router.chat = _slow_chat
            mock_get_router.return_value = router

            result = await engine.generate_code_async(
                prompt="write something",
                language="python",
            )

        assert result.success is False
        assert "超时" in result.error or "timeout" in result.error.lower()

    @pytest.mark.asyncio
    async def test_llm_exception_returns_error(self):
        """LLM 抛出异常时，返回带明确错误信息的失败结果（不抛出）。"""
        engine = _make_engine()

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {"openai": MagicMock(status=ProviderStatus.HEALTHY)}
            router.chat = AsyncMock(side_effect=RuntimeError("API error"))
            mock_get_router.return_value = router

            result = await engine.generate_code_async(
                prompt="write something",
                language="python",
            )

        assert result.success is False
        assert "API error" in result.error

    @pytest.mark.asyncio
    async def test_all_providers_down_returns_error(self):
        """所有提供商状态为 DOWN 时，返回明确错误。"""
        engine = _make_engine()

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {"openai": MagicMock(status=ProviderStatus.DOWN)}
            mock_get_router.return_value = router

            result = await engine.generate_code_async(
                prompt="write something",
                language="python",
            )

        assert result.success is False
        assert result.code == ""


# ---------------------------------------------------------------------------
# configure()
# ---------------------------------------------------------------------------


class TestConfigure:

    def test_valid_provider_accepted(self):
        engine = _make_engine()
        result = engine.configure(model="gpt-4o", provider="openai")
        assert result["success"] is True
        assert engine._configured_provider == "openai"
        assert engine._configured_model == "gpt-4o"

    def test_invalid_provider_rejected(self):
        engine = _make_engine()
        result = engine.configure(model="unknown-model", provider="nonexistent_provider")
        assert result["success"] is False
        assert "不支持" in result["error"] or "nonexistent_provider" in result["error"]

    def test_configure_does_not_mutate_on_failure(self):
        engine = _make_engine()
        engine._configured_provider = "openai"
        engine._configured_model = "gpt-4o"
        engine.configure(model="x", provider="bad_provider")
        # 配置应未被修改
        assert engine._configured_provider == "openai"
        assert engine._configured_model == "gpt-4o"


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------


class TestGetStatus:

    def test_status_includes_required_fields(self):
        engine = _make_engine()

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {"openai": MagicMock(status=ProviderStatus.HEALTHY, default_model="gpt-4o")}
            router.get_status = MagicMock(return_value={"total_providers": 1, "healthy_providers": 1})
            mock_get_router.return_value = router

            status = engine.get_status()

        required = {
            "installed", "generation_count", "configured_provider",
            "configured_model", "effective_provider", "effective_model",
            "available_providers", "provider_count", "healthy_provider_count",
            "timeout_seconds",
        }
        assert required.issubset(status.keys())

    def test_available_providers_excludes_down(self):
        engine = _make_engine()

        with patch("core.multi_llm_router.get_llm_router") as mock_get_router:
            router = MagicMock()
            router.providers = {
                "openai": MagicMock(status=ProviderStatus.HEALTHY, default_model="gpt-4o"),
                "anthropic": MagicMock(status=ProviderStatus.DOWN, default_model="claude-3"),
            }
            router.get_status = MagicMock(return_value={"total_providers": 2, "healthy_providers": 1})
            mock_get_router.return_value = router

            status = engine.get_status()

        assert "openai" in status["available_providers"]
        assert "anthropic" not in status["available_providers"]
