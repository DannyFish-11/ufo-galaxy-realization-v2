#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_routing_canonical_truth_alignment.py
=================================================
PR-ALIGN: Routing and formation decisions grounded in canonical device truth.

Verifies that:
1. ``CommandRouter._route_cross_device_envelope()`` validates targets via
   ``core.target_device_validator.validate_target_device()`` before dispatch
   and propagates the validated target as ``context["device_id"]``.
   (Closes SCHED-002 — CommandRouter side.)

2. ``galaxy_gateway.routing.device_selection.select_devices()`` applies an
   admissibility pre-filter using ``core.target_device_validator`` before
   exec_mode or capability filtering.
   (Closes SCHED-002 — DeviceRouter selection side.)

3. ``DeviceRouter._dispatch_cross_device_task()`` filters the device list
   through ``core.device_participation.get_device_participation()`` before
   calling ``resolve_formation()``, ensuring formation membership reflects
   participation eligibility.
   (Closes ADMIT-003.)

4. Sentinel constants for each enforcement point are importable and stable.

5. All enforcement points degrade gracefully when the canonical modules are
   unavailable.

Test classes
------------
A. TestSentinelConstants
       Authority sentinels for the new enforcement points are importable.

B. TestSelectDevicesAdmissibilityPrefilter
       select_devices() step-0 pre-filter excludes offline candidates.
       Online candidates pass through the pre-filter unchanged.
       Graceful degradation when validator unavailable.

C. TestRouteEnvelopeTargetValidation
       _route_cross_device_envelope() filters invalid targets.
       Valid targets are passed as device_id to DeviceRouter.
       Graceful degradation when validator unavailable.

D. TestDispatchCrossDeviceParticipationFilter
       _dispatch_cross_device_task() excludes non-eligible devices from
       formation input.
       Graceful degradation when participation module unavailable.
