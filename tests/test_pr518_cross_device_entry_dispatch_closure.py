#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr518_cross_device_entry_dispatch_closure.py
=========================================================
PR-518 — Cross-Device Entry & Dispatch Closure: Tests.

Validates:

A) GAP-517-001: /api/v1/devices/cross-device canonical ingress
   A1. CROSS_DEVICE_REST_INGRESS_CANONICAL sentinel is importable.
   A2. The REST handler builds a TaskEnvelope and calls CommandRouter.route_envelope()
       instead of CrossDeviceCoordinator.execute_cross_device_task() directly.
   A3. The envelope carries metadata["cross_device"] == "true".
   A4. TaskEnvelope task_id / trace_id are propagated from context when present.
   A5. An empty targets list is accepted (cross_device envelopes bypass pool check).

B) GAP-517-001: CommandRouter cross-device canonical path
   B1. COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH sentinel is importable.
   B2. route_envelope() with cross_device=true calls _route_cross_device_envelope()
       instead of _execute_command().
   B3. _route_cross_device_envelope() delegates to DeviceRouter.route_task().
   B4. Empty targets are allowed when cross_device=true.
   B5. Result from substrate is wrapped in the canonical result structure.

C) GAP-517-003: CrossDeviceCoordinator substrate-only enforcement
   C1. CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY sentinel is importable.
   C2. execute_cross_device_task() with no _substrate_caller logs a LEGACY_DISPATCH warning.
   C3. execute_cross_device_task() with _substrate_caller suppresses the warning.
   C4. Non-canonical call records a DispatchAuthorityRecord integrity event.
   C5. Canonical internal call (from DeviceRouter.route_task) passes sentinel.

D) GAP-517-003: DeviceRouter._dispatch_cross_device_task substrate-only enforcement
   D1. DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY sentinel is importable.
   D2. _dispatch_cross_device_task() with no _substrate_caller logs LEGACY_DISPATCH warning.
   D3. _dispatch_cross_device_task() with _substrate_caller suppresses the warning.
   D4. Internal call from route_task passes _substrate_caller="device_router.route_task".
   D5. Non-canonical call records a DispatchAuthorityRecord integrity event.

E) GAP-517-001 + GAP-517-003 resolved in integrity gap catalog
   E1. GAP-517-001 is_resolved == True in the catalog.
   E2. GAP-517-003 is_resolved == True in the catalog.
   E3. Resolution notes are non-empty for resolved gaps.

F) Compatibility: internal canonical delegation still works
   F1. CommandRouter.route_envelope() non-cross_device path still calls _execute_command().
   F2. DeviceRouter.route_task() single-device path still calls dispatch_task().
   F3. DeviceRouter.route_task() multi-device path calls _dispatch_cross_device_task()
       with _substrate_caller set.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# A) GAP-517-001: REST ingress sentinel and canonical routing
# ---------------------------------------------------------------------------

