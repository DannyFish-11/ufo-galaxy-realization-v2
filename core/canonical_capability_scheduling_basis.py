"""core/canonical_capability_scheduling_basis.py
===================================================
PR package 6 (post-533 dual-repo runtime unification master plan, MAIN repo
side): Canonical Device Capability & Scheduling Basis.

This module is the **canonical authority** for device/host runtime capability
representation and scheduling-basis normalization on the main-repo side.

Background
----------
Prior to PR-6, execution-surface selection in the OpenClawd runtime relied on
a combination of scattered heuristics: implicit host/device assumptions,
ad-hoc eligibility checks at individual dispatch call sites, and partial
capability signals that were inconsistently propagated through the formation,
projection, and orchestration layers.

PR-6 closes the main-repo half of the canonical capability/scheduling basis
work by providing:

1. :class:`CapabilityTier` — canonical enum classifying a device or host's
   runtime capability level relevant to execution placement.
2. :class:`RuntimeCapabilityProfile` — a stable, serialisable snapshot of all
   capability-relevant signals for one device or host, including posture,
   coordination role, host presence, and Galaxy-app autonomy flags.
3. :class:`SchedulingBasisInputs` — normalized, flat view of the inputs that
   matter for execution-surface eligibility and future scheduling decisions.
4. :class:`ExecutionSurfaceEligibility` — the canonical output of a scheduling-
   basis evaluation, naming the eligible execution surface and the reason.
5. :func:`build_runtime_capability_profile` — derives a
   :class:`RuntimeCapabilityProfile` from a device record (attribute or dict).
6. :func:`build_scheduling_basis_inputs` — normalizes raw signals into a
   :class:`SchedulingBasisInputs`.
7. :func:`evaluate_execution_surface_eligibility` — combines all scheduling-
   basis inputs into an :class:`ExecutionSurfaceEligibility` result.
8. :func:`normalize_scheduling_inputs` — convenience wrapper for dict-shaped
   raw payloads.
9. Eight policy sentinels documenting canonical scheduling-basis rules.

Design principles
-----------------
- **Additive only** — does not modify any existing module.
- **Posture-preserving** — all ``source_runtime_posture`` semantics from
  PR-533 / PR-1 are honoured and composed, not replaced.
- **Coordination-role aware** — integrates with the PR-538 / PR-6
  ``CoordinationRole`` model so eligibility is consistent across both layers.
- **Android-host aware** — uses the AndroidRuntimeHostRole classification
  from PR-5 as one input signal.
- **Graceful degradation** — unknown or missing fields default to the
  conservative safe outcome (``unknown`` tier, ``unavailable`` surface).
- **Fully serialisable** — all dataclasses expose ``to_dict()`` / ``to_json()``
  for stable, round-trippable wire representations.

Relationship to other PR packages
----------------------------------
* PR-1  (``core.posture_contract_canonicalization``) — canonicalises the
  posture value that is consumed here.
* PR-2  (``core.source_execution_eligibility``) — provides per-posture
  eligibility checks; this module is a higher-level scheduling composition.
* PR-4  (``core.canonical_session_truth``) — session truth records may embed
  scheduling-basis snapshots for audit.
* PR-5  (``core.android_runtime_host``) — ``AndroidRuntimeHostRole`` is one
  of the capability signals consumed by this module.
* PR-538 (``core.multi_device_coordination_authority``) — ``CoordinationRole``
  is a key scheduling-basis input.

Public API
----------
Sentinels::

    CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY
    FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY
    COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY
    CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY
    OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY
    ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY
    SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY
    CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL

Enums::

    CapabilityTier
    ExecutionSurface

Dataclasses::

    RuntimeCapabilityProfile
    SchedulingBasisInputs
    ExecutionSurfaceEligibility

Functions::

    build_runtime_capability_profile(device) -> RuntimeCapabilityProfile
    build_scheduling_basis_inputs(...) -> SchedulingBasisInputs
    evaluate_execution_surface_eligibility(inputs) -> ExecutionSurfaceEligibility
    normalize_scheduling_inputs(raw) -> SchedulingBasisInputs
"""

from __future__ import annotations

import json
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from core.schemas.ugcp.shared import ParticipantTier

__all__ = [
    # Sentinels
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY",
    "FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY",
    "COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY",
    "CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY",
    "OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY",
    "ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY",
    "SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY",
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL",
    # Enums
    "CapabilityTier",
    "ExecutionSurface",
    # Dataclasses
    "RuntimeCapabilityProfile",
    "SchedulingBasisInputs",
    "ExecutionSurfaceEligibility",
    # Functions
    "build_runtime_capability_profile",
    "build_scheduling_basis_inputs",
    "evaluate_execution_surface_eligibility",
    "normalize_scheduling_inputs",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::AUTHORITY_V1: "
    "core.canonical_capability_scheduling_basis is the canonical authority "
    "for device/host runtime capability representation and scheduling-basis "
    "normalization on the main-repo side.  "
    "PR package 6, post-533 dual-repo runtime unification master plan."
)
"""Module authority sentinel."""

FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::FULL_RUNTIME_TIER_REQUIRES_JOIN_RUNTIME_POSTURE_V1: "
    "A device or host may only be classified as CapabilityTier.full_runtime "
    "when its source_runtime_posture is 'join_runtime' (or equivalent).  "
    "Devices with 'control_only' posture are capped at partial_runtime or below "
    "regardless of their autonomy flags."
)
"""Policy: full_runtime tier requires join_runtime posture."""

COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::COMMAND_ONLY_BLOCKS_PLACEMENT_V1: "
    "A device classified as CapabilityTier.command_only MUST NOT be selected "
    "as an execution surface.  It may only receive commands and return state; "
    "no task segment may be dispatched to it as an executor."
)
"""Policy: command_only capability tier blocks execution placement."""

CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::CAPABILITY_TIER_DRIVES_SURFACE_V1: "
    "ExecutionSurface selection is driven primarily by CapabilityTier.  "
    "full_runtime and partial_runtime tiers may receive execution dispatch; "
    "command_only and unknown tiers yield ExecutionSurface.unavailable unless "
    "an explicit canonical exception is registered by the caller."
)
"""Policy: capability tier is the primary driver of surface eligibility."""

OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_V1: "
    "A device assigned the 'observer_only' coordination role (PR-538) MUST NOT "
    "be selected as an execution surface regardless of its declared posture "
    "or capability tier.  The coordination role overrides scheduling eligibility "
    "when the role is definitively observer_only."
)
"""Policy: observer_only role excludes device from scheduling."""

ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_V1: "
    "When a device is classified as AndroidRuntimeHostRole.FULL_RUNTIME_HOST or "
    "PARTIAL_RUNTIME_HOST by core.android_runtime_host (PR-5), its capability "
    "tier is lifted to at least partial_runtime in the scheduling basis, even if "
    "the posture or autonomy flags alone would not yet justify full_runtime."
)
"""Policy: Android runtime-host classification (PR-5) lifts capability tier."""

SCHEDULING_BASIS_NORMALISATION_IS_ADDITIVE_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::SCHEDULING_BASIS_NORMALISATION_ADDITIVE_V1: "
    "SchedulingBasisInputs normalization is strictly additive.  It collects and "
    "standardises existing signals (posture, coordination role, host presence, "
    "capability flags) without replacing or overriding the originating sources.  "
    "No scheduling policy decision is made inside normalization; decisions are "
    "made exclusively in evaluate_execution_surface_eligibility()."
)
"""Policy: input normalisation is additive and does not embed decisions."""

CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::PR6_SENTINEL_V1: "
    "PR package 6 (post-533 dual-repo runtime unification, MAIN repo side) — "
    "canonical device/host capability representation and scheduling-basis "
    "normalization is active.  core.canonical_capability_scheduling_basis is "
    "the single authoritative module for capability tier classification and "
    "execution-surface eligibility in the Galaxy runtime."
)
"""PR-6 integration sentinel."""

# ---------------------------------------------------------------------------
# Internal canonical string constants
# ---------------------------------------------------------------------------

_POSTURE_JOIN_RUNTIME: str = "join_runtime"
_POSTURE_CONTROL_ONLY: str = "control_only"

_ROLE_OBSERVER_ONLY: str = "observer_only"
_ROLE_JOINED_RUNTIME_PARTICIPANT: str = "joined_runtime_participant"
_ROLE_SOURCE_CONTROLLER: str = "source_controller"
_ROLE_TARGET_ONLY_EXECUTOR: str = "target_only_executor"
_ROLE_UNRESOLVED: str = "unresolved"

_ANDROID_ROLE_FULL: str = "full_runtime_host"
_ANDROID_ROLE_PARTIAL: str = "partial_runtime_host"
_ANDROID_ROLE_CONNECTED: str = "connected_device_only"
_ANDROID_ROLE_UNCLASSIFIED: str = "unclassified"

_PARTICIPANT_TIER_FULL_RUNTIME_HOST: str = ParticipantTier.FULL_RUNTIME_HOST.value
_PARTICIPANT_TIER_PARTIAL_RUNTIME_NODE: str = ParticipantTier.PARTIAL_RUNTIME_NODE.value
_PARTICIPANT_TIER_COMMAND_ENDPOINT: str = ParticipantTier.COMMAND_ENDPOINT.value
_PARTICIPANT_TIER_OBSERVER_ENDPOINT: str = ParticipantTier.OBSERVER_ENDPOINT.value


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CapabilityTier(str, Enum):
    """Canonical capability tier for a device or host runtime participant.

    Drives execution-surface eligibility and future scheduling policy.

    Values
    ------
    full_runtime
        Device has full runtime capability: ``source_runtime_posture ==
        'join_runtime'``, Galaxy app runtime is enabled, and handoff/takeover
        is supported.  May be selected as a primary execution surface.
    partial_runtime
        Device has partial runtime capability: either posture or autonomy flags
        indicate some execution capacity, but not the full combination.  May be
        selected as an execution surface with reduced confidence.
    command_only
        Device can only receive commands and return state.  MUST NOT be
        selected as an execution surface.
    unknown
        Insufficient information to classify.  Treated conservatively as
        command_only for scheduling purposes.
    """

    full_runtime = "full_runtime"
    partial_runtime = "partial_runtime"
    command_only = "command_only"
    unknown = "unknown"

    @classmethod
    def from_string(cls, value: str) -> "CapabilityTier":
        """Return a :class:`CapabilityTier` from a raw string, defaulting to
        :attr:`unknown` on unrecognised values."""
        try:
            return cls(str(value).strip().lower())
        except (ValueError, AttributeError):
            return cls.unknown


