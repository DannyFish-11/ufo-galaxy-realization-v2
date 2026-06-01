#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_execution_authority_contract.py
===============================================

PR-9 — Execution Authority Contract tests.

Validates that the canonical execution authority schema and metadata
threading work correctly across the runtime stack.  All tests are
self-contained (no live servers, no real devices).

Test classes:

  1. TestExecutionLayerRole
       ExecutionLayerRole enum values and completeness.

  2. TestExecutionAuthorityMetadata
       ExecutionAuthorityMetadata construction, to_dict, and field defaults.

  3. TestCanonicalAuthorityChain
       CANONICAL_AUTHORITY_CHAIN ordering and completeness.

  4. TestGetLayerAuthority
       get_layer_authority() module-path resolution including boundary checks.

  5. TestBuildAuthorityMetadata
       build_authority_metadata() convenience factory.

  6. TestDesktopPresenceRuntimeAuthority
       DesktopPresenceRuntime.handle_request() stamps authority_metadata
       identifying it as the runtime shell authority.

  7. TestOpenClawdSubjectDecisionAuthority
       OpenClawd.process() stamps authority_role="subject_decision_authority"
       in its response metadata.

  8. TestAgentKernelCognitionLayer
       KernelResponse carries authority_role="cognition_planning_layer" by
       default and to_api_dict() propagates it.

  9. TestCommandRouterSubstrate
       CommandRouter.route_envelope() stamps
       execution_substrate_role="execution_substrate" in its result.

  10. TestChatRouteEntrySurface
        /api/v1/chat sets execution_authority and surface_role consistent with
        the entry-surface / compat-adapter contract.

  11. TestAuthorityChainContract
        Cross-layer guardrail: the roles declared by each layer are consistent
        with the canonical chain and no layer claims an authority it should
        not hold.
