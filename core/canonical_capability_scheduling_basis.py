"""core/canonical_capability_scheduling_basis.py
==================================================
Canonical Device Capability & Scheduling Basis — PR package 6
(post-533 dual-repo runtime unification master plan, MAIN repo side).

This module is the canonical authority for normalising the inputs used for
**execution-surface eligibility** and **capability-aware scheduling decisions**
in the OpenClawd runtime.  It builds on the semantic foundations established
by the earlier post-533 PR packages:

- PR-1 — Posture Contract Canonicalization
  (``core.posture_contract_canonicalization``)
- PR-2 — Posture-Aware Source Execution Eligibility
  (``core.source_execution_eligibility``)
- PR-3 — Canonical Handoff / Takeover Path
  (``core.canonical_handoff_path``)
- PR-4 — Canonical Session Truth and Result Merge
  (``core.canonical_session_truth``)
- PR-5 — Android as a First-Class Runtime Host
  (``core.android_runtime_host``)
- PR-538 / Coord-Auth — Multi-Device Coordination Roles
  (``core.multi_device_coordination_authority``)

Problem addressed
-----------------
After PR-1 through PR-5, the main repo has canonical posture, eligibility,
handoff, session-truth, and Android-host models.  However, **execution
placement** — deciding *which surface* should execute a given task — still
relies on scattered heuristics that inspect posture, coordination role, host
presence, and capability signals independently.  This module replaces those
scattered checks with one authoritative place to:

1. Collect all scheduling-relevant signals into a normalised
   :class:`CapabilitySchedulingInput`.
2. Derive a :class:`CapabilitySchedulingBasis` (eligible surfaces, scheduling
   weight, capability signals, ineligibility reason when blocked).
3. Expose policy sentinels so audit / observability layers can reference
   which rule drove a given eligibility outcome.

Non-goals
---------
- This module does **not** implement a full dynamic scheduler or policy
  control plane.
- It does **not** modify any existing module.
- It does **not** attempt full recovery/lifecycle orchestration.

Design principles
-----------------
- **Additive only** — no existing module is altered.
- **Posture-preserving** — all ``source_runtime_posture`` semantics from
  PR-533/PR-1 are honoured exactly.
- **Coordination-role-aware** — ``CoordinationRole`` semantics from PR-538
  are respected: ``observer_only`` is never eligible for scheduling.
- **Android-host-aware** — :class:`~core.android_runtime_host.AndroidRuntimeHostRole`
  from PR-5 informs Android surface eligibility.
- **Graceful defaults** — unknown or missing fields fall back to the safe
  conservative default (ineligible / lowest weight).
- **Fully serialisable** — :meth:`CapabilitySchedulingBasis.to_dict` produces
  a stable, round-trippable JSON payload.

Public surface
--------------
:data:`CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY`
    Module-level authority sentinel.

:data:`CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL`
    Integration sentinel confirming PR package 6 delivery.

:data:`OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY`
    Policy: ``observer_only`` coordination role is never scheduling-eligible.

:data:`CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY`
    Policy: ``control_only`` posture excludes local-host scheduling.

:data:`ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY`
    Policy: Android surface requires ``join_runtime`` posture.

:data:`CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY`
    Policy: all scheduling inputs must be normalised through this module.

:class:`ExecutionSurface`
    Canonical enum of execution surfaces a device may contribute to.

:class:`CapabilitySchedulingInput`
    Normalised inputs for scheduling: posture + coordination role +
    android host role + capabilities + liveness.

:class:`CapabilitySchedulingBasis`
    Derived scheduling basis: eligible surfaces, weight, signals, reason.

:func:`normalize_scheduling_inputs`
    Produce a :class:`CapabilitySchedulingInput` from a
    ``RegisteredRuntimeDevice``-shaped object or dict.

:func:`build_capability_scheduling_basis`
    Derive a :class:`CapabilitySchedulingBasis` from a
    :class:`CapabilitySchedulingInput`.

:func:`assess_scheduling_eligibility`
    Convenience helper: given a device-like object, return
    ``(CapabilitySchedulingInput, CapabilitySchedulingBasis)``.
"""

from __future__ import annotations