class ExecutionSurface(str, Enum):
    """Canonical execution surface that a device may occupy.

    Values
    ------
    local_host
        The request-originating host (typically the OpenClawd process on the
        local desktop/server) executes the task.
    android_host
        An Android device that is a first-class runtime host (PR-5) executes
        the task or a segment of it.
    remote_device
        A registered remote device (non-Android) executes the task.
    unavailable
        No eligible execution surface is available given the current capability
        and scheduling basis.  The task cannot be dispatched.
    """

    local_host = "local_host"
    android_host = "android_host"
    remote_device = "remote_device"
    unavailable = "unavailable"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionSurface":
        """Return an :class:`ExecutionSurface` from a raw string."""
        try:
            return cls(str(value).strip().lower())
        except (ValueError, AttributeError):
            return cls.unavailable


# ---------------------------------------------------------------------------
# RuntimeCapabilityProfile
# ---------------------------------------------------------------------------


class RuntimeCapabilityProfile:
    """Canonical snapshot of a device or host's runtime capability signals.

    This is the stable, serialisable capability representation used by the
    scheduling basis.  It aggregates all signals that influence capability
    tier classification into one inspectable record.

    Attributes
    ----------
    device_id:
        Stable unique identifier for the device or host.
    platform:
        Platform string (e.g. ``"android"``, ``"desktop"``, ``"remote"``).
    source_runtime_posture:
        Normalised posture value (``"join_runtime"`` or ``"control_only"``).
    coordination_role:
        Canonical coordination role string (e.g. ``"source_controller"``,
        ``"joined_runtime_participant"``).  Empty string if unknown.
    is_host_present:
        ``True`` when the local OpenClawd host process is running on this
        device (relevant for ``local_host`` surface eligibility).
    is_runtime_host:
        ``True`` when the device is explicitly marked as a runtime host (e.g.
        from Android registration with ``is_runtime_host=True``).
    runtime_enabled:
        ``True`` when the Galaxy runtime module is active on the device.
    supports_remote_handoff:
        ``True`` when the device can participate in cross-device handoff.
    android_host_role:
        The ``AndroidRuntimeHostRole`` string value (from PR-5) if this is an
        Android device, otherwise ``""`` (empty).
    capability_tier:
        Derived :class:`CapabilityTier` classification for this device.
    profile_id:
        Auto-generated stable identifier for this profile record.
    """

    __slots__ = (
        "device_id",
        "platform",
        "source_runtime_posture",
        "coordination_role",
        "is_host_present",
        "is_runtime_host",
        "runtime_enabled",
        "supports_remote_handoff",
        "android_host_role",
        "capability_tier",
        "profile_id",
    )

    def __init__(
        self,
        device_id: str = "",
        platform: str = "",
        source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
        coordination_role: str = "",
        is_host_present: bool = False,
        is_runtime_host: bool = False,
        runtime_enabled: bool = False,
        supports_remote_handoff: bool = False,
        android_host_role: str = "",
        capability_tier: Optional[CapabilityTier] = None,
        profile_id: Optional[str] = None,
    ) -> None:
        self.device_id = device_id
        self.platform = platform
        self.source_runtime_posture = source_runtime_posture
        self.coordination_role = coordination_role
        self.is_host_present = is_host_present
        self.is_runtime_host = is_runtime_host
        self.runtime_enabled = runtime_enabled
        self.supports_remote_handoff = supports_remote_handoff
        self.android_host_role = android_host_role
        self.capability_tier = capability_tier if capability_tier is not None else CapabilityTier.unknown
        self.profile_id = profile_id or f"rcap_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "profile_id": self.profile_id,
            "device_id": self.device_id,
            "platform": self.platform,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "is_host_present": self.is_host_present,
            "is_runtime_host": self.is_runtime_host,
            "runtime_enabled": self.runtime_enabled,
            "supports_remote_handoff": self.supports_remote_handoff,
            "android_host_role": self.android_host_role,
            "capability_tier": self.capability_tier.value
            if isinstance(self.capability_tier, CapabilityTier)
            else str(self.capability_tier),
            "authority": CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeCapabilityProfile":
        """Reconstruct from a plain dict (e.g., from :meth:`to_dict`)."""
        return cls(
            device_id=str(data.get("device_id", "") or ""),
            platform=str(data.get("platform", "") or ""),
            source_runtime_posture=str(
                data.get("source_runtime_posture", _POSTURE_CONTROL_ONLY)
                or _POSTURE_CONTROL_ONLY
            ),
            coordination_role=str(data.get("coordination_role", "") or ""),
            is_host_present=bool(data.get("is_host_present", False)),
            is_runtime_host=bool(data.get("is_runtime_host", False)),
            runtime_enabled=bool(data.get("runtime_enabled", False)),
            supports_remote_handoff=bool(data.get("supports_remote_handoff", False)),
            android_host_role=str(data.get("android_host_role", "") or ""),
            capability_tier=CapabilityTier.from_string(
                str(data.get("capability_tier", "unknown"))
            ),
            profile_id=data.get("profile_id"),
        )

    def __repr__(self) -> str:
        return (
            f"RuntimeCapabilityProfile("
            f"device_id={self.device_id!r}, "
            f"tier={self.capability_tier!r}, "
            f"posture={self.source_runtime_posture!r})"
        )


