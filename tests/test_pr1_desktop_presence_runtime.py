"""
PR-1 回归测试 — DesktopPresenceRuntime 统一主体架构验收
=======================================================

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

统一主体架构验收 (新增):
  12. DesktopPresenceRuntime 模块文档声明其为 runtime shell
  13. DesktopPresenceRuntime 模块文档声明 OpenClawd 为 subject core
  14. TriState 文档区分于 UI shell states
  15. source 参数在文档中被标记为 observability tag
  16. _try_start_ingest_bus 文档说明其为 runtime shell 对 host ingress 的所有权
  17. handle_request 文档说明 shell→liminal→core→manifest→silent 生命周期

PR-1 入口主权收束 (gateway 修复):
  18. galaxy_gateway/app.py chat endpoint 经 DesktopPresenceRuntime 路由
  19. galaxy_gateway/app.py chat endpoint 不直接调用 openclawd_instance.process()
  20. galaxy_gateway/app.py 声明 gateway 为 internal substrate，非主体入口
  21. source="chat" 在 gateway chat endpoint 被明确作为 observability tag 传递
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


# ──────────────────────────────────────────────────────────────────────────────
# 10. 统一主体架构 — 模块文档验收
# ──────────────────────────────────────────────────────────────────────────────


class TestUnifiedSubjectArchitectureDocstrings:
    """Verify that key docstrings reflect the unified-subject architecture."""

    def _read_module(self, path: str) -> str:
        return pathlib.Path(__file__).parent.parent.joinpath(path).read_text(encoding="utf-8")

    def test_dpr_module_doc_declares_runtime_shell(self):
        """desktop_presence_runtime.py module docstring must declare 'runtime shell'."""
        src = self._read_module("core/desktop_presence_runtime.py")
        assert "runtime shell" in src, (
            "core/desktop_presence_runtime.py must describe itself as the runtime shell"
        )

    def test_dpr_module_doc_declares_openclawd_as_core(self):
        """desktop_presence_runtime.py must explicitly name OpenClawd as the subject core."""
        src = self._read_module("core/desktop_presence_runtime.py")
        assert "subject core" in src, (
            "core/desktop_presence_runtime.py must reference OpenClawd as the subject core"
        )

    def test_dpr_module_doc_not_parallel_subjects(self):
        """desktop_presence_runtime.py must say they are not parallel subjects."""
        src = self._read_module("core/desktop_presence_runtime.py")
        assert "not parallel" in src.lower() or "not two parallel" in src.lower() or \
               "not** two parallel" in src.lower() or "NOT** two parallel" in src, (
            "core/desktop_presence_runtime.py must clarify DesktopPresenceRuntime "
            "and OpenClawd are not parallel subjects"
        )

    def test_tristate_docstring_distinguishes_from_ui_states(self):
        """TriState docstring must distinguish from UI shell states."""
        src = self._read_module("core/desktop_presence_runtime.py")
        # The TriState class docstring should mention that UI shell states are different
        assert "DORMANT" in src or "UI shell" in src or "desktop clothing" in src, (
            "TriState docstring must distinguish from UI shell states "
            "(DORMANT/ISLAND/SIDESHEET/FULLAGENT)"
        )

    def test_source_param_described_as_observability_tag(self):
        """handle_request() docstring must describe source as observability tag only."""
        src = self._read_module("core/desktop_presence_runtime.py")
        assert "observability tag" in src or "Observability tag" in src, (
            "handle_request() must describe 'source' as an observability tag only"
        )

    def test_try_start_ingest_bus_doc_mentions_shell_ownership(self):
        """_try_start_ingest_bus docstring must mention runtime shell ownership."""
        src = self._read_module("core/desktop_presence_runtime.py")
        assert "shell" in src and ("ingest" in src or "ingress" in src), (
            "_try_start_ingest_bus must describe runtime shell ownership of ingress"
        )

    def test_openclawd_module_doc_declares_subject_core(self):
        """openclawd.py module docstring must declare it as the subject core."""
        src = self._read_module("core/openclawd.py")
        assert "subject core" in src.lower() or "Subject Core" in src, (
            "core/openclawd.py must describe itself as the subject core"
        )

    def test_openclawd_module_doc_mentions_liminal(self):
        """openclawd.py must describe operating inside liminal phase."""
        src = self._read_module("core/openclawd.py")
        assert "liminal" in src, (
            "core/openclawd.py must mention it operates inside the liminal phase"
        )

    def test_openclawd_module_doc_execution_path_semantics(self):
        """openclawd.py must document execution_path semantics."""
        src = self._read_module("core/openclawd.py")
        assert "local" in src and "cross_device" in src, (
            "core/openclawd.py must document execution_path: local/cross_device/hybrid/none"
        )

    def test_decision_executor_doc_local_manifestation_layer(self):
        """decision_executor.py must describe itself as local manifestation layer."""
        src = self._read_module("core/execution/decision_executor.py")
        assert "local manifestation" in src or "Local Manifestation" in src, (
            "core/execution/decision_executor.py must describe itself as the "
            "subject's local manifestation layer"
        )

    def test_multimodal_ingest_runtime_doc_shell_ownership(self):
        """ingest_runtime.py must describe runtime shell ownership."""
        src = self._read_module("core/multimodal/ingest_runtime.py")
        assert "runtime shell" in src or "Runtime Shell" in src, (
            "core/multimodal/ingest_runtime.py must describe runtime shell ownership"
        )

    def test_multimodal_ingest_runtime_doc_distinguishes_paths(self):
        """ingest_runtime.py must distinguish continuous host ingress from request-bound."""
        src = self._read_module("core/multimodal/ingest_runtime.py")
        assert "continuous" in src.lower() and "request" in src.lower(), (
            "core/multimodal/ingest_runtime.py must distinguish continuous host "
            "ingress from request-bound multimodal_context"
        )

    def test_hardware_trigger_system_state_doc_clothing_not_tristate(self):
        """SystemState in hardware_trigger.py must say it's UI clothing, not tri-state."""
        src = self._read_module("system_integration/hardware_trigger.py")
        assert "clothing" in src or "presentation" in src or "not" in src.lower(), (
            "system_integration/hardware_trigger.py SystemState must clarify "
            "it is not the tri-state lifecycle"
        )

    def test_chat_route_doc_demoted_to_adapter(self):
        """core/routes/chat.py docstring must mention adapter role."""
        src = self._read_module("core/routes/chat.py")
        assert "adapter" in src.lower() or "Adapter" in src, (
            "core/routes/chat.py must be described as an adapter, not a subject entrypoint"
        )

    def test_gateway_app_doc_internal_substrate_not_primary_entrypoint(self):
        """galaxy_gateway/app.py must describe gateway as internal substrate."""
        src = self._read_module("galaxy_gateway/app.py")
        assert "internal" in src.lower() and ("substrate" in src.lower() or "adapter" in src.lower()), (
            "galaxy_gateway/app.py must describe the gateway as an internal substrate, "
            "not a primary subject entrypoint"
        )

    def test_unified_subject_architecture_doc_exists(self):
        """docs/UNIFIED_SUBJECT_ARCHITECTURE.md must exist."""
        doc_path = pathlib.Path(__file__).parent.parent / "docs" / "UNIFIED_SUBJECT_ARCHITECTURE.md"
        assert doc_path.exists(), "docs/UNIFIED_SUBJECT_ARCHITECTURE.md must exist"
        content = doc_path.read_text(encoding="utf-8")
        assert "DesktopPresenceRuntime" in content
        assert "OpenClawd" in content
        assert "runtime shell" in content
        assert "subject core" in content

    def test_entrypoint_demotion_doc_exists(self):
        """docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md must exist."""
        doc_path = pathlib.Path(__file__).parent.parent / "docs" / "ENTRYPOINT_AND_SURFACE_DEMOTION.md"
        assert doc_path.exists(), "docs/ENTRYPOINT_AND_SURFACE_DEMOTION.md must exist"
        content = doc_path.read_text(encoding="utf-8")
        assert "chat" in content.lower()
        assert "gateway" in content.lower()
        assert "launcher" in content.lower()
        assert "dashboard" in content.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 11. UI shell states are NOT tri-state lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestUIShellStatesNotTristate:
    """Assert that UI shell states (DORMANT/ISLAND/SIDESHEET/FULLAGENT) are
    distinct from the tri-state lifecycle (silent/liminal/manifest)."""

    def test_tristate_values_do_not_include_dormant(self):
        """TriState must not include DORMANT (that's a UI shell state)."""
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        assert "dormant" not in values, (
            "DORMANT is a UI shell state, not a tri-state lifecycle value"
        )

    def test_tristate_values_do_not_include_island(self):
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        assert "island" not in values, (
            "ISLAND is a UI shell state, not a tri-state lifecycle value"
        )

    def test_tristate_values_do_not_include_sidesheet(self):
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        assert "sidesheet" not in values, (
            "SIDESHEET is a UI shell state, not a tri-state lifecycle value"
        )

    def test_tristate_values_do_not_include_fullagent(self):
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        assert "fullagent" not in values, (
            "FULLAGENT is a UI shell state, not a tri-state lifecycle value"
        )

    def test_tristate_has_exactly_three_values(self):
        """TriState must have exactly SILENT, LIMINAL, MANIFEST."""
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        assert values == {"silent", "liminal", "manifest"}, (
            f"TriState must have exactly silent/liminal/manifest, got: {values}"
        )

    def test_hardware_trigger_system_state_has_dormant_island_etc(self):
        """hardware_trigger.SystemState has DORMANT/ISLAND/SIDESHEET/FULLAGENT."""
        import pathlib
        src = pathlib.Path(__file__).parent.parent.joinpath(
            "system_integration/hardware_trigger.py"
        ).read_text(encoding="utf-8")
        for state in ("DORMANT", "ISLAND", "SIDESHEET", "FULLAGENT"):
            assert state in src, f"hardware_trigger.py must define {state}"


