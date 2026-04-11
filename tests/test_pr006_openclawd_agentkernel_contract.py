"""
tests/test_pr006_openclawd_agentkernel_contract.py
====================================================

PR-006: Tighten OpenClawd–AgentKernel execution and routing contract.

Validates that:

KernelResponse Contract Fields (PR-006)
  1.  KernelResponse has ``soul_injection_phase`` field (None by default).
  2.  KernelResponse has ``routing_authority`` field (always "advisory_to_openclawd").
  3.  ``soul_injection_phase`` appears in ``to_api_dict()`` output.
  4.  ``routing_authority`` appears in ``to_api_dict()`` output.
  5.  ``routing_authority`` is always "advisory_to_openclawd" (never changes).

SOUL Injection Boundary
  6.  chat_only KernelResponse has ``soul_injection_phase = None``.
  7.  task_execute KernelResponse has ``soul_injection_phase = "task_execute"``.
  8.  hybrid KernelResponse has ``soul_injection_phase = "hybrid"``.
  9.  AgentKernel class docstring explicitly states SOUL injection boundary.
  10. Module docstring explicitly states SOUL injection boundary.

delegation_hint Advisory Contract
  11. ``delegation_hint`` defaults to None (no mandatory hint).
  12. OpenClawd process() metadata includes ``delegation_hint_decision``.
  13. When hint is None, ``delegation_hint_decision`` == "advisory_none".
  14. When hint is set, ``delegation_hint_decision`` == "advisory_noted".
  15. AgentKernel docstring explicitly states delegation_hint is advisory.

Multi-model Routing Authority
  16. ``KernelResponse.routing_authority`` is "advisory_to_openclawd".
  17. OpenClawd process() metadata includes ``kernel_routing_authority``.
  18. ``kernel_routing_authority`` in metadata is "advisory_to_openclawd".
  19. AgentKernel docstring explicitly states routing authority belongs to OpenClawd.

Authority Chain Consistency
  20. KernelResponse.authority_role is "cognition_planning_layer".
  21. KernelResponse.arch_layer_id (via to_api_dict) is "cognition_layer".
  22. ExecutionLayerRole.COGNITION_PLANNING_LAYER docstring references PR-006.
"""

from __future__ import annotations

import pathlib
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO_ROOT = pathlib.Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_kernel_response(
    *,
    mode: str = "chat_only",
    delegation_hint: Optional[str] = None,
    soul_injection_phase: Optional[str] = None,
):
    from core.agent.kernel import KernelResponse
    from core.agent.intent_router import IntentResult

    return KernelResponse(
        success=True,
        mode=mode,
        reply="hello",
        model="test-model",
        session_id="test-session",
        intent=IntentResult(mode=mode, raw_intent=mode, confidence=0.9),
        delegation_hint=delegation_hint,
        soul_injection_phase=soul_injection_phase,
    )


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
    # Bypass initialization guard (consistent with test_pr4_agent_kernel_boundary.py)
    oc._ensure_initialized = lambda: None
    return oc


async def _run_process(
    oc,
    mock_kernel,
    *,
    message: str = "hello",
    session_id: str = "s1",
    continuum_state: Optional[Dict[str, Any]] = None,
    execution_result: Optional[Dict[str, Any]] = None,
    execution_path: str = "none",
    **process_kwargs: Any,
) -> dict:
    """Run oc.process() with all heavy side-effects patched out.

    Returns the result dict from process().
    """
    with patch.object(oc, "_get_kernel", return_value=mock_kernel), patch.object(
        oc, "_get_router", return_value=None
    ), patch.object(
        oc, "_parse_intent", new_callable=AsyncMock
    ), patch.object(
        oc, "_run_continuum", return_value=continuum_state
    ), patch.object(
        oc, "_run_execution", return_value=execution_result or {}
    ), patch.object(
        oc, "_determine_execution_path", return_value=execution_path
    ), patch.object(
        oc, "_build_execution_plan", return_value=None
    ), patch.object(
        oc, "_finalise_plan_lifecycle", return_value=None
    ), patch.object(
        oc, "_build_unified_control_plan", return_value=None
    ), patch.object(
        oc, "_record_turn", new_callable=AsyncMock
    ), patch.object(
        oc, "sync_device_capabilities", return_value=None
    ):
        return await oc.process(message=message, session_id=session_id, **process_kwargs)