# ---------------------------------------------------------------------------
# SchedulingBasisInputs
# ---------------------------------------------------------------------------


class SchedulingBasisInputs:
    """Normalised, flat view of all scheduling-basis inputs for one device.

    This is the single normalised record that
    :func:`evaluate_execution_surface_eligibility` consumes to produce an
    :class:`ExecutionSurfaceEligibility` result.

    Callers should construct this either via
    :func:`build_scheduling_basis_inputs` (from explicit kwargs) or via
    :func:`normalize_scheduling_inputs` (from a raw dict), not by hand.

    Attributes
    ----------
    device_id:
        Stable unique identifier.
    platform:
        Platform string.
    source_runtime_posture:
        Normalised posture value.
    coordination_role:
        Normalised coordination role string.
    capability_tier:
        Derived :class:`CapabilityTier`.
    is_host_present:
        Whether the local OpenClawd host is present on this device.
    is_android_device:
        Whether this is an Android device.
    android_host_role:
        AndroidRuntimeHostRole string (from PR-5), if applicable.
    runtime_enabled:
        Galaxy runtime active flag.
    supports_remote_handoff:
        Handoff participation flag.
    target_device_id:
        Preferred target device ID if the source is a controller dispatching
        to a specific target.  Empty string if not applicable.
    inputs_id:
        Auto-generated identifier for this inputs record.
    """

    __slots__ = (
        "device_id",
        "platform",
        "source_runtime_posture",
        "coordination_role",
        "participant_tier",
        "capability_tier",
        "is_host_present",
        "is_android_device",
        "android_host_role",
        "runtime_enabled",
        "supports_remote_handoff",
        "target_device_id",
        "inputs_id",
    )

    def __init__(
        self,
        device_id: str = "",
        platform: str = "",
        source_runtime_posture: str = _POSTURE_CONTROL_ONLY,
        coordination_role: str = "",
        participant_tier: str = "",
        capability_tier: Optional[CapabilityTier] = None,
        is_host_present: bool = False,
        is_android_device: bool = False,
        android_host_role: str = "",
        runtime_enabled: bool = False,
        supports_remote_handoff: bool = False,
        target_device_id: str = "",
        inputs_id: Optional[str] = None,
    ) -> None:
        self.device_id = device_id
        self.platform = platform
        self.source_runtime_posture = source_runtime_posture
        self.coordination_role = coordination_role
        self.participant_tier = participant_tier
        self.capability_tier = capability_tier if capability_tier is not None else CapabilityTier.unknown
        self.is_host_present = is_host_present
        self.is_android_device = is_android_device
        self.android_host_role = android_host_role
        self.runtime_enabled = runtime_enabled
        self.supports_remote_handoff = supports_remote_handoff
        self.target_device_id = target_device_id
        self.inputs_id = inputs_id or f"sbi_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "inputs_id": self.inputs_id,
            "device_id": self.device_id,
            "platform": self.platform,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "participant_tier": self.participant_tier,
            "capability_tier": self.capability_tier.value
            if isinstance(self.capability_tier, CapabilityTier)
            else str(self.capability_tier),
            "is_host_present": self.is_host_present,
            "is_android_device": self.is_android_device,
            "android_host_role": self.android_host_role,
            "runtime_enabled": self.runtime_enabled,
            "supports_remote_handoff": self.supports_remote_handoff,
            "target_device_id": self.target_device_id,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:
        return (
            f"SchedulingBasisInputs("
            f"device_id={self.device_id!r}, "
            f"tier={self.capability_tier!r}, "
            f"posture={self.source_runtime_posture!r}, "
            f"role={self.coordination_role!r})"
        )


# ---------------------------------------------------------------------------
# ExecutionSurfaceEligibility
# ---------------------------------------------------------------------------