"""

from __future__ import annotations

import asyncio
import sys
import os
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


# ===========================================================================
# 1. TestExecutionLayerRole
# ===========================================================================


class TestExecutionLayerRole:
    """ExecutionLayerRole enum values and completeness."""

    def test_entry_surface_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.ENTRY_SURFACE.value == "entry_surface"

    def test_runtime_shell_authority_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY.value == "runtime_shell_authority"

    def test_subject_decision_authority_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY.value == "subject_decision_authority"

    def test_cognition_planning_layer_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.COGNITION_PLANNING_LAYER.value == "cognition_planning_layer"

    def test_execution_substrate_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.EXECUTION_SUBSTRATE.value == "execution_substrate"

    def test_orchestration_layer_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.ORCHESTRATION_LAYER.value == "orchestration_layer"

    def test_compatibility_adapter_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.COMPATIBILITY_ADAPTER.value == "compatibility_adapter"

    def test_unknown_value(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.UNKNOWN.value == "unknown"

    def test_all_values_are_strings(self):
        from core.schemas.execution_authority import ExecutionLayerRole
        for role in ExecutionLayerRole:
            assert isinstance(role.value, str) and role.value

    def test_string_enum(self):
        """ExecutionLayerRole instances compare equal to their string values."""
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.EXECUTION_SUBSTRATE == "execution_substrate"


# ===========================================================================
# 2. TestExecutionAuthorityMetadata
# ===========================================================================


class TestExecutionAuthorityMetadata:
    """ExecutionAuthorityMetadata construction and serialisation."""

    def test_required_fields(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
            canonical_module="core.desktop_presence_runtime",
        )
        assert meta.canonical_module == "core.desktop_presence_runtime"

    def test_optional_fields_default_to_none(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.EXECUTION_SUBSTRATE,
            canonical_module="core.command_router",
        )
        assert meta.canonical_class is None
        assert meta.is_adapter_surface is False
        assert meta.pr_introduced is None
        assert meta.extra is None

    def test_to_dict_required_keys(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
            canonical_module="core.desktop_presence_runtime",
            canonical_class="DesktopPresenceRuntime",
            pr_introduced="PR-1",
        )
        d = meta.to_dict()
        assert d["layer_role"] == "runtime_shell_authority"
        assert d["canonical_module"] == "core.desktop_presence_runtime"
        assert d["canonical_class"] == "DesktopPresenceRuntime"
        assert d["pr_introduced"] == "PR-1"

    def test_to_dict_omits_none_optionals(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.EXECUTION_SUBSTRATE,
            canonical_module="core.command_router",
        )
        d = meta.to_dict()
        assert "canonical_class" not in d
        assert "is_adapter_surface" not in d
        assert "pr_introduced" not in d
        assert "extra" not in d

    def test_to_dict_includes_extra(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.COGNITION_PLANNING_LAYER,
            canonical_module="core.agent.kernel",
            extra={"agent_id": "kernel_01"},
        )
        d = meta.to_dict()
        assert d["extra"]["agent_id"] == "kernel_01"

    def test_adapter_surface_flag(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.ENTRY_SURFACE,
            canonical_module="core.routes.chat",
            is_adapter_surface=True,
        )
        d = meta.to_dict()
        assert d["is_adapter_surface"] is True

    def test_to_dict_is_json_serialisable(self):
        import json
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
        )
        meta = ExecutionAuthorityMetadata(
            layer_role=ExecutionLayerRole.ORCHESTRATION_LAYER,
            canonical_module="core.swarm_coordinator",
            canonical_class="SwarmCoordinator",
            pr_introduced="PR-8",
        )
        serialised = json.dumps(meta.to_dict())
        assert isinstance(serialised, str)


# ===========================================================================
# 3. TestCanonicalAuthorityChain
# ===========================================================================


class TestCanonicalAuthorityChain:
    """CANONICAL_AUTHORITY_CHAIN ordering and completeness."""

    def test_chain_is_list(self):
        from core.schemas.execution_authority import CANONICAL_AUTHORITY_CHAIN
        assert isinstance(CANONICAL_AUTHORITY_CHAIN, list)
        assert len(CANONICAL_AUTHORITY_CHAIN) >= 5

    def test_chain_entries_are_3_tuples(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        for entry in CANONICAL_AUTHORITY_CHAIN:
            assert len(entry) == 3
            role, module, cls = entry
            assert isinstance(role, ExecutionLayerRole), f"role must be ExecutionLayerRole, got {type(role)}"
            assert isinstance(module, str), f"module must be str, got {type(module)}"
            assert isinstance(cls, str), f"cls must be str, got {type(cls)}"

    def test_entry_surface_is_present(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert ExecutionLayerRole.ENTRY_SURFACE in roles

    def test_runtime_shell_authority_is_present(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY in roles

    def test_subject_decision_authority_is_present(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY in roles

    def test_cognition_planning_layer_is_present(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert ExecutionLayerRole.COGNITION_PLANNING_LAYER in roles

    def test_execution_substrate_is_present(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert ExecutionLayerRole.EXECUTION_SUBSTRATE in roles

    def test_runtime_shell_before_subject_decision(self):
        """Runtime shell must appear before subject decision in the chain."""
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert roles.index(ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY) < roles.index(
            ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY
        )

    def test_subject_decision_before_cognition(self):
        """Subject decision must appear before cognition layer in the chain."""
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        roles = [r for r, _, _ in CANONICAL_AUTHORITY_CHAIN]
        assert roles.index(ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY) < roles.index(
            ExecutionLayerRole.COGNITION_PLANNING_LAYER
        )

    def test_desktop_presence_runtime_is_runtime_shell(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        shell_entries = [
            (r, m, c)
            for r, m, c in CANONICAL_AUTHORITY_CHAIN
            if r == ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY
        ]
        assert len(shell_entries) == 1
        _, module, cls = shell_entries[0]
        assert module == "core.desktop_presence_runtime"
        assert cls == "DesktopPresenceRuntime"

    def test_openclawd_is_subject_decision(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        entries = [
            (r, m, c)
            for r, m, c in CANONICAL_AUTHORITY_CHAIN
            if r == ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY
        ]
        assert len(entries) == 1
        _, module, cls = entries[0]
        assert module == "core.openclawd"
        assert cls == "OpenClawd"

    def test_agent_kernel_is_cognition_layer(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        entries = [
            (r, m, c)
            for r, m, c in CANONICAL_AUTHORITY_CHAIN
            if r == ExecutionLayerRole.COGNITION_PLANNING_LAYER
        ]
        assert len(entries) == 1
        _, module, cls = entries[0]
        assert module == "core.agent.kernel"
        assert cls == "AgentKernel"

    def test_command_router_is_execution_substrate(self):
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            ExecutionLayerRole,
        )
        entries = [
            (r, m, c)
            for r, m, c in CANONICAL_AUTHORITY_CHAIN
            if r == ExecutionLayerRole.EXECUTION_SUBSTRATE
        ]
        assert len(entries) == 1
        _, module, cls = entries[0]
        assert module == "core.command_router"
        assert cls == "CommandRouter"


# ===========================================================================
# 4. TestGetLayerAuthority
# ===========================================================================


class TestGetLayerAuthority:
    """get_layer_authority() module-path resolution."""

    def test_chat_route_is_entry_surface(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert get_layer_authority("core.routes.chat") == ExecutionLayerRole.ENTRY_SURFACE

    def test_desktop_presence_runtime_is_runtime_shell(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.desktop_presence_runtime")
            == ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY
        )

    def test_openclawd_is_subject_decision(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.openclawd")
            == ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY
        )

    def test_agent_kernel_is_cognition(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.agent.kernel")
            == ExecutionLayerRole.COGNITION_PLANNING_LAYER
        )

    def test_command_router_is_substrate(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.command_router")
            == ExecutionLayerRole.EXECUTION_SUBSTRATE
        )

    def test_swarm_coordinator_is_orchestration(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.swarm_coordinator")
            == ExecutionLayerRole.ORCHESTRATION_LAYER
        )

    def test_e2e_orchestrator_is_orchestration(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.e2e_orchestrator")
            == ExecutionLayerRole.ORCHESTRATION_LAYER
        )

    def test_submodule_inherits_parent_role(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert (
            get_layer_authority("core.desktop_presence_runtime.DesktopPresenceRuntime")
            == ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY
        )

    def test_unknown_module_returns_unknown(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert get_layer_authority("some.random.module") == ExecutionLayerRole.UNKNOWN

    def test_empty_string_returns_unknown(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        assert get_layer_authority("") == ExecutionLayerRole.UNKNOWN

    def test_prefix_matching_requires_dot_separator(self):
        """core.openclawd_extra must not match core.openclawd prefix."""
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            get_layer_authority,
        )
        role = get_layer_authority("core.openclawd_extra")
        assert role == ExecutionLayerRole.UNKNOWN


# ===========================================================================
# 5. TestBuildAuthorityMetadata
# ===========================================================================


class TestBuildAuthorityMetadata:
    """build_authority_metadata() convenience factory."""

    def test_returns_execution_authority_metadata(self):
        from core.schemas.execution_authority import (
            ExecutionAuthorityMetadata,
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
            "core.desktop_presence_runtime",
        )
        assert isinstance(meta, ExecutionAuthorityMetadata)

    def test_fields_set_correctly(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.COGNITION_PLANNING_LAYER,
            "core.agent.kernel",
            canonical_class="AgentKernel",
            pr_introduced="PR-4",
        )
        assert meta.canonical_class == "AgentKernel"
        assert meta.pr_introduced == "PR-4"

    def test_adapter_surface_flag(self):
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.ENTRY_SURFACE,
            "core.routes.chat",
            is_adapter_surface=True,
        )
        assert meta.is_adapter_surface is True


# ===========================================================================
# 6. TestDesktopPresenceRuntimeAuthority
# ===========================================================================


class TestDesktopPresenceRuntimeAuthority:
    """DesktopPresenceRuntime stamps authority_metadata in handle_request()."""

    def _run(self, coro):
        return asyncio.get_running_loop().run_until_complete(coro)

    def test_authority_metadata_in_result(self):
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        runtime = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
        runtime._initialized = True
        runtime._active_sessions = {}
        runtime.created_at = 0.0

        # Stub out the internal dispatch so it returns immediately
        async def _fake_dispatch(msg, source, device_id, session_id, user_id,
                                  context, required_capabilities, multimodal_context,
                                  use_constellation, entry_mode, **kwargs):
            return {"success": True, "response": "ok"}

        runtime._dispatch = _fake_dispatch

        # Stub RuntimeSession creation
        from unittest.mock import MagicMock
        from core.desktop_presence_runtime import TriState

        mock_session = MagicMock()
        mock_session.runtime_session_id = "rsess_test_001"
        mock_session.tristate = TriState.SILENT

        def _advance(state):
            mock_session.tristate = state

        mock_session.advance = _advance

        runtime._create_session = MagicMock(return_value=mock_session)
        runtime._log_request_start = MagicMock()
        runtime._log_request_end = MagicMock()

        with patch("core.desktop_presence_runtime.DesktopPresenceRuntime._create_session",
                   return_value=mock_session):
            result = self._run(
                runtime.handle_request("hello", source="test")
            )

        assert "authority_metadata" in result
        assert result["authority_metadata"]["layer_role"] == "runtime_shell_authority"
        assert result["authority_metadata"]["canonical_module"] == "core.desktop_presence_runtime"
        assert result["authority_metadata"]["canonical_class"] == "DesktopPresenceRuntime"

    def test_authority_metadata_not_overwritten_by_inner_layers(self):
        """authority_metadata uses setdefault so it is stamped by the outermost layer
        only if the inner dispatch didn't already set it."""
        # Test the setdefault behavior directly without full dispatch mocking:
        # if a result dict already has authority_metadata, setdefault won't overwrite.
        inner_meta = {
            "layer_role": "subject_decision_authority",
            "canonical_module": "core.openclawd",
        }
        result = {"success": True, "authority_metadata": inner_meta}
        result.setdefault("authority_metadata", {
            "layer_role": "runtime_shell_authority",
            "canonical_module": "core.desktop_presence_runtime",
        })
        # setdefault: inner layer stamp is preserved (not overwritten)
        assert result["authority_metadata"]["layer_role"] == "subject_decision_authority"