def _make_kernel_mock(
    *,
    delegation_hint: Optional[str] = None,
    soul_injection_phase: Optional[str] = None,
    mode: str = "chat_only",
):
    """Build an AsyncMock that returns a realistic KernelResponse."""
    from core.agent.kernel import KernelResponse
    from core.agent.intent_router import IntentResult

    kr = KernelResponse(
        success=True,
        mode=mode,
        reply="test reply",
        model="test-model",
        session_id="test-session",
        intent=IntentResult(mode=mode, raw_intent=mode, confidence=0.9),
        delegation_hint=delegation_hint,
        soul_injection_phase=soul_injection_phase,
    )
    mock_kernel = MagicMock()
    mock_kernel.handle_message = AsyncMock(return_value=kr)
    return mock_kernel


# ---------------------------------------------------------------------------
# 1-5  KernelResponse Contract Fields
# ---------------------------------------------------------------------------


class TestKernelResponseContractFields:
    """PR-006 contract fields must be present in KernelResponse."""

    def test_soul_injection_phase_field_exists(self):
        """KernelResponse must have a soul_injection_phase field."""
        from core.agent.kernel import KernelResponse

        fields = KernelResponse.model_fields
        assert "soul_injection_phase" in fields, (
            "KernelResponse must have 'soul_injection_phase' field (PR-006)."
        )

    def test_routing_authority_field_exists(self):
        """KernelResponse must have a routing_authority field."""
        from core.agent.kernel import KernelResponse

        fields = KernelResponse.model_fields
        assert "routing_authority" in fields, (
            "KernelResponse must have 'routing_authority' field (PR-006)."
        )

    def test_soul_injection_phase_in_api_dict(self):
        """soul_injection_phase must appear in to_api_dict() output."""
        kr = _make_kernel_response()
        api = kr.to_api_dict()
        assert "soul_injection_phase" in api, (
            "KernelResponse.to_api_dict() must include 'soul_injection_phase'."
        )

    def test_routing_authority_in_api_dict(self):
        """routing_authority must appear in to_api_dict() output."""
        kr = _make_kernel_response()
        api = kr.to_api_dict()
        assert "routing_authority" in api, (
            "KernelResponse.to_api_dict() must include 'routing_authority'."
        )

    def test_routing_authority_is_advisory_to_openclawd(self):
        """routing_authority must always be 'advisory_to_openclawd'."""
        kr = _make_kernel_response()
        assert kr.routing_authority == "advisory_to_openclawd", (
            "KernelResponse.routing_authority must be 'advisory_to_openclawd' "
            "to make explicit that AgentKernel does not own routing authority."
        )
        # Also verify in to_api_dict()
        assert kr.to_api_dict()["routing_authority"] == "advisory_to_openclawd"


# ---------------------------------------------------------------------------
# 6-10  SOUL Injection Boundary
# ---------------------------------------------------------------------------


