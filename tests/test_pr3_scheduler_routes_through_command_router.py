#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr3_scheduler_routes_through_command_router.py
==========================================================
PR-3 — Execution Spine Integration: Scheduler → CommandRouter tests.

Validates:
 1.  SCHEDULER_ROUTES_COMMAND_ROUTER importable from core.scheduler.
 2.  SCHEDULER_ROUTES_COMMAND_ROUTER contains 'SCHEDULER_ROUTES'.
 3.  SCHEDULER_MESSAGE_INTEROP_APPLIED still importable from core.scheduler.
 4.  GalaxyScheduler class importable from core.scheduler.
 5.  GalaxyScheduler has _exec_send_to_device method.
 6.  GalaxyScheduler has _exec_relay method.
 7.  GalaxyScheduler has _exec_mesh_send method.
 8.  _exec_send_to_device records ingress in execution spine log.
 9.  _exec_send_to_device uses CommandRouter when available in context.
10.  _exec_send_to_device falls back to ws_sender when CommandRouter unavailable.
11.  _exec_send_to_device falls back to queued status when no ws_sender.
12.  _exec_relay records ingress in execution spine log.
13.  _exec_mesh_send records ingress in execution spine log.
14.  _exec_send_to_device result is JSON-decodable.
15.  _exec_send_to_device with CommandRouter returns router result.
16.  _exec_send_to_device ingress record source is 'scheduler'.
17.  _exec_relay ingress record source is 'scheduler'.
18.  _exec_mesh_send ingress record source is 'scheduler'.
19.  CommandRouter.normalize_legacy_ingress called from scheduler context.
20.  Ingress log grows after multiple send_to_device calls.
"""

from __future__ import annotations

import sys
import os
import json
import unittest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    """Run a coroutine in a new event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestSchedulerSentinels(unittest.TestCase):
    """Tests 1–3: Scheduler sentinel constants."""

    def test_01_routes_command_router_importable(self):
        try:
            from core.scheduler import SCHEDULER_ROUTES_COMMAND_ROUTER
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertIsNotNone(SCHEDULER_ROUTES_COMMAND_ROUTER)

    def test_02_routes_command_router_contains_expected(self):
        try:
            from core.scheduler import SCHEDULER_ROUTES_COMMAND_ROUTER
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertIn("SCHEDULER_ROUTES", SCHEDULER_ROUTES_COMMAND_ROUTER)

    def test_03_message_interop_applied_still_importable(self):
        try:
            from core.scheduler import SCHEDULER_MESSAGE_INTEROP_APPLIED
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertIsNotNone(SCHEDULER_MESSAGE_INTEROP_APPLIED)


class TestSchedulerMethods(unittest.TestCase):
    """Tests 4–7: GalaxyScheduler method presence."""

    def test_04_galaxy_scheduler_importable(self):
        try:
            from core.scheduler import GalaxyScheduler
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertIsNotNone(GalaxyScheduler)

    def test_05_has_exec_send_to_device(self):
        try:
            from core.scheduler import GalaxyScheduler
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertTrue(hasattr(GalaxyScheduler, "_exec_send_to_device"))

    def test_06_has_exec_relay(self):
        try:
            from core.scheduler import GalaxyScheduler
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertTrue(hasattr(GalaxyScheduler, "_exec_relay"))

    def test_07_has_exec_mesh_send(self):
        try:
            from core.scheduler import GalaxyScheduler
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        self.assertTrue(hasattr(GalaxyScheduler, "_exec_mesh_send"))


