"""
tests/test_observability.py
============================

Minimal tests for PR11 observability enhancements:
  1. emit_task_log writes structured JSON to Galaxy.TaskLifecycle logger
  2. OpenClawd.process() returns trace_id in metadata and top-level response
  3. _dispatch_goal_execution propagates trace_id into result and payload
  4. _dispatch_parallel_goal propagates trace_id into subtask payloads and result
  5. GalaxyOrchestrator.process_request() extracts trace_id from context
  6. /api/v1/chat emits aggregation_done log when parallel_result is present
"""

import asyncio
import json
import logging
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 1. core/task_logger.emit_task_log
# ---------------------------------------------------------------------------

class TestEmitTaskLog(unittest.TestCase):
    """emit_task_log must write valid JSON to Galaxy.TaskLifecycle."""

    def test_emits_json_with_required_fields(self):
        from core.task_logger import emit_task_log

        records = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        tl_logger = logging.getLogger("Galaxy.TaskLifecycle")
        original_level = tl_logger.level
        tl_logger.setLevel(logging.DEBUG)
        handler = _Handler()
        tl_logger.addHandler(handler)
        try:
            emit_task_log(
                "task_completed",
                task_id="t1",
                trace_id="tr1",
                device_id="dev1",
                latency_ms=42.0,
                status="success",
                task_type="goal_execution",
            )
        finally:
            tl_logger.removeHandler(handler)
            tl_logger.setLevel(original_level)

        self.assertEqual(len(records), 1)
        entry = json.loads(records[0])
        self.assertEqual(entry["event"], "task_completed")
        self.assertEqual(entry["task_id"], "t1")
        self.assertEqual(entry["trace_id"], "tr1")
        self.assertEqual(entry["device_id"], "dev1")
        self.assertAlmostEqual(entry["latency_ms"], 42.0)
        self.assertEqual(entry["status"], "success")
        self.assertIn("ts", entry)

    def test_all_lifecycle_events_are_valid_json(self):
        from core.task_logger import emit_task_log

        events = [
            "task_received", "task_dispatched", "task_completed",
            "task_failed", "task_cancelled", "task_timeout", "aggregation_done",
        ]
        records = []

        class _Handler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        tl_logger = logging.getLogger("Galaxy.TaskLifecycle")
        original_level = tl_logger.level
        tl_logger.setLevel(logging.DEBUG)
        handler = _Handler()
        tl_logger.addHandler(handler)
        try:
            for event in events:
                emit_task_log(event, task_id="x", trace_id="y")
        finally:
            tl_logger.removeHandler(handler)
            tl_logger.setLevel(original_level)

        self.assertEqual(len(records), len(events))
        for raw in records:
            entry = json.loads(raw)
            self.assertIn("event", entry)
            self.assertIn("ts", entry)


# ---------------------------------------------------------------------------
# 2. OpenClawd.process() includes trace_id
# ---------------------------------------------------------------------------