class TestSoulInjectionBoundary:
    """SOUL must only be injected in task_execute / hybrid phases."""

    def test_chat_only_soul_injection_phase_is_none(self):
        """chat_only KernelResponse must have soul_injection_phase=None."""
        kr = _make_kernel_response(mode="chat_only", soul_injection_phase=None)
        assert kr.soul_injection_phase is None, (
            "chat_only KernelResponse must have soul_injection_phase=None — "
            "SOUL is never loaded in the pure chat path."
        )

    def test_task_execute_soul_injection_phase(self):
        """task_execute KernelResponse must carry soul_injection_phase='task_execute'."""
        kr = _make_kernel_response(
            mode="task_execute", soul_injection_phase="task_execute"
        )
        assert kr.soul_injection_phase == "task_execute"

    def test_hybrid_soul_injection_phase(self):
        """hybrid KernelResponse must carry soul_injection_phase='hybrid'."""
        kr = _make_kernel_response(mode="hybrid", soul_injection_phase="hybrid")
        assert kr.soul_injection_phase == "hybrid"

    def test_agent_kernel_docstring_states_soul_boundary(self):
        """AgentKernel class docstring must state SOUL injection boundary."""
        from core.agent.kernel import AgentKernel

        doc = AgentKernel.__doc__ or ""
        assert "SOUL" in doc, (
            "AgentKernel class docstring must mention SOUL injection boundary."
        )
        assert "task_execute" in doc or "hybrid" in doc, (
            "AgentKernel class docstring must mention task_execute or hybrid "
            "as the phases where SOUL is injected."
        )

    def test_module_docstring_states_soul_boundary(self):
        """Module docstring must state SOUL injection boundary."""
        import core.agent.kernel as kernel_mod

        doc = kernel_mod.__doc__ or ""
        assert "SOUL" in doc, (
            "core/agent/kernel.py module docstring must mention SOUL."
        )
        assert "task_execute" in doc or "hybrid" in doc, (
            "Module docstring must describe the execution phases where SOUL "
            "is injected."
        )


# ---------------------------------------------------------------------------
# 11-15  delegation_hint Advisory Contract
# ---------------------------------------------------------------------------


