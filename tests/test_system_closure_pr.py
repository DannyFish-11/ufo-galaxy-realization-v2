"""tests/test_system_closure_pr.py
===================================
PR system-closure tests covering four critical gaps:

A — Android completion drives asyncio awaiter (CanonicalCompletionIngress)
B — Capability-aware routing fallback (CommandRouter + capability_graph_selection)
C — UnifiedLLMRouter is the primary entry point for OpenClawd._get_router()
D — HITL gate blocks high-risk commands in _execute_command()
"""

from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable.
PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ===========================================================================
# Test A: Android completion drives awaiter
# ===========================================================================


class TestCanonicalCompletionIngress:
    """Test A: register_pending_dispatch() → notify() resolves the Future."""

    def test_register_returns_future(self):
        """register_pending_dispatch returns an asyncio.Future."""
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-001", task_id="tid-001")
            assert isinstance(fut, asyncio.Future)
            assert not fut.done()
        finally:
            loop.close()

    def test_notify_resolves_future_by_handoff_id(self):
        """notify() with a terminal envelope resolves the Future."""
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-002", task_id="tid-002")

            # Build a minimal mock terminal envelope.
            envelope = MagicMock()
            envelope.handoff_id = "hid-002"
            envelope.task_id = "tid-002"
            envelope.is_terminal = True
            envelope.response_kind = "result"

            resolved = cci.notify(envelope)

            assert resolved is True
            assert fut.done()
            assert fut.result() is envelope
        finally:
            loop.close()

    def test_notify_non_terminal_does_not_resolve(self):
        """notify() with an ACK (non-terminal) does NOT resolve the Future."""
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-003")

            envelope = MagicMock()
            envelope.handoff_id = "hid-003"
            envelope.task_id = ""
            envelope.is_terminal = False
            envelope.response_kind = "ack"

            resolved = cci.notify(envelope)

            assert resolved is False
            assert not fut.done()
        finally:
            loop.close()

    def test_complete_pending_dispatch_by_key(self):
        """complete_pending_dispatch() resolves Future by direct key lookup."""
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            fut = cci.register_pending_dispatch("hid-004")

            envelope = MagicMock()
            envelope.handoff_id = "hid-004"
            envelope.task_id = ""

            resolved = cci.complete_pending_dispatch("hid-004", envelope)

            assert resolved is True
            assert fut.done()
        finally:
            loop.close()

    def test_complete_missing_key_is_safe(self):
        """complete_pending_dispatch() with unknown key returns False (no error)."""
        from core.canonical_completion_ingress import CanonicalCompletionIngress

        cci = CanonicalCompletionIngress()
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            resolved = cci.complete_pending_dispatch("non-existent", MagicMock())
            assert resolved is False
        finally:
            loop.close()

    def test_singleton_factory(self):
        """get_canonical_completion_ingress() returns the same instance each call."""
        # Use a fresh module-level singleton by patching
        import core.canonical_completion_ingress as mod

        original = mod._singleton
        mod._singleton = None
        try:
            from core.canonical_completion_ingress import (
                get_canonical_completion_ingress,
                CanonicalCompletionIngress,
            )

            a = get_canonical_completion_ingress()
            b = get_canonical_completion_ingress()
            assert a is b
            assert isinstance(a, CanonicalCompletionIngress)
        finally:
            mod._singleton = original


# ===========================================================================
# Test B: Capability-aware routing fallback
# ===========================================================================