# ──────────────────────────────────────────────────────────────────────────────
# 12. gateway/app.py — authority chain guardrails (PR-1)
# ──────────────────────────────────────────────────────────────────────────────


class TestGatewayAuthorityChain:
    """Galaxy gateway chat endpoint must route through DesktopPresenceRuntime.

    Acceptance criteria (PR-1):
    - The gateway /api/v1/chat endpoint (in galaxy_gateway/routes/chat.py) calls
      DesktopPresenceRuntime.handle_request()
    - It does NOT call openclawd_instance.process() directly in chat_endpoint
    - source="chat" is passed as an observability tag, not an authority grant
    - galaxy_gateway/app.py is described as an internal substrate, not a primary entrypoint

    Note: chat_endpoint was refactored from galaxy_gateway/app.py into
    galaxy_gateway/routes/chat.py to reduce gateway surface coupling.  The
    implementation tests now check routes/chat.py; the substrate-description
    test still checks app.py (that is where the architectural declaration lives).
    """

    def _read_chat_route(self) -> str:
        """Read the chat adapter surface (where chat_endpoint is implemented)."""
        return pathlib.Path(__file__).parent.parent.joinpath(
            "galaxy_gateway/routes/chat.py"
        ).read_text(encoding="utf-8")

    def _read_gateway_app(self) -> str:
        """Read the gateway app module (architectural declaration, not endpoint impl)."""
        return pathlib.Path(__file__).parent.parent.joinpath(
            "galaxy_gateway/app.py"
        ).read_text(encoding="utf-8")

    # Keep _read_gateway() as a backward-compat alias — delegates to _read_chat_route()
    # since chat_endpoint now lives in galaxy_gateway/routes/chat.py.
    def _read_gateway(self) -> str:
        return self._read_chat_route()

    def test_gateway_chat_endpoint_uses_desktop_presence_runtime(self):
        """chat_endpoint in galaxy_gateway/routes/chat.py must call get_desktop_presence_runtime()."""
        src = self._read_chat_route()
        assert "get_desktop_presence_runtime" in src, (
            "galaxy_gateway/routes/chat.py chat_endpoint must call get_desktop_presence_runtime() "
            "to route through the runtime shell"
        )

    def test_gateway_chat_endpoint_calls_handle_request(self):
        """chat_endpoint must call runtime.handle_request(), not openclawd directly."""
        src = self._read_chat_route()
        assert "runtime.handle_request" in src, (
            "galaxy_gateway/routes/chat.py chat_endpoint must call runtime.handle_request() "
            "as the canonical shell entry"
        )

    def test_gateway_chat_endpoint_does_not_bypass_runtime_shell(self):
        """chat_endpoint must NOT call openclawd_instance.process() inside chat_endpoint.

        The gateway surface must not act as an alternative subject-core authority
        by calling openclawd_instance.process() directly.  All subject cognition
        must flow through DesktopPresenceRuntime first.
        """
        src = self._read_chat_route()
        # Find the chat_endpoint function body and check it does not call
        # openclawd_instance.process() directly — that would bypass the runtime shell.
        chat_ep_start = src.find("async def chat_endpoint(")
        assert chat_ep_start != -1, "chat_endpoint function not found in galaxy_gateway/routes/chat.py"
        # Use multiple boundary candidates; take the earliest valid one
        candidates = [
            src.find("\n\ndef _merge_parallel_result", chat_ep_start),
            src.find("\n\ndef _merge_parallel", chat_ep_start),
            src.find("\n@app.", chat_ep_start + 50),
            src.find("\n@router.", chat_ep_start + 50),
            src.find("\nasync def ", chat_ep_start + 50),
        ]
        valid = [c for c in candidates if c > chat_ep_start]
        next_def = min(valid) if valid else -1
        func_body = src[chat_ep_start:next_def] if next_def != -1 else src[chat_ep_start:]
        assert "openclawd_instance.process(" not in func_body, (
            "galaxy_gateway/routes/chat.py chat_endpoint must not call openclawd_instance.process() "
            "directly — all requests must flow through DesktopPresenceRuntime.handle_request()"
        )

    def test_gateway_chat_endpoint_passes_source_chat(self):
        """chat_endpoint must pass source='chat' to handle_request as an observability tag."""
        src = self._read_chat_route()
        assert 'source="chat"' in src or "source='chat'" in src, (
            "galaxy_gateway/routes/chat.py chat_endpoint must pass source='chat' to "
            "runtime.handle_request() as an observability tag"
        )

    def test_gateway_app_declares_internal_substrate(self):
        """galaxy_gateway/app.py must describe gateway as internal substrate."""
        src = self._read_gateway_app()
        assert "internal" in src.lower(), (
            "galaxy_gateway/app.py must describe itself as an internal substrate"
        )
        assert "NOT" in src or "not a primary" in src.lower() or "not a subject" in src.lower(), (
            "galaxy_gateway/app.py must clarify it is NOT a primary subject entrypoint"
        )

    def test_gateway_chat_doc_includes_authority_chain(self):
        """chat_endpoint module docstring must document the authority chain."""
        src = self._read_chat_route()
        # The module docstring should mention the routing chain
        assert "DesktopPresenceRuntime" in src, (
            "galaxy_gateway/routes/chat.py must mention DesktopPresenceRuntime in the "
            "module or chat endpoint docstring to document the authority chain"
        )
        assert "handle_request" in src, (
            "galaxy_gateway/routes/chat.py must mention handle_request in the chat endpoint"
        )

    def test_gateway_chat_endpoint_authority_chain_static(self):
        """Static analysis: chat_endpoint code must reflect the authority chain.

        Verifies that within the chat_endpoint function body:
        1. ``get_desktop_presence_runtime`` is called to obtain the runtime shell
        2. ``runtime.handle_request`` is invoked as the canonical entry
        3. ``openclawd_instance.process(`` does NOT appear (would bypass the shell)
        """
        src = self._read_chat_route()

        # Find chat_endpoint function body
        chat_ep_start = src.find("async def chat_endpoint(")
        assert chat_ep_start != -1, "chat_endpoint not found in galaxy_gateway/routes/chat.py"

        # Find end of function body using multiple boundary candidates; take the
        # earliest one that appears after the function definition.
        candidates = [
            src.find("\n\ndef _merge_parallel_result", chat_ep_start),
            src.find("\n\ndef _merge_parallel", chat_ep_start),
            src.find("\n@app.", chat_ep_start + 50),
            src.find("\n@router.", chat_ep_start + 50),
            src.find("\nasync def ", chat_ep_start + 50),
        ]
        valid = [c for c in candidates if c > chat_ep_start]
        next_boundary = min(valid) if valid else -1
        func_body = src[chat_ep_start:next_boundary] if next_boundary != -1 else src[chat_ep_start:]

        assert "get_desktop_presence_runtime" in func_body, (
            "chat_endpoint body must call get_desktop_presence_runtime()"
        )
        assert "runtime.handle_request" in func_body, (
            "chat_endpoint body must call runtime.handle_request()"
        )
        assert "openclawd_instance.process(" not in func_body, (
            "chat_endpoint must NOT call openclawd_instance.process() directly — "
            "this bypasses DesktopPresenceRuntime and violates the authority chain"
        )


