#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr532_parallel_entry_canonicalization.py
===================================================
PR-532 — Parallel Device Entry Canonicalization (GAP-517-002).
"""

from __future__ import annotations

import asyncio
import inspect
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestA_ParallelRestIngress(unittest.TestCase):
    """A) /api/v1/devices/parallel canonical ingress."""

    def test_A1_parallel_ingress_sentinel_present(self):
        import core.routes.devices as devices_mod

        src = inspect.getsource(devices_mod)
        self.assertIn("PARALLEL_DEVICE_REST_INGRESS_CANONICAL", src)
        self.assertIn("GAP-517-002", src)

    def test_A2_handler_uses_command_router_not_raw_device_send(self):
        import core.routes.devices as devices_mod

        src = inspect.getsource(devices_mod)
        section = src[src.find("parallel_device_commands"):src.find("trigger_device_discovery")]
        self.assertIn("TaskEnvelope", section)
        self.assertIn("route_envelope", section)
        self.assertNotIn("connection_manager.send_to_device", section)

    def test_A3_handler_builds_top_level_parallel_envelope(self):
        import core.routes.devices as devices_mod

        app = FastAPI()
        app.include_router(devices_mod.create_router())
        client = TestClient(app)

        fake_router = MagicMock()
        fake_router.route_envelope = AsyncMock(return_value={
            "success": True,
            "task_id": "task-root",
            "trace_id": "trace-root",
            "request_id": "req-root",
            "command_id": "cmd-root",
            "result": {"success": True, "total": 2, "results": []},
        })

        with patch("core.routes.devices.get_command_router", return_value=fake_router):
            response = client.post(
                "/api/v1/devices/parallel",
                json={
                    "commands": [
                        {"device_id": "device-a", "command": "ping", "params": {"x": 1}},
                        {"device_id": "device-b", "command": "pong", "params": {"y": 2}},
                    ],
                    "timeout": 45,
                    "context": {"task_id": "task-root", "trace_id": "trace-root"},
                },
            )

        self.assertEqual(response.status_code, 200)
        fake_router.route_envelope.assert_awaited_once()
        envelope = fake_router.route_envelope.await_args.args[0]
        self.assertEqual(envelope.task_id, "task-root")
        self.assertEqual(envelope.trace_id, "trace-root")
        self.assertEqual(envelope.source, "api.parallel_devices")
        self.assertEqual(envelope.targets, ["device-a", "device-b"])
        self.assertEqual(envelope.metadata.get("parallel_fanout"), "true")
        self.assertEqual(envelope.args["commands"][0]["command"], "ping")
        self.assertEqual(envelope.args["commands"][1]["device_id"], "device-b")


class TestB_CommandRouterParallelPath(unittest.TestCase):
    """B) CommandRouter canonical parallel fan-out path."""

    def test_B1_parallel_fanout_sentinel_importable(self):
        from core.command_router import COMMAND_ROUTER_PARALLEL_FANOUT_CANONICAL_PATH

        self.assertIsInstance(COMMAND_ROUTER_PARALLEL_FANOUT_CANONICAL_PATH, str)
        self.assertIn("PARALLEL_FANOUT_CANONICAL_PATH", COMMAND_ROUTER_PARALLEL_FANOUT_CANONICAL_PATH)
        self.assertIn("GAP-517-002", COMMAND_ROUTER_PARALLEL_FANOUT_CANONICAL_PATH)

    def test_B2_route_envelope_has_parallel_branch(self):
        from core.command_router import CommandRouter

        src = inspect.getsource(CommandRouter.route_envelope)
        self.assertIn("parallel_fanout", src)
        self.assertIn("_route_parallel_fanout_envelope", src)

    def test_B3_parallel_fanout_creates_canonical_sub_envelopes(self):
        from core.command_router import CommandRouter
        from core.schemas.task_envelope import TaskEnvelope

        router = CommandRouter()

        async def _exercise():
            envelope = TaskEnvelope(
                task_id="task-root",
                trace_id="trace-root",
                source="api.parallel_devices",
                targets=["device-a", "device-b"],
                tool_name="parallel_device_commands",
                args={
                    "commands": [
                        {"device_id": "device-a", "command": "ping", "params": {"x": 1}},
                        {"device_id": "device-b", "command": "pong", "params": {"y": 2}},
                    ]
                },
                metadata={"parallel_fanout": "true"},
            )
            fake_results = [
                {
                    "success": True,
                    "task_id": "task-root__p00",
                    "trace_id": "trace-root",
                    "request_id": "req-root:p0",
                    "command_id": "cmd-root:p0",
                    "result": {"ok": True},
                    "via": "command_router",
                },
                {
                    "success": True,
                    "task_id": "task-root__p01",
                    "trace_id": "trace-root",
                    "request_id": "req-root:p1",
                    "command_id": "cmd-root:p1",
                    "result": {"ok": True},
                    "via": "command_router",
                },
            ]
            with patch.object(router, "route_envelope", new=AsyncMock(side_effect=fake_results)) as mocked:
                result = await router._route_parallel_fanout_envelope(
                    envelope,
                    command_id="cmd-root",
                    request_id="req-root",
                )
            return mocked, result

        mocked, result = _run(_exercise())
        self.assertEqual(mocked.await_count, 2)
        first = mocked.await_args_list[0].args[0]
        second = mocked.await_args_list[1].args[0]
        self.assertEqual(first.targets, ["device-a"])
        self.assertEqual(second.targets, ["device-b"])
        self.assertEqual(first.tool_name, "ping")
        self.assertEqual(second.tool_name, "pong")
        self.assertEqual(first.metadata["parallel_parent_task_id"], "task-root")
        self.assertEqual(second.metadata["parallel_parent_task_id"], "task-root")
        self.assertTrue(result["success"])
        self.assertEqual(result["result"]["total"], 2)
        self.assertEqual(result["result"]["successful"], 2)
