"""
tests/unit/runtime/test_openclawd_subject_core.py
=========================================

PR-3: Refine OpenClawd as the Subject Decision Core.

Validates that:

Architecture / Role
  1. OpenClawd module docstring identifies it as the "subject core".
  2. OpenClawd class docstring identifies it as "subject core" / "decision core".
  3. DesktopPresenceRuntime sits above OpenClawd as the outer runtime shell.
  4. AgentKernel is embedded *inside* OpenClawd, not a separate authority.
  5. OpenClawd is NOT described as a surface authority or transport substrate.

Delegation Boundary Helpers (PR-3 additions)
  6. ``_delegate_local_manifestation`` exists on OpenClawd.
  7. ``_delegate_single_remote`` exists on OpenClawd.
  8. ``_delegate_multi_device_orchestration`` exists on OpenClawd.
  9. ``_delegate_local_manifestation`` returns ``delegation_point="local"``.
 10. ``_delegate_single_remote`` returns ``delegation_point="single_remote"``.
 11. ``_delegate_multi_device_orchestration`` returns
     ``delegation_point="multi_device_orchestration"``.

Execution-Path Branching
 12. ``_determine_execution_path`` returns ``"local"`` for local-only execution.
 13. ``_determine_execution_path`` returns ``"cross_device"`` when
     ``cross_device_dispatched=True``.
 14. ``_determine_execution_path`` returns ``"hybrid"`` when both local and
     cross-device ran.
 15. ``_determine_execution_path`` returns ``"none"`` for no-op execution.
 16. ``_determine_execution_path`` returns ``"cross_device"`` when
     ``entry_mode="cross_device"`` even with no local action.

Dispatch Agent Routing (delegation branch selection)
 17. ``_dispatch_agent`` routes to local manifestation when no device specified.
 18. ``_dispatch_agent`` routes to single-remote when a non-local device is given.
 19. ``_dispatch_agent`` routes to local manifestation when a local device id is given.

Process Response Guardrails
 20. ``process()`` always returns ``execution_path`` in the response.
 21. ``process()`` always returns ``execution_result`` in the response.
 22. ``process()`` via kernel path returns ``delegation_point="local"`` in metadata.

Structural / Regression Guardrails
 23. OpenClawd does NOT inherit from any surface/API class.
 24. OpenClawd module does not import from ``core/routes`` (not a surface).
"""

from __future__ import annotations

import inspect
import asyncio
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_openclawd():
    """Return a minimal OpenClawd with heavy init suppressed."""
    with patch("core.openclawd.OpenClawd.__init__", return_value=None):
        from core.openclawd import OpenClawd
        oc = OpenClawd.__new__(OpenClawd)
    oc._continuum_orchestrator = None
    oc._decision_executor = None
    oc._request_count = 0
    oc._error_count = 0
    oc._session_memory = {}
    oc._cancel_registry = set()
    oc._router = None
    oc._kernel = None
    oc._current_trace_id = None
    oc._current_session_id = None
    oc._current_device_id = ""
    oc._tool_permission_checker = None
    oc._node_actions_cache = {}
    oc._node_id_to_key = {}
    return oc


# ---------------------------------------------------------------------------
# 1-5: Architecture / Role
# ---------------------------------------------------------------------------