class TestDelegationHintAdvisory:
    """delegation_hint must be treated as advisory-only throughout the stack."""

    def test_delegation_hint_default_is_none(self):
        """delegation_hint must default to None."""
        kr = _make_kernel_response()
        assert kr.delegation_hint is None

    @pytest.mark.asyncio
    async def test_process_metadata_includes_delegation_hint_decision(self):
        """OpenClawd process() metadata must include delegation_hint_decision."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock(delegation_hint=None)
        result = await _run_process(oc, mock_kernel)

        meta = result.get("metadata", {})
        assert "delegation_hint_decision" in meta, (
            "OpenClawd process() metadata must include 'delegation_hint_decision' "
            "to record how the advisory hint was treated (PR-006)."
        )

    @pytest.mark.asyncio
    async def test_process_delegation_hint_decision_advisory_none_when_no_hint(self):
        """delegation_hint_decision must be 'advisory_none' when hint is None."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock(delegation_hint=None)
        result = await _run_process(oc, mock_kernel)

        meta = result.get("metadata", {})
        assert meta.get("delegation_hint_decision") == "advisory_none", (
            "When delegation_hint is None, metadata.delegation_hint_decision "
            "must be 'advisory_none'."
        )

    @pytest.mark.asyncio
    async def test_process_delegation_hint_decision_advisory_noted_when_hint_set(self):
        """delegation_hint_decision must be 'advisory_noted' when hint is present."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock(delegation_hint="local")
        result = await _run_process(oc, mock_kernel)

        meta = result.get("metadata", {})
        assert meta.get("delegation_hint_decision") == "advisory_noted", (
            "When delegation_hint is set, metadata.delegation_hint_decision "
            "must be 'advisory_noted' — hint is logged but remains advisory."
        )

    def test_agent_kernel_docstring_states_delegation_hint_advisory(self):
        """AgentKernel docstring must explicitly state delegation_hint is advisory."""
        from core.agent.kernel import AgentKernel

        doc = AgentKernel.__doc__ or ""
        lower = doc.lower()
        assert "advisory" in lower or "建议" in doc, (
            "AgentKernel class docstring must state that delegation_hint is "
            "advisory only (PR-006)."
        )

    @pytest.mark.asyncio
    async def test_kernel_path_receives_fused_multimodal_message(self):
        """Multimodal fusion suffix must be threaded into kernel.handle_message()."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock(delegation_hint=None)
        fused = "[multimodal_fusion_summary] image=present"

        with patch(
            "core.perception.multimodal_bus.MultimodalBus.ingest",
            return_value={"fusion_summary": fused},
        ):
            result = await _run_process(
                oc,
                mock_kernel,
                message="hello",
                multimodal_context=object(),
            )

        call_kwargs = mock_kernel.handle_message.call_args.kwargs
        assert call_kwargs["message"] == f"hello\n\n{fused}", (
            "OpenClawd must pass fused multimodal content to AgentKernel.handle_message() "
            "instead of silently sending bare text."
        )
        assert result.get("metadata", {}).get("kernel_received_fused_multimodal_content") is True

    @pytest.mark.asyncio
    async def test_cognitive_execution_hint_metadata_explicitly_non_binding(self):
        """Cognitive execution-path preference must be surfaced as advisory-only metadata."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock(delegation_hint=None)

        class _Hint:
            cognitive_region = "liminal"
            execution_path_preference = "planning"
            activation_budget = 0.6

            def to_dict(self):
                return {
                    "cognitive_region": self.cognitive_region,
                    "execution_path_preference": self.execution_path_preference,
                    "activation_budget": self.activation_budget,
                }

        result = await _run_process(
            oc,
            mock_kernel,
            cognitive_execution_hint=_Hint(),
        )

        cog_hint = result.get("metadata", {}).get("cognitive_execution_hint") or {}
        assert cog_hint.get("hint_authority") == "advisory_only"
        assert cog_hint.get("execution_path_preference_binding") == "advisory_only_non_binding"
        assert cog_hint.get("influences_execution_path_routing") is False


# ---------------------------------------------------------------------------
# 16-19  Multi-model Routing Authority
# ---------------------------------------------------------------------------


class TestMultiModelRoutingAuthority:
    """Final multi-model routing authority must reside with OpenClawd."""

    def test_kernel_response_routing_authority_is_advisory(self):
        """KernelResponse.routing_authority must be 'advisory_to_openclawd'."""
        kr = _make_kernel_response()
        assert kr.routing_authority == "advisory_to_openclawd", (
            "KernelResponse.routing_authority must be 'advisory_to_openclawd' — "
            "AgentKernel does not hold final routing authority."
        )

    @pytest.mark.asyncio
    async def test_process_metadata_includes_kernel_routing_authority(self):
        """OpenClawd process() metadata must include kernel_routing_authority."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock()
        result = await _run_process(oc, mock_kernel)

        meta = result.get("metadata", {})
        assert "kernel_routing_authority" in meta, (
            "OpenClawd process() metadata must include 'kernel_routing_authority' "
            "to make explicit that AgentKernel routing is advisory (PR-006)."
        )

    @pytest.mark.asyncio
    async def test_process_kernel_routing_authority_value(self):
        """kernel_routing_authority in metadata must be 'advisory_to_openclawd'."""
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock()
        result = await _run_process(oc, mock_kernel)

        meta = result.get("metadata", {})
        assert meta.get("kernel_routing_authority") == "advisory_to_openclawd", (
            "metadata.kernel_routing_authority must be 'advisory_to_openclawd'."
        )

    def test_agent_kernel_docstring_states_routing_authority_belongs_to_openclawd(self):
        """AgentKernel docstring must state routing authority belongs to OpenClawd."""
        from core.agent.kernel import AgentKernel

        doc = AgentKernel.__doc__ or ""
        assert "路由" in doc or "routing" in doc.lower(), (
            "AgentKernel class docstring must reference routing authority (PR-006)."
        )
        assert "OpenClawd" in doc, (
            "AgentKernel class docstring must state that OpenClawd owns routing "
            "authority."
        )


# ---------------------------------------------------------------------------
# 19b  Kernel intent vs continuum action semantics
# ---------------------------------------------------------------------------


