"""
core.desktop_presence_system — Formal Desktop Presence System
=============================================================

Builds a product-level desktop presence layer on top of the runtime tri-state.
This layer is intentionally distinct from the technical lifecycle:

- Tri-state lifecycle (runtime technical): silent / liminal / manifest
- Desktop presence modes (product-level): static / liminal / manifest
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.hidden_context_visible_action_surface import (
    build_hidden_context_visible_action_surface_contract,
)
from core.realtime_streaming_backbone import build_realtime_streaming_backbone_contract


class DesktopPresenceMode(str, Enum):
    """Product-level desktop presence modes."""

    STATIC = "static"
    LIMINAL = "liminal"
    MANIFEST = "manifest"


@dataclass(frozen=True)
class PresenceModeDefinition:
    """Formal definition of one desktop presence mode."""

    mode: DesktopPresenceMode
    definition: str
    tri_state_mapping: str
    extension_scope: str
    non_equivalence_guard: str
    ambient_board_role: str
    foreground_role: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "definition": self.definition,
            "tri_state_mapping": self.tri_state_mapping,
            "extension_scope": self.extension_scope,
            "non_equivalence_guard": self.non_equivalence_guard,
            "ambient_board_role": self.ambient_board_role,
            "foreground_role": self.foreground_role,
        }


@dataclass(frozen=True)
class PresenceTransitionPolicy:
    """Formal transition rule for the desktop presence state machine."""

    from_modes: Tuple[DesktopPresenceMode, ...]
    to_mode: DesktopPresenceMode
    trigger: str
    automatic: bool
    reversible: bool
    depends_on_task: bool = False
    depends_on_sensing: bool = False
    depends_on_execution: bool = False
    cooldown_ms: int = 0
    stability_window_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_modes": [m.value for m in self.from_modes],
            "to_mode": self.to_mode.value,
            "trigger": self.trigger,
            "automatic": self.automatic,
            "reversible": self.reversible,
            "depends_on_task": self.depends_on_task,
            "depends_on_sensing": self.depends_on_sensing,
            "depends_on_execution": self.depends_on_execution,
            "cooldown_ms": self.cooldown_ms,
            "stability_window_ms": self.stability_window_ms,
        }


PRESENCE_MODE_DEFINITIONS: Tuple[PresenceModeDefinition, ...] = (
    PresenceModeDefinition(
        mode=DesktopPresenceMode.STATIC,
        definition=(
            "Present but low-disturbance desktop existence: perceptible standby that does not "
            "take foreground subject position."
        ),
        tri_state_mapping=(
            "Primarily maps to tri-state=silent, with explicit guard that silent is lifecycle "
            "rest while static is the product presence posture."
        ),
        extension_scope="Carries low-attention availability and boundary posture.",
        non_equivalence_guard=(
            "Do not treat technical silent completion as automatically sufficient to explain "
            "desktop presence semantics."
        ),
        ambient_board_role="Ambient board remains quiet but available as continuity substrate.",
        foreground_role="Desktop presence layer remains primary foreground anchor in low intensity.",
    ),
    PresenceModeDefinition(
        mode=DesktopPresenceMode.LIMINAL,
        definition=(
            "Environment-transition layer: sensing/permeation/brewing state between background "
            "reasoning and manifest action."
        ),
        tri_state_mapping=(
            "Anchors on tri-state=liminal and extends it into ambient-board semantics, not busy/"
            "loading spinner semantics."
        ),
        extension_scope="Primary carrier for ambient gradients, subtle feedback, and transition intent.",
        non_equivalence_guard=(
            "Liminal presence is not equivalent to request-in-progress/busy spinner semantics; "
            "it is a desktop atmosphere and transition field."
        ),
        ambient_board_role="Ambient board is the canonical carrier of liminal presence.",
        foreground_role="Foreground remains presence-first while chat/panel/operator stay supporting layers.",
    ),
    PresenceModeDefinition(
        mode=DesktopPresenceMode.MANIFEST,
        definition=(
            "Explicit action/execution/result layer where work traces become perceptible as "
            "desktop-visible change."
        ),
        tri_state_mapping=(
            "Maps to tri-state=manifest with explicit coupling to execution substrate, command routing, "
            "and completion traces."
        ),
        extension_scope="Carries execution pressure, result emission, and completion visibility.",
        non_equivalence_guard=(
            "Manifest requires real execution/result evidence; it is not a cosmetic UI expansion."
        ),
        ambient_board_role="Ambient board escalates into action-support context and trace framing.",
        foreground_role="Presence layer becomes explicit foreground actor during execution windows.",
    ),
)


PRESENCE_TRANSITION_POLICIES: Tuple[PresenceTransitionPolicy, ...] = (
    PresenceTransitionPolicy(
        from_modes=(DesktopPresenceMode.STATIC,),
        to_mode=DesktopPresenceMode.LIMINAL,
        trigger="request_received_or_continuous_sensing",
        automatic=True,
        reversible=True,
        depends_on_task=True,
        depends_on_sensing=True,
        stability_window_ms=120,
    ),
    PresenceTransitionPolicy(
        from_modes=(DesktopPresenceMode.LIMINAL,),
        to_mode=DesktopPresenceMode.MANIFEST,
        trigger="execution_path_confirmed_and_running",
        automatic=True,
        reversible=True,
        depends_on_task=True,
        depends_on_execution=True,
        stability_window_ms=40,
    ),
    PresenceTransitionPolicy(
        from_modes=(DesktopPresenceMode.MANIFEST,),
        to_mode=DesktopPresenceMode.LIMINAL,
        trigger="execution_completed_or_result_committed",
        automatic=True,
        reversible=True,
        depends_on_execution=True,
        cooldown_ms=300,
        stability_window_ms=120,
    ),
    PresenceTransitionPolicy(
        from_modes=(DesktopPresenceMode.LIMINAL,),
        to_mode=DesktopPresenceMode.STATIC,
        trigger="stability_window_elapsed_without_task_or_sensing",
        automatic=True,
        reversible=True,
        cooldown_ms=250,
        stability_window_ms=300,
    ),
)


DESKTOP_FOREGROUND_HIERARCHY: Dict[str, Any] = {
    "primary_foreground": "desktop_presence_layer",
    "layers": [
        {"name": "desktop_presence_layer", "role": "primary_foreground"},
        {"name": "ambient_board_state_layer", "role": "liminal_carrier_and_transition_board"},
        {"name": "behavior_trace_layer", "role": "execution_trace_and_result_visibility"},
        {"name": "chat_surface", "role": "interaction_ingress_supporting_surface"},
        {"name": "panel_surface", "role": "projection_and_operator_supporting_surface"},
        {"name": "operator_surface", "role": "governance_and_control_supporting_surface"},
    ],
    "policy": "Presence layer is the main foreground; chat/panel/operator are supportive.",
}


DESKTOP_RUNTIME_COUPLING: Dict[str, Any] = {
    "runtime_shell": "DesktopPresenceRuntime",
    "subject_core": "OpenClawd",
    "command_routing": "CommandRouter",
    "execution_substrate": "local_execution_chain + cross_device_execution_chain",
    "mode_signal_mapping": {
        "static": ["tri_state=silent", "no_active_execution", "ambient continuity only"],
        "liminal": [
            "tri_state=liminal",
            "openclawd cognition/branching active",
            "continuous sensing pressure and ambient board gradients",
        ],
        "manifest": [
            "tri_state=manifest",
            "dispatch/execution active",
            "result or desktop-change trace visible",
        ],
    },
    "non_ui_toggle_guard": "Modes derive from runtime/task/sensing/execution signals, not UI flags.",
}


DESKTOP_EXTENSION_HOME: Dict[str, Any] = {
    "multimodal_ingress_home": "DesktopPresenceRuntime native MultimodalIngressBus + request multimodal_context",
    "continuous_sensing_influence": "Feeds liminal transition pressure and ambient-board gradients.",
    "webrtc_streaming_home": (
        "PerceptionSourceRegistry and ingress channels feed liminal ambient board "
        "and manifest trace."
    ),
    "background_foreground_boundary": (
        "Static anchors background availability, liminal governs boundary transitions, "
        "manifest governs explicit foreground execution."
    ),
}


def _lookup_transition_policy(
    from_mode: DesktopPresenceMode, to_mode: DesktopPresenceMode
) -> PresenceTransitionPolicy:
    for policy in PRESENCE_TRANSITION_POLICIES:
        if to_mode == policy.to_mode and from_mode in policy.from_modes:
            return policy
    raise KeyError(f"missing transition policy: {from_mode.value}->{to_mode.value}")


class DesktopPresenceStateMachine:
    """Formal state machine for desktop presence modes."""

    _MIN_MODE_HOLD_MS: Dict[DesktopPresenceMode, int] = {
        DesktopPresenceMode.STATIC: 200,
        DesktopPresenceMode.LIMINAL: 120,
        DesktopPresenceMode.MANIFEST: 120,
    }
    _COOLDOWN_LIMINAL_TO_STATIC_MS: int = _lookup_transition_policy(
        DesktopPresenceMode.LIMINAL, DesktopPresenceMode.STATIC
    ).cooldown_ms
    _COOLDOWN_MANIFEST_TO_LIMINAL_MS: int = _lookup_transition_policy(
        DesktopPresenceMode.MANIFEST, DesktopPresenceMode.LIMINAL
    ).cooldown_ms

    def __init__(self) -> None:
        self._mode: DesktopPresenceMode = DesktopPresenceMode.STATIC
        self._mode_since: float = time.monotonic()
        self._last_transition: Optional[Dict[str, Any]] = None
        self._last_manifest_exit_at: Optional[float] = None

    @property
    def mode(self) -> DesktopPresenceMode:
        return self._mode

    def update(
        self,
        *,
        tri_state: str,
        task_active: bool,
        sensing_active: bool,
        execution_active: bool,
        user_interaction: bool,
        result_committed: bool = False,
        android_presence_participation: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        now = time.monotonic()

        # Resolve android participation signals once, so _derive_target_mode
        # and the transition record both see the same derived values.
        android_drives_liminal = False
        android_drives_manifest = False
        android_participant_count = 0
        if android_presence_participation is not None:
            try:
                android_drives_liminal = bool(android_presence_participation.any_drives_liminal)
                android_drives_manifest = bool(android_presence_participation.any_drives_manifest)
                android_participant_count = int(
                    android_presence_participation.presence_participant_count
                )
            except AttributeError:
                pass

        target = self._derive_target_mode(
            tri_state=tri_state,
            task_active=task_active,
            sensing_active=sensing_active,
            execution_active=execution_active,
            android_drives_liminal=android_drives_liminal,
            android_drives_manifest=android_drives_manifest,
        )
        if result_committed and self._mode == DesktopPresenceMode.MANIFEST:
            target = DesktopPresenceMode.LIMINAL
        if target == self._mode:
            return None

        hold_ms = self._MIN_MODE_HOLD_MS.get(self._mode, 0)
        if (now - self._mode_since) * 1000 < hold_ms:
            return None

        if (
            target == DesktopPresenceMode.STATIC
            and self._mode == DesktopPresenceMode.LIMINAL
            and self._last_manifest_exit_at is not None
            and ((now - self._last_manifest_exit_at) * 1000) < self._COOLDOWN_LIMINAL_TO_STATIC_MS
        ):
            return None

        if (
            target == DesktopPresenceMode.MANIFEST
            and self._last_manifest_exit_at is not None
            and ((now - self._last_manifest_exit_at) * 1000) < self._COOLDOWN_MANIFEST_TO_LIMINAL_MS
            and not user_interaction
            and not execution_active
        ):
            return None

        previous = self._mode
        self._mode = target
        self._mode_since = now
        if previous == DesktopPresenceMode.MANIFEST and target != DesktopPresenceMode.MANIFEST:
            self._last_manifest_exit_at = now

        self._last_transition = {
            "from_mode": previous.value,
            "to_mode": target.value,
            "at_monotonic": now,
            "automatic": True,
            "reversible": True,
            "task_active": task_active,
            "sensing_active": sensing_active,
            "execution_active": execution_active,
            "tri_state": tri_state,
            "result_committed": result_committed,
            "android_presence_participant_count": android_participant_count,
            "android_drives_liminal": android_drives_liminal,
            "android_drives_manifest": android_drives_manifest,
        }
        return dict(self._last_transition)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current_mode": self._mode.value,
            "mode_uptime_ms": int((time.monotonic() - self._mode_since) * 1000),
            "last_transition": dict(self._last_transition) if self._last_transition else None,
            "transition_policies": [p.to_dict() for p in PRESENCE_TRANSITION_POLICIES],
        }

    def simulate_elapsed_time_for_testing(self, seconds: float) -> None:
        """Testing helper: simulate elapsed monotonic time without sleeping."""
        if seconds < 0:
            raise ValueError("seconds must be non-negative")
        self._mode_since -= seconds
        if self._last_manifest_exit_at is not None:
            self._last_manifest_exit_at -= seconds

    @staticmethod
    def _derive_target_mode(
        *,
        tri_state: str,
        task_active: bool,
        sensing_active: bool,
        execution_active: bool,
        android_drives_liminal: bool = False,
        android_drives_manifest: bool = False,
    ) -> DesktopPresenceMode:
        if execution_active or tri_state == "manifest" or android_drives_manifest:
            return DesktopPresenceMode.MANIFEST
        if tri_state == "liminal" or task_active or sensing_active or android_drives_liminal:
            return DesktopPresenceMode.LIMINAL
        return DesktopPresenceMode.STATIC


def build_desktop_presence_system_view(
    *,
    state_machine_snapshot: Dict[str, Any],
    dominant_tristate: str,
    tristate_distribution: Dict[str, int],
    active_session_count: int,
    stream_runtime_status: Optional[Dict[str, Any]] = None,
    android_presence_participation: Optional[Any] = None,
    subject_foreground: Optional[Dict[str, Any]] = None,
    subject_unified_lineage: Optional[Dict[str, Any]] = None,
    canonical_continuous_ingress: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a formal desktop-presence projection for runtime/panel/operator surfaces.

    ``android_presence_participation`` is accepted as an optional argument so that
    the canonical default runtime path (PR-canonical-default) can pass the real
    Android presence participation summary built from the device state store.  When
    provided, it is embedded in the view as ``android_presence_participation`` so
    that the field is visible on the user-facing default path rather than only in
    operator/debug surfaces.
    """
    subject_fg = dict(subject_foreground or {})
    unified_lineage = dict(subject_unified_lineage or {})
    continuous_ingress = dict(canonical_continuous_ingress or {})
    lineage_active_families = (
        (unified_lineage.get("temporal_alignment") or {}).get("active_continuous_families")
    )
    ingress_active_families = continuous_ingress.get("active_families") or []
    active_stream_families = list(
        lineage_active_families
        if lineage_active_families is not None
        else ingress_active_families
    )
    subject_state = str(subject_fg.get("subject_state") or dominant_tristate)
    subject_state_source = (
        "subject_foreground" if subject_fg.get("subject_state") else "dominant_tristate_fallback"
    )

    view: Dict[str, Any] = {
        "formal_presence_modes": [d.to_dict() for d in PRESENCE_MODE_DEFINITIONS],
        "state_machine": state_machine_snapshot,
        "mapping_to_runtime": {
            "dominant_tristate": dominant_tristate,
            "tristate_distribution": dict(tristate_distribution),
            "active_session_count": active_session_count,
            "runtime_coupling": dict(DESKTOP_RUNTIME_COUPLING),
        },
        "liminal_ambient_board": {
            "is_primary_carrier": True,
            "purpose": "Desktop ambient board/environment transition layer.",
            "carries_presence_and_low_intensity_feedback": True,
            "bridges_background_reasoning_to_foreground_action": True,
            "rejects_busy_spinner_equivalence": True,
        },
        "foreground_hierarchy": dict(DESKTOP_FOREGROUND_HIERARCHY),
        "future_extension_home": dict(DESKTOP_EXTENSION_HOME),
        "hidden_context_visible_action_surface": (
            build_hidden_context_visible_action_surface_contract()
        ),
        "realtime_streaming_backbone": {
            "contract": build_realtime_streaming_backbone_contract(),
            "runtime_status": dict(stream_runtime_status or {}),
        },
    }
    if subject_fg or unified_lineage:
        if subject_fg:
            view["subject_foreground"] = dict(subject_fg)
        if unified_lineage:
            view["subject_unified_lineage"] = dict(unified_lineage)
        view["subject_panel"] = {
            "source_object_family": "subject_foreground",
            "shared_canonical_lineage_id": str(
                unified_lineage.get("canonical_lineage_id") or ""
            ),
            "subject_state": subject_state,
            "subject_state_source": subject_state_source,
            "foreground_event": str(subject_fg.get("foreground_event") or ""),
            "action_phase": str(subject_fg.get("action_phase") or ""),
            "foreground_status": str(subject_fg.get("foreground_status") or ""),
            "blocker": subject_fg.get("blocker"),
            "confirmation": subject_fg.get("confirmation"),
            "continuous_ingress_participation": {
                "is_present": bool(active_stream_families),
                "active_families": active_stream_families,
            },
            "authority_boundary": dict(unified_lineage.get("authority_boundary") or {}),
            "failure_discipline": dict(unified_lineage.get("failure_discipline") or {}),
            "continuity_trace": dict(unified_lineage.get("continuity_trace") or {}),
        }
        hierarchy = view.setdefault("foreground_hierarchy", {})
        hierarchy["panel_subject_source"] = "subject_foreground"
        hierarchy["shared_lineage_object"] = "subject_unified_lineage"
    # Attach android_presence_participation when the canonical default path provides it.
    # This makes the android participation data a first-class presence-system field
    # on the user-facing default path (not hidden behind operator/debug paths).
    if android_presence_participation is not None:
        try:
            view["android_presence_participation"] = (
                android_presence_participation.to_dict()
                if hasattr(android_presence_participation, "to_dict")
                else dict(android_presence_participation)
            )
        except Exception:
            pass
    return view


def list_presence_mode_names() -> List[str]:
    """Helper for tests and schema checks."""
    return [m.value for m in DesktopPresenceMode]


def iter_presence_transition_targets() -> Iterable[str]:
    """Helper for tests and schema checks."""
    return (p.to_mode.value for p in PRESENCE_TRANSITION_POLICIES)