class TestArchitecturalRole:
    """OpenClawd must be identified as the subject/decision core."""

    def test_module_docstring_contains_subject_core(self):
        """Module-level docstring must name OpenClawd as subject core."""
        import core.openclawd as mod
        doc = mod.__doc__ or ""
        assert "subject core" in doc.lower() or "subject core" in doc, (
            "core/openclawd.py module docstring must mention 'subject core'"
        )

    def test_class_docstring_contains_subject_core_or_decision_core(self):
        """OpenClawd class docstring must name it as subject core / decision core."""
        from core.openclawd import OpenClawd
        doc = OpenClawd.__doc__ or ""
        assert "subject core" in doc.lower() or "decision core" in doc.lower(), (
            "OpenClawd class docstring must mention 'subject core' or 'decision core'"
        )

    def test_class_docstring_mentions_delegation_boundaries(self):
        """Class docstring must name at least two of the delegation boundaries."""
        from core.openclawd import OpenClawd
        doc = OpenClawd.__doc__ or ""
        found = sum(1 for term in ("local manifestation", "single remote", "multi-device") if term in doc.lower())
        assert found >= 2, (
            f"OpenClawd class docstring should name delegation boundaries; found {found}/3"
        )

    def test_desktop_presence_runtime_is_outer_shell(self):
        """DesktopPresenceRuntime module must describe itself as outer shell."""
        import core.desktop_presence_runtime as dpr_mod
        doc = dpr_mod.__doc__ or ""
        assert "shell" in doc.lower() or "outer" in doc.lower(), (
            "desktop_presence_runtime module should identify itself as 'shell' or 'outer'"
        )

    def test_openclawd_not_described_as_surface_authority(self):
        """OpenClawd docstring must clarify it is NOT a surface authority.

        The docstring should explicitly distinguish OpenClawd from a surface
        authority (i.e., say it is NOT one), which is stronger than just not
        mentioning it.
        """
        from core.openclawd import OpenClawd
        doc = (OpenClawd.__doc__ or "").lower()
        # The docstring should explicitly say OpenClawd is NOT a surface
        # authority / transport substrate.  Both phrases appear in the PR-3
        # docstring as negations ("it is not the transport substrate",
        # "not a surface authority").
        has_negation = (
            "not the transport substrate" in doc
            or "not a surface authority" in doc
            or "not a parallel entrypoint" in doc
        )
        assert has_negation, (
            "OpenClawd class docstring must explicitly say it is NOT a "
            "surface authority / transport substrate"
        )

    def test_agent_kernel_is_embedded_inside_openclawd(self):
        """AgentKernel should be lazy-initialised inside OpenClawd (not separate)."""
        from core.openclawd import OpenClawd
        # The _kernel attribute exists on OpenClawd instances — it is the
        # embedded cognition sub-layer, not a separate authority.
        oc = _make_openclawd()
        assert hasattr(oc, "_kernel"), (
            "OpenClawd must have a '_kernel' attribute (embedded AgentKernel)"
        )


# ---------------------------------------------------------------------------
# 6-11: Delegation boundary helpers exist and return correct metadata
# ---------------------------------------------------------------------------

class TestDelegationBoundaryHelpers:
    """PR-3 delegation helpers must exist and stamp delegation_point."""

    def test_delegate_local_manifestation_exists(self):
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_delegate_local_manifestation"), (
            "OpenClawd must have '_delegate_local_manifestation' delegation helper"
        )
        assert asyncio.iscoroutinefunction(OpenClawd._delegate_local_manifestation), (
            "_delegate_local_manifestation must be an async method"
        )

    def test_delegate_single_remote_exists(self):
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_delegate_single_remote"), (
            "OpenClawd must have '_delegate_single_remote' delegation helper"
        )
        assert asyncio.iscoroutinefunction(OpenClawd._delegate_single_remote), (
            "_delegate_single_remote must be an async method"
        )

    def test_delegate_multi_device_orchestration_exists(self):
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_delegate_multi_device_orchestration"), (
            "OpenClawd must have '_delegate_multi_device_orchestration' delegation helper"
        )
        assert asyncio.iscoroutinefunction(OpenClawd._delegate_multi_device_orchestration), (
            "_delegate_multi_device_orchestration must be an async method"
        )

    @pytest.mark.asyncio
    async def test_delegate_local_manifestation_stamps_delegation_point(self):
        """`_delegate_local_manifestation` must stamp `delegation_point='local'`."""
        oc = _make_openclawd()
        oc.handle_agent_task = AsyncMock(return_value={
            "success": True,
            "response": "done",
            "metadata": {},
        })
        result = await oc._delegate_local_manifestation(
            message="test",
            intent=None,
            session_id="s1",
            trace_id="t1",
        )
        assert result.get("metadata", {}).get("delegation_point") == "local", (
            f"Expected delegation_point='local', got: {result.get('metadata', {})}"
        )

    @pytest.mark.asyncio
    async def test_delegate_single_remote_stamps_delegation_point(self):
        """`_delegate_single_remote` must stamp `delegation_point='single_remote'`."""
        oc = _make_openclawd()
        oc._dispatch_remote_agent = AsyncMock(return_value={
            "success": True,
            "response": "remote done",
            "metadata": {},
        })
        result = await oc._delegate_single_remote(
            message="test",
            intent=None,
            device_id="phone_01",
            session_id="s1",
            trace_id="t1",
        )
        assert result.get("metadata", {}).get("delegation_point") == "single_remote", (
            f"Expected delegation_point='single_remote', got: {result.get('metadata', {})}"
        )

    @pytest.mark.asyncio
    async def test_delegate_multi_device_orchestration_stamps_delegation_point(self):
        """`_delegate_multi_device_orchestration` must stamp the correct point."""
        oc = _make_openclawd()
        oc._dispatch_parallel_goal = AsyncMock(return_value={
            "success": True,
            "response": "parallel done",
            "metadata": {},
        })
        result = await oc._delegate_multi_device_orchestration(
            message="test",
            intent=None,
            session_id="s1",
            trace_id="t1",
        )
        assert result.get("metadata", {}).get("delegation_point") == "multi_device_orchestration", (
            f"Expected delegation_point='multi_device_orchestration', got: {result.get('metadata', {})}"
        )


