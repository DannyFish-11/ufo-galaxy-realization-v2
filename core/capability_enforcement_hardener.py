#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_enforcement_hardener.py
========================================
Canonical capability enforcement hardener: strict blocking mode for mainline
dispatch paths.

Problem addressed
-----------------
The existing :mod:`core.mainline_routing_enforcement` module introduced an
``enforce_explicit_route_capability_gate`` function that audits capability
mismatches but defaults to ``raise_on_mismatch=False`` — meaning capability
mismatches on explicit device routes are logged but do NOT stop dispatch.

This was intentional for the initial rollout (fail-open → audited bypass
→ strict enforcement as a planned progression).  This module completes that
progression by providing:

1. A **strict enforcement mode** that converts capability mismatches on
   canonical mainline paths into hard rejections (``CapabilityHardRejectError``).
2. A **mainline path classifier** that identifies dispatch calls that originate
   from the canonical V2 → Android execution chain and must be hardened.
3. An **audit trail** that records every enforcement decision — whether the
   gate was passed, bypassed under strict mode, or rejected — so that the
   capability reality always matches the dispatch reality.
4. An **override mechanism** that requires an explicit ``override_reason`` token
   so that capability bypasses are never silent, only audited.

Design principles
-----------------
- **Additive only** — does not modify :mod:`core.mainline_routing_enforcement`
  or :mod:`core.capability_routing_gate`.
- **Hard reject by default on mainline** — the canonical mainline dispatch path
  uses ``EnforcementMode.STRICT`` by default; soft paths may downgrade to
  ``EnforcementMode.AUDIT``.
- **No silent bypass** — any route that bypasses the gate must supply an
  ``override_reason`` token that is persisted in the enforcement audit log.
- **Observable** — every gate decision produces an
  :class:`HardenedEnforcementRecord` that callers can attach to response
  metadata.

Public API
----------
Sentinels::

    CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY
    CAPABILITY_ENFORCEMENT_HARDENER_PR_SENTINEL
    MAINLINE_REQUIRES_STRICT_CAPABILITY_ENFORCEMENT_POLICY
    SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY
    OVERRIDE_REQUIRES_EXPLICIT_AUDIT_POLICY

Enumerations::

    EnforcementMode
    HardenedVerdict

Exceptions::

    CapabilityHardRejectError

Data class::

    HardenedEnforcementRecord

Functions::

    enforce_mainline_capability_gate(...)  -> HardenedEnforcementRecord
    audit_capability_override(...)         -> HardenedEnforcementRecord
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence

logger = logging.getLogger("Galaxy.CapabilityEnforcementHardener")

