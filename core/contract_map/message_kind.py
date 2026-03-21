"""
core/contract_map/message_kind.py
==================================
Stable enumeration of contract / message kinds that flow through the
Galaxy runtime.  Every value maps to an actual code artefact in the
repository; the ``source_module`` docstring notes in each member give
the canonical reference.

Naming follows ``<noun>_<verb_or_role>`` where possible so the taxonomy
is self-describing and remains stable even as the underlying schemas
evolve.
"""

from __future__ import annotations

from enum import Enum


class MessageKind(str, Enum):
    """Canonical set of contract/message kinds in the Galaxy runtime."""

    # ------------------------------------------------------------------ #
    # Device plane — AIP / WebSocket device-facing messages               #
    # ------------------------------------------------------------------ #

    device_register = "device_register"
    """A device announces itself to the gateway and provides its initial
    capability set.
    Source: core/routes/devices.py — POST /api/v1/devices/register."""

    device_heartbeat = "device_heartbeat"
    """A device sends a liveness ping; optionally includes updated metrics.
    Source: core/routes/devices.py — POST /api/v1/devices/{id}/heartbeat."""

    device_capability_report = "device_capability_report"
    """A device reports or updates its capability set.
    Source: core/unified/capability_contract.py, NATSTopics.capability_registered."""

    device_task_result = "device_task_result"
    """A device returns the result of a task it was asked to execute.
    Source: CommandEnvelope (ResultEnvelope) — core/unified/command_envelope.py."""

    # ------------------------------------------------------------------ #
    # Orchestration plane — TaskEnvelope lifecycle contracts               #
    # ------------------------------------------------------------------ #

    task_envelope = "task_envelope"
    """Canonical internal task contract.  Wraps all work entering the
    executor graph.
    Source: core/schemas/task_envelope.py — TaskEnvelope."""

    task_envelope_cancel = "task_envelope_cancel"
    """Signals cancellation of an in-flight TaskEnvelope.
    Source: core/unified/command_envelope.py — CommandVerb.CANCEL,
            make_cancel()."""

    task_envelope_interrupt = "task_envelope_interrupt"
    """Signals immediate interruption of a running TaskEnvelope.
    Source: core/unified/command_envelope.py — CommandVerb.INTERRUPT,
            make_interrupt()."""

    command_envelope = "command_envelope"
    """AIP v3 wire-level command contract wrapping device and executor
    instructions.
    Source: core/unified/command_envelope.py — CommandEnvelope,
            ENVELOPE_VERSION='3.0'."""

    # ------------------------------------------------------------------ #
    # Control plane — NATS JetStream subjects                             #
    # ------------------------------------------------------------------ #

    nats_task_dispatch = "nats_task_dispatch"
    """NATS task dispatch message on galaxy.task.dispatch.*.
    Source: core/nats_bus.py — NATSTopics.TASK_DISPATCH, TaskDispatchModel."""

    nats_task_result = "nats_task_result"
    """NATS task result message on galaxy.task.result.*.
    Source: core/nats_bus.py — NATSTopics.TASK_RESULT, TaskResultModel."""

    nats_worker_heartbeat = "nats_worker_heartbeat"
    """NATS worker liveness on galaxy.task.worker_heartbeat.
    Source: core/nats_bus.py — NATSTopics.TASK_WORKER_HEARTBEAT,
            WorkerHeartbeatModel."""

    nats_capability_event = "nats_capability_event"
    """NATS capability registration/removal event.
    Source: core/nats_bus.py — NATSTopics.CAPABILITY_REGISTERED."""

    nats_audit_event = "nats_audit_event"
    """NATS audit log event on galaxy.audit.*.
    Source: core/nats_bus.py — NATSTopics.AUDIT_COMMAND,
            publish_audit_event()."""

    nats_mcp_call = "nats_mcp_call"
    """NATS MCP tool-call request.
    Source: core/nats_bus.py — NATSTopics.MCP_CALL, MCPCallRequestModel."""

    # ------------------------------------------------------------------ #
    # Runtime handoff plane — gateway-to-runtime transfer contracts        #
    # ------------------------------------------------------------------ #

    handoff_contract = "handoff_contract"
    """Transfers execution context from the gateway to the downstream
    agent runtime.
    Source: galaxy_gateway/agent_bridge.py — HandoffContract dataclass."""

    swarm_agent_manifest = "swarm_agent_manifest"
    """Serialised manifest for dispatching a remote swarm agent member.
    Source: core/control_plane/swarm_manifest.py — SwarmAgentManifest."""

    # ------------------------------------------------------------------ #
    # Projection plane — read-only derived state surfaces                 #
    # ------------------------------------------------------------------ #

    runtime_projection = "runtime_projection"
    """Assembled runtime-state snapshot for dashboards and clients.
    Source: core/projection/runtime_projection.py — RuntimeProjection,
            GET /api/v1/projection/runtime."""

    return_projection = "return_projection"
    """RuntimeProjection enriched with return-intelligence summary.
    Source: core/routes/projection.py — GET /api/v1/projection/return."""

    execution_policy_projection = "execution_policy_projection"
    """RuntimeProjection enriched with execution-policy view.
    Source: core/routes/projection.py — GET /api/v1/projection/execution_policy."""

    merge_summary = "merge_summary"
    """Summary of cross-device result merge status.
    Source: core/routes/projection.py — GET /api/v1/execution/merge-summary."""

    # ------------------------------------------------------------------ #
    # Observability plane — audit / telemetry                             #
    # ------------------------------------------------------------------ #

    audit_trace = "audit_trace"
    """Structured audit trace record.
    Source: core/routes/audit.py — GET /api/v1/audit/traces."""

    error_payload = "error_payload"
    """Structured error payload with GalaxyErrorCode classification.
    Source: core/unified/error_codes.py — ErrorPayload."""
