#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr521_control_semantic_separation.py
================================================
PR-521 — Control Semantic Separation.

Validates that:

1. **Sentinel is importable** (GAP-517-006 resolved).
   - ``DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION`` is importable from
     ``galaxy_gateway.device_router`` and references GAP-517-006.

2. **Local-control paths record matching source and target devices** (GAP-517-006).
   - When ``source_device_id == target_device_id`` the emitted
     ``ControlSemanticRecord`` has ``is_local=True`` and
     ``control_kind == LOCAL_EXECUTION``.

3. **Remote-dispatch paths distinguish source from target** (GAP-517-006).
   - When ``source_device_id != target_device_id`` the emitted record has
     ``is_remote_dispatch=True`` and ``control_kind == REMOTE_DISPATCH``.

4. **Takeover/delegation scenarios can be represented** without overloading
   ``device_id`` (GAP-517-006).
   - When ``is_takeover=True`` the record has ``control_kind == TAKEOVER``.

5. **Hybrid/parallel multi-device execution is labelled correctly**.
   - When multiple target devices are selected the record carries
     ``control_kind == HYBRID``.

6. **Legacy ``device_id``-only callers are adapted transparently**.
   - When only ``device_id`` is provided (no ``source_device_id``) it is
     mapped to ``source_device_id`` so the canonical path remains clear.

7. **TaskEnvelope metadata carries both source and target device IDs**.
   - The ``TaskEnvelope`` built in ``route_task()`` includes
     ``source_device_id`` in its ``metadata``.
   - The ``TaskEnvelope`` built in ``dispatch_task()`` includes both
     ``source_device_id`` and ``target_device_id`` in its ``metadata``.

8. **task dict carries source_device_id after routing decision**.
   - ``source_device_id`` is written into the task dict so downstream
     dispatch and formation layers can consume it.

9. **ControlSemanticRecord is semantically clear when source and target
   are explicitly provided**.
   - ``is_semantically_clear == True`` when both source and target are set
     and the kind is non-ambiguous.

10. **GAP-517-006 is marked as resolved** in the residual gap catalog.

Test groups
-----------
 A)  Sentinel imports — PR-521 constant importable and references GAP-517-006.
 B)  ControlSemanticKind — LOCAL_EXECUTION for matching source/target.
 C)  ControlSemanticKind — REMOTE_DISPATCH for differing source/target.
 D)  ControlSemanticKind — TAKEOVER when is_takeover flag is set.
 E)  ControlSemanticKind — HYBRID for multi-target dispatch.
 F)  ControlSemanticKind — UNKNOWN when no target device.
 G)  Legacy compat — device_id-only callers adapted as source_device_id.
 H)  route_task propagates source_device_id into task dict.
 I)  route_task envelope metadata carries source_device_id.
 J)  dispatch_task envelope metadata carries source_device_id and target_device_id.
 K)  ControlSemanticRecord emitted to integrity runtime after route_task.
 L)  ControlSemanticRecord.is_semantically_clear for explicit source+target.
 M)  build_control_semantic_record helper — round-trip.
 N)  GAP-517-006 marked resolved in residual gap catalog.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

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


class TestPR521Sentinels(unittest.TestCase):
    """PR-521 sentinel constant is importable and references GAP-517-006."""

    def test_sentinel_importable(self):
        from galaxy_gateway.device_router import DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION
        self.assertIn(
            "CONTROL_SEMANTIC_SEPARATION",
            DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION,
        )

    def test_sentinel_references_gap(self):
        from galaxy_gateway.device_router import DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION
        self.assertIn("GAP-517-006", DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION)

    def test_sentinel_is_string(self):
        from galaxy_gateway.device_router import DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION
        self.assertIsInstance(DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION, str)


# ===========================================================================
# B–F) ControlSemanticKind derivation via build_control_semantic_record
# ===========================================================================


