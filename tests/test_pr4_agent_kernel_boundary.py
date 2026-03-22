"""
tests/test_pr4_agent_kernel_boundary.py
========================================

PR-4: Formalize AgentKernel as OpenClawd's embedded cognition layer.

Validates that:

Architecture / Role
  1. AgentKernel module docstring identifies it as OpenClawd's embedded layer.
  2. AgentKernel class docstring states it is NOT a peer/top-level authority.
  3. KernelResponse carries a ``delegation_hint`` field (cognition artifact).
  4. ``delegation_hint`` is present in ``KernelResponse.to_api_dict()`` output.

OpenClawd Ownership of Kernel Lifecycle
  5. OpenClawd holds a ``_kernel`` attribute (the embedded AgentKernel).
  6. OpenClawd exposes ``_get_kernel()`` as the sole access point.
  7. ``_get_kernel()`` docstring indicates OpenClawd ownership.
  8. OpenClawd process() metadata stamps ``kernel_cognition_role``.
  9. OpenClawd process() metadata stamps ``kernel_delegation_hint``.

No Circular Dependency / Peer Relationship
 10. AgentKernel._handle_chat does NOT import or call OpenClawd.
 11. core/routes/chat.py does NOT directly import AgentKernel.
 12. AgentKernel is not imported from core/routes/chat.py.

Regression Guard — OpenClawd is the Decision Point
 13. process() with kernel path includes handler="agent_kernel" in metadata.
 14. process() always has ``execution_path`` in the response (regression).
 15. process() always has ``execution_result`` in the response (regression).
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).parent.parent


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
    return oc


def _make_kernel_response(*, delegation_hint=None):
    from core.agent.kernel import KernelResponse
    from core.agent.intent_router import IntentResult
    return KernelResponse(
        success=True,
        mode="chat_only",
        reply="hello",
        model="test-model",
        session_id="test-session",
        intent=IntentResult(mode="chat_only", raw_intent="chat_only", confidence=0.9),
        delegation_hint=delegation_hint,
    )


# ---------------------------------------------------------------------------
# 1-4  Architecture / Role
# ---------------------------------------------------------------------------

class TestAgentKernelRole:
    """AgentKernel must be identified as an embedded cognition layer."""

    def test_module_docstring_mentions_embedded(self):
        """Module docstring should identify AgentKernel as embedded in OpenClawd."""
        import core.agent.kernel as kernel_mod
        doc = kernel_mod.__doc__ or ""
        assert "OpenClawd" in doc, (
            "core/agent/kernel.py module docstring must mention OpenClawd "
            "to make the embedded role explicit."
        )
        assert "内嵌" in doc or "embedded" in doc.lower() or "Embedded" in doc, (
            "Module docstring must use '内嵌' or 'embedded'/'Embedded' to state the role."
        )

    def test_class_docstring_states_not_peer_authority(self):
        """AgentKernel class docstring should state it is NOT a peer authority."""
        from core.agent.kernel import AgentKernel
        doc = AgentKernel.__doc__ or ""
        # Must describe its embedded / internal role
        assert "OpenClawd" in doc, (
            "AgentKernel class docstring must reference OpenClawd."
        )
        # Must explicitly deny peer/standalone status
        lower = doc.lower()
        assert "不是" in doc or "not" in lower, (
            "AgentKernel class docstring should explicitly state it is NOT "
            "a standalone or peer authority."
        )

    def test_kernel_response_has_delegation_hint_field(self):
        """KernelResponse must have a delegation_hint field."""
        from core.agent.kernel import KernelResponse
        fields = KernelResponse.model_fields
        assert "delegation_hint" in fields, (
            "KernelResponse must have a 'delegation_hint' field so that "
            "cognition outputs are distinguishable from transport directives."
        )

    def test_kernel_response_delegation_hint_in_api_dict(self):
        """delegation_hint should appear in to_api_dict() output."""
        kr = _make_kernel_response(delegation_hint="local")
        api = kr.to_api_dict()
        assert "delegation_hint" in api, (
            "KernelResponse.to_api_dict() must include 'delegation_hint'."
        )
        assert api["delegation_hint"] == "local"

    def test_kernel_response_delegation_hint_default_is_none(self):
        """delegation_hint should default to None (no mandatory hint)."""
        kr = _make_kernel_response()
        assert kr.delegation_hint is None, (
            "KernelResponse.delegation_hint should default to None."
        )


# ---------------------------------------------------------------------------
# 5-9  OpenClawd Ownership of Kernel Lifecycle
# ---------------------------------------------------------------------------

class TestOpenClawdKernelOwnership:
    """OpenClawd must own and manage the AgentKernel lifecycle."""

    def test_openclawd_has_kernel_attribute(self):
        from core.openclawd import OpenClawd
        oc = OpenClawd()
        assert hasattr(oc, "_kernel"), (
            "OpenClawd must have a '_kernel' attribute for the embedded AgentKernel."
        )

    def test_openclawd_has_get_kernel_method(self):
        from core.openclawd import OpenClawd
        assert hasattr(OpenClawd, "_get_kernel") and callable(OpenClawd._get_kernel), (
            "OpenClawd must have a _get_kernel() method."
        )

    def test_get_kernel_docstring_mentions_ownership(self):
        """_get_kernel docstring should describe OpenClawd's ownership."""
        from core.openclawd import OpenClawd
        doc = OpenClawd._get_kernel.__doc__ or ""
        assert "OpenClawd" in doc or "持有" in doc, (
            "_get_kernel() docstring should make ownership by OpenClawd explicit."
        )

    @pytest.mark.asyncio
    async def test_process_metadata_stamps_kernel_cognition_role(self):
        """process() kernel path must stamp kernel_cognition_role in metadata."""
        oc = _make_openclawd()
        mock_kernel = MagicMock()
        mock_kernel.handle_message = AsyncMock(return_value=_make_kernel_response())
        oc._get_kernel = lambda: mock_kernel
        oc._get_router = lambda: None
        oc._ensure_initialized = lambda: None
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._record_turn = AsyncMock()
        oc._run_continuum = lambda **kw: {"decision": {"action_level": "observe"}, "metadata": {}}
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop", "success": False, "skipped_reason": "observe"
        }

        result = await oc.process(message="hello", session_id="s1")
        meta = result.get("metadata", {})
        assert "kernel_cognition_role" in meta, (
            "process() kernel path must stamp 'kernel_cognition_role' in metadata "
            "to make the architectural boundary explicit."
        )
        assert meta["kernel_cognition_role"] == "embedded_cognition_layer"

    @pytest.mark.asyncio
    async def test_process_metadata_stamps_kernel_delegation_hint(self):
        """process() kernel path must stamp kernel_delegation_hint in metadata."""
        oc = _make_openclawd()
        mock_kernel = MagicMock()
        mock_kernel.handle_message = AsyncMock(
            return_value=_make_kernel_response(delegation_hint="local")
        )
        oc._get_kernel = lambda: mock_kernel
        oc._get_router = lambda: None
        oc._ensure_initialized = lambda: None
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._record_turn = AsyncMock()
        oc._run_continuum = lambda **kw: {"decision": {"action_level": "observe"}, "metadata": {}}
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop", "success": False, "skipped_reason": "observe"
        }

        result = await oc.process(message="hello", session_id="s2")
        meta = result.get("metadata", {})
        assert "kernel_delegation_hint" in meta, (
            "process() must include 'kernel_delegation_hint' from KernelResponse "
            "so OpenClawd can inspect the cognition artifact's delegation suggestion."
        )
        assert meta["kernel_delegation_hint"] == "local"


