"""
core.continuum.expression_engine — Expression Engine
=====================================================

Derives abstract, non-UI expression parameters from the current
:class:`~core.continuum.types.ContinuumState`.

The engine maps phase + smoothed signal values to
:class:`~core.continuum.types.ExpressionState` fields.  All outputs are
purely abstract descriptors; no widget, page, or view semantics are
implied.  Downstream rendering layers (audio, haptics, visual projectors)
are responsible for interpreting these values.

Phase → expression mapping (defaults)
--------------------------------------
- *formless*   → still, absent, no form, empty texture.
- *liminal*    → soft diffuse cluster, peripheral presence, coherence-scaled
                 motion and intensity.
- *manifest*   → focused or expanding form, ambient/foreground presence,
                 full intensity proportional to ``presence_intensity`` and
                 ``should_act_score``.
- *receding*   → collapsing field, peripheral, decreasing motion and
                 intensity.

All values remain in ``[0, 1]``.

Usage::

    from core.continuum.expression_engine import ExpressionEngine
    from core.continuum.types import ContinuumState, ContinuumPhase

    engine = ExpressionEngine()
    expression = engine.compute(continuum_state)
    print(expression.form_signature, expression.motion)
"""

from __future__ import annotations

from core.continuum.config import ContinuumConfig, DEFAULT_CONTINUUM_CONFIG
from core.continuum.types import (
    ActionLevel,
    ContinuumPhase,
    ContinuumState,
    ExpressionState,
    FormSignature,
    SpatialPresence,
)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Return *v* clamped to [*lo*, *hi*]."""
    return max(lo, min(hi, v))


class ExpressionEngine:
    """Derives :class:`~core.continuum.types.ExpressionState` from a
    :class:`~core.continuum.types.ContinuumState` snapshot.

    The engine is **stateless**: each call to :meth:`compute` produces an
    independent result.

    Args:
        config: Continuum configuration.  Defaults to
            :data:`~core.continuum.config.DEFAULT_CONTINUUM_CONFIG`.
    """

    def __init__(
        self,
        config: ContinuumConfig = DEFAULT_CONTINUUM_CONFIG,
    ) -> None:
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute(self, state: ContinuumState) -> ExpressionState:
        """Derive :class:`~core.continuum.types.ExpressionState` from *state*.

        Args:
            state: Current continuum state (post temporal engine + decision gate).

        Returns:
            Immutable :class:`~core.continuum.types.ExpressionState` snapshot.
        """
        phase = state.phase
        if phase == ContinuumPhase.FORMLESS:
            return self._formless(state)
        if phase == ContinuumPhase.LIMINAL:
            return self._liminal(state)
        if phase == ContinuumPhase.MANIFEST:
            return self._manifest(state)
        # receding (or any unexpected phase)
        return self._receding(state)

    # ------------------------------------------------------------------
    # Per-phase derivation helpers
    # ------------------------------------------------------------------

    def _formless(self, state: ContinuumState) -> ExpressionState:
        return ExpressionState(
            motion=0.0,
            intensity=0.0,
            form_signature=FormSignature.NONE,
            spatial_presence=SpatialPresence.ABSENT,
            texture_hint="",
            phase_signature=ContinuumPhase.FORMLESS,
        )

    def _liminal(self, state: ContinuumState) -> ExpressionState:
        motion = _clamp(
            state.coherence * 0.5 + state.collapse_tendency * 0.3
        )
        intensity = _clamp(state.presence_intensity * 0.65)
        return ExpressionState(
            motion=motion,
            intensity=intensity,
            form_signature=FormSignature.DIFFUSE_CLUSTER,
            spatial_presence=SpatialPresence.PERIPHERAL,
            texture_hint="soft_granular",
            phase_signature=ContinuumPhase.LIMINAL,
        )

    def _manifest(self, state: ContinuumState) -> ExpressionState:
        action_level = state.decision.action_level
        decision_contribution = _clamp(state.decision.should_act_score)

        motion = _clamp(
            state.presence_intensity * 0.6 + decision_contribution * 0.4
        )
        intensity = _clamp(state.presence_intensity)

        if action_level in (ActionLevel.EXECUTE, ActionLevel.ASSIST):
            form_sig = FormSignature.EXPANDING_RING
            spatial = SpatialPresence.FOREGROUND
            texture = "crisp_edge"
        else:
            form_sig = FormSignature.FOCUSED_POINT
            spatial = SpatialPresence.AMBIENT
            texture = "smooth_gradient"

        return ExpressionState(
            motion=motion,
            intensity=intensity,
            form_signature=form_sig,
            spatial_presence=spatial,
            texture_hint=texture,
            phase_signature=ContinuumPhase.MANIFEST,
        )

    def _receding(self, state: ContinuumState) -> ExpressionState:
        motion = _clamp(state.presence_intensity * 0.3)
        intensity = _clamp(state.presence_intensity * 0.5)
        return ExpressionState(
            motion=motion,
            intensity=intensity,
            form_signature=FormSignature.COLLAPSING_FIELD,
            spatial_presence=SpatialPresence.PERIPHERAL,
            texture_hint="soft_dissolve",
            phase_signature=ContinuumPhase.RECEDING,
        )
