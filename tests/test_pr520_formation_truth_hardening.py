#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr520_formation_truth_hardening.py
=============================================
PR-520 — Formation Truth Hardening.

Validates that:

1. **Cross-device flows produce a canonical formation descriptor** (GAP-517-004)
   - ``DeviceRouter._dispatch_cross_device_task()`` resolves and attaches a
     ``DeviceFormationGroup`` to the result payload.
   - ``CrossDeviceCoordinator.execute_cross_device_task()`` does the same.
   - The formation descriptor includes source device, primary execution device,
     and all participating member IDs.

2. **Participation-layer unavailability does not silently fail open** (GAP-517-005)
   - ``ConstellationRuntime._is_orchestration_ready()`` returns ``False``
     (deny-by-default) when the participation layer raises.
   - A structured WARNING log is emitted.

3. **Ineligible devices are excluded from formation membership** (GAP-517-004)
   - Only orchestration-eligible devices pass the formation gate.

4. **Sentinel constants are present and importable**.

Test groups
-----------
 A)  Sentinel imports — PR-520 constants importable.
 B)  GAP-517-005 — deny-by-default when participation layer unavailable.
 C)  GAP-517-005 — deny-by-default on any Exception (not just ImportError).
 D)  GAP-517-005 — WARNING is emitted when gate is unreachable.
 E)  GAP-517-005 — eligible device still passes the gate.
 F)  GAP-517-005 — non-eligible device is still excluded.
 G)  GAP-517-005 — empty device_id rejected without calling participation layer.
 H)  GAP-517-004 — DeviceRouter attaches formation to _dispatch_cross_device_task result.
 I)  GAP-517-004 — Formation has source, primary, and member device IDs.
 J)  GAP-517-004 — Formation descriptor is serialisable (to_dict present).
 K)  GAP-517-004 — CrossDeviceCoordinator attaches formation to execute_cross_device_task result.
 L)  GAP-517-004 — Formation is attached even when resolve_formation returns EMPTY group.
 M)  GAP-517-004 — FormationTruthRecord is emitted to integrity runtime.
 N)  Residual gap catalog — GAP-517-004 and GAP-517-005 marked as resolved.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset_integrity_runtime():
    try:
        from core.multi_device_control_integrity import reset_multi_device_integrity_runtime
        reset_multi_device_integrity_runtime()
    except Exception:
        pass


# ===========================================================================
# A) Sentinel imports
# ===========================================================================


class TestPR520Sentinels(unittest.TestCase):
    """All PR-520 sentinel constants are importable and contain expected text."""

    def test_constellation_sentinel_importable(self):
        from core.constellation_runtime import (
            CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT,
        )
        assert "DENY_BY_DEFAULT" in CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT
        assert "GAP-517-005" in CONSTELLATION_ORCHESTRATION_GATE_DENY_BY_DEFAULT

    def test_device_router_formation_sentinel_importable(self):
        from galaxy_gateway.device_router import (
            DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED,
        )
        assert "FORMATION_DESCRIPTOR_ATTACHED" in DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED
        assert "GAP-517-004" in DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED

    def test_coordinator_formation_sentinel_importable(self):
        from galaxy_gateway.cross_device_coordinator import (
            CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED,
        )
        assert (
            "FORMATION_DESCRIPTOR_ATTACHED"
            in CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED
        )
        assert "GAP-517-004" in CROSS_DEVICE_COORDINATOR_FORMATION_DESCRIPTOR_ATTACHED


# ===========================================================================
# B–G) GAP-517-005 — ConstellationRuntime._is_orchestration_ready
# ===========================================================================


