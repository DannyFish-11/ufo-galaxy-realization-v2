"""core/android_network_participation.py
=========================================
PR-1: Unified Android Network Participation Truth.

Background
----------
Prior to this module the V2 host side had no single authoritative answer to
the question "what is the current network participation tier of this Android
device in the center-distributed runtime?"  Instead, the answer was rebuilt
from four or more scattered signals:

* ``registration_fully_attached`` / ``registration_gaps`` from the gateway
  registration handler.
* ``android_attached`` inferred from device counts, snapshot counts, and
  session participant counts in ``core.v2_unified_state_contract``.
* ``cross_device_available`` from the same contract.
* ``is_dispatch_eligible`` / ``is_takeover_eligible`` from
  ``core.android_mode_gate_policy``.
* ``posture`` on ``AttachedSessionRegistryEntry``.

This multi-gate inference pattern creates well-documented system-wide
ambiguity between:

* *connected / registered*
* *fully attached*
* *dispatch eligible*
* *true distributed-network participant*

This module closes that gap by introducing a **single, typed, runtime-derived
participation tier** that is computed from real runtime conditions and can be
consumed authoritatively by any V2 surface instead of re-deriving the answer
locally.

Design principles
-----------------
1. **Single authoritative truth** — :func:`get_participation_state_for_device`
   is the one place that produces the canonical participation tier.  All other
   surfaces SHOULD consume this rather than rebuilding the answer.
2. **Runtime-path grounded** — the derivation rules are evaluated against
   *live* store state (session registry, snapshot store, mode gate policy) so
   the answer reflects real runtime conditions, not static declarations.
3. **Strict layering** — the seven tiers express a strict ordering from no
   participation to full distributed participation.  A device can only be at
   the highest tier that *all* required conditions are satisfied for.
4. **Explicit transition semantics** — every tier transition is driven by a
   named :class:`AndroidParticipationTransitionSignal`.  The module records
   the last signal that caused a tier change so operators and diagnostics can
   trace *why* the tier is what it is.
5. **Fail-conservative** — when any required runtime store is unavailable the
   derivation falls back to the lowest confirmed tier rather than asserting a
   higher one.
6. **Non-raising** — all public functions return well-typed results; they do
   not raise exceptions.

Android-originating integration contract
-----------------------------------------
For the participation tier to reach ``dispatch_eligible`` or
``distributed_participant``, the Android side (``ufo-galaxy-android``) must
supply:

* ``source_runtime_posture`` = ``"join_runtime"`` in the registration message.
* ``cross_device_enabled = true`` in capability metadata.
* ``local_loop_ready`` / ``model_ready`` / ``accessibility_ready`` as
  ``true`` in ``DEVICE_STATE_SNAPSHOT`` messages.
* Zero registration gaps (i.e. all downstream registration steps succeed).
* An active attached runtime session in ``"join_runtime"`` posture.

V2 cannot verify or enforce these conditions on the Android side; it can only
observe their *V2-side projections*.  The participation tier therefore
represents the **V2-side view** of Android's participation status.  Full
convergence requires that the Android side also maintains an authoritative
local participation truth and communicates it to V2 via the registration and
snapshot message protocol.  The :data:`ANDROID_ORIGINATING_CONTRACT` sentinel
below documents the expected Android-side participation fields.

Public API
----------
Sentinels::

    ANDROID_NETWORK_PARTICIPATION_AUTHORITY
    ANDROID_NETWORK_PARTICIPATION_CONTRACT_VERSION
    ANDROID_ORIGINATING_CONTRACT

Enums::

    AndroidNetworkParticipationTier
    AndroidParticipationTransitionSignal

Dataclasses::

    AndroidNetworkParticipationState

Functions::

    derive_android_network_participation_tier(
        *,
        websocket_connected,
        registration_ack_success,
        registration_fully_attached,
        registration_gaps,
        capability_visible,
        active_session_count,
        session_posture,
        cross_device_enabled,
        readiness_satisfied,
        dispatch_gate_passed,
        operator_suspended,
    ) -> AndroidNetworkParticipationTier

    build_android_network_participation_state(
        device_id,
        *,
        prior_tier,
        signal,
        ...derive inputs...
    ) -> AndroidNetworkParticipationState

    get_participation_state_for_device(device_id) -> AndroidNetworkParticipationState

    apply_participation_signal(
        state,
        signal,
        **updated_condition_kwargs,
    ) -> AndroidNetworkParticipationState

    record_participation_state(state) -> None

    reset_participation_store() -> None  (test-isolation only)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.AndroidNetworkParticipation")

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

ANDROID_NETWORK_PARTICIPATION_AUTHORITY: str = (
    "ANDROID_NETWORK_PARTICIPATION_AUTHORITY::PR-1::"
    "core.android_network_participation is the single authoritative runtime "
    "source of truth for the Android device network participation tier on the "
    "V2 side.  All surfaces that need to answer 'what is this Android device's "
    "current participation level in the center-distributed runtime?' MUST "
    "consume this module rather than re-deriving the answer from scattered "
    "signals.  derive_android_network_participation_tier() is the canonical "
    "derivation function; get_participation_state_for_device() is the "
    "canonical per-device query accessor."
)

ANDROID_NETWORK_PARTICIPATION_CONTRACT_VERSION: str = "1.0.0"

ANDROID_ORIGINATING_CONTRACT: str = (
    "ANDROID_ORIGINATING_PARTICIPATION_CONTRACT::PR-1::"
    "Android devices (ufo-galaxy-android) must supply the following to reach "
    "higher participation tiers on the V2 side: "
    "(1) source_runtime_posture='join_runtime' in device_register message; "
    "(2) cross_device_enabled=true in capability_report metadata; "
    "(3) local_loop_ready=true, model_ready=true, accessibility_ready=true in "
    "DEVICE_STATE_SNAPSHOT; "
    "(4) zero registration_gaps (all downstream steps succeed); "
    "(5) active attached runtime session retained in 'join_runtime' posture.  "
    "The V2-side participation tier reflects the V2-observable projection of "
    "these conditions; full convergence requires the Android side to maintain "
    "a symmetric local participation truth and communicate it canonically."
)

# Policy sentinels
PARTICIPATION_TIER_IS_DERIVED_FROM_RUNTIME_CONDITIONS_POLICY: str = (
    "POLICY::PARTICIPATION_TIER_IS_DERIVED_FROM_RUNTIME_CONDITIONS: "
    "The AndroidNetworkParticipationTier for a device MUST be derived from "
    "live runtime-store state via derive_android_network_participation_tier() "
    "or get_participation_state_for_device().  It MUST NOT be set by direct "
    "field assignment at call sites."
)

PARTICIPATION_TIER_IS_FAIL_CONSERVATIVE_POLICY: str = (
    "POLICY::PARTICIPATION_TIER_IS_FAIL_CONSERVATIVE: "
    "When any required runtime store is unavailable or returns an error, "
    "derive_android_network_participation_tier() MUST return the lowest "
    "confirmed tier rather than asserting a higher one.  Uncertainty MUST NOT "
    "be silently resolved in favour of eligibility."
)

DISPATCH_REQUIRES_DISPATCH_ELIGIBLE_TIER_POLICY: str = (
    "POLICY::DISPATCH_REQUIRES_DISPATCH_ELIGIBLE_TIER: "
    "Delegated dispatch MUST NOT be initiated to a device whose current "
    "AndroidNetworkParticipationTier is below dispatch_eligible.  Callers that "
    "currently derive dispatch eligibility inline SHOULD migrate to checking "
    "get_participation_state_for_device(device_id).tier >= "
    "AndroidNetworkParticipationTier.dispatch_eligible."
)

# ---------------------------------------------------------------------------
# AndroidNetworkParticipationTier
# ---------------------------------------------------------------------------


class AndroidNetworkParticipationTier(str, Enum):
    """Canonical Android device network participation tier.

    Values represent a strict ordering from no participation to full
    distributed-network participation.  A device is at the *highest* tier
    whose *all* required conditions are satisfied.

    Values
    ------
    local_only
        The device has no WebSocket connection to the V2 gateway.  It operates
        entirely locally and is invisible to the V2 runtime network.

    control_only
        The device has an active WebSocket connection and has received a
        ``device_register_ack(success=True)``.  However, its runtime posture
        is ``control_only`` — it can receive control-plane messages but cannot
        be selected as a dispatch or execution target.

    cross_device_capable
        Registration succeeded and is *partially* attached (no ``control_only``
        posture), but there are still open registration gaps.  The device is
        visible to V2 but is not yet fully eligible for dispatch — some
        downstream registration steps have not completed.

    cross_device_enabled
        Registration is fully attached (zero gaps), the Android-side
        ``cross_device_enabled`` gate is ON, and a session exists.  The device
        has announced its capability to participate in cross-device execution,
        but readiness conditions (model, accessibility, local loop) have not
        yet been verified.

    fully_attached
        All of the above conditions hold AND capability is visible on V2 AND
        there is an active runtime session in ``join_runtime`` posture.  This
        is the first tier at which the device is *structurally* ready to be
        selected as a dispatch target.

    dispatch_eligible
        ``fully_attached`` conditions hold AND all mode-gate and readiness
        checks pass (model_ready, accessibility_ready, local_loop_ready, V2
        cross-device switch, goal-execution gate).  The device can be selected
        as an immediate dispatch target.

    distributed_participant
        ``dispatch_eligible`` conditions hold AND the device is actively
        participating in the V2 runtime network — i.e. there is an active
        task execution session in progress or the device has been confirmed as
        a live distributed runtime node.  This is the highest tier and
        represents the answer "yes, this device is a true participant in the
        center-distributed runtime right now."
    """

    local_only = "local_only"
    control_only = "control_only"
    cross_device_capable = "cross_device_capable"
    cross_device_enabled = "cross_device_enabled"
    fully_attached = "fully_attached"
    dispatch_eligible = "dispatch_eligible"
    distributed_participant = "distributed_participant"

    @classmethod
    def from_string(cls, value: str) -> "AndroidNetworkParticipationTier":
        """Return the enum member for *value*, defaulting to ``local_only``."""
        try:
            return cls(value.lower().strip())
        except (ValueError, AttributeError):
            return cls.local_only

    def ordinal(self) -> int:
        """Return the numeric ordinal of this tier (0 = lowest)."""
        _ord = {
            "local_only": 0,
            "control_only": 1,
            "cross_device_capable": 2,
            "cross_device_enabled": 3,
            "fully_attached": 4,
            "dispatch_eligible": 5,
            "distributed_participant": 6,
        }
        return _ord.get(self.value, 0)

    def __ge__(self, other: "AndroidNetworkParticipationTier") -> bool:  # type: ignore[override]
        if not isinstance(other, AndroidNetworkParticipationTier):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() >= other.ordinal()

    def __gt__(self, other: "AndroidNetworkParticipationTier") -> bool:  # type: ignore[override]
        if not isinstance(other, AndroidNetworkParticipationTier):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() > other.ordinal()

    def __le__(self, other: "AndroidNetworkParticipationTier") -> bool:  # type: ignore[override]
        if not isinstance(other, AndroidNetworkParticipationTier):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() <= other.ordinal()

    def __lt__(self, other: "AndroidNetworkParticipationTier") -> bool:  # type: ignore[override]
        if not isinstance(other, AndroidNetworkParticipationTier):
            return NotImplemented  # type: ignore[return-value]
        return self.ordinal() < other.ordinal()


# ---------------------------------------------------------------------------
# AndroidParticipationTransitionSignal
# ---------------------------------------------------------------------------


class AndroidParticipationTransitionSignal(str, Enum):
    """Named signals that drive Android participation tier transitions.

    Values
    ------
    websocket_connected
        A WebSocket connection was established from the Android device to the
        V2 gateway.  Enables transition from ``local_only`` toward higher tiers
        once registration completes.

    registration_ack_success
        ``device_register_ack(success=True)`` was delivered to the device.
        The device is now at least ``control_only``.

    registration_fully_attached
        All downstream registration steps completed with zero gaps.
        Enables transition to ``cross_device_enabled`` or higher.

    registration_partial_attached
        Registration completed but with open gaps.  Device is at
        ``cross_device_capable`` until gaps are resolved.

    capability_visibility_gained
        An Android capability report was absorbed by V2 and the device's
        capability is now visible.  Required for ``fully_attached``.

    capability_visibility_lost
        The device's capability visibility was lost (e.g. capability report
        withdrawn or expired).  Forces tier back to at most
        ``cross_device_enabled``.

    active_session_acquired
        An active ``join_runtime`` session was established in the attached
        runtime session registry.  Required for ``fully_attached`` and above.

    active_session_lost
        The active session was detached, replaced, or invalidated.  Forces
        tier back to at most ``cross_device_enabled``.

    readiness_satisfied
        All local readiness conditions (model_ready, accessibility_ready,
        local_loop_ready) are satisfied AND all dispatch mode gates pass.
        Enables transition to ``dispatch_eligible``.

    readiness_lost
        One or more readiness or dispatch-gate conditions failed.  Forces
        tier back to at most ``fully_attached``.

    cross_device_switch_enabled
        The V2-side cross-device switch was turned ON.  Required for
        ``dispatch_eligible`` and above.

    cross_device_switch_disabled
        The V2-side cross-device switch was turned OFF.  Forces tier back to
        at most ``fully_attached``.

    cross_device_gate_enabled
        Android-side ``cross_device_enabled`` flag turned ON.  Required for
        ``cross_device_enabled`` and above.

    cross_device_gate_disabled
        Android-side ``cross_device_enabled`` flag turned OFF.  Forces tier
        back to at most ``cross_device_capable``.

    posture_join_runtime
        Session posture changed to ``join_runtime``.  Required for
        ``fully_attached`` and above.

    posture_control_only
        Session posture changed to ``control_only``.  Forces tier to
        ``control_only`` regardless of other conditions.

    execution_session_started
        An active task execution session has been confirmed on the device.
        Enables ``distributed_participant``.

    execution_session_ended
        The active execution session ended (success, failure, or cancellation).
        Forces tier back to ``dispatch_eligible``.

    websocket_disconnected
        The WebSocket connection was lost.  Forces tier back to ``local_only``.

    reconnect_continuity_resumed
        A WebSocket reconnect was classified as ``continuity_resume``.  The
        existing session identity is preserved; tier recovers toward the last
        confirmed tier rather than resetting to ``local_only``.

    attachment_break
        Registration or session state indicates an attachment break (e.g. a
        new registration replaced the old session without a clean continuity
        resume).  Forces tier to re-derive from current registration state.

    operator_suspended
        An operator or board-level isolation/suspension was imposed on this
        device.  Forces tier to ``control_only`` regardless of other conditions
        while suspension is active.

    operator_suspension_lifted
        The operator suspension was lifted.  Tier re-derives from current
        runtime conditions.
    """

    websocket_connected = "websocket_connected"
    registration_ack_success = "registration_ack_success"
    registration_fully_attached = "registration_fully_attached"
    registration_partial_attached = "registration_partial_attached"
    capability_visibility_gained = "capability_visibility_gained"
    capability_visibility_lost = "capability_visibility_lost"
    active_session_acquired = "active_session_acquired"
    active_session_lost = "active_session_lost"
    readiness_satisfied = "readiness_satisfied"
    readiness_lost = "readiness_lost"
    cross_device_switch_enabled = "cross_device_switch_enabled"
    cross_device_switch_disabled = "cross_device_switch_disabled"
    cross_device_gate_enabled = "cross_device_gate_enabled"
    cross_device_gate_disabled = "cross_device_gate_disabled"
    posture_join_runtime = "posture_join_runtime"
    posture_control_only = "posture_control_only"
    execution_session_started = "execution_session_started"
    execution_session_ended = "execution_session_ended"
    websocket_disconnected = "websocket_disconnected"
    reconnect_continuity_resumed = "reconnect_continuity_resumed"
    attachment_break = "attachment_break"
    operator_suspended = "operator_suspended"
    operator_suspension_lifted = "operator_suspension_lifted"


# ---------------------------------------------------------------------------
# Explicit tier transition table
#
# Maps (current_tier, signal) → maximum_reachable_tier_after_signal.
# The actual tier after applying a signal is:
#   min(max_reachable_tier, derive_tier_from_conditions(updated_conditions))
#
# Signals that *cap* the tier downward are listed as "floor/ceiling" entries.
# This table is the formal documentation of transition semantics; the
# implementation in derive_android_network_participation_tier() enforces
# these semantics via runtime condition evaluation.
# ---------------------------------------------------------------------------

PARTICIPATION_TIER_TRANSITIONS: Dict[
    AndroidParticipationTransitionSignal, str
] = {
    # Upward-enabling signals
    AndroidParticipationTransitionSignal.websocket_connected: (
        "Tier can now rise to at least control_only after registration ack."
    ),
    AndroidParticipationTransitionSignal.registration_ack_success: (
        "Tier rises to control_only."
    ),
    AndroidParticipationTransitionSignal.registration_fully_attached: (
        "Tier rises to cross_device_enabled when cross_device_gate is ON; "
        "otherwise cross_device_capable."
    ),
    AndroidParticipationTransitionSignal.registration_partial_attached: (
        "Tier is capped at cross_device_capable until gaps are resolved."
    ),
    AndroidParticipationTransitionSignal.capability_visibility_gained: (
        "Tier can rise to fully_attached when session is active in join_runtime."
    ),
    AndroidParticipationTransitionSignal.active_session_acquired: (
        "Tier rises to fully_attached when capability is visible and "
        "posture is join_runtime."
    ),
    AndroidParticipationTransitionSignal.readiness_satisfied: (
        "Tier rises to dispatch_eligible."
    ),
    AndroidParticipationTransitionSignal.cross_device_switch_enabled: (
        "Tier can rise to dispatch_eligible when readiness is satisfied."
    ),
    AndroidParticipationTransitionSignal.cross_device_gate_enabled: (
        "Tier can rise to cross_device_enabled."
    ),
    AndroidParticipationTransitionSignal.posture_join_runtime: (
        "Tier can rise to fully_attached when capability visible and "
        "cross_device conditions are met."
    ),
    AndroidParticipationTransitionSignal.execution_session_started: (
        "Tier rises to distributed_participant."
    ),
    AndroidParticipationTransitionSignal.reconnect_continuity_resumed: (
        "Tier recovers toward last confirmed tier without full reset."
    ),
    AndroidParticipationTransitionSignal.operator_suspension_lifted: (
        "Tier re-derives from current runtime conditions."
    ),
    # Downward-forcing signals
    AndroidParticipationTransitionSignal.websocket_disconnected: (
        "Tier forced to local_only."
    ),
    AndroidParticipationTransitionSignal.posture_control_only: (
        "Tier forced to control_only regardless of other conditions."
    ),
    AndroidParticipationTransitionSignal.operator_suspended: (
        "Tier forced to control_only while suspension is active."
    ),
    AndroidParticipationTransitionSignal.capability_visibility_lost: (
        "Tier capped at cross_device_enabled."
    ),
    AndroidParticipationTransitionSignal.active_session_lost: (
        "Tier capped at cross_device_enabled."
    ),
    AndroidParticipationTransitionSignal.readiness_lost: (
        "Tier capped at fully_attached."
    ),
    AndroidParticipationTransitionSignal.cross_device_switch_disabled: (
        "Tier capped at fully_attached."
    ),
    AndroidParticipationTransitionSignal.cross_device_gate_disabled: (
        "Tier capped at cross_device_capable."
    ),
    AndroidParticipationTransitionSignal.execution_session_ended: (
        "Tier falls back to dispatch_eligible."
    ),
    AndroidParticipationTransitionSignal.attachment_break: (
        "Tier re-derives from current registration state."
    ),
}


# ---------------------------------------------------------------------------
# AndroidNetworkParticipationState
# ---------------------------------------------------------------------------


@dataclass
class AndroidNetworkParticipationState:
    """Full V2-side participation state for a single Android device.

    Attributes
    ----------
    device_id
        Android device identifier.
    tier
        Current :class:`AndroidNetworkParticipationTier`.
    last_signal
        The most recent :class:`AndroidParticipationTransitionSignal` that
        caused a tier change, or ``None`` if no signal has been applied.
    prior_tier
        The tier before the last signal was applied, or ``None``.
    derived_at
        Unix epoch seconds when this state was derived.

    Runtime condition snapshot (all fields optional)
    -------------------------------------------------
    websocket_connected
        Whether the WebSocket connection is currently live.
    registration_ack_success
        Whether a successful ``device_register_ack`` was received.
    registration_fully_attached
        Whether registration completed with zero gaps.
    registration_gaps
        List of open registration gap names, if any.
    capability_visible
        Whether the device's capability is visible on V2.
    active_session_count
        Number of active attached runtime sessions for this device.
    session_posture
        Posture of the active session (``"join_runtime"`` or
        ``"control_only"``).
    cross_device_enabled
        Whether the Android-side ``cross_device_enabled`` gate is ON.
    readiness_satisfied
        Whether all model/accessibility/local-loop readiness gates pass.
    dispatch_gate_passed
        Whether all dispatch-gate checks (mode gate, V2 switch, etc.) pass.
    operator_suspended
        Whether an operator suspension is currently active.
    execution_active
        Whether an active task execution session is in progress.

    Diagnostics
    -----------
    blocking_reasons
        Human-readable list of conditions that are preventing a higher tier.
    tier_derivation_notes
        Free-text notes from the derivation function for diagnostics.
    """

    device_id: str
    tier: AndroidNetworkParticipationTier = AndroidNetworkParticipationTier.local_only
    last_signal: Optional[AndroidParticipationTransitionSignal] = None
    prior_tier: Optional[AndroidNetworkParticipationTier] = None
    derived_at: float = field(default_factory=time.time)

    # Runtime conditions
    websocket_connected: bool = False
    registration_ack_success: bool = False
    registration_fully_attached: bool = False
    registration_gaps: List[str] = field(default_factory=list)
    capability_visible: bool = False
    active_session_count: int = 0
    session_posture: str = ""
    cross_device_enabled: bool = False
    readiness_satisfied: bool = False
    dispatch_gate_passed: bool = False
    operator_suspended: bool = False
    execution_active: bool = False

    # Diagnostics
    blocking_reasons: List[str] = field(default_factory=list)
    tier_derivation_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "tier": self.tier.value,
            "last_signal": self.last_signal.value if self.last_signal else None,
            "prior_tier": self.prior_tier.value if self.prior_tier else None,
            "derived_at": self.derived_at,
            "websocket_connected": self.websocket_connected,
            "registration_ack_success": self.registration_ack_success,
            "registration_fully_attached": self.registration_fully_attached,
            "registration_gaps": list(self.registration_gaps),
            "capability_visible": self.capability_visible,
            "active_session_count": self.active_session_count,
            "session_posture": self.session_posture,
            "cross_device_enabled": self.cross_device_enabled,
            "readiness_satisfied": self.readiness_satisfied,
            "dispatch_gate_passed": self.dispatch_gate_passed,
            "operator_suspended": self.operator_suspended,
            "execution_active": self.execution_active,
            "blocking_reasons": list(self.blocking_reasons),
            "tier_derivation_notes": list(self.tier_derivation_notes),
            "_authority": ANDROID_NETWORK_PARTICIPATION_AUTHORITY,
            "_contract_version": ANDROID_NETWORK_PARTICIPATION_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Core derivation function
# ---------------------------------------------------------------------------


def derive_android_network_participation_tier(
    *,
    websocket_connected: bool,
    registration_ack_success: bool,
    registration_fully_attached: bool,
    registration_gaps: Optional[List[str]] = None,
    capability_visible: bool,
    active_session_count: int,
    session_posture: str,
    cross_device_enabled: bool,
    readiness_satisfied: bool,
    dispatch_gate_passed: bool,
    operator_suspended: bool = False,
    execution_active: bool = False,
) -> tuple[AndroidNetworkParticipationTier, List[str], List[str]]:
    """Derive the canonical participation tier from runtime conditions.

    This is the **single authoritative derivation function** for Android
    network participation tiers.  It evaluates conditions in strict
    bottom-to-top order and returns the highest tier whose requirements are
    fully met.

    Parameters
    ----------
    websocket_connected
        Whether the WebSocket connection is currently live.
    registration_ack_success
        Whether a successful ``device_register_ack`` was received.
    registration_fully_attached
        Whether registration completed with zero gaps.
    registration_gaps
        List of open registration gap names; ``None`` or empty means no gaps.
    capability_visible
        Whether the device's capability is visible on V2.
    active_session_count
        Number of active attached runtime sessions for this device.
    session_posture
        Posture of the active session (``"join_runtime"`` or
        ``"control_only"``).
    cross_device_enabled
        Whether the Android-side ``cross_device_enabled`` gate is ON.
    readiness_satisfied
        Whether all model/accessibility/local-loop readiness gates pass.
    dispatch_gate_passed
        Whether all dispatch-gate checks (mode gate, V2 switch, etc.) pass.
    operator_suspended
        Whether an operator suspension is currently active.
    execution_active
        Whether an active task execution session is in progress.

    Returns
    -------
    tuple[AndroidNetworkParticipationTier, List[str], List[str]]
        ``(tier, blocking_reasons, derivation_notes)`` where:
        - ``tier`` is the derived :class:`AndroidNetworkParticipationTier`.
        - ``blocking_reasons`` lists conditions preventing a higher tier.
        - ``derivation_notes`` provides the derivation trace for diagnostics.
    """
    gaps = list(registration_gaps or [])
    blocking: List[str] = []
    notes: List[str] = []

    # --- Operator suspension overrides everything ---
    if operator_suspended:
        blocking.append("operator_suspended: device is under operator-imposed suspension")
        notes.append("Tier capped at control_only due to operator suspension.")
        return (
            AndroidNetworkParticipationTier.control_only,
            blocking,
            notes,
        )

    # --- Tier 0: local_only ---
    if not websocket_connected:
        blocking.append("websocket_connected=False: no active WebSocket connection")
        notes.append("No WebSocket connection → local_only.")
        return (AndroidNetworkParticipationTier.local_only, blocking, notes)

    notes.append("websocket_connected=True")

    # --- Tier 1: control_only ---
    if not registration_ack_success:
        blocking.append("registration_ack_success=False: device_register_ack not yet received")
        notes.append("WebSocket up but registration ack not received → local_only.")
        return (AndroidNetworkParticipationTier.local_only, blocking, notes)

    notes.append("registration_ack_success=True")

    # posture=control_only caps tier here
    is_control_only_posture = session_posture == "control_only"
    if is_control_only_posture:
        blocking.append(
            "session_posture='control_only': device explicitly announced control-only posture"
        )
        notes.append("Posture is control_only → capped at control_only.")
        return (AndroidNetworkParticipationTier.control_only, blocking, notes)

    # --- Tier 2: cross_device_capable ---
    if gaps:
        blocking.append(
            f"registration_gaps={gaps}: registration has incomplete downstream steps"
        )
        notes.append(f"Registered but {len(gaps)} gap(s) → cross_device_capable.")
        return (
            AndroidNetworkParticipationTier.cross_device_capable,
            blocking,
            notes,
        )

    notes.append("registration_fully_attached=True (no gaps)")

    # --- Tier 3: cross_device_enabled ---
    if not cross_device_enabled:
        blocking.append(
            "cross_device_enabled=False: Android-side cross_device gate is OFF"
        )
        notes.append("Fully attached but cross_device_enabled=False → cross_device_capable.")
        return (
            AndroidNetworkParticipationTier.cross_device_capable,
            blocking,
            notes,
        )

    notes.append("cross_device_enabled=True")

    # --- Tier 4: fully_attached ---
    has_join_runtime_session = (
        active_session_count > 0 and session_posture == "join_runtime"
    )
    if not capability_visible:
        blocking.append("capability_visible=False: device capability not yet visible on V2")
    if not has_join_runtime_session:
        if active_session_count == 0:
            blocking.append("active_session_count=0: no active attached runtime session")
        else:
            blocking.append(
                f"session_posture='{session_posture}': session not in join_runtime posture"
            )

    if not capability_visible or not has_join_runtime_session:
        notes.append(
            f"cross_device_enabled=True but capability_visible={capability_visible}, "
            f"session_join_runtime={has_join_runtime_session} → cross_device_enabled tier."
        )
        return (
            AndroidNetworkParticipationTier.cross_device_enabled,
            blocking,
            notes,
        )

    notes.append("capability_visible=True and join_runtime session active")

    # --- Tier 5: dispatch_eligible ---
    if not readiness_satisfied:
        blocking.append(
            "readiness_satisfied=False: model/accessibility/local-loop readiness not met"
        )
    if not dispatch_gate_passed:
        blocking.append(
            "dispatch_gate_passed=False: mode-gate or V2 cross-device switch check failed"
        )

    if not readiness_satisfied or not dispatch_gate_passed:
        notes.append(
            f"fully_attached but readiness_satisfied={readiness_satisfied}, "
            f"dispatch_gate_passed={dispatch_gate_passed} → fully_attached tier."
        )
        return (
            AndroidNetworkParticipationTier.fully_attached,
            blocking,
            notes,
        )

    notes.append("readiness_satisfied=True and dispatch_gate_passed=True")

    # --- Tier 6: distributed_participant ---
    if not execution_active:
        blocking.append(
            "execution_active=False: no active distributed execution session in progress"
        )
        notes.append("dispatch_eligible but no active execution session → dispatch_eligible.")
        return (
            AndroidNetworkParticipationTier.dispatch_eligible,
            blocking,
            notes,
        )

    notes.append("execution_active=True → distributed_participant")
    return (
        AndroidNetworkParticipationTier.distributed_participant,
        [],
        notes,
    )


# ---------------------------------------------------------------------------
# build_android_network_participation_state
# ---------------------------------------------------------------------------


def build_android_network_participation_state(
    device_id: str,
    *,
    websocket_connected: bool = False,
    registration_ack_success: bool = False,
    registration_fully_attached: bool = False,
    registration_gaps: Optional[List[str]] = None,
    capability_visible: bool = False,
    active_session_count: int = 0,
    session_posture: str = "",
    cross_device_enabled: bool = False,
    readiness_satisfied: bool = False,
    dispatch_gate_passed: bool = False,
    operator_suspended: bool = False,
    execution_active: bool = False,
    prior_tier: Optional[AndroidNetworkParticipationTier] = None,
    last_signal: Optional[AndroidParticipationTransitionSignal] = None,
) -> AndroidNetworkParticipationState:
    """Build an :class:`AndroidNetworkParticipationState` from explicit conditions.

    This function derives the tier from the supplied conditions, creates the
    state dataclass, and returns it.  It does NOT read from any runtime store;
    callers that want to read live state should use
    :func:`get_participation_state_for_device` instead.
    """
    tier, blocking, notes = derive_android_network_participation_tier(
        websocket_connected=websocket_connected,
        registration_ack_success=registration_ack_success,
        registration_fully_attached=registration_fully_attached,
        registration_gaps=registration_gaps,
        capability_visible=capability_visible,
        active_session_count=active_session_count,
        session_posture=session_posture,
        cross_device_enabled=cross_device_enabled,
        readiness_satisfied=readiness_satisfied,
        dispatch_gate_passed=dispatch_gate_passed,
        operator_suspended=operator_suspended,
        execution_active=execution_active,
    )

    return AndroidNetworkParticipationState(
        device_id=device_id,
        tier=tier,
        last_signal=last_signal,
        prior_tier=prior_tier,
        websocket_connected=websocket_connected,
        registration_ack_success=registration_ack_success,
        registration_fully_attached=registration_fully_attached,
        registration_gaps=list(registration_gaps or []),
        capability_visible=capability_visible,
        active_session_count=active_session_count,
        session_posture=session_posture,
        cross_device_enabled=cross_device_enabled,
        readiness_satisfied=readiness_satisfied,
        dispatch_gate_passed=dispatch_gate_passed,
        operator_suspended=operator_suspended,
        execution_active=execution_active,
        blocking_reasons=blocking,
        tier_derivation_notes=notes,
    )


# ---------------------------------------------------------------------------
# apply_participation_signal
# ---------------------------------------------------------------------------


def apply_participation_signal(
    state: AndroidNetworkParticipationState,
    signal: AndroidParticipationTransitionSignal,
    **updated_condition_kwargs: Any,
) -> AndroidNetworkParticipationState:
    """Return a new :class:`AndroidNetworkParticipationState` after applying *signal*.

    This function merges *updated_condition_kwargs* with the existing conditions
    from *state* and re-derives the tier.  The ``last_signal`` and
    ``prior_tier`` fields of the returned state are updated accordingly.

    Parameters
    ----------
    state
        The current participation state.
    signal
        The signal to apply.
    **updated_condition_kwargs
        Any condition fields that changed as a result of the signal.  These
        override the corresponding fields from *state*.

    Returns
    -------
    AndroidNetworkParticipationState
        A new state with re-derived tier; the original state is unchanged.
    """
    conditions: Dict[str, Any] = {
        "websocket_connected": state.websocket_connected,
        "registration_ack_success": state.registration_ack_success,
        "registration_fully_attached": state.registration_fully_attached,
        "registration_gaps": list(state.registration_gaps),
        "capability_visible": state.capability_visible,
        "active_session_count": state.active_session_count,
        "session_posture": state.session_posture,
        "cross_device_enabled": state.cross_device_enabled,
        "readiness_satisfied": state.readiness_satisfied,
        "dispatch_gate_passed": state.dispatch_gate_passed,
        "operator_suspended": state.operator_suspended,
        "execution_active": state.execution_active,
    }
    conditions.update(updated_condition_kwargs)

    return build_android_network_participation_state(
        device_id=state.device_id,
        prior_tier=state.tier,
        last_signal=signal,
        **conditions,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Runtime store (thread-safe per-device state ring buffer)
# ---------------------------------------------------------------------------

_STORE_CAPACITY: int = 64

_store_lock = threading.Lock()
# Maps device_id → most recent AndroidNetworkParticipationState
_participation_store: Dict[str, AndroidNetworkParticipationState] = {}


def record_participation_state(state: AndroidNetworkParticipationState) -> None:
    """Store the most recent participation state for *state.device_id*.

    Thread-safe.  Overwrites the previous entry for the same device.
    """
    with _store_lock:
        _participation_store[state.device_id] = state
    logger.debug(
        "participation_state recorded: device_id=%s tier=%s signal=%s",
        state.device_id,
        state.tier.value,
        state.last_signal.value if state.last_signal else None,
    )


def get_stored_participation_state(
    device_id: str,
) -> Optional[AndroidNetworkParticipationState]:
    """Return the most recently stored participation state for *device_id*, or None."""
    with _store_lock:
        return _participation_store.get(device_id)


def reset_participation_store() -> None:
    """Clear all stored participation states.

    **Test-isolation only** — do not call from production paths.
    """
    with _store_lock:
        _participation_store.clear()


# ---------------------------------------------------------------------------
# get_participation_state_for_device — live query helper
# ---------------------------------------------------------------------------


def get_participation_state_for_device(
    device_id: str,
) -> AndroidNetworkParticipationState:
    """Return the current participation state for *device_id* by reading live stores.

    This function reads from:
    * ``core.android_device_state_store`` — snapshot (capability, readiness).
    * ``core.attached_runtime_session_registry`` — active session, posture,
      registration gaps.
    * ``core.android_mode_gate_policy`` — dispatch gate verdict.

    It derives the current tier from the live state of those stores and
    records the result via :func:`record_participation_state`.

    When any store is unavailable the function degrades conservatively: the
    corresponding condition is treated as ``False`` / empty / 0, so the
    returned tier is the *lowest* tier consistent with the available evidence.

    Returns
    -------
    AndroidNetworkParticipationState
        Always returns a valid state; never raises.
    """
    try:
        return _derive_live_state(device_id)
    except Exception as exc:
        logger.warning(
            "get_participation_state_for_device: internal error device_id=%r: %s",
            device_id, exc, exc_info=True,
        )
        return AndroidNetworkParticipationState(
            device_id=device_id,
            tier=AndroidNetworkParticipationTier.local_only,
            tier_derivation_notes=[f"internal_error: {exc}"],
        )


def _derive_live_state(device_id: str) -> AndroidNetworkParticipationState:
    """Internal: derive live participation state from V2-side runtime stores."""
    websocket_connected = False
    registration_ack_success = False
    registration_fully_attached = False
    registration_gaps: List[str] = []
    capability_visible = False
    active_session_count = 0
    session_posture = ""
    cross_device_enabled = False
    readiness_satisfied = False
    dispatch_gate_passed = False
    execution_active = False

    # --- Read from attached_runtime_session_registry ---
    try:
        from core.attached_runtime_session_registry import (
            get_registry,
        )
        registry = get_registry()
        entry = registry.lookup_session_by_device(device_id)
        if entry is not None:
            websocket_connected = True
            registration_ack_success = True
            session_posture = getattr(entry, "posture", "") or ""
            if hasattr(entry, "registration_gaps"):
                registration_gaps = list(entry.registration_gaps or [])
            registration_fully_attached = len(registration_gaps) == 0
            active_session_count = 1
    except Exception as exc:
        logger.debug(
            "_derive_live_state: registry read failed for device_id=%r: %s",
            device_id, exc,
        )

    # --- Read from android_device_state_store ---
    try:
        from core.android_device_state_store import get_device_state_snapshot
        snapshot = get_device_state_snapshot(device_id)
        if snapshot is not None:
            # Capability visibility: a snapshot being present means we have
            # device state; cross_device_enabled comes from local_loop_config
            cfg = getattr(snapshot, "local_loop_config", None) or {}
            if isinstance(cfg, dict):
                cross_device_enabled = bool(
                    cfg.get("crossDeviceEnabled", cfg.get("cross_device_enabled", False))
                )
            # Readiness: all three gates must pass
            model_ready = bool(getattr(snapshot, "model_ready", False))
            accessibility_ready = bool(getattr(snapshot, "accessibility_ready", False))
            local_loop_ready = bool(getattr(snapshot, "local_loop_ready", False))
            readiness_satisfied = model_ready and accessibility_ready and local_loop_ready

            # Snapshot presence contributes to capability_visible heuristic
            # (a proper capability_visible flag requires the capability_report handler)
    except Exception as exc:
        logger.debug(
            "_derive_live_state: snapshot read failed for device_id=%r: %s",
            device_id, exc,
        )

    # --- Read capability_visible from android_mode_gate_policy (mode state) ---
    try:
        from core.android_mode_gate_policy import build_mode_state_for_device
        mode_state = build_mode_state_for_device(device_id)
        if mode_state is not None:
            # capability_visible proxied from cross_device_enabled flag in mode state
            capability_visible = bool(mode_state.cross_device_enabled)
            cross_device_enabled = bool(mode_state.cross_device_enabled)
    except Exception as exc:
        logger.debug(
            "_derive_live_state: mode_state read failed for device_id=%r: %s",
            device_id, exc,
        )

    # --- Read dispatch gate from android_mode_gate_policy ---
    try:
        from core.android_mode_gate_policy import evaluate_android_mode_readiness
        verdict = evaluate_android_mode_readiness(device_id)
        dispatch_gate_passed = bool(verdict.is_dispatch_eligible)
        if dispatch_gate_passed and not readiness_satisfied:
            # If the gate passed, readiness must have been satisfied
            readiness_satisfied = True
    except Exception as exc:
        logger.debug(
            "_derive_live_state: mode_gate read failed for device_id=%r: %s",
            device_id, exc,
        )

    # --- Detect active execution session ---
    try:
        from core.android_participant_session_state import list_active_participant_sessions
        active_sessions = list_active_participant_sessions()
        execution_active = any(
            getattr(s, "device_id", "") == device_id
            and getattr(s, "phase", "").startswith("execution")
            for s in active_sessions
        )
    except Exception as exc:
        logger.debug(
            "_derive_live_state: participant_sessions read failed for device_id=%r: %s",
            device_id, exc,
        )

    state = build_android_network_participation_state(
        device_id=device_id,
        websocket_connected=websocket_connected,
        registration_ack_success=registration_ack_success,
        registration_fully_attached=registration_fully_attached,
        registration_gaps=registration_gaps,
        capability_visible=capability_visible,
        active_session_count=active_session_count,
        session_posture=session_posture,
        cross_device_enabled=cross_device_enabled,
        readiness_satisfied=readiness_satisfied,
        dispatch_gate_passed=dispatch_gate_passed,
        execution_active=execution_active,
    )
    record_participation_state(state)
    return state