class TestSchedulerSpineIngress(unittest.TestCase):
    """Tests 8–20: Scheduler dispatch methods use the execution spine."""

    def setUp(self):
        from core.execution_spine import reset_ingress_log
        reset_ingress_log()

    def _make_scheduler(self):
        try:
            from core.scheduler import GalaxyScheduler
        except ImportError as e:
            self.skipTest(f"core.scheduler unavailable (missing dep): {e}")
        sched = GalaxyScheduler.__new__(GalaxyScheduler)
        sched.api_base = "http://localhost:9999"
        sched.api_key = ""
        sched.model = "gpt-4"
        return sched

    def test_08_send_to_device_records_ingress(self):
        from core.execution_spine import get_ingress_log
        sched = self._make_scheduler()
        # context has no ws_sender → falls back to queued path
        _run(sched._exec_send_to_device(
            {"device_id": "dev_test", "task_type": "screenshot"},
            {},
        ))
        log = get_ingress_log()
        self.assertTrue(len(log) >= 1)

    def test_09_send_to_device_uses_command_router(self):
        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"success": True, "routed_via_spine": True})
        sched = self._make_scheduler()
        context = {"command_router": mock_router}
        result_str = _run(sched._exec_send_to_device(
            {"device_id": "dev_test", "task_type": "screenshot"},
            context,
        ))
        result = json.loads(result_str)
        self.assertTrue(result.get("routed_via_spine") or result.get("success"))
        mock_router.route_envelope.assert_called_once()

    def test_10_send_to_device_falls_back_to_ws_sender(self):
        sched = self._make_scheduler()
        ws_called = {}

        async def fake_ws(device_id, payload):
            ws_called["device_id"] = device_id
            return {"status": "sent"}

        context = {"ws_sender": fake_ws}
        # Ensure no command_router so we exercise WS path
        with patch("core.command_router.get_command_router", side_effect=ImportError("no router")):
            result_str = _run(sched._exec_send_to_device(
                {"device_id": "dev_ws", "task_type": "open_app"},
                context,
            ))
        result = json.loads(result_str)
        self.assertEqual(ws_called.get("device_id"), "dev_ws")

    def test_11_send_to_device_fallback_queued(self):
        sched = self._make_scheduler()
        # No ws_sender, no executor, no command_router
        with patch("core.command_router.get_command_router", side_effect=ImportError):
            result_str = _run(sched._exec_send_to_device(
                {"device_id": "dev_q", "task_type": "screenshot"},
                {},
            ))
        result = json.loads(result_str)
        # Should be queued status or an error dict
        self.assertIn(result.get("status", result.get("error", "")), ["queued", ""])
        if "error" not in result:
            self.assertEqual(result["status"], "queued")

    def test_12_relay_records_ingress(self):
        from core.execution_spine import get_ingress_log
        sched = self._make_scheduler()
        with patch("core.proxy_relay.get_proxy_relay", side_effect=ImportError):
            _run(sched._exec_relay(
                {"source_device": "a", "target_device": "b", "payload": {}},
                {},
            ))
        log = get_ingress_log()
        self.assertTrue(len(log) >= 1)

    def test_13_mesh_send_records_ingress(self):
        from core.execution_spine import get_ingress_log
        sched = self._make_scheduler()
        with patch("core.mesh_coordinator.get_mesh_coordinator", side_effect=ImportError):
            _run(sched._exec_mesh_send(
                {"target_device": "dev_mesh", "payload": {}}
            ))
        log = get_ingress_log()
        self.assertTrue(len(log) >= 1)

    def test_14_send_to_device_result_json_decodable(self):
        sched = self._make_scheduler()
        with patch("core.command_router.get_command_router", side_effect=ImportError):
            result_str = _run(sched._exec_send_to_device(
                {"device_id": "dev_j", "task_type": "screenshot"},
                {},
            ))
        result = json.loads(result_str)
        self.assertIsInstance(result, dict)

    def test_15_send_to_device_with_router_returns_router_result(self):
        mock_router = MagicMock()
        mock_router.route_envelope = AsyncMock(return_value={"spine_result": "ok"})
        sched = self._make_scheduler()
        result_str = _run(sched._exec_send_to_device(
            {"device_id": "dev_r", "task_type": "click"},
            {"command_router": mock_router},
        ))
        result = json.loads(result_str)
        self.assertEqual(result.get("spine_result"), "ok")

    def test_16_send_to_device_ingress_source_scheduler(self):
        from core.execution_spine import get_ingress_log, ExecutionIngressSource
        sched = self._make_scheduler()
        with patch("core.command_router.get_command_router", side_effect=ImportError):
            _run(sched._exec_send_to_device({"device_id": "d", "task_type": "t"}, {}))
        log = get_ingress_log()
        sources = [r.source for r in log]
        self.assertIn(ExecutionIngressSource.SCHEDULER, sources)

    def test_17_relay_ingress_source_scheduler(self):
        from core.execution_spine import get_ingress_log, ExecutionIngressSource
        sched = self._make_scheduler()
        with patch("core.proxy_relay.get_proxy_relay", side_effect=ImportError):
            _run(sched._exec_relay({"source_device": "a", "target_device": "b"}, {}))
        log = get_ingress_log()
        sources = [r.source for r in log]
        self.assertIn(ExecutionIngressSource.SCHEDULER, sources)

    def test_18_mesh_send_ingress_source_scheduler(self):
        from core.execution_spine import get_ingress_log, ExecutionIngressSource
        sched = self._make_scheduler()
        with patch("core.mesh_coordinator.get_mesh_coordinator", side_effect=ImportError):
            _run(sched._exec_mesh_send({"target_device": "d", "payload": {}}))
        log = get_ingress_log()
        sources = [r.source for r in log]
        self.assertIn(ExecutionIngressSource.SCHEDULER, sources)

    def test_19_normalize_legacy_ingress_in_scheduler_context(self):
        from core.command_router import CommandRouter
        router = CommandRouter.__new__(CommandRouter)
        envelope = router.normalize_legacy_ingress(
            {"task_type": "screenshot", "device_id": "dev_1"},
            source="scheduler",
        )
        # Should not raise; should return something
        self.assertIsNotNone(envelope)

    def test_20_ingress_log_grows_with_multiple_calls(self):
        from core.execution_spine import get_ingress_log
        sched = self._make_scheduler()
        with patch("core.command_router.get_command_router", side_effect=ImportError):
            for i in range(3):
                _run(sched._exec_send_to_device(
                    {"device_id": f"dev_{i}", "task_type": "screenshot"},
                    {},
                ))
        log = get_ingress_log()
        self.assertGreaterEqual(len(log), 3)


if __name__ == "__main__":
    unittest.main()
