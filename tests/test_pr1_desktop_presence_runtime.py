"""
PR-1 回归测试 — DesktopPresenceRuntime 控制面收束验收
===================================================

验收清单：
  1. DesktopPresenceRuntime 可导入并实例化
  2. get_desktop_presence_runtime() 返回单例
  3. TriState 枚举包含 SILENT / LIMINAL / MANIFEST
  4. RuntimeSession 生命周期正确（状态推进、elapsed_ms）
  5. handle_request() 经 chat/openclawd 源路由到 OpenClawd
  6. handle_request() 返回结果中包含 runtime_session_id、tristate、entrypoint_source
  7. handle_request() 最终 tristate 为 SILENT（即使执行出错）
  8. chat.py 通过 DesktopPresenceRuntime 路由（不直接调用 clawd.process）
  9. OpenClawd.process() 接受并传播 runtime_session_id
  10. ContinuumOrchestrator.run() 接受 runtime_session_id 参数
  11. e2e_orchestrator.process_user_input() 经 DesktopPresenceRuntime 路由
"""

import asyncio
import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────────────────
# 1. 模块可导入
# ──────────────────────────────────────────────────────────────────────────────


class TestModuleImport:
    """DesktopPresenceRuntime 模块可以无副作用导入。"""

    def test_import_desktop_presence_runtime(self):
        from core.desktop_presence_runtime import (
            DesktopPresenceRuntime,
            TriState,
            RuntimeSession,
            get_desktop_presence_runtime,
        )
        assert DesktopPresenceRuntime is not None
        assert TriState is not None
        assert RuntimeSession is not None
        assert get_desktop_presence_runtime is not None

    def test_tristate_values(self):
        from core.desktop_presence_runtime import TriState
        assert TriState.SILENT.value == "silent"
        assert TriState.LIMINAL.value == "liminal"
        assert TriState.MANIFEST.value == "manifest"


# ──────────────────────────────────────────────────────────────────────────────
# 2. 单例
# ──────────────────────────────────────────────────────────────────────────────


class TestSingleton:
    """get_desktop_presence_runtime() 应返回同一实例。"""

    def test_singleton_identity(self):
        from core.desktop_presence_runtime import get_desktop_presence_runtime
        a = get_desktop_presence_runtime()
        b = get_desktop_presence_runtime()
        assert a is b


# ──────────────────────────────────────────────────────────────────────────────
# 3. RuntimeSession 状态推进
# ──────────────────────────────────────────────────────────────────────────────


