"""
core/transport_hierarchy.py
============================
Canonical transport role hierarchy for non-WebRTC paths (PR-4).

This module defines the intended transport roles for the Galaxy runtime and
is the authoritative reference for transport semantics:

  DIRECT_WS  = primary transport      — canonical first-choice delivery path
  RELAY      = fallback transport     — mediated fallback, never a truth source
  MESH       = overlay / enrichment   — topology assist only, not orchestration

Higher-level code (readiness, routing, dispatch) must treat these roles as
authoritative and must not allow mesh presence or relay availability to
substitute for canonical connection or orchestration truth.

Public API
----------
Sentinels:
    TRANSPORT_HIERARCHY_AUTHORITY       — identifies this as the hierarchy authority
    TRANSPORT_ROLE_DIRECT_WS            — "primary"
    TRANSPORT_ROLE_RELAY                — "fallback"
    TRANSPORT_ROLE_MESH                 — "overlay"
    MESH_ORCHESTRATION_AUTHORITY_EXCLUDED — affirms mesh is excluded from orchestration

Helpers:
    transport_role_for_path(path)       — maps a preferred_path string → role string
"""

from __future__ import annotations

__all__ = [
    "TRANSPORT_HIERARCHY_AUTHORITY",
    "TRANSPORT_ROLE_DIRECT_WS",
    "TRANSPORT_ROLE_RELAY",
    "TRANSPORT_ROLE_MESH",
    "MESH_ORCHESTRATION_AUTHORITY_EXCLUDED",
    "transport_role_for_path",
]

# ---------------------------------------------------------------------------
# Authority sentinel — identifies this module as the canonical hierarchy source
# ---------------------------------------------------------------------------

TRANSPORT_HIERARCHY_AUTHORITY: str = "TRANSPORT_HIERARCHY::CANONICAL_V1"

# ---------------------------------------------------------------------------
# Transport role constants
# ---------------------------------------------------------------------------

# Direct WebSocket is the canonical primary transport.  When available it
# must be the preferred dispatch path.  All higher-level routing and
# readiness logic should prefer this path over any alternative.
TRANSPORT_ROLE_DIRECT_WS: str = "primary"

# Relay (ProxyRelay / server-mediated forwarding) is the canonical fallback
# transport.  Relay availability contributes to routability but does NOT
# substitute for canonical connection truth.  A device reachable only via
# relay is routable but not directly connected.
TRANSPORT_ROLE_RELAY: str = "fallback"

# Mesh (MeshCoordinator P2P / peer-exchange) is an overlay for topology
# enrichment, peer discovery, and assisted delivery.  Mesh presence or
# membership MUST NOT imply canonical routability or orchestration
# eligibility.  Mesh send paths are subordinate to canonical transport and
# dispatch authority decisions.
TRANSPORT_ROLE_MESH: str = "overlay"

# Explicit sentinel affirming that mesh is excluded from acting as an
# orchestration authority.  Import this sentinel to document an exclusion
# boundary at a call site.
MESH_ORCHESTRATION_AUTHORITY_EXCLUDED: bool = True

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

# Maps preferred_path strings (as used in RoutabilitySummary) to roles.
_PATH_TO_ROLE: dict[str, str] = {
    "direct_ws": TRANSPORT_ROLE_DIRECT_WS,
    "ucm": TRANSPORT_ROLE_DIRECT_WS,       # UCM send is still direct WS delivery
    "relay": TRANSPORT_ROLE_RELAY,
    # Mesh paths are listed for completeness but their role is overlay-only.
    # They should NOT appear as preferred_path after PR-4 hierarchy enforcement.
    "mesh_direct": TRANSPORT_ROLE_MESH,
    "mesh_relay": TRANSPORT_ROLE_MESH,
    "none": "none",
}


def transport_role_for_path(path: str) -> str:
    """Return the transport role string for a *preferred_path* value.

    Returns one of ``"primary"``, ``"fallback"``, ``"overlay"``, or ``"none"``.
    Unknown paths return ``"unknown"``.
    """
    return _PATH_TO_ROLE.get(path, "unknown")