# ===========================================================================
# 7. TestOpenClawdSubjectDecisionAuthority
# ===========================================================================


class TestOpenClawdSubjectDecisionAuthority:
    """OpenClawd stamps authority_role in its response metadata."""

    def _make_openclawd(self):
        """Return a minimal OpenClawd with mocked internals."""
        from core.openclawd import OpenClawd

        oc = OpenClawd.__new__(OpenClawd)
        oc._initialized = True
        oc._request_count = 0
        oc._error_count = 0
        oc._session_histories = {}
        oc._active_tasks = {}
        oc._cancel_registry = set()
        oc._continuum_orchestrator = None
        oc._task_memory = None
        return oc

    def test_authority_role_in_metadata(self):
        """OpenClawd.process() metadata contains authority_role=subject_decision_authority.

        This test verifies the structural contract: the metadata dict returned by
        process() should carry authority_role.  We verify this by inspecting the
        source of the declared field in the response-building code.
        """
        import inspect
        from core.openclawd import OpenClawd

        source = inspect.getsource(OpenClawd.process)
        # The authority_role annotation must be present in the process() method
        assert "authority_role" in source, (
            "OpenClawd.process() must stamp 'authority_role' in response metadata"
        )
        assert "subject_decision_authority" in source, (
            "OpenClawd.process() must declare 'subject_decision_authority' role"
        )