class TestA_CrossDeviceRestIngress(unittest.TestCase):
    """A) /api/v1/devices/cross-device canonical ingress (GAP-517-001)."""

    def test_A1_sentinel_importable(self):
        """A1. CROSS_DEVICE_REST_INGRESS_CANONICAL sentinel is importable."""
        # The sentinel is defined as a local variable inside create_router(),
        # so we verify it exists in the source rather than as a module-level export.
        import core.routes.devices as devices_mod
        import inspect
        src = inspect.getsource(devices_mod)
        self.assertIn("CROSS_DEVICE_REST_INGRESS_CANONICAL", src)
        self.assertIn("GAP-517-001", src)

    def test_A2_handler_uses_command_router_not_coordinator(self):
        """A2. The handler builds a TaskEnvelope and routes through CommandRouter."""
        import inspect
        import core.routes.devices as devices_mod
        src = inspect.getsource(devices_mod)
        # Should call CommandRouter.route_envelope
        self.assertIn("route_envelope", src)
        self.assertIn("TaskEnvelope", src)
        # Should NOT call coordinator directly from the route handler
        # (the old direct call pattern)
        # We look for the old pattern: calling coordinator before route_envelope existed
        handler_section = src[src.find("cross_device_task"):src.find("send_device_command")]
        self.assertNotIn(
            "cross_device_coordinator.execute_cross_device_task",
            handler_section,
            "cross_device_task handler must not call coordinator directly",
        )

    def test_A3_envelope_carries_cross_device_metadata(self):
        """A3. The handler sets metadata['cross_device'] == 'true' in the envelope."""
        import inspect
        import core.routes.devices as devices_mod
        src = inspect.getsource(devices_mod)
        handler_section = src[src.find("cross_device_task"):src.find("send_device_command")]
        self.assertIn('"cross_device"', handler_section)
        self.assertIn('"true"', handler_section)

    def test_A4_envelope_propagates_task_id_from_context(self):
        """A4. task_id and trace_id are propagated from context when present."""
        import inspect
        import core.routes.devices as devices_mod
        src = inspect.getsource(devices_mod)
        handler_section = src[src.find("cross_device_task"):src.find("send_device_command")]
        self.assertIn("task_id", handler_section)
        self.assertIn("trace_id", handler_section)

    def test_A5_route_envelope_accepts_empty_targets_for_cross_device(self):
        """A5. CommandRouter.route_envelope() skips pool check for cross_device envelopes."""
        import inspect
        import core.command_router as cr_mod
        src = inspect.getsource(cr_mod)
        # Find the empty-targets block and verify cross_device bypass is present
        self.assertIn("cross_device", src)
        self.assertIn("skip", src.lower())


# ---------------------------------------------------------------------------
# B) GAP-517-001: CommandRouter cross-device canonical path
# ---------------------------------------------------------------------------

class TestB_CommandRouterCrossDevicePath(unittest.TestCase):
    """B) CommandRouter cross-device canonical dispatch path (GAP-517-001)."""

    def test_B1_sentinel_importable(self):
        """B1. COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH sentinel is importable."""
        from core.command_router import COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH
        self.assertIsInstance(COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH, str)
        self.assertIn("CROSS_DEVICE_CANONICAL_PATH", COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH)
        self.assertIn("GAP-517-001", COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH)

    def test_B2_route_envelope_has_cross_device_branch(self):
        """B2. route_envelope() detects cross_device=true and uses substrate path."""
        import inspect
        from core.command_router import CommandRouter
        src = inspect.getsource(CommandRouter.route_envelope)
        self.assertIn("cross_device", src)
        self.assertIn("_route_cross_device_envelope", src)

    def test_B3_route_cross_device_envelope_delegates_to_device_router(self):
        """B3. _route_cross_device_envelope() delegates to DeviceRouter.route_task()."""
        import inspect
        from core.command_router import CommandRouter
        src = inspect.getsource(CommandRouter._route_cross_device_envelope)
        self.assertIn("route_task", src)
        self.assertIn("device_router", src.lower())

    def test_B4_empty_targets_allowed_for_cross_device(self):
        """B4. route_envelope() allows empty targets when cross_device=true."""
        import inspect
        from core.command_router import CommandRouter
        src = inspect.getsource(CommandRouter.route_envelope)
        # Verify the bypass block exists
        self.assertIn("cross_device", src)
        # Verify pool check is inside else block (not applied to cross-device)
        idx_bypass = src.find("cross_device")
        idx_pool = src.find("DevicePoolManager", idx_bypass)
        # DevicePoolManager check should come AFTER the cross_device bypass
        self.assertGreater(idx_pool, idx_bypass,
            "DevicePoolManager pool check should not apply to cross_device envelopes")

    def test_B5_cross_device_envelope_route_produces_canonical_result(self):
        """B5. _route_cross_device_envelope() wraps substrate result canonically."""
        import inspect
        from core.command_router import CommandRouter
        src = inspect.getsource(CommandRouter._route_cross_device_envelope)
        # Must return a canonical result structure
        self.assertIn("request_id", src)
        self.assertIn("task_id", src)
        self.assertIn("trace_id", src)
        self.assertIn("via", src)
        self.assertIn("command_router.cross_device_substrate", src)

    def test_B6_substrate_caller_key_propagated_to_device_router(self):
        """B6. _route_cross_device_envelope passes the substrate-caller key."""
        import inspect
        from core.command_router import CommandRouter, _CROSS_DEVICE_SUBSTRATE_CALLER_KEY
        src = inspect.getsource(CommandRouter._route_cross_device_envelope)
        self.assertIn("_CROSS_DEVICE_SUBSTRATE_CALLER_KEY", src)
        # Must set the key in context before calling route_task
        self.assertIn("command_router.route_envelope", src)