class TestRuntimeSession:
    """RuntimeSession 状态推进与计时逻辑。"""

    def test_initial_state_is_silent(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        s = RuntimeSession(source="chat")
        assert s.tristate == TriState.SILENT

    def test_advance_records_transitions(self):
        from core.desktop_presence_runtime import RuntimeSession, TriState
        s = RuntimeSession(source="chat")
        s.advance(TriState.LIMINAL)
        s.advance(TriState.MANIFEST)
        s.advance(TriState.SILENT)
        states = [t[0] for t in s.transitions]
        assert states == [TriState.LIMINAL, TriState.MANIFEST, TriState.SILENT]

    def test_elapsed_ms_is_non_negative(self):
        from core.desktop_presence_runtime import RuntimeSession
        s = RuntimeSession(source="e2e")
        assert s.elapsed_ms() >= 0.0

    def test_runtime_session_id_is_hex_string(self):
        from core.desktop_presence_runtime import RuntimeSession
        s = RuntimeSession(source="chat")
        assert isinstance(s.runtime_session_id, str)
        assert len(s.runtime_session_id) == 32  # uuid4().hex


# ──────────────────────────────────────────────────────────────────────────────
# 4. handle_request() — 基本协议
# ──────────────────────────────────────────────────────────────────────────────


class TestHandleRequestProtocol:
    """handle_request() 必须返回带有 runtime 观测字段的 dict。"""

    def _make_openclawd_result(self):
        return {
            "success": True,
            "response": "OK",
            "intent": "chat",
            "trace_id": "mock-trace",
            "metadata": {"session_id": "s1", "mode": "chat_only", "model": "gpt-4o"},
        }

    @pytest.mark.asyncio
    async def test_handle_request_returns_runtime_session_id(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime()

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=self._make_openclawd_result())
            mock_get.return_value = mock_clawd

            result = await rt.handle_request(message="hello", source="chat")

        assert "runtime_session_id" in result
        assert isinstance(result["runtime_session_id"], str)
        assert len(result["runtime_session_id"]) == 32

    @pytest.mark.asyncio
    async def test_handle_request_final_tristate_is_silent(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime, TriState
        rt = DesktopPresenceRuntime()

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=self._make_openclawd_result())
            mock_get.return_value = mock_clawd

            result = await rt.handle_request(message="hello", source="chat")

        assert result["tristate"] == TriState.SILENT.value

    @pytest.mark.asyncio
    async def test_handle_request_entrypoint_source(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime()

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=self._make_openclawd_result())
            mock_get.return_value = mock_clawd

            result = await rt.handle_request(message="hello", source="openclawd")

        assert result["entrypoint_source"] == "openclawd"

    @pytest.mark.asyncio
    async def test_handle_request_error_still_returns_silent(self):
        """Even when the handler raises, final tristate must be SILENT."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime, TriState
        rt = DesktopPresenceRuntime()

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(side_effect=RuntimeError("boom"))
            mock_get.return_value = mock_clawd

            result = await rt.handle_request(message="hello", source="chat")

        assert result["tristate"] == TriState.SILENT.value
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_runtime_session_id_forwarded_to_openclawd(self):
        """handle_request() must pass runtime_session_id to OpenClawd.process()."""
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime()
        captured = {}

        async def _mock_process(**kwargs):
            captured["runtime_session_id"] = kwargs.get("runtime_session_id")
            return {
                "success": True,
                "response": "OK",
                "trace_id": "t",
                "metadata": {},
            }

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = _mock_process
            mock_get.return_value = mock_clawd

            result = await rt.handle_request(message="hi", source="chat")

        assert captured["runtime_session_id"] == result["runtime_session_id"]


# ──────────────────────────────────────────────────────────────────────────────
# 5. chat.py — 使用 DesktopPresenceRuntime
# ──────────────────────────────────────────────────────────────────────────────


class TestChatRouteUsesRuntime:
    """chat.py 必须通过 DesktopPresenceRuntime 路由，不直接调用 clawd.process。"""

    def test_chat_py_imports_runtime(self):
        chat_file = pathlib.Path(__file__).parent.parent / "core" / "routes" / "chat.py"
        source = chat_file.read_text(encoding="utf-8")
        assert "desktop_presence_runtime" in source, (
            "core/routes/chat.py 必须导入 DesktopPresenceRuntime"
        )
        assert "get_desktop_presence_runtime" in source, (
            "core/routes/chat.py 必须调用 get_desktop_presence_runtime()"
        )

    def test_chat_py_uses_runtime_handle_request(self):
        chat_file = pathlib.Path(__file__).parent.parent / "core" / "routes" / "chat.py"
        source = chat_file.read_text(encoding="utf-8")
        assert "runtime.handle_request" in source, (
            "core/routes/chat.py 必须调用 runtime.handle_request()"
        )

    def test_chat_py_includes_runtime_session_id_in_response(self):
        chat_file = pathlib.Path(__file__).parent.parent / "core" / "routes" / "chat.py"
        source = chat_file.read_text(encoding="utf-8")
        assert "runtime_session_id" in source, (
            "core/routes/chat.py 必须在响应中包含 runtime_session_id"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 6. OpenClawd — 接受 runtime_session_id
# ──────────────────────────────────────────────────────────────────────────────


class TestOpenClawdAcceptsRuntimeSessionId:
    """OpenClawd.process() 必须接受 runtime_session_id 参数。"""

    def test_process_signature_has_runtime_session_id(self):
        import inspect
        from core.openclawd import OpenClawd
        sig = inspect.signature(OpenClawd.process)
        assert "runtime_session_id" in sig.parameters, (
            "OpenClawd.process() 必须接受 runtime_session_id 参数"
        )

    def test_process_runtime_session_id_default_is_none(self):
        import inspect
        from core.openclawd import OpenClawd
        sig = inspect.signature(OpenClawd.process)
        param = sig.parameters["runtime_session_id"]
        assert param.default is None


# ──────────────────────────────────────────────────────────────────────────────
# 7. ContinuumOrchestrator — 接受 runtime_session_id
# ──────────────────────────────────────────────────────────────────────────────


class TestContinuumOrchestratorAcceptsRuntimeSessionId:
    """ContinuumOrchestrator.run() 必须接受 runtime_session_id 关键字参数。"""

    def test_run_signature_has_runtime_session_id(self):
        """Check the source file directly to avoid heavy numpy/audio imports."""
        orchestrator_file = (
            pathlib.Path(__file__).parent.parent / "core" / "continuum" / "orchestrator.py"
        )
        source = orchestrator_file.read_text(encoding="utf-8")
        assert "runtime_session_id" in source, (
            "core/continuum/orchestrator.py: run() 必须接受 runtime_session_id 参数"
        )

    def test_run_docstring_mentions_runtime_session_id(self):
        orchestrator_file = (
            pathlib.Path(__file__).parent.parent / "core" / "continuum" / "orchestrator.py"
        )
        source = orchestrator_file.read_text(encoding="utf-8")
        assert "DesktopPresenceRuntime" in source, (
            "core/continuum/orchestrator.py 应在文档中提及 DesktopPresenceRuntime"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 8. e2e_orchestrator — 经 DesktopPresenceRuntime 路由
# ──────────────────────────────────────────────────────────────────────────────


class TestE2EOrchestratorUsesRuntime:
    """e2e_orchestrator.process_user_input() 应通过 DesktopPresenceRuntime 路由。"""

    def test_e2e_orchestrator_imports_runtime(self):
        e2e_file = pathlib.Path(__file__).parent.parent / "core" / "e2e_orchestrator.py"
        source = e2e_file.read_text(encoding="utf-8")
        assert "desktop_presence_runtime" in source, (
            "core/e2e_orchestrator.py 必须通过 DesktopPresenceRuntime 路由"
        )

    @pytest.mark.asyncio
    async def test_process_user_input_returns_runtime_session_id(self):
        """process_user_input() 最终结果应包含 runtime_session_id。"""
        from core.e2e_orchestrator import process_user_input

        rt_result = {
            "success": True,
            "response": "OK",
            "reply": "OK",
            "session_id": "s1",
            "mode": "chat",
            "data": {},
            "devices_notified": [],
            "runtime_session_id": "test-runtime-abc",
            "tristate": "silent",
            "entrypoint_source": "e2e",
            "trace_id": "test-trace",
        }

        with patch("core.desktop_presence_runtime.get_desktop_presence_runtime") as mock_get_rt:
            mock_rt = MagicMock()
            mock_rt.handle_request = AsyncMock(return_value=rt_result)
            mock_get_rt.return_value = mock_rt

            result = await process_user_input(message="hello", device_id="pc_01")

        assert "runtime_session_id" in result
        assert result["runtime_session_id"] == "test-runtime-abc"


# ──────────────────────────────────────────────────────────────────────────────
# 9. 未知 source 的 guardrail — 回退到 OpenClawd
# ──────────────────────────────────────────────────────────────────────────────


class TestUnknownSourceGuardrail:
    """未知 source 应回退到 OpenClawd（而非静默丢弃请求）。"""

    @pytest.mark.asyncio
    async def test_unknown_source_falls_back_to_openclawd(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        rt = DesktopPresenceRuntime()
        called_with_source = {}

        async def _mock_process(**kwargs):
            return {
                "success": True,
                "response": "fallback OK",
                "trace_id": "t",
                "metadata": {},
            }

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = _mock_process
            mock_get.return_value = mock_clawd

            result = await rt.handle_request(message="hi", source="unknown_source_xyz")

        assert result["success"] is True
        # The entrypoint_source should reflect the caller's declared source
        assert result["entrypoint_source"] == "unknown_source_xyz"