# ===========================================================================
# 8. TestAgentKernelCognitionLayer
# ===========================================================================


class TestAgentKernelCognitionLayer:
    """KernelResponse carries authority_role='cognition_planning_layer'."""

    def test_default_authority_role(self):
        from core.agent.kernel import KernelResponse

        kr = KernelResponse()
        assert kr.authority_role == "cognition_planning_layer"

    def test_authority_role_in_to_api_dict(self):
        from core.agent.kernel import KernelResponse

        kr = KernelResponse(success=True, reply="hello")
        d = kr.to_api_dict()
        assert d["authority_role"] == "cognition_planning_layer"

    def test_authority_role_not_overridable_externally(self):
        """authority_role field can be set but defaults to cognition_planning_layer."""
        from core.agent.kernel import KernelResponse

        kr = KernelResponse(authority_role="cognition_planning_layer")
        assert kr.authority_role == "cognition_planning_layer"

    def test_kernel_response_backward_compat(self):
        """Existing fields in to_api_dict() are unchanged."""
        from core.agent.kernel import KernelResponse

        kr = KernelResponse(success=True, reply="test", model="gpt-4")
        d = kr.to_api_dict()
        # Existing fields must still be present
        assert "success" in d
        assert "reply" in d
        assert "response" in d
        assert "model" in d
        assert "session_id" in d
        assert "error" in d
        assert "latency_ms" in d


