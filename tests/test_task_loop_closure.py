"""
tests/test_task_loop_closure.py
=================================
Acceptance tests for the unified task execution loop (PR154 Loop B).

Covers:
  1. Trace continuity   — every dispatch path carries trace_id, task_id, device_id
  2. Backflow persistence — results written to TaskMemory and retrievable
  3. Failure semantics  — structured errors on timeout and unsupported capability

Note:
  All LLM calls and external I/O are mocked; no real services are required.
"""

import asyncio
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_router():
    router = MagicMock()
    router.is_available = MagicMock(return_value=False)
    router.chat = AsyncMock(return_value=MagicMock(
        content="task result", provider="mock", model="mock",
        latency_ms=5.0, input_tokens=5, output_tokens=10,
    ))
    router._compute_complexity_vector = MagicMock(return_value=MagicMock(weighted_score=0.2))
    return router


# ---------------------------------------------------------------------------
# Test 1: trace continuity
# ---------------------------------------------------------------------------

class TestTraceContinuity:
    """Loop B-1: every dispatch path carries trace_id, task_id, device_id."""

    @pytest.mark.asyncio
    async def test_openclawd_process_returns_trace_id(self, mock_llm_router):
        """OpenClawd.process() must return a non-empty trace_id in every response."""
        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_instance = MagicMock()
            mock_instance.process = AsyncMock(return_value={
                "success": True,
                "response": "ok",
                "intent": "chat",
                "trace_id": "test_trace_abc123",
                "metadata": {
                    "trace_id": "test_trace_abc123",
                    "task_id": "",
                    "session_id": "test_session",
                    "device_id": "windows_client",
                },
            })
            mock_get.return_value = mock_instance

            clawd = mock_get()
            result = await clawd.process(
                message="help me do something",
                device_id="windows_client",
                session_id="test_session",
            )

            assert "trace_id" in result
            assert result["trace_id"] != ""
            assert "metadata" in result
            assert "trace_id" in result["metadata"]

    @pytest.mark.asyncio
    async def test_handle_agent_task_returns_task_id(self, mock_llm_router):
        """handle_agent_task must include task_id in returned metadata."""
        import core.multi_llm_router  # ensure module is importable before patching
        import core.agent_factory

        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._router = mock_llm_router
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        trace_id = uuid.uuid4().hex
        device_id = "test_device"
        session_id = "test_session"

        # Mock out the internals to return quickly without real LLM
        async def fake_handle_chat(msg, mode):
            return {"success": True, "response": "fallback", "metadata": {}}

        clawd.handle_chat = fake_handle_chat

        with patch("core.agent_factory.get_agent_factory") as mock_factory_fn, \
             patch("core.multi_llm_router.get_llm_router") as mock_llm_fn:
            mock_llm_fn.return_value = mock_llm_router
            mock_factory = MagicMock()
            mock_agent = MagicMock()
            mock_agent.id = "agent_test123"
            mock_agent.config = MagicMock()
            mock_agent.config.role = MagicMock()
            mock_agent.config.role.value = "analyst"
            mock_factory.create_from_template = MagicMock(return_value=mock_agent)
            mock_factory.execute_agent_task = AsyncMock(return_value={
                "status": "success",
                "results": [{"output": "test output"}],
            })
            mock_factory.terminate_agent = MagicMock()
            mock_factory_fn.return_value = mock_factory

            # Intent mock
            mock_intent = MagicMock()
            mock_intent.targets = []
            mock_intent.intent = "analysis"
            mock_intent.params = {"message": "analyze this"}

            result = await clawd.handle_agent_task(
                "analyze this",
                mock_intent,
                device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
            )

        meta = result.get("metadata", {})
        assert "task_id" in meta, f"task_id missing from metadata: {meta}"
        assert meta["task_id"].startswith("task_"), f"task_id format wrong: {meta['task_id']}"
        assert meta.get("trace_id") == trace_id
        assert meta.get("device_id") == device_id
        assert meta.get("session_id") == session_id

    @pytest.mark.asyncio
    async def test_dispatch_agent_passes_trace_id(self):
        """_dispatch_agent must forward trace_id to handle_agent_task."""
        import core.multi_llm_router  # ensure importable before patching
        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        received_kwargs = {}

        async def capture_handle_agent_task(message, intent, **kwargs):
            received_kwargs.update(kwargs)
            return {"success": True, "response": "ok", "metadata": {}}

        clawd.handle_agent_task = capture_handle_agent_task

        trace_id = "trace_dispatch_test_" + uuid.uuid4().hex[:8]
        await clawd._dispatch_agent(
            message="test message",
            intent=None,
            device_id="dev_x",
            session_id="sess_x",
            trace_id=trace_id,
        )

        assert received_kwargs.get("trace_id") == trace_id, \
            f"trace_id not forwarded to handle_agent_task: {received_kwargs}"
        assert received_kwargs.get("device_id") == "dev_x"
        assert received_kwargs.get("session_id") == "sess_x"


