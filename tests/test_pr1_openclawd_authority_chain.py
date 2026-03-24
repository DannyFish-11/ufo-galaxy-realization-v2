#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr1_openclawd_authority_chain.py
============================================

PR-1 — OpenClawd Authority Chain enforcement tests.

Validates that the OpenClawd authority chain is correctly enforced:

  (a) Chat route does not instantiate AgentKernel directly.
  (b) OpenClawd owns the AgentKernel lifecycle via _get_kernel().
  (c) OpenClawd stamps authority_role / execution_path in response metadata.
  (d) No direct kernel invocation in routes.

Also verifies PR-1 additions to LocalExecutionResult and CommandRouter:

  (e) LocalExecutionResult.to_dict() includes authority_role and execution_path.
  (f) CommandRouter introspection_snapshot includes execution_path.

Test classes:

  1. TestChatRouteNoAgentKernelDirectAccess
       (a + d) chat route source does not import or instantiate AgentKernel.

  2. TestOpenClawdKernelLifecycleOwnership
       (b) _get_kernel() is the sole creation/access point for AgentKernel in
       OpenClawd; no other attribute holds a raw AgentKernel instance.

  3. TestOpenClawdAuthorityMetadataStamps
       (c) OpenClawd.process() stamps authority_role and execution_path.

  4. TestLocalExecutionResultMetadataStamps
       (e) LocalExecutionResult.to_dict() includes authority_role / execution_path.

  5. TestCommandRouterExecutionPathStamp
       (f) CommandRouter introspection_snapshot includes execution_path.

  6. TestCanonicalDispatcherIsPrimaryPath
       CanonicalDispatcher is the primary execution path referenced by OpenClawd.