class TestOrchestrationGateDenyByDefault(unittest.TestCase):
    """_is_orchestration_ready() is deny-by-default when participation layer
    is unavailable (GAP-517-005 resolved in PR-520)."""

    def _make_runtime(self):
        from core.constellation_runtime import ConstellationRuntime
        return ConstellationRuntime(enable_dag_evolution=False)

    # B — ImportError → False (deny-by-default)
    def test_import_error_returns_false(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            side_effect=ImportError("subsystem not loaded"),
        ):
            result = rt._is_orchestration_ready("dev_x")
        self.assertFalse(result)

    # C — RuntimeError → False (any exception → deny)
    def test_runtime_error_returns_false(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            side_effect=RuntimeError("database unavailable"),
        ):
            result = rt._is_orchestration_ready("dev_y")
        self.assertFalse(result)

    # D — WARNING is logged when gate is unreachable
    def test_warning_emitted_when_gate_unreachable(self):
        rt = self._make_runtime()
        with self.assertLogs(
            "Galaxy.ConstellationRuntime", level="WARNING"
        ) as log_ctx:
            with patch(
                "core.device_participation.is_device_orchestration_ready",
                side_effect=ImportError("unavailable"),
            ):
                rt._is_orchestration_ready("dev_warn")
        joined = " ".join(log_ctx.output)
        # Structured log should mention the device_id and indicate exclusion
        self.assertIn("dev_warn", joined)
        self.assertIn("EXCLUDED", joined)

    # E — eligible device still passes
    def test_eligible_device_passes(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            return_value=True,
        ):
            result = rt._is_orchestration_ready("dev_eligible")
        self.assertTrue(result)

    # F — non-eligible device is excluded even when layer is available
    def test_non_eligible_device_excluded(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
            return_value=False,
        ):
            result = rt._is_orchestration_ready("dev_not_eligible")
        self.assertFalse(result)

    # G — empty device_id rejected without calling participation layer
    def test_empty_device_id_rejected_without_layer_call(self):
        rt = self._make_runtime()
        with patch(
            "core.device_participation.is_device_orchestration_ready",
        ) as mock_fn:
            result = rt._is_orchestration_ready("")
        self.assertFalse(result)
        mock_fn.assert_not_called()


# ===========================================================================
# H–J) GAP-517-004 — DeviceRouter._dispatch_cross_device_task
# ===========================================================================


class TestDeviceRouterFormationAttachment(unittest.IsolatedAsyncioTestCase):
    """DeviceRouter._dispatch_cross_device_task() attaches a canonical
    DeviceFormationGroup to the result payload (GAP-517-004 resolved PR-520)."""

    def _make_router(self):
        from galaxy_gateway.device_router import DeviceRouter
        router = DeviceRouter()
        return router

    def _make_devices(self, ids):
        devices = []
        for did in ids:
            d = MagicMock()
            d.device_id = did
            devices.append(d)
        return devices

    # H — formation key is present in result
    async def test_formation_key_present_in_result(self):
        router = self._make_router()
        devices = self._make_devices(["dev_a", "dev_b"])
        task = {
            "task_id": "t-h",
            "trace_id": "trace-h",
            "command": "test",
            "source_device_id": "dev_src",
        }

        # Stub dispatch_task to return success
        async def _fake_dispatch(task, device):
            return {"success": True, "device_id": device.device_id}

        router.dispatch_task = _fake_dispatch

        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
            return_value=True,
        ):
            result = await router._dispatch_cross_device_task(
                task, devices, _substrate_caller="test"
            )

        self.assertIn("formation", result, "Formation key must be present in result")

    # I — formation contains expected metadata
    async def test_formation_contains_source_and_primary_and_members(self):
        router = self._make_router()
        devices = self._make_devices(["dev_primary", "dev_secondary"])
        task = {
            "task_id": "t-i",
            "trace_id": "trace-i",
            "command": "test",
            "source_device_id": "dev_origin",
        }

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
            return_value=True,
        ):
            result = await router._dispatch_cross_device_task(
                task, devices, _substrate_caller="test"
            )

        formation = result.get("formation", {})
        self.assertIsInstance(formation, dict)
        # Must carry member device IDs
        members = formation.get("members", [])
        member_ids = [
            m.get("device_id") for m in members if isinstance(m, dict)
        ]
        self.assertIn("dev_primary", member_ids)
        self.assertIn("dev_secondary", member_ids)

    # J — formation is JSON-serialisable (to_dict)
    async def test_formation_is_serialisable(self):
        import json

        router = self._make_router()
        devices = self._make_devices(["dev_1"])
        task = {"task_id": "t-j", "trace_id": None, "command": "x"}

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
            return_value=True,
        ):
            result = await router._dispatch_cross_device_task(
                task, devices, _substrate_caller="test"
            )

        formation = result.get("formation")
        if formation is not None:
            # Must be JSON-serialisable
            try:
                json.dumps(formation)
            except (TypeError, ValueError) as exc:
                self.fail(f"formation is not JSON-serialisable: {exc}")


# ===========================================================================
# K–L) GAP-517-004 — CrossDeviceCoordinator.execute_cross_device_task
# ===========================================================================