# ---------------------------------------------------------------------------
# 10-12  No Circular Dependency / Peer Relationship
# ---------------------------------------------------------------------------

class TestNoPeerRelationship:
    """AgentKernel must not call back to OpenClawd (no circular dependency)."""

    def test_handle_chat_does_not_import_openclawd(self):
        """AgentKernel._handle_chat source must not import openclawd."""
        kernel_file = _REPO_ROOT / "core" / "agent" / "kernel.py"
        source = kernel_file.read_text(encoding="utf-8")

        # Find the _handle_chat function source
        tree = ast.parse(source)
        handle_chat_source = ""
        for node in ast.walk(tree):
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                if node.name == "_handle_chat":
                    # Extract lines for this function
                    lines = source.splitlines()
                    func_lines = lines[node.lineno - 1: node.end_lineno]
                    handle_chat_source = "\n".join(func_lines)
                    break

        assert handle_chat_source, "_handle_chat method must exist in AgentKernel."
        # Must not contain import of openclawd or call to get_openclawd
        assert (
            "get_openclawd" not in handle_chat_source
            and "from core.openclawd" not in handle_chat_source
        ), (
            "AgentKernel._handle_chat must NOT import or call get_openclawd(). "
            "This would create a circular dependency and make the two look like peers. "
            "Use _fallback_chat (direct LLM) instead."
        )

    def test_kernel_module_has_no_openclawd_import_at_module_level(self):
        """AgentKernel module must not import openclawd at module level."""
        kernel_file = _REPO_ROOT / "core" / "agent" / "kernel.py"
        source = kernel_file.read_text(encoding="utf-8")

        # Only check top-level (non-indented) imports
        for line in source.splitlines():
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent == 0 and ("openclawd" in line.lower()) and (
                line.strip().startswith("import") or line.strip().startswith("from")
            ):
                pytest.fail(
                    f"AgentKernel module has a top-level import of openclawd: {line!r}. "
                    "This must not exist — AgentKernel depends on OpenClawd only through "
                    "the interface it receives (e.g., injected _llm_router)."
                )

    def test_chat_route_does_not_directly_import_agent_kernel(self):
        """core/routes/chat.py must not directly import AgentKernel."""
        chat_file = _REPO_ROOT / "core" / "routes" / "chat.py"
        source = chat_file.read_text(encoding="utf-8")
        assert "from core.agent.kernel import" not in source, (
            "core/routes/chat.py must not directly import AgentKernel. "
            "Kernel access must go through OpenClawd."
        )
        # Check there is no instantiation or direct call to AgentKernel
        # (comments explaining the architecture are OK, but usage is not)
        assert "AgentKernel()" not in source, (
            "core/routes/chat.py must not instantiate AgentKernel directly. "
            "Only OpenClawd should create/access the embedded kernel."
        )
        assert "import AgentKernel" not in source, (
            "core/routes/chat.py must not import AgentKernel. "
            "Only OpenClawd should access the embedded kernel."
        )


