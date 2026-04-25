#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_tier.py
========================
PR-4: Governance / Readiness / Release Validation Main Chain Entry.

Capability Tiering — canonical definition of which capabilities belong to
which tier of system maturity.

Problem addressed
-----------------
The system previously had no canonical boundary between:

* **Main-chain capabilities** — fully integrated, tested, and production-ready
  capabilities that form the canonical operational backbone.
* **Quasi-main-chain capabilities** — capabilities that are substantially
  integrated but have known gaps (e.g. incomplete E2E verification, pending
  test coverage, staged rollout).
* **Experimental / extension capabilities** — capabilities that exist in the
  codebase but are NOT fully integrated into the main dispatch chain.  They
  MUST NOT be treated as production-ready or described as main-chain.

This ambiguity led to system maturity being *over-estimated* because
un-integrated capabilities were described alongside verified main-chain ones.

Design principles
-----------------
- **Additive only** — does not modify any existing capability module.
- **Single-source-of-truth** — this file is the authoritative tier registry.
  Other modules import from here; they do not define tiers locally.
- **Guard functions** — :func:`assert_main_chain_capability` and
  :func:`require_main_chain_capability` provide hard enforcement points.
- **Auditable** — :func:`get_tier_registry` returns the full tier map for
  logging, test assertions, and CI tooling.

Tier definitions
----------------
MAIN_CHAIN
    Capabilities that are fully integrated into the canonical main path
    ``main.py → OpenClawd → CommandRouter → DeviceRouter → dispatch_to_websocket``.
    These capabilities have verified dispatch, completion, and continuation.

QUASI_MAIN_CHAIN
    Capabilities that are substantially present and partially integrated but
    have at least one known gap:
    - Incomplete E2E verification
    - Staged rollout not yet default-on
    - Truth/session convergence not fully verified

EXPERIMENTAL
    Capabilities that exist in the codebase but are NOT currently integrated
    into the canonical main dispatch chain.  They may be:
    - Under active development
    - Staged / feature-flagged
    - Dependent on external services not yet connected
    Experimental capabilities MUST NOT be described as production main-chain.

Public API
----------
Constants::

    CAPABILITY_TIER_AUTHORITY
    MAIN_CHAIN_IS_VERIFIED_POLICY
    EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY
    QUASI_MAIN_CHAIN_HAS_KNOWN_GAPS_POLICY

Enumerations::

    CapabilityTier

Exceptions::

    CapabilityTierViolationError

Functions::

    get_capability_tier(capability_name) -> CapabilityTier
    assert_main_chain_capability(capability_name) -> None
    require_main_chain_capability(capability_name) -> CapabilityTier
    get_tier_registry() -> Dict[str, str]
    list_capabilities_by_tier(tier) -> List[str]
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("Galaxy.CapabilityTier")

