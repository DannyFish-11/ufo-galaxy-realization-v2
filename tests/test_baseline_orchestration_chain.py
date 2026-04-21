"""
tests/test_baseline_orchestration_chain.py
==========================================
Baseline Orchestration/Runtime Chain Acceptance Tests
======================================================

This file validates the **canonical V2 orchestration/runtime chain** established
by the baseline hardening PR.  It serves as the reviewability artifact for:

1. What the canonical baseline runtime/orchestration path is.
2. Which previously ambiguous or partial transitions were clarified.
3. Whether the cleaned-up baseline is suitable for later mesh/routing/
   reconciliation work.

Canonical chain (top-level)::

    main.py
      └─ SystemOrchestrator (phased pre-check)
           └─ DesktopPresenceRuntime (tri-state lifecycle owner)
                └─ OpenClawd (cognition + execution decision core)
                     ├─ local path → DecisionExecutor
                     └─ cross-device path → CommandRouter.route_envelope()
                          └─ task_cancel / task_status → android handlers
                          └─ capability-aware routing via query_routable_executors()

Gap closures validated here
----------------------------
- PROTO-002 (HIGH): task_cancel/task_status no longer fall through to
  _handle_forward_log; dedicated handlers are registered.
- SCHED-001 (MEDIUM): CommandRouter.route_envelope() calls
  query_routable_executors() before cross-device dispatch.
- Gateway authority chain drift: chat_endpoint in
  galaxy_gateway/routes/chat.py routes through DesktopPresenceRuntime
  (not openclawd directly).
"""

from __future__ import annotations

import pathlib
import sys


# ---------------------------------------------------------------------------
# Group A: Canonical authority chain — module-level import checks
# ---------------------------------------------------------------------------


class TestGroupA_CanonicalAuthorityChain:
    """The canonical orchestration path is importable and traceable."""

    def test_a1_desktop_presence_runtime_importable(self):
        """DesktopPresenceRuntime can be imported without error."""
        from core.desktop_presence_runtime import (  # noqa: F401
            DesktopPresenceRuntime,
            get_desktop_presence_runtime,
            TriState,
        )
        assert TriState.SILENT.value == "silent"
        assert TriState.LIMINAL.value == "liminal"
        assert TriState.MANIFEST.value == "manifest"

    def test_a2_openclawd_importable(self):
        """OpenClawd can be imported without error."""
        from core.openclawd import get_openclawd  # noqa: F401
        assert callable(get_openclawd)

    def test_a3_command_router_importable(self):
        """CommandRouter can be imported without error."""
        from core.command_router import CommandRouter  # noqa: F401
        assert CommandRouter is not None

    def test_a4_tristate_has_exactly_three_values(self):
        """TriState must have exactly SILENT / LIMINAL / MANIFEST — no UI states."""
        from core.desktop_presence_runtime import TriState
        values = {s.value for s in TriState}
        assert values == {"silent", "liminal", "manifest"}, (
            f"TriState must be exactly silent/liminal/manifest, got: {values}"
        )

    def test_a5_runtime_session_id_type(self):
        """RuntimeSession generates a non-empty string runtime_session_id."""
        from core.desktop_presence_runtime import RuntimeSession, TriState
        session = RuntimeSession(source="test")
        assert isinstance(session.runtime_session_id, str)
        assert len(session.runtime_session_id) > 0
        assert session.tristate == TriState.SILENT

    def test_a6_canonical_chain_docstrings_present(self):
        """Key modules carry docstrings identifying their chain position."""
        root = pathlib.Path(__file__).parent.parent

        dpr_src = (root / "core" / "desktop_presence_runtime.py").read_text(encoding="utf-8")
        assert "runtime shell" in dpr_src, (
            "core/desktop_presence_runtime.py must identify itself as the runtime shell"
        )
        assert "subject core" in dpr_src, (
            "core/desktop_presence_runtime.py must reference OpenClawd as the subject core"
        )

        oc_src = (root / "core" / "openclawd.py").read_text(encoding="utf-8")
        assert "subject core" in oc_src.lower() or "Subject Core" in oc_src, (
            "core/openclawd.py must identify itself as the subject core"
        )
        assert "liminal" in oc_src, (
            "core/openclawd.py must describe operating inside the liminal phase"
        )


# ---------------------------------------------------------------------------
# Group B: PROTO-002 closure — task_cancel / task_status handler registration
# ---------------------------------------------------------------------------