class ExecutionSurfaceEligibility:
    """Canonical output of a scheduling-basis eligibility evaluation.

    Attributes
    ----------
    eligible:
        ``True`` when an eligible execution surface was identified.
    surface:
        The canonical :class:`ExecutionSurface` selected.  Always
        :attr:`ExecutionSurface.unavailable` when ``eligible`` is ``False``.
    reason:
        Human-readable explanation of the eligibility decision.
    capability_tier:
        The :class:`CapabilityTier` that drove the decision.
    inputs_snapshot:
        Dict representation of the :class:`SchedulingBasisInputs` used.
    eligibility_id:
        Auto-generated identifier for this eligibility record.
    """

    __slots__ = (
        "eligible",
        "surface",
        "reason",
        "capability_tier",
        "inputs_snapshot",
        "eligibility_id",
    )

    def __init__(
        self,
        eligible: bool,
        surface: ExecutionSurface,
        reason: str,
        capability_tier: CapabilityTier = CapabilityTier.unknown,
        inputs_snapshot: Optional[Dict[str, Any]] = None,
        eligibility_id: Optional[str] = None,
    ) -> None:
        self.eligible = eligible
        self.surface = surface
        self.reason = reason
        self.capability_tier = capability_tier
        self.inputs_snapshot = inputs_snapshot or {}
        self.eligibility_id = eligibility_id or f"ese_{uuid.uuid4().hex[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        return {
            "eligibility_id": self.eligibility_id,
            "eligible": self.eligible,
            "surface": self.surface.value
            if isinstance(self.surface, ExecutionSurface)
            else str(self.surface),
            "capability_tier": self.capability_tier.value
            if isinstance(self.capability_tier, CapabilityTier)
            else str(self.capability_tier),
            "reason": self.reason,
            "inputs_snapshot": self.inputs_snapshot,
            "authority": CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:
        return (
            f"ExecutionSurfaceEligibility("
            f"eligible={self.eligible!r}, "
            f"surface={self.surface!r}, "
            f"tier={self.capability_tier!r})"
        )


# ---------------------------------------------------------------------------
# Internal: capability tier derivation
# ---------------------------------------------------------------------------


def _derive_capability_tier(
    source_runtime_posture: str,
    is_runtime_host: bool,
    runtime_enabled: bool,
    supports_remote_handoff: bool,
    android_host_role: str,
    coordination_role: str,
) -> CapabilityTier:
    """Derive :class:`CapabilityTier` from the available signals.

    Derivation rules (evaluated in priority order):

    1. **observer_only** coordination role → ``command_only`` (no execution).
    2. ``join_runtime`` posture + runtime_enabled + supports_remote_handoff
       → ``full_runtime``.
    3. ``join_runtime`` posture alone → ``partial_runtime`` (posture declared
       but autonomy flags not fully set).
    4. Android role ``full_runtime_host`` or ``partial_runtime_host`` (PR-5)
       with ``is_runtime_host=True`` → ``partial_runtime`` minimum.
    5. ``is_runtime_host=True`` without join_runtime posture → ``partial_runtime``.
    6. ``runtime_enabled`` alone → ``partial_runtime``.
    7. All else → ``command_only``.
    """
    role_norm = str(coordination_role).strip().lower() if coordination_role else ""
    posture_norm = str(source_runtime_posture).strip().lower() if source_runtime_posture else _POSTURE_CONTROL_ONLY
    android_norm = str(android_host_role).strip().lower() if android_host_role else ""

    # Rule 1: observer_only blocks all execution regardless of other signals.
    if role_norm == _ROLE_OBSERVER_ONLY:
        return CapabilityTier.command_only

    # Rule 2: full join posture + both autonomy flags → full_runtime.
    if (
        posture_norm == _POSTURE_JOIN_RUNTIME
        and runtime_enabled
        and supports_remote_handoff
    ):
        return CapabilityTier.full_runtime

    # Rule 3: join_runtime posture alone → partial_runtime at minimum.
    if posture_norm == _POSTURE_JOIN_RUNTIME:
        return CapabilityTier.partial_runtime

    # Rule 4: Android PR-5 host role lifts tier (even without join_runtime posture).
    if android_norm in (_ANDROID_ROLE_FULL, _ANDROID_ROLE_PARTIAL) and is_runtime_host:
        return CapabilityTier.partial_runtime

    # Rule 5: is_runtime_host flag alone (no join_runtime posture).
    if is_runtime_host:
        return CapabilityTier.partial_runtime

    # Rule 6: runtime_enabled flag alone.
    if runtime_enabled:
        return CapabilityTier.partial_runtime

    # Rule 7: conservative default.
    return CapabilityTier.command_only


# ---------------------------------------------------------------------------
# build_runtime_capability_profile
# ---------------------------------------------------------------------------