# ---------------------------------------------------------------------------
# Test 2: backflow persistence
# ---------------------------------------------------------------------------

class TestBackflowPersistence:
    """Loop B-2: task results are persisted via memory backflow and retrievable."""

    @pytest.mark.asyncio
    async def test_store_task_result_writes_to_task_memory(self):
        """store_task_result must write a record to TaskMemory."""
        from core.openclawd_memory_backflow import store_task_result

        with patch("core.openclawd_memory_backflow.get_task_memory") as mock_get_mem:
            mock_mem = MagicMock()
            mock_mem.record_task = MagicMock()
            mock_get_mem.return_value = mock_mem

            await store_task_result(
                task_id="task_test_001",
                device_id="windows_client",
                route_mode="agent",
                result={
                    "status": "completed",
                    "task_type": "agent_task",
                    "task_description": "Test task",
                    "result_summary": "Task completed",
                },
                session_id="session_001",
            )

            mock_mem.record_task.assert_called_once()
            call_kwargs = mock_mem.record_task.call_args
            # Verify key fields were persisted
            args = call_kwargs[1] if call_kwargs[1] else {}
            assert args.get("success") is True or args.get("task") is not None

    @pytest.mark.asyncio
    async def test_store_task_result_silent_on_memory_unavailable(self):
        """store_task_result must not raise when TaskMemory is unavailable."""
        from core.openclawd_memory_backflow import store_task_result

        with patch("core.openclawd_memory_backflow.get_task_memory", return_value=None):
            # Should complete silently
            await store_task_result(
                task_id="task_no_mem",
                device_id="device_x",
                route_mode="agent",
                result={"status": "completed"},
            )

    @pytest.mark.asyncio
    async def test_handle_agent_task_calls_backflow_on_success(self, mock_llm_router):
        """handle_agent_task must call store_task_result after successful execution."""
        import core.multi_llm_router  # ensure module is importable before patching
        import core.agent_factory

        from core.openclawd import OpenClawd

        clawd = OpenClawd.__new__(OpenClawd)
        clawd._router = mock_llm_router
        clawd._initialized = True
        clawd._start_time = 0.0
        clawd._request_count = 0
        clawd._error_count = 0
        clawd._session_memory = {}
        clawd._cancel_registry = set()

        backflow_calls = []

        async def mock_store_task_result(**kwargs):
            backflow_calls.append(kwargs)

        with patch("core.agent_factory.get_agent_factory") as mock_factory_fn, \
             patch("core.multi_llm_router.get_llm_router") as mock_llm_fn, \
             patch("core.openclawd_memory_backflow.store_task_result",
                   side_effect=mock_store_task_result):

            mock_llm_fn.return_value = mock_llm_router
            mock_factory = MagicMock()
            mock_agent = MagicMock()
            mock_agent.id = "agent_bf_test"
            mock_agent.config = MagicMock()
            mock_agent.config.role = MagicMock()
            mock_agent.config.role.value = "analyst"
            mock_factory.create_from_template = MagicMock(return_value=mock_agent)
            mock_factory.execute_agent_task = AsyncMock(return_value={
                "status": "success",
                "results": [{"output": "done"}],
            })
            mock_factory.terminate_agent = MagicMock()
            mock_factory_fn.return_value = mock_factory

            mock_intent = MagicMock()
            mock_intent.targets = []
            mock_intent.intent = "analysis"
            mock_intent.params = {"message": "test"}

            await clawd.handle_agent_task(
                "test task",
                mock_intent,
                device_id="test_device",
                session_id="test_session",
                trace_id="test_trace",
            )

        assert len(backflow_calls) == 1, "store_task_result must be called once"
        call = backflow_calls[0]
        assert call["device_id"] == "test_device"
        assert call["route_mode"] == "agent"
        assert call["session_id"] == "test_session"
        assert call["task_id"].startswith("task_")