# ---------------------------------------------------------------------------
# 12-16: Execution-path branching
# ---------------------------------------------------------------------------

class TestExecutionPathBranching:
    """_determine_execution_path must correctly map all four branches."""

    def _ep(self, entry_mode, action_taken, cross_device=False):
        from core.openclawd import OpenClawd
        return OpenClawd._determine_execution_path(
            entry_mode=entry_mode,
            execution_result={"action_taken": action_taken},
            cross_device_dispatched=cross_device,
        )

    def test_local_execution_path(self):
        assert self._ep("local", "focus_window") == "local"

    def test_cross_device_dispatched_path(self):
        assert self._ep("local", "noop", cross_device=True) == "cross_device"

    def test_hybrid_path(self):
        assert self._ep("local", "focus_window", cross_device=True) == "hybrid"

    def test_none_path_no_action(self):
        assert self._ep("local", "noop") == "none"

    def test_cross_device_entry_mode(self):
        assert self._ep("cross_device", "noop") == "cross_device"

    def test_hybrid_entry_mode(self):
        assert self._ep("hybrid", "noop") == "hybrid"

    def test_none_path_observe_action(self):
        assert self._ep("local", "none") == "none"

    def test_docstring_names_four_paths(self):
        """_determine_execution_path docstring must describe all four paths."""
        from core.openclawd import OpenClawd
        doc = OpenClawd._determine_execution_path.__doc__ or ""
        for path in ("local", "cross_device", "hybrid", "none"):
            assert f'"{path}"' in doc or f"``{path}``" in doc, (
                f"_determine_execution_path docstring must document path '{path}'"
            )


# ---------------------------------------------------------------------------
# 17-19: _dispatch_agent delegation routing
# ---------------------------------------------------------------------------

