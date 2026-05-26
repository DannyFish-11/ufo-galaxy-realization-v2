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


class DesktopPresenceStateMachine:
    """Formal state machine for desktop presence modes."""

    _MIN_MODE_HOLD_MS: Dict[DesktopPresenceMode, int] = {
        DesktopPresenceMode.STATIC: 200,
        DesktopPresenceMode.LIMINAL: 120,
        DesktopPresenceMode.MANIFEST: 120,
    }

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
    ) -> Optional[Dict[str, Any]]:
        now = time.monotonic()
        target = self._derive_target_mode(
            tri_state=tri_state,
            task_active=task_active,
            sensing_active=sensing_active,
            execution_active=execution_active,
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
            and ((now - self._last_manifest_exit_at) * 1000) < 250
        ):
            return None

        if (
            target == DesktopPresenceMode.MANIFEST
            and self._last_manifest_exit_at is not None
            and ((now - self._last_manifest_exit_at) * 1000) < 300
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
        }
        return dict(self._last_transition)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "current_mode": self._mode.value,
            "mode_uptime_ms": max(0, int((time.monotonic() - self._mode_since) * 1000)),
            "last_transition": dict(self._last_transition) if self._last_transition else None,
            "transition_policies": [p.to_dict() for p in PRESENCE_TRANSITION_POLICIES],
        }

    @staticmethod
    def _derive_target_mode(
        *,
        tri_state: str,
        task_active: bool,
        sensing_active: bool,
        execution_active: bool,
    ) -> DesktopPresenceMode:
        if execution_active or tri_state == "manifest":
            return DesktopPresenceMode.MANIFEST
        if tri_state == "liminal" or task_active or sensing_active:
            return DesktopPresenceMode.LIMINAL
        return DesktopPresenceMode.STATIC


def build_desktop_presence_system_view(
    *,
    state_machine_snapshot: Dict[str, Any],
    dominant_tristate: str,
    tristate_distribution: Dict[str, int],
    active_session_count: int,
) -> Dict[str, Any]:
    """Return a formal desktop-presence projection for runtime/panel/operator surfaces."""
    return {
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
    }


def list_presence_mode_names() -> List[str]:
    """Helper for tests and schema checks."""
    return [m.value for m in DesktopPresenceMode]


def iter_presence_transition_targets() -> Iterable[str]:
    """Helper for tests and schema checks."""
    return (p.to_mode.value for p in PRESENCE_TRANSITION_POLICIES)