def build_runtime_capability_profile(device: Any) -> RuntimeCapabilityProfile:
    """Build a :class:`RuntimeCapabilityProfile` from *device*.

    The function is tolerant of both object (attribute-style) and dict inputs.
    Missing or malformed fields fall back to conservative safe defaults.

    Parameters
    ----------
    device:
        A ``RegisteredRuntimeDevice`` instance, a compatible plain dict, or
        any object with compatible attribute or key access.

    Returns
    -------
    RuntimeCapabilityProfile
        Fully populated profile with a derived :class:`CapabilityTier`.
    """
    try:
        if isinstance(device, dict):
            device_id = str(device.get("device_id", "") or "")
            platform = str(device.get("platform", "") or "")
            posture = str(
                device.get("source_runtime_posture", _POSTURE_CONTROL_ONLY)
                or _POSTURE_CONTROL_ONLY
            )
            role = str(device.get("coordination_role", "") or "")
            is_host_present = bool(device.get("is_host_present", False))
            is_runtime_host = bool(device.get("is_runtime_host", False))
            android_host_role = str(device.get("android_host_role", "") or "")

            autonomy_raw = device.get("autonomy") or {}
            if isinstance(autonomy_raw, dict):
                runtime_enabled = bool(autonomy_raw.get("runtime_enabled", False))
                supports_remote_handoff = bool(
                    autonomy_raw.get("supports_remote_handoff", False)
                )
            else:
                runtime_enabled = bool(
                    getattr(autonomy_raw, "runtime_enabled", False)
                )
                supports_remote_handoff = bool(
                    getattr(autonomy_raw, "supports_remote_handoff", False)
                )
            # Allow flat fields as fallback when no autonomy sub-object.
            if not runtime_enabled:
                runtime_enabled = bool(device.get("runtime_enabled", False))
            if not supports_remote_handoff:
                supports_remote_handoff = bool(
                    device.get("supports_remote_handoff", False)
                )
        else:
            device_id = str(getattr(device, "device_id", "") or "")
            platform = str(getattr(device, "platform", "") or "")
            posture = str(
                getattr(device, "source_runtime_posture", _POSTURE_CONTROL_ONLY)
                or _POSTURE_CONTROL_ONLY
            )
            role = str(getattr(device, "coordination_role", "") or "")
            is_host_present = bool(getattr(device, "is_host_present", False))
            is_runtime_host = bool(getattr(device, "is_runtime_host", False))
            android_host_role = str(getattr(device, "android_host_role", "") or "")

            autonomy = getattr(device, "autonomy", None)
            if autonomy is not None:
                runtime_enabled = bool(getattr(autonomy, "runtime_enabled", False))
                supports_remote_handoff = bool(
                    getattr(autonomy, "supports_remote_handoff", False)
                )
            else:
                runtime_enabled = bool(getattr(device, "runtime_enabled", False))
                supports_remote_handoff = bool(
                    getattr(device, "supports_remote_handoff", False)
                )

        tier = _derive_capability_tier(
            source_runtime_posture=posture,
            is_runtime_host=is_runtime_host,
            runtime_enabled=runtime_enabled,
            supports_remote_handoff=supports_remote_handoff,
            android_host_role=android_host_role,
            coordination_role=role,
        )

        return RuntimeCapabilityProfile(
            device_id=device_id,
            platform=platform,
            source_runtime_posture=posture,
            coordination_role=role,
            is_host_present=is_host_present,
            is_runtime_host=is_runtime_host,
            runtime_enabled=runtime_enabled,
            supports_remote_handoff=supports_remote_handoff,
            android_host_role=android_host_role,
            capability_tier=tier,
        )

    except Exception:
        try:
            fallback_id = str(getattr(device, "device_id", "") or "")
        except Exception:
            fallback_id = ""
        return RuntimeCapabilityProfile(
            device_id=fallback_id,
            capability_tier=CapabilityTier.unknown,
        )


# ---------------------------------------------------------------------------
# build_scheduling_basis_inputs
# ---------------------------------------------------------------------------


def build_scheduling_basis_inputs(
    device_id: str = "",
    platform: str = "",
    source_runtime_posture: Optional[str] = None,
    coordination_role: Optional[str] = None,
    participant_tier: Optional[str] = None,
    capability_tier: Optional[CapabilityTier] = None,
    is_host_present: bool = False,
    is_android_device: bool = False,
    android_host_role: str = "",
    runtime_enabled: bool = False,
    supports_remote_handoff: bool = False,
    target_device_id: str = "",
) -> SchedulingBasisInputs:
    """Construct a :class:`SchedulingBasisInputs` from explicit kwargs.

    All inputs are normalised to canonical values before constructing the
    record.  Unknown or ``None`` values fall back to conservative safe defaults.

    Parameters
    ----------
    device_id:
        Stable unique identifier for the device.
    platform:
        Platform string (e.g. ``"android"``, ``"desktop"``).
    source_runtime_posture:
        Raw posture value.  ``None`` / unknown → ``"control_only"``.
    coordination_role:
        Raw coordination role string.  ``None`` → ``""``.
    capability_tier:
        Pre-computed capability tier.  ``None`` triggers automatic derivation
        from the other signals.
    is_host_present:
        Whether the local OpenClawd host process is present.
    is_android_device:
        Whether this is an Android device.
    android_host_role:
        AndroidRuntimeHostRole string (from PR-5), if applicable.
    runtime_enabled:
        Galaxy runtime active flag.
    supports_remote_handoff:
        Handoff participation flag.
    target_device_id:
        Preferred target device ID, if dispatching from a source controller.

    Returns
    -------
    SchedulingBasisInputs
    """
    posture = (
        _POSTURE_JOIN_RUNTIME
        if str(source_runtime_posture or "").strip().lower() == _POSTURE_JOIN_RUNTIME
        else _POSTURE_CONTROL_ONLY
    )
    role = str(coordination_role or "").strip().lower()
    participant_tier_norm = str(participant_tier or "").strip().lower()

    if capability_tier is None:
        is_runtime_host = is_android_device and bool(android_host_role)
        capability_tier = _derive_capability_tier(
            source_runtime_posture=posture,
            is_runtime_host=is_runtime_host,
            runtime_enabled=runtime_enabled,
            supports_remote_handoff=supports_remote_handoff,
            android_host_role=android_host_role,
            coordination_role=role,
        )

    return SchedulingBasisInputs(
        device_id=device_id,
        platform=platform,
        source_runtime_posture=posture,
        coordination_role=role,
        participant_tier=participant_tier_norm,
        capability_tier=capability_tier,
        is_host_present=is_host_present,
        is_android_device=is_android_device,
        android_host_role=android_host_role,
        runtime_enabled=runtime_enabled,
        supports_remote_handoff=supports_remote_handoff,
        target_device_id=target_device_id,
    )


