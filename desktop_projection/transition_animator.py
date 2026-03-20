"""
desktop_projection/transition_animator.py
==========================================
Transition timing and easing for the "silent → liminal → manifest" desktop
spatial expansion.

Overview
--------
:class:`TransitionAnimator` receives a source :class:`LiminalSpaceState` and
a target :class:`LiminalSpaceState` and produces a finite sequence of
interpolated states that represent the continuous, smooth path between them.
This ensures there are no hard jumps in any spatial dimension when the system
changes phase.

Easing curves
-------------
Three built-in curves are provided:

``linear``
    Constant rate; useful for debugging.
``ease_in_out``
    Slow start, fast middle, slow end (cubic S-curve).  The default for
    silent → liminal and liminal → manifest transitions.
``ease_out``
    Fast start, decelerating end.  Suitable for manifest → silent retreat.

Usage
-----
::

    from desktop_projection import TransitionAnimator, TransitionPhase
    from desktop_projection.state_space_mapper import LiminalSpaceState

    animator = TransitionAnimator()
    frames = list(animator.interpolate(source_state, target_state, steps=30))
    for frame in frames:
        render(frame)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterator, Optional

from .state_space_mapper import LiminalSpaceState, _clamp


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class EasingCurve(str, Enum):
    """Available easing curve algorithms."""

    LINEAR = "linear"
    """Constant-rate interpolation.  Good for debugging."""

    EASE_IN_OUT = "ease_in_out"
    """Smooth cubic S-curve: slow start, fast middle, slow end.

    Recommended for phase-change transitions.
    """

    EASE_OUT = "ease_out"
    """Decelerating curve: fast start, slow end.

    Recommended for retreat / return-to-silent transitions.
    """


class TransitionPhase(str, Enum):
    """Semantic label for the direction of a transition."""

    SILENT_TO_LIMINAL = "silent_to_liminal"
    LIMINAL_TO_MANIFEST = "liminal_to_manifest"
    MANIFEST_TO_LIMINAL = "manifest_to_liminal"
    LIMINAL_TO_SILENT = "liminal_to_silent"
    IDENTITY = "identity"
    """No-op transition (source == target phase)."""


# ---------------------------------------------------------------------------
# TransitionAnimator
# ---------------------------------------------------------------------------


class TransitionAnimator:
    """Produces smooth interpolation frames between two :class:`LiminalSpaceState`\\s.

    All interpolation is performed in the four spatial dimensions defined by
    :class:`~desktop_projection.state_space_mapper.LiminalSpaceState`:

    * ``depth_factor``
    * ``topology_visibility``
    * ``domain_path_emphasis``
    * ``ambient_intensity``

    The animator is **stateless** — it carries no mutable fields and can be
    shared across threads.

    Parameters
    ----------
    default_curve:
        Easing curve applied when the caller does not specify one explicitly.
        Defaults to :attr:`EasingCurve.EASE_IN_OUT`.
    default_steps:
        Default number of interpolation steps when not specified by caller.
    """

    def __init__(
        self,
        default_curve: EasingCurve = EasingCurve.EASE_IN_OUT,
        default_steps: int = 20,
    ) -> None:
        self._default_curve = default_curve
        self._default_steps = default_steps

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def classify_transition(
        self,
        source: LiminalSpaceState,
        target: LiminalSpaceState,
    ) -> TransitionPhase:
        """Return the semantic :class:`TransitionPhase` for this transition.

        Parameters
        ----------
        source:
            Starting liminal space state.
        target:
            Ending liminal space state.

        Returns
        -------
        TransitionPhase
            The direction of this transition.
        """
        sp = source.source_phase
        tp = target.source_phase
        if sp == tp:
            return TransitionPhase.IDENTITY
        if sp == "silent" and tp == "liminal":
            return TransitionPhase.SILENT_TO_LIMINAL
        if sp == "liminal" and tp == "manifest":
            return TransitionPhase.LIMINAL_TO_MANIFEST
        if sp == "manifest" and tp == "liminal":
            return TransitionPhase.MANIFEST_TO_LIMINAL
        if sp == "liminal" and tp == "silent":
            return TransitionPhase.LIMINAL_TO_SILENT
        # Catch all other cross-phase jumps (e.g. silent → manifest).
        return TransitionPhase.SILENT_TO_LIMINAL

    def recommend_curve(self, phase: TransitionPhase) -> EasingCurve:
        """Recommend the most natural easing curve for *phase*.

        Parameters
        ----------
        phase:
            The transition direction.

        Returns
        -------
        EasingCurve
            Recommended easing curve.
        """
        _RETREAT = {TransitionPhase.MANIFEST_TO_LIMINAL, TransitionPhase.LIMINAL_TO_SILENT}
        if phase in _RETREAT:
            return EasingCurve.EASE_OUT
        return EasingCurve.EASE_IN_OUT

    def interpolate(
        self,
        source: LiminalSpaceState,
        target: LiminalSpaceState,
        steps: Optional[int] = None,
        curve: Optional[EasingCurve] = None,
    ) -> Iterator[LiminalSpaceState]:
        """Yield *steps* smoothly-interpolated states from *source* to *target*.

        The first yielded frame is **not** the source itself; it is the first
        step away from the source.  The last yielded frame **is** the target.
        This guarantees that a caller rendering successive frames arrives at
        the exact target state without overshoot.

        Parameters
        ----------
        source:
            Starting spatial state.
        target:
            Destination spatial state.
        steps:
            Number of frames to emit.  Defaults to ``default_steps``.
        curve:
            Easing curve to apply.  When ``None``, the recommended curve for
            the detected :class:`TransitionPhase` is used.

        Yields
        ------
        LiminalSpaceState
            Interpolated frames, ``steps`` total.
        """
        n = max(1, steps if steps is not None else self._default_steps)

        if curve is None:
            tp = self.classify_transition(source, target)
            curve = self.recommend_curve(tp)

        ease_fn = _EASING_FUNCTIONS[curve]

        for i in range(1, n + 1):
            t = i / n  # raw linear parameter in (0, 1]
            t_eased = ease_fn(t)
            yield _lerp_state(source, target, t_eased)

    def single_frame(
        self,
        source: LiminalSpaceState,
        target: LiminalSpaceState,
        t: float,
        curve: Optional[EasingCurve] = None,
    ) -> LiminalSpaceState:
        """Return a single interpolated frame at normalised time *t*.

        Parameters
        ----------
        source:
            Starting spatial state.
        target:
            Destination spatial state.
        t:
            Normalised time in ``[0, 1]``.  0 → source, 1 → target.
        curve:
            Easing curve.  Defaults to ``EASE_IN_OUT``.

        Returns
        -------
        LiminalSpaceState
            Interpolated frame.
        """
        t = _clamp(t, 0.0, 1.0)
        if curve is None:
            curve = self._default_curve
        t_eased = _EASING_FUNCTIONS[curve](t)
        return _lerp_state(source, target, t_eased)


# ---------------------------------------------------------------------------
# Easing functions
# ---------------------------------------------------------------------------


def _ease_linear(t: float) -> float:
    return t


def _ease_in_out(t: float) -> float:
    """Cubic S-curve: 3t² - 2t³ (smooth step)."""
    return t * t * (3.0 - 2.0 * t)


def _ease_out(t: float) -> float:
    """Decelerating curve: 1 - (1 - t)²."""
    return 1.0 - (1.0 - t) ** 2


_EASING_FUNCTIONS = {
    EasingCurve.LINEAR: _ease_linear,
    EasingCurve.EASE_IN_OUT: _ease_in_out,
    EasingCurve.EASE_OUT: _ease_out,
}


# ---------------------------------------------------------------------------
# Interpolation helper
# ---------------------------------------------------------------------------


def _lerp_state(
    a: LiminalSpaceState,
    b: LiminalSpaceState,
    t: float,
) -> LiminalSpaceState:
    """Linear-interpolate all numeric dimensions between *a* and *b* at *t*."""

    def _lerp(va: float, vb: float) -> float:
        return va + (vb - va) * t

    return LiminalSpaceState(
        depth_factor=_lerp(a.depth_factor, b.depth_factor),
        topology_visibility=_lerp(a.topology_visibility, b.topology_visibility),
        domain_path_emphasis=_lerp(a.domain_path_emphasis, b.domain_path_emphasis),
        ambient_intensity=_lerp(a.ambient_intensity, b.ambient_intensity),
        # Use the target phase/domain so consumers know where the transition is heading.
        source_phase=b.source_phase,
        source_domain=b.source_domain,
    )