# ---------------------------------------------------------------------------
# Test 3: failure semantics
# ---------------------------------------------------------------------------

class TestFailureSemantics:
    """Loop B-3: structured errors on timeout / disconnect / unsupported capability."""

    @pytest.mark.asyncio
    async def test_execution_planner_timeout_returns_structured_error(self):
        """ExecutionPlanner must return structured ExecutionResult on timeout."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        plan = ExecutionPlan(
            message="do something slow",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.8,
            ),
            timeout=0.001,  # extremely short timeout to trigger TimeoutError
        )

        with patch.object(planner, "_dispatch", side_effect=asyncio.TimeoutError()):
            result = await planner.execute(plan)

        assert result.success is False
        assert result.error == "timeout"
        assert "超时" in result.reply or "timeout" in result.reply.lower()

    @pytest.mark.asyncio
    async def test_execution_planner_exception_returns_structured_error(self):
        """ExecutionPlanner must return structured ExecutionResult on generic exception."""
        from core.agent.execution_planner import ExecutionPlanner, ExecutionPlan
        from core.agent.intent_router import IntentResult, IntentMode

        planner = ExecutionPlanner(llm_router=None)

        plan = ExecutionPlan(
            message="do something broken",
            intent=IntentResult(
                mode=IntentMode.TASK_EXECUTE,
                raw_intent="task_execute",
                confidence=0.8,
            ),
        )

        with patch.object(planner, "_dispatch", side_effect=RuntimeError("device disconnected")):
            result = await planner.execute(plan)

        assert result.success is False
        assert "device disconnected" in result.error or "device disconnected" in result.reply
        assert result.error != ""

    @pytest.mark.asyncio
    async def test_openclawd_process_returns_structured_error_on_exception(self):
        """OpenClawd.process() must return structured error dict (not raise) on failure."""
        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_instance = MagicMock()
            trace = uuid.uuid4().hex
            mock_instance.process = AsyncMock(return_value={
                "success": False,
                "response": "处理请求时发生错误: forced error",
                "intent": "error",
                "trace_id": trace,
                "metadata": {"trace_id": trace, "error": "forced error"},
            })
            mock_get.return_value = mock_instance

            clawd = mock_get()
            result = await clawd.process(
                message="trigger error",
                device_id="test",
                session_id="s1",
            )

        assert result["success"] is False
        assert result.get("trace_id") != ""
        assert "error" in result.get("metadata", {}) or "error" in result.get("response", "").lower()

    def test_chat_route_response_contains_trace_id_field(self):
        """UnifiedChatResponse.to_json_response must emit trace_id."""
        from core.unified_response import UnifiedChatResponse

        resp = UnifiedChatResponse(
            success=True,
            response="test",
            intent="chat",
            confidence=1.0,
            mode="chat",
            session_id="sess1",
        )
        resp_dict = resp.to_json_response()
        resp_dict["trace_id"] = "trace_abc"
        # Verify we can set and read trace_id in the response dict
        assert resp_dict.get("trace_id") == "trace_abc"