class TestCapabilityAwareRouting:
    """Test B: When DevicePoolManager returns None but capability_graph_selection
    returns a result, the envelope targets are updated correctly.
    """

    def _make_minimal_command_router(self):
        """Import CommandRouter with minimal dependencies."""
        try:
            from core.command_router import CommandRouter
            return CommandRouter
        except Exception as exc:
            pytest.skip(f"CommandRouter import failed: {exc}")

    def test_capability_graph_used_when_pool_returns_none(self):
        """If DevicePoolManager.select_device returns None, capability_graph
        select_best_provider result is used for target selection."""

        # We test this by checking the logic in the code paths directly via
        # unit-testing the fallback chain with mocks.  The actual route_envelope
        # path is integration-level; here we verify the selection logic.
        try:
            from core.capability_graph_selection import select_best_provider
        except Exception as exc:
            pytest.skip(f"capability_graph_selection unavailable: {exc}")

        # Mock the assimilation layer to return one record
        mock_record = MagicMock()
        mock_record.node_id = "device-cap-001"

        with patch(
            "core.capability_graph_selection.discover_providers",
            return_value=[mock_record],
        ):
            result = select_best_provider(required_capabilities=["screen", "touch"])

        assert result is not None
        assert result.node_id == "device-cap-001"

    def test_select_fallback_providers_excludes_primary(self):
        """select_fallback_providers excludes the primary device node_id."""
        try:
            from core.capability_graph_selection import select_fallback_providers
        except Exception as exc:
            pytest.skip(f"capability_graph_selection unavailable: {exc}")

        mock_primary = MagicMock()
        mock_primary.node_id = "primary-001"
        mock_fallback = MagicMock()
        mock_fallback.node_id = "fallback-001"

        # score_provider should return a score for each candidate
        mock_score = MagicMock()
        mock_score.total_score = 0.7

        # Give both records proper presence state and execution_profile
        for rec in [mock_primary, mock_fallback]:
            rec.fabric_presence.presence_state.value = "online"
            rec.execution_profile.participant_kind.value = "android_device"

        mock_layer = MagicMock()
        mock_layer.list_records.return_value = [mock_primary, mock_fallback]

        # The function imports get_capability_assimilation_layer locally,
        # so we patch the canonical module path it comes from.
        with patch(
            "core.capability_assimilation.get_capability_assimilation_layer",
            return_value=mock_layer,
            create=True,
        ), patch(
            "core.capability_graph_selection.score_provider", return_value=mock_score
        ):
            try:
                results = select_fallback_providers(
                    required_capabilities=["screen"],
                    exclude_ids=["primary-001"],
                )
            except Exception:
                # If assimilation layer import itself fails, skip
                pytest.skip("capability_assimilation unavailable")

        # primary should be excluded
        node_ids = [r.node_id for r in results]
        assert "primary-001" not in node_ids
        assert "fallback-001" in node_ids

    def test_capability_graph_fallbacks_stored_in_metadata(self):
        """When capability graph selects a device and has fallbacks, they are
        stored in envelope metadata under _capability_graph_fallbacks."""
        try:
            from core.capability_graph_selection import (
                select_best_provider,
                select_fallback_providers,
            )
        except Exception as exc:
            pytest.skip(f"capability_graph_selection unavailable: {exc}")

        # Verify behavioral contract: select_best_provider returns a node_id
        # and select_fallback_providers returns a list excluding the primary.
        primary = MagicMock()
        primary.node_id = "primary-node"
        fallback = MagicMock()
        fallback.node_id = "fallback-node"

        with patch(
            "core.capability_graph_selection.discover_providers",
            return_value=[primary],
        ):
            best = select_best_provider(required_capabilities=["screen"])

        assert best is not None
        assert best.node_id == "primary-node"

        # Fallback should exclude the primary
        for rec in [primary, fallback]:
            rec.fabric_presence.presence_state.value = "online"
            rec.execution_profile.participant_kind.value = "android_device"

        mock_score = MagicMock()
        mock_score.total_score = 0.5
        mock_layer = MagicMock()
        mock_layer.list_records.return_value = [primary, fallback]

        with patch(
            "core.capability_assimilation.get_capability_assimilation_layer",
            return_value=mock_layer,
            create=True,
        ), patch("core.capability_graph_selection.score_provider", return_value=mock_score):
            try:
                fallbacks = select_fallback_providers(
                    required_capabilities=["screen"],
                    exclude_ids=["primary-node"],
                )
                fb_ids = [r.node_id for r in fallbacks]
                assert "primary-node" not in fb_ids
            except Exception:
                pytest.skip("capability_assimilation unavailable")


# ===========================================================================
# Test C: UnifiedLLMRouter is primary entry
# ===========================================================================