class TestExecutionSemanticsDiagnostics:
    @pytest.mark.asyncio
    async def test_metadata_exposes_divergence_between_kernel_intent_and_execution_path(self):
        oc = _make_openclawd()
        mock_kernel = _make_kernel_mock(mode="task_execute")
        result = await _run_process(
            oc,
            mock_kernel,
            continuum_state={"decision": {"action_level": "observe"}},
            execution_result={"action_taken": "none"},
            execution_path="none",
        )

        semantics = result.get("metadata", {}).get("execution_semantics") or {}
        assert semantics.get("decision_tracks") == "dual_track"
        assert semantics.get("kernel_intent_mode") == "task_execute"
        assert semantics.get("continuum_action_level") == "observe"
        assert semantics.get("execution_path") == "none"
        assert semantics.get("intent_action_alignment") == "divergent"
        assert semantics.get("execution_path_source") == "OpenClawd._determine_execution_path"
        pr14_status = result.get("metadata", {}).get("pr14_activation_runtime_status")
        assert isinstance(pr14_status, dict)
        assert pr14_status.get("pr14_activation_model_available") is True
        assert pr14_status.get("dispatch_time_enforced") is False
        assert isinstance(pr14_status.get("dispatch_authority_layers"), list)

    @pytest.mark.asyncio
    async def test_handler_metadata_cannot_override_openclawd_authority(self):
        from core.ai_intent import ParsedIntent

        oc = _make_openclawd()
        parsed_intent = ParsedIntent(
            intent="chat",
            command="chat",
            targets=[],
            params={},
            confidence=0.9,
            raw_text="hello",
            context_used=False,
            suggestions=[],
        )
        handler_result = {
            "success": True,
            "response": "ok",
            "metadata": {
                "remote_dispatch": True,
                "execution_path": "cross_device",
                "execution_semantics": {"execution_path_source": "handler_override"},
                "pr14_activation_runtime_status": {"dispatch_time_enforced": True},
            },
        }

        with patch.object(oc, "_get_kernel", return_value=None), patch.object(
            oc, "_get_router", return_value=None
        ), patch.object(
            oc, "_parse_intent", new_callable=AsyncMock, return_value=parsed_intent
        ), patch.object(
            oc, "_dispatch_chat", new_callable=AsyncMock, return_value=handler_result
        ), patch.object(
            oc, "_run_continuum", return_value={"decision": {"action_level": "observe"}}
        ), patch.object(
            oc, "_run_execution", return_value={"action_taken": "none"}
        ), patch.object(
            oc, "_determine_execution_path", return_value="none"
        ), patch.object(
            oc, "_build_execution_plan", return_value=None
        ), patch.object(
            oc, "_finalise_plan_lifecycle", return_value=None
        ), patch.object(
            oc, "_build_unified_control_plan", return_value=None
        ), patch.object(
            oc, "_record_turn", new_callable=AsyncMock
        ), patch.object(
            oc, "sync_device_capabilities", return_value=None
        ):
            result = await oc.process(message="hello", session_id="s1")

        meta = result.get("metadata", {})
        assert meta.get("remote_dispatch") is True
        assert meta.get("execution_path") == "none"
        assert meta.get("execution_semantics", {}).get("execution_path_source") == (
            "OpenClawd._determine_execution_path"
        )
        assert meta.get("pr14_activation_runtime_status", {}).get("dispatch_time_enforced") is False

# ---------------------------------------------------------------------------
# 20-22  Authority Chain Consistency
# ---------------------------------------------------------------------------


class TestAuthorityChainConsistency:
    """KernelResponse authority annotations must be consistent with PR-9 chain."""

    def test_authority_role_is_cognition_planning_layer(self):
        """KernelResponse.authority_role must be 'cognition_planning_layer'."""
        kr = _make_kernel_response()
        assert kr.authority_role == "cognition_planning_layer", (
            "KernelResponse.authority_role must be 'cognition_planning_layer' "
            "consistent with PR-9 execution authority contract."
        )

    def test_arch_layer_id_in_api_dict_is_cognition_layer(self):
        """to_api_dict() arch_layer_id must be 'cognition_layer'."""
        kr = _make_kernel_response()
        api = kr.to_api_dict()
        assert api.get("arch_layer_id") == "cognition_layer", (
            "KernelResponse.to_api_dict()['arch_layer_id'] must be 'cognition_layer' "
            "consistent with PR-10 architecture diagnostics."
        )

    def test_execution_authority_schema_cognition_layer_references_pr006(self):
        """ExecutionLayerRole.COGNITION_PLANNING_LAYER doc must reference PR-006."""
        from core.schemas.execution_authority import ExecutionLayerRole

        # Get the docstring for the enum member
        import inspect

        source = inspect.getsource(ExecutionLayerRole)
        assert "PR-006" in source, (
            "ExecutionLayerRole source must reference PR-006 in the "
            "COGNITION_PLANNING_LAYER documentation."
        )