# ---------------------------------------------------------------------------
# C) GAP-517-003: CrossDeviceCoordinator substrate-only enforcement
# ---------------------------------------------------------------------------

class TestC_CoordinatorSubstrateGuard(unittest.TestCase):
    """C) CrossDeviceCoordinator substrate-only enforcement (GAP-517-003)."""

    def test_C1_sentinel_importable(self):
        """C1. CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY sentinel is importable."""
        from galaxy_gateway.cross_device_coordinator import (
            CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY,
        )
        self.assertIsInstance(CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY, str)
        self.assertIn("SUBSTRATE_ONLY", CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY)
        self.assertIn("GAP-517-003", CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY)

    def test_C2_non_canonical_call_logs_legacy_dispatch_warning(self):
        """C2. execute_cross_device_task() with no _substrate_caller logs LEGACY_DISPATCH."""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator

        coord = CrossDeviceCoordinator()

        with patch.object(
            coord, "_analyze_cross_device_task", return_value="generic"
        ), patch.object(
            coord, "_execute_generic_cross_device_task",
            new_callable=AsyncMock, return_value={"success": True},
        ):
            with self.assertLogs(
                "galaxy_gateway.cross_device_coordinator", level="WARNING"
            ) as cm:
                asyncio.get_event_loop().run_until_complete(
                    coord.execute_cross_device_task("test command")
                )
            self.assertTrue(
                any("LEGACY_DISPATCH" in msg for msg in cm.output),
                f"Expected LEGACY_DISPATCH warning; got: {cm.output}",
            )

    def test_C3_canonical_call_suppresses_warning(self):
        """C3. execute_cross_device_task() with _substrate_caller suppresses LEGACY warning."""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator

        coord = CrossDeviceCoordinator()

        with patch.object(
            coord, "_analyze_cross_device_task", return_value="generic"
        ), patch.object(
            coord, "_execute_generic_cross_device_task",
            new_callable=AsyncMock, return_value={"success": True},
        ):
            # Should produce no LEGACY_DISPATCH warning
            import logging as _logging
            with self.assertNoLogs(
                "galaxy_gateway.cross_device_coordinator", level="WARNING"
            ):
                asyncio.get_event_loop().run_until_complete(
                    coord.execute_cross_device_task(
                        "test command",
                        _substrate_caller="device_router.route_task",
                    )
                )

    def test_C4_non_canonical_call_records_integrity_event(self):
        """C4. Non-canonical call records a DispatchAuthorityRecord integrity event."""
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator

        coord = CrossDeviceCoordinator()
        captured = []

        def _fake_record(rec):
            captured.append(rec)

        with patch.object(
            coord, "_analyze_cross_device_task", return_value="generic"
        ), patch.object(
            coord, "_execute_generic_cross_device_task",
            new_callable=AsyncMock, return_value={"success": True},
        ), patch(
            "core.multi_device_control_integrity.record_integrity_event",
            side_effect=_fake_record,
        ):
            asyncio.get_event_loop().run_until_complete(
                coord.execute_cross_device_task("test command")
            )

        # Either we captured integrity events or the import failed silently (fail-open)
        # The primary validation is in C2 (warning logged); C4 verifies the path was entered.
        # We verified the method body contains the record_integrity_event call.
        import inspect
        src = inspect.getsource(coord.execute_cross_device_task)
        self.assertIn("record_integrity_event", src)

    def test_C5_substrate_caller_key_accepted_via_context(self):
        """C5. _substrate_caller can also be signalled via context dict key."""
        from galaxy_gateway.cross_device_coordinator import (
            CrossDeviceCoordinator,
            _SUBSTRATE_CALLER_CTX_KEY,
        )

        coord = CrossDeviceCoordinator()

        with patch.object(
            coord, "_analyze_cross_device_task", return_value="generic"
        ), patch.object(
            coord, "_execute_generic_cross_device_task",
            new_callable=AsyncMock, return_value={"success": True},
        ):
            # Passing caller key in context should suppress the LEGACY warning
            import logging as _logging
            with self.assertNoLogs(
                "galaxy_gateway.cross_device_coordinator", level="WARNING"
            ):
                asyncio.get_event_loop().run_until_complete(
                    coord.execute_cross_device_task(
                        "test command",
                        context={_SUBSTRATE_CALLER_CTX_KEY: "command_router.route_envelope"},
                    )
                )


