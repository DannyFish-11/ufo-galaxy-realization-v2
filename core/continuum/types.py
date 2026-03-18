"""
core.continuum.types — State Continuum Protocol Data Structures
===============================================================

Defines the canonical types for OpenClawd's state continuum system.
All models are serializable to dict/JSON and carry no UI semantics.

Phase lifecycle:
    formless  →  liminal  →  manifest  →  receding  →  formless
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ContinuumPhase(str, Enum):
    """The four mutually-exclusive phases of the state continuum.

    Transitions must follow the allowed graph defined in
    docs/PHASE_TRANSITION_TABLE.md.  Hard-jumps (e.g. formless → manifest)
    are forbidden except in emergency/degraded mode.
    """

    FORMLESS = "formless"
    """Silent sensing, minimal presence.  Default / safe-fallback state."""

    LIMINAL = "liminal"
    """Intent injected, structure undetermined, window for intervention open."""

    MANIFEST = "manifest"
    """Structure formed, action ready or in progress."""

    RECEDING = "receding"
    """Expression dissolving, returning to silence."""


class ActionLevel(str, Enum):
    """Graduated action output from the decision gate."""

    OBSERVE = "observe"
    """Monitor only — no external signal emitted."""

    HINT = "hint"
    """Subtle ambient signal — low interruption cost."""

    ASSIST = "assist"
    """Proactive partial engagement — moderate cost."""

    EXECUTE = "execute"
    """Full action — high cost, must pass decision gate threshold."""


class FormSignature(str, Enum):
    """Qualitative shape descriptor for expression output (non-UI)."""

    NONE = "none"
    DIFFUSE_CLUSTER = "diffuse_cluster"
    FOCUSED_POINT = "focused_point"
    EXPANDING_RING = "expanding_ring"
    COLLAPSING_FIELD = "collapsing_field"


class SpatialPresence(str, Enum):
    """Abstract spatial weight hint for expression output (non-UI)."""

    ABSENT = "absent"
    PERIPHERAL = "peripheral"
    AMBIENT = "ambient"
    FOREGROUND = "foreground"


# ---------------------------------------------------------------------------
# Input / sensing models
# ---------------------------------------------------------------------------


class HumanFieldState(BaseModel):
    """Inferred state of the human field from multimodal perception signals.

    All values are normalised to [0.0, 1.0] unless noted.
    A consumer should treat this as a snapshot, not a running average —
    smoothing is the responsibility of the temporal engine.
    """

    attention: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Estimated attention level directed toward the system.",
    )
    focus_level: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Depth of cognitive focus on the current task context. "
            "Higher values increase interruption cost."
        ),
    )
    fatigue: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated fatigue.  High fatigue suppresses manifest transitions.",
    )
    intent_probability: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Probability that an actionable intent is forming.",
    )
    interruption_sensitivity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description=(
            "How disruptive an interruption would be right now. "
            "Feeds directly into interruption_cost in the decision gate."
        ),
    )
    input_rhythm: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Normalised input event rate (keyboard / pointer / touch).",
    )
    speaking: bool = Field(
        default=False,
        description="True when voice-activity detection indicates active speech.",
    )
    motion_level: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Video-derived motion proxy (0 = still, 1 = high motion).",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds when this snapshot was captured.",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Fusion / intermediate models
# ---------------------------------------------------------------------------


class UnifiedState(BaseModel):
    """Fusion of human field, world context, and recent history.

    Produced by state_fusion and consumed by the temporal engine and
    liminal field engine.  Carries the raw, un-smoothed signal values
    before hysteresis and dwell filtering are applied.
    """

    human: HumanFieldState = Field(
        default_factory=HumanFieldState,
        description="Current human field snapshot.",
    )
    context_utility: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Utility estimate of acting given the current world context.",
    )
    urgency: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Time-sensitivity of potential action.",
    )
    action_risk: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Estimated risk of taking action (irreversibility, side-effects).",
    )
    uncertainty: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Model confidence about current context (1 = fully uncertain).",
    )
    phase_candidate: ContinuumPhase = Field(
        default=ContinuumPhase.FORMLESS,
        description="Raw phase suggested by mode-collapse before temporal filtering.",
    )
    candidate_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the phase_candidate before hysteresis.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds of this fusion snapshot.",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Expression / output models
# ---------------------------------------------------------------------------


class ExpressionState(BaseModel):
    """Abstract, non-UI expression parameters describing system presence.

    Consumers (rendering layers, audio engines, haptics, etc.) translate
    these values into medium-specific signals.  This model carries *no*
    widget, page, or view semantics.
    """

    motion: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Abstract motion energy (0 = still, 1 = full kinetic).",
    )
    intensity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Overall presence intensity.",
    )
    form_signature: FormSignature = Field(
        default=FormSignature.NONE,
        description="Qualitative shape / form hint for rendering.",
    )
    spatial_presence: SpatialPresence = Field(
        default=SpatialPresence.ABSENT,
        description="Abstract spatial weight / proximity hint.",
    )
    texture_hint: str = Field(
        default="",
        description=(
            "Optional freeform texture descriptor "
            "(e.g. 'soft_granular', 'crisp_edge').  Empty = no hint."
        ),
    )
    phase_signature: ContinuumPhase = Field(
        default=ContinuumPhase.FORMLESS,
        description="Phase this expression snapshot was computed for.",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Decision model
# ---------------------------------------------------------------------------


class DecisionState(BaseModel):
    """Output of the decision gate for a single evaluation cycle.

    The gate computes::

        should_act_score = value - interruption_cost - risk_cost

    where::

        value             = intent_probability × context_utility × urgency
        interruption_cost = interruption_sensitivity × focus_level × timing_penalty
        risk_cost         = action_risk × uncertainty
    """

    should_act_score: float = Field(
        default=0.0,
        description="Net score from the decision gate formula.",
    )
    action_level: ActionLevel = Field(
        default=ActionLevel.OBSERVE,
        description="Graduated action level derived from should_act_score.",
    )
    decision_reason: str = Field(
        default="",
        description="Human-readable explanation of this decision.",
    )
    decision_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the action_level classification.",
    )
    value_score: float = Field(
        default=0.0,
        description="Intermediate: value component of the gate formula.",
    )
    interruption_cost: float = Field(
        default=0.0,
        description="Intermediate: interruption cost component.",
    )
    risk_cost: float = Field(
        default=0.0,
        description="Intermediate: risk cost component.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds of this decision snapshot.",
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Top-level continuum state (the wire format)
# ---------------------------------------------------------------------------


class ContinuumState(BaseModel):
    """Unified output of a single continuum evaluation cycle.

    This is the canonical ``state_continuum`` object attached to
    OpenClawd responses.  It carries no UI semantics and is fully
    serialisable to dict/JSON.

    Degraded fallback example::

        ContinuumState(
            phase=ContinuumPhase.FORMLESS,
            presence_intensity=0.0,
            degraded=True,
            degrade_reason="continuum_internal_error",
        )
    """

    version: int = Field(
        default=1,
        description="Protocol version. Increment on breaking schema changes.",
    )
    trace_id: str = Field(
        default_factory=lambda: f"cont_{uuid.uuid4().hex[:12]}",
        description="Correlation ID for log tracing.",
    )
    phase: ContinuumPhase = Field(
        default=ContinuumPhase.FORMLESS,
        description="Current phase of the state continuum.",
    )
    presence_intensity: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="EMA-smoothed overall presence strength.",
    )
    coherence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Degree to which signals form a coherent intent.",
    )
    ambiguity: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Inverse of coherence; high when intent is undetermined.",
    )
    collapse_tendency: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Probability mass pushing toward phase collapse (liminal → manifest).",
    )
    retreat_tendency: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Probability mass pushing toward retreat (manifest/liminal → receding).",
    )
    stability: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Temporal stability; low values indicate recent phase oscillation.",
    )
    decision: DecisionState = Field(
        default_factory=DecisionState,
        description="Decision gate output for this cycle.",
    )
    expression: ExpressionState = Field(
        default_factory=ExpressionState,
        description="Expression parameters for this cycle.",
    )
    degraded: bool = Field(
        default=False,
        description="True when continuum ran in degraded/fallback mode.",
    )
    degrade_reason: Optional[str] = Field(
        default=None,
        description="Populated only when degraded=True.",
    )
    timestamp: float = Field(
        default_factory=time.time,
        description="Unix epoch seconds of this state snapshot.",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Opaque extensibility bag for future fields.",
    )

    model_config = {"from_attributes": True}

    # ------------------------------------------------------------------
    # Convenience factories
    # ------------------------------------------------------------------

    @classmethod
    def formless_default(cls) -> "ContinuumState":
        """Return a safe, minimal formless state (used as startup default)."""
        return cls(
            phase=ContinuumPhase.FORMLESS,
            presence_intensity=0.0,
            coherence=0.0,
            ambiguity=1.0,
            collapse_tendency=0.0,
            retreat_tendency=0.0,
            stability=1.0,
        )

    @classmethod
    def degraded_fallback(cls, reason: str = "continuum_internal_error") -> "ContinuumState":
        """Return a degraded-mode formless state for error paths."""
        return cls(
            phase=ContinuumPhase.FORMLESS,
            presence_intensity=0.0,
            degraded=True,
            degrade_reason=reason,
        )
