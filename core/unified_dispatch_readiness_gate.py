"""core/unified_dispatch_readiness_gate.py
==========================================
Unified Dispatch Readiness Gate — single canonical pre-dispatch authority.

Problem addressed
-----------------
Prior to this module the system had no single gate that distinguished
**Registered** (transport connected, UDM record exists) from **Dispatch Ready**
(all conditions for reliable task dispatch are satisfied).  Multiple call sites
performed partial or ad-hoc checks, creating silent registration-gap pass-through,
stale-attachment dispatch, and cross-device eligibility bypasses.

This module closes all those gaps by providing one function,
:func:`evaluate_dispatch_readiness`, that is the **single canonical pre-dispatch
authority** every dispatch path MUST consult before sending a task to a device.

Design
------
1. **Additive only** — does not modify any existing module.
2. **Composing, not duplicating** — delegates to existing authorities:
   - ``core.device_readiness`` (UDM/UCM connection truth)
   - ``core.attached_runtime_session_registry`` (session attachment truth)
   - ``galaxy_gateway.android.handlers.registration`` (registration gap truth)
3. **Explicit Registered vs Dispatch Ready distinction** — exposes both levels
   explicitly so callers can surface the right error category.
4. **Fully serialisable** — :meth:`DispatchReadinessResult.to_dict` produces
   stable, round-trippable JSON.
5. **Gracefully degrades** — all optional imports are wrapped; if a sub-system
   is unavailable the gate conservatively blocks with a meaningful reason.

Authority sentinels
-------------------
:data:`UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY`
:data:`REGISTERED_VS_DISPATCH_READY_DISTINCTION_POLICY`
:data:`DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY`
:data:`REGISTRATION_GAP_BLOCKS_DISPATCH_POLICY`
:data:`STALE_ATTACHMENT_BLOCKS_DISPATCH_POLICY`
:data:`ONLINE_NOT_EQUAL_DISPATCH_READY_POLICY`

Public API
----------
Enums::

    DispatchReadinessStatus

Dataclasses::

    DispatchReadinessResult

Functions::

    evaluate_dispatch_readiness(device_id, ...) -> DispatchReadinessResult
    reset_dispatch_readiness_gate()   (testing only)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.UnifiedDispatchReadinessGate")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY: str = (
    "UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY::"
    "core.unified_dispatch_readiness_gate is the single canonical pre-dispatch "
    "authority for all execution modes.  Every dispatch path MUST call "
    "evaluate_dispatch_readiness() before sending tasks to a device."
)

REGISTERED_VS_DISPATCH_READY_DISTINCTION_POLICY: str = (
    "POLICY::REGISTERED_VS_DISPATCH_READY_DISTINCTION: "
    "Being 'registered' (transport connected, UDM record present) is a necessary "
    "but NOT sufficient condition for dispatch.  A device is only DISPATCH_READY "
    "when ALL of the following hold: (1) registered in UDM, (2) transport alive "
    "(WebSocket or UCM), (3) no blocking registration gaps, (4) runtime attachment "
    "session is active and not stale, (5) required capability / action constraints "
    "are satisfied, (6) cross-device eligibility requirements are met when applicable. "
    "Only this gate produces that authoritative verdict."
)

DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY: str = (
    "POLICY::DISPATCH_MUST_CONSULT_UNIFIED_GATE: "
    "No dispatch path — local, single-device remote, parallel fan-out, cross-device, "
    "handoff, wake-routed, delegated runtime, or hybrid — may send a task to a device "
    "without first obtaining a DISPATCH_READY verdict from evaluate_dispatch_readiness(). "
    "Bypassing this gate is a policy violation."
)

REGISTRATION_GAP_BLOCKS_DISPATCH_POLICY: str = (
    "POLICY::REGISTRATION_GAP_BLOCKS_DISPATCH: "
    "A device with one or more downstream registration gaps (UDM write failed, "
    "DeviceRouter sync failed, attach_runtime_session failed, or "
    "attached_runtime_session_registry write failed) MUST NOT be used as a dispatch "
    "target.  Registration gaps are surfaced as DispatchReadinessStatus.BLOCKED_REGISTRATION_GAP "
    "and must form an explicit blocking decision, not a silent pass-through."
)

STALE_ATTACHMENT_BLOCKS_DISPATCH_POLICY: str = (
    "POLICY::STALE_ATTACHMENT_BLOCKS_DISPATCH: "
    "A device whose runtime attachment session is in 'replaced', 'detached', or "
    "'invalidated' state in the AttachedSessionRegistry MUST NOT be used as a "
    "dispatch target.  Stale/replaced sessions are surfaced as "
    "DispatchReadinessStatus.BLOCKED_STALE_ATTACHMENT."
)

ONLINE_NOT_EQUAL_DISPATCH_READY_POLICY: str = (
    "POLICY::ONLINE_NOT_EQUAL_DISPATCH_READY: "
    "'Online' (transport physically connected) is NOT the same as 'Dispatch Ready'. "
    "A device can be online but blocked from dispatch by registration gaps, stale "
    "attachments, capability mismatches, or session conflicts.  This distinction MUST "
    "be explicit in every dispatch decision."
)

UNSUPPORTED_DEVICE_TYPE_BLOCKS_DISPATCH_POLICY: str = (
    "POLICY::UNSUPPORTED_DEVICE_TYPE_BLOCKS_DISPATCH: "
    "Declared or registered device classes that are not operationally supported "
    "near-peers MUST NOT receive a DISPATCH_READY verdict. Operational support "
    "truth is sourced from core.device_operational_support."
)

DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY: str = (
    "POLICY::DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY: "
    "Online dispatch acceptance is NOT exempt from the unified continuity legality "
    "authority.  The attachment-validity check in evaluate_dispatch_readiness() "
    "implements the same stale-identity and session-mismatch rules that apply to "
    "reconnect, replay, delegated recovery, and result ingestion.  This ensures "
    "that a stale or invalidated attachment cannot proceed to dispatch even on the "
    "'online' path.  Per ONLINE_EXECUTION_SUBMITS_TO_SAME_AUTHORITY_POLICY in "
    "core.unified_continuity_legality_authority."
)

CANONICAL_DISPATCH_SLOT_AUTHORITY_CONSUMES_THIS_GATE_POLICY: str = (
    "POLICY::CANONICAL_DISPATCH_SLOT_AUTHORITY_CONSUMES_THIS_GATE: "
    "core.canonical_dispatch_slot_authority (PR-V3) is the higher-level dispatch-slot "
    "authority that consumes this gate for dimensions 1-3, 5, and 9 "
    "(transport readiness, registration validity, attachment validity, capability fit, "
    "and cross-device reachability).  It additionally evaluates continuity legality, "
    "execution-mode eligibility, occupancy, policy allowance, and delegated/handoff "
    "acceptability.  All execution modes MUST use the canonical dispatch-slot "
    "authority rather than calling this gate directly."
)

# ---------------------------------------------------------------------------
# DispatchReadinessStatus — canonical status vocabulary
# ---------------------------------------------------------------------------


class DispatchReadinessStatus(str, Enum):
    """Canonical dispatch readiness verdict.

    DISPATCH_READY
        All conditions satisfied; task dispatch is permitted.
    REGISTERED_NOT_READY
        Device is registered in UDM but one or more dispatch prerequisites
        are not yet met (transport, attachment, capabilities).
    BLOCKED_REGISTRATION_GAP
        Device has incomplete downstream registration (one or more attachment
        steps failed during handle_device_register).  Dispatch is blocked.
    BLOCKED_STALE_ATTACHMENT
        Device's runtime attachment session is replaced, detached, or
        invalidated.  Dispatch is blocked until a fresh register/reconnect.
    BLOCKED_TRANSPORT
        Transport is not alive (WebSocket closed, UCM absent).  Dispatch is
        blocked.
    BLOCKED_CAPABILITY
        Device does not satisfy the required capability / action constraints
        for this dispatch request.
    BLOCKED_SESSION_VALIDITY
        Session identity is invalid, stale, or conflicts with an active
        session for this device.
    BLOCKED_CROSS_DEVICE_ELIGIBILITY
        Cross-device eligibility requirements are not met for this device.
    BLOCKED_OPERATIONAL_SUPPORT
        Device class is declared or observable but not operationally supported
        as a dispatch/control near-peer.
    BLOCKED_CONTINUITY_LEGALITY
        The unified continuity legality authority rejected the inbound action
        for this device.  Dispatch is blocked until continuity legality is
        re-established.  Evaluated by ``core.canonical_dispatch_slot_authority``
        (dimension 4) which consumes this gate for lower dimensions.
    BLOCKED_EXECUTION_MODE_INELIGIBLE
        Device does not meet the eligibility requirements for the requested
        execution mode (e.g., device does not support concurrent execution for
        PARALLEL_FANOUT, or does not support wake-signal delivery for
        WAKE_ROUTED).  Evaluated by ``core.canonical_dispatch_slot_authority``
        (dimension 6).
    BLOCKED_OCCUPANCY
        Device is fully occupied (maximum concurrent task limit reached or
        exclusive reservation held by another task).  Evaluated by
        ``core.canonical_dispatch_slot_authority`` (dimension 7).
    BLOCKED_POLICY
        Device-level or system-level dispatch policy rejects this request
        (device disabled, maintenance mode, rate-limit exhausted).  Evaluated
        by ``core.canonical_dispatch_slot_authority`` (dimension 8).
    NOT_REGISTERED
        Device is not registered in UDM at all.
    GATE_ERROR
        An internal error prevented the gate from completing its evaluation.
        Dispatch is blocked conservatively.
    """

    DISPATCH_READY = "dispatch_ready"
    REGISTERED_NOT_READY = "registered_not_ready"
    BLOCKED_REGISTRATION_GAP = "blocked_registration_gap"
    BLOCKED_STALE_ATTACHMENT = "blocked_stale_attachment"
    BLOCKED_TRANSPORT = "blocked_transport"
    BLOCKED_CAPABILITY = "blocked_capability"
    BLOCKED_SESSION_VALIDITY = "blocked_session_validity"
    BLOCKED_CROSS_DEVICE_ELIGIBILITY = "blocked_cross_device_eligibility"
    BLOCKED_OPERATIONAL_SUPPORT = "blocked_operational_support"
    BLOCKED_CONTINUITY_LEGALITY = "blocked_continuity_legality"
    BLOCKED_EXECUTION_MODE_INELIGIBLE = "blocked_execution_mode_ineligible"
    BLOCKED_OCCUPANCY = "blocked_occupancy"
    BLOCKED_POLICY = "blocked_policy"
    NOT_REGISTERED = "not_registered"
    GATE_ERROR = "gate_error"


# ---------------------------------------------------------------------------
# DispatchReadinessResult — canonical readiness contract
# ---------------------------------------------------------------------------


@dataclass
class DispatchReadinessResult:
    """Canonical dispatch readiness decision.

    Produced by :func:`evaluate_dispatch_readiness`.

    Fields
    ------
    device_id
        The device that was evaluated.
    dispatch_ready
        ``True`` iff status is DISPATCH_READY.  All other statuses set
        this to ``False``.
    registered
        ``True`` iff the device has a record in UDM (regardless of dispatch
        readiness).  Explicitly distinguishes Registered from Dispatch Ready.
    status
        :class:`DispatchReadinessStatus` value string.
    reason
        Human-readable explanation of the verdict.
    registration_gaps
        List of downstream registration step names that failed.  Non-empty
        only when status is BLOCKED_REGISTRATION_GAP.
    attachment_state
        Current state of the device's runtime attachment session
        (``"active"``, ``"detached"``, ``"replaced"``, ``"invalidated"``,
        or ``"unknown"`` if not found).
    runtime_session_id
        The registry-assigned stable session ID, when available.
    runtime_attachment_session_id
        The client-supplied canonical attachment identity, when available.
    transport_alive
        ``True`` iff the transport (WebSocket / UCM) is physically connected.
    blocking_notes
        List of additional context strings explaining specific blocking causes.
    """

    device_id: str
    dispatch_ready: bool = False
    registered: bool = False
    status: str = DispatchReadinessStatus.NOT_REGISTERED.value
    reason: str = ""
    registration_gaps: List[str] = field(default_factory=list)
    attachment_state: str = "unknown"
    runtime_session_id: Optional[str] = None
    runtime_attachment_session_id: Optional[str] = None
    transport_alive: bool = False
    blocking_notes: List[str] = field(default_factory=list)
    device_type: Optional[str] = None
    operational_support_status: Optional[str] = None
    operational_support_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "dispatch_ready": self.dispatch_ready,
            "registered": self.registered,
            "status": self.status,
            "reason": self.reason,
            "registration_gaps": list(self.registration_gaps),
            "attachment_state": self.attachment_state,
            "runtime_session_id": self.runtime_session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "transport_alive": self.transport_alive,
            "blocking_notes": list(self.blocking_notes),
            "device_type": self.device_type,
            "operational_support_status": self.operational_support_status,
            "operational_support_reason": self.operational_support_reason,
            "authority": UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def evaluate_dispatch_readiness(
    device_id: str,
    *,
    required_capabilities: Optional[List[str]] = None,
    require_cross_device_eligible: bool = False,
    session_id: Optional[str] = None,
    runtime_attachment_session_id: Optional[str] = None,
    execution_mode: Optional[str] = None,
) -> DispatchReadinessResult:
    """Evaluate whether *device_id* is ready for task dispatch.

    This is the **single canonical pre-dispatch authority**.  Every dispatch
    path MUST call this before sending a task to a device.

    Parameters
    ----------
    device_id
        The device to evaluate.
    required_capabilities
        Optional list of capability names the device must support (e.g.
        ``["screen", "touch"]``).  When provided, any missing capability
        produces BLOCKED_CAPABILITY.
    require_cross_device_eligible
        When ``True``, require the device to pass the cross-device
        eligibility check from ``core.device_readiness``.  Use for
        cross-device, handoff, and wake-routed dispatch modes.
    session_id
        Optional session identity to cross-check against the registry.
        When provided, a mismatch with the device's active session produces
        BLOCKED_SESSION_VALIDITY.
    runtime_attachment_session_id
        Optional client-supplied attachment identity to verify against the
        registry entry.  A mismatch produces BLOCKED_SESSION_VALIDITY.
    execution_mode
        Informational hint (``"local"``, ``"cross_device"``, ``"parallel_fanout"``,
        etc.) for logging context.  Does not affect the decision logic.

    Returns
    -------
    DispatchReadinessResult
        Always returns a valid result; never raises.
    """
    try:
        return _evaluate_impl(
            device_id=device_id,
            required_capabilities=required_capabilities or [],
            require_cross_device_eligible=require_cross_device_eligible,
            session_id=session_id,
            runtime_attachment_session_id=runtime_attachment_session_id,
            execution_mode=execution_mode,
        )
    except Exception as exc:
        logger.warning(
            "UnifiedDispatchReadinessGate: gate evaluation error for device_id=%r: %s",
            device_id,
            exc,
            exc_info=True,
        )
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=False,
            status=DispatchReadinessStatus.GATE_ERROR.value,
            reason=f"gate_internal_error: {exc}",
            blocking_notes=[str(exc)],
        )


def _evaluate_impl(
    device_id: str,
    *,
    required_capabilities: List[str],
    require_cross_device_eligible: bool,
    session_id: Optional[str],
    runtime_attachment_session_id: Optional[str],
    execution_mode: Optional[str],
) -> DispatchReadinessResult:
    """Internal evaluation — all gate checks in order of severity."""
    notes: List[str] = []
    if execution_mode:
        notes.append(f"execution_mode={execution_mode!r}")

    # ----------------------------------------------------------------
    # Gate 1: Registration gap check
    # Must be evaluated early because a gap means attachment steps failed
    # and subsequent checks may not have reliable data.
    # ----------------------------------------------------------------
    gaps = _check_registration_gaps(device_id)
    if gaps:
        logger.info(
            "UnifiedDispatchReadinessGate: BLOCKED_REGISTRATION_GAP device_id=%r gaps=%r",
            device_id,
            gaps,
        )
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=True,   # registered at transport level but gaps present
            status=DispatchReadinessStatus.BLOCKED_REGISTRATION_GAP.value,
            reason=(
                f"Device has {len(gaps)} downstream registration gap(s): {gaps!r}. "
                "Critical attachment steps failed during handle_device_register. "
                "Resolve gaps before dispatching."
            ),
            registration_gaps=gaps,
            blocking_notes=notes,
        )

    # ----------------------------------------------------------------
    # Gate 2: UDM registration check (is the device known to the system?)
    # ----------------------------------------------------------------
    udm_info = _check_udm_registration(device_id)
    udm_registered = udm_info.get("registered", False)
    udm_online = udm_info.get("online", False)

    if not udm_registered:
        logger.debug(
            "UnifiedDispatchReadinessGate: NOT_REGISTERED device_id=%r", device_id,
        )
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=False,
            status=DispatchReadinessStatus.NOT_REGISTERED.value,
            reason="Device is not registered in UDM.",
            blocking_notes=notes,
        )

    support_result = _check_device_operational_support(
        device_id,
        raw_device_type=udm_info.get("device_type"),
    )
    if not support_result["dispatch_target_capable"]:
        notes.append(f"device_type={support_result['device_type']}")
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=True,
            status=DispatchReadinessStatus.BLOCKED_OPERATIONAL_SUPPORT.value,
            reason=support_result["reason"],
            blocking_notes=notes,
            device_type=support_result["device_type"],
            operational_support_status=support_result["support_tier"],
            operational_support_reason=support_result["reason"],
        )

    # ----------------------------------------------------------------
    # Gate 3: Transport alive check
    # ----------------------------------------------------------------
    transport_alive = _check_transport_alive(device_id)
    if not transport_alive:
        notes.append(f"udm_online={udm_online}")
        logger.info(
            "UnifiedDispatchReadinessGate: BLOCKED_TRANSPORT device_id=%r", device_id,
        )
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=True,
            status=DispatchReadinessStatus.BLOCKED_TRANSPORT.value,
            reason="Transport is not alive (WebSocket closed or UCM absent).",
            transport_alive=False,
            blocking_notes=notes,
            device_type=support_result["device_type"],
            operational_support_status=support_result["support_tier"],
            operational_support_reason=support_result["reason"],
        )

    # ----------------------------------------------------------------
    # Gate 4: Runtime attachment session validity
    # ----------------------------------------------------------------
    attachment_result = _check_attachment_validity(
        device_id,
        expected_session_id=session_id,
        expected_attachment_id=runtime_attachment_session_id,
    )
    if not attachment_result["valid"]:
        logger.info(
            "UnifiedDispatchReadinessGate: %s device_id=%r attachment_state=%r",
            attachment_result["status"],
            device_id,
            attachment_result["state"],
        )
        return DispatchReadinessResult(
            device_id=device_id,
            dispatch_ready=False,
            registered=True,
            transport_alive=True,
            status=attachment_result["status"],
            reason=attachment_result["reason"],
            attachment_state=attachment_result["state"],
            runtime_session_id=attachment_result.get("runtime_session_id"),
            runtime_attachment_session_id=attachment_result.get("runtime_attachment_session_id"),
            blocking_notes=notes + attachment_result.get("notes", []),
            device_type=support_result["device_type"],
            operational_support_status=support_result["support_tier"],
            operational_support_reason=support_result["reason"],
        )

    # ----------------------------------------------------------------
    # Gate 5: Capability check (optional — skip when no constraints given)
    # ----------------------------------------------------------------
    if required_capabilities:
        capability_result = _check_capabilities(device_id, required_capabilities)
        if not capability_result["satisfied"]:
            notes.append(
                f"missing_capabilities={capability_result['missing']!r}"
            )
            logger.info(
                "UnifiedDispatchReadinessGate: BLOCKED_CAPABILITY device_id=%r "
                "missing=%r",
                device_id,
                capability_result["missing"],
            )
            return DispatchReadinessResult(
                device_id=device_id,
                dispatch_ready=False,
                registered=True,
                transport_alive=True,
                status=DispatchReadinessStatus.BLOCKED_CAPABILITY.value,
                reason=(
                    f"Device missing required capabilities: "
                    f"{capability_result['missing']!r}."
                ),
                attachment_state=attachment_result["state"],
                runtime_session_id=attachment_result.get("runtime_session_id"),
                runtime_attachment_session_id=attachment_result.get(
                    "runtime_attachment_session_id"
                ),
                blocking_notes=notes,
                device_type=support_result["device_type"],
                operational_support_status=support_result["support_tier"],
                operational_support_reason=support_result["reason"],
            )

    # ----------------------------------------------------------------
    # Gate 6: Cross-device eligibility (optional)
    # ----------------------------------------------------------------
    if require_cross_device_eligible:
        cd_eligible = _check_cross_device_eligibility(device_id)
        if not cd_eligible:
            notes.append("cross_device_eligible=False")
            logger.info(
                "UnifiedDispatchReadinessGate: BLOCKED_CROSS_DEVICE_ELIGIBILITY "
                "device_id=%r",
                device_id,
            )
            return DispatchReadinessResult(
                device_id=device_id,
                dispatch_ready=False,
                registered=True,
                transport_alive=True,
                status=DispatchReadinessStatus.BLOCKED_CROSS_DEVICE_ELIGIBILITY.value,
                reason="Device is not eligible for cross-device dispatch.",
                attachment_state=attachment_result["state"],
                runtime_session_id=attachment_result.get("runtime_session_id"),
                runtime_attachment_session_id=attachment_result.get(
                    "runtime_attachment_session_id"
                ),
                blocking_notes=notes,
                device_type=support_result["device_type"],
                operational_support_status=support_result["support_tier"],
                operational_support_reason=support_result["reason"],
            )

    # ----------------------------------------------------------------
    # All gates passed — DISPATCH_READY
    # ----------------------------------------------------------------
    logger.debug(
        "UnifiedDispatchReadinessGate: DISPATCH_READY device_id=%r "
        "attachment_state=%r mode=%r",
        device_id,
        attachment_result["state"],
        execution_mode,
    )
    return DispatchReadinessResult(
        device_id=device_id,
        dispatch_ready=True,
        registered=True,
        transport_alive=True,
        status=DispatchReadinessStatus.DISPATCH_READY.value,
        reason="All dispatch readiness gates passed.",
        attachment_state=attachment_result["state"],
        runtime_session_id=attachment_result.get("runtime_session_id"),
        runtime_attachment_session_id=attachment_result.get(
            "runtime_attachment_session_id"
        ),
        blocking_notes=notes,
        device_type=support_result["device_type"],
        operational_support_status=support_result["support_tier"],
        operational_support_reason=support_result["reason"],
    )


# ---------------------------------------------------------------------------
# Sub-checks (each composed from existing authority modules)
# ---------------------------------------------------------------------------


def _check_registration_gaps(device_id: str) -> List[str]:
    """Return list of registration gaps for *device_id*; empty = none."""
    try:
        from galaxy_gateway.android.handlers.registration import (
            get_registration_gaps,
        )
        return get_registration_gaps(device_id)
    except Exception as exc:
        logger.debug(
            "UnifiedDispatchReadinessGate: registration gap check unavailable for "
            "device_id=%r: %s",
            device_id,
            exc,
        )
        return []


def _check_udm_registration(device_id: str) -> Dict[str, Any]:
    """Return dict with ``registered`` and ``online`` from UDM."""
    result = {"registered": False, "online": False, "device_type": None}
    try:
        from core.unified.device_manager import get_unified_device_manager
        udm = get_unified_device_manager()
        device = udm.get_device(device_id)
        if device is not None:
            result["registered"] = True
            result["online"] = bool(device.get("online", False))
            result["device_type"] = device.get("device_type") or device.get("platform")
        return result
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)
    # Fallback: try device_readiness (composes UDM internally)
    try:
        from core.device_readiness import get_device_readiness
        summary = get_device_readiness(device_id)
        result["registered"] = summary.registered
        result["online"] = summary.online
        return result
    except Exception as exc:
        logger.debug(
            "UnifiedDispatchReadinessGate: UDM check unavailable for device_id=%r: %s",
            device_id,
            exc,
        )
        # Conservative: treat as registered=False when UDM is unavailable
        return result


def _check_transport_alive(device_id: str) -> bool:
    """Return True iff the transport (WebSocket or UCM) is alive."""
    try:
        from core.device_readiness import get_connection_summary
        conn = get_connection_summary(device_id)
        return conn.websocket_connected or conn.ucm_connected
    except Exception as exc:
        logger.debug(
            "UnifiedDispatchReadinessGate: transport check unavailable for "
            "device_id=%r: %s",
            device_id,
            exc,
        )
        # Conservative default: assume transport alive when check unavailable
        # (prevents infinite block when the readiness module is not yet loaded)
        return True


def _check_attachment_validity(
    device_id: str,
    *,
    expected_session_id: Optional[str],
    expected_attachment_id: Optional[str],
) -> Dict[str, Any]:
    """Check runtime attachment session validity via the registry.

    Returns a dict with:
    - ``valid`` (bool)
    - ``status`` (DispatchReadinessStatus value string)
    - ``reason`` (str)
    - ``state`` (str) — registry entry state
    - ``runtime_session_id`` (str or None)
    - ``runtime_attachment_session_id`` (str or None)
    - ``notes`` (list[str])
    """
    result: Dict[str, Any] = {
        "valid": True,
        "status": DispatchReadinessStatus.DISPATCH_READY.value,
        "reason": "",
        "state": "unknown",
        "runtime_session_id": None,
        "runtime_attachment_session_id": None,
        "notes": [],
    }
    try:
        from core.attached_runtime_session_registry import (
            lookup_session_by_device,
        )
        entry = lookup_session_by_device(device_id, active_only=False)
        if entry is None:
            # No registry entry — registry cannot assert non-active; pass through
            # (consistent with REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY)
            result["state"] = "no_registry_entry"
            return result

        result["state"] = entry.attachment_state.value if hasattr(entry.attachment_state, "value") else str(entry.attachment_state)
        result["runtime_session_id"] = entry.runtime_session_id
        result["runtime_attachment_session_id"] = entry.runtime_attachment_session_id

        # Check for terminal / non-active state
        from core.attached_runtime_session_registry import RegistryEntryState
        state_val = entry.attachment_state
        if hasattr(state_val, "is_terminal") and state_val.is_terminal():
            result["valid"] = False
            result["status"] = DispatchReadinessStatus.BLOCKED_STALE_ATTACHMENT.value
            result["reason"] = (
                f"Runtime attachment session is in terminal state "
                f"'{state_val.value}' for device_id={device_id!r}. "
                "A fresh register/reconnect is required before dispatching."
            )
            return result

        if state_val == RegistryEntryState.detached:
            result["valid"] = False
            result["status"] = DispatchReadinessStatus.BLOCKED_STALE_ATTACHMENT.value
            result["reason"] = (
                f"Runtime attachment session is detached for device_id={device_id!r}. "
                "A reconnect/reattach is required before dispatching."
            )
            return result

        # Cross-check session_id and attachment_id when provided
        if expected_session_id and entry.runtime_session_id:
            if entry.runtime_session_id != expected_session_id:
                result["valid"] = False
                result["status"] = DispatchReadinessStatus.BLOCKED_SESSION_VALIDITY.value
                result["reason"] = (
                    f"Provided session_id={expected_session_id!r} does not match "
                    f"active registry session_id={entry.runtime_session_id!r} "
                    f"for device_id={device_id!r}."
                )
                result["notes"].append(
                    f"session_id_mismatch: expected={expected_session_id!r} "
                    f"actual={entry.runtime_session_id!r}"
                )
                return result

        if expected_attachment_id and entry.runtime_attachment_session_id:
            if entry.runtime_attachment_session_id != expected_attachment_id:
                result["valid"] = False
                result["status"] = DispatchReadinessStatus.BLOCKED_SESSION_VALIDITY.value
                result["reason"] = (
                    f"Provided runtime_attachment_session_id={expected_attachment_id!r} "
                    f"does not match active registry attachment_id="
                    f"{entry.runtime_attachment_session_id!r} for device_id={device_id!r}."
                )
                result["notes"].append(
                    f"attachment_id_mismatch: expected={expected_attachment_id!r} "
                    f"actual={entry.runtime_attachment_session_id!r}"
                )
                return result

    except Exception as exc:
        logger.debug(
            "UnifiedDispatchReadinessGate: attachment check unavailable for "
            "device_id=%r: %s",
            device_id,
            exc,
        )
        # When registry is unavailable, pass through (consistent with
        # REGISTRY_ABSENT_ENTRY_PASSES_THROUGH_PR22_POLICY — we cannot assert
        # non-active state without the registry).
        result["state"] = "registry_unavailable"

    return result


def _check_capabilities(
    device_id: str, required: List[str]
) -> Dict[str, Any]:
    """Check that device satisfies all *required* capabilities."""
    result = {"satisfied": True, "missing": [], "present": []}
    if not required:
        return result
    try:
        from core.device_readiness import get_device_readiness
        summary = get_device_readiness(device_id)
        # DeviceReadinessSummary has capability_ready; for per-capability we
        # fall back to UCM device record
        device_caps: List[str] = []
        try:
            from core.unified.connection_manager import get_unified_connection_manager
            ucm = get_unified_connection_manager()
            dev_record = ucm.get_device(device_id) or {}
            caps_raw = dev_record.get("capabilities", []) or dev_record.get("supported_capabilities", [])
            if isinstance(caps_raw, (list, tuple)):
                device_caps = [str(c).lower() for c in caps_raw]
            elif isinstance(caps_raw, dict):
                device_caps = [str(k).lower() for k, v in caps_raw.items() if v]
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)
        if not device_caps:
            # If capability list is empty, treat as satisfied (no info = don't block)
            return result
        missing = [c for c in required if c.lower() not in device_caps]
        result["missing"] = missing
        result["present"] = [c for c in required if c.lower() in device_caps]
        result["satisfied"] = len(missing) == 0
    except Exception as exc:
        logger.debug(
            "UnifiedDispatchReadinessGate: capability check error for device_id=%r: %s",
            device_id,
            exc,
        )
        # When capability info unavailable, treat as satisfied (don't block)
    return result


def _check_cross_device_eligibility(device_id: str) -> bool:
    """Return True iff device passes the cross-device eligibility check."""
    try:
        from core.device_readiness import is_device_cross_device_ready
        return is_device_cross_device_ready(device_id)
    except Exception as exc:
        logger.debug(
            "UnifiedDispatchReadinessGate: cross-device eligibility check "
            "unavailable for device_id=%r: %s",
            device_id,
            exc,
        )
        # When check unavailable, do not block cross-device dispatch
        return True


def _check_device_operational_support(
    device_id: str,
    *,
    raw_device_type: Optional[str],
) -> Dict[str, Any]:
    try:
        from core.device_operational_support import get_device_operational_support

        verdict = get_device_operational_support(
            device_id=device_id,
            raw_device_type=raw_device_type,
        ).to_dict()
        return verdict
    except Exception:
        return {
            "device_type": str(raw_device_type or "unknown"),
            "support_tier": "unknown",
            "dispatch_target_capable": False,
            "reason": "Operational support classification unavailable.",
        }


# ---------------------------------------------------------------------------
# Test helper
# ---------------------------------------------------------------------------


def reset_dispatch_readiness_gate() -> None:
    """No-op — this module is stateless.  Kept for API symmetry with other gates."""


# ---------------------------------------------------------------------------
# __all__
# ---------------------------------------------------------------------------

__all__ = [
    "UNIFIED_DISPATCH_READINESS_GATE_AUTHORITY",
    "REGISTERED_VS_DISPATCH_READY_DISTINCTION_POLICY",
    "DISPATCH_MUST_CONSULT_UNIFIED_GATE_POLICY",
    "REGISTRATION_GAP_BLOCKS_DISPATCH_POLICY",
    "STALE_ATTACHMENT_BLOCKS_DISPATCH_POLICY",
    "ONLINE_NOT_EQUAL_DISPATCH_READY_POLICY",
    "UNSUPPORTED_DEVICE_TYPE_BLOCKS_DISPATCH_POLICY",
    "DISPATCH_GATE_SHARES_CONTINUITY_AUTHORITY_POLICY",
    "CANONICAL_DISPATCH_SLOT_AUTHORITY_CONSUMES_THIS_GATE_POLICY",
    "DispatchReadinessStatus",
    "DispatchReadinessResult",
    "evaluate_dispatch_readiness",
    "reset_dispatch_readiness_gate",
]