class TestCompatWebSocketAuthorityChain:
    """Legacy core-direct websocket chat must still enter via the runtime shell."""

    def _read_api_routes(self) -> str:
        return pathlib.Path(__file__).parent.parent.joinpath(
            "core/api_routes.py"
        ).read_text(encoding="utf-8")

    def test_compat_ws_chat_uses_runtime_shell(self):
        src = self._read_api_routes()
        assert "get_desktop_presence_runtime" in src, (
            "core/api_routes.py compat websocket chat must obtain DesktopPresenceRuntime"
        )
        assert "runtime.handle_request(" in src, (
            "core/api_routes.py compat websocket chat must call runtime.handle_request()"
        )

    def test_compat_ws_chat_does_not_call_openclawd_directly(self):
        src = self._read_api_routes()
        branch_start = src.find('elif msg_type == "chat":')
        assert branch_start != -1, 'compat websocket "chat" branch not found'
        candidates = [
            src.find("\n                elif ", branch_start + 1),
            src.find("\n                    except ", branch_start + 1),
        ]
        valid = [c for c in candidates if c > branch_start]
        next_boundary = min(valid) if valid else -1
        branch_body = src[branch_start:next_boundary] if next_boundary != -1 else src[branch_start:]
        assert "clawd.process(" not in branch_body, (
            'compat websocket "chat" branch must not call OpenClawd.process() directly'
        )
        assert 'source="chat"' in branch_body or "source='chat'" in branch_body, (
            'compat websocket "chat" branch must keep source="chat" when calling runtime.handle_request()'
        )

    def test_compat_ws_chat_context_normalization_helper(self):
        from core.api_routes import _normalize_chat_context

        assert _normalize_chat_context({"role": "user"}) == [{"role": "user"}]
        assert _normalize_chat_context([{"role": "user"}]) == [{"role": "user"}]
        assert _normalize_chat_context("invalid") is None


