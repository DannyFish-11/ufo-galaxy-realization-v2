"""
core/admissibility_chain.py
============================
Canonical admissibility chain for device eligibility in cross-device execution.

Defines and enforces the three-layer admissibility hierarchy:

  Layer 1 — Readiness   (``core.device_readiness``)
      Question: Is the device reachable at the transport layer?
      Truth:    registered + online + connected + routable.
      Authority: ``DEVICE_READINESS_AUTHORITY`` / ``DEVICE_READINESS_LAYER_V2``

  Layer 2 — Participation  (``core.device_participation``)
      Question: Is the device eligible to participate in orchestration/session?
      Truth:    Layer-1 ready AND orchestration_eligible (from selector).
      Authority: ``DEVICE_PARTICIPATION_AUTHORITY`` / ``DEVICE_PARTICIPATION_LAYER_V2``

  Layer 3 — Target Validation  (``core.target_device_validator``)
      Question: For a specific request, is this device a valid target?
      Truth:    Layer-1 ready AND Layer-2 eligible AND capability-matched.
      Authority: ``TARGET_DEVICE_VALIDATOR_AUTHORITY`` / ``TARGET_DEVICE_VALIDATOR_V2``

Ordering rules
--------------
- Each layer *consumes* lower-layer outputs — it must not re-derive readiness
  or eligibility from parallel sources.
- Higher layers must not silently substitute for lower-layer authority.
- Mesh/session summaries are *enrichment* data; they must not override
  readiness or eligibility truth from Layers 1–2.

Failure reason constants
------------------------
Use these canonical strings in ``reasons`` lists throughout the chain so that
callers can reliably pattern-match on failure causes regardless of which layer
raised the reason.

Public API
----------
Sentinels:
    ADMISSIBILITY_CHAIN_AUTHORITY
    ADMISSIBILITY_LAYER_READINESS
    ADMISSIBILITY_LAYER_PARTICIPATION
    ADMISSIBILITY_LAYER_TARGET_VALIDATION

Reason constants (canonical failure strings):
    REASON_EMPTY_DEVICE_ID
    REASON_NOT_REGISTERED
    REASON_NOT_READY
    REASON_NO_ROUTE
    REASON_NOT_ELIGIBLE
    REASON_CAPABILITY_MISMATCH
    REASON_SESSION_RESTRICTION
    REASON_READINESS_UNAVAILABLE
    REASON_PARTICIPATION_UNAVAILABLE
"""

from __future__ import annotations

__all__ = [
    # Sentinels
    "ADMISSIBILITY_CHAIN_AUTHORITY",
    "ADMISSIBILITY_LAYER_READINESS",
    "ADMISSIBILITY_LAYER_PARTICIPATION",
    "ADMISSIBILITY_LAYER_TARGET_VALIDATION",
    # Canonical failure reason constants
    "REASON_EMPTY_DEVICE_ID",
    "REASON_NOT_REGISTERED",
    "REASON_NOT_READY",
    "REASON_NO_ROUTE",
    "REASON_NOT_ELIGIBLE",
    "REASON_CAPABILITY_MISMATCH",
    "REASON_SESSION_RESTRICTION",
    "REASON_READINESS_UNAVAILABLE",
    "REASON_PARTICIPATION_UNAVAILABLE",
]

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

#: Identifies this module as the canonical admissibility-chain definition.
ADMISSIBILITY_CHAIN_AUTHORITY: str = "ADMISSIBILITY_CHAIN_V1"

# ---------------------------------------------------------------------------
# Layer position constants
# ---------------------------------------------------------------------------

#: Layer 1 — transport/presence feasibility (core.device_readiness).
ADMISSIBILITY_LAYER_READINESS: int = 1

#: Layer 2 — orchestration/session eligibility (core.device_participation).
ADMISSIBILITY_LAYER_PARTICIPATION: int = 2

#: Layer 3 — request-specific target admissibility (core.target_device_validator).
ADMISSIBILITY_LAYER_TARGET_VALIDATION: int = 3

# ---------------------------------------------------------------------------
# Canonical failure reason constants
# ---------------------------------------------------------------------------
# These are the canonical reason strings used throughout the admissibility
# chain.  Callers can reliably match on these values to distinguish failure
# classes without parsing free-form text.

#: Device identifier was empty or whitespace-only.
REASON_EMPTY_DEVICE_ID: str = "not-registered:empty-device-id"

#: Device is unknown to the canonical registry.
REASON_NOT_REGISTERED: str = "not-registered"

#: Device is registered but not ready (offline / disconnected / unroutable).
REASON_NOT_READY: str = "not-ready"

#: Device has no canonical transport route (direct WS, UCM, or relay).
REASON_NO_ROUTE: str = "no-route"

#: Device is not eligible for orchestration/session participation.
REASON_NOT_ELIGIBLE: str = "not-eligible"

#: Device does not satisfy the required capability set.
REASON_CAPABILITY_MISMATCH: str = "capability-mismatch"

#: Device is excluded by session or group restriction.
REASON_SESSION_RESTRICTION: str = "session-restriction"

#: The canonical readiness module could not be consulted.
REASON_READINESS_UNAVAILABLE: str = "readiness-unavailable"

#: The canonical participation module could not be consulted.
REASON_PARTICIPATION_UNAVAILABLE: str = "participation-unavailable"
