"""
TaskEnvelope schema — unit tests
==================================

Covers:
  1. Canonical schema creation and field defaults
  2. Field validation (priority bounds, timeout > 0)
  3. envelope_from_command_request adapter
  4. envelope_from_relay_request adapter
  5. envelope_from_mcp_call adapter
  6. Backward-compat: CommandRouter.route_command still works without trace_id
  7. CommandRouter.route_envelope delegates to route_command
"""

import asyncio
import pytest
from datetime import datetime, timezone

from pydantic import ValidationError

from core.schemas.task_envelope import (
    TaskEnvelope,
    envelope_from_command_request,
    envelope_from_relay_request,
    envelope_from_mcp_call,
)
from core.schemas import TaskEnvelope as TaskEnvelopeFromPackage  # re-export check


# ============================================================================
# 1. Schema creation & defaults
# ============================================================================

class TestTaskEnvelopeDefaults:
    def test_auto_task_id(self):
        env = TaskEnvelope()
        assert env.task_id.startswith("task_")
        assert len(env.task_id) > 5

    def test_auto_trace_id(self):
        env = TaskEnvelope()
        assert env.trace_id.startswith("trace_")
        assert len(env.trace_id) > 6

    def test_created_at_is_utc(self):
        env = TaskEnvelope()
        assert env.created_at.tzinfo is not None

    def test_default_priority(self):
        env = TaskEnvelope()
        assert env.priority == 5

    def test_default_timeout(self):
        env = TaskEnvelope()
        assert env.timeout == 30.0

    def test_target_shorthand_empty(self):
        env = TaskEnvelope()
        assert env.target == ""

    def test_target_shorthand_returns_first(self):
        env = TaskEnvelope(targets=["device_1", "device_2"])
        assert env.target == "device_1"

    def test_log_context_keys(self):
        env = TaskEnvelope(source="api", tool_name="screenshot")
        ctx = env.log_context()
        assert set(ctx.keys()) == {"task_id", "trace_id", "source", "tool_name"}

    def test_re_export_from_package(self):
        """TaskEnvelope is importable from core.schemas directly."""
        env = TaskEnvelopeFromPackage(tool_name="ping")
        assert env.tool_name == "ping"


# ============================================================================
# 2. Field validation
# ============================================================================

class TestTaskEnvelopeValidation:
    def test_priority_lower_bound(self):
        with pytest.raises(ValidationError):
            TaskEnvelope(priority=0)

    def test_priority_upper_bound(self):
        with pytest.raises(ValidationError):
            TaskEnvelope(priority=11)

    def test_timeout_must_be_positive(self):
        with pytest.raises(ValidationError):
            TaskEnvelope(timeout=0)

    def test_timeout_negative_rejected(self):
        with pytest.raises(ValidationError):
            TaskEnvelope(timeout=-1.0)

    def test_explicit_ids_preserved(self):
        env = TaskEnvelope(task_id="my-task-123", trace_id="my-trace-456")
        assert env.task_id == "my-task-123"
        assert env.trace_id == "my-trace-456"


# ============================================================================
# 3. envelope_from_command_request adapter
# ============================================================================

class TestEnvelopeFromCommandRequest:
    def test_basic_conversion(self):
        env = envelope_from_command_request(
            command="screenshot",
            targets=["device_a"],
            params={"format": "png"},
        )
        assert env.tool_name == "screenshot"
        assert env.targets == ["device_a"]
        assert env.args == {"format": "png"}
        assert env.source == "api"

    def test_mode_stored_in_metadata(self):
        env = envelope_from_command_request(
            command="click",
            targets=["dev1"],
            params={},
            mode="async",
        )
        assert env.metadata["mode"] == "async"

    def test_request_id_propagated(self):
        env = envelope_from_command_request(
            command="ping",
            targets=["dev1"],
            params={},
            request_id="req-xyz",
        )
        assert env.task_id == "req-xyz"
        assert env.metadata["request_id"] == "req-xyz"

    def test_priority_and_timeout(self):
        env = envelope_from_command_request(
            command="cmd",
            targets=["dev"],
            params={},
            priority=3,
            timeout=60.0,
        )
        assert env.priority == 3
        assert env.timeout == 60.0

    def test_unique_trace_ids(self):
        env1 = envelope_from_command_request(command="a", targets=[], params={})
        env2 = envelope_from_command_request(command="b", targets=[], params={})
        assert env1.trace_id != env2.trace_id

    def test_explicit_trace_id(self):
        env = envelope_from_command_request(
            command="c", targets=[], params={}, trace_id="my-trace"
        )
        assert env.trace_id == "my-trace"


