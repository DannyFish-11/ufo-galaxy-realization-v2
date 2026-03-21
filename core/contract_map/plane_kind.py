"""
core/contract_map/plane_kind.py
================================
Stable enumeration of the message/data planes that exist in the current
Galaxy runtime architecture.

Each ``PlaneKind`` value represents one coherent boundary across which messages
and contracts flow.  The names are grounded in real code paths that already
exist in the repository:

- ``device_plane``          — AIP/WebSocket flows between devices and the
                              gateway (core/routes/devices.py, galaxy_gateway/
                              device_router.py, CommandEnvelope).
- ``orchestration_plane``   — Internal task-envelope contract that governs how
                              work is handed from the gateway to the executor
                              graph (core/schemas/task_envelope.py,
                              galaxy_gateway/orchestrator/task_orchestrator.py).
- ``control_plane``         — NATS JetStream subjects that carry task dispatch,
                              worker heartbeats, MCP calls, and audit events
                              (core/nats_bus.py, core/control_plane/).
- ``runtime_handoff_plane`` — Contracts that transfer execution context between
                              the gateway and the downstream agent runtime
                              (galaxy_gateway/agent_bridge.py — HandoffContract,
                              core/control_plane/swarm_manifest.py —
                              SwarmAgentManifest).
- ``projection_plane``      — Read surfaces that expose derived/summarised
                              runtime state to dashboards and clients
                              (core/routes/projection.py, core/projection/
                              runtime_projection.py).
- ``observability_plane``   — Cross-cutting audit traces, error telemetry, and
                              diagnostic events that flow orthogonally to all
                              other planes (core/routes/audit.py,
                              core/routes/observability.py, NATSTopics audit.*).
"""

from __future__ import annotations

from enum import Enum


class PlaneKind(str, Enum):
    """Canonical set of message planes in the Galaxy runtime."""

    device_plane = "device_plane"
    """AIP/WebSocket device-facing flows: registration, heartbeat,
    capability reports, task dispatch to/from physical devices."""

    orchestration_plane = "orchestration_plane"
    """Internal task-envelope contracts: TaskEnvelope lifecycle,
    priority, session continuity, and lifecycle state machine."""

    control_plane = "control_plane"
    """NATS JetStream control/task subjects: task dispatch, result
    delivery, worker heartbeat, MCP calls, capability events."""

    runtime_handoff_plane = "runtime_handoff_plane"
    """Gateway-to-runtime handoff: HandoffContract (agent_bridge),
    SwarmAgentManifest (remote swarm dispatch)."""

    projection_plane = "projection_plane"
    """Read-only derived state surfaces: RuntimeProjection, return
    intelligence, execution-policy views, merge summaries."""

    observability_plane = "observability_plane"
    """Cross-cutting audit, telemetry, and diagnostic events that do
    not belong exclusively to any single functional plane."""
