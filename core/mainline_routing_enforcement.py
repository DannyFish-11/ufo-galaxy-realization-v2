#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/mainline_routing_enforcement.py
======================================
Canonical mainline routing enforcement: capability gate on explicit device paths.

Problem addressed
-----------------
Prior to this module, the ``process()`` entry point in ``OpenClawd`` applied
capability-aware routing only when no explicit ``device_id`` was provided.
When a caller explicitly named a ``device_id``, capability validation was
silently skipped — the gate was effectively bypassed without any audit record.

This module provides:

1. Policy sentinels that make the enforcement contract machine-checkable.
2. :func:`audit_explicit_device_capabilities` — the canonical enforcement
   function that validates an explicit target device against
   ``required_capabilities`` and returns a structured
   :class:`ExplicitRouteCapabilityAudit` record.
3. :func:`enforce_explicit_route_capability_gate` — thin wrapper consumed
   by ``OpenClawd.process()`` that logs the audit record and raises or
   warns depending on the configured enforcement mode.

Design principles
-----------------
- **Additive only** — does not modify any other module.
- **Auditable, not silent** — every explicit-route capability mismatch
  produces a structured audit record that is visible in logs and returned
  to callers.  Silent degradation is explicitly prohibited by
  :data:`NO_SILENT_CAPABILITY_BYPASS_POLICY`.
- **Fail-open by default** — when capability information cannot be
  determined the function records ``INSUFFICIENT_DATA`` and allows routing
  to proceed (conservative fallback, not hard block).  Callers that want
  strict enforcement can set ``raise_on_mismatch=True``.
- **Capability gate is canonical** — the gate delegates to
  :mod:`core.capability_routing_gate` so there is a single authoritative
  evaluation path.

Public API
----------
Sentinels::

    MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY
    MAINLINE_ROUTING_ENFORCEMENT_PR_SENTINEL
    CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY
    NO_SILENT_CAPABILITY_BYPASS_POLICY
    EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_POLICY

Enumerations::

    ExplicitRouteVerdict

Data class::

    ExplicitRouteCapabilityAudit

Functions::

    audit_explicit_device_capabilities(...)  -> ExplicitRouteCapabilityAudit
    enforce_explicit_route_capability_gate(...)  -> ExplicitRouteCapabilityAudit
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

logger = logging.getLogger("Galaxy.MainlineRoutingEnforcement")

