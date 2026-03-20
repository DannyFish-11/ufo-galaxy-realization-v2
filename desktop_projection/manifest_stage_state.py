"""
desktop_projection/manifest_stage_state.py
===========================================
:class:`ManifestStageState` — the 显现台 (manifest stage) descriptor.

Derived from a :class:`~core.projection.RuntimeProjection` and a
:class:`~desktop_projection.LiminalSpaceState`, this dataclass captures
everything needed to render the manifest execution surface:

- *what* is running (task summary, execution stage)
- *which models* are active (primary + support, top-N weights)
- *which devices* are active
- *why* this routing was chosen (route_reason)
- *how intense* the focus field is (focus_intensity)
- *whether* the surface is ready to display (stage_ready)

Design
------
``ManifestStageState`` is **pure data** — no I/O, no side effects.  It is
produced exclusively by :class:`~desktop_projection.ManifestStageController`.
All float fields are in ``[0.0, 1.0]`` unless otherwise noted.

Thresholds
----------
``stage_ready`` becomes ``True`` when the liminal ``ambient_intensity``
(proxy for focus energy) exceeds :data:`STAGE_READY_THRESHOLD`.  This prevents
the manifest surface from lighting up during quiet or transitional states.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# Minimum liminal ambient_intensity required for stage_ready to be True.
STAGE_READY_THRESHOLD: float = 0.35


@dataclass
class ManifestStageState:
    """Descriptor for the manifest-stage (显现台) projection surface.

    Attributes
    ----------
    task_summary
        Human-readable description of the current task (or ``None``).
    execution_stage
        Execution lifecycle label (e.g. ``"planning"``, ``"executing"``,
        ``"complete"``).  ``None`` when not yet determined.
    primary_model_id
        ID of the primary routed model node (or ``None``).
    support_model_ids
        Ordered list of supporting model IDs.
    active_device_ids
        IDs of devices currently involved in execution.
    active_weights
        Top-N (model_id → weight) mapping, ordered by weight descending.
        Values are in ``[0.0, 1.0]``.
    route_reason
        Human-readable rationale for the routing decision (or ``None``).
    focus_intensity
        Derived focus-field strength in ``[0.0, 1.0]``.  Computed from
        collapse_tendency and coherence; reflects how "committed" the system
        is to this manifest projection.
    stage_ready
        ``True`` when the liminal intensity field is strong enough for the
        manifest surface to be considered active.
    source_phase
        The tri_state_phase from the originating RuntimeProjection.
    """

    task_summary: Optional[str] = None
    execution_stage: Optional[str] = None
    primary_model_id: Optional[str] = None
    support_model_ids: List[str] = field(default_factory=list)
    active_device_ids: List[str] = field(default_factory=list)
    active_weights: Dict[str, float] = field(default_factory=dict)
    route_reason: Optional[str] = None
    focus_intensity: float = 0.0
    stage_ready: bool = False
    source_phase: str = "silent"

    def to_dict(self) -> dict:
        """Return a plain dict representation."""
        return {
            "task_summary": self.task_summary,
            "execution_stage": self.execution_stage,
            "primary_model_id": self.primary_model_id,
            "support_model_ids": list(self.support_model_ids),
            "active_device_ids": list(self.active_device_ids),
            "active_weights": dict(self.active_weights),
            "route_reason": self.route_reason,
            "focus_intensity": self.focus_intensity,
            "stage_ready": self.stage_ready,
            "source_phase": self.source_phase,
        }

    def __repr__(self) -> str:
        return (
            f"<ManifestStageState "
            f"phase={self.source_phase} "
            f"ready={self.stage_ready} "
            f"focus={self.focus_intensity:.3f} "
            f"primary={self.primary_model_id!r} "
            f"stage={self.execution_stage!r}>"
        )