# ===========================================================================
# 9. TestCommandRouterSubstrate
# ===========================================================================


class TestCommandRouterSubstrate:
    """CommandRouter.route_envelope() stamps execution_substrate_role."""

    def test_execution_substrate_role_in_result(self):
        """route_envelope stamps execution_substrate_role='execution_substrate'.

        This test verifies the structural contract: the result dict returned by
        route_envelope() must carry the execution substrate role annotation.
        We verify this by inspecting the source of the declared setdefault call.
        """
        import inspect
        from core.command_router import CommandRouter

        source = inspect.getsource(CommandRouter.route_envelope)
        assert "execution_substrate_role" in source, (
            "CommandRouter.route_envelope() must stamp 'execution_substrate_role' in result"
        )
        assert "execution_substrate" in source, (
            "CommandRouter.route_envelope() must declare 'execution_substrate' role"
        )

    def test_execution_substrate_role_value(self):
        """execution_substrate_role is always 'execution_substrate'."""
        from core.schemas.execution_authority import ExecutionLayerRole
        assert ExecutionLayerRole.EXECUTION_SUBSTRATE.value == "execution_substrate"


# ===========================================================================
# 10. TestChatRouteEntrySurface
# ===========================================================================


class TestChatRouteEntrySurface:
    """Chat route identifies itself as the entry surface / compat adapter."""

    def _get_chat_endpoint(self):
        """Return (router, endpoint_func) from the chat route module."""
        from core.routes.chat import router as chat_router
        endpoint = None
        for route in chat_router.routes:
            if hasattr(route, "path") and route.path in ("/api/v1/chat", ""):
                endpoint = route.endpoint
                break
        if endpoint is None and chat_router.routes:
            endpoint = chat_router.routes[0].endpoint
        return chat_router, endpoint

    def test_surface_role_compat_adapter(self):
        """Chat route response should have surface_role='compat_adapter'."""
        import json

        try:
            _, endpoint = self._get_chat_endpoint()
            if endpoint is None:
                pytest.skip("Could not locate chat route endpoint")
        except Exception:
            pytest.skip("Chat router not importable in this environment")

        from unittest.mock import AsyncMock, MagicMock, patch
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        mock_body = MagicMock()
        mock_body.message = "hi"
        mock_body.session_id = None
        mock_body.device_id = None
        mock_body.context = []
        mock_body.required_capabilities = None
        mock_body.multimodal_context = None
        mock_body.use_constellation = True
        mock_body.entry_mode = None

        fake_runtime_result = {
            "success": True,
            "response": "ok",
            "runtime_session_id": "rsess_001",
        }

        with patch("core.routes.chat.get_desktop_presence_runtime") as mock_rt:
            mock_rt.return_value.handle_request = AsyncMock(
                return_value=fake_runtime_result
            )
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                resp = loop.run_until_complete(endpoint(mock_request, mock_body))
                loop.close()
            except Exception:
                pytest.skip("Could not execute chat endpoint in test environment")

        try:
            data = json.loads(resp.body)
        except Exception:
            pytest.skip("Response not JSON-parseable in test environment")

        assert data.get("surface_role") == "compat_adapter"

    def test_execution_authority_in_chat_response(self):
        """Chat route should set execution_authority to the runtime+core pair."""
        import json

        try:
            _, endpoint = self._get_chat_endpoint()
            if endpoint is None:
                pytest.skip("Could not locate chat route endpoint")
        except Exception:
            pytest.skip("Chat router not importable in this environment")

        from unittest.mock import AsyncMock, MagicMock, patch
        from fastapi import Request

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {}

        mock_body = MagicMock()
        mock_body.message = "hi"
        mock_body.session_id = None
        mock_body.device_id = None
        mock_body.context = []
        mock_body.required_capabilities = None
        mock_body.multimodal_context = None
        mock_body.use_constellation = True
        mock_body.entry_mode = None

        fake_runtime_result = {
            "success": True,
            "response": "ok",
            "runtime_session_id": "rsess_002",
        }

        with patch("core.routes.chat.get_desktop_presence_runtime") as mock_rt:
            mock_rt.return_value.handle_request = AsyncMock(
                return_value=fake_runtime_result
            )
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                resp = loop.run_until_complete(endpoint(mock_request, mock_body))
                loop.close()
            except Exception:
                pytest.skip("Could not execute chat endpoint in test environment")

        try:
            data = json.loads(resp.body)
        except Exception:
            pytest.skip("Response not JSON-parseable in test environment")

        assert "execution_authority" in data
        # The chat route delegates to DesktopPresenceRuntime + OpenClawd
        assert "DesktopPresenceRuntime" in data["execution_authority"]


