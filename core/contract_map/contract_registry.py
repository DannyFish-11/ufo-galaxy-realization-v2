"""
core/contract_map/contract_registry.py
========================================
Singleton registry that holds all known :class:`ContractDescriptor` entries
for the Galaxy runtime.

The registry is **seeded at import time** with descriptors grounded in the
current main-branch architecture.  Additional descriptors can be registered
at runtime (e.g. by plugin loaders) via :meth:`ContractRegistry.register`.

Thread-safety
-------------
The registry uses a ``threading.Lock`` for write operations so it is safe
to call ``register`` from multiple threads.  The read path (``get_*`` /
``snapshot``) returns copies and does not hold the lock.

Non-goals
---------
- This registry does *not* replace TaskEnvelope, HandoffContract,
  SwarmAgentManifest, or any NATS payload model.
- It does *not* replace the NATS transport layer.
- It does *not* perform schema validation.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from .contract_descriptor import ContractDescriptor
from .message_kind import MessageKind
from .plane_kind import PlaneKind

# ---------------------------------------------------------------------------
# Registry implementation
# ---------------------------------------------------------------------------


class ContractRegistry:
    """Read/write registry of :class:`ContractDescriptor` entries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # keyed by MessageKind value for O(1) lookup
        self._registry: Dict[str, ContractDescriptor] = {}

    # ------------------------------------------------------------------
    # Write interface
    # ------------------------------------------------------------------

    def register(self, descriptor: ContractDescriptor) -> None:
        """Add or replace a descriptor.

        Calling ``register`` with a descriptor whose ``kind`` is already
        present will overwrite the existing entry.  This is intentional so
        that plugins / late-binding code can refine descriptors registered
        by the seed layer.
        """
        with self._lock:
            self._registry[descriptor.kind.value] = descriptor

    # ------------------------------------------------------------------
    # Read interface
    # ------------------------------------------------------------------

    def get(self, kind: MessageKind) -> Optional[ContractDescriptor]:
        """Return the descriptor for *kind*, or ``None`` if not registered."""
        return self._registry.get(kind.value)

    def all_descriptors(self) -> List[ContractDescriptor]:
        """Return all registered descriptors (unsorted copy)."""
        return list(self._registry.values())

    def descriptors_for_plane(self, plane: PlaneKind) -> List[ContractDescriptor]:
        """Return all descriptors belonging to *plane*."""
        return [d for d in self._registry.values() if d.plane == plane]

    def snapshot(self) -> Dict[str, dict]:
        """Return a JSON-serialisable snapshot of the full registry.

        Keys are ``MessageKind`` values; values are ``ContractDescriptor.to_dict()``.
        """
        return {k: v.to_dict() for k, v in self._registry.items()}

    def planes_summary(self) -> Dict[str, List[str]]:
        """Return a mapping of plane → list of message-kind values."""
        result: Dict[str, List[str]] = {}
        for d in self._registry.values():
            result.setdefault(d.plane.value, []).append(d.kind.value)
        return result

    def __len__(self) -> int:
        return len(self._registry)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_registry: Optional[ContractRegistry] = None
_registry_lock = threading.Lock()