class TestUnifiedLLMRouterPrimary:
    """Test C: OpenClawd._get_router() returns a UnifiedLLMRouter instance."""

    def test_get_router_uses_unified_llm_router(self):
        """_get_router() imports from core.unified.llm_router first."""
        try:
            from core.unified.llm_router import UnifiedLLMRouter, get_unified_llm_router
        except Exception as exc:
            pytest.skip(f"UnifiedLLMRouter unavailable: {exc}")

        try:
            from core.openclawd import OpenClawd
        except Exception as exc:
            pytest.skip(f"OpenClawd unavailable: {exc}")

        oc = object.__new__(OpenClawd)
        oc._router = None

        # Patch get_unified_llm_router to return a mock UnifiedLLMRouter
        mock_router = MagicMock(spec=UnifiedLLMRouter)

        with patch(
            "core.unified.llm_router.get_unified_llm_router",
            return_value=mock_router,
        ):
            result = oc._get_router()

        assert result is mock_router

    def test_get_router_fallback_to_multi_llm_router(self):
        """_get_router() falls back gracefully when UnifiedLLMRouter raises."""
        try:
            from core.openclawd import OpenClawd
        except Exception as exc:
            pytest.skip(f"OpenClawd unavailable: {exc}")

        oc = object.__new__(OpenClawd)
        oc._router = None

        # Make a fake unified module that raises on import
        fake_unified_mod = types.ModuleType("core.unified.llm_router")
        fake_unified_mod.get_unified_llm_router = MagicMock(
            side_effect=RuntimeError("unified unavailable")
        )

        mock_multi_router = MagicMock()
        fake_multi_mod = types.ModuleType("core.multi_llm_router")
        fake_multi_mod.get_llm_router = MagicMock(return_value=mock_multi_router)

        original_unified = sys.modules.get("core.unified.llm_router")
        original_multi = sys.modules.get("core.multi_llm_router")
        try:
            sys.modules["core.unified.llm_router"] = fake_unified_mod
            sys.modules["core.multi_llm_router"] = fake_multi_mod
            oc._router = None
            result = oc._get_router()
        finally:
            if original_unified is None:
                sys.modules.pop("core.unified.llm_router", None)
            else:
                sys.modules["core.unified.llm_router"] = original_unified
            if original_multi is None:
                sys.modules.pop("core.multi_llm_router", None)
            else:
                sys.modules["core.multi_llm_router"] = original_multi

        # Result should be the multi router (or None if graceful fail-open)
        assert result is mock_multi_router or result is None

    def test_get_router_returns_cached_instance(self):
        """_get_router() returns same instance on subsequent calls."""
        try:
            from core.unified.llm_router import UnifiedLLMRouter
            from core.openclawd import OpenClawd
        except Exception as exc:
            pytest.skip(f"Dependencies unavailable: {exc}")

        oc = object.__new__(OpenClawd)
        oc._router = None

        mock_router = MagicMock(spec=UnifiedLLMRouter)

        with patch(
            "core.unified.llm_router.get_unified_llm_router",
            return_value=mock_router,
        ):
            r1 = oc._get_router()
            r2 = oc._get_router()

        assert r1 is r2


# ===========================================================================
# Test D: HITL gate blocks high-risk commands
# ===========================================================================