import dataclasses
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    # Authority / policy sentinels
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY",
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL",
    "OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY",
    "CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY",
    "ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY",
    "CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY",
    "SCHEDULING_BASIS_IS_POSTURE_AND_ROLE_DRIVEN_POLICY",
    # Data types
    "ExecutionSurface",
    "CapabilitySchedulingInput",
    "CapabilitySchedulingBasis",
    # Functions
    "normalize_scheduling_inputs",
    "build_capability_scheduling_basis",
    "assess_scheduling_eligibility",
]


# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::PR6_AUTHORITY_V1: "
    "core.canonical_capability_scheduling_basis is the canonical authority "
    "for normalising execution-surface eligibility and capability-aware "
    "scheduling basis inputs on the main repo side.  "
    "PR package 6, post-533 dual-repo runtime unification master plan."
)
"""Sentinel: this module owns canonical capability/scheduling basis derivation."""

CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::PR6_INTEGRATED_V1: "
    "PR package 6 (Canonical Device Capability & Scheduling Basis, MAIN "
    "repo side) of the post-533 dual-repo runtime unification master plan "
    "is active.  Execution-surface eligibility and scheduling inputs are "
    "now normalised through a single canonical basis module, replacing "
    "scattered heuristics in orchestration paths."
)
"""Integration sentinel confirming PR package 6 delivery is live."""

OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::OBSERVER_ONLY_EXCLUDED_V1: "
    "A device assigned the 'observer_only' coordination role MUST NOT be "
    "included in any execution-surface eligibility or scheduling basis "
    "computation.  The observer_only role unconditionally blocks scheduling "
    "regardless of posture, capabilities, or runtime presence.  "
    "This is consistent with PR-2 and PR-4 observer-only exclusion policies."
)
"""Policy: observer_only coordination role blocks scheduling unconditionally."""

CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::CONTROL_ONLY_EXCLUDED_LOCAL_V1: "
    "A device with source_runtime_posture='control_only' MUST NOT be "
    "scheduled onto the LOCAL_HOST execution surface as a runtime executor.  "
    "It may still contribute remote-handoff scheduling via the REMOTE_DEVICE "
    "surface when routable.  This extends the PR-2 control_only ineligibility "
    "policy to the scheduling-basis layer."
)
"""Policy: control_only posture excludes LOCAL_HOST scheduling."""

ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::ANDROID_HOST_JOIN_RUNTIME_V1: "
    "An Android device is eligible for the ANDROID_HOST execution surface "
    "ONLY when its source_runtime_posture is 'join_runtime' AND its "
    "android_host_role is FULL_RUNTIME_HOST or PARTIAL_RUNTIME_HOST (PR-5).  "
    "A CONNECTED_DEVICE_ONLY or UNCLASSIFIED Android device MAY still be "
    "eligible for REMOTE_DEVICE scheduling when routable, but MUST NOT be "
    "included in the ANDROID_HOST surface without the requisite posture."
)
"""Policy: Android host surface requires join_runtime posture + host role."""

CAPABILITY_SCHEDULING_INPUTS_NORMALIZED_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::INPUTS_NORMALIZED_V1: "
    "All scheduling-relevant signals (posture, coordination role, android "
    "host role, runtime presence, routability, capabilities, platform) MUST "
    "be normalised through normalize_scheduling_inputs() before being passed "
    "to build_capability_scheduling_basis().  Callers MUST NOT construct "
    "CapabilitySchedulingInput manually and bypass the normalisation layer."
)
"""Policy: scheduling inputs must flow through the normalisation function."""

SCHEDULING_BASIS_IS_POSTURE_AND_ROLE_DRIVEN_POLICY: str = (
    "CANONICAL_CAPABILITY_SCHEDULING_BASIS::POSTURE_AND_ROLE_DRIVEN_V1: "
    "The canonical scheduling basis is primarily driven by two signals: "
    "source_runtime_posture (PR-533/PR-1) and coordination_role (PR-538).  "
    "Capability signals, runtime presence, and android host role refine the "
    "eligible surfaces and scheduling weight but do not override the "
    "posture/role eligibility gate."
)
"""Policy: posture and coordination role are the primary scheduling gates."""


# ---------------------------------------------------------------------------
# ExecutionSurface enum
# ---------------------------------------------------------------------------