class TestDispatchAgentRouting:
    """_dispatch_agent must route to the correct delegation boundary."""

    @pytest.mark.asyncio
    async def test_no_device_routes_to_local_manifestation(self):
        """With no device_id and no intent target, route to local."""
        oc = _make_openclawd()
        local_mock = AsyncMock(return_value={
            "success": True, "response": "local", "metadata": {"delegation_point": "local"},
        })
        remote_mock = AsyncMock(return_value={
            "success": True, "response": "remote", "metadata": {"delegation_point": "single_remote"},
        })
        oc._delegate_local_manifestation = local_mock
        oc._delegate_single_remote = remote_mock

        result = await oc._dispatch_agent(message="hello", intent=None, device_id=None)
        local_mock.assert_called_once()
        remote_mock.assert_not_called()
        assert result["metadata"]["delegation_point"] == "local"

    @pytest.mark.asyncio
    async def test_remote_device_routes_to_single_remote(self):
        """With a non-local device_id, route to single-remote delegation."""
        oc = _make_openclawd()
        local_mock = AsyncMock(return_value={
            "success": True, "response": "local", "metadata": {"delegation_point": "local"},
        })
        remote_mock = AsyncMock(return_value={
            "success": True, "response": "remote", "metadata": {"delegation_point": "single_remote"},
        })
        oc._delegate_local_manifestation = local_mock
        oc._delegate_single_remote = remote_mock

        result = await oc._dispatch_agent(
            message="hello", intent=None, device_id="phone_01",
        )
        remote_mock.assert_called_once()
        local_mock.assert_not_called()
        assert result["metadata"]["delegation_point"] == "single_remote"

    @pytest.mark.asyncio
    async def test_local_device_id_routes_to_local_manifestation(self):
        """With a local device_id ('local'), route to local manifestation."""
        oc = _make_openclawd()
        local_mock = AsyncMock(return_value={
            "success": True, "response": "local", "metadata": {"delegation_point": "local"},
        })
        remote_mock = AsyncMock(return_value={
            "success": True, "response": "remote", "metadata": {"delegation_point": "single_remote"},
        })
        oc._delegate_local_manifestation = local_mock
        oc._delegate_single_remote = remote_mock

        result = await oc._dispatch_agent(
            message="hello", intent=None, device_id="local",
        )
        local_mock.assert_called_once()
        remote_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_intent_target_device_used_for_routing(self):
        """intent.target_device should also trigger single-remote delegation."""
        oc = _make_openclawd()
        local_mock = AsyncMock(return_value={
            "success": True, "response": "local", "metadata": {"delegation_point": "local"},
        })
        remote_mock = AsyncMock(return_value={
            "success": True, "response": "remote", "metadata": {"delegation_point": "single_remote"},
        })
        oc._delegate_local_manifestation = local_mock
        oc._delegate_single_remote = remote_mock

        intent = MagicMock()
        intent.target_device = "tablet_02"

        result = await oc._dispatch_agent(
            message="hello", intent=intent, device_id=None,
        )
        remote_mock.assert_called_once()
        local_mock.assert_not_called()


# ---------------------------------------------------------------------------
# 20-22: process() response guardrails
# ---------------------------------------------------------------------------