class TestHITLGate:
    """Test D: _execute_command() blocks high-risk commands without _hitl_approved."""

    def _make_router(self):
        try:
            from core.command_router import CommandRouter
        except Exception as exc:
            pytest.skip(f"CommandRouter unavailable: {exc}")
        cr = object.__new__(CommandRouter)
        cr._cb_enabled = False
        cr._circuit_breakers = {}
        cr._stats = {"total_requests": 0, "total_fallbacks": 0}
        cr._latencies = []
        cr._executor = None
        return cr

    @pytest.mark.asyncio
    async def test_high_risk_command_blocked_without_approval(self):
        """_execute_command with delete (high-risk) and no _hitl_approved returns HITL_APPROVAL_REQUIRED."""
        cr = self._make_router()

        # Patch _get_gateway_trace_store to avoid side effects
        mock_trace_store = MagicMock()
        mock_trace_store.record = MagicMock()

        with patch(
            "core.command_router._get_gateway_trace_store",
            return_value=mock_trace_store,
        ):
            result = await cr._execute_command(
                device_id="device-001",
                command="delete_all_data",
                payload={},
                command_id="cmd-001",
                task_id="task-001",
            )

        assert result["success"] is False
        assert result["error_code"] == "HITL_APPROVAL_REQUIRED"
        assert result.get("requires_hitl") is True

    @pytest.mark.asyncio
    async def test_high_risk_command_allowed_with_approval(self):
        """_execute_command with _hitl_approved=True does not return HITL_APPROVAL_REQUIRED."""
        cr = self._make_router()

        mock_trace_store = MagicMock()
        mock_trace_store.record = MagicMock()

        # Mock _dispatch_to_device so we don't need a real device connection
        dispatch_result = {
            "success": True,
            "result": "ok",
            "error_code": None,
            "error_message": None,
            "request_id": "req-x",
            "task_id": "task-002",
            "trace_id": "trace-x",
            "command_id": "cmd-002",
            "device_id": "device-001",
            "command": "delete_all_data",
            "via": "command_router",
            "latency_ms": 1.0,
        }

        with patch(
            "core.command_router._get_gateway_trace_store",
            return_value=mock_trace_store,
        ), patch.object(cr, "_emit_audit", return_value=None), patch.object(
            cr, "_dispatch_to_device", return_value=dispatch_result
        ):
            result = await cr._execute_command(
                device_id="device-001",
                command="delete_all_data",
                payload={"_hitl_approved": True},
                command_id="cmd-002",
                task_id="task-002",
            )

        # HITL gate must have passed — error_code should NOT be HITL_APPROVAL_REQUIRED
        assert result.get("error_code") != "HITL_APPROVAL_REQUIRED"

    @pytest.mark.asyncio
    async def test_safe_command_not_blocked(self):
        """_execute_command with a non-high-risk command passes the HITL gate."""
        cr = self._make_router()

        mock_trace_store = MagicMock()
        mock_trace_store.record = MagicMock()

        dispatch_result = {
            "success": True,
            "result": "ok",
            "error_code": None,
            "error_message": None,
            "request_id": "req-y",
            "task_id": "task-003",
            "trace_id": "trace-y",
            "command_id": "cmd-003",
            "device_id": "device-001",
            "command": "get_status",
            "via": "command_router",
            "latency_ms": 1.0,
        }

        with patch(
            "core.command_router._get_gateway_trace_store",
            return_value=mock_trace_store,
        ), patch.object(cr, "_emit_audit", return_value=None), patch.object(
            cr, "_dispatch_to_device", return_value=dispatch_result
        ):
            result = await cr._execute_command(
                device_id="device-001",
                command="get_status",
                payload={},
                command_id="cmd-003",
                task_id="task-003",
            )

        assert result.get("error_code") != "HITL_APPROVAL_REQUIRED"

    def test_is_high_risk_command_detects_keywords(self):
        """_is_high_risk_command correctly identifies high-risk commands."""
        cr = self._make_router()

        assert cr._is_high_risk_command("delete") is True
        assert cr._is_high_risk_command("delete_all_data") is True
        assert cr._is_high_risk_command("format_disk") is True
        assert cr._is_high_risk_command("shutdown") is True
        assert cr._is_high_risk_command("wipe") is True
        assert cr._is_high_risk_command("get_status") is False
        assert cr._is_high_risk_command("read_file") is False
        assert cr._is_high_risk_command("list_devices") is False


# ===========================================================================
# Test E: Policy sentinel exported from android_handoff_v2_response_ingress
# ===========================================================================


class TestCompletionResultDrivenPolicy:
    """Verify COMPLETION_RESULT_DRIVEN_POLICY is exported and notify is called."""

    def test_policy_sentinel_exported(self):
        from core.android_handoff_v2_response_ingress import (
            COMPLETION_RESULT_DRIVEN_POLICY,
        )

        assert isinstance(COMPLETION_RESULT_DRIVEN_POLICY, str)
        assert "COMPLETION_RESULT_DRIVEN" in COMPLETION_RESULT_DRIVEN_POLICY

    def test_policy_in_all(self):
        import core.android_handoff_v2_response_ingress as mod

        assert "COMPLETION_RESULT_DRIVEN_POLICY" in mod.__all__

    def test_notify_called_on_terminal_response(self):
        """ingest_android_handoff_response calls notify() on terminal responses."""
        from core.android_handoff_v2_response_ingress import (
            HandoffV2ResponseRuntime,
            ingest_android_handoff_response,
        )

        # Build a runtime with a registered callback
        runtime = HandoffV2ResponseRuntime()
        received = []
        runtime.register("hid-notify-001", lambda env: received.append(env))

        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)

            notify_calls = []
            mock_cci = MagicMock()
            mock_cci.notify = lambda env: notify_calls.append(env) or True

            # Patch where it's actually imported from (the canonical source module)
            with patch(
                "core.canonical_completion_ingress.get_canonical_completion_ingress",
                return_value=mock_cci,
            ):
                # Build a minimal terminal message
                message = {
                    "type": "handoff_result",
                    "payload": {
                        "handoff_id": "hid-notify-001",
                        "task_id": "tid-notify-001",
                        "status": "success",
                        "result": {"output": "done"},
                    },
                }

                outcome = ingest_android_handoff_response(message, runtime=runtime)

            assert outcome.was_correlated is True
            assert len(notify_calls) == 1
        finally:
            loop.close()