class ExecutionSurface(str, Enum):
    """Canonical set of execution surfaces a device may contribute to.

    Values
    ------
    LOCAL_HOST
        Local desktop / server machine.  The primary host running the
        OpenClawd agent.  Eligible when the device is the local host (i.e.,
        ``platform != 'android'`` and ``source_runtime_posture == 'join_runtime'``
        or the device is the source controller running locally).

    ANDROID_HOST
        Android device acting as a runtime host.  Eligible when the device
        has ``AndroidRuntimeHostRole.FULL_RUNTIME_HOST`` or
        ``PARTIAL_RUNTIME_HOST`` (PR-5) AND ``source_runtime_posture ==
        'join_runtime'``.

    REMOTE_DEVICE
        Any registered remote device that is routable.  Used when the device
        cannot join the local runtime but can receive dispatched sub-tasks
        via the handoff path (PR-3).

    UNAVAILABLE
        The device is not eligible for any execution surface in the current
        scheduling context.  Used as a safe placeholder so callers never
        receive an empty eligibility list without an explicit reason.
    """

    LOCAL_HOST = "local_host"
    ANDROID_HOST = "android_host"
    REMOTE_DEVICE = "remote_device"
    UNAVAILABLE = "unavailable"

    @classmethod
    def from_string(cls, value: str) -> "ExecutionSurface":
        """Return an :class:`ExecutionSurface` from a raw string,
        defaulting to :attr:`UNAVAILABLE` on unrecognised values.
        """
        try:
            return cls(str(value).lower())
        except (ValueError, AttributeError):
            return cls.UNAVAILABLE


# ---------------------------------------------------------------------------
# CapabilitySchedulingInput
# ---------------------------------------------------------------------------

# Canonical posture constants (consistent with PR-533 / PR-1).
_POSTURE_JOIN_RUNTIME = "join_runtime"
_POSTURE_CONTROL_ONLY = "control_only"

# Canonical coordination role constants (consistent with PR-538).
_ROLE_OBSERVER_ONLY = "observer_only"
_ROLE_JOINED_RUNTIME_PARTICIPANT = "joined_runtime_participant"
_ROLE_SOURCE_CONTROLLER = "source_controller"
_ROLE_TARGET_ONLY_EXECUTOR = "target_only_executor"
_ROLE_UNRESOLVED = "unresolved"

# Canonical Android host role constants (consistent with PR-5).
_ANDROID_ROLE_FULL_HOST = "full_runtime_host"
_ANDROID_ROLE_PARTIAL_HOST = "partial_runtime_host"
_ANDROID_ROLE_CONNECTED_ONLY = "connected_device_only"
_ANDROID_ROLE_UNCLASSIFIED = "unclassified"

# Platform identifier for Android devices.
_PLATFORM_ANDROID = "android"

# Android host roles that allow ANDROID_HOST surface eligibility.
_ANDROID_HOST_ELIGIBLE_ROLES = frozenset(
    {_ANDROID_ROLE_FULL_HOST, _ANDROID_ROLE_PARTIAL_HOST}
)


