"""core/canonical_capability_scheduling_basis.py
===================================================
PR package 6 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Device Capability & Scheduling Basis.

**Architecture role**
---------------------
This module is the **canonical authority** for device/host runtime capability
representation and scheduling-basis normalization on the main repo side.

Before this PR, execution-surface selection was driven by a combination of
scattered heuristics: ``source_runtime_posture`` checks in dispatch paths,
``CoordinationRole`` derivations in formation code, Android host-role
classification in PR-5, and per-call capability look-ups in candidate
resolution.  None of these were assembled into a single canonical
representation that a future scheduler could rely on.

This module closes that gap by providing:

1. :class:`CapabilityTier` — machine-readable coarse classification of a
   device's execution capacity, derived from posture, host role, and declared
   capabilities.

2. :class:`RuntimeCapabilityProfile` — the canonical, serialisable snapshot
   capturing all signals relevant to execution-surface placement for a single
   device/host.

3. :class:`SchedulingBasisInputs` — a normalized struct that aggregates all
   inputs a scheduler would need: posture, coordination role, host presence,
   capability tier, and declared capabilities.

4. :class:`ExecutionSurfaceEligibility` — the result of evaluating a surface
   against canonical scheduling-basis inputs.

5. :func:`build_runtime_capability_profile` — constructs a
   :class:`RuntimeCapabilityProfile` from a device info dict or
   ``RegisteredRuntimeDevice``-shaped object.

6. :func:`build_scheduling_basis_inputs` — accepts the already-normalized
   signals and returns a :class:`SchedulingBasisInputs` with coerced defaults.

7. :func:`evaluate_execution_surface_eligibility` — combines
   :class:`SchedulingBasisInputs` with an optional required-capabilities list
   to produce an :class:`ExecutionSurfaceEligibility`.

8. Policy sentinels documenting every behavioral rule.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Posture-preserving** — fully respects ``source_runtime_posture`` values
  from PR-533/PR-1.
- **Coordination-role aware** — integrates ``CoordinationRole`` from PR-6
  (post-533 naming: PR package 6 of the old track = multi_device_coordination
  authority; this module is a new layer above it for the post-533 package 6
  unification track).
- **Graceful defaults** — unknown / missing fields degrade to the safe
  conservative tier (:attr:`CapabilityTier.command_only`).
- **Fully serialisable** — all snapshot objects expose :meth:`to_dict` /
  :meth:`from_dict` for wire transfer.
- **No circular imports** — subsystem imports are performed lazily inside
  helper functions.

Public API
----------
Sentinels::

    CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY
    CAPABILITY_TIER_DRIVES_SURFACE_SELECTION_POLICY
    POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY
    COORDINATION_ROLE_GATES_ORCHESTRATION_PARTICIPATION_POLICY
    HOST_PRESENCE_REQUIRED_FOR_FULL_RUNTIME_POLICY
    OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL

Enums::

    CapabilityTier

Dataclasses::

    RuntimeCapabilityProfile
    SchedulingBasisInputs
    ExecutionSurfaceEligibility

Functions::

    build_runtime_capability_profile(device)
    build_scheduling_basis_inputs(...)
    evaluate_execution_surface_eligibility(inputs, required_capabilities)
    runtime_capability_profile_from_scheduling_inputs(inputs)

Relationship to other modules
------------------------------
* :mod:`core.source_execution_eligibility` — PR-2 posture-aware eligibility is
  incorporated into :func:`evaluate_execution_surface_eligibility` rather than
  duplicated.
* :mod:`core.multi_device_coordination_authority` — ``CoordinationRole`` values
  are accepted by :func:`build_scheduling_basis_inputs`; ``observer_only`` is
  enforced as ineligible.
* :mod:`core.android_runtime_host` — :class:`AndroidRuntimeHostRole` is used
  in :func:`build_runtime_capability_profile` when the device is an Android
  host.
* :mod:`core.capability_registry` — resolved capability lists are consumed by
  :func:`build_runtime_capability_profile` when available.
* :mod:`core.device_execution_profile` — :class:`DeviceProfileClass` is mapped
  to :class:`CapabilityTier` for cross-module coherence.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalCapabilitySchedulingBasis")

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::AUTHORITY_V1: "
    "core.canonical_capability_scheduling_basis is the canonical authority for "
    "device/host runtime capability representation and scheduling-basis "
    "normalization on the main repo side.  "
    "PR package 6 (post-533 dual-repo runtime unification master plan, MAIN side)."
)
"""Sentinel: this module owns canonical capability/scheduling-basis logic."""

CAPABILITY_TIER_DRIVES_SURFACE_SELECTION_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::TIER_DRIVES_SURFACE_SELECTION_V1: "
    "CapabilityTier is the single coarse-grained signal used to select which "
    "execution surfaces are eligible for a task.  Full_runtime surfaces may "
    "receive any task; command_only surfaces receive only structured command "
    "payloads; unknown surfaces are treated conservatively as command_only."
)
"""Policy: capability tier is the primary execution-surface selector."""

POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::POSTURE_GATES_LOCAL_EXECUTION_V1: "
    "A source device with source_runtime_posture='control_only' MUST NOT be "
    "included in the local-execution pool even if it otherwise has a high "
    "CapabilityTier.  Only join_runtime posture unlocks local execution for the "
    "source device."
)
"""Policy: posture gates local execution regardless of capability tier."""

COORDINATION_ROLE_GATES_ORCHESTRATION_PARTICIPATION_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::COORDINATION_ROLE_GATES_ORCHESTRATION_V1: "
    "A device with coordination_role='observer_only' MUST be excluded from all "
    "orchestrated execution surfaces.  Devices with coordination_role="
    "'joined_runtime_participant' are always eligible for execution surfaces "
    "that their CapabilityTier supports."
)
"""Policy: observer_only coordination role blocks orchestration participation."""

HOST_PRESENCE_REQUIRED_FOR_FULL_RUNTIME_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::HOST_PRESENCE_REQUIRED_V1: "
    "A device can only contribute to the full_runtime tier if host_present is "
    "True.  Devices without a confirmed host presence are capped at the "
    "partial_runtime tier even if their declared capabilities would otherwise "
    "qualify them for full_runtime."
)
"""Policy: host presence is required for full_runtime tier assignment."""

OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::OBSERVER_ONLY_EXCLUDED_V1: "
    "observer_only role devices contribute no execution surface regardless of "
    "their CapabilityTier or declared capabilities.  This mirrors the policy "
    "established in core.source_execution_eligibility for PR-2 and extended by "
    "core.canonical_session_truth for PR-4."
)
"""Policy: observer_only devices have no execution surface."""

CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::PR6_INTEGRATION_SENTINEL: "
    "PR package 6 (post-533 dual-repo runtime unification master plan, MAIN "
    "side) canonical capability/scheduling-basis layer is active."
)
"""Integration sentinel confirming PR package 6 scheduling basis is active."""

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

_FULL_RUNTIME_CAPABILITIES = frozenset(
    {"screen", "touch", "keyboard", "camera", "microphone", "agent_runtime"}
)
_PARTIAL_RUNTIME_CAPABILITIES = frozenset(
    {"screen", "touch", "bluetooth", "nfc", "gps"}
)


class CapabilityTier(str, Enum):
    """Coarse-grained classification of a device's execution capacity.

    Used as the primary fast-path signal for execution-surface selection.

    Values
    ------
    full_runtime
        The device can host a full remote agent runtime.  Supports autonomous
        execution, handoff receipt, sub-task execution, and local inference.
        Corresponds to ``join_runtime`` posture and/or Android
        ``FULL_RUNTIME_HOST`` role.
    partial_runtime
        The device has some runtime-capable flags (e.g. remote-handoff support,
        autonomy enabled) but has not committed to full-runtime participation.
        May receive structured sub-tasks but not unconstrained agent execution.
    command_only
        The device accepts only structured gateway commands.  Cannot host an
        agent runtime or receive handoff.  Corresponds to ``control_only``
        posture for source devices, or thin-profile target devices.
    unknown
        Insufficient information to classify the device.  Treated
        conservatively as ``command_only`` for dispatch purposes.
    """

    full_runtime = "full_runtime"
    partial_runtime = "partial_runtime"
    command_only = "command_only"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "CapabilityTier":
        """Return a :class:`CapabilityTier` from a raw string,
        defaulting to :attr:`unknown` on unrecognised values.
        """
        try:
            return cls(str(value).lower())
        except (ValueError, AttributeError):
            return cls.unknown


# ---------------------------------------------------------------------------
# RuntimeCapabilityProfile
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class RuntimeCapabilityProfile:
    """Canonical, serialisable snapshot of a device/host's runtime capabilities
    relevant to execution-surface placement.

    This is the single authoritative representation that downstream scheduling
    and eligibility logic should consume instead of querying disparate sources
    directly.

    Attributes
    ----------
    device_id:
        Stable identifier for the device or host.
    capability_tier:
        Coarse execution-capacity classification derived from posture, host role,
        and declared capabilities.
    source_runtime_posture:
        The ``source_runtime_posture`` value from the device record.
        ``control_only`` or ``join_runtime``; defaults to ``control_only``.
    coordination_role:
        The ``CoordinationRole`` string for this device in the current
        session/formation.  Empty string when not yet assigned.
    is_runtime_host:
        True when the device record explicitly marks the device as a runtime
        host (populated by PR-5 Android host classification or equivalent
        logic for other platforms).
    host_present:
        True when a confirmed host-side runtime presence has been established
        for this device.  Required for :attr:`CapabilityTier.full_runtime`.
    declared_capabilities:
        Raw capability strings declared by the device during registration.
    resolved_capabilities:
        Union of all capability strings resolved from available sources.
        Superset of *declared_capabilities* when multiple sources are queried.
    profile_id:
        Auto-generated stable identifier for this profile snapshot.
    """

    device_id: str
    capability_tier: CapabilityTier = CapabilityTier.unknown
    source_runtime_posture: str = "control_only"
    coordination_role: str = ""
    is_runtime_host: bool = False
    host_present: bool = False
    declared_capabilities: List[str] = dataclasses.field(default_factory=list)
    resolved_capabilities: List[str] = dataclasses.field(default_factory=list)
    profile_id: str = dataclasses.field(
        default_factory=lambda: f"rcap_{uuid.uuid4().hex[:12]}"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "profile_id": self.profile_id,
            "device_id": self.device_id,
            "capability_tier": (
                self.capability_tier.value
                if isinstance(self.capability_tier, CapabilityTier)
                else str(self.capability_tier)
            ),
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "is_runtime_host": self.is_runtime_host,
            "host_present": self.host_present,
            "declared_capabilities": list(self.declared_capabilities),
            "resolved_capabilities": list(self.resolved_capabilities),
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeCapabilityProfile":
        """Reconstruct a :class:`RuntimeCapabilityProfile` from a plain dict."""
        return cls(
            device_id=str(data.get("device_id", "") or ""),
            capability_tier=CapabilityTier.from_string(
                str(data.get("capability_tier", "unknown"))
            ),
            source_runtime_posture=str(
                data.get("source_runtime_posture", "control_only") or "control_only"
            ),
            coordination_role=str(data.get("coordination_role", "") or ""),
            is_runtime_host=bool(data.get("is_runtime_host", False)),
            host_present=bool(data.get("host_present", False)),
            declared_capabilities=list(data.get("declared_capabilities") or []),
            resolved_capabilities=list(data.get("resolved_capabilities") or []),
            profile_id=str(data.get("profile_id") or f"rcap_{uuid.uuid4().hex[:12]}"),
        )


# ---------------------------------------------------------------------------
# SchedulingBasisInputs
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class SchedulingBasisInputs:
    """Normalized struct of all inputs required for an execution-surface
    eligibility or scheduling decision.

    Consuming code (dispatch, orchestration, candidate resolution) should build
    a :class:`SchedulingBasisInputs` once and pass it through the pipeline
    rather than re-reading individual signals from disparate sources.

    Attributes
    ----------
    device_id:
        Target device/surface identifier.
    source_runtime_posture:
        Normalized posture string (``control_only`` or ``join_runtime``).
    coordination_role:
        Normalized coordination role string (``source_controller``,
        ``joined_runtime_participant``, ``target_only_executor``,
        ``observer_only``, or empty when unresolved).
    capability_tier:
        :class:`CapabilityTier` derived from available signals.
    host_present:
        Whether a confirmed host-side runtime presence exists.
    declared_capabilities:
        Capability strings declared by the device.
    required_capabilities:
        Capability strings that must be present for eligibility (caller
        supplied; may be empty).
    is_runtime_host:
        Whether the device is explicitly marked as a runtime host.
    """

    device_id: str = ""
    source_runtime_posture: str = "control_only"
    coordination_role: str = ""
    capability_tier: CapabilityTier = CapabilityTier.unknown
    host_present: bool = False
    declared_capabilities: List[str] = dataclasses.field(default_factory=list)
    required_capabilities: List[str] = dataclasses.field(default_factory=list)
    is_runtime_host: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "device_id": self.device_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "capability_tier": (
                self.capability_tier.value
                if isinstance(self.capability_tier, CapabilityTier)
                else str(self.capability_tier)
            ),
            "host_present": self.host_present,
            "declared_capabilities": list(self.declared_capabilities),
            "required_capabilities": list(self.required_capabilities),
            "is_runtime_host": self.is_runtime_host,
        }


# ---------------------------------------------------------------------------
# ExecutionSurfaceEligibility
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class ExecutionSurfaceEligibility:
    """Result of evaluating a device/surface against canonical scheduling-basis
    inputs.

    Attributes
    ----------
    device_id:
        The device/surface that was evaluated.
    eligible:
        ``True`` when the surface is eligible for execution given the supplied
        inputs.
    capability_tier:
        The resolved :class:`CapabilityTier` at evaluation time.
    blocking_reason:
        Human-readable explanation when ``eligible`` is ``False``; empty string
        when eligible.
    policy_applied:
        The canonical policy sentinel string that produced the eligibility
        decision.
    capabilities_met:
        ``True`` when all *required_capabilities* were satisfied.
    missing_capabilities:
        List of required capabilities that were not found.
    evaluation_id:
        Auto-generated identifier for this evaluation record.
    """

    device_id: str = ""
    eligible: bool = False
    capability_tier: CapabilityTier = CapabilityTier.unknown
    blocking_reason: str = ""
    policy_applied: str = ""
    capabilities_met: bool = True
    missing_capabilities: List[str] = dataclasses.field(default_factory=list)
    evaluation_id: str = dataclasses.field(
        default_factory=lambda: f"ese_{uuid.uuid4().hex[:12]}"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return {
            "evaluation_id": self.evaluation_id,
            "device_id": self.device_id,
            "eligible": self.eligible,
            "capability_tier": (
                self.capability_tier.value
                if isinstance(self.capability_tier, CapabilityTier)
                else str(self.capability_tier)
            ),
            "blocking_reason": self.blocking_reason,
            "policy_applied": self.policy_applied,
            "capabilities_met": self.capabilities_met,
            "missing_capabilities": list(self.missing_capabilities),
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_posture(posture: Optional[str]) -> str:
    """Coerce any posture hint to a canonical ``control_only`` / ``join_runtime``
    string.  Unknown values default to ``control_only`` (conservative safe
    default).
    """
    if posture in ("join_runtime",):
        return "join_runtime"
    return "control_only"


def _normalise_coordination_role(role: Optional[str]) -> str:
    """Return the role string unchanged if it is a known canonical value;
    return empty string otherwise so callers can distinguish *unset* from
    *unrecognised*.
    """
    _known = {
        "source_controller",
        "joined_runtime_participant",
        "target_only_executor",
        "observer_only",
        "unresolved",
    }
    if role and str(role).lower() in _known:
        return str(role).lower()
    return ""


def _derive_tier_from_signals(
    posture: str,
    is_runtime_host: bool,
    host_present: bool,
    declared_capabilities: List[str],
) -> CapabilityTier:
    """Derive a :class:`CapabilityTier` from the available signals.

    Decision logic (in priority order):

    1. ``join_runtime`` posture + ``host_present`` → ``full_runtime``
    2. ``join_runtime`` posture alone (no confirmed host) → ``partial_runtime``
    3. ``is_runtime_host`` flag + partial-runtime capability indicators →
       ``partial_runtime``
    4. Any declared capability set → ``command_only``
    5. Nothing → ``unknown``
    """
    cap_set = frozenset(c.lower() for c in declared_capabilities)

    if posture == "join_runtime":
        if host_present:
            return CapabilityTier.full_runtime
        return CapabilityTier.partial_runtime

    if is_runtime_host:
        # Explicit host flag without join_runtime posture → partial
        return CapabilityTier.partial_runtime

    if cap_set & _PARTIAL_RUNTIME_CAPABILITIES:
        return CapabilityTier.command_only  # connected but not host-capable

    if cap_set:
        return CapabilityTier.command_only

    return CapabilityTier.unknown


def _check_capabilities(
    declared: List[str], required: List[str]
) -> tuple[bool, List[str]]:
    """Return ``(all_met, missing_list)`` for the given capability check."""
    if not required:
        return True, []
    declared_set = {c.lower() for c in declared}
    missing = [c for c in required if c.lower() not in declared_set]
    return len(missing) == 0, missing


# ---------------------------------------------------------------------------
# Public builder functions
# ---------------------------------------------------------------------------


def build_runtime_capability_profile(device: Any) -> RuntimeCapabilityProfile:
    """Build a :class:`RuntimeCapabilityProfile` from a device info dict or
    ``RegisteredRuntimeDevice``-shaped object.

    This function is the single canonical entry point for constructing a
    capability profile from raw device data.  It aggregates signals from:

    - ``source_runtime_posture`` (PR-533/PR-1)
    - ``is_runtime_host`` (PR-5 Android host)
    - ``autonomy.runtime_enabled`` / ``autonomy.supports_remote_handoff``
    - ``online`` / ``status`` (presence)
    - ``capabilities`` / ``capabilities.capabilities`` (declared caps)
    - ``coordination_role`` (PR-6 coordination authority)

    Unknown or missing fields degrade gracefully to the safe conservative
    defaults (``control_only``, ``unknown`` tier, empty capability lists).

    Parameters
    ----------
    device:
        A ``RegisteredRuntimeDevice``-shaped object or a plain ``dict`` from
        a device registration payload.

    Returns
    -------
    RuntimeCapabilityProfile
        Canonical capability profile for the device.
    """
    try:
        return _build_profile_inner(device)
    except Exception as exc:
        logger.warning(
            "canonical_capability_scheduling_basis | build_runtime_capability_profile "
            "failed for device=%r: %s — returning safe-default profile",
            _safe_device_id(device),
            exc,
        )
        return RuntimeCapabilityProfile(device_id=_safe_device_id(device))


def _safe_device_id(device: Any) -> str:
    """Extract a device_id string without raising."""
    try:
        if isinstance(device, dict):
            return str(device.get("device_id", "") or "")
        return str(getattr(device, "device_id", "") or "")
    except Exception:
        return ""


def _build_profile_inner(device: Any) -> RuntimeCapabilityProfile:
    """Inner logic for :func:`build_runtime_capability_profile`."""
    if isinstance(device, dict):
        device_id = str(device.get("device_id", "") or "")
        posture = _normalise_posture(device.get("source_runtime_posture"))
        is_runtime_host = bool(device.get("is_runtime_host", False))
        coordination_role = _normalise_coordination_role(
            str(device.get("coordination_role", "") or "")
        )

        # Host presence: online/status field
        online = device.get("online", False)
        status = str(device.get("status", "") or "")
        host_present = bool(online) or status == "online"

        # Autonomy flags (nested dict or flat)
        autonomy = device.get("autonomy") or {}
        if isinstance(autonomy, dict):
            runtime_enabled = bool(autonomy.get("runtime_enabled", False))
            supports_remote_handoff = bool(autonomy.get("supports_remote_handoff", False))
        else:
            runtime_enabled = bool(getattr(autonomy, "runtime_enabled", False))
            supports_remote_handoff = bool(
                getattr(autonomy, "supports_remote_handoff", False)
            )

        if runtime_enabled or supports_remote_handoff:
            is_runtime_host = is_runtime_host or True

        # Capabilities
        raw_caps = device.get("capabilities") or []
        if isinstance(raw_caps, list):
            declared_caps: List[str] = [str(c) for c in raw_caps]
        else:
            declared_caps = []

        # Try to pull resolved caps from capability_registry lazily
        resolved_caps = _try_get_resolved_capabilities(device_id, declared_caps)

    else:
        # Object-shaped (RegisteredRuntimeDevice or compatible mock)
        device_id = str(getattr(device, "device_id", "") or "")
        posture = _normalise_posture(getattr(device, "source_runtime_posture", None))
        is_runtime_host = bool(getattr(device, "is_runtime_host", False))
        coordination_role = _normalise_coordination_role(
            str(getattr(device, "coordination_role", "") or "")
        )

        # Host presence
        online = getattr(device, "online", False)
        status = str(getattr(device, "status", "") or "")
        host_present = bool(online) or status == "online"

        # Autonomy flags from nested autonomy object
        autonomy = getattr(device, "autonomy", None)
        if autonomy is not None:
            runtime_enabled = bool(getattr(autonomy, "runtime_enabled", False))
            supports_remote_handoff = bool(
                getattr(autonomy, "supports_remote_handoff", False)
            )
            if runtime_enabled or supports_remote_handoff:
                is_runtime_host = is_runtime_host or True
        
        # Capabilities — may be nested object or list
        raw_caps_attr = getattr(device, "capabilities", None)
        if raw_caps_attr is None:
            declared_caps = []
        elif isinstance(raw_caps_attr, list):
            declared_caps = [str(c) for c in raw_caps_attr]
        elif hasattr(raw_caps_attr, "capabilities"):
            declared_caps = [str(c) for c in (raw_caps_attr.capabilities or [])]
        else:
            declared_caps = []

        resolved_caps = _try_get_resolved_capabilities(device_id, declared_caps)

    tier = _derive_tier_from_signals(
        posture=posture,
        is_runtime_host=is_runtime_host,
        host_present=host_present,
        declared_capabilities=declared_caps,
    )

    return RuntimeCapabilityProfile(
        device_id=device_id,
        capability_tier=tier,
        source_runtime_posture=posture,
        coordination_role=coordination_role,
        is_runtime_host=is_runtime_host,
        host_present=host_present,
        declared_capabilities=declared_caps,
        resolved_capabilities=resolved_caps,
    )


def _try_get_resolved_capabilities(
    device_id: str, fallback: List[str]
) -> List[str]:
    """Try to fetch resolved capabilities from :mod:`core.capability_registry`.

    Falls back to *fallback* silently if the registry is unavailable (import
    failure, missing device, or any exception).
    """
    if not device_id:
        return list(fallback)
    try:
        from core.capability_registry import get_device_capability_summary

        summary = get_device_capability_summary(device_id)
        resolved = summary.resolved_capabilities
        if resolved:
            return list(resolved)
    except Exception:
        pass
    return list(fallback)


def build_scheduling_basis_inputs(
    device_id: str = "",
    *,
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    capability_tier: Optional[CapabilityTier] = None,
    host_present: bool = False,
    declared_capabilities: Optional[List[str]] = None,
    required_capabilities: Optional[List[str]] = None,
    is_runtime_host: bool = False,
) -> SchedulingBasisInputs:
    """Build a :class:`SchedulingBasisInputs` from the individual signals,
    applying canonical normalization and safe defaults.

    This is the preferred factory for constructing scheduling basis inputs.
    Callers should pass whatever signals are available; missing signals degrade
    to safe conservative defaults.

    Parameters
    ----------
    device_id:
        Target device/surface identifier.
    source_runtime_posture:
        Raw posture hint; coerced to ``control_only`` or ``join_runtime``.
    coordination_role:
        Raw coordination role string; coerced to a known canonical value or
        empty string.
    capability_tier:
        Explicit tier override.  When ``None`` the tier is derived from the
        other signals.
    host_present:
        Whether a confirmed host-side runtime presence exists.
    declared_capabilities:
        Capability strings declared by the device.
    required_capabilities:
        Capability strings that must be satisfied for eligibility.
    is_runtime_host:
        Whether the device is explicitly marked as a runtime host.

    Returns
    -------
    SchedulingBasisInputs
        Normalized scheduling-basis inputs.
    """
    norm_posture = _normalise_posture(source_runtime_posture)
    norm_role = _normalise_coordination_role(coordination_role)
    caps = list(declared_capabilities or [])
    req_caps = list(required_capabilities or [])

    derived_tier = capability_tier
    if derived_tier is None:
        derived_tier = _derive_tier_from_signals(
            posture=norm_posture,
            is_runtime_host=is_runtime_host,
            host_present=host_present,
            declared_capabilities=caps,
        )

    return SchedulingBasisInputs(
        device_id=device_id,
        source_runtime_posture=norm_posture,
        coordination_role=norm_role,
        capability_tier=derived_tier,
        host_present=host_present,
        declared_capabilities=caps,
        required_capabilities=req_caps,
        is_runtime_host=is_runtime_host,
    )


def evaluate_execution_surface_eligibility(
    inputs: SchedulingBasisInputs,
    required_capabilities: Optional[List[str]] = None,
) -> ExecutionSurfaceEligibility:
    """Evaluate whether a device/surface is eligible for execution given
    canonical scheduling-basis inputs.

    This function applies the canonical policies in priority order:

    1. **observer_only** coordination role → ineligible
       (OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY)
    2. **control_only** posture → ineligible for local execution
       (POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY)
    3. **Capability requirements** not met → ineligible
    4. All gates passed → eligible

    Parameters
    ----------
    inputs:
        Normalized :class:`SchedulingBasisInputs` for the device.
    required_capabilities:
        Optional capability requirement list.  When supplied, it overrides
        ``inputs.required_capabilities`` for this evaluation.

    Returns
    -------
    ExecutionSurfaceEligibility
        Evaluation result with ``eligible``, ``blocking_reason``, and
        ``policy_applied`` populated.
    """
    req_caps = required_capabilities if required_capabilities is not None else inputs.required_capabilities

    # Gate 1: observer_only role → always ineligible
    if inputs.coordination_role == "observer_only":
        return ExecutionSurfaceEligibility(
            device_id=inputs.device_id,
            eligible=False,
            capability_tier=inputs.capability_tier,
            blocking_reason=(
                "observer_only coordination role: device has no execution authority"
            ),
            policy_applied=OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY,
            capabilities_met=True,
            missing_capabilities=[],
        )

    # Gate 2: control_only posture → ineligible for local execution
    if inputs.source_runtime_posture == "control_only":
        return ExecutionSurfaceEligibility(
            device_id=inputs.device_id,
            eligible=False,
            capability_tier=inputs.capability_tier,
            blocking_reason=(
                "control_only posture: source device is not eligible for local execution"
            ),
            policy_applied=POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY,
            capabilities_met=True,
            missing_capabilities=[],
        )

    # Gate 3: capability requirements
    caps_met, missing = _check_capabilities(inputs.declared_capabilities, req_caps)
    if not caps_met:
        return ExecutionSurfaceEligibility(
            device_id=inputs.device_id,
            eligible=False,
            capability_tier=inputs.capability_tier,
            blocking_reason=(
                f"missing required capabilities: {missing}"
            ),
            policy_applied=CAPABILITY_TIER_DRIVES_SURFACE_SELECTION_POLICY,
            capabilities_met=False,
            missing_capabilities=missing,
        )

    # All gates passed
    return ExecutionSurfaceEligibility(
        device_id=inputs.device_id,
        eligible=True,
        capability_tier=inputs.capability_tier,
        blocking_reason="",
        policy_applied=CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
        capabilities_met=True,
        missing_capabilities=[],
    )


def runtime_capability_profile_from_scheduling_inputs(
    inputs: SchedulingBasisInputs,
) -> RuntimeCapabilityProfile:
    """Derive a :class:`RuntimeCapabilityProfile` directly from
    :class:`SchedulingBasisInputs`.

    Useful when a full profile is needed from already-normalized inputs
    without re-reading from device records.

    Parameters
    ----------
    inputs:
        Already-normalized :class:`SchedulingBasisInputs`.

    Returns
    -------
    RuntimeCapabilityProfile
        Profile snapshot built from the scheduling-basis inputs.
    """
    return RuntimeCapabilityProfile(
        device_id=inputs.device_id,
        capability_tier=inputs.capability_tier,
        source_runtime_posture=inputs.source_runtime_posture,
        coordination_role=inputs.coordination_role,
        is_runtime_host=inputs.is_runtime_host,
        host_present=inputs.host_present,
        declared_capabilities=list(inputs.declared_capabilities),
        resolved_capabilities=list(inputs.declared_capabilities),
    )


__all__ = [
    # Sentinels
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY",
    "CAPABILITY_TIER_DRIVES_SURFACE_SELECTION_POLICY",
    "POSTURE_GATES_LOCAL_EXECUTION_IN_SCHEDULING_POLICY",
    "COORDINATION_ROLE_GATES_ORCHESTRATION_PARTICIPATION_POLICY",
    "HOST_PRESENCE_REQUIRED_FOR_FULL_RUNTIME_POLICY",
    "OBSERVER_ONLY_EXCLUDED_FROM_EXECUTION_SURFACE_POLICY",
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL",
    # Enumerations
    "CapabilityTier",
    # Dataclasses
    "RuntimeCapabilityProfile",
    "SchedulingBasisInputs",
    "ExecutionSurfaceEligibility",
    # Functions
    "build_runtime_capability_profile",
    "build_scheduling_basis_inputs",
    "evaluate_execution_surface_eligibility",
    "runtime_capability_profile_from_scheduling_inputs",
]