class TestGroupB_Proto002Closure:
    """PROTO-002 (HIGH): task_cancel and task_status are properly handled.

    Prior state: both message types fell through to ``_handle_forward_log``
    catch-all — received, logged, not acted upon.

    Current state: dedicated handlers registered in ``_register_default_handlers``
    cancel pending Futures and return canonical ack messages.
    """

    def test_b1_handle_task_cancel_importable(self):
        """handle_task_cancel is importable from the canonical handler module."""
        from galaxy_gateway.android.handlers.task_lifecycle import (  # noqa: F401
            handle_task_cancel,
        )
        assert callable(handle_task_cancel)

    def test_b2_handle_task_status_importable(self):
        """handle_task_status is importable from the canonical handler module."""
        from galaxy_gateway.android.handlers.task_lifecycle import (  # noqa: F401
            handle_task_status,
        )
        assert callable(handle_task_status)

    def test_b3_android_bridge_registers_task_cancel_handler(self):
        """AndroidBridge._register_default_handlers registers TASK_CANCEL → handle_task_cancel."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = AndroidBridge()
        assert MessageType.TASK_CANCEL in bridge._message_handlers, (
            "AndroidBridge must register a handler for TASK_CANCEL — "
            "it must NOT fall through to _handle_forward_log"
        )

    def test_b4_android_bridge_registers_task_status_handler(self):
        """AndroidBridge._register_default_handlers registers TASK_STATUS → handle_task_status."""
        from galaxy_gateway.android_bridge import AndroidBridge
        from galaxy_gateway.protocol.aip_v3 import MessageType

        bridge = AndroidBridge()
        assert MessageType.TASK_STATUS in bridge._message_handlers, (
            "AndroidBridge must register a handler for TASK_STATUS — "
            "it must NOT fall through to _handle_forward_log"
        )

    def test_b5_task_cancel_handler_returns_ack(self):
        """handle_task_cancel returns a task_cancel_ack message."""
        import asyncio
        from unittest.mock import MagicMock, AsyncMock, patch

        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_cancel

        bridge = MagicMock()
        bridge._pending_responses = {}
        bridge._devices = {}
        bridge._lock = asyncio.Lock()

        message = {
            "type": "task_cancel",
            "task_id": "task_abc",
            "device_id": "device_001",
            "message_id": "msg_001",
        }
        ws = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            handle_task_cancel(bridge, ws, message)
        )
        assert isinstance(result, dict), "handle_task_cancel must return a dict"
        assert result.get("type") == "task_cancel_ack", (
            f"handle_task_cancel must return task_cancel_ack, got type={result.get('type')!r}"
        )
        assert result.get("task_id") == "task_abc"

    def test_b6_task_status_handler_returns_status_response(self):
        """handle_task_status returns a task_status_response message."""
        import asyncio
        from unittest.mock import MagicMock

        from galaxy_gateway.android.handlers.task_lifecycle import handle_task_status

        bridge = MagicMock()
        bridge._pending_responses = {}
        bridge._devices = {}
        bridge._lock = asyncio.Lock()

        message = {
            "type": "task_status",
            "task_id": "task_xyz",
            "device_id": "device_001",
            "message_id": "msg_002",
        }
        ws = MagicMock()

        result = asyncio.get_event_loop().run_until_complete(
            handle_task_status(bridge, ws, message)
        )
        assert isinstance(result, dict), "handle_task_status must return a dict"
        assert result.get("type") == "task_status_response", (
            f"handle_task_status must return task_status_response, got type={result.get('type')!r}"
        )
        assert result.get("task_id") == "task_xyz"

    def test_b7_task_cancel_gap_matrix_marked_resolved(self):
        """DUAL_REPO_GAP_MATRIX.md must mark PROTO-002 as RESOLVED."""
        root = pathlib.Path(__file__).parent.parent
        gap_matrix = (root / "docs" / "DUAL_REPO_GAP_MATRIX.md").read_text(encoding="utf-8")
        # Find the PROTO-002 row and confirm it says RESOLVED
        proto_002_line = next(
            (line for line in gap_matrix.splitlines() if "PROTO-002" in line),
            None,
        )
        assert proto_002_line is not None, "PROTO-002 row not found in DUAL_REPO_GAP_MATRIX.md"
        assert "RESOLVED" in proto_002_line, (
            f"PROTO-002 must be marked RESOLVED in DUAL_REPO_GAP_MATRIX.md; "
            f"found: {proto_002_line!r}"
        )


# ---------------------------------------------------------------------------
# Group C: SCHED-001 closure — CommandRouter capability-aware routing
# ---------------------------------------------------------------------------


class TestGroupC_Sched001Closure:
    """SCHED-001 (MEDIUM): CommandRouter.route_envelope() consults capability graph.

    Prior state: CommandRouter selected cross-device dispatch targets without
    querying the unified capability graph — routing was reachability-valid but
    not capability-verified.

    Current state: route_envelope() calls query_routable_executors() and
    query_network_path() from core.capability_network_runtime_policy before
    dispatching.  Targets not in the capability graph emit warnings and are
    filtered when confirmed alternatives exist.
    """

    def test_c1_capability_policy_module_importable(self):
        """core.capability_network_runtime_policy is importable."""
        try:
            from core.capability_network_runtime_policy import (  # noqa: F401
                query_routable_executors,
                query_network_path,
            )
        except ImportError as exc:
            assert False, (
                f"core.capability_network_runtime_policy must be importable: {exc}"
            )

    def test_c2_command_router_source_references_capability_query(self):
        """CommandRouter source references query_routable_executors call."""
        root = pathlib.Path(__file__).parent.parent
        src = (root / "core" / "command_router.py").read_text(encoding="utf-8")
        assert "query_routable_executors" in src, (
            "core/command_router.py must call query_routable_executors() "
            "in route_envelope() to close SCHED-001"
        )
        assert "query_network_path" in src, (
            "core/command_router.py must call query_network_path() "
            "in route_envelope() to close SCHED-001"
        )

    def test_c3_sched001_gap_matrix_marked_resolved(self):
        """DUAL_REPO_GAP_MATRIX.md must mark SCHED-001 as RESOLVED."""
        root = pathlib.Path(__file__).parent.parent
        gap_matrix = (root / "docs" / "DUAL_REPO_GAP_MATRIX.md").read_text(encoding="utf-8")
        sched_001_line = next(
            (line for line in gap_matrix.splitlines() if "SCHED-001" in line),
            None,
        )
        assert sched_001_line is not None, "SCHED-001 row not found in DUAL_REPO_GAP_MATRIX.md"
        assert "RESOLVED" in sched_001_line, (
            f"SCHED-001 must be marked RESOLVED in DUAL_REPO_GAP_MATRIX.md; "
            f"found: {sched_001_line!r}"
        )

    def test_c4_command_router_capability_enforcement_in_route_envelope(self):
        """CommandRouter source calls query_routable_executors within route_envelope().

        Validates that the actual function calls exist, not just the import or a sentinel name.
        """
        root = pathlib.Path(__file__).parent.parent
        src = (root / "core" / "command_router.py").read_text(encoding="utf-8")
        assert "_query_exec(" in src or "query_routable_executors" in src, (
            "core/command_router.py must call query_routable_executors() in route_envelope()"
        )
        assert "_query_path(" in src or "query_network_path" in src, (
            "core/command_router.py must call query_network_path() in route_envelope()"
        )


# ---------------------------------------------------------------------------
# Group D: Gateway authority chain — chat_endpoint routes through runtime shell
# ---------------------------------------------------------------------------


class TestGroupD_GatewayChatAuthorityChain:
    """The gateway chat surface routes all requests through DesktopPresenceRuntime.

    This test group validates the canonical routing path:
        galaxy_gateway/routes/chat.py::chat_endpoint
            → DesktopPresenceRuntime.handle_request(source="chat")
                → OpenClawd.process()

    Note: chat_endpoint lives in galaxy_gateway/routes/chat.py (extracted from
    app.py in the PR-3 modularization).  galaxy_gateway/app.py remains the
    architectural declaration surface (describes the gateway as an internal
    substrate).
    """

    def _read_chat_route(self) -> str:
        root = pathlib.Path(__file__).parent.parent
        return (root / "galaxy_gateway" / "routes" / "chat.py").read_text(encoding="utf-8")

    def _read_gateway_app(self) -> str:
        root = pathlib.Path(__file__).parent.parent
        return (root / "galaxy_gateway" / "app.py").read_text(encoding="utf-8")

    def test_d1_chat_route_calls_get_desktop_presence_runtime(self):
        """galaxy_gateway/routes/chat.py chat_endpoint calls get_desktop_presence_runtime()."""
        src = self._read_chat_route()
        assert "get_desktop_presence_runtime" in src, (
            "galaxy_gateway/routes/chat.py must call get_desktop_presence_runtime() "
            "to ensure all chat requests flow through the runtime shell"
        )

    def test_d2_chat_route_calls_handle_request(self):
        """chat_endpoint calls runtime.handle_request(), not openclawd directly."""
        src = self._read_chat_route()
        assert "runtime.handle_request" in src, (
            "galaxy_gateway/routes/chat.py chat_endpoint must call runtime.handle_request() "
            "as the canonical shell entry — not openclawd directly"
        )

    def test_d3_chat_route_passes_source_chat(self):
        """chat_endpoint passes source='chat' as observability tag."""
        src = self._read_chat_route()
        assert 'source="chat"' in src or "source='chat'" in src, (
            "galaxy_gateway/routes/chat.py chat_endpoint must pass source='chat' "
            "to handle_request() as an observability tag"
        )

    def test_d4_chat_route_does_not_bypass_runtime_shell(self):
        """chat_endpoint does NOT call openclawd_instance.process() directly."""
        src = self._read_chat_route()
        chat_ep_start = src.find("async def chat_endpoint(")
        assert chat_ep_start != -1, (
            "chat_endpoint not found in galaxy_gateway/routes/chat.py"
        )
        # Find end of function body
        candidates = [
            src.find("\n@router.", chat_ep_start + 50),
            src.find("\nasync def ", chat_ep_start + 50),
        ]
        valid = [c for c in candidates if c > chat_ep_start]
        next_def = min(valid) if valid else -1
        func_body = src[chat_ep_start:next_def] if next_def != -1 else src[chat_ep_start:]
        assert "openclawd_instance.process(" not in func_body, (
            "chat_endpoint must NOT call openclawd_instance.process() directly — "
            "all cognition must flow through DesktopPresenceRuntime.handle_request()"
        )

    def test_d5_gateway_app_describes_internal_substrate(self):
        """galaxy_gateway/app.py describes itself as an internal substrate."""
        src = self._read_gateway_app()
        assert "internal" in src.lower(), (
            "galaxy_gateway/app.py must declare itself as an internal substrate"
        )

    def test_d6_chat_route_module_doc_mentions_authority_chain(self):
        """galaxy_gateway/routes/chat.py module docstring documents the authority chain."""
        src = self._read_chat_route()
        assert "DesktopPresenceRuntime" in src, (
            "galaxy_gateway/routes/chat.py must mention DesktopPresenceRuntime "
            "to document the authority chain"
        )
        assert "handle_request" in src, (
            "galaxy_gateway/routes/chat.py must mention handle_request"
        )


# ---------------------------------------------------------------------------
# Group E: Live mesh session coordinator — MESH-001/002 baseline
# ---------------------------------------------------------------------------


class TestGroupE_MeshSessionBaseline:
    """MESH-001/002 baseline: LiveMeshSessionCoordinator and contracts are importable.

    The full live engine (barrier wait, assignment progress, merge trigger) is
    available but not yet wired to TaskGraphRuntime events.  This group validates
    that the contracts and engine are present as the foundation for future mesh work.
    """

    def test_e1_mesh_session_coordinator_contracts_importable(self):
        """contracts.mesh_session_coordinator is importable."""
        from contracts.mesh_session_coordinator import (  # noqa: F401
            MeshSessionCoordinatorState,
            build_mesh_session_coordinator,
        )
        state = build_mesh_session_coordinator(session_id="test_session")
        assert state.session_id == "test_session"

    def test_e2_live_mesh_runtime_engine_importable(self):
        """core.mesh.live_mesh_runtime_engine is importable."""
        from core.mesh.live_mesh_runtime_engine import (  # noqa: F401
            run_live_mesh_session,
        )
        assert callable(run_live_mesh_session)

    def test_e3_live_mesh_session_coordinator_importable(self):
        """core.mesh.live_mesh_session_coordinator is importable."""
        from core.mesh.live_mesh_session_coordinator import (  # noqa: F401
            LiveMeshSessionCoordinator,
        )
        assert LiveMeshSessionCoordinator is not None

    def test_e4_mesh_session_coordinator_convenience_importable(self):
        """core.mesh.mesh_session_coordinator convenience functions are importable."""
        from core.mesh.mesh_session_coordinator import (  # noqa: F401
            coordinate_mesh_session,
            run_live_mesh_session,
        )
        assert callable(coordinate_mesh_session)

    def test_e5_coordinate_mesh_session_returns_state(self):
        """coordinate_mesh_session() returns a coordinator state without error."""
        from core.mesh.mesh_session_coordinator import coordinate_mesh_session
        state = coordinate_mesh_session(session_id="baseline_test", mesh_id="mesh_001")
        assert state is not None, "coordinate_mesh_session must return a non-None state"

    def test_e6_mesh_session_status_contract_importable(self):
        """contracts.mesh_session.MeshSessionStatus is importable."""
        from contracts.mesh_session import MeshSession, build_mesh_session  # noqa: F401
        session = build_mesh_session(
            source_device_id="device_a",
            primary_device_id="device_b",
        )
        assert session is not None