@dataclasses.dataclass
class CapabilitySchedulingInput:
    """Normalised collection of signals used to derive the scheduling basis.

    All fields have safe, conservative defaults so partially-populated
    inputs degrade gracefully rather than raising errors.

    Attributes
    ----------
    device_id:
        Stable unique identifier for the device/host being evaluated.
    source_runtime_posture:
        Canonical posture value from PR-533/PR-1.
        One of ``'join_runtime'`` or ``'control_only'``.  Defaults to
        ``'control_only'`` (the safe conservative value).
    coordination_role:
        Canonical coordination role from PR-538.
        One of the :class:`~core.multi_device_coordination_authority.CoordinationRole`
        string values.  Defaults to ``'unresolved'``.
    android_host_role:
        Canonical Android host role from PR-5.
        One of the :class:`~core.android_runtime_host.AndroidRuntimeHostRole`
        string values, or ``''`` when the device is not an Android device.
    is_runtime_host:
        ``True`` when the device has been marked as a runtime host (PR-5
        ``RegisteredRuntimeDevice.is_runtime_host``).
    runtime_present:
        ``True`` when the device is operationally present (online/busy in
        the canonical registry).
    routable:
        ``True`` when a live transport connection to the device exists.
    capabilities:
        List of capability identifier strings the device declares.
    platform:
        Platform string (e.g. ``'android'``, ``'darwin'``, ``'linux'``,
        ``'windows'``).  Used to distinguish Android from host platforms.
    metadata:
        Arbitrary additional signals the caller wishes to preserve in the
        basis record.  Not used for eligibility derivation.
    """

    device_id: str = ""
    source_runtime_posture: str = _POSTURE_CONTROL_ONLY
    coordination_role: str = _ROLE_UNRESOLVED
    android_host_role: str = ""
    is_runtime_host: bool = False
    runtime_present: bool = False
    routable: bool = False
    capabilities: List[str] = dataclasses.field(default_factory=list)
    platform: str = ""
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of all input signals."""
        return {
            "device_id": self.device_id,
            "source_runtime_posture": self.source_runtime_posture,
            "coordination_role": self.coordination_role,
            "android_host_role": self.android_host_role,
            "is_runtime_host": self.is_runtime_host,
            "runtime_present": self.runtime_present,
            "routable": self.routable,
            "capabilities": list(self.capabilities),
            "platform": self.platform,
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# CapabilitySchedulingBasis
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class CapabilitySchedulingBasis:
    """Derived canonical scheduling basis for a single device/host.

    Attributes
    ----------
    device_id:
        The device this basis was derived for.
    eligible_surfaces:
        Ordered list of :class:`ExecutionSurface` values the device is
        eligible for in the current scheduling context.  Empty implies
        ``UNAVAILABLE`` (the sentinel is always appended in that case).
    is_scheduling_eligible:
        ``True`` when at least one non-``UNAVAILABLE`` surface is eligible.
    scheduling_weight:
        Normalised weight in ``[0.0, 1.0]`` for use in priority ordering.
        Higher values indicate stronger scheduling preference.  This is a
        *hint* for later scheduling policy work; it does not replace a full
        scheduler.
    capability_signals:
        Dict mapping capability name → availability hint (``True``/``False``),
        reflecting which declared capabilities are considered active.
    ineligibility_reason:
        Human-readable explanation when ``is_scheduling_eligible`` is
        ``False``.  ``None`` when the device is eligible.
    basis_id:
        Stable unique identifier for this basis record (UUID-based).
    scheduling_authority:
        String reference to the authority sentinel for audit.
    """

    device_id: str = ""
    eligible_surfaces: List[ExecutionSurface] = dataclasses.field(
        default_factory=list
    )
    is_scheduling_eligible: bool = False
    scheduling_weight: float = 0.0
    capability_signals: Dict[str, bool] = dataclasses.field(default_factory=dict)
    ineligibility_reason: Optional[str] = None
    basis_id: str = dataclasses.field(
        default_factory=lambda: f"csb_{uuid.uuid4().hex[:12]}"
    )
    scheduling_authority: str = dataclasses.field(
        default=CANONICAL_CAPABILITY_SCHEDULING_BASIS_AUTHORITY
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the derived scheduling basis."""
        return {
            "device_id": self.device_id,
            "eligible_surfaces": [s.value for s in self.eligible_surfaces],
            "is_scheduling_eligible": self.is_scheduling_eligible,
            "scheduling_weight": self.scheduling_weight,
            "capability_signals": dict(self.capability_signals),
            "ineligibility_reason": self.ineligibility_reason,
            "basis_id": self.basis_id,
            "scheduling_authority": self.scheduling_authority,
            "pr6_sentinel": CANONICAL_CAPABILITY_SCHEDULING_BASIS_PR6_SENTINEL,
        }


# ---------------------------------------------------------------------------
# Input normalisation
# ---------------------------------------------------------------------------


def _safe_str(value: Any, default: str = "") -> str:
    """Return a stripped lower-case string, or *default* on None/exception."""
    try:
        return str(value).strip().lower() if value is not None else default
    except Exception:  # pragma: no cover
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    """Return a bool from *value*, falling back to *default* on error."""
    if isinstance(value, bool):
        return value
    try:
        return bool(value)
    except Exception:  # pragma: no cover
        return default