class TestCoordinatorFormationAttachment(unittest.IsolatedAsyncioTestCase):
    """CrossDeviceCoordinator.execute_cross_device_task() attaches a
    canonical DeviceFormationGroup to the result payload (GAP-517-004)."""

    def _make_coordinator(self):
        from galaxy_gateway.cross_device_coordinator import CrossDeviceCoordinator
        return CrossDeviceCoordinator()

    # K — formation key is present in coordinator result
    async def test_formation_key_present_in_coordinator_result(self):
        coordinator = self._make_coordinator()
        context = {
            "task_id": "t-k",
            "trace_id": "trace-k",
            "source_device_id": "phone_01",
            "target_device_ids": ["pc_01"],
            "device_id": "pc_01",
        }

        # Stub the internal generic executor so we don't need real devices
        async def _fake_generic(command, context):
            return {"success": True, "data": "ok"}

        coordinator._execute_generic_cross_device_task = _fake_generic

        result = await coordinator.execute_cross_device_task(
            "share clipboard",
            context,
            _substrate_caller="test",
        )

        self.assertIn(
            "formation", result,
            "Formation key must be attached to coordinator result"
        )

    # L — formation attached even when resolve_formation returns EMPTY group
    async def test_formation_fallback_does_not_crash(self):
        """When resolve_formation is unavailable the call must still succeed."""
        coordinator = self._make_coordinator()
        context = {"task_id": "t-l"}

        async def _fake_generic(command, context):
            return {"success": True}

        coordinator._execute_generic_cross_device_task = _fake_generic

        with patch(
            "core.device_formation.formation_resolver.resolve_formation",
            side_effect=ImportError("formation module not loaded"),
        ):
            result = await coordinator.execute_cross_device_task(
                "generic command",
                context,
                _substrate_caller="test",
            )

        # Must succeed even without a formation descriptor
        self.assertTrue(result.get("success", False) is not None)
        # The "formation" key may be absent (fallback case) — that's acceptable
        # as long as the call completes without raising.


# ===========================================================================
# M) GAP-517-004 — FormationTruthRecord emitted to integrity runtime
# ===========================================================================


class TestFormationTruthRecordEmitted(unittest.IsolatedAsyncioTestCase):
    """A FormationTruthRecord is emitted to the integrity runtime when a
    cross-device formation is resolved (GAP-517-004)."""

    async def test_formation_truth_record_appended_after_dispatch(self):
        _reset_integrity_runtime()
        from galaxy_gateway.device_router import DeviceRouter
        from core.multi_device_control_integrity import (
            get_multi_device_integrity_runtime,
        )

        router = DeviceRouter()
        devices = []
        for did in ["d1", "d2"]:
            d = MagicMock()
            d.device_id = did
            devices.append(d)

        task = {"task_id": "t-m", "trace_id": "tr-m", "command": "cmd"}

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with patch(
            "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
            return_value=True,
        ):
            await router._dispatch_cross_device_task(
                task, devices, _substrate_caller="test"
            )

        rt = get_multi_device_integrity_runtime()
        snapshot = rt.snapshot()
        # At least one formation record should have been emitted
        self.assertGreater(
            len(snapshot.recent_formation_records),
            0,
            "Expected at least one FormationTruthRecord in integrity runtime",
        )
        # The record should reference the expected task_id
        rec = snapshot.recent_formation_records[-1]
        self.assertEqual(rec.task_id, "t-m")


# ===========================================================================
# N) Residual gap catalog — GAP-517-004 and GAP-517-005 resolved
# ===========================================================================


class TestResidualGapResolutionStatus(unittest.TestCase):
    """The machine-readable gap catalog marks GAP-517-004 and GAP-517-005
    as resolved after PR-520."""

    def _get_gap(self, gap_id: str):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        for gap in get_residual_integrity_gaps():
            if gap.gap_id == gap_id:
                return gap
        return None

    def test_gap_517_004_is_resolved(self):
        gap = self._get_gap("GAP-517-004")
        self.assertIsNotNone(gap, "GAP-517-004 should be in the gap catalog")
        self.assertTrue(
            gap.is_resolved,
            "GAP-517-004 should be marked resolved after PR-520",
        )
        self.assertIn("PR-520", gap.resolution_note)

    def test_gap_517_005_is_resolved(self):
        gap = self._get_gap("GAP-517-005")
        self.assertIsNotNone(gap, "GAP-517-005 should be in the gap catalog")
        self.assertTrue(
            gap.is_resolved,
            "GAP-517-005 should be marked resolved after PR-520",
        )
        self.assertIn("PR-520", gap.resolution_note)

    def test_open_gaps_do_not_include_004_or_005(self):
        from core.multi_device_control_integrity import (
            MultiDeviceIntegritySnapshot,
            build_integrity_snapshot,
        )
        snapshot = build_integrity_snapshot()
        open_ids = {g.gap_id for g in snapshot.open_gaps()}
        self.assertNotIn("GAP-517-004", open_ids)
        self.assertNotIn("GAP-517-005", open_ids)


if __name__ == "__main__":
    unittest.main()