__all__ = [
    # Sentinels
    "MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY",
    "MAINLINE_ROUTING_ENFORCEMENT_PR_SENTINEL",
    "CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY",
    "NO_SILENT_CAPABILITY_BYPASS_POLICY",
    "EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_POLICY",
    "EXPLICIT_ROUTE_IS_EXCEPTION_PATH",
    "CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE",
    # Enumerations
    "ExplicitRouteVerdict",
    # Data class
    "ExplicitRouteCapabilityAudit",
    # Functions
    "audit_explicit_device_capabilities",
    "enforce_explicit_route_capability_gate",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY: str = (
    "MAINLINE_ROUTING_ENFORCEMENT_AUTHORITY_V1: "
    "core.mainline_routing_enforcement is the canonical enforcement layer "
    "that closes the explicit-device-id capability gate bypass gap.  "
    "All explicit-route capability validation must flow through this module."
)

MAINLINE_ROUTING_ENFORCEMENT_PR_SENTINEL: str = (
    "PR::ENFORCE_CANONICAL_MAINLINE_ROUTING_V1: "
    "This module was introduced to enforce the requirement that explicit "
    "device_id routing does NOT silently bypass the capability gate.  "
    "Removing or weakening this enforcement violates the mainline routing "
    "contract."
)

CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_POLICY: str = (
    "POLICY::CAPABILITY_GATE_ENFORCED_ON_EXPLICIT_ROUTING_V1: "
    "When a caller supplies both an explicit device_id AND required_capabilities, "
    "the capability gate MUST be consulted for that device.  "
    "The route may still proceed when capabilities cannot be confirmed "
    "(INSUFFICIENT_DATA), but the decision MUST be logged as an audited "
    "bypass rather than silently degrading."
)

NO_SILENT_CAPABILITY_BYPASS_POLICY: str = (
    "POLICY::NO_SILENT_CAPABILITY_BYPASS_V1: "
    "Silent capability bypass is prohibited on all mainline routing paths.  "
    "Every capability mismatch or data-insufficiency on an explicit routing "
    "decision MUST produce an ExplicitRouteCapabilityAudit record with "
    "verdict MISMATCH or INSUFFICIENT_DATA.  Callers must not suppress "
    "these records."
)

EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_POLICY: str = (
    "POLICY::EXPLICIT_ROUTE_BYPASS_REQUIRES_AUDIT_V1: "
    "When an explicit device_id route is allowed to proceed despite a "
    "capability mismatch or data gap, the routing event MUST be recorded "
    "with verdict AUDITED_BYPASS.  The record must include the device_id, "
    "the required_capabilities, and the reason for the bypass."
)

EXPLICIT_ROUTE_IS_EXCEPTION_PATH: str = (
    "POLICY::EXPLICIT_ROUTE_IS_EXCEPTION_PATH_V1: "
    "An explicit device_id in a cross-device dispatch request is the "
    "EXCEPTION PATH (override / debug / forced routing scenarios).  It is "
    "NOT the default main path.  The default main path is capability-driven "
    "selection via the capability graph.  Exception-path requests still run "
    "the capability gate and produce an audit record.  When the explicit "
    "target fails the capability gate, the system must reroute to a capable "
    "alternative or reject — it must NOT silently proceed with an incapable "
    "device.  Closes the structural gap where explicit device_id bypassed "
    "capability-aware routing in the default main path."
)

CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE: str = (
    "POLICY::CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_V1: "
    "Cross-device participant selection MUST default to capability-driven "
    "routing.  When required_capabilities is absent, capability inference "
    "from the tool/command name activates the gate automatically.  The "
    "system does NOT default to explicit device_id dispatch.  This policy "
    "is enforced in route_envelope() (capability inference before dispatch) "
    "and in process() (gate expanded to all intent types, not just "
    "device_control/task_manage).  See core.capability_aware_routing_default "
    "for the canonical enforcement implementation."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ExplicitRouteVerdict(str, Enum):
    """Outcome of capability validation for an explicit device routing decision.

    Attributes
    ----------
    CONFIRMED:
        The target device was confirmed to possess all required capabilities.
        Routing proceeds on the canonical path.
    MISMATCH:
        The target device was found and its capability list was readable, but
        one or more required capabilities are absent.
        Routing proceeds as an audited bypass (logged, not silent).
    INSUFFICIENT_DATA:
        Capability information for the target device could not be determined
        (device not found, capability list unreadable, or runtime layer
        unavailable).  Routing proceeds with degraded confidence.
    AUDITED_BYPASS:
        The route was allowed to proceed despite MISMATCH or INSUFFICIENT_DATA.
        The routing event is recorded so it is not silent.
    NO_REQUIREMENTS:
        No required_capabilities were specified; the gate is inactive for
        this routing decision.  Not an error condition.
    """

    CONFIRMED = "confirmed"
    MISMATCH = "mismatch"
    INSUFFICIENT_DATA = "insufficient_data"
    AUDITED_BYPASS = "audited_bypass"
    NO_REQUIREMENTS = "no_requirements"


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class ExplicitRouteCapabilityAudit:
    """Audit record for a capability gate evaluation on an explicit device route.

    Produced by :func:`audit_explicit_device_capabilities` and logged by
    :func:`enforce_explicit_route_capability_gate`.  Callers should surface
    this record through their normal observability stack so that capability
    mismatch events are discoverable without log scraping.
    """

    device_id: str
    required_capabilities: List[str]
    verdict: ExplicitRouteVerdict
    confirmed_capabilities: List[str] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "required_capabilities": self.required_capabilities,
            "verdict": self.verdict.value,
            "confirmed_capabilities": self.confirmed_capabilities,
            "missing_capabilities": self.missing_capabilities,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Core gate function
# ---------------------------------------------------------------------------


def _normalize_capability_value(cap: object) -> str:
    """Normalise a raw capability entry to a plain string.

    Capabilities stored in device registries may be plain strings, dicts with
    a ``"name"`` key, or other objects.  This helper normalises them so
    comparisons always work against plain strings.
    """
    if isinstance(cap, str):
        return cap
    if isinstance(cap, dict):
        return cap.get("name", "")
    return str(cap)


def audit_explicit_device_capabilities(
    device_id: str,
    required_capabilities: Sequence[str],
    *,
    device_capabilities: Optional[Sequence[str]] = None,
) -> ExplicitRouteCapabilityAudit:
    """Validate *device_id* against *required_capabilities* for explicit routing.

    This is the canonical enforcement function.  It replaces silent skip
    logic that previously allowed explicit-device-id paths to bypass the
    capability gate entirely.

    Parameters
    ----------
    device_id:
        The explicit target device identifier.
    required_capabilities:
        Capabilities the routing context requires.
    device_capabilities:
        Pre-loaded capability list for the device.  When ``None`` (default)
        the function attempts to read capabilities from the connection manager
        runtime.  When provided (e.g. in tests), runtime lookup is skipped.

    Returns
    -------
    ExplicitRouteCapabilityAudit
        Structured audit record with verdict.
    """
    req_caps = list(required_capabilities)

    if not req_caps:
        return ExplicitRouteCapabilityAudit(
            device_id=device_id,
            required_capabilities=[],
            verdict=ExplicitRouteVerdict.NO_REQUIREMENTS,
            reason="No required_capabilities specified; gate is inactive.",
        )

    # Attempt to resolve device capabilities from the runtime layer when not
    # supplied by the caller.
    resolved_caps: Optional[List[str]] = (
        list(device_capabilities) if device_capabilities is not None else None
    )
    if resolved_caps is None:
        try:
            # Lazy import: core.routes._shared uses FastAPI app state and may
            # not be importable in all test environments or early-boot contexts.
            # Keeping the import here avoids circular dependencies and silent
            # import failures at module load time.
            from core.routes._shared import connection_manager  # noqa: PLC0415

            all_devices = connection_manager.get_all_devices()
            info = all_devices.get(device_id)
            if info is not None:
                raw_caps = info.get("capabilities", [])
                if isinstance(raw_caps, list):
                    resolved_caps = [
                        _normalize_capability_value(c) for c in raw_caps
                    ]
                else:
                    resolved_caps = []
        except Exception as _lookup_exc:
            logger.debug(
                "audit_explicit_device_capabilities: runtime lookup failed for %s: %s",
                device_id,
                _lookup_exc,
            )
            resolved_caps = None

    if resolved_caps is None:
        return ExplicitRouteCapabilityAudit(
            device_id=device_id,
            required_capabilities=req_caps,
            verdict=ExplicitRouteVerdict.INSUFFICIENT_DATA,
            reason=(
                "Device capability list could not be resolved from the runtime layer.  "
                "Route proceeds as degraded-confidence audited bypass."
            ),
        )

    # Delegate hard evaluation to the canonical capability routing gate.
    try:
        from core.capability_routing_gate import device_meets_capabilities, CapabilityGateVerdict

        gate_result = device_meets_capabilities(
            device_id=device_id,
            device_capabilities=resolved_caps,
            required_capabilities=req_caps,
        )

        if gate_result.verdict == CapabilityGateVerdict.PASS:
            return ExplicitRouteCapabilityAudit(
                device_id=device_id,
                required_capabilities=req_caps,
                verdict=ExplicitRouteVerdict.CONFIRMED,
                confirmed_capabilities=resolved_caps,
                missing_capabilities=[],
                reason="All required capabilities confirmed via capability routing gate.",
            )
        elif gate_result.verdict == CapabilityGateVerdict.INSUFFICIENT_DATA:
            return ExplicitRouteCapabilityAudit(
                device_id=device_id,
                required_capabilities=req_caps,
                verdict=ExplicitRouteVerdict.INSUFFICIENT_DATA,
                confirmed_capabilities=resolved_caps,
                reason="Capability gate returned INSUFFICIENT_DATA for this device.",
            )
        else:
            # FAIL / other non-pass verdict
            confirmed = [c for c in req_caps if c in resolved_caps]
            missing = [c for c in req_caps if c not in resolved_caps]
            return ExplicitRouteCapabilityAudit(
                device_id=device_id,
                required_capabilities=req_caps,
                verdict=ExplicitRouteVerdict.MISMATCH,
                confirmed_capabilities=confirmed,
                missing_capabilities=missing,
                reason=(
                    f"Capability gate verdict={gate_result.verdict.value}: "
                    f"missing={missing}"
                ),
            )
    except ImportError as _imp_exc:
        logger.debug(
            "audit_explicit_device_capabilities: capability_routing_gate unavailable: %s",
            _imp_exc,
        )
        # Fallback: simple set membership check
        cap_set = set(resolved_caps)
        missing = [c for c in req_caps if c not in cap_set]
        if not missing:
            return ExplicitRouteCapabilityAudit(
                device_id=device_id,
                required_capabilities=req_caps,
                verdict=ExplicitRouteVerdict.CONFIRMED,
                confirmed_capabilities=resolved_caps,
                reason="All required capabilities confirmed via fallback set check.",
            )
        return ExplicitRouteCapabilityAudit(
            device_id=device_id,
            required_capabilities=req_caps,
            verdict=ExplicitRouteVerdict.MISMATCH,
            confirmed_capabilities=[c for c in req_caps if c in cap_set],
            missing_capabilities=missing,
            reason=f"Fallback check: missing capabilities={missing}",
        )


def enforce_explicit_route_capability_gate(
    device_id: str,
    required_capabilities: Sequence[str],
    *,
    device_capabilities: Optional[Sequence[str]] = None,
    raise_on_mismatch: bool = False,
    calling_site: str = "unknown",
) -> ExplicitRouteCapabilityAudit:
    """Enforce the capability gate for an explicit device routing decision.

    Wraps :func:`audit_explicit_device_capabilities` with structured logging
    and optional raise-on-mismatch semantics.  This is the function called by
    ``OpenClawd.process()`` when an explicit ``device_id`` is provided
    alongside ``required_capabilities``.

    Parameters
    ----------
    device_id:
        Explicit target device identifier.
    required_capabilities:
        Required capability strings.
    device_capabilities:
        Pre-loaded device capabilities (bypasses runtime lookup; mainly for
        testing).
    raise_on_mismatch:
        When ``True``, raises ``CapabilityMismatchError`` on MISMATCH verdict.
        Default ``False`` (audited bypass, not hard reject) to avoid breaking
        callers that depend on best-effort routing.
    calling_site:
        Human-readable identifier for the callsite, used in log records.

    Returns
    -------
    ExplicitRouteCapabilityAudit
        The audit record.  Callers should attach this to their response
        metadata so the routing decision is observable.
    """
    audit = audit_explicit_device_capabilities(
        device_id=device_id,
        required_capabilities=required_capabilities,
        device_capabilities=device_capabilities,
    )

    if audit.verdict == ExplicitRouteVerdict.NO_REQUIREMENTS:
        # Gate inactive — nothing to log at warning level.
        return audit

    if audit.verdict == ExplicitRouteVerdict.CONFIRMED:
        logger.debug(
            "[%s] explicit-route capability gate: device=%s CONFIRMED for caps=%s",
            calling_site,
            device_id,
            list(required_capabilities),
        )
        return audit

    if audit.verdict == ExplicitRouteVerdict.MISMATCH:
        log_msg = (
            "[%s] explicit-route capability gate: device=%s MISMATCH "
            "required=%s missing=%s — routing as AUDITED_BYPASS "
            "(policy: %s)"
        )
        logger.warning(
            log_msg,
            calling_site,
            device_id,
            list(required_capabilities),
            audit.missing_capabilities,
            NO_SILENT_CAPABILITY_BYPASS_POLICY,
        )
        if raise_on_mismatch:
            # Raise with original MISMATCH verdict so the caller receives
            # the real verdict, not the post-mutation AUDITED_BYPASS.
            raise CapabilityMismatchError(audit)
        audit.verdict = ExplicitRouteVerdict.AUDITED_BYPASS
        audit.reason = f"Audited bypass: {audit.reason}"
        return audit

    if audit.verdict == ExplicitRouteVerdict.INSUFFICIENT_DATA:
        logger.warning(
            "[%s] explicit-route capability gate: device=%s INSUFFICIENT_DATA "
            "for caps=%s — routing as AUDITED_BYPASS (policy: %s)",
            calling_site,
            device_id,
            list(required_capabilities),
            NO_SILENT_CAPABILITY_BYPASS_POLICY,
        )
        audit.verdict = ExplicitRouteVerdict.AUDITED_BYPASS
        audit.reason = f"Audited bypass (insufficient data): {audit.reason}"
        return audit

    return audit


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class CapabilityMismatchError(Exception):
    """Raised by :func:`enforce_explicit_route_capability_gate` when
    ``raise_on_mismatch=True`` and the verdict is MISMATCH."""

    def __init__(self, audit: ExplicitRouteCapabilityAudit) -> None:
        self.audit = audit
        super().__init__(
            f"CapabilityMismatch: device={audit.device_id!r} "
            f"missing={audit.missing_capabilities!r}"
        )