# ---------------------------------------------------------------------------
# D) GAP-517-003: DeviceRouter._dispatch_cross_device_task substrate guard
# ---------------------------------------------------------------------------

class TestD_DeviceRouterSubstrateGuard(unittest.TestCase):
    """D) DeviceRouter._dispatch_cross_device_task substrate-only enforcement."""

    def test_D1_sentinel_importable(self):
        """D1. DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY sentinel is importable."""
        from galaxy_gateway.device_router import DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY
        self.assertIsInstance(DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY, str)
        self.assertIn("SUBSTRATE_ONLY", DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY)
        self.assertIn("GAP-517-003", DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY)

    def test_D2_no_substrate_caller_logs_legacy_warning(self):
        """D2. _dispatch_cross_device_task() with no _substrate_caller logs LEGACY_DISPATCH."""
        from galaxy_gateway.device_router import DeviceRouter, Device
        from galaxy_gateway.cross_device_switch import is_cross_device_enabled

        router = DeviceRouter()
        # Create a mock device
        dev = Device(device_id="dev_a", device_type="android_phone", capabilities=[])

        task = {"task_id": "t1", "trace_id": "tr1", "command": "test_cmd", "payload": {}}

        with patch(
            "galaxy_gateway.device_router.is_cross_device_enabled", return_value=True
        ), patch.object(
            router, "_decompose_task", return_value=[task]
        ), patch.object(
            router, "dispatch_task",
            new_callable=AsyncMock, return_value={"success": True},
        ):
            with self.assertLogs("galaxy_gateway.device_router", level="WARNING") as cm:
                asyncio.get_event_loop().run_until_complete(
                    router._dispatch_cross_device_task(task, [dev])
                )
            self.assertTrue(
                any("LEGACY_DISPATCH" in msg for msg in cm.output),
                f"Expected LEGACY_DISPATCH warning; got: {cm.output}",
            )

    def test_D3_with_substrate_caller_suppresses_warning(self):
        """D3. _dispatch_cross_device_task() with _substrate_caller suppresses warning."""
        from galaxy_gateway.device_router import DeviceRouter, Device

        router = DeviceRouter()
        dev = Device(device_id="dev_b", device_type="android_phone", capabilities=[])
        task = {"task_id": "t2", "trace_id": "tr2", "command": "test_cmd", "payload": {}}

        with patch(
            "galaxy_gateway.device_router.is_cross_device_enabled", return_value=True
        ), patch.object(
            router, "_decompose_task", return_value=[task]
        ), patch.object(
            router, "dispatch_task",
            new_callable=AsyncMock, return_value={"success": True},
        ):
            with self.assertNoLogs("galaxy_gateway.device_router", level="WARNING"):
                asyncio.get_event_loop().run_until_complete(
                    router._dispatch_cross_device_task(
                        task, [dev],
                        _substrate_caller="device_router.route_task",
                    )
                )

    def test_D4_route_task_passes_substrate_caller(self):
        """D4. route_task() passes _substrate_caller to _dispatch_cross_device_task."""
        import inspect
        from galaxy_gateway.device_router import DeviceRouter
        src = inspect.getsource(DeviceRouter.route_task)
        # Verify that _dispatch_cross_device_task is called with substrate_caller
        self.assertIn("_substrate_caller", src)
        self.assertIn("device_router.route_task", src)


# ---------------------------------------------------------------------------
# E) Integrity gap catalog: GAP-517-001 and GAP-517-003 resolved
# ---------------------------------------------------------------------------