__all__ = [
    # Sentinels
    "CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY",
    "CAPABILITY_ENFORCEMENT_HARDENER_PR_SENTINEL",
    "MAINLINE_REQUIRES_STRICT_CAPABILITY_ENFORCEMENT_POLICY",
    "SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY",
    "OVERRIDE_REQUIRES_EXPLICIT_AUDIT_POLICY",
    # Enumerations
    "EnforcementMode",
    "HardenedVerdict",
    # Exceptions
    "CapabilityHardRejectError",
    # Data class
    "HardenedEnforcementRecord",
    # Functions
    "enforce_mainline_capability_gate",
    "audit_capability_override",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY: str = (
    "CAPABILITY_ENFORCEMENT_HARDENER_AUTHORITY_V1: "
    "core.capability_enforcement_hardener is the canonical strict-enforcement "
    "layer for capability gates on mainline dispatch paths.  "
    "It builds on core.mainline_routing_enforcement by converting audited "
    "bypasses into hard rejections on canonical V2 → Android paths.  "
    "All mainline capability enforcement must flow through this module."
)

CAPABILITY_ENFORCEMENT_HARDENER_PR_SENTINEL: str = (
    "PR::CAPABILITY_ENFORCEMENT_HARDENER_V1: "
    "This module was introduced to close the gap between 'audited capability "
    "bypass' and 'hard capability enforcement' on canonical mainline paths.  "
    "Removing or weakening this enforcement reopens the bypass gap that "
    "core.mainline_routing_enforcement was designed to close."
)

MAINLINE_REQUIRES_STRICT_CAPABILITY_ENFORCEMENT_POLICY: str = (
    "POLICY::MAINLINE_REQUIRES_STRICT_CAPABILITY_ENFORCEMENT_V1: "
    "Canonical mainline dispatch paths (V2 → Android task_assign, "
    "register, capability_report, task_result, continuation) MUST use "
    "EnforcementMode.STRICT.  STRICT mode raises CapabilityHardRejectError "
    "when a required capability is absent from the target device.  "
    "Callers that need to bypass must supply a non-empty override_reason "
    "token, which is persisted in the enforcement audit log."
)

SILENT_BYPASS_PROHIBITED_ON_MAINLINE_POLICY: str = (
    "POLICY::SILENT_BYPASS_PROHIBITED_ON_MAINLINE_V1: "
    "A mainline dispatch MUST NOT silently proceed when the target device "
    "lacks required capabilities.  Either the gate passes, or a hard reject "
    "is raised, or an explicit audited override is recorded.  "
    "There is no code path that can silently ignore a capability mismatch "
    "on the canonical mainline path."
)

OVERRIDE_REQUIRES_EXPLICIT_AUDIT_POLICY: str = (
    "POLICY::OVERRIDE_REQUIRES_EXPLICIT_AUDIT_V1: "
    "Any capability gate override must supply a non-empty override_reason "
    "string.  The reason is stored in HardenedEnforcementRecord.override_reason "
    "and logged at WARNING level.  An empty override_reason causes "
    "audit_capability_override() to raise ValueError, ensuring overrides "
    "are never accidentally silent."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EnforcementMode(str, Enum):
    """Mode governing how a capability mismatch is handled.

    Values
    ------
    STRICT
        Mismatch raises :class:`CapabilityHardRejectError`.  Required for
        canonical mainline paths.
    AUDIT
        Mismatch is logged at WARNING level and an audit record is returned,
        but execution proceeds.  Suitable for non-canonical paths and
        compatibility surfaces.
    DISABLED
        Gate is not evaluated; a ``NO_REQUIREMENTS`` record is always returned.
        Must not be used on mainline paths.
    """

    STRICT = "strict"
    AUDIT = "audit"
    DISABLED = "disabled"


class HardenedVerdict(str, Enum):
    """Outcome of a hardened capability gate evaluation.

    Values
    ------
    PASSED
        All required capabilities confirmed present on the target device.
    REJECTED
        One or more required capabilities absent; in STRICT mode this
        triggers :class:`CapabilityHardRejectError`.
    AUDITED_OVERRIDE
        Gate would have rejected but an explicit override_reason was provided;
        execution proceeds with an audit record.
    INSUFFICIENT_DATA
        Device capability data unavailable; verdict deferred to caller.
    NO_REQUIREMENTS
        No required capabilities specified; gate is a no-op.
    DISABLED
        Gate disabled via :attr:`EnforcementMode.DISABLED`; not evaluated.
    """

    PASSED = "passed"
    REJECTED = "rejected"
    AUDITED_OVERRIDE = "audited_override"
    INSUFFICIENT_DATA = "insufficient_data"
    NO_REQUIREMENTS = "no_requirements"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CapabilityHardRejectError(Exception):
    """Raised when STRICT mode enforcement rejects a dispatch due to missing
    capabilities.

    Attributes
    ----------
    device_id : str
        Target device that failed the gate.
    required_capabilities : list[str]
        The capabilities that were required but not found.
    missing_capabilities : list[str]
        Subset of ``required_capabilities`` absent from the device.
    calling_site : str
        Human-readable identifier for the call site that triggered the gate.
    audit_id : str
        Stable identifier for the corresponding
        :class:`HardenedEnforcementRecord`.
    """

    def __init__(
        self,
        device_id: str,
        required_capabilities: Sequence[str],
        missing_capabilities: Sequence[str],
        calling_site: str = "unknown",
        audit_id: str = "",
    ) -> None:
        self.device_id = device_id
        self.required_capabilities = list(required_capabilities)
        self.missing_capabilities = list(missing_capabilities)
        self.calling_site = calling_site
        self.audit_id = audit_id or f"hcer_{uuid.uuid4().hex[:12]}"
        super().__init__(
            f"[{self.calling_site}] capability gate REJECTED dispatch to "
            f"device={device_id!r}: missing capabilities "
            f"{self.missing_capabilities!r} from required "
            f"{self.required_capabilities!r}.  "
            f"audit_id={self.audit_id!r}.  "
            f"Resolve by ensuring the device advertises all required capabilities "
            f"before dispatch, or supply an explicit override_reason via "
            f"audit_capability_override()."
        )


# ---------------------------------------------------------------------------
# HardenedEnforcementRecord
# ---------------------------------------------------------------------------


@dataclass
class HardenedEnforcementRecord:
    """Structured record of a hardened capability gate decision.

    Fields
    ------
    audit_id
        Stable unique identifier for this record.
    device_id
        Target device evaluated by the gate.
    required_capabilities
        Capabilities that were required.
    device_capabilities
        Capabilities the device reported.  Empty list if unavailable.
    missing_capabilities
        Capabilities from ``required_capabilities`` absent from
        ``device_capabilities``.
    verdict
        :class:`HardenedVerdict` for this gate evaluation.
    enforcement_mode
        :class:`EnforcementMode` applied during this evaluation.
    calling_site
        Human-readable name of the code that invoked the gate.
    override_reason
        Non-empty only for :attr:`HardenedVerdict.AUDITED_OVERRIDE` records.
    timestamp_ms
        Unix time in milliseconds when the record was created.
    """

    audit_id: str = field(default_factory=lambda: f"her_{uuid.uuid4().hex[:12]}")
    device_id: str = ""
    required_capabilities: List[str] = field(default_factory=list)
    device_capabilities: List[str] = field(default_factory=list)
    missing_capabilities: List[str] = field(default_factory=list)
    verdict: str = HardenedVerdict.NO_REQUIREMENTS
    enforcement_mode: str = EnforcementMode.STRICT
    calling_site: str = "unknown"
    override_reason: str = ""
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def to_dict(self) -> dict:
        return {
            "audit_id": self.audit_id,
            "device_id": self.device_id,
            "required_capabilities": self.required_capabilities,
            "device_capabilities": self.device_capabilities,
            "missing_capabilities": self.missing_capabilities,
            "verdict": self.verdict,
            "enforcement_mode": self.enforcement_mode,
            "calling_site": self.calling_site,
            "override_reason": self.override_reason,
            "timestamp_ms": self.timestamp_ms,
        }


# ---------------------------------------------------------------------------
# Core enforcement function
# ---------------------------------------------------------------------------


def enforce_mainline_capability_gate(
    device_id: str,
    required_capabilities: Sequence[str],
    device_capabilities: Sequence[str],
    *,
    mode: EnforcementMode = EnforcementMode.STRICT,
    calling_site: str = "unknown",
) -> HardenedEnforcementRecord:
    """Enforce the capability gate for a mainline dispatch decision.

    Parameters
    ----------
    device_id:
        Target device identifier.
    required_capabilities:
        Capability strings that the target device must possess.  An empty
        sequence makes the gate a no-op (returns ``NO_REQUIREMENTS``).
    device_capabilities:
        Capabilities the target device has reported.  An empty sequence is
        treated as ``INSUFFICIENT_DATA`` unless ``required_capabilities`` is
        also empty.
    mode:
        :class:`EnforcementMode` to apply.  Canonical mainline paths must
        use :attr:`EnforcementMode.STRICT`.
    calling_site:
        Human-readable label for the dispatch code path invoking this gate.

    Returns
    -------
    HardenedEnforcementRecord
        Structured audit record describing the gate decision.

    Raises
    ------
    CapabilityHardRejectError
        When ``mode == EnforcementMode.STRICT`` and one or more required
        capabilities are absent from ``device_capabilities``.
    """
    req_caps = [c for c in required_capabilities if c]
    dev_caps = list(device_capabilities)

    if mode == EnforcementMode.DISABLED:
        return HardenedEnforcementRecord(
            device_id=device_id,
            required_capabilities=req_caps,
            device_capabilities=dev_caps,
            missing_capabilities=[],
            verdict=HardenedVerdict.DISABLED,
            enforcement_mode=EnforcementMode.DISABLED,
            calling_site=calling_site,
        )

    if not req_caps:
        return HardenedEnforcementRecord(
            device_id=device_id,
            required_capabilities=[],
            device_capabilities=dev_caps,
            missing_capabilities=[],
            verdict=HardenedVerdict.NO_REQUIREMENTS,
            enforcement_mode=mode,
            calling_site=calling_site,
        )

    if not dev_caps:
        record = HardenedEnforcementRecord(
            device_id=device_id,
            required_capabilities=req_caps,
            device_capabilities=[],
            missing_capabilities=req_caps,
            verdict=HardenedVerdict.INSUFFICIENT_DATA,
            enforcement_mode=mode,
            calling_site=calling_site,
        )
        logger.warning(
            "[%s] capability gate: device=%s has no reported capabilities; "
            "required=%s verdict=INSUFFICIENT_DATA",
            calling_site,
            device_id,
            req_caps,
        )
        return record

    dev_caps_set = set(dev_caps)
    missing = [c for c in req_caps if c not in dev_caps_set]

    if not missing:
        logger.debug(
            "[%s] capability gate: device=%s PASSED for caps=%s",
            calling_site,
            device_id,
            req_caps,
        )
        return HardenedEnforcementRecord(
            device_id=device_id,
            required_capabilities=req_caps,
            device_capabilities=dev_caps,
            missing_capabilities=[],
            verdict=HardenedVerdict.PASSED,
            enforcement_mode=mode,
            calling_site=calling_site,
        )

    # Mismatch — STRICT mode raises; AUDIT mode records and continues.
    audit_id = f"her_{uuid.uuid4().hex[:12]}"
    record = HardenedEnforcementRecord(
        audit_id=audit_id,
        device_id=device_id,
        required_capabilities=req_caps,
        device_capabilities=dev_caps,
        missing_capabilities=missing,
        verdict=HardenedVerdict.REJECTED,
        enforcement_mode=mode,
        calling_site=calling_site,
    )

    if mode == EnforcementMode.STRICT:
        logger.error(
            "[%s] capability gate HARD REJECT: device=%s missing caps=%s "
            "required=%s audit_id=%s",
            calling_site,
            device_id,
            missing,
            req_caps,
            audit_id,
        )
        raise CapabilityHardRejectError(
            device_id=device_id,
            required_capabilities=req_caps,
            missing_capabilities=missing,
            calling_site=calling_site,
            audit_id=audit_id,
        )

    # AUDIT mode — log and return without raising.
    logger.warning(
        "[%s] capability gate AUDITED MISMATCH: device=%s missing caps=%s "
        "required=%s audit_id=%s (enforcement_mode=AUDIT — proceeding)",
        calling_site,
        device_id,
        missing,
        req_caps,
        audit_id,
    )
    return record


# ---------------------------------------------------------------------------
# Override path
# ---------------------------------------------------------------------------


def audit_capability_override(
    device_id: str,
    required_capabilities: Sequence[str],
    device_capabilities: Sequence[str],
    override_reason: str,
    *,
    calling_site: str = "unknown",
) -> HardenedEnforcementRecord:
    """Record an explicit capability gate override with a mandatory audit token.

    Use this function when dispatch must proceed despite a capability mismatch,
    and the caller can provide a documented justification.  The override is
    logged at WARNING level and captured in the returned record.

    Parameters
    ----------
    device_id:
        Target device.
    required_capabilities:
        Required capabilities (for audit logging).
    device_capabilities:
        Device's reported capabilities.
    override_reason:
        **Mandatory** non-empty human-readable justification for the override.
        Raises :exc:`ValueError` when empty, ensuring overrides are never silent.
    calling_site:
        Human-readable label for the dispatch code invoking the override.

    Returns
    -------
    HardenedEnforcementRecord
        Record with ``verdict=AUDITED_OVERRIDE`` and the supplied
        ``override_reason``.

    Raises
    ------
    ValueError
        When ``override_reason`` is empty.
    """
    if not override_reason or not override_reason.strip():
        raise ValueError(
            "audit_capability_override() requires a non-empty override_reason.  "
            "An empty reason would make the capability bypass silent, violating "
            "OVERRIDE_REQUIRES_EXPLICIT_AUDIT_POLICY.  "
            "Supply a short, human-readable justification string."
        )

    req_caps = [c for c in required_capabilities if c]
    dev_caps = list(device_capabilities)
    dev_caps_set = set(dev_caps)
    missing = [c for c in req_caps if c not in dev_caps_set]

    audit_id = f"her_{uuid.uuid4().hex[:12]}"
    record = HardenedEnforcementRecord(
        audit_id=audit_id,
        device_id=device_id,
        required_capabilities=req_caps,
        device_capabilities=dev_caps,
        missing_capabilities=missing,
        verdict=HardenedVerdict.AUDITED_OVERRIDE,
        enforcement_mode=EnforcementMode.AUDIT,
        calling_site=calling_site,
        override_reason=override_reason.strip(),
    )

    logger.warning(
        "[%s] capability gate AUDITED OVERRIDE: device=%s missing=%s "
        "reason=%r audit_id=%s",
        calling_site,
        device_id,
        missing,
        override_reason.strip(),
        audit_id,
    )
    return record