"""

from __future__ import annotations

import inspect
import pathlib
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = pathlib.Path(__file__).parent.parent


# ===========================================================================
# 1. TestChatRouteNoAgentKernelDirectAccess
# ===========================================================================


class TestChatRouteNoAgentKernelDirectAccess:
    """(a + d) chat route must not import or instantiate AgentKernel directly."""

    def _chat_source(self) -> str:
        src_path = _REPO_ROOT / "core" / "routes" / "chat.py"
        return src_path.read_text(encoding="utf-8")

    def test_chat_route_does_not_import_agent_kernel(self):
        """core/routes/chat.py must not import or instantiate AgentKernel."""
        src = self._chat_source()
        # Disallow import-style references; docstrings may mention the name for
        # architecture documentation purposes, but must never import or instantiate.
        import re
        assert not re.search(r"\bfrom\s+core\.agent(?:\.kernel)?\s+import\b", src), (
            "core/routes/chat.py must not import from core.agent or core.agent.kernel. "
            "AgentKernel is owned exclusively by OpenClawd — routes must "
            "delegate to DesktopPresenceRuntime → OpenClawd instead."
        )
        assert "AgentKernel()" not in src, (
            "core/routes/chat.py must not instantiate AgentKernel(). "
            "AgentKernel lifecycle is owned by OpenClawd exclusively."
        )

    def test_chat_route_does_not_import_kernel_module(self):
        """core/routes/chat.py must not import from core.agent.kernel."""
        src = self._chat_source()
        assert "core.agent.kernel" not in src, (
            "core/routes/chat.py must not import from core.agent.kernel. "
            "The kernel is an internal component of OpenClawd."
        )

    def test_chat_route_delegates_to_desktop_presence_runtime(self):
        """core/routes/chat.py must delegate to DesktopPresenceRuntime."""
        src = self._chat_source()
        assert "DesktopPresenceRuntime" in src or "desktop_presence_runtime" in src, (
            "core/routes/chat.py must delegate to DesktopPresenceRuntime — "
            "this is the runtime shell that drives OpenClawd."
        )

    def test_chat_route_no_legacy_bypass_functions(self):
        """Legacy bypass functions must not exist in core/routes/chat.py."""
        src = self._chat_source()
        legacy_names = [
            "_handle_agent_action",
            "_try_capability_execute",
            "_try_agent_factory",
            "_handle_scheduler_react",
            "_handle_pure_chat",
        ]
        for name in legacy_names:
            assert f"def {name}" not in src, (
                f"Legacy bypass function '{name}' must not exist in "
                "core/routes/chat.py — it bypasses the OpenClawd authority "
                "chain.  All execution must flow through "
                "DesktopPresenceRuntime → OpenClawd."
            )

    def test_chat_route_no_action_keyword_lists(self):
        """Legacy action-keyword lists used by removed bypass functions must be gone."""
        src = self._chat_source()
        assert "_ACTION_KEYWORDS_ZH" not in src, (
            "_ACTION_KEYWORDS_ZH belongs to the removed legacy bypass path."
        )
        assert "_ACTION_KEYWORDS_EN" not in src, (
            "_ACTION_KEYWORDS_EN belongs to the removed legacy bypass path."
        )

    def test_chat_route_declares_no_direct_kernel_authority(self):
        """Module docstring must state AgentKernel is never called directly."""
        src = self._chat_source()
        assert "never called directly" in src or "never called directly from this adapter" in src, (
            "core/routes/chat.py docstring must state AgentKernel is never "
            "called directly from this adapter."
        )


# ===========================================================================
# 2. TestOpenClawdKernelLifecycleOwnership
# ===========================================================================


class TestOpenClawdKernelLifecycleOwnership:
    """(b) OpenClawd must own AgentKernel lifecycle via _get_kernel()."""

    def _openclawd_source(self) -> str:
        src_path = _REPO_ROOT / "core" / "openclawd.py"
        return src_path.read_text(encoding="utf-8")

    def test_openclawd_has_get_kernel_method(self):
        """OpenClawd must have a _get_kernel method."""
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_get_kernel"), (
            "OpenClawd must have _get_kernel() as the sole kernel creation "
            "and access point (PR-1)."
        )

    def test_get_kernel_is_the_creation_point(self):
        """_get_kernel source must create AgentKernel internally."""
        from core.openclawd import OpenClawd
        src = inspect.getsource(OpenClawd._get_kernel)
        assert "AgentKernel" in src, (
            "OpenClawd._get_kernel() must be responsible for creating the "
            "AgentKernel instance.  No other method should create it."
        )

    def test_get_kernel_lazy_initialises_kernel(self):
        """_get_kernel must use lazy initialisation (if self._kernel is None)."""
        from core.openclawd import OpenClawd
        src = inspect.getsource(OpenClawd._get_kernel)
        assert "self._kernel" in src, (
            "_get_kernel must store the kernel as self._kernel."
        )
        assert "None" in src, (
            "_get_kernel must check for None before creating a new instance."
        )

    def test_openclawd_source_only_uses_get_kernel_to_access_kernel(self):
        """OpenClawd process() must access the kernel only via _get_kernel()."""
        src = self._openclawd_source()
        # The canonical access pattern is _get_kernel(); direct 'AgentKernel()'
        # calls must not appear outside of _get_kernel itself.
        # We check that outside of _get_kernel, there is no 'AgentKernel()'
        # instantiation call (which would be a lifecycle bypass).
        lines = src.splitlines()
        in_get_kernel = False
        for line in lines:
            stripped = line.strip()
            if "def _get_kernel" in stripped:
                in_get_kernel = True
            elif in_get_kernel and stripped.startswith("def "):
                in_get_kernel = False
            if not in_get_kernel and "AgentKernel()" in stripped:
                pytest.fail(
                    "AgentKernel() must only be instantiated inside "
                    "OpenClawd._get_kernel().  Found a direct instantiation "
                    "outside that method, which violates lifecycle ownership."
                )

    def test_openclawd_docstring_states_kernel_ownership(self):
        """OpenClawd._get_kernel docstring must describe ownership."""
        from core.openclawd import OpenClawd
        doc = OpenClawd._get_kernel.__doc__ or ""
        assert "OpenClawd" in doc or "唯一" in doc or "lifecycle" in doc.lower() or "持有" in doc, (
            "OpenClawd._get_kernel docstring must explain that OpenClawd "
            "is the sole owner and lifecycle manager for AgentKernel."
        )


# ===========================================================================
# 3. TestOpenClawdAuthorityMetadataStamps
# ===========================================================================


class TestOpenClawdAuthorityMetadataStamps:
    """(c) OpenClawd stamps authority_role and execution_path in metadata."""

    def _openclawd_source(self) -> str:
        src_path = _REPO_ROOT / "core" / "openclawd.py"
        return src_path.read_text(encoding="utf-8")

    def test_openclawd_stamps_authority_role_subject_decision_authority(self):
        """OpenClawd source must stamp authority_role=subject_decision_authority."""
        src = self._openclawd_source()
        assert '"authority_role": "subject_decision_authority"' in src, (
            "OpenClawd.process() must stamp "
            "authority_role='subject_decision_authority' in response metadata "
            "so that the authority chain is observable end-to-end (PR-1 / PR-9)."
        )

    def test_openclawd_stamps_execution_path_in_metadata(self):
        """OpenClawd source must stamp execution_path in response metadata."""
        src = self._openclawd_source()
        assert '"execution_path"' in src, (
            "OpenClawd.process() must include 'execution_path' in response "
            "metadata so that callers can observe the canonical execution branch."
        )

    def test_openclawd_process_metadata_has_authority_role_at_runtime(self):
        """OpenClawd.process() runtime output must include authority_role."""
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
        oc._ensure_initialized = lambda: None

        from core.agent.kernel import KernelResponse
        from core.agent.intent_router import IntentResult

        kr = KernelResponse(
            success=True,
            mode="chat_only",
            reply="test reply",
            model="test-model",
            session_id="s1",
            intent=IntentResult(mode="chat_only", raw_intent="chat_only", confidence=0.9),
        )
        mock_kernel = MagicMock()
        mock_kernel.handle_message = AsyncMock(return_value=kr)

        import asyncio

        async def _run():
            with patch.object(oc, "_get_kernel", return_value=mock_kernel), \
                 patch.object(oc, "_get_router", return_value=None), \
                 patch.object(oc, "_parse_intent", new_callable=AsyncMock), \
                 patch.object(oc, "_run_continuum", return_value=None), \
                 patch.object(oc, "_run_execution", return_value={}), \
                 patch.object(oc, "_determine_execution_path", return_value="none"), \
                 patch.object(oc, "_build_execution_plan", return_value=None), \
                 patch.object(oc, "_finalise_plan_lifecycle", return_value=None), \
                 patch.object(oc, "_build_unified_control_plan", return_value=None), \
                 patch.object(oc, "_record_turn", new_callable=AsyncMock), \
                 patch.object(oc, "sync_device_capabilities", return_value=None):
                return await oc.process(message="hello", session_id="s1")

        result = asyncio.new_event_loop().run_until_complete(_run())
        meta = result.get("metadata", {})
        assert "authority_role" in meta, (
            "OpenClawd.process() response metadata must contain 'authority_role'."
        )
        assert meta["authority_role"] == "subject_decision_authority", (
            "OpenClawd response metadata.authority_role must be "
            "'subject_decision_authority'."
        )

    def test_openclawd_process_metadata_has_execution_path_at_runtime(self):
        """OpenClawd.process() runtime output must include execution_path."""
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
        oc._ensure_initialized = lambda: None

        from core.agent.kernel import KernelResponse
        from core.agent.intent_router import IntentResult

        kr = KernelResponse(
            success=True,
            mode="chat_only",
            reply="test",
            model="test-model",
            session_id="s1",
            intent=IntentResult(mode="chat_only", raw_intent="chat_only", confidence=0.9),
        )
        mock_kernel = MagicMock()
        mock_kernel.handle_message = AsyncMock(return_value=kr)

        import asyncio

        async def _run():
            with patch.object(oc, "_get_kernel", return_value=mock_kernel), \
                 patch.object(oc, "_get_router", return_value=None), \
                 patch.object(oc, "_parse_intent", new_callable=AsyncMock), \
                 patch.object(oc, "_run_continuum", return_value=None), \
                 patch.object(oc, "_run_execution", return_value={}), \
                 patch.object(oc, "_determine_execution_path", return_value="none"), \
                 patch.object(oc, "_build_execution_plan", return_value=None), \
                 patch.object(oc, "_finalise_plan_lifecycle", return_value=None), \
                 patch.object(oc, "_build_unified_control_plan", return_value=None), \
                 patch.object(oc, "_record_turn", new_callable=AsyncMock), \
                 patch.object(oc, "sync_device_capabilities", return_value=None):
                return await oc.process(message="hello", session_id="s1")

        result = asyncio.new_event_loop().run_until_complete(_run())
        meta = result.get("metadata", {})
        assert "execution_path" in meta, (
            "OpenClawd.process() response metadata must contain 'execution_path'."
        )


# ===========================================================================
# 4. TestLocalExecutionResultMetadataStamps
# ===========================================================================


class TestLocalExecutionResultMetadataStamps:
    """(e) LocalExecutionResult.to_dict() must include authority_role + execution_path."""

    def test_to_dict_includes_authority_role(self):
        """LocalExecutionResult.to_dict() must include authority_role."""
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="t1", success=True, status="completed")
        d = r.to_dict()
        assert "authority_role" in d, (
            "LocalExecutionResult.to_dict() must include 'authority_role' for "
            "normalized metadata stamping (PR-1)."
        )

    def test_authority_role_is_execution_substrate(self):
        """LocalExecutionResult authority_role must be 'execution_substrate'."""
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult()
        d = r.to_dict()
        assert d["authority_role"] == "execution_substrate", (
            "LocalExecutionResult.to_dict()['authority_role'] must be "
            "'execution_substrate' to identify it as the local execution layer "
            "downstream of OpenClawd (subject decision authority)."
        )

    def test_to_dict_includes_execution_path(self):
        """LocalExecutionResult.to_dict() must include execution_path."""
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="t2", success=False, status="failed")
        d = r.to_dict()
        assert "execution_path" in d, (
            "LocalExecutionResult.to_dict() must include 'execution_path' for "
            "normalized metadata stamping (PR-1)."
        )

    def test_execution_path_is_local(self):
        """LocalExecutionResult execution_path must be 'local'."""
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult()
        d = r.to_dict()
        assert d["execution_path"] == "local", (
            "LocalExecutionResult.to_dict()['execution_path'] must be 'local' "
            "to identify this result as produced by the local execution chain."
        )

    def test_existing_keys_still_present(self):
        """Adding new fields must not remove any existing to_dict() keys."""
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="t3", success=True, status="done")
        d = r.to_dict()
        for key in (
            "task_id", "chain_step", "success", "status", "payload",
            "error", "executor_module", "session_id", "result_id",
            "timestamp", "extra", "openclawd_merged",
        ):
            assert key in d, (
                f"Existing key '{key}' must still be present in "
                "LocalExecutionResult.to_dict() after PR-1 additions."
            )

    def test_to_dict_is_json_serialisable(self):
        """to_dict() including new fields must still be JSON-serialisable."""
        import json
        from core.local_execution_chain import LocalExecutionResult
        r = LocalExecutionResult(task_id="t4", success=True, status="ok")
        json.dumps(r.to_dict())  # must not raise


# ===========================================================================
# 5. TestCommandRouterExecutionPathStamp
# ===========================================================================


class TestCommandRouterExecutionPathStamp:
    """(f) CommandRouter introspection_snapshot must include execution_path."""

    def _router_source(self) -> str:
        src_path = _REPO_ROOT / "core" / "command_router.py"
        return src_path.read_text(encoding="utf-8")

    def test_introspection_snapshot_has_execution_path_in_source(self):
        """command_router.py must stamp execution_path in introspection_snapshot."""
        src = self._router_source()
        assert '"execution_path"' in src, (
            "core/command_router.py introspection_snapshot must include "
            "'execution_path' so that substrate results carry the canonical "
            "execution path annotation (PR-1)."
        )

    def test_introspection_snapshot_execution_path_is_local(self):
        """command_router.py must stamp execution_path='local' in introspection_snapshot."""
        src = self._router_source()
        assert '"execution_path": "local"' in src, (
            "core/command_router.py must stamp execution_path='local' in "
            "introspection_snapshot — CommandRouter is the local execution "
            "substrate layer."
        )

    def test_introspection_snapshot_retains_authority_role(self):
        """command_router.py introspection_snapshot must keep authority_role."""
        src = self._router_source()
        assert '"authority_role": "execution_substrate"' in src, (
            "core/command_router.py introspection_snapshot must still contain "
            "authority_role='execution_substrate' (unchanged from PR-14)."
        )


# ===========================================================================
# 6. TestCanonicalDispatcherIsPrimaryPath
# ===========================================================================


class TestCanonicalDispatcherIsPrimaryPath:
    """CanonicalDispatcher must be the primary tool execution path in OpenClawd."""

    def _openclawd_source(self) -> str:
        src_path = _REPO_ROOT / "core" / "openclawd.py"
        return src_path.read_text(encoding="utf-8")

    def test_openclawd_imports_canonical_dispatcher(self):
        """OpenClawd source must reference CanonicalDispatcher."""
        src = self._openclawd_source()
        assert "CanonicalDispatcher" in src or "canonical_dispatcher" in src, (
            "OpenClawd must reference CanonicalDispatcher as the primary "
            "tool/capability execution path (PR-001)."
        )

    def test_canonical_dispatcher_is_importable(self):
        """CanonicalDispatcher must be importable."""
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        assert CanonicalDispatcher is not None

    def test_canonical_dispatcher_has_dispatch_method(self):
        """CanonicalDispatcher must have a dispatch() method."""
        from core.capabilities.canonical_dispatcher import CanonicalDispatcher
        assert hasattr(CanonicalDispatcher, "dispatch"), (
            "CanonicalDispatcher must expose a dispatch() method as the "
            "single canonical execution path for capabilities."
        )

    def test_canonical_dispatcher_dispatch_result_importable(self):
        """DispatchResult must be importable from canonical_dispatcher."""
        from core.capabilities.canonical_dispatcher import DispatchResult
        assert DispatchResult is not None

    def test_dispatch_result_has_to_dict(self):
        """DispatchResult must have a to_dict() method for serialisation."""
        from core.capabilities.canonical_dispatcher import DispatchResult
        assert hasattr(DispatchResult, "to_dict"), (
            "DispatchResult must expose to_dict() for a stable, serialisable "
            "dispatch result contract."
        )

    def test_openclawd_uses_capability_dispatcher_attribute(self):
        """OpenClawd must store CanonicalDispatcher in _capability_dispatcher."""
        src = self._openclawd_source()
        assert "_capability_dispatcher" in src, (
            "OpenClawd must hold a _capability_dispatcher attribute backed by "
            "CanonicalDispatcher — this makes the dispatcher lifecycle "
            "explicitly owned by OpenClawd."
        )