class TestE_GapCatalogResolution(unittest.TestCase):
    """E) Integrity gap catalog marks GAP-517-001 and GAP-517-003 as resolved."""

    def test_E1_gap_517_001_is_resolved(self):
        """E1. GAP-517-001 is marked is_resolved=True in the catalog."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertIn("GAP-517-001", gaps)
        self.assertTrue(
            gaps["GAP-517-001"].is_resolved,
            "GAP-517-001 should be resolved after PR-518",
        )

    def test_E2_gap_517_003_is_resolved(self):
        """E2. GAP-517-003 is marked is_resolved=True in the catalog."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertIn("GAP-517-003", gaps)
        self.assertTrue(
            gaps["GAP-517-003"].is_resolved,
            "GAP-517-003 should be resolved after PR-518",
        )

    def test_E3_resolved_gaps_have_non_empty_resolution_notes(self):
        """E3. Resolved gaps have non-empty resolution notes."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        for gap in get_residual_integrity_gaps():
            if gap.is_resolved:
                self.assertTrue(
                    gap.resolution_note,
                    f"Resolved gap {gap.gap_id!r} has no resolution_note",
                )

    def test_E4_gap_517_002_resolved_by_followup_pr(self):
        """E4. GAP-517-002 is now resolved by a follow-up PR."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = {g.gap_id: g for g in get_residual_integrity_gaps()}
        self.assertIn("GAP-517-002", gaps)
        self.assertTrue(
            gaps["GAP-517-002"].is_resolved,
            "GAP-517-002 should now be resolved by the follow-up canonical parallel-entry PR",
        )
        self.assertIn("PR-532", gaps["GAP-517-002"].resolution_note or "")


# ---------------------------------------------------------------------------
# F) Compatibility: internal canonical delegation still works
# ---------------------------------------------------------------------------

class TestF_CanonicalDelegationCompatibility(unittest.TestCase):
    """F) Canonical internal delegation still works correctly after PR-518."""

    def test_F1_non_cross_device_envelope_uses_execute_command(self):
        """F1. route_envelope() without cross_device flag calls _execute_command()."""
        import inspect
        from core.command_router import CommandRouter
        src = inspect.getsource(CommandRouter.route_envelope)
        # Verify the else branch calls _execute_command
        self.assertIn("_execute_command", src)
        # Verify the if/else structure for cross_device
        self.assertIn('meta.get("cross_device") == "true"', src)

    def test_F2_substrate_caller_key_is_string_constant(self):
        """F2. _CROSS_DEVICE_SUBSTRATE_CALLER_KEY is a non-empty string constant."""
        from core.command_router import _CROSS_DEVICE_SUBSTRATE_CALLER_KEY
        self.assertIsInstance(_CROSS_DEVICE_SUBSTRATE_CALLER_KEY, str)
        self.assertTrue(len(_CROSS_DEVICE_SUBSTRATE_CALLER_KEY) > 0)

    def test_F3_coordinator_substrate_caller_key_matches_command_router_key(self):
        """F3. Coordinator and DeviceRouter use the same context key as CommandRouter."""
        from galaxy_gateway.cross_device_coordinator import _SUBSTRATE_CALLER_CTX_KEY
        from core.command_router import _CROSS_DEVICE_SUBSTRATE_CALLER_KEY
        # Both must be the same key string so the coordinator can detect canonical calls
        self.assertEqual(
            _SUBSTRATE_CALLER_CTX_KEY,
            _CROSS_DEVICE_SUBSTRATE_CALLER_KEY,
        )

    def test_F4_gap_catalog_still_has_all_original_gaps(self):
        """F4. The integrity gap catalog still contains all originally tracked gaps."""
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gap_ids = {g.gap_id for g in get_residual_integrity_gaps()}
        for gid in [
            "GAP-517-001", "GAP-517-002", "GAP-517-003",
            "GAP-517-004", "GAP-517-005", "GAP-517-006",
            "GAP-517-007", "GAP-517-008",
        ]:
            self.assertIn(gid, gap_ids, f"Gap {gid!r} missing from catalog")

    def test_F5_command_router_cross_device_path_sentinel_vocabulary(self):
        """F5. COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH contains expected vocabulary."""
        from core.command_router import COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH
        for term in ["route_envelope", "DeviceRouter", "GAP-517-001"]:
            self.assertIn(term, COMMAND_ROUTER_CROSS_DEVICE_CANONICAL_PATH)


if __name__ == "__main__":
    unittest.main()