__all__ = [
    # Sentinels / policy constants
    "CAPABILITY_TIER_AUTHORITY",
    "MAIN_CHAIN_IS_VERIFIED_POLICY",
    "EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY",
    "QUASI_MAIN_CHAIN_HAS_KNOWN_GAPS_POLICY",
    # Enumerations
    "CapabilityTier",
    # Exceptions
    "CapabilityTierViolationError",
    # Functions
    "get_capability_tier",
    "assert_main_chain_capability",
    "require_main_chain_capability",
    "get_tier_registry",
    "list_capabilities_by_tier",
    # Registry constant
    "CAPABILITY_TIER_REGISTRY",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CAPABILITY_TIER_AUTHORITY: str = (
    "CAPABILITY_TIER_AUTHORITY::"
    "core.capability_tier::"
    "PR4::capability-tiering-and-semantic-guard::"
    "main-chain-quasi-main-chain-experimental"
)
"""Sentinel: this module is the canonical capability tier registry."""

MAIN_CHAIN_IS_VERIFIED_POLICY: str = (
    "POLICY::MAIN_CHAIN_IS_VERIFIED_V1: "
    "A capability MAY only be classified as MAIN_CHAIN if it has verified "
    "dispatch, completion, and continuation in the canonical path "
    "main.py → OpenClawd → CommandRouter → DeviceRouter → dispatch_to_websocket.  "
    "Unverified or partially-integrated capabilities MUST be QUASI_MAIN_CHAIN "
    "or EXPERIMENTAL."
)
"""Policy: MAIN_CHAIN classification requires verified end-to-end integration."""

EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY: str = (
    "POLICY::EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_V1: "
    "Capabilities in the EXPERIMENTAL tier MUST NOT be described as "
    "main-chain capabilities in documentation, test assertions, or system "
    "maturity assessments.  Code that requires MAIN_CHAIN capabilities "
    "MUST use assert_main_chain_capability() to guard against EXPERIMENTAL "
    "substitution."
)
"""Policy: experimental capabilities must not be treated as main-chain."""

QUASI_MAIN_CHAIN_HAS_KNOWN_GAPS_POLICY: str = (
    "POLICY::QUASI_MAIN_CHAIN_HAS_KNOWN_GAPS_V1: "
    "Capabilities in the QUASI_MAIN_CHAIN tier are substantially present but "
    "have at least one known integration gap.  They MUST NOT be presented as "
    "fully-verified main-chain capabilities.  They MAY be used in production "
    "with explicit acknowledgement of known gaps."
)
"""Policy: quasi-main-chain capabilities have known integration gaps."""


# ---------------------------------------------------------------------------
# CapabilityTier
# ---------------------------------------------------------------------------


class CapabilityTier(str, Enum):
    """Canonical capability tier classification.

    Values
    ------
    MAIN_CHAIN
        Fully integrated, tested, and verified in the canonical main dispatch
        path.  These are the capabilities the system can reliably claim as
        production-ready.

    QUASI_MAIN_CHAIN
        Substantially integrated but with at least one known gap.  Usable in
        production with acknowledged limitations.

    EXPERIMENTAL
        Present in codebase but NOT fully integrated into the main dispatch
        chain.  Must not be described as production main-chain.

    UNKNOWN
        The capability was not found in the tier registry.  Treat as
        EXPERIMENTAL for safety.
    """

    MAIN_CHAIN = "MAIN_CHAIN"
    QUASI_MAIN_CHAIN = "QUASI_MAIN_CHAIN"
    EXPERIMENTAL = "EXPERIMENTAL"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# CapabilityTierViolationError
# ---------------------------------------------------------------------------


class CapabilityTierViolationError(Exception):
    """Raised by :func:`assert_main_chain_capability` when a non-MAIN_CHAIN
    capability is required to be MAIN_CHAIN.

    Attributes
    ----------
    capability : str
        The capability name that failed the tier check.
    actual_tier : CapabilityTier
        The actual tier of the capability.
    """

    def __init__(self, capability: str, actual_tier: CapabilityTier) -> None:
        super().__init__(
            f"Capability '{capability}' is not MAIN_CHAIN "
            f"(actual tier: {actual_tier.value}).  "
            "See EXPERIMENTAL_MUST_NOT_CLAIM_MAIN_CHAIN_POLICY."
        )
        self.capability = capability
        self.actual_tier = actual_tier


# ---------------------------------------------------------------------------
# Canonical capability tier registry
# ---------------------------------------------------------------------------

CAPABILITY_TIER_REGISTRY: Dict[str, str] = {
    # -----------------------------------------------------------------------
    # MAIN_CHAIN capabilities
    # These are verified in the canonical main path:
    # main.py → OpenClawd → CommandRouter → DeviceRouter → dispatch_to_websocket
    # -----------------------------------------------------------------------

    # Core dispatch and routing
    "command_routing": CapabilityTier.MAIN_CHAIN.value,
    "device_dispatch": CapabilityTier.MAIN_CHAIN.value,
    "websocket_dispatch": CapabilityTier.MAIN_CHAIN.value,
    "task_completion_ingress": CapabilityTier.MAIN_CHAIN.value,
    "android_handoff": CapabilityTier.MAIN_CHAIN.value,

    # Session and truth
    "session_management": CapabilityTier.MAIN_CHAIN.value,
    "device_registry": CapabilityTier.MAIN_CHAIN.value,
    "canonical_session_truth": CapabilityTier.MAIN_CHAIN.value,

    # Android core capabilities (verified via device registration)
    "screen": CapabilityTier.MAIN_CHAIN.value,
    "touch": CapabilityTier.MAIN_CHAIN.value,
    "keyboard": CapabilityTier.MAIN_CHAIN.value,

    # Orchestration
    "task_orchestration": CapabilityTier.MAIN_CHAIN.value,
    "llm_routing": CapabilityTier.MAIN_CHAIN.value,
    "skill_dispatch": CapabilityTier.MAIN_CHAIN.value,

    # Governance (verified readiness structure)
    "release_gate_evaluation": CapabilityTier.MAIN_CHAIN.value,
    "readiness_evaluation": CapabilityTier.MAIN_CHAIN.value,

    # -----------------------------------------------------------------------
    # QUASI_MAIN_CHAIN capabilities
    # Substantially integrated but with at least one known gap.
    # -----------------------------------------------------------------------

    # Mesh / multi-node (staged, not default-on)
    "staged_mesh": CapabilityTier.QUASI_MAIN_CHAIN.value,
    "multi_node_dispatch": CapabilityTier.QUASI_MAIN_CHAIN.value,

    # Session migration/continuity (substantially integrated, gaps in E2E)
    "session_migration": CapabilityTier.QUASI_MAIN_CHAIN.value,
    "session_continuity": CapabilityTier.QUASI_MAIN_CHAIN.value,
    "session_recovery": CapabilityTier.QUASI_MAIN_CHAIN.value,

    # Local LLM (integration present, not fully verified in all paths)
    "local_llm": CapabilityTier.QUASI_MAIN_CHAIN.value,

    # Camera / microphone (capability declared, not fully verified in main path)
    "camera": CapabilityTier.QUASI_MAIN_CHAIN.value,
    "microphone": CapabilityTier.QUASI_MAIN_CHAIN.value,

    # -----------------------------------------------------------------------
    # EXPERIMENTAL capabilities
    # Present in codebase but NOT fully integrated into main dispatch chain.
    # MUST NOT be described as production main-chain.
    # -----------------------------------------------------------------------

    # Visual-language models (architecture exists, not wired to main dispatch)
    "vlm": CapabilityTier.EXPERIMENTAL.value,
    "multimodal_vlm": CapabilityTier.EXPERIMENTAL.value,
    "visual_language_model": CapabilityTier.EXPERIMENTAL.value,

    # WebRTC (gateway exists, not connected to canonical main path)
    "webrtc": CapabilityTier.EXPERIMENTAL.value,
    "webrtc_gateway": CapabilityTier.EXPERIMENTAL.value,
    "peer_video": CapabilityTier.EXPERIMENTAL.value,

    # Live mesh runtime engine (staged mesh is QUASI, live engine is EXPERIMENTAL)
    "live_mesh_runtime": CapabilityTier.EXPERIMENTAL.value,
    "mesh_runtime_engine": CapabilityTier.EXPERIMENTAL.value,

    # Hardware-specific features not yet verified in main path
    "bluetooth": CapabilityTier.EXPERIMENTAL.value,
    "nfc": CapabilityTier.EXPERIMENTAL.value,
    "gps": CapabilityTier.EXPERIMENTAL.value,
    "accelerometer": CapabilityTier.EXPERIMENTAL.value,
    "gyroscope": CapabilityTier.EXPERIMENTAL.value,
    "biometric": CapabilityTier.EXPERIMENTAL.value,

    # Dual-repo E2E (architecture defined, not yet verified)
    "dual_repo_e2e": CapabilityTier.EXPERIMENTAL.value,

    # Desktop projection (adapter exists but not in main dispatch path)
    "desktop_projection": CapabilityTier.EXPERIMENTAL.value,
}


# ---------------------------------------------------------------------------
# Public API functions
# ---------------------------------------------------------------------------


def get_capability_tier(capability_name: str) -> CapabilityTier:
    """Return the :class:`CapabilityTier` for *capability_name*.

    If the capability is not found in the registry, returns
    :attr:`CapabilityTier.UNKNOWN` (treated as EXPERIMENTAL for safety).

    Parameters
    ----------
    capability_name : str
        The canonical capability name (case-insensitive lookup).

    Returns
    -------
    CapabilityTier
    """
    key = capability_name.lower().strip()
    # Direct lookup
    raw = CAPABILITY_TIER_REGISTRY.get(key)
    if raw is None:
        # Try case-insensitive scan
        for reg_key, reg_val in CAPABILITY_TIER_REGISTRY.items():
            if reg_key.lower() == key:
                raw = reg_val
                break
    if raw is None:
        logger.debug(
            "get_capability_tier: '%s' not in registry → UNKNOWN", capability_name
        )
        return CapabilityTier.UNKNOWN
    try:
        return CapabilityTier(raw)
    except ValueError:  # pragma: no cover
        return CapabilityTier.UNKNOWN


def assert_main_chain_capability(capability_name: str) -> None:
    """Assert that *capability_name* is MAIN_CHAIN.

    Raises :class:`CapabilityTierViolationError` if the capability is not
    MAIN_CHAIN.  Intended as a hard guard in code paths that require
    verified main-chain integration.

    Parameters
    ----------
    capability_name : str
        The capability to check.

    Raises
    ------
    CapabilityTierViolationError
        When the capability tier is not MAIN_CHAIN.
    """
    tier = get_capability_tier(capability_name)
    if tier != CapabilityTier.MAIN_CHAIN:
        raise CapabilityTierViolationError(capability_name, tier)


def require_main_chain_capability(capability_name: str) -> CapabilityTier:
    """Assert MAIN_CHAIN and return the tier (convenience wrapper).

    Same as :func:`assert_main_chain_capability` but returns the tier on
    success, making it usable in assignment contexts.

    Returns
    -------
    CapabilityTier
        Always :attr:`CapabilityTier.MAIN_CHAIN` (raises on anything else).

    Raises
    ------
    CapabilityTierViolationError
    """
    assert_main_chain_capability(capability_name)
    return CapabilityTier.MAIN_CHAIN


def get_tier_registry() -> Dict[str, str]:
    """Return a copy of the full tier registry for introspection / testing.

    Returns
    -------
    Dict[str, str]
        Maps capability name → tier value string.
    """
    return dict(CAPABILITY_TIER_REGISTRY)


def list_capabilities_by_tier(tier: CapabilityTier) -> List[str]:
    """Return all capability names registered under *tier*.

    Parameters
    ----------
    tier : CapabilityTier

    Returns
    -------
    List[str]
        Sorted list of capability names.
    """
    target = tier.value
    return sorted(k for k, v in CAPABILITY_TIER_REGISTRY.items() if v == target)