# ---------------------------------------------------------------------------
# normalize_scheduling_inputs
# ---------------------------------------------------------------------------


def normalize_scheduling_inputs(raw: Dict[str, Any]) -> SchedulingBasisInputs:
    """Normalise a raw dict payload into a :class:`SchedulingBasisInputs`.

    Convenience wrapper for dict-shaped inputs (e.g. from Android registration
    payloads, device projection records, or handoff envelopes).

    Parameters
    ----------
    raw:
        Arbitrary dict with any subset of known scheduling-input keys.

    Returns
    -------
    SchedulingBasisInputs
    """
    if not isinstance(raw, dict):
        return SchedulingBasisInputs()

    device_id = str(raw.get("device_id", "") or "")
    platform = str(raw.get("platform", "") or "")
    posture_raw = raw.get("source_runtime_posture", None)
    role_raw = raw.get("coordination_role", None)
    participant_tier_raw = raw.get("participant_tier", None)
    android_host_role = str(raw.get("android_host_role", "") or "")
    is_host_present = bool(raw.get("is_host_present", False))

    # Detect Android device by platform or by presence of android-specific fields.
    is_android = (
        str(platform).lower() == "android"
        or bool(raw.get("is_android_device", False))
        or bool(android_host_role)
    )

    # Autonomy signals may live in a nested dict or flat at root level.
    autonomy = raw.get("autonomy") or {}
    if isinstance(autonomy, dict):
        runtime_enabled = bool(autonomy.get("runtime_enabled", raw.get("runtime_enabled", False)))
        supports_remote_handoff = bool(
            autonomy.get("supports_remote_handoff", raw.get("supports_remote_handoff", False))
        )
    else:
        runtime_enabled = bool(raw.get("runtime_enabled", False))
        supports_remote_handoff = bool(raw.get("supports_remote_handoff", False))

    pre_tier_raw = raw.get("capability_tier", None)
    pre_tier = CapabilityTier.from_string(str(pre_tier_raw)) if pre_tier_raw else None

    return build_scheduling_basis_inputs(
        device_id=device_id,
        platform=platform,
        source_runtime_posture=str(posture_raw) if posture_raw else None,
        coordination_role=str(role_raw) if role_raw else None,
        participant_tier=str(participant_tier_raw) if participant_tier_raw else None,
        capability_tier=pre_tier,
        is_host_present=is_host_present,
        is_android_device=is_android,
        android_host_role=android_host_role,
        runtime_enabled=runtime_enabled,
        supports_remote_handoff=supports_remote_handoff,
        target_device_id=str(raw.get("target_device_id", "") or ""),
    )


# ---------------------------------------------------------------------------
# evaluate_execution_surface_eligibility
# ---------------------------------------------------------------------------