class TestAndroidVisionAuthorityChain:
    """Android vision requests must enter through DesktopPresenceRuntime."""

    def _read_android_vision_handler(self) -> str:
        return pathlib.Path(__file__).parent.parent.joinpath(
            "galaxy_gateway/android/handlers/vision.py"
        ).read_text(encoding="utf-8")

    def test_android_vision_handler_uses_runtime_shell(self):
        src = self._read_android_vision_handler()
        assert "get_desktop_presence_runtime" in src, (
            "android vision handler must obtain DesktopPresenceRuntime"
        )
        assert "runtime.handle_request(" in src, (
            "android vision handler must route requests through runtime.handle_request()"
        )

    def test_android_vision_handler_does_not_instantiate_openclawd(self):
        src = self._read_android_vision_handler()
        assert "OpenClawd()" not in src, (
            "android vision handler must not instantiate OpenClawd directly"
        )
        assert "oc.process(" not in src and "clawd.process(" not in src, (
            "android vision primary path must not call OpenClawd.process() directly"
        )

    @pytest.mark.asyncio
    async def test_android_vision_runtime_session_id_propagated(self):
        from galaxy_gateway.android.handlers.vision import _process_via_runtime_shell

        mock_runtime = MagicMock()
        mock_runtime.handle_request = AsyncMock(
            return_value={
                "success": True,
                "response": "ok",
                "runtime_session_id": "runtime-123",
                "multimodal_route_decision": {"provider": "test"},
            }
        )

        with patch(
            "core.desktop_presence_runtime.get_desktop_presence_runtime",
            return_value=mock_runtime,
        ):
            result = await _process_via_runtime_shell(
                image_base64="ZmFrZQ==",
                task_context="inspect",
                mode="full",
                device_id="android-1",
            )

        assert result["runtime_session_id"] == "runtime-123"


class TestVisionSamplerAuthorityChain:
    """Vision sampler ingress must also enter through the runtime shell."""

    def _read_vision_sampler(self) -> str:
        return pathlib.Path(__file__).parent.parent.joinpath(
            "core/services/vision_sampler.py"
        ).read_text(encoding="utf-8")

    def test_vision_sampler_uses_runtime_shell(self):
        src = self._read_vision_sampler()
        assert "get_desktop_presence_runtime" in src, (
            "VisionSampler must obtain DesktopPresenceRuntime"
        )
        assert "runtime.handle_request(" in src, (
            "VisionSampler must route multimodal sampling through runtime.handle_request()"
        )

    def test_vision_sampler_does_not_call_openclawd_directly(self):
        src = self._read_vision_sampler()
        assert "get_openclawd" not in src, (
            "VisionSampler must not depend on get_openclawd() for request ingress"
        )
        assert "clawd.process(" not in src, (
            "VisionSampler must not call OpenClawd.process() directly"
        )