def get_contract_registry() -> ContractRegistry:
    """Return the module-level singleton :class:`ContractRegistry`.

    The registry is seeded with all known current-architecture descriptors
    on first call.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ContractRegistry()
                _seed_registry(_registry)
    return _registry


def reset_contract_registry() -> None:
    """Reset the singleton (for testing only)."""
    global _registry
    with _registry_lock:
        _registry = None


# ---------------------------------------------------------------------------
# Seed data — descriptors grounded in current main-branch architecture
# ---------------------------------------------------------------------------


def _seed_registry(reg: ContractRegistry) -> None:  # noqa: C901  (intentionally long)
    """Populate *reg* with descriptors for all currently-known contracts."""

    # ------------------------------------------------------------------ #
    # Device plane                                                         #
    # ------------------------------------------------------------------ #

    reg.register(ContractDescriptor(
        plane=PlaneKind.device_plane,
        kind=MessageKind.device_register,
        canonical_type=None,
        source_module="core.routes.devices",
        identity_fields=["device_id"],
        producer_modules=["android_app", "desktop_client"],
        consumer_modules=["core.routes.devices", "core.unified.device_manager"],
        notes=(
            "Sent via POST /api/v1/devices/register.  Payload includes "
            "device_id, capabilities list, and optional metadata.  "
            "Handled by core/unified/device_manager.py after route intake."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.device_plane,
        kind=MessageKind.device_heartbeat,
        canonical_type=None,
        source_module="core.routes.devices",
        identity_fields=["device_id", "timestamp"],
        producer_modules=["android_app", "desktop_client"],
        consumer_modules=["core.routes.devices", "core.unified.device_health"],
        notes=(
            "POST /api/v1/devices/{id}/heartbeat.  Feeds "
            "DeviceHealthScorer (core/unified/device_health.py) which "
            "computes weighted health score from latency/error_rate/"
            "jitter/heartbeat_age."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.device_plane,
        kind=MessageKind.device_capability_report,
        canonical_type="core.unified.capability_contract.CapabilityContract",
        source_module="core.unified.capability_contract",
        identity_fields=["device_id", "capability_id"],
        producer_modules=["core.routes.devices", "core.nodes.node_fabric_registry"],
        consumer_modules=["core.agent.capability_registry", "core.unified.capability_resolver"],
        notes=(
            "CapabilityContract validates each capability before insertion "
            "into CapabilityRegistry.  NodeFabricRegistry.sync_capabilities_to_registry() "
            "injects node caps via inject_item().  NATS mirror: "
            "galaxy.capability.registered.*"
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.device_plane,
        kind=MessageKind.device_task_result,
        canonical_type="core.unified.command_envelope.ResultEnvelope",
        source_module="core.unified.command_envelope",
        identity_fields=["task_id", "trace_id", "device_id"],
        producer_modules=["android_app", "desktop_client", "core.command_router"],
        consumer_modules=["galaxy_gateway.device_router", "core.e2e_orchestrator"],
        notes=(
            "ResultEnvelope mirrors CommandEnvelope for responses.  "
            "Contains result, error, status_code fields.  "
            "Delivered back over the same channel that carried the "
            "CommandEnvelope (WebSocket /ws/device/{id} or NATS)."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.device_plane,
        kind=MessageKind.command_envelope,
        canonical_type="core.unified.command_envelope.CommandEnvelope",
        source_module="core.unified.command_envelope",
        identity_fields=["trace_id", "task_id", "runtime_session_id"],
        producer_modules=["galaxy_gateway.device_router", "core.command_router"],
        consumer_modules=["android_app", "desktop_client", "core.routes.command"],
        notes=(
            "AIP v3 wire-level envelope (version='3.0').  Verbs: "
            "EXECUTE | CANCEL | INTERRUPT | QUERY.  "
            "from_task_envelope() and from_aip_message() constructors "
            "bridge between internal and external representations.  "
            "idempotency_key auto-generated from task_id when absent."
        ),
    ))

    # ------------------------------------------------------------------ #
    # Orchestration plane                                                  #
    # ------------------------------------------------------------------ #

    reg.register(ContractDescriptor(
        plane=PlaneKind.orchestration_plane,
        kind=MessageKind.task_envelope,
        canonical_type="core.schemas.task_envelope.TaskEnvelope",
        source_module="core.schemas.task_envelope",
        identity_fields=["task_id", "trace_id", "session_id"],
        producer_modules=[
            "galaxy_gateway.orchestrator.task_orchestrator",
            "galaxy_gateway.device_router",
            "core.e2e_orchestrator",
        ],
        consumer_modules=[
            "core.command_router",
            "core.execution_policy",
            "galaxy_gateway.agent_bridge",
        ],
        notes=(
            "Canonical internal task contract.  Lifecycle: "
            "created → running → done | failed (terminal).  "
            "Carries priority (1-10), timeout, permission_level (0-3), "
            "and required_capabilities list.  All work entering the "
            "executor graph must be wrapped in a TaskEnvelope."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.orchestration_plane,
        kind=MessageKind.task_envelope_cancel,
        canonical_type="core.unified.command_envelope.CommandEnvelope",
        source_module="core.unified.command_envelope",
        identity_fields=["task_id", "trace_id", "cancel_target_task_ids"],
        producer_modules=["core.routes.tasks", "core.routes.command"],
        consumer_modules=["core.command_router", "galaxy_gateway.orchestrator.task_orchestrator"],
        notes=(
            "CommandEnvelope with verb=CANCEL.  Produced by "
            "make_cancel().  cancel_reason encodes why: "
            "USER_REQUEST | TIMEOUT | HEALTH_DEGRADED | POLICY_REJECTED "
            "| SUPERSEDED | UNKNOWN."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.orchestration_plane,
        kind=MessageKind.task_envelope_interrupt,
        canonical_type="core.unified.command_envelope.CommandEnvelope",
        source_module="core.unified.command_envelope",
        identity_fields=["task_id", "trace_id"],
        producer_modules=["core.routes.tasks", "core.routes.command"],
        consumer_modules=["core.command_router"],
        notes=(
            "CommandEnvelope with verb=INTERRUPT.  Best-effort immediate "
            "stop; not guaranteed to halt already-started side effects.  "
            "Produced by make_interrupt()."
        ),
    ))

    # ------------------------------------------------------------------ #
    # Control plane — NATS                                                 #
    # ------------------------------------------------------------------ #

    reg.register(ContractDescriptor(
        plane=PlaneKind.control_plane,
        kind=MessageKind.nats_task_dispatch,
        canonical_type=None,
        source_module="core.nats_bus",
        identity_fields=["task_id", "trace_id", "target"],
        producer_modules=["galaxy_gateway.orchestrator.task_orchestrator", "core.e2e_orchestrator"],
        consumer_modules=["core.command_router", "worker_processes"],
        notes=(
            "Published on galaxy.task.dispatch.<target>.  "
            "Schema: TaskDispatchModel (JSON, snake_case).  "
            "Stream: GALAXY_TASKS (100K msgs, 1 GB).  "
            "Consumers must ack within configured timeout."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.control_plane,
        kind=MessageKind.nats_task_result,
        canonical_type=None,
        source_module="core.nats_bus",
        identity_fields=["task_id", "trace_id"],
        producer_modules=["worker_processes", "core.command_router"],
        consumer_modules=["galaxy_gateway.orchestrator.task_orchestrator", "core.e2e_orchestrator"],
        notes=(
            "Published on galaxy.task.result.<task_id>.  "
            "Schema: TaskResultModel (JSON, snake_case).  "
            "Correlated back to original dispatch via task_id."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.control_plane,
        kind=MessageKind.nats_worker_heartbeat,
        canonical_type=None,
        source_module="core.nats_bus",
        identity_fields=["worker_id", "timestamp"],
        producer_modules=["worker_processes"],
        consumer_modules=["core.orchestration.global_arbiter", "core.unified.device_health"],
        notes=(
            "Published on galaxy.task.worker_heartbeat.  "
            "Schema: WorkerHeartbeatModel.  "
            "GlobalArbiter uses these to inform scheduling decisions."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.control_plane,
        kind=MessageKind.nats_capability_event,
        canonical_type=None,
        source_module="core.nats_bus",
        identity_fields=["capability_id", "source"],
        producer_modules=["core.agent.capability_registry", "core.nodes.node_fabric_registry"],
        consumer_modules=["core.unified.capability_resolver"],
        notes=(
            "Published on galaxy.capability.registered.<source>.  "
            "Mirrors CapabilityRegistry mutations so remote nodes stay "
            "in sync.  Schema: AgentEventModel."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.control_plane,
        kind=MessageKind.nats_audit_event,
        canonical_type=None,
        source_module="core.nats_bus",
        identity_fields=["trace_id", "event_type"],
        producer_modules=["core.routes.command", "galaxy_gateway.agent_bridge"],
        consumer_modules=["core.routes.audit"],
        notes=(
            "Published on galaxy.audit.command / galaxy.audit.result / "
            "galaxy.audit.violation.  "
            "publish_audit_event() enforces trace propagation via "
            "_ensure_trace_fields()."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.control_plane,
        kind=MessageKind.nats_mcp_call,
        canonical_type=None,
        source_module="core.nats_bus",
        identity_fields=["call_id", "tool_name"],
        producer_modules=["core.mcp_loader"],
        consumer_modules=["mcp_servers"],
        notes=(
            "Published on galaxy.mcp.call.  "
            "Schema: MCPCallRequestModel.  "
            "Stream: GALAXY_MCP (50K msgs, 512 MB)."
        ),
    ))

    # ------------------------------------------------------------------ #
    # Runtime handoff plane                                                #
    # ------------------------------------------------------------------ #

    reg.register(ContractDescriptor(
        plane=PlaneKind.runtime_handoff_plane,
        kind=MessageKind.handoff_contract,
        canonical_type="galaxy_gateway.agent_bridge.HandoffContract",
        source_module="galaxy_gateway.agent_bridge",
        identity_fields=["trace_id", "task_id"],
        producer_modules=["galaxy_gateway.agent_bridge"],
        consumer_modules=["agent_runtime"],
        notes=(
            "Dataclass transferred via POST /handoff to the downstream "
            "agent runtime (GALAXY_RUNTIME_URL, default localhost:9000).  "
            "Fields: trace_id, task, capability, exec_mode, route_mode, "
            "session, callback_channel, task_id.  "
            "LRU dedup cache (1024 entries) prevents duplicate handoffs.  "
            "Falls back to local executor on timeout / connection error."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.runtime_handoff_plane,
        kind=MessageKind.swarm_agent_manifest,
        canonical_type="core.control_plane.swarm_manifest.SwarmAgentManifest",
        source_module="core.control_plane.swarm_manifest",
        identity_fields=["manifest_id", "agent_id", "task_id", "trace_id", "session_id"],
        producer_modules=["swarm_coordinator"],
        consumer_modules=["galaxy_gateway.agent_bridge", "remote_agent_runtime"],
        notes=(
            "Serialised swarm-member manifest for remote dispatch.  "
            "State-only (no live objects), JSON-encodable, picklable.  "
            "to_agent_execute_payload() produces PR155-compatible payload.  "
            "Fields: agent_id, template, system_prompt, tool_schemas, "
            "memory_snapshot, task, subtask, target_device_id, "
            "required_capabilities, timeout_seconds."
        ),
    ))

    # ------------------------------------------------------------------ #
    # Projection plane                                                     #
    # ------------------------------------------------------------------ #

    reg.register(ContractDescriptor(
        plane=PlaneKind.projection_plane,
        kind=MessageKind.runtime_projection,
        canonical_type="core.projection.runtime_projection.RuntimeProjection",
        source_module="core.projection.runtime_projection",
        identity_fields=["timestamp"],
        producer_modules=["core.routes.projection"],
        consumer_modules=["dashboard_frontend", "status_board_v2"],
        notes=(
            "Read-only assembled snapshot at GET /api/v1/projection/runtime.  "
            "Fields: tri_state_phase, runtime_domain, presence_intensity, "
            "coherence, collapse_tendency, retreat_tendency, "
            "primary_model_id, support_model_ids, active_weights, "
            "route_reason, active_device_ids, execution_stage, "
            "current_task_summary, timestamp.  "
            "Graceful degradation: returns minimal valid projection when "
            "continuum or topology layers are unavailable."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.projection_plane,
        kind=MessageKind.return_projection,
        canonical_type="core.projection.runtime_projection.RuntimeProjection",
        source_module="core.routes.projection",
        identity_fields=["timestamp"],
        producer_modules=["core.routes.projection"],
        consumer_modules=["dashboard_frontend"],
        notes=(
            "RuntimeProjection + nested 'return_intelligence' key at "
            "GET /api/v1/projection/return.  "
            "Includes ReturnSummary (PR-10).  "
            "Public-safe: internal 'receding' phase not exposed."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.projection_plane,
        kind=MessageKind.execution_policy_projection,
        canonical_type="core.projection.runtime_projection.RuntimeProjection",
        source_module="core.routes.projection",
        identity_fields=["timestamp"],
        producer_modules=["core.routes.projection"],
        consumer_modules=["dashboard_frontend", "manifest_stage_controller"],
        notes=(
            "RuntimeProjection + nested 'execution_policy' key at "
            "GET /api/v1/projection/execution_policy (PR-11).  "
            "Includes policy band, risk/action/fallback budgets, "
            "executor levels, cross-device permissions."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.projection_plane,
        kind=MessageKind.merge_summary,
        canonical_type=None,
        source_module="core.routes.projection",
        identity_fields=["task_id"],
        producer_modules=["core.distributed_execution"],
        consumer_modules=["core.routes.projection", "dashboard_frontend"],
        notes=(
            "Cross-device result merge status at "
            "GET /api/v1/execution/merge-summary (PR-14).  "
            "Covers distributed merge and recovery semantics."
        ),
    ))

    # ------------------------------------------------------------------ #
    # Observability plane                                                  #
    # ------------------------------------------------------------------ #

    reg.register(ContractDescriptor(
        plane=PlaneKind.observability_plane,
        kind=MessageKind.audit_trace,
        canonical_type=None,
        source_module="core.routes.audit",
        identity_fields=["trace_id"],
        producer_modules=["core.routes.command", "galaxy_gateway.agent_bridge", "core.nats_bus"],
        consumer_modules=["core.routes.audit"],
        notes=(
            "Structured audit trace record at GET /api/v1/audit/traces.  "
            "Also mirrored to NATS galaxy.audit.* subjects.  "
            "Covers command, result, and violation event types."
        ),
    ))

    reg.register(ContractDescriptor(
        plane=PlaneKind.observability_plane,
        kind=MessageKind.error_payload,
        canonical_type="core.unified.error_codes.ErrorPayload",
        source_module="core.unified.error_codes",
        identity_fields=["code", "trace_id"],
        producer_modules=["core.unified.error_mapper"],
        consumer_modules=["core.routes.command", "core.routes.tasks", "client_sdks"],
        notes=(
            "GalaxyErrorCode-classified error payload (Block-5).  "
            "ErrorMapper maps raw exceptions by class name (MRO walk) "
            "and legacy string errors.  "
            "Codes cover: PL (planner), EX (executor), GW (gateway), "
            "DV (device), TR (transport), ID (idempotency), "
            "AR (arbiter), RL (release)."
        ),
    ))