class TestProcessResponseGuardrails:
    """process() must always return execution_path and execution_result."""

    def _stub_openclawd_for_process(self):
        """Return an OpenClawd with process() internals stubbed to minimal."""
        oc = _make_openclawd()
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._get_kernel = lambda: None  # skip AgentKernel path
        oc._get_router = lambda: None
        oc._ensure_initialized = lambda: None
        oc._record_turn = AsyncMock()
        oc._parse_intent = AsyncMock(return_value=MagicMock(
            intent="chat",
            confidence=0.9,
            suggestions=[],
            target_device=None,
        ))
        oc._dispatch_chat = AsyncMock(return_value={
            "success": True,
            "response": "ok",
            "metadata": {},
        })
        oc._run_continuum = lambda **kw: {
            "decision": {"action_level": "observe"},
            "metadata": {},
        }
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop",
            "target": None,
            "success": False,
            "skipped_reason": "enable_system_actions=false",
            "metadata": {},
        }
        return oc

    @pytest.mark.asyncio
    async def test_process_always_returns_execution_path(self):
        oc = self._stub_openclawd_for_process()
        result = await oc.process(message="hello", session_id="s1")
        assert "execution_path" in result, "process() must always return 'execution_path'"

    @pytest.mark.asyncio
    async def test_process_always_returns_execution_result(self):
        oc = self._stub_openclawd_for_process()
        result = await oc.process(message="hello", session_id="s1")
        assert "execution_result" in result, "process() must always return 'execution_result'"

    @pytest.mark.asyncio
    async def test_process_returns_runtime_session_id(self):
        oc = self._stub_openclawd_for_process()
        result = await oc.process(
            message="hello", session_id="s1", runtime_session_id="rsid_abc",
        )
        assert result.get("runtime_session_id") == "rsid_abc", (
            "process() must echo runtime_session_id in the response"
        )

    @pytest.mark.asyncio
    async def test_kernel_path_has_delegation_point_local(self):
        """When AgentKernel handles the request, delegation_point must be 'local'."""
        oc = _make_openclawd()
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._ensure_initialized = lambda: None
        oc._record_turn = AsyncMock()

        # Fake a kernel that works
        fake_intent = MagicMock()
        fake_intent.raw_intent = "chat"
        fake_intent.confidence = 0.9

        kernel_result = MagicMock()
        kernel_result.success = True
        kernel_result.reply = "kernel response"
        kernel_result.intent = fake_intent
        kernel_result.error = None
        kernel_result.mode = "chat_only"
        kernel_result.model = "gpt-4"
        kernel_result.to_api_dict.return_value = {
            "agent_steps": [],
            "tool_calls": [],
            "task_result": {},
        }

        fake_kernel = AsyncMock()
        fake_kernel.handle_message = AsyncMock(return_value=kernel_result)

        oc._get_kernel = lambda: fake_kernel
        oc._get_router = lambda: None
        oc._run_continuum = lambda **kw: {"decision": {"action_level": "observe"}, "metadata": {}}
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop", "target": None, "success": False,
            "skipped_reason": "test", "metadata": {},
        }

        result = await oc.process(message="hello", session_id="s1")
        assert result.get("metadata", {}).get("delegation_point") == "local", (
            f"Kernel path must set delegation_point='local'; got: {result.get('metadata', {}).get('delegation_point')}"
        )


# ---------------------------------------------------------------------------
# 23-24: Structural / Regression Guardrails
# ---------------------------------------------------------------------------

class TestStructuralGuardrails:
    """OpenClawd must not inherit from surface classes or import route modules."""

    def test_openclawd_not_subclass_of_surface_classes(self):
        """OpenClawd must be a plain class, not subclassing any surface."""
        from core.openclawd import OpenClawd
        mro_names = [c.__name__ for c in OpenClawd.__mro__]
        surface_names = {"APIRouter", "FastAPI", "Blueprint", "Route", "BaseHTTPHandler"}
        overlap = surface_names.intersection(set(mro_names))
        assert not overlap, (
            f"OpenClawd must NOT inherit from surface classes; found: {overlap}"
        )

    def test_openclawd_module_does_not_statically_import_routes(self):
        """core/openclawd.py must not have *top-level* imports from core/routes.

        Lazy imports inside function bodies are acceptable (they are utility
        uses, not surface ownership), but top-level static imports would
        couple OpenClawd to the HTTP surface at module load time.
        """
        import ast
        import pathlib
        src = pathlib.Path("core/openclawd.py").read_text()
        tree = ast.parse(src)
        # Only check top-level import nodes (direct children of the Module node)
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("core.routes"), (
                    f"core/openclawd.py must not have a top-level import from "
                    f"core.routes; found: from {node.module} import ..."
                )

    def test_delegation_helpers_are_not_public_api(self):
        """Delegation boundary helpers should be private (prefixed with _)."""
        from core.openclawd import OpenClawd
        for name in ("_delegate_local_manifestation", "_delegate_single_remote",
                     "_delegate_multi_device_orchestration"):
            assert name.startswith("_"), f"{name} should be private (start with _)"
            assert hasattr(OpenClawd, name), f"OpenClawd must have {name}"

    def test_intent_handler_map_present(self):
        """_INTENT_HANDLER_MAP must still be present — backward compatibility."""
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_INTENT_HANDLER_MAP"), (
            "OpenClawd._INTENT_HANDLER_MAP must remain for backward compatibility"
        )
        assert "chat" in OpenClawd._INTENT_HANDLER_MAP
        assert "parallel_goal" in OpenClawd._INTENT_HANDLER_MAP
