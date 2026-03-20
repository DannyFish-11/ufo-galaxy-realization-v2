"""
desktop_projection/manifest_stage_controller.py
================================================
:class:`ManifestStageController` — maps RuntimeProjection + LiminalSpaceState
into a :class:`~desktop_projection.ManifestStageState`.

Design
------
The controller is **stateful** in one narrow sense: it remembers the previous
``ManifestStageState`` so that it can apply a *softening* policy when
``retreat_tendency`` is high.  This prevents abrupt jumps when the system
momentarily pulls back from a manifest projection.

Softening policy
~~~~~~~~~~~~~~~~
When ``retreat_tendency >= RETREAT_SOFTENING_THRESHOLD``:

* ``focus_intensity`` is blended toward the previous value (hold/soften).
* ``stage_ready`` is latched to ``False`` until focus recovers.

The blend ratio is controlled by :attr:`ManifestStageController.retreat_blend`,
defaulting to ``0.7`` (70 % old / 30 % new when retreating).

Transition continuity
~~~~~~~~~~~~~~~~~~~~~
The controller requires a :class:`~desktop_projection.LiminalSpaceState` as
input.  The ``ambient_intensity`` from the liminal state drives
``focus_intensity`` (alongside ``coherence`` and ``collapse_tendency`` from
the raw projection), ensuring that the manifest surface is always a smooth
continuation of the liminal projection — never an abrupt jump.

Usage::

    from desktop_projection import ManifestStageController, LiminalSpaceState

    controller = ManifestStageController()
    manifest = controller.update(projection_dict, liminal_state)
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple, Union

from .manifest_stage_state import ManifestStageState, STAGE_READY_THRESHOLD

# Retreat tendency threshold above which the softening policy activates.
RETREAT_SOFTENING_THRESHOLD: float = 0.5

# Number of top-N weight entries included in ManifestStageState.active_weights.
_TOP_N_WEIGHTS: int = 5


def _safe_float(value: object, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _safe_str(value: object, default: Optional[str]) -> Optional[str]:
    if value is None:
        return default
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def _to_dict(projection: Union[dict, object]) -> dict:
    if isinstance(projection, dict):
        return projection
    if hasattr(projection, "to_dict"):
        return projection.to_dict()  # type: ignore[union-attr]
    return vars(projection)


def _top_n_weights(weights: Dict[str, float], n: int) -> Dict[str, float]:
    """Return the top-*n* entries from *weights*, sorted descending by value."""
    if not weights:
        return {}
    sorted_items: List[Tuple[str, float]] = sorted(
        weights.items(), key=lambda kv: kv[1], reverse=True
    )[:n]
    return dict(sorted_items)


class ManifestStageController:
    """Stateful controller: RuntimeProjection + LiminalSpaceState → ManifestStageState.

    Parameters
    ----------
    retreat_blend
        Blending factor applied to ``focus_intensity`` when retreat_tendency
        is high.  Must be in ``[0.0, 1.0]``.  Higher values hold the previous
        intensity more strongly.  Default: ``0.7``.
    top_n
        Number of top model weights to include in the output state.
        Default: ``5``.
    """

    def __init__(
        self,
        retreat_blend: float = 0.7,
        top_n: int = _TOP_N_WEIGHTS,
    ) -> None:
        if not (0.0 <= retreat_blend <= 1.0):
            raise ValueError(
                f"retreat_blend must be in [0.0, 1.0]; got {retreat_blend!r}"
            )
        self._retreat_blend = retreat_blend
        self._top_n = top_n
        self._previous: Optional[ManifestStageState] = None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def previous_state(self) -> Optional[ManifestStageState]:
        """The last emitted :class:`ManifestStageState`, or ``None``."""
        return self._previous

    def update(
        self,
        projection: Union[dict, object],
        liminal: object,
    ) -> ManifestStageState:
        """Compute a new :class:`ManifestStageState` from *projection* and *liminal*.

        Parameters
        ----------
        projection
            A ``dict`` conforming to the ``RuntimeProjection`` schema, or an
            actual ``RuntimeProjection`` instance.
        liminal
            A :class:`~desktop_projection.LiminalSpaceState` instance, or any
            object / dict with the same fields.

        Returns
        -------
        ManifestStageState
            The manifest-stage descriptor.  Also stored as
            :attr:`previous_state` for the next call.
        """
        p = _to_dict(projection)
        lim = _to_dict(liminal) if not isinstance(liminal, dict) else liminal

        # Extract raw fields from projection.
        phase_str: str = _safe_str(p.get("tri_state_phase"), "silent") or "silent"
        coherence: float = _safe_float(p.get("coherence"), 0.0)
        collapse: float = _safe_float(p.get("collapse_tendency"), 0.0)
        retreat: float = _safe_float(p.get("retreat_tendency"), 0.0)

        primary: Optional[str] = _safe_str(p.get("primary_model_id"), None)
        support: List[str] = list(p.get("support_model_ids") or [])
        active_devices: List[str] = list(p.get("active_device_ids") or [])
        raw_weights: Dict[str, float] = dict(p.get("active_weights") or {})
        reason: Optional[str] = _safe_str(p.get("route_reason"), None)
        task_summary: Optional[str] = _safe_str(
            p.get("current_task_summary") or p.get("task_summary"), None
        )
        exec_stage: Optional[str] = _safe_str(p.get("execution_stage"), None)

        # Extract liminal ambient_intensity (used for both focus and stage_ready).
        ambient: float = _safe_float(
            lim.get("ambient_intensity") if isinstance(lim, dict) else getattr(lim, "ambient_intensity", 0.0),
            0.0,
        )

        # Compute focus_intensity from liminal ambient + coherence + collapse.
        raw_focus = self._compute_focus(ambient, coherence, collapse)

        # Apply softening when retreat is high.
        focus = self._apply_softening(raw_focus, retreat)

        # Stage ready when ambient (from liminal) exceeds threshold.
        stage_ready = (ambient >= STAGE_READY_THRESHOLD) and (retreat < RETREAT_SOFTENING_THRESHOLD)

        # Top-N weights, stable ordering.
        top_weights = _top_n_weights(raw_weights, self._top_n)

        state = ManifestStageState(
            task_summary=task_summary,
            execution_stage=exec_stage,
            primary_model_id=primary,
            support_model_ids=support,
            active_device_ids=active_devices,
            active_weights=top_weights,
            route_reason=reason,
            focus_intensity=_clamp(focus, 0.0, 1.0),
            stage_ready=stage_ready,
            source_phase=phase_str,
        )
        self._previous = state
        return state

    def reset(self) -> None:
        """Clear the controller's internal state (previous ManifestStageState)."""
        self._previous = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_focus(
        self,
        ambient: float,
        coherence: float,
        collapse: float,
    ) -> float:
        """focus = geometric mean of (ambient, coherence) nudged by collapse."""
        base = math.sqrt(max(ambient, 0.0) * max(coherence, 0.0))
        nudge = 0.15 * collapse
        return base + nudge

    def _apply_softening(self, raw_focus: float, retreat: float) -> float:
        """Blend toward previous focus when retreat is high."""
        if retreat < RETREAT_SOFTENING_THRESHOLD:
            return raw_focus
        if self._previous is None:
            return raw_focus
        prev_focus = self._previous.focus_intensity
        # Weighted blend: old * blend + new * (1 - blend).
        return prev_focus * self._retreat_blend + raw_focus * (1.0 - self._retreat_blend)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))
