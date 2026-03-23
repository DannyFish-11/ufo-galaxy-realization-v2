"""core/capabilities — canonical capability dispatch layer.

This package is owned by OpenClawd and provides the single canonical
execution path for tool/capability invocations:

  MCP tools       → mcp__<server_id>__<tool_name>
  Skills          → skill__<skill_id>
  Node actions    → node__<node_id>__<action>
  Gateway tools   → mcp__gateway__<tool_name>
  GitHub addons   → github__<action>

Public surface
--------------
  CanonicalDispatcher  — primary dispatcher class
  DispatchResult       — normalized result contract
  CapabilityLayer      — capability layer classification enum
"""

from core.capabilities.canonical_dispatcher import (  # noqa: F401
    CanonicalDispatcher,
    CapabilityLayer,
    DispatchResult,
    get_canonical_dispatcher,
)