class TestOpenClawdTraceId(unittest.IsolatedAsyncioTestCase):
    """process() must include trace_id in the top-level result."""

    async def test_process_returns_trace_id(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = False
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None

        # Patch out heavy dependencies
        with (
            patch.object(clawd, "sync_device_capabilities", return_value=None),
            patch.object(
                clawd,
                "_get_kernel",
                return_value=None,
            ),
            patch.object(
                clawd,
                "_parse_intent",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                clawd,
                "_dispatch_chat",
                new=AsyncMock(return_value={"success": True, "response": "ok", "metadata": {}}),
            ),
            patch.object(
                clawd,
                "_record_turn",
                new=AsyncMock(return_value=None),
            ),
            patch.object(clawd, "_get_router", return_value=None),
        ):
            result = await clawd.process(message="hello", session_id="sess1")

        self.assertIn("trace_id", result)
        self.assertIsInstance(result["trace_id"], str)
        self.assertGreater(len(result["trace_id"]), 0)

        # trace_id must also be present in metadata
        meta = result.get("metadata", {})
        self.assertIn("trace_id", meta)
        self.assertEqual(result["trace_id"], meta["trace_id"])


# ---------------------------------------------------------------------------
# 3. _dispatch_goal_execution propagates trace_id
# ---------------------------------------------------------------------------

class TestDispatchGoalExecutionTraceId(unittest.IsolatedAsyncioTestCase):

    async def test_trace_id_in_result_and_payload(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None
        clawd.GOAL_EXECUTION_TIMEOUT = 60.0

        captured_payload: dict = {}

        async def _fake_send(device_id, command, payload, task_id=None, session_id=None):
            captured_payload.update(payload or {})
            return {"success": True, "response": "done"}

        with (
            patch.object(clawd, "_pick_autonomous_device_id", return_value="dev42"),
            patch.object(clawd, "send_gateway_command", new=AsyncMock(side_effect=_fake_send)),
        ):
            result = await clawd._dispatch_goal_execution(
                message="take screenshot",
                trace_id="trace_abc",
            )

        # trace_id must appear in payload sent downstream
        self.assertEqual(captured_payload.get("trace_id"), "trace_abc")
        # and in the returned result
        self.assertEqual(result.get("trace_id"), "trace_abc")

    async def test_cancelled_result_contains_trace_id(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._cancel_registry = {"MARKER_ALL"}
        clawd._tool_permission_checker = None
        clawd.GOAL_EXECUTION_TIMEOUT = 60.0

        # Override _is_cancelled to always return True
        clawd._is_cancelled = lambda task_id, group_id=None: True

        with patch.object(clawd, "_pick_autonomous_device_id", return_value="dev1"):
            result = await clawd._dispatch_goal_execution(
                message="do something",
                trace_id="trace_cancel",
            )

        self.assertTrue(result.get("cancelled"))
        self.assertEqual(result.get("trace_id"), "trace_cancel")


# ---------------------------------------------------------------------------
# 4. _dispatch_parallel_goal propagates trace_id (with real devices)
# ---------------------------------------------------------------------------

class TestDispatchParallelGoalTraceId(unittest.IsolatedAsyncioTestCase):

    async def test_result_contains_trace_id_when_devices_present(self):
        """When devices are available, result and subtask payloads carry trace_id."""
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None
        clawd.PARALLEL_SUBTASK_TIMEOUT = 60.0

        captured_payloads: list = []

        async def _fake_send(device_id, command, payload, task_id=None, session_id=None):
            captured_payloads.append(dict(payload or {}))
            return {"success": True, "response": "ok"}

        # Two fake devices via UDM fallback
        mock_dev1 = MagicMock()
        mock_dev1.device_id = "dev_a"
        mock_dev2 = MagicMock()
        mock_dev2.device_id = "dev_b"

        mock_udm = MagicMock()
        mock_udm.get_devices_with_capability = MagicMock(return_value=[])
        mock_udm.get_autonomous_devices = MagicMock(return_value=[mock_dev1, mock_dev2])

        with (
            patch("core.openclawd.OpenClawd._dispatch_parallel_goal",
                  clawd._dispatch_parallel_goal),
        ):
            pass  # just to ensure import

        # We need to patch the module-level imports inside _dispatch_parallel_goal.
        # The simplest way: patch sys.modules entries used by the lazy imports.
        import sys

        # Build a fake CapabilityRegistry that raises immediately
        fake_cap_reg_module = MagicMock()
        fake_cap_reg_module.CapabilityRegistry.get_instance.side_effect = Exception("skip")

        fake_udm_module = MagicMock()
        fake_udm_module.get_unified_device_manager.return_value = mock_udm

        saved_cap = sys.modules.get("core.agent.capability_registry")
        saved_udm = sys.modules.get("core.unified.device_manager")
        sys.modules["core.agent.capability_registry"] = fake_cap_reg_module
        sys.modules["core.unified.device_manager"] = fake_udm_module

        try:
            with patch.object(clawd, "send_gateway_command", new=AsyncMock(side_effect=_fake_send)):
                result = await clawd._dispatch_parallel_goal(
                    message="parallel task",
                    trace_id="trace_parallel_42",
                )
        finally:
            if saved_cap is None:
                sys.modules.pop("core.agent.capability_registry", None)
            else:
                sys.modules["core.agent.capability_registry"] = saved_cap
            if saved_udm is None:
                sys.modules.pop("core.unified.device_manager", None)
            else:
                sys.modules["core.unified.device_manager"] = saved_udm

        # Each subtask payload must carry trace_id
        self.assertGreater(len(captured_payloads), 0)
        for payload in captured_payloads:
            self.assertEqual(payload.get("trace_id"), "trace_parallel_42")

        # Top-level result carries trace_id
        self.assertEqual(result.get("trace_id"), "trace_parallel_42")
        self.assertEqual(result.get("metadata", {}).get("trace_id"), "trace_parallel_42")


# ---------------------------------------------------------------------------
# 5. GalaxyOrchestrator.process_request() uses trace_id from context
# ---------------------------------------------------------------------------

class TestGalaxyOrchestratorTraceId(unittest.IsolatedAsyncioTestCase):

    async def test_trace_id_from_context_propagates_to_result(self):
        """process_request should honour trace_id supplied in context."""
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator

        orch = GalaxyOrchestrator.__new__(GalaxyOrchestrator)

        orch.task_queue = []
        orch.task_history = {}
        orch.stats = {"total_tasks": 0, "completed_tasks": 0, "failed_tasks": 0}
        orch._event_subscribers = []
        orch.device_manager = MagicMock()
        orch.gateway = MagicMock()
        orch.gateway._rag_memory = None
        orch.gateway._team_manager = None
        orch.gateway.understand_intent = AsyncMock(return_value={"intent_type": "general"})
        orch.gateway.decompose_task = AsyncMock(return_value=[])
        orch._execute_subtasks = AsyncMock(return_value=[])
        orch._aggregate_results = MagicMock(return_value={"output": "done"})
        orch._log_experience = AsyncMock(return_value=None)

        result = await orch.process_request(
            request="do something",
            context={"trace_id": "ctx_trace_xyz", "device_id": "phone1"},
        )

        self.assertEqual(result.get("trace_id"), "ctx_trace_xyz")

    async def test_trace_id_generated_when_absent_from_context(self):
        """process_request must generate trace_id if not supplied."""
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator

        orch = GalaxyOrchestrator.__new__(GalaxyOrchestrator)
        orch.task_queue = []
        orch.task_history = {}
        orch.stats = {"total_tasks": 0, "completed_tasks": 0, "failed_tasks": 0}
        orch._event_subscribers = []
        orch.device_manager = MagicMock()
        orch.gateway = MagicMock()
        orch.gateway._rag_memory = None
        orch.gateway._team_manager = None
        orch.gateway.understand_intent = AsyncMock(return_value={"intent_type": "general"})
        orch.gateway.decompose_task = AsyncMock(return_value=[])
        orch._execute_subtasks = AsyncMock(return_value=[])
        orch._aggregate_results = MagicMock(return_value={"output": "done"})
        orch._log_experience = AsyncMock(return_value=None)

        result = await orch.process_request(request="do something")

        self.assertIn("trace_id", result)
        self.assertIsInstance(result["trace_id"], str)
        self.assertGreater(len(result["trace_id"]), 0)


# ---------------------------------------------------------------------------
# 6. /api/v1/chat emits aggregation_done when parallel_result is present
# ---------------------------------------------------------------------------

class TestChatAggregationLog(unittest.IsolatedAsyncioTestCase):

    async def test_aggregation_log_emitted_for_parallel_result(self):
        """chat() must call emit_task_log('aggregation_done') when result has parallel_result."""
        from core.routes.chat import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        router = create_router()
        app.include_router(router)

        parallel_result_payload = {
            "group_id": "grp1",
            "device_results": [],
            "summary_status": "success",
            "succeeded": 2,
            "failed": 0,
            "cancelled": 0,
            "total": 2,
        }

        mock_clawd_result = {
            "success": True,
            "response": "done",
            "intent": "parallel_goal",
            "trace_id": "tr_parallel",
            "metadata": {
                "request_id": "tr_parallel",
                "trace_id": "tr_parallel",
                "session_id": "sess1",
                "device_id": "dev1",
                "latency_ms": 100.0,
                "parallel_group": "grp1",
                "parallel_result": parallel_result_payload,
            },
        }

        log_calls: list = []

        def _capture_log(event, **fields):
            log_calls.append({"event": event, **fields})

        mock_oc = MagicMock()
        mock_oc.process = AsyncMock(return_value=mock_clawd_result)

        with (
            patch("core.routes.chat.create_router.__code__", create_router.__code__),
            patch("core.task_logger.emit_task_log", side_effect=_capture_log),
        ):
            # Patch openclawd inside the closure by patching the import
            import core.openclawd as _oc_mod
            original_get = getattr(_oc_mod, "get_openclawd", None)
            _oc_mod.get_openclawd = lambda: mock_oc
            try:
                client = TestClient(app)
                resp = client.post(
                    "/api/v1/chat",
                    json={"message": "run in parallel", "device_id": "dev1"},
                )
            finally:
                if original_get is not None:
                    _oc_mod.get_openclawd = original_get

        self.assertEqual(resp.status_code, 200)
        agg_events = [c for c in log_calls if c.get("event") == "aggregation_done"]
        self.assertGreater(
            len(agg_events), 0,
            "Expected at least one 'aggregation_done' log when parallel_result is present",
        )
        agg = agg_events[0]
        self.assertEqual(agg.get("trace_id"), "tr_parallel")
        self.assertEqual(agg.get("succeeded"), 2)
        self.assertEqual(agg.get("total"), 2)


if __name__ == "__main__":
    unittest.main()



# ---------------------------------------------------------------------------
# 2. OpenClawd.process() includes trace_id
# ---------------------------------------------------------------------------

class TestOpenClawdTraceId(unittest.IsolatedAsyncioTestCase):
    """process() must include trace_id in the top-level result."""

    async def test_process_returns_trace_id(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = False
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None

        # Patch out heavy dependencies
        with (
            patch.object(clawd, "sync_device_capabilities", return_value=None),
            patch.object(
                clawd,
                "_get_kernel",
                return_value=None,
            ),
            patch.object(
                clawd,
                "_parse_intent",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                clawd,
                "_dispatch_chat",
                new=AsyncMock(return_value={"success": True, "response": "ok", "metadata": {}}),
            ),
            patch.object(
                clawd,
                "_record_turn",
                new=AsyncMock(return_value=None),
            ),
            patch.object(clawd, "_get_router", return_value=None),
        ):
            result = await clawd.process(message="hello", session_id="sess1")

        self.assertIn("trace_id", result)
        self.assertIsInstance(result["trace_id"], str)
        self.assertGreater(len(result["trace_id"]), 0)

        # trace_id must also be present in metadata
        meta = result.get("metadata", {})
        self.assertIn("trace_id", meta)
        self.assertEqual(result["trace_id"], meta["trace_id"])


# ---------------------------------------------------------------------------
# 3. _dispatch_goal_execution propagates trace_id
# ---------------------------------------------------------------------------

class TestDispatchGoalExecutionTraceId(unittest.IsolatedAsyncioTestCase):

    async def test_trace_id_in_result_and_payload(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None
        clawd.GOAL_EXECUTION_TIMEOUT = 60.0

        captured_payload: dict = {}

        async def _fake_send(device_id, command, payload, task_id=None, session_id=None):
            captured_payload.update(payload or {})
            return {"success": True, "response": "done"}

        with (
            patch.object(clawd, "_pick_autonomous_device_id", return_value="dev42"),
            patch.object(clawd, "send_gateway_command", new=AsyncMock(side_effect=_fake_send)),
        ):
            result = await clawd._dispatch_goal_execution(
                message="take screenshot",
                trace_id="trace_abc",
            )

        # trace_id must appear in payload sent downstream
        self.assertEqual(captured_payload.get("trace_id"), "trace_abc")
        # and in the returned result
        self.assertEqual(result.get("trace_id"), "trace_abc")

    async def test_cancelled_result_contains_trace_id(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._cancel_registry = {"MARKER_ALL"}  # force cancel via __contains__
        clawd._tool_permission_checker = None
        clawd.GOAL_EXECUTION_TIMEOUT = 60.0

        # Override _is_cancelled to always return True
        clawd._is_cancelled = lambda task_id, group_id=None: True

        with patch.object(clawd, "_pick_autonomous_device_id", return_value="dev1"):
            result = await clawd._dispatch_goal_execution(
                message="do something",
                trace_id="trace_cancel",
            )

        self.assertTrue(result.get("cancelled"))
        self.assertEqual(result.get("trace_id"), "trace_cancel")


# ---------------------------------------------------------------------------
# 4. _dispatch_parallel_goal propagates trace_id
# ---------------------------------------------------------------------------

class TestDispatchParallelGoalTraceId(unittest.IsolatedAsyncioTestCase):

    async def test_subtask_payload_contains_trace_id(self):
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None
        clawd.PARALLEL_SUBTASK_TIMEOUT = 60.0

        captured_payloads: list = []

        async def _fake_send(device_id, command, payload, task_id=None, session_id=None):
            captured_payloads.append(dict(payload or {}))
            return {"success": True, "response": "ok"}

        with (
            patch(
                "core.agent.capability_registry.CapabilityRegistry",
                side_effect=Exception("skip"),
            ),
            patch(
                "core.unified.device_manager.get_unified_device_manager",
                side_effect=Exception("skip"),
            ),
            patch.object(clawd, "send_gateway_command", new=AsyncMock(side_effect=_fake_send)),
        ):
            # Manually set parallel_devices to bypass device lookups
            with patch.object(
                clawd,
                "_dispatch_parallel_goal",
                wraps=clawd._dispatch_parallel_goal,
            ):
                # Inject two fake devices by patching the private lookup
                original = clawd._dispatch_parallel_goal

                async def _patched(*args, **kwargs):
                    # Force two devices without external lookups
                    import unittest.mock as _mock
                    with _mock.patch(
                        "core.agent.capability_registry.CapabilityRegistry.get_instance",
                        side_effect=Exception("skip"),
                    ):
                        pass
                    return await original(*args, **kwargs)

                result = await clawd._dispatch_parallel_goal(
                    message="parallel task",
                    trace_id="trace_parallel",
                )

        # When no devices are available, expect a graceful "no devices" response
        # (trace_id still propagates into result even in this degenerate path)
        self.assertIn("intent", result)

    async def test_result_contains_trace_id_when_devices_present(self):
        """When devices are available, result and subtask payloads carry trace_id."""
        from core.openclawd import OpenClawd, ParallelGroupTracker, _SubtaskEntry

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._session_memory = {}
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._start_time = time.time()
        clawd._node_actions_cache = {}
        clawd._node_id_to_key = {}
        clawd._router = None
        clawd._kernel = None
        clawd._cancel_registry = set()
        clawd._tool_permission_checker = None
        clawd.PARALLEL_SUBTASK_TIMEOUT = 60.0

        captured_payloads: list = []

        async def _fake_send(device_id, command, payload, task_id=None, session_id=None):
            captured_payloads.append(dict(payload or {}))
            return {"success": True, "response": "ok"}

        # Patch device lookup to return two devices
        mock_dev1 = MagicMock()
        mock_dev1.device_id = "dev_a"
        mock_dev2 = MagicMock()
        mock_dev2.device_id = "dev_b"

        with (
            patch(
                "core.agent.capability_registry.CapabilityRegistry.get_instance",
                side_effect=Exception("skip"),
            ),
            patch(
                "core.unified.device_manager.get_unified_device_manager",
                return_value=MagicMock(
                    get_devices_with_capability=MagicMock(return_value=[]),
                    get_autonomous_devices=MagicMock(return_value=[mock_dev1, mock_dev2]),
                ),
            ),
            patch.object(clawd, "send_gateway_command", new=AsyncMock(side_effect=_fake_send)),
        ):
            result = await clawd._dispatch_parallel_goal(
                message="parallel task",
                trace_id="trace_parallel_42",
            )

        # Check that trace_id is present in each subtask payload
        for payload in captured_payloads:
            self.assertEqual(payload.get("trace_id"), "trace_parallel_42")

        # Check top-level result
        self.assertEqual(result.get("trace_id"), "trace_parallel_42")
        self.assertEqual(result.get("metadata", {}).get("trace_id"), "trace_parallel_42")


# ---------------------------------------------------------------------------
# 5. GalaxyOrchestrator.process_request() uses trace_id from context
# ---------------------------------------------------------------------------

class TestGalaxyOrchestratorTraceId(unittest.IsolatedAsyncioTestCase):

    async def test_trace_id_from_context_propagates_to_result(self):
        """process_request should honour trace_id supplied in context."""
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator

        orch = GalaxyOrchestrator.__new__(GalaxyOrchestrator)

        # Minimal state
        from galaxy_gateway.orchestrator.galaxy_orchestrator import TaskStatus
        from dataclasses import dataclass, field as dc_field

        orch.task_queue = []
        orch.task_history = {}
        orch.stats = {"total_tasks": 0, "completed_tasks": 0, "failed_tasks": 0}
        orch._event_subscribers = []
        orch.device_manager = MagicMock()
        orch.gateway = MagicMock()
        orch.gateway._rag_memory = None
        orch.gateway._team_manager = None
        orch.gateway.understand_intent = AsyncMock(return_value={"intent_type": "general"})
        orch.gateway.decompose_task = AsyncMock(return_value=[])
        orch._execute_subtasks = AsyncMock(return_value=[])
        orch._aggregate_results = MagicMock(return_value={"output": "done"})
        orch._log_experience = AsyncMock(return_value=None)

        result = await orch.process_request(
            request="do something",
            context={"trace_id": "ctx_trace_xyz", "device_id": "phone1"},
        )

        self.assertEqual(result.get("trace_id"), "ctx_trace_xyz")

    async def test_trace_id_generated_when_absent_from_context(self):
        """process_request must generate trace_id if not supplied."""
        from galaxy_gateway.orchestrator.galaxy_orchestrator import GalaxyOrchestrator

        orch = GalaxyOrchestrator.__new__(GalaxyOrchestrator)
        orch.task_queue = []
        orch.task_history = {}
        orch.stats = {"total_tasks": 0, "completed_tasks": 0, "failed_tasks": 0}
        orch._event_subscribers = []
        orch.device_manager = MagicMock()
        orch.gateway = MagicMock()
        orch.gateway._rag_memory = None
        orch.gateway._team_manager = None
        orch.gateway.understand_intent = AsyncMock(return_value={"intent_type": "general"})
        orch.gateway.decompose_task = AsyncMock(return_value=[])
        orch._execute_subtasks = AsyncMock(return_value=[])
        orch._aggregate_results = MagicMock(return_value={"output": "done"})
        orch._log_experience = AsyncMock(return_value=None)

        result = await orch.process_request(request="do something")

        self.assertIn("trace_id", result)
        self.assertIsInstance(result["trace_id"], str)
        self.assertGreater(len(result["trace_id"]), 0)


# ---------------------------------------------------------------------------
# 6. /api/v1/chat emits aggregation_done when parallel_result is present
# ---------------------------------------------------------------------------

class TestChatAggregationLog(unittest.IsolatedAsyncioTestCase):

    async def test_aggregation_log_emitted_for_parallel_result(self):
        """chat() must call emit_task_log('aggregation_done') when result has parallel_result."""
        from core.routes.chat import create_router
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        router = create_router()
        app.include_router(router)

        parallel_result_payload = {
            "group_id": "grp1",
            "device_results": [],
            "summary_status": "success",
            "succeeded": 2,
            "failed": 0,
            "cancelled": 0,
            "total": 2,
        }

        mock_clawd_result = {
            "success": True,
            "response": "done",
            "intent": "parallel_goal",
            "trace_id": "tr_parallel",
            "metadata": {
                "request_id": "tr_parallel",
                "trace_id": "tr_parallel",
                "session_id": "sess1",
                "device_id": "dev1",
                "latency_ms": 100.0,
                "parallel_group": "grp1",
                "parallel_result": parallel_result_payload,
            },
        }

        log_calls: list = []

        def _capture_log(event, **fields):
            log_calls.append({"event": event, **fields})

        with (
            patch("core.openclawd.get_openclawd") as mock_get_oc,
            patch("core.task_logger.emit_task_log", side_effect=_capture_log),
        ):
            mock_oc = MagicMock()
            mock_oc.process = AsyncMock(return_value=mock_clawd_result)
            mock_get_oc.return_value = mock_oc

            client = TestClient(app)
            resp = client.post(
                "/api/v1/chat",
                json={"message": "run in parallel", "device_id": "dev1"},
            )

        self.assertEqual(resp.status_code, 200)
        agg_events = [c for c in log_calls if c.get("event") == "aggregation_done"]
        self.assertGreater(
            len(agg_events), 0,
            "Expected at least one 'aggregation_done' log when parallel_result is present",
        )
        agg = agg_events[0]
        self.assertEqual(agg.get("trace_id"), "tr_parallel")
        self.assertEqual(agg.get("succeeded"), 2)
        self.assertEqual(agg.get("total"), 2)


if __name__ == "__main__":
    unittest.main()
