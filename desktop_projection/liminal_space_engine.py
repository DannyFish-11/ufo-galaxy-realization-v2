"""
desktop_projection/liminal_space_engine.py
===========================================
The :class:`LiminalSpaceEngine` is the stateful coordinator for the Liminal
Projection Engine.  It:

1. Receives a new :class:`~core.projection.RuntimeProjection` (dict or object).
2. Uses :class:`~desktop_projection.StateSpaceMapper` to convert it to a
   :class:`~desktop_projection.LiminalSpaceState`.
3. Uses :class:`~desktop_projection.TransitionAnimator` to produce smooth
   interpolation frames between the previous and the new state.
4. Maintains a simple current-state cache so that callers who poll via a
   status board can always get the latest rendered state.

The engine is intentionally **lightweight** and carries no UI framework
dependencies.  Output is always a :class:`LiminalSpaceState` (plain Python
dataclass) or a list thereof.

Usage
-----
::

    from desktop_projection import LiminalSpaceEngine

    engine = LiminalSpaceEngine()

    # Feed a new RuntimeProjection (dict from HTTP endpoint):
    frames = engine.update(projection_dict, transition_steps=20)
    for frame in frames:
        render_desktop(frame)

    # Or just get the current state without driving a transition:
    current = engine.current_state
"""

from __future__ import annotations

from typing import List, Optional, Union

from .state_space_mapper import LiminalSpaceState, StateSpaceMapper
from .transition_animator import EasingCurve, TransitionAnimator


# ---------------------------------------------------------------------------
# LiminalSpaceEngine
# ---------------------------------------------------------------------------


class LiminalSpaceEngine:
    """Stateful coordinator for the liminal desktop projection layer.

    Parameters
    ----------
    mapper:
        :class:`StateSpaceMapper` instance.  Created automatically when ``None``.
    animator:
        :class:`TransitionAnimator` instance.  Created automatically when ``None``.
    default_steps:
        Number of interpolation steps to use for transitions when the caller
        does not specify ``transition_steps``.
    """

    def __init__(
        self,
        mapper: Optional[StateSpaceMapper] = None,
        animator: Optional[TransitionAnimator] = None,
        default_steps: int = 20,
    ) -> None:
        self._mapper = mapper or StateSpaceMapper()
        self._animator = animator or TransitionAnimator(default_steps=default_steps)
        self._current: Optional[LiminalSpaceState] = None
        self._default_steps = default_steps

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def current_state(self) -> Optional[LiminalSpaceState]:
        """Return the most recently computed :class:`LiminalSpaceState`.

        ``None`` until :meth:`update` has been called at least once.
        """
        return self._current

    def update(
        self,
        projection: Union[dict, object],
        transition_steps: Optional[int] = None,
        curve: Optional[EasingCurve] = None,
    ) -> List[LiminalSpaceState]:
        """Process a new *projection* and return transition frames.

        Parameters
        ----------
        projection:
            A ``dict`` conforming to the ``RuntimeProjection`` schema, or
            an actual ``RuntimeProjection`` instance.
        transition_steps:
            Number of interpolation steps.  Defaults to ``default_steps``.
        curve:
            Easing curve override.  When ``None``, the animator selects the
            recommended curve based on the detected transition direction.

        Returns
        -------
        List[LiminalSpaceState]
            Ordered list of interpolation frames.  The last frame is always
            identical to the newly mapped target state.  If no previous state
            exists (first call), a single-element list containing the target
            state is returned.
        """
        target = self._mapper.map(projection)

        if self._current is None:
            # First update — no transition possible; return target directly.
            self._current = target
            return [target]

        source = self._current
        steps = transition_steps if transition_steps is not None else self._default_steps

        frames = list(
            self._animator.interpolate(source, target, steps=steps, curve=curve)
        )

        # Always update current to the exact target state.
        self._current = target
        return frames

    def render_text(self, state: Optional[LiminalSpaceState] = None) -> str:
        """Render *state* (or :attr:`current_state`) as a human-readable string.

        This provides a minimal text representation suitable for log output or
        for integrating into the Status Board V2 liminal surface.

        Parameters
        ----------
        state:
            The :class:`LiminalSpaceState` to render.  Defaults to
            :attr:`current_state`.

        Returns
        -------
        str
            Multi-line human-readable summary.
        """
        s = state if state is not None else self._current
        if s is None:
            return (
                "┌─ Liminal Projection ─────────────────────────────\n"
                "│  (no state available — call update() first)\n"
                "└───────────────────────────────────────────────────"
            )

        bar_depth = _progress_bar(s.depth_factor)
        bar_topo = _progress_bar(s.topology_visibility)
        bar_path = _progress_bar(s.domain_path_emphasis)
        bar_ambient = _progress_bar(s.ambient_intensity)

        domain_label = s.source_domain or "—"
        lines = [
            "┌─ Liminal Projection ─────────────────────────────",
            f"│  Phase          : {s.source_phase}",
            f"│  Domain         : {domain_label}",
            f"│  Depth          : {bar_depth}  {s.depth_factor:.3f}",
            f"│  Topology       : {bar_topo}  {s.topology_visibility:.3f}",
            f"│  Domain Path    : {bar_path}  {s.domain_path_emphasis:.3f}",
            f"│  Ambient        : {bar_ambient}  {s.ambient_intensity:.3f}",
            "└───────────────────────────────────────────────────",
        ]
        return "\n".join(lines)

    def reset(self) -> None:
        """Reset the engine to its initial (no-state) condition."""
        self._current = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _progress_bar(value: float, width: int = 20) -> str:
    """Render a compact ASCII progress bar for *value* in [0, 1]."""
    filled = round(max(0.0, min(1.0, value)) * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"