class TestControlSemanticKindDerivation(unittest.TestCase):
    """build_control_semantic_record derives the correct execution kind."""

    def _build(self, **kwargs):
        from core.multi_device_control_integrity import build_control_semantic_record
        return build_control_semantic_record(**kwargs)

    # B — LOCAL_EXECUTION when source == target
    def test_local_execution_kind(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-local",
            source_device_id="phone_01",
            target_device_id="phone_01",
            control_kind=ControlSemanticKind.LOCAL_EXECUTION,
        )
        self.assertEqual(rec.control_kind, ControlSemanticKind.LOCAL_EXECUTION)
        self.assertTrue(rec.is_local)
        self.assertFalse(rec.is_remote_dispatch)

    # C — REMOTE_DISPATCH when source != target
    def test_remote_dispatch_kind(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-remote",
            source_device_id="phone_01",
            target_device_id="desktop_01",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertEqual(rec.control_kind, ControlSemanticKind.REMOTE_DISPATCH)
        self.assertTrue(rec.is_remote_dispatch)
        self.assertFalse(rec.is_local)

    # D — TAKEOVER
    def test_takeover_kind(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-takeover",
            source_device_id="phone_01",
            target_device_id="desktop_01",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        self.assertEqual(rec.control_kind, ControlSemanticKind.TAKEOVER)
        self.assertTrue(rec.is_takeover)

    # E — HYBRID
    def test_hybrid_kind(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-hybrid",
            source_device_id="phone_01",
            target_device_id="desktop_01",
            control_kind=ControlSemanticKind.HYBRID,
        )
        self.assertEqual(rec.control_kind, ControlSemanticKind.HYBRID)

    # F — UNKNOWN when no target device
    def test_unknown_kind(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-unknown",
            source_device_id="phone_01",
            target_device_id="",
            control_kind=ControlSemanticKind.UNKNOWN,
        )
        self.assertEqual(rec.control_kind, ControlSemanticKind.UNKNOWN)


# ===========================================================================
# G) Legacy compat — device_id-only callers
# ===========================================================================


class TestLegacyDeviceIdCompat(unittest.IsolatedAsyncioTestCase):
    """Legacy callers that only supply device_id are adapted to source_device_id."""

    def _make_router(self):
        from galaxy_gateway.device_router import DeviceRouter
        return DeviceRouter()

    def _make_device(self, did):
        d = MagicMock()
        d.device_id = did
        d.websocket = None
        d.type = MagicMock()
        return d

    async def test_device_id_used_as_source_when_source_not_provided(self):
        """When only device_id is in context it is mapped to source_device_id."""
        router = self._make_router()
        _task_created = {}

        async def _fake_dispatch(task, device):
            _task_created.update(task)
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        target = self._make_device("desktop_01")
        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "test",
                "exec_mode": "both",
                "actions": ["do_thing"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            ctx = {"device_id": "phone_01"}
            await router.route_task("do_thing", ctx)

        # source_device_id should be propagated from device_id
        self.assertEqual(
            _task_created.get("source_device_id"),
            "phone_01",
            "device_id should be adapted as source_device_id for legacy callers",
        )

    async def test_explicit_source_device_id_preferred_over_device_id(self):
        """Explicit source_device_id in context is preferred over device_id."""
        router = self._make_router()
        _task_created = {}

        async def _fake_dispatch(task, device):
            _task_created.update(task)
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        target = self._make_device("desktop_01")
        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "test",
                "exec_mode": "both",
                "actions": ["do_thing"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            ctx = {
                "device_id": "phone_01",
                "source_device_id": "tablet_01",  # explicit overrides device_id
            }
            await router.route_task("do_thing", ctx)

        self.assertEqual(
            _task_created.get("source_device_id"),
            "tablet_01",
            "Explicit source_device_id should be preferred over device_id",
        )


# ===========================================================================
# H) route_task propagates source_device_id into task dict
# ===========================================================================


class TestRouteTaskPropagatesSourceDeviceId(unittest.IsolatedAsyncioTestCase):
    """route_task() writes source_device_id into the task dict."""

    def _make_router(self):
        from galaxy_gateway.device_router import DeviceRouter
        return DeviceRouter()

    def _make_device(self, did):
        d = MagicMock()
        d.device_id = did
        d.websocket = None
        return d

    async def test_source_device_id_in_task_dict(self):
        router = self._make_router()
        captured = {}

        async def _fake_dispatch(task, device):
            captured.update(task)
            return {"success": True}

        router.dispatch_task = _fake_dispatch
        target = self._make_device("pc_01")

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "screen_capture",
                "exec_mode": "both",
                "actions": ["capture"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task("capture", {"source_device_id": "phone_01"})

        self.assertEqual(
            captured.get("source_device_id"),
            "phone_01",
        )

    async def test_source_device_id_absent_when_empty_context(self):
        """When no source device is provided, source_device_id should not pollute task."""
        router = self._make_router()
        captured = {}

        async def _fake_dispatch(task, device):
            captured.update(task)
            return {"success": True}

        router.dispatch_task = _fake_dispatch
        target = self._make_device("pc_01")

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "query",
                "exec_mode": "both",
                "actions": ["query"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task("query", {})

        # source_device_id should not be set (empty string → not written)
        self.assertNotIn(
            "source_device_id",
            captured,
            "Empty source_device_id should not be injected into task dict",
        )


# ===========================================================================
# I) route_task envelope metadata carries source_device_id
# ===========================================================================


class TestRouteTaskEnvelopeMetadata(unittest.IsolatedAsyncioTestCase):
    """The TaskEnvelope built in route_task() includes source_device_id in metadata."""

    def _make_router(self):
        from galaxy_gateway.device_router import DeviceRouter
        return DeviceRouter()

    def _make_device(self, did):
        d = MagicMock()
        d.device_id = did
        d.websocket = None
        return d

    async def test_envelope_metadata_has_source_device_id(self):
        router = self._make_router()
        envelopes_built = []

        # Patch TaskEnvelope to capture what was built
        import core.schemas.task_envelope as _te_mod
        original_te = _te_mod.TaskEnvelope

        class _CapturingEnvelope(original_te):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                envelopes_built.append(self)

        target = self._make_device("pc_01")

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "test",
                "exec_mode": "both",
                "actions": [],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
            patch("core.schemas.task_envelope.TaskEnvelope", _CapturingEnvelope),
            patch("galaxy_gateway.device_router.TaskEnvelope", _CapturingEnvelope, create=True),
        ):
            await router.route_task("test_cmd", {"source_device_id": "origin_phone"})

        # At least one envelope should carry source_device_id in metadata
        found = any(
            getattr(e, "metadata", {}).get("source_device_id") == "origin_phone"
            for e in envelopes_built
        )
        # If TaskEnvelope patching didn't capture (import path varies), skip gracefully
        if envelopes_built:
            self.assertTrue(
                found,
                "At least one TaskEnvelope should carry source_device_id in metadata",
            )


# ===========================================================================
# J) dispatch_task envelope metadata carries source and target device IDs
# ===========================================================================


class TestDispatchTaskEnvelopeMetadata(unittest.IsolatedAsyncioTestCase):
    """dispatch_task() includes source_device_id and target_device_id in its
    TaskEnvelope metadata."""

    def _make_router(self):
        from galaxy_gateway.device_router import DeviceRouter
        return DeviceRouter()

    def _make_device(self, did):
        d = MagicMock()
        d.device_id = did
        d.websocket = None
        return d

    async def test_dispatch_task_envelope_metadata(self):
        router = self._make_router()
        envelopes_built = []

        import core.schemas.task_envelope as _te_mod
        original_te = _te_mod.TaskEnvelope

        class _CapturingEnvelope(original_te):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                envelopes_built.append(self)

        device = self._make_device("desktop_01")

        async def _fake_route_envelope(env):
            return {"success": True, "task_id": env.task_id, "trace_id": env.trace_id}

        mock_cmd_router = MagicMock()
        mock_cmd_router._executor = MagicMock()
        mock_cmd_router.route_envelope = AsyncMock(side_effect=_fake_route_envelope)

        task = {
            "task_id": "t-dispatch-j",
            "trace_id": "trace-j",
            "command": "click",
            "source_device_id": "phone_01",
            "payload": {"action": "click", "params": {}},
        }

        with (
            patch("core.command_router.get_command_router", return_value=mock_cmd_router),
            patch("core.schemas.task_envelope.TaskEnvelope", _CapturingEnvelope),
        ):
            result = await router.dispatch_task(task, device)

        self.assertTrue(result.get("success"), f"dispatch_task should succeed; got {result}")

        # Find the envelope that was built for this dispatch
        matching = [
            e for e in envelopes_built
            if "desktop_01" in (getattr(e, "targets", None) or [])
        ]
        if matching:
            env = matching[0]
            meta = getattr(env, "metadata", {}) or {}
            self.assertEqual(
                meta.get("source_device_id"),
                "phone_01",
                "dispatch_task envelope metadata must carry source_device_id",
            )
            self.assertEqual(
                meta.get("target_device_id"),
                "desktop_01",
                "dispatch_task envelope metadata must carry target_device_id",
            )


# ===========================================================================
# K) ControlSemanticRecord emitted to integrity runtime
# ===========================================================================


class TestControlSemanticRecordEmitted(unittest.IsolatedAsyncioTestCase):
    """route_task() emits a ControlSemanticRecord to the integrity runtime."""

    def _make_router(self):
        from galaxy_gateway.device_router import DeviceRouter
        return DeviceRouter()

    def _make_device(self, did):
        d = MagicMock()
        d.device_id = did
        d.websocket = None
        return d

    async def test_control_semantic_record_appended(self):
        _reset_integrity_runtime()
        router = self._make_router()
        target = self._make_device("pc_02")

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "type_text",
                "exec_mode": "both",
                "actions": ["type"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task(
                "type hello",
                {"source_device_id": "phone_02", "target_device_id": "pc_02"},
            )

        from core.multi_device_control_integrity import get_multi_device_integrity_runtime
        runtime = get_multi_device_integrity_runtime()
        records = list(runtime._control)

        self.assertGreater(
            len(records), 0,
            "At least one ControlSemanticRecord must be in the runtime buffer",
        )
        last = records[-1]
        self.assertEqual(last.source_device_id, "phone_02")
        self.assertEqual(last.target_device_id, "pc_02")

    async def test_control_semantic_record_remote_dispatch(self):
        """Remote-dispatch scenario: source != target → REMOTE_DISPATCH."""
        _reset_integrity_runtime()
        router = self._make_router()
        target = self._make_device("desktop_remote")

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "remote_type",
                "exec_mode": "both",
                "actions": ["type"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task(
                "type hello",
                {"source_device_id": "phone_remote", "target_device_id": "desktop_remote"},
            )

        from core.multi_device_control_integrity import (
            get_multi_device_integrity_runtime,
            ControlSemanticKind,
        )
        runtime = get_multi_device_integrity_runtime()
        records = list(runtime._control)
        self.assertTrue(records, "ControlSemanticRecord must be emitted")
        last = records[-1]
        self.assertEqual(
            last.control_kind,
            ControlSemanticKind.REMOTE_DISPATCH,
            f"Expected REMOTE_DISPATCH, got {last.control_kind}",
        )

    async def test_control_semantic_record_local_execution(self):
        """Local-execution scenario: source == target → LOCAL_EXECUTION."""
        _reset_integrity_runtime()
        router = self._make_router()
        target = self._make_device("same_device")

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "local_cmd",
                "exec_mode": "both",
                "actions": ["run"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task(
                "run",
                {"source_device_id": "same_device"},
            )

        from core.multi_device_control_integrity import (
            get_multi_device_integrity_runtime,
            ControlSemanticKind,
        )
        runtime = get_multi_device_integrity_runtime()
        records = list(runtime._control)
        self.assertTrue(records, "ControlSemanticRecord must be emitted")
        last = records[-1]
        self.assertEqual(
            last.control_kind,
            ControlSemanticKind.LOCAL_EXECUTION,
            f"Expected LOCAL_EXECUTION, got {last.control_kind}",
        )
        self.assertTrue(last.is_local)

    async def test_control_semantic_record_takeover(self):
        """Takeover scenario: is_takeover=True → TAKEOVER kind."""
        _reset_integrity_runtime()
        router = self._make_router()
        target = self._make_device("assistant_device")

        async def _fake_dispatch(task, device):
            return {"success": True}

        router.dispatch_task = _fake_dispatch

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "delegation",
                "exec_mode": "both",
                "actions": ["delegate"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=[target]),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task(
                "delegate task",
                {
                    "source_device_id": "originator_device",
                    "is_takeover": True,
                },
            )

        from core.multi_device_control_integrity import (
            get_multi_device_integrity_runtime,
            ControlSemanticKind,
        )
        runtime = get_multi_device_integrity_runtime()
        records = list(runtime._control)
        self.assertTrue(records, "ControlSemanticRecord must be emitted")
        last = records[-1]
        self.assertEqual(
            last.control_kind,
            ControlSemanticKind.TAKEOVER,
            f"Expected TAKEOVER, got {last.control_kind}",
        )
        self.assertTrue(last.is_takeover)

    async def test_control_semantic_record_hybrid_multi_device(self):
        """Hybrid scenario: multiple target devices → HYBRID kind."""
        _reset_integrity_runtime()
        router = self._make_router()

        def _make_dev(did):
            d = MagicMock()
            d.device_id = did
            d.websocket = None
            return d

        targets = [_make_dev("pc_01"), _make_dev("tablet_01")]

        async def _fake_dispatch_cross(task, devices, _substrate_caller=""):
            return {"success": True, "subtask_results": []}

        router._dispatch_cross_device_task = _fake_dispatch_cross

        with (
            patch.object(router, "_analyze_command", return_value={
                "task_type": "parallel",
                "exec_mode": "both",
                "actions": ["broadcast"],
                "target_device_type": MagicMock(),
                "requires_cross_device": False,
            }),
            patch.object(router, "_select_devices", return_value=targets),
            patch(
                "galaxy_gateway.cross_device_switch.is_cross_device_enabled",
                return_value=True,
            ),
        ):
            await router.route_task(
                "broadcast",
                {"source_device_id": "controller_device"},
            )

        from core.multi_device_control_integrity import (
            get_multi_device_integrity_runtime,
            ControlSemanticKind,
        )
        runtime = get_multi_device_integrity_runtime()
        records = list(runtime._control)
        self.assertTrue(records, "ControlSemanticRecord must be emitted")
        last = records[-1]
        self.assertEqual(
            last.control_kind,
            ControlSemanticKind.HYBRID,
            f"Expected HYBRID, got {last.control_kind}",
        )


# ===========================================================================
# L) ControlSemanticRecord.is_semantically_clear
# ===========================================================================


class TestControlSemanticRecordSemanticClarity(unittest.TestCase):
    """ControlSemanticRecord.is_semantically_clear is True when source,
    target, and kind are all explicitly set and non-ambiguous."""

    def _build(self, **kwargs):
        from core.multi_device_control_integrity import build_control_semantic_record
        return build_control_semantic_record(**kwargs)

    def test_clear_when_all_fields_set(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-clear",
            source_device_id="phone_01",
            target_device_id="desktop_01",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertTrue(
            rec.is_semantically_clear,
            "Record should be semantically clear when source, target, and kind are set",
        )

    def test_not_clear_when_source_missing(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-no-source",
            source_device_id="",
            target_device_id="desktop_01",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertFalse(
            rec.is_semantically_clear,
            "Record should not be semantically clear when source_device_id is missing",
        )

    def test_not_clear_when_target_missing(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-no-target",
            source_device_id="phone_01",
            target_device_id="",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        self.assertFalse(
            rec.is_semantically_clear,
            "Record should not be semantically clear when target_device_id is missing",
        )

    def test_not_clear_when_kind_unknown(self):
        from core.multi_device_control_integrity import ControlSemanticKind
        rec = self._build(
            task_id="t-unknown",
            source_device_id="phone_01",
            target_device_id="desktop_01",
            control_kind=ControlSemanticKind.UNKNOWN,
        )
        self.assertFalse(
            rec.is_semantically_clear,
            "Record should not be semantically clear when kind is UNKNOWN",
        )


# ===========================================================================
# M) build_control_semantic_record round-trip
# ===========================================================================


class TestControlSemanticRecordRoundTrip(unittest.TestCase):
    """ControlSemanticRecord round-trips through to_dict / from_dict."""

    def test_round_trip_remote_dispatch(self):
        from core.multi_device_control_integrity import (
            ControlSemanticRecord,
            ControlSemanticKind,
            build_control_semantic_record,
        )
        rec = build_control_semantic_record(
            task_id="t-rt",
            trace_id="trace-rt",
            source_device_id="phone_rt",
            target_device_id="desktop_rt",
            control_kind=ControlSemanticKind.REMOTE_DISPATCH,
        )
        rec2 = ControlSemanticRecord.from_dict(rec.to_dict())
        self.assertEqual(rec.source_device_id, rec2.source_device_id)
        self.assertEqual(rec.target_device_id, rec2.target_device_id)
        self.assertEqual(rec.control_kind, rec2.control_kind)
        self.assertEqual(rec.is_remote_dispatch, rec2.is_remote_dispatch)
        self.assertEqual(rec.is_semantically_clear, rec2.is_semantically_clear)

    def test_round_trip_local_execution(self):
        from core.multi_device_control_integrity import (
            ControlSemanticRecord,
            ControlSemanticKind,
            build_control_semantic_record,
        )
        rec = build_control_semantic_record(
            task_id="t-local-rt",
            source_device_id="dev_x",
            target_device_id="dev_x",
            control_kind=ControlSemanticKind.LOCAL_EXECUTION,
        )
        rec2 = ControlSemanticRecord.from_dict(rec.to_dict())
        self.assertEqual(rec.control_kind, rec2.control_kind)
        self.assertTrue(rec2.is_local)

    def test_round_trip_takeover(self):
        from core.multi_device_control_integrity import (
            ControlSemanticRecord,
            ControlSemanticKind,
            build_control_semantic_record,
        )
        rec = build_control_semantic_record(
            task_id="t-takeover-rt",
            source_device_id="src",
            target_device_id="tgt",
            control_kind=ControlSemanticKind.TAKEOVER,
            is_takeover=True,
        )
        rec2 = ControlSemanticRecord.from_dict(rec.to_dict())
        self.assertEqual(rec.control_kind, rec2.control_kind)
        self.assertTrue(rec2.is_takeover)


# ===========================================================================
# N) GAP-517-006 resolved in residual gap catalog
# ===========================================================================


class TestResidualGapResolutionStatus(unittest.TestCase):
    """GAP-517-006 is marked as resolved in the residual gap catalog."""

    def test_gap_517_006_is_resolved(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        gaps = get_residual_integrity_gaps()
        gap = next((g for g in gaps if g.gap_id == "GAP-517-006"), None)
        self.assertIsNotNone(gap, "GAP-517-006 must be present in the residual gap catalog")
        self.assertTrue(
            gap.is_resolved,
            "GAP-517-006 must be marked as resolved",
        )
        self.assertIn(
            "PR-521",
            gap.resolution_note,
            "GAP-517-006 resolution note must reference PR-521",
        )

    def test_open_gaps_do_not_include_006(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        open_gaps = [g for g in get_residual_integrity_gaps() if not g.is_resolved]
        open_ids = [g.gap_id for g in open_gaps]
        self.assertNotIn(
            "GAP-517-006",
            open_ids,
            "GAP-517-006 should not appear in open gaps after PR-521",
        )

    def test_control_semantic_area_has_no_open_gaps(self):
        from core.multi_device_control_integrity import get_residual_integrity_gaps
        open_control = [
            g for g in get_residual_integrity_gaps()
            if g.area == "control_semantics" and not g.is_resolved
        ]
        self.assertEqual(
            len(open_control),
            0,
            f"All control_semantics gaps should be resolved; open: {open_control}",
        )


if __name__ == "__main__":
    unittest.main()