# ---------------------------------------------------------------------------
# 13-15  Regression Guard — OpenClawd is the Decision Point
# ---------------------------------------------------------------------------

class TestOpenClawdDecisionPoint:
    """OpenClawd must remain the decision point that interprets kernel output."""

    @pytest.mark.asyncio
    async def test_process_kernel_path_sets_handler_agent_kernel(self):
        """process() via kernel path must set handler='agent_kernel' in metadata."""
        oc = _make_openclawd()
        mock_kernel = MagicMock()
        mock_kernel.handle_message = AsyncMock(return_value=_make_kernel_response())
        oc._get_kernel = lambda: mock_kernel
        oc._get_router = lambda: None
        oc._ensure_initialized = lambda: None
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._record_turn = AsyncMock()
        oc._run_continuum = lambda **kw: {"decision": {"action_level": "observe"}, "metadata": {}}
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop", "success": False, "skipped_reason": "observe"
        }

        result = await oc.process(message="hello", session_id="s3")
        meta = result.get("metadata", {})
        assert meta.get("handler") == "agent_kernel", (
            "process() via kernel path must record handler='agent_kernel' "
            "so the decision path is observable."
        )

    @pytest.mark.asyncio
    async def test_process_always_has_execution_path(self):
        """process() must always return execution_path (regression guard)."""
        oc = _make_openclawd()
        oc._get_kernel = lambda: None
        oc._get_router = lambda: None
        oc._ensure_initialized = lambda: None
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._record_turn = AsyncMock()
        oc._parse_intent = AsyncMock(return_value=MagicMock(
            intent="chat", confidence=0.9, suggestions=[], target_device=None,
        ))
        oc._run_continuum = lambda **kw: {"decision": {"action_level": "observe"}, "metadata": {}}
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop", "success": False, "skipped_reason": "observe"
        }
        oc._dispatch_chat = AsyncMock(return_value={"success": True, "response": "ok", "metadata": {}})

        result = await oc.process(message="hello", session_id="s4")
        assert "execution_path" in result, "execution_path must always be present in process() response."

    @pytest.mark.asyncio
    async def test_process_always_has_execution_result(self):
        """process() must always return execution_result (regression guard)."""
        oc = _make_openclawd()
        oc._get_kernel = lambda: None
        oc._get_router = lambda: None
        oc._ensure_initialized = lambda: None
        oc._emit_audit = MagicMock()
        oc.sync_device_capabilities = MagicMock()
        oc._record_turn = AsyncMock()
        oc._parse_intent = AsyncMock(return_value=MagicMock(
            intent="chat", confidence=0.9, suggestions=[], target_device=None,
        ))
        oc._run_continuum = lambda **kw: {"decision": {"action_level": "observe"}, "metadata": {}}
        oc._run_execution = lambda state, entry_mode=None: {
            "action_taken": "noop", "success": False, "skipped_reason": "observe"
        }
        oc._dispatch_chat = AsyncMock(return_value={"success": True, "response": "ok", "metadata": {}})

        result = await oc.process(message="hello", session_id="s5")
        assert "execution_result" in result, "execution_result must always be present in process() response."