# ============================================================================
# 4. envelope_from_relay_request adapter
# ============================================================================

class TestEnvelopeFromRelayRequest:
    def test_source_and_target(self):
        env = envelope_from_relay_request(
            source_device="phone",
            target_device="tablet",
            payload_type="task",
            payload={"action": "open_app"},
        )
        assert env.source == "phone"
        assert env.targets[0] == "tablet"
        assert env.tool_name == "task"
        assert env.args == {"action": "open_app"}

    def test_chain_in_targets(self):
        env = envelope_from_relay_request(
            source_device="A",
            target_device="B",
            payload_type="cmd",
            payload={},
            chain=["C", "D"],
        )
        assert env.targets == ["B", "C", "D"]
        assert env.metadata["relay_chain"] == ["C", "D"]

    def test_relay_id_as_task_id(self):
        env = envelope_from_relay_request(
            source_device="X",
            target_device="Y",
            payload_type="t",
            payload={},
            relay_id="relay-001",
        )
        assert env.task_id == "relay-001"
        assert env.metadata["relay_id"] == "relay-001"

    def test_timeout_propagated(self):
        env = envelope_from_relay_request(
            source_device="A", target_device="B",
            payload_type="t", payload={}, timeout_seconds=45.0,
        )
        assert env.timeout == 45.0


# ============================================================================
# 5. envelope_from_mcp_call adapter
# ============================================================================

class TestEnvelopeFromMcpCall:
    def test_basic_mcp_call(self):
        env = envelope_from_mcp_call(
            server_name="my-mcp",
            tool_name="read_file",
            arguments={"path": "/tmp/test.txt"},
        )
        assert env.targets == ["my-mcp"]
        assert env.tool_name == "read_file"
        assert env.args == {"path": "/tmp/test.txt"}
        assert env.metadata["mcp_server"] == "my-mcp"

    def test_source_default(self):
        env = envelope_from_mcp_call(
            server_name="srv", tool_name="t", arguments={}
        )
        assert env.source == "api"

    def test_custom_trace_id(self):
        env = envelope_from_mcp_call(
            server_name="srv", tool_name="t", arguments={},
            trace_id="trace-custom",
        )
        assert env.trace_id == "trace-custom"


# ============================================================================
# 6 & 7. CommandRouter integration
# ============================================================================

class TestCommandRouterEnvelopeIntegration:
    """CommandRouter.route_command and route_envelope with a mock executor."""

    def _make_router(self, executor):
        from core.command_router import CommandRouter
        return CommandRouter(executor=executor)

    @pytest.mark.asyncio
    async def test_route_command_without_trace_id(self):
        """Backward compat: trace_id is auto-generated when omitted."""
        async def mock_executor(target, command, params):
            return {"done": True}

        router = self._make_router(mock_executor)
        result = await router.route_command(
            device_id="dev1",
            command="ping",
            payload={},
            command_id="cmd-1",
            task_id="task-1",
        )
        assert result["success"] is True
        assert "trace_id" in result
        assert result["trace_id"].startswith("trace_")

    @pytest.mark.asyncio
    async def test_route_command_with_explicit_trace_id(self):
        async def mock_executor(target, command, params):
            return {"done": True}

        router = self._make_router(mock_executor)
        result = await router.route_command(
            device_id="dev1",
            command="ping",
            payload={},
            command_id="cmd-2",
            task_id="task-2",
            trace_id="explicit-trace",
        )
        assert result["trace_id"] == "explicit-trace"

    @pytest.mark.asyncio
    async def test_route_envelope_delegates(self):
        async def mock_executor(target, command, params):
            return {"executed": command}

        router = self._make_router(mock_executor)
        envelope = TaskEnvelope(
            task_id="env-task-1",
            trace_id="env-trace-1",
            source="test",
            targets=["node_42"],
            tool_name="status",
            args={"verbose": True},
        )
        result = await router.route_envelope(envelope)
        assert result["success"] is True
        assert result["trace_id"] == "env-trace-1"
        assert result["task_id"] == "env-task-1"

    @pytest.mark.asyncio
    async def test_route_envelope_invalid_empty_device(self):
        """Envelope with empty target → INVALID_ENVELOPE error."""
        router = self._make_router(None)
        envelope = TaskEnvelope(
            task_id="bad-task",
            trace_id="bad-trace",
            source="test",
            targets=[],   # no targets → empty device_id
            tool_name="ping",
        )
        result = await router.route_envelope(envelope)
        assert result["success"] is False
        assert result["error_code"] == "INVALID_ENVELOPE"