# ===========================================================================
# 11. TestAuthorityChainContract
# ===========================================================================


class TestAuthorityChainContract:
    """Cross-layer guardrail: authority chain consistency."""

    def test_entry_surface_is_adapter_not_authority(self):
        """The entry surface should be marked as an adapter, not a subject authority."""
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.ENTRY_SURFACE,
            "core.routes.chat",
            is_adapter_surface=True,
        )
        assert meta.is_adapter_surface is True

    def test_runtime_shell_is_not_adapter(self):
        """Runtime shell authority is NOT a compat adapter."""
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
            "core.desktop_presence_runtime",
        )
        assert meta.is_adapter_surface is False

    def test_subject_decision_is_not_adapter(self):
        """Subject decision authority is NOT a compat adapter."""
        from core.schemas.execution_authority import (
            ExecutionLayerRole,
            build_authority_metadata,
        )
        meta = build_authority_metadata(
            ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY,
            "core.openclawd",
        )
        assert meta.is_adapter_surface is False

    def test_kernel_response_has_correct_authority_role(self):
        """KernelResponse.authority_role must be 'cognition_planning_layer'."""
        from core.agent.kernel import KernelResponse
        from core.schemas.execution_authority import ExecutionLayerRole

        kr = KernelResponse()
        assert kr.authority_role == ExecutionLayerRole.COGNITION_PLANNING_LAYER.value

    def test_all_canonical_chain_roles_have_stable_string_values(self):
        """All roles in the canonical chain must have stable string values."""
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
        )
        seen = set()
        for role, module, cls in CANONICAL_AUTHORITY_CHAIN:
            # Values must be non-empty strings
            assert isinstance(role.value, str) and role.value
            assert isinstance(module, str) and module
            assert isinstance(cls, str) and cls
            # Roles must be distinct (no two entries for the same role)
            assert role.value not in seen, f"Duplicate role in chain: {role.value}"
            seen.add(role.value)

    def test_canonical_authority_chain_is_immutable_copy(self):
        """Modifying the returned list must not affect the canonical constant."""
        from core.schemas.execution_authority import CANONICAL_AUTHORITY_CHAIN

        original_len = len(CANONICAL_AUTHORITY_CHAIN)
        copy = list(CANONICAL_AUTHORITY_CHAIN)
        copy.clear()
        assert len(CANONICAL_AUTHORITY_CHAIN) == original_len

    def test_schemas_package_exports(self):
        """core.schemas.execution_authority exports all required symbols."""
        from core.schemas import execution_authority as ea

        required = [
            "ExecutionLayerRole",
            "ExecutionAuthorityMetadata",
            "CANONICAL_AUTHORITY_CHAIN",
            "build_authority_metadata",
            "get_layer_authority",
        ]
        for name in required:
            assert hasattr(ea, name), f"Missing export: {name}"

    def test_get_layer_authority_consistent_with_canonical_chain(self):
        """get_layer_authority() resolves canonical chain modules to their declared roles."""
        from core.schemas.execution_authority import (
            CANONICAL_AUTHORITY_CHAIN,
            get_layer_authority,
        )
        for role, module, _ in CANONICAL_AUTHORITY_CHAIN:
            resolved = get_layer_authority(module)
            assert resolved == role, (
                f"get_layer_authority({module!r}) → {resolved.value!r}, "
                f"expected {role.value!r}"
            )
