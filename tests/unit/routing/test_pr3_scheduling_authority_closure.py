"""tests/unit/routing/test_pr3_scheduling_authority_closure.py
================================================================

PR-3 — Unified Scheduling and Router Authority Closure.

Covers:
  A) GAP-512-004 closure: CommandRouter capability graph enforcement
     - Targets confirmed in the capability graph proceed unchanged.
     - Unconfirmed targets are filtered when confirmed ones exist.
     - If no confirmed target exists, routing proceeds with original targets
       (fail-open; capability graph may not have the device assimilated yet).
     - New ``CAPABILITY_GRAPH_SELECTION_ENFORCED`` sentinel is present.

  B) SCHED-003 partial closure: DeviceRouter pre-analysis passthrough
     - When context["_command_router_pre_analyzed"]==True and
       context["_pre_analysis"] is set, route_task() skips _analyze_command().
     - ``DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL`` is present.

  C) Unified node+device capability query
     - ``query_capable_device_executors()`` returns DEVICE-kind entries only.
     - ``query_routable_executors()`` returns all kinds (including DEVICE).
     - Both use the same canonical CapabilityAssimilationLayer.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ===========================================================================
# A) GAP-512-004 closure: CommandRouter capability graph enforcement
# ===========================================================================


class TestCommandRouterCapabilityGraphSentinel:
    """New sentinel CAPABILITY_GRAPH_SELECTION_ENFORCED must be present."""

    def test_sentinel_importable(self):
        """CAPABILITY_GRAPH_SELECTION_ENFORCED is importable from command_router."""
        from core.command_router import CAPABILITY_GRAPH_SELECTION_ENFORCED

        assert "GAP-512-004" in CAPABILITY_GRAPH_SELECTION_ENFORCED
        assert "CAPABILITY_GRAPH_SELECTION_ENFORCED" in CAPABILITY_GRAPH_SELECTION_ENFORCED


class TestCommandRouterCapabilityGraphEnforcement:
    """route_envelope() enforces capability graph selection when caps provided."""

    @pytest.mark.asyncio
    async def test_confirmed_target_proceeds_unchanged(self):
        """When the capability graph confirms the target, routing proceeds unchanged."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope
        from core.capability_network_runtime_policy import RoutableExecutor

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        envelope = TaskEnvelope(
            targets=["confirmed_device_01"],
            tool_name="screenshot",
            args={},
            required_capabilities=["screen"],
        )

        mock_executor = RoutableExecutor(
            node_id="confirmed_device_01",
            participant_kind="device",
            capabilities=["screen"],
            presence_state="online",
            health_score=1.0,
        )

        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[mock_executor],
        ):
            result = await router.route_envelope(envelope)

        # Routing should succeed and reach the confirmed device.
        assert result.get("success") is True
        assert result.get("device_id") == "confirmed_device_01"

    @pytest.mark.asyncio
    async def test_unconfirmed_target_filtered_when_confirmed_exists(self):
        """Unconfirmed targets are removed when confirmed ones exist in the graph."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope
        from core.capability_network_runtime_policy import RoutableExecutor

        dispatched_device_ids = []

        async def fake_exec(device_id, command, params):
            dispatched_device_ids.append(device_id)
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        # Envelope targets: confirmed_dev is in graph, unconfirmed_dev is not.
        envelope = TaskEnvelope(
            targets=["confirmed_dev", "unconfirmed_dev"],
            tool_name="screenshot",
            args={},
            required_capabilities=["screen"],
        )

        confirmed_executor = RoutableExecutor(
            node_id="confirmed_dev",
            participant_kind="device",
            capabilities=["screen"],
            presence_state="online",
            health_score=1.0,
        )

        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[confirmed_executor],
        ):
            result = await router.route_envelope(envelope)

        # The unconfirmed device should have been filtered out.
        # Route should use only the confirmed device.
        assert "unconfirmed_dev" not in dispatched_device_ids
        # Execution targeted confirmed_dev (single target after filtering).
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_capability_layer_unavailable_is_fail_open(self):
        """When the capability layer is unavailable, routing proceeds unchanged."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        envelope = TaskEnvelope(
            targets=["any_device"],
            tool_name="screenshot",
            args={},
            required_capabilities=["screen"],
        )

        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            side_effect=RuntimeError("capability layer unavailable"),
        ):
            result = await router.route_envelope(envelope)

        # Routing must proceed and succeed (fail-open on capability layer failure).
        assert result.get("success") is True
        assert result.get("device_id") == "any_device"

    @pytest.mark.asyncio
    async def test_no_required_caps_skips_enforcement(self):
        """When required_capabilities is absent, capability enforcement is skipped."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        envelope = TaskEnvelope(
            targets=["any_device"],
            tool_name="screenshot",
            args={},
            # No required_capabilities set.
        )

        mock_query = MagicMock(return_value=[])
        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            mock_query,
        ):
            result = await router.route_envelope(envelope)

        # query_routable_executors is still called but without capability filtering.
        assert result.get("success") is True
        # Verify no capability-graph enforcement happened for this target.
        assert result.get("device_id") == "any_device"

    @pytest.mark.asyncio
    async def test_no_confirmed_target_proceeds_with_original(self):
        """When no target is confirmed in graph, routing proceeds with original targets."""
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope
        from core.capability_network_runtime_policy import RoutableExecutor

        async def fake_exec(device_id, command, params):
            return {"success": True, "result": "ok", "device_id": device_id}

        router = CommandRouter(executor=fake_exec)

        # Target is not in the capability graph but a *different* device is.
        envelope = TaskEnvelope(
            targets=["target_not_in_graph"],
            tool_name="screenshot",
            args={},
            required_capabilities=["screen"],
        )

        other_executor = RoutableExecutor(
            node_id="some_other_device",
            participant_kind="device",
            capabilities=["screen"],
            presence_state="online",
            health_score=1.0,
        )

        with patch(
            "core.capability_network_runtime_policy.query_routable_executors",
            return_value=[other_executor],
        ):
            result = await router.route_envelope(envelope)

        # Routing must proceed to the original target (fail-open; device may not
        # be assimilated yet but is still reachable).
        assert result.get("device_id") == "target_not_in_graph"


# ===========================================================================
# B) SCHED-003 partial closure: DeviceRouter pre-analysis passthrough
# ===========================================================================


class TestDeviceRouterGovernanceSentinel:
    """DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL must be present."""

    def test_sentinel_importable(self):
        """DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL is importable."""
        try:
            from galaxy_gateway.device_router import (
                DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL,
            )
        except ImportError:
            pytest.skip("galaxy_gateway not importable in this environment")

        assert "SCHED-003" in DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL
        assert "_command_router_pre_analyzed" in DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL

    def test_sentinel_references_command_router_authority(self):
        """The governance sentinel must reference CommandRouter as decision authority."""
        try:
            from galaxy_gateway.device_router import (
                DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL,
            )
        except ImportError:
            pytest.skip("galaxy_gateway not importable in this environment")

        assert "CommandRouter" in DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL


class TestDeviceRouterPreAnalysisPassthrough:
    """DeviceRouter skips _analyze_command when pre-analyzed context is supplied."""

    def _make_router(self) -> "DeviceRouter":
        try:
            from galaxy_gateway.device_router import DeviceRouter
        except ImportError:
            pytest.skip("galaxy_gateway not importable in this environment")

        router = DeviceRouter.__new__(DeviceRouter)
        router.websocket_manager = MagicMock()
        router.devices = {}
        router.task_queue = {}
        return router

    @pytest.mark.asyncio
    async def test_pre_analyzed_context_skips_analyze_command(self):
        """When _command_router_pre_analyzed=True, _analyze_command is not called."""
        router = self._make_router()

        pre_analysis = {
            "command": "open gallery",
            "target_device_type": "android",
            "task_type": "app_control",
            "actions": ["open"],
            "requires_cross_device": False,
            "exec_mode": "both",
        }

        context = {
            "_command_router_pre_analyzed": True,
            "_pre_analysis": pre_analysis,
            "device_id": "test_device",
        }

        analyze_mock = AsyncMock(return_value={})

        # Patch both the cross-device check and device selection to isolate the test.
        with (
            patch.object(router, "_analyze_command", analyze_mock),
            patch.object(
                router,
                "_select_devices",
                return_value=[],
            ),
            patch(
                "galaxy_gateway.device_router.is_cross_device_enabled",
                return_value=False,
            ),
        ):
            try:
                await router.route_task("open gallery", context)
            except Exception:
                pass  # We only care that _analyze_command was NOT called.

        # _analyze_command must NOT have been called because pre-analysis was provided.
        analyze_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_pre_analyzed_calls_analyze_command(self):
        """When pre-analysis is absent, _analyze_command is called normally."""
        router = self._make_router()

        context = {
            "device_id": "test_device",
            # No _command_router_pre_analyzed flag.
        }

        analyze_mock = AsyncMock(
            return_value={
                "command": "test",
                "target_device_type": "android",
                "task_type": "query",
                "actions": [],
                "requires_cross_device": False,
                "exec_mode": "both",
            }
        )

        with (
            patch.object(router, "_analyze_command", analyze_mock),
            patch.object(router, "_select_devices", return_value=[]),
            patch(
                "galaxy_gateway.device_router.is_cross_device_enabled",
                return_value=False,
            ),
        ):
            try:
                await router.route_task("test query", context)
            except Exception:
                pass

        # _analyze_command MUST have been called for non-pre-analyzed context.
        analyze_mock.assert_called_once()


# ===========================================================================
# C) Unified node+device capability query
# ===========================================================================


class TestQueryCapableDeviceExecutors:
    """query_capable_device_executors() returns only DEVICE-kind entries."""

    def _register_mixed_entries(self) -> "CapabilityAssimilationLayer":
        """Register one WORKER node and one DEVICE node, then return the layer."""
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            reset_capability_assimilation_layer,
            NodeParticipantKind,
        )

        reset_capability_assimilation_layer()
        layer = get_capability_assimilation_layer()

        # Register a WORKER-kind node (compute node, not a device).
        layer.assimilate(
            "worker_node_01",
            capabilities=["inference", "screen"],
            participant_kind=NodeParticipantKind.WORKER,
        )

        # Register a DEVICE-kind node (physical device like Android).
        layer.assimilate(
            "android_device_01",
            capabilities=["screen", "touch"],
            participant_kind=NodeParticipantKind.DEVICE,
        )

        return layer

    def test_returns_only_device_kind_entries(self):
        """query_capable_device_executors returns only DEVICE-kind entries."""
        from core.capability_network_runtime_policy import query_capable_device_executors
        from core.capability_assimilation import reset_capability_assimilation_layer

        self._register_mixed_entries()
        try:
            results = query_capable_device_executors()
            node_ids = {r.node_id for r in results}
            # Only the DEVICE-kind entry should appear.
            assert "android_device_01" in node_ids
            assert "worker_node_01" not in node_ids
        finally:
            reset_capability_assimilation_layer()

    def test_capability_filter_applied_to_device_entries(self):
        """query_capable_device_executors filters by required_capabilities."""
        from core.capability_network_runtime_policy import query_capable_device_executors
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            reset_capability_assimilation_layer,
            NodeParticipantKind,
        )

        reset_capability_assimilation_layer()
        layer = get_capability_assimilation_layer()

        layer.assimilate(
            "dev_with_camera",
            capabilities=["screen", "camera"],
            participant_kind=NodeParticipantKind.DEVICE,
        )
        layer.assimilate(
            "dev_without_camera",
            capabilities=["screen"],
            participant_kind=NodeParticipantKind.DEVICE,
        )

        try:
            results = query_capable_device_executors(required_capabilities=["camera"])
            node_ids = {r.node_id for r in results}
            assert "dev_with_camera" in node_ids
            assert "dev_without_camera" not in node_ids
        finally:
            reset_capability_assimilation_layer()

    def test_returns_empty_when_no_device_entries(self):
        """query_capable_device_executors returns empty list when no devices assimilated."""
        from core.capability_network_runtime_policy import query_capable_device_executors
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            reset_capability_assimilation_layer,
            NodeParticipantKind,
        )

        reset_capability_assimilation_layer()
        layer = get_capability_assimilation_layer()

        # Only register WORKER-kind nodes, no DEVICE-kind.
        layer.assimilate(
            "worker_only",
            capabilities=["screen"],
            participant_kind=NodeParticipantKind.WORKER,
        )

        try:
            results = query_capable_device_executors()
            assert results == []
        finally:
            reset_capability_assimilation_layer()

    def test_query_routable_executors_includes_device_kind(self):
        """The generic query_routable_executors includes DEVICE-kind entries too."""
        from core.capability_network_runtime_policy import query_routable_executors
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            reset_capability_assimilation_layer,
            NodeParticipantKind,
        )

        reset_capability_assimilation_layer()
        layer = get_capability_assimilation_layer()

        layer.assimilate(
            "android_device_02",
            capabilities=["screen"],
            participant_kind=NodeParticipantKind.DEVICE,
        )
        layer.assimilate(
            "worker_node_02",
            capabilities=["screen"],
            participant_kind=NodeParticipantKind.WORKER,
        )

        try:
            results = query_routable_executors(required_capabilities=["screen"])
            node_ids = {r.node_id for r in results}
            # Both DEVICE and WORKER entries with the required cap should be present.
            assert "android_device_02" in node_ids
            assert "worker_node_02" in node_ids
        finally:
            reset_capability_assimilation_layer()

    def test_unified_scheduling_basis_device_and_node_same_layer(self):
        """Devices and nodes appear in the same CapabilityAssimilationLayer.

        This validates that node capabilities and device capabilities converge
        in one canonical scheduling comparison framework (AC1 of PR-3).
        """
        from core.capability_assimilation import (
            get_capability_assimilation_layer,
            reset_capability_assimilation_layer,
            NodeParticipantKind,
        )

        reset_capability_assimilation_layer()
        layer = get_capability_assimilation_layer()

        layer.assimilate(
            "node_x", capabilities=["compute"], participant_kind=NodeParticipantKind.WORKER
        )
        layer.assimilate(
            "device_x", capabilities=["screen"], participant_kind=NodeParticipantKind.DEVICE
        )

        try:
            records = layer.list_online_records()
            node_ids = {r.node_id for r in records}
            assert "node_x" in node_ids, "Node must appear in assimilation layer"
            assert "device_x" in node_ids, "Device must appear in same assimilation layer"
        finally:
            reset_capability_assimilation_layer()