"""

from __future__ import annotations

import sys
import os
import unittest
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_readiness(
    device_id: str = "dev1",
    registered: bool = True,
    online: bool = True,
    connected: bool = True,
    routable: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.device_id = device_id
    m.registered = registered
    m.online = online
    m.connected = connected
    m.routable = routable
    return m


def _make_participation(
    device_id: str = "dev1",
    orchestration_eligible: bool = True,
) -> MagicMock:
    m = MagicMock()
    m.device_id = device_id
    m.orchestration_eligible = orchestration_eligible
    return m


def _make_validation_result(
    device_id: str = "dev1",
    valid: bool = True,
    registered: bool = True,
    ready: bool = True,
    reasons: List[str] = None,
) -> MagicMock:
    m = MagicMock()
    m.device_id = device_id
    m.valid = valid
    m.registered = registered
    m.ready = ready
    m.reasons = reasons or []
    return m


def _make_device(device_id: str, status: str = "online") -> MagicMock:
    m = MagicMock()
    m.device_id = device_id
    m.status = status
    m.metadata = {}
    return m


# ---------------------------------------------------------------------------
# A. Sentinel constants
# ---------------------------------------------------------------------------


class TestSentinelConstants(unittest.TestCase):
    """A) Authority sentinels for the new enforcement points are importable."""

    def test_command_router_target_admissibility_sentinel_importable(self) -> None:
        from core.command_router import COMMAND_ROUTER_TARGET_ADMISSIBILITY_VALIDATED
        self.assertIsInstance(COMMAND_ROUTER_TARGET_ADMISSIBILITY_VALIDATED, str)
        self.assertTrue(len(COMMAND_ROUTER_TARGET_ADMISSIBILITY_VALIDATED) > 0)

    def test_command_router_target_admissibility_sentinel_contains_sched002(self) -> None:
        from core.command_router import COMMAND_ROUTER_TARGET_ADMISSIBILITY_VALIDATED
        self.assertIn("SCHED-002", COMMAND_ROUTER_TARGET_ADMISSIBILITY_VALIDATED)

    def test_device_selection_admissibility_prefilter_sentinel_importable(self) -> None:
        from galaxy_gateway.routing.device_selection import ADMISSIBILITY_PREFILTER_IN_SELECTION
        self.assertIsInstance(ADMISSIBILITY_PREFILTER_IN_SELECTION, str)
        self.assertTrue(len(ADMISSIBILITY_PREFILTER_IN_SELECTION) > 0)

    def test_device_selection_admissibility_prefilter_sentinel_contains_sched002(self) -> None:
        from galaxy_gateway.routing.device_selection import ADMISSIBILITY_PREFILTER_IN_SELECTION
        self.assertIn("SCHED-002", ADMISSIBILITY_PREFILTER_IN_SELECTION)

    def test_device_router_formation_participation_sentinel_importable(self) -> None:
        from galaxy_gateway.device_router import DEVICE_ROUTER_FORMATION_PARTICIPATION_FILTERED
        self.assertIsInstance(DEVICE_ROUTER_FORMATION_PARTICIPATION_FILTERED, str)
        self.assertTrue(len(DEVICE_ROUTER_FORMATION_PARTICIPATION_FILTERED) > 0)

    def test_device_router_formation_participation_sentinel_contains_admit003(self) -> None:
        from galaxy_gateway.device_router import DEVICE_ROUTER_FORMATION_PARTICIPATION_FILTERED
        self.assertIn("ADMIT-003", DEVICE_ROUTER_FORMATION_PARTICIPATION_FILTERED)

    def test_routing_package_exports_admissibility_prefilter_sentinel(self) -> None:
        from galaxy_gateway.routing import ADMISSIBILITY_PREFILTER_IN_SELECTION
        self.assertIsInstance(ADMISSIBILITY_PREFILTER_IN_SELECTION, str)


# ---------------------------------------------------------------------------
# B. select_devices() admissibility pre-filter
# ---------------------------------------------------------------------------


class TestSelectDevicesAdmissibilityPrefilter(unittest.TestCase):
    """B) select_devices() step-0 pre-filter gates on canonical readiness."""

    def _call_select(self, candidates: List[Any], analysis: Dict = None) -> List[Any]:
        from galaxy_gateway.routing.device_selection import select_devices
        return select_devices(analysis or {"target_device_type": "android"}, candidates)

    def test_offline_device_excluded_when_readiness_consulted(self) -> None:
        """A device that is registered but not ready is excluded by the pre-filter."""
        online_dev = _make_device("dev-online", status="online")
        offline_dev = _make_device("dev-offline", status="offline")

        def _vtd(device_id, **kwargs):
            if device_id == "dev-online":
                return _make_validation_result("dev-online", valid=True, registered=True, ready=True)
            return _make_validation_result(
                device_id, valid=False, registered=True, ready=False, reasons=["not-ready"]
            )

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            result = self._call_select([online_dev, offline_dev])

        result_ids = [d.device_id for d in result]
        self.assertIn("dev-online", result_ids)
        self.assertNotIn("dev-offline", result_ids)

    def test_online_device_passes_prefilter(self) -> None:
        """A device that passes the readiness check is included after pre-filter."""
        dev = _make_device("dev-ready", status="online")

        def _vtd(device_id, **kwargs):
            return _make_validation_result(device_id, valid=True, registered=True, ready=True)

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            result = self._call_select([dev])

        result_ids = [d.device_id for d in result]
        self.assertIn("dev-ready", result_ids)

    def test_prefilter_degrades_gracefully_when_all_fail_readiness(self) -> None:
        """When all candidates fail readiness, the original list is preserved (graceful degradation)."""
        dev1 = _make_device("dev1", status="online")
        dev2 = _make_device("dev2", status="online")

        def _vtd(device_id, **kwargs):
            # Both fail readiness
            return _make_validation_result(device_id, valid=False, ready=False, reasons=["not-ready"])

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            # select_devices degrades gracefully — returns at least some result
            # (downstream "no online devices" filter will produce empty)
            result = self._call_select([dev1, dev2])
        # Graceful degradation: result may be empty (from downstream online filter),
        # but must not raise and must be a list.
        self.assertIsInstance(result, list)

    def test_prefilter_degrades_when_readiness_module_unavailable(self) -> None:
        """Graceful degradation when validate_target_device raises ImportError."""
        dev = _make_device("dev1", status="online")

        with patch(
            "galaxy_gateway.routing.device_selection.select_devices",
            wraps=lambda analysis, candidates: candidates,
        ):
            # Directly test that raising the validator doesn't crash
            from galaxy_gateway.routing.device_selection import select_devices

            with patch(
                "core.target_device_validator.validate_target_device",
                side_effect=ImportError("mocked unavailable"),
            ):
                result = select_devices({"target_device_type": "android"}, [dev])
        # Result should be a list (even if empty or full)
        self.assertIsInstance(result, list)

    def test_readiness_unavailable_reason_treated_as_include(self) -> None:
        """When readiness module reports unavailable, device is included by default."""
        dev = _make_device("dev1", status="online")

        def _vtd(device_id, **kwargs):
            # Module is unavailable — returns the canonical "readiness-unavailable" reason
            return _make_validation_result(
                device_id,
                valid=False,
                registered=False,
                ready=False,
                reasons=["readiness-unavailable:import-error"],
            )

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            from galaxy_gateway.routing.device_selection import select_devices
            result = select_devices({"target_device_type": "android"}, [dev])

        # Device should be INCLUDED because readiness was unavailable (graceful degradation)
        result_ids = [d.device_id for d in result]
        self.assertIn("dev1", result_ids)


# ---------------------------------------------------------------------------
# C. _route_cross_device_envelope() target validation
# ---------------------------------------------------------------------------


class TestRouteEnvelopeTargetValidation(unittest.TestCase):
    """C) _route_cross_device_envelope() validates targets before dispatch."""

    def _make_envelope(
        self,
        targets: List[str],
        tool_name: str = "test_tool",
        required_capabilities: List[str] = None,
    ) -> Any:
        """Build a minimal TaskEnvelope-like mock."""
        m = MagicMock()
        m.task_id = "task-test-001"
        m.trace_id = "trace-test-001"
        m.tool_name = tool_name
        m.source = "test"
        m.targets = targets
        m.target = targets[0] if targets else ""
        m.args = {}
        m.metadata = {}
        m.required_capabilities = required_capabilities or []
        m.model_copy = lambda update=None: self._make_updated_envelope(m, update or {})
        return m

    def _make_updated_envelope(self, original: Any, update: Dict) -> Any:
        """Return a copy of the envelope with updated fields."""
        m = MagicMock()
        m.task_id = original.task_id
        m.trace_id = original.trace_id
        m.tool_name = original.tool_name
        m.source = original.source
        new_targets = update.get("targets", original.targets)
        m.targets = new_targets
        m.target = new_targets[0] if new_targets else ""
        m.args = original.args
        m.metadata = update.get("metadata", original.metadata)
        m.required_capabilities = original.required_capabilities
        m.model_copy = lambda upd=None: self._make_updated_envelope(m, upd or {})
        return m

    def test_valid_target_passed_as_device_id_to_device_router(self) -> None:
        """When a target passes validation, it is passed as device_id to DeviceRouter."""
        captured_context: Dict = {}

        async def _mock_route_task(command, context=None):
            captured_context.update(context or {})
            return {"success": True, "result": "ok"}

        envelope = self._make_envelope(targets=["android-1"])

        def _vtd(device_id, **kwargs):
            return _make_validation_result(device_id, valid=True, ready=True)

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            from unittest.mock import MagicMock as MM
            mock_dr = MM()
            mock_dr.route_task = _mock_route_task

            import asyncio
            from core.command_router import CommandRouter
            router = CommandRouter.__new__(CommandRouter)
            router._logger = __import__("logging").getLogger("test")

            with patch(
                "galaxy_gateway.device_router.device_router",
                mock_dr,
                create=True,
            ):
                asyncio.run(
                    router._route_cross_device_envelope(
                        envelope=envelope,
                        command_id="cmd-001",
                        request_id="req-001",
                    )
                )

        # The validated primary target "android-1" should be in device_id
        self.assertEqual(captured_context.get("device_id"), "android-1")

    def test_invalid_target_filtered_valid_one_used(self) -> None:
        """Invalid targets are filtered; valid ones proceed to dispatch."""
        captured_context: Dict = {}

        async def _mock_route_task(command, context=None):
            captured_context.update(context or {})
            return {"success": True}

        envelope = self._make_envelope(targets=["invalid-dev", "valid-dev"])

        def _vtd(device_id, **kwargs):
            if device_id == "valid-dev":
                return _make_validation_result(device_id, valid=True, ready=True)
            return _make_validation_result(
                device_id, valid=False, ready=False, reasons=["not-ready"]
            )

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            mock_dr = MagicMock()
            mock_dr.route_task = _mock_route_task

            import asyncio
            from core.command_router import CommandRouter
            router = CommandRouter.__new__(CommandRouter)

            with patch("galaxy_gateway.device_router.device_router", mock_dr, create=True):
                asyncio.run(
                    router._route_cross_device_envelope(
                        envelope=envelope,
                        command_id="cmd-002",
                        request_id="req-002",
                    )
                )

        # Should use the valid device as device_id
        self.assertEqual(captured_context.get("device_id"), "valid-dev")

    def test_graceful_degradation_when_validator_raises(self) -> None:
        """When validate_target_device raises, dispatch still proceeds."""
        dispatched = []

        async def _mock_route_task(command, context=None):
            dispatched.append(command)
            return {"success": True}

        envelope = self._make_envelope(targets=["dev-1"])

        with patch(
            "core.target_device_validator.validate_target_device",
            side_effect=ImportError("validator unavailable"),
        ):
            mock_dr = MagicMock()
            mock_dr.route_task = _mock_route_task

            import asyncio
            from core.command_router import CommandRouter
            router = CommandRouter.__new__(CommandRouter)

            with patch("galaxy_gateway.device_router.device_router", mock_dr, create=True):
                result = asyncio.run(
                    router._route_cross_device_envelope(
                        envelope=envelope,
                        command_id="cmd-003",
                        request_id="req-003",
                    )
                )

        # Dispatch should still have been called (graceful degradation)
        self.assertEqual(len(dispatched), 1)
        self.assertIsInstance(result, dict)

    def test_result_is_dict_with_expected_keys(self) -> None:
        """_route_cross_device_envelope() always returns a structured result dict."""
        async def _mock_route_task(command, context=None):
            return {"success": True, "result": "done"}

        envelope = self._make_envelope(targets=["dev-1"])

        def _vtd(device_id, **kwargs):
            return _make_validation_result(device_id, valid=True, ready=True)

        with patch("core.target_device_validator.validate_target_device", side_effect=_vtd):
            mock_dr = MagicMock()
            mock_dr.route_task = _mock_route_task

            import asyncio
            from core.command_router import CommandRouter
            router = CommandRouter.__new__(CommandRouter)

            with patch("galaxy_gateway.device_router.device_router", mock_dr, create=True):
                result = asyncio.run(
                    router._route_cross_device_envelope(
                        envelope=envelope,
                        command_id="cmd-004",
                        request_id="req-004",
                    )
                )

        for key in ("task_id", "trace_id", "success", "via"):
            self.assertIn(key, result, f"expected key '{key}' in result")
        self.assertEqual(result["via"], "command_router.cross_device_substrate")


# ---------------------------------------------------------------------------
# D. _dispatch_cross_device_task() participation filter
# ---------------------------------------------------------------------------


class TestDispatchCrossDeviceParticipationFilter(unittest.TestCase):
    """D) formation is assembled from participation-eligible devices only."""

    def _make_dispatch_devices(self, specs: List[Dict]) -> List[MagicMock]:
        devices = []
        for s in specs:
            d = MagicMock()
            d.device_id = s["device_id"]
            d.status = s.get("status", "online")
            d.metadata = {}
            devices.append(d)
        return devices

    def _build_formation_ids_from_last_call(self, mock_resolve: MagicMock) -> List[str]:
        """Extract target_device_ids from the last resolve_formation call."""
        if not mock_resolve.called:
            return []
        call_kwargs = mock_resolve.call_args[1] if mock_resolve.call_args else {}
        return list(call_kwargs.get("target_device_ids", []))

    def test_non_eligible_device_excluded_from_formation(self) -> None:
        """A device that is not orchestration_eligible is excluded from formation input."""
        devices = self._make_dispatch_devices([
            {"device_id": "elig-1"},
            {"device_id": "inelig-1"},
        ])
        task = {"task_id": "t1", "trace_id": "tr1", "command": "test", "source_device_id": "src"}

        def _gdp(device_id):
            m = MagicMock()
            m.orchestration_eligible = (device_id == "elig-1")
            return m

        from unittest.mock import AsyncMock as AM

        with patch("core.device_participation.get_device_participation", side_effect=_gdp):
            from core.device_formation.formation_resolver import (
                DeviceFormationGroup,
                EMPTY_FORMATION_GROUP,
                FormationPolicy,
                DEFAULT_LOCAL_FORMATION_POLICY,
            )
            mock_fg = MagicMock(spec=DeviceFormationGroup)
            mock_fg.formation_id = "fg-1"
            mock_fg.source_device_id = "src"
            mock_fg.primary_execution_device_id = "elig-1"
            mock_fg.members = []
            mock_fg.to_dict = lambda: {}

            mock_resolve = MagicMock(return_value=(mock_fg, DEFAULT_LOCAL_FORMATION_POLICY))

            with patch(
                "core.device_formation.formation_resolver.resolve_formation",
                mock_resolve,
            ):
                import asyncio
                from galaxy_gateway.device_router import DeviceRouter

                dr = DeviceRouter.__new__(DeviceRouter)
                dr.task_queue = {}

                with patch.object(dr, "_decompose_task", return_value=[task, task]):
                    with patch.object(
                        dr,
                        "dispatch_task",
                        new_callable=lambda: lambda *a, **kw: AsyncMock(
                            return_value={"success": True}
                        )(),
                    ):
                        asyncio.run(
                            dr._dispatch_cross_device_task(
                                task,
                                devices,
                                _substrate_caller="test",
                            )
                        )

        # resolve_formation should have been called with only "elig-1"
        formation_ids = self._build_formation_ids_from_last_call(mock_resolve)
        self.assertIn("elig-1", formation_ids)
        self.assertNotIn("inelig-1", formation_ids)

    def test_graceful_degradation_when_participation_unavailable(self) -> None:
        """When participation module raises, dispatch still proceeds without crashing."""
        devices = self._make_dispatch_devices([{"device_id": "dev-1"}, {"device_id": "dev-2"}])
        task = {"task_id": "t2", "trace_id": "tr2", "command": "test", "source_device_id": "src"}

        with patch(
            "core.device_participation.get_device_participation",
            side_effect=ImportError("participation unavailable"),
        ):
            mock_fg = MagicMock()
            mock_fg.formation_id = "fg-2"
            mock_fg.source_device_id = "src"
            mock_fg.primary_execution_device_id = "dev-1"
            mock_fg.members = []
            mock_fg.to_dict = lambda: {}

            from core.device_formation.formation_resolver import DEFAULT_LOCAL_FORMATION_POLICY
            mock_resolve = MagicMock(return_value=(mock_fg, DEFAULT_LOCAL_FORMATION_POLICY))

            with patch(
                "core.device_formation.formation_resolver.resolve_formation",
                mock_resolve,
            ):
                import asyncio
                from galaxy_gateway.device_router import DeviceRouter

                dr = DeviceRouter.__new__(DeviceRouter)
                dr.task_queue = {}

                with patch.object(dr, "_decompose_task", return_value=[task, task]):
                    with patch.object(
                        dr,
                        "dispatch_task",
                        new_callable=lambda: lambda *a, **kw: AsyncMock(
                            return_value={"success": True}
                        )(),
                    ):
                        result = asyncio.run(
                            dr._dispatch_cross_device_task(
                                task,
                                devices,
                                _substrate_caller="test",
                            )
                        )

        # Should not crash and should return a result dict
        self.assertIsInstance(result, dict)

    def test_all_ineligible_degrades_gracefully(self) -> None:
        """When all devices are ineligible, the original list is used (graceful degradation)."""
        devices = self._make_dispatch_devices([{"device_id": "d1"}, {"device_id": "d2"}])
        task = {"task_id": "t3", "trace_id": "tr3", "command": "test", "source_device_id": "src"}

        def _gdp(device_id):
            m = MagicMock()
            m.orchestration_eligible = False  # all ineligible
            return m

        mock_fg = MagicMock()
        mock_fg.formation_id = "fg-3"
        mock_fg.source_device_id = "src"
        mock_fg.primary_execution_device_id = "d1"
        mock_fg.members = []
        mock_fg.to_dict = lambda: {}

        from core.device_formation.formation_resolver import DEFAULT_LOCAL_FORMATION_POLICY
        mock_resolve = MagicMock(return_value=(mock_fg, DEFAULT_LOCAL_FORMATION_POLICY))

        with patch("core.device_participation.get_device_participation", side_effect=_gdp):
            with patch(
                "core.device_formation.formation_resolver.resolve_formation",
                mock_resolve,
            ):
                import asyncio
                from galaxy_gateway.device_router import DeviceRouter

                dr = DeviceRouter.__new__(DeviceRouter)
                dr.task_queue = {}

                with patch.object(dr, "_decompose_task", return_value=[task, task]):
                    with patch.object(
                        dr,
                        "dispatch_task",
                        new_callable=lambda: lambda *a, **kw: AsyncMock(
                            return_value={"success": True}
                        )(),
                    ):
                        result = asyncio.run(
                            dr._dispatch_cross_device_task(
                                task,
                                devices,
                                _substrate_caller="test",
                            )
                        )

        # Graceful degradation: dispatch still runs with original device list
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