def evaluate_execution_surface_eligibility(
    inputs: SchedulingBasisInputs,
) -> ExecutionSurfaceEligibility:
    """Evaluate execution-surface eligibility from :class:`SchedulingBasisInputs`.

    This is the **canonical scheduling-basis evaluation function**.  It
    combines posture, coordination role, capability tier, platform, and host
    presence into a single :class:`ExecutionSurfaceEligibility` result.

    Evaluation rules (applied in priority order):

    1. **observer_only** coordination role → ``unavailable`` (observer cannot
       be an execution surface regardless of tier or posture).
    2. **observer_endpoint / command_endpoint** *participant tiers* →
       ``unavailable``.
    3. **command_only / unknown** *capability tiers* → ``unavailable``
       (capability gate).
    4. **local_host** surface: ``is_host_present`` is True AND tier is
       ``full_runtime`` or ``partial_runtime`` AND posture is ``join_runtime``
       (or role is ``joined_runtime_participant``).
    5. **android_host** surface: ``is_android_device`` is True AND tier is
       ``full_runtime`` or ``partial_runtime``.
    6. **remote_device** surface: non-Android device with ``partial_runtime``
       or ``full_runtime`` tier and a ``target_device_id`` present.
    7. **unavailable** — none of the above conditions matched.

    Parameters
    ----------
    inputs:
        Normalised :class:`SchedulingBasisInputs`.

    Returns
    -------
    ExecutionSurfaceEligibility
    """
    try:
        role = str(inputs.coordination_role or "").strip().lower()
        participant_tier = str(inputs.participant_tier or "").strip().lower()
        tier = inputs.capability_tier
        posture = str(inputs.source_runtime_posture or "").strip().lower()
        inputs_snap = inputs.to_dict()

        # Rule 1: observer_only → unavailable.
        if role == _ROLE_OBSERVER_ONLY:
            return ExecutionSurfaceEligibility(
                eligible=False,
                surface=ExecutionSurface.unavailable,
                reason=(
                    "coordination_role=observer_only: device is excluded from "
                    "execution scheduling.  "
                    f"Policy: {OBSERVER_ONLY_ROLE_EXCLUDED_FROM_SCHEDULING_POLICY}"
                ),
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )

        # Rule 2: participant tier explicit gate.
        if participant_tier == _PARTICIPANT_TIER_OBSERVER_ENDPOINT:
            return ExecutionSurfaceEligibility(
                eligible=False,
                surface=ExecutionSurface.unavailable,
                reason="participant_tier=observer_endpoint: participant is observer-only.",
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )
        if participant_tier == _PARTICIPANT_TIER_COMMAND_ENDPOINT:
            return ExecutionSurfaceEligibility(
                eligible=False,
                surface=ExecutionSurface.unavailable,
                reason="participant_tier=command_endpoint: participant is not a runtime execution surface.",
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )

        # Rule 3: command_only / unknown tier → unavailable.
        if tier in (CapabilityTier.command_only, CapabilityTier.unknown):
            return ExecutionSurfaceEligibility(
                eligible=False,
                surface=ExecutionSurface.unavailable,
                reason=(
                    f"capability_tier={tier.value}: device cannot be selected "
                    "as an execution surface.  "
                    f"Policy: {COMMAND_ONLY_TIER_BLOCKS_EXECUTION_PLACEMENT_POLICY}"
                ),
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )

        eligible_tier = tier in (CapabilityTier.full_runtime, CapabilityTier.partial_runtime)

        # Rule 4: local_host surface.
        if (
            inputs.is_host_present
            and eligible_tier
            and (
                posture == _POSTURE_JOIN_RUNTIME
                or role == _ROLE_JOINED_RUNTIME_PARTICIPANT
            )
        ):
            return ExecutionSurfaceEligibility(
                eligible=True,
                surface=ExecutionSurface.local_host,
                reason=(
                    f"local_host: host is present, tier={tier.value}, "
                    f"posture={posture}, role={role or 'none'}.  "
                    f"Policy: {CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY}"
                ),
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )

        # Rule 5: android_host surface.
        if inputs.is_android_device and eligible_tier:
            return ExecutionSurfaceEligibility(
                eligible=True,
                surface=ExecutionSurface.android_host,
                reason=(
                    f"android_host: Android device with tier={tier.value}, "
                    f"posture={posture}, android_host_role={inputs.android_host_role!r}.  "
                    f"Policy: {ANDROID_HOST_CAPABILITY_LIFTED_FROM_PR5_POLICY}"
                ),
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )

        # Rule 6: remote_device surface (non-Android, with a target).
        if not inputs.is_android_device and eligible_tier and inputs.target_device_id:
            return ExecutionSurfaceEligibility(
                eligible=True,
                surface=ExecutionSurface.remote_device,
                reason=(
                    f"remote_device: non-Android device with tier={tier.value}, "
                    f"target_device_id={inputs.target_device_id!r}.  "
                    f"Policy: {CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY}"
                ),
                capability_tier=tier,
                inputs_snapshot=inputs_snap,
            )

        # Rule 7: unavailable.
        return ExecutionSurfaceEligibility(
            eligible=False,
            surface=ExecutionSurface.unavailable,
            reason=(
                f"No eligible execution surface: tier={tier.value}, "
                f"posture={posture}, is_host_present={inputs.is_host_present}, "
                f"is_android={inputs.is_android_device}, "
                f"target_device_id={inputs.target_device_id!r}.  "
                f"Policy: {CAPABILITY_TIER_DRIVES_SURFACE_ELIGIBILITY_POLICY}"
            ),
            capability_tier=tier,
            inputs_snapshot=inputs_snap,
        )

    except Exception:
        return ExecutionSurfaceEligibility(
            eligible=False,
            surface=ExecutionSurface.unavailable,
            reason="evaluate_execution_surface_eligibility: unexpected error; defaulting to unavailable.",
            capability_tier=CapabilityTier.unknown,
        )
