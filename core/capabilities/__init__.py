"""core/capabilities — canonical capability dispatch layer.

This package is owned by OpenClawd and provides the single canonical
execution path for tool/capability invocations:

  MCP tools       → mcp__<server_id>__<tool_name>
  Skills          → skill__<skill_id>
  Node actions    → node__<node_id>__<action>
  Gateway tools   → mcp__gateway__<tool_name>
  GitHub addons   → github__<action>
  Device actions  → device__<device_id>__<action>  (PR-3)

Public surface
--------------
  CanonicalDispatcher  — primary dispatcher class
  DispatchResult       — normalized result contract
  CapabilityLayer      — capability layer classification enum

Capability bus (PR-3)
---------------------
  get_capability_bus   — singleton capability bus factory
  reset_capability_bus — test-isolation reset
  CapabilityBus        — unified capability registry
  CapabilityBusEntry   — unified capability descriptor
  CapabilityBusRole    — role/origin enum
  CapabilityHealthStatus — health status enum
  BusSnapshot          — point-in-time bus snapshot
"""

from core.capabilities.canonical_dispatcher import (  # noqa: F401
    CanonicalDispatcher,
    CapabilityLayer,
    DispatchResult,
    get_canonical_dispatcher,
)

from core.capability_bus import (  # noqa: F401
    CapabilityBus,
    CapabilityBusEntry,
    CapabilityBusRole,
    CapabilityHealthStatus,
    BusSnapshot,
    get_capability_bus,
    reset_capability_bus,
)