def _safe_list_of_str(value: Any) -> List[str]:
    """Return a list of strings from *value*, degrading gracefully."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if item is not None]
    if isinstance(value, str):
        return [value] if value else []
    return []


def _resolve_posture(raw: Any) -> str:
    """Resolve a raw posture hint to a canonical posture value.

    Unknown / ``None`` → ``'control_only'`` (safe conservative default).
    """
    normalised = _safe_str(raw, _POSTURE_CONTROL_ONLY)
    if normalised == _POSTURE_JOIN_RUNTIME:
        return _POSTURE_JOIN_RUNTIME
    return _POSTURE_CONTROL_ONLY


def _resolve_coordination_role(raw: Any) -> str:
    """Resolve a raw coordination role to a canonical role string.

    Unknown / ``None`` → ``'unresolved'``.
    """
    normalised = _safe_str(raw, _ROLE_UNRESOLVED)
    _KNOWN_ROLES = frozenset(
        {
            _ROLE_SOURCE_CONTROLLER,
            _ROLE_JOINED_RUNTIME_PARTICIPANT,
            _ROLE_TARGET_ONLY_EXECUTOR,
            _ROLE_OBSERVER_ONLY,
            _ROLE_UNRESOLVED,
        }
    )
    return normalised if normalised in _KNOWN_ROLES else _ROLE_UNRESOLVED


def _resolve_android_host_role(raw: Any) -> str:
    """Resolve a raw android host role string.

    Unknown / ``None`` → ``''`` (not an Android device).
    """
    if raw is None:
        return ""
    normalised = _safe_str(raw, "")
    _KNOWN_ANDROID_ROLES = frozenset(
        {
            _ANDROID_ROLE_FULL_HOST,
            _ANDROID_ROLE_PARTIAL_HOST,
            _ANDROID_ROLE_CONNECTED_ONLY,
            _ANDROID_ROLE_UNCLASSIFIED,
        }
    )
    return normalised if normalised in _KNOWN_ANDROID_ROLES else ""


def normalize_scheduling_inputs(device: Any) -> CapabilitySchedulingInput:
    """Produce a :class:`CapabilitySchedulingInput` from a device record.

    Accepts any object or dict with the following optional fields:

    - ``device_id`` / ``"device_id"``
    - ``source_runtime_posture``
    - ``coordination_role``
    - ``android_host_role``
    - ``is_runtime_host``
    - ``online`` / ``status``
    - ``connection_state`` / ``connected`` (routing liveness hint)
    - ``capabilities``
    - ``platform``

    All missing or invalid fields fall back to safe conservative defaults.
    The returned :class:`CapabilitySchedulingInput` is ready to pass to
    :func:`build_capability_scheduling_basis`.

    Args:
        device: ``RegisteredRuntimeDevice``-shaped object or dict.

    Returns:
        A fully populated :class:`CapabilitySchedulingInput`.
    """

    def _get(attr: str, dict_key: Optional[str] = None) -> Any:
        """Fetch from object attribute or dict key."""
        key = dict_key or attr
        if isinstance(device, dict):
            return device.get(key)
        return getattr(device, attr, None)

    # --- device_id ---
    device_id = _safe_str(_get("device_id"), "")

    # --- posture ---
    posture = _resolve_posture(_get("source_runtime_posture"))

    # --- coordination role ---
    coord_role = _resolve_coordination_role(_get("coordination_role"))

    # --- android host role ---
    android_role_raw = _get("android_host_role")
    # Try to resolve from AndroidRuntimeHostRole enum attribute if it's an enum.
    if android_role_raw is not None and hasattr(android_role_raw, "value"):
        android_role_raw = android_role_raw.value
    android_host_role = _resolve_android_host_role(android_role_raw)

    # --- is_runtime_host ---
    is_runtime_host = _safe_bool(_get("is_runtime_host"), False)

    # --- runtime_present (online / status) ---
    online_raw = _get("online")
    if online_raw is not None:
        runtime_present = _safe_bool(online_raw, False)
    else:
        status_raw = _safe_str(_get("status"), "offline")
        runtime_present = status_raw in ("online", "busy", "active")

    # --- routable (connection_state or connected flag) ---
    conn_state_raw = _safe_str(_get("connection_state"), "")
    if conn_state_raw:
        routable = conn_state_raw in ("connected", "active", "established")
    else:
        connected_raw = _get("connected")
        if connected_raw is not None:
            routable = _safe_bool(connected_raw, False)
        else:
            routable = runtime_present  # conservative: present implies routable

    # --- capabilities ---
    capabilities_raw = _get("capabilities")
    if capabilities_raw is None:
        # Try inner capabilities object.
        cap_obj = _get("capabilities")
        capabilities = []
    elif isinstance(capabilities_raw, dict):
        # Might be a CapabilityRuntimeState dict or similar; extract keys.
        capabilities = _safe_list_of_str(list(capabilities_raw.keys()))
    else:
        capabilities = _safe_list_of_str(capabilities_raw)

    # --- platform ---
    platform_raw = _get("platform")
    if platform_raw is not None and hasattr(platform_raw, "value"):
        platform_raw = platform_raw.value
    platform = _safe_str(platform_raw, "")

    # If the device is platform=android and no android_host_role was supplied,
    # infer CONNECTED_DEVICE_ONLY as a baseline (safer than empty).
    if platform == _PLATFORM_ANDROID and not android_host_role:
        android_host_role = _ANDROID_ROLE_CONNECTED_ONLY

    return CapabilitySchedulingInput(
        device_id=device_id,
        source_runtime_posture=posture,
        coordination_role=coord_role,
        android_host_role=android_host_role,
        is_runtime_host=is_runtime_host,
        runtime_present=runtime_present,
        routable=routable,
        capabilities=capabilities,
        platform=platform,
    )


# ---------------------------------------------------------------------------
# Scheduling basis derivation
# ---------------------------------------------------------------------------


def _capability_signals_from_list(capabilities: List[str]) -> Dict[str, bool]:
    """Build a capability signals dict from a list of capability names.

    Each named capability maps to ``True`` (declared present).
    """
    return {cap: True for cap in capabilities if cap}


def build_capability_scheduling_basis(
    inp: CapabilitySchedulingInput,
) -> CapabilitySchedulingBasis:
    """Derive the canonical :class:`CapabilitySchedulingBasis` from *inp*.

    Decision procedure
    ------------------
    1. **Observer-only gate** — if ``coordination_role == 'observer_only'``,
       the device is unconditionally ineligible for all surfaces.
       Policy: :data:`OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY`.

    2. **Capability signals** — collect declared capabilities into the
       ``capability_signals`` dict (name → ``True``).

    3. **LOCAL_HOST surface** — eligible when:
       - ``source_runtime_posture == 'join_runtime'`` AND
       - ``platform != 'android'`` (non-Android host) AND
       - ``runtime_present == True``.
       Policy: :data:`CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY`.

    4. **ANDROID_HOST surface** — eligible when:
       - ``platform == 'android'`` AND
       - ``android_host_role`` in ``{full_runtime_host, partial_runtime_host}`` AND
       - ``source_runtime_posture == 'join_runtime'``.
       Policy: :data:`ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY`.

    5. **REMOTE_DEVICE surface** — eligible when:
       - ``routable == True`` AND
       - ``coordination_role != 'observer_only'``.
       Note: even ``control_only`` devices may be routable remote dispatch
       targets; they just cannot join the local runtime themselves.

    6. **Scheduling weight** — computed as a normalised float:
       - FULL_RUNTIME_HOST Android: 0.9
       - PARTIAL_RUNTIME_HOST Android or LOCAL_HOST join_runtime: 0.75
       - REMOTE_DEVICE only (routable): 0.4
       - UNAVAILABLE: 0.0

    Args:
        inp: A :class:`CapabilitySchedulingInput` produced by
             :func:`normalize_scheduling_inputs`.

    Returns:
        A :class:`CapabilitySchedulingBasis` describing eligible surfaces
        and scheduling weight for the device.
    """
    device_id = inp.device_id
    cap_signals = _capability_signals_from_list(inp.capabilities)

    # ------------------------------------------------------------------
    # Gate 1: observer_only is unconditionally ineligible.
    # ------------------------------------------------------------------
    if inp.coordination_role == _ROLE_OBSERVER_ONLY:
        return CapabilitySchedulingBasis(
            device_id=device_id,
            eligible_surfaces=[ExecutionSurface.UNAVAILABLE],
            is_scheduling_eligible=False,
            scheduling_weight=0.0,
            capability_signals=cap_signals,
            ineligibility_reason=(
                f"observer_only coordination role blocks scheduling. "
                f"Policy: {OBSERVER_ONLY_EXCLUDED_FROM_SCHEDULING_POLICY}"
            ),
        )

    # ------------------------------------------------------------------
    # Derive eligible surfaces.
    # ------------------------------------------------------------------
    eligible: List[ExecutionSurface] = []

    is_android = inp.platform == _PLATFORM_ANDROID
    is_join_runtime = inp.source_runtime_posture == _POSTURE_JOIN_RUNTIME

    # --- LOCAL_HOST ---
    if is_join_runtime and not is_android and inp.runtime_present:
        eligible.append(ExecutionSurface.LOCAL_HOST)

    # --- ANDROID_HOST ---
    if (
        is_android
        and inp.android_host_role in _ANDROID_HOST_ELIGIBLE_ROLES
        and is_join_runtime
    ):
        eligible.append(ExecutionSurface.ANDROID_HOST)

    # --- REMOTE_DEVICE ---
    if inp.routable:
        eligible.append(ExecutionSurface.REMOTE_DEVICE)

    # ------------------------------------------------------------------
    # Derive scheduling weight.
    # ------------------------------------------------------------------
    weight = 0.0
    if ExecutionSurface.LOCAL_HOST in eligible:
        weight = 0.75
    if (
        ExecutionSurface.ANDROID_HOST in eligible
        and inp.android_host_role == _ANDROID_ROLE_FULL_HOST
    ):
        weight = 0.90
    elif (
        ExecutionSurface.ANDROID_HOST in eligible
        and inp.android_host_role == _ANDROID_ROLE_PARTIAL_HOST
    ):
        weight = max(weight, 0.75)
    elif not eligible:
        weight = 0.0
    elif ExecutionSurface.REMOTE_DEVICE in eligible and len(eligible) == 1:
        weight = 0.40

    # ------------------------------------------------------------------
    # Build result.
    # ------------------------------------------------------------------
    if not eligible:
        # Determine the most informative reason.
        if not inp.runtime_present and not inp.routable:
            reason = "device is offline and not routable"
        elif is_android and inp.android_host_role not in _ANDROID_HOST_ELIGIBLE_ROLES:
            reason = (
                f"Android device android_host_role='{inp.android_host_role}' is not "
                f"eligible for ANDROID_HOST surface.  "
                f"Policy: {ANDROID_HOST_REQUIRES_JOIN_RUNTIME_FOR_SCHEDULING_POLICY}"
            )
        elif not is_join_runtime:
            reason = (
                f"source_runtime_posture='control_only' excludes LOCAL_HOST scheduling "
                f"and device is not routable.  "
                f"Policy: {CONTROL_ONLY_SOURCE_EXCLUDED_FROM_LOCAL_SCHEDULING_POLICY}"
            )
        else:
            reason = "no eligible execution surface could be derived from available signals"

        return CapabilitySchedulingBasis(
            device_id=device_id,
            eligible_surfaces=[ExecutionSurface.UNAVAILABLE],
            is_scheduling_eligible=False,
            scheduling_weight=0.0,
            capability_signals=cap_signals,
            ineligibility_reason=reason,
        )

    return CapabilitySchedulingBasis(
        device_id=device_id,
        eligible_surfaces=eligible,
        is_scheduling_eligible=True,
        scheduling_weight=weight,
        capability_signals=cap_signals,
        ineligibility_reason=None,
    )


# ---------------------------------------------------------------------------
# Convenience: assess_scheduling_eligibility
# ---------------------------------------------------------------------------


def assess_scheduling_eligibility(
    device: Any,
) -> tuple:  # tuple[CapabilitySchedulingInput, CapabilitySchedulingBasis]
    """Assess the scheduling eligibility of a device-like object.

    This is a single-call convenience wrapper combining
    :func:`normalize_scheduling_inputs` and
    :func:`build_capability_scheduling_basis`.

    Args:
        device: ``RegisteredRuntimeDevice``-shaped object or dict.

    Returns:
        A ``(CapabilitySchedulingInput, CapabilitySchedulingBasis)`` pair.
    """
    inp = normalize_scheduling_inputs(device)
    basis = build_capability_scheduling_basis(inp)
    return inp, basis
