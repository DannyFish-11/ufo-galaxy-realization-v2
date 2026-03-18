"""
core.continuum.config — Default Configuration for the State Continuum
======================================================================

Defines the configuration structures and default thresholds for:

  - Hysteresis  (dual-threshold enter/exit per phase)
  - Dwell times (minimum time-in-phase before transition is allowed)
  - EMA smoothing alpha
  - Max delta per tick (rate limiter)
  - Feature flags (enabled / debug)

All values can be overridden at runtime by passing a populated
``ContinuumConfig`` to the engine constructors.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Sub-config models
# ---------------------------------------------------------------------------


class HysteresisConfig(BaseModel):
    """Dual-threshold hysteresis settings for phase transitions.

    Each phase transition has a separate *enter* threshold (higher, to
    commit to the new phase) and an *exit* threshold (lower, to allow
    leaving).  This prevents rapid oscillation near the boundary.

    Default values::

        liminal_enter  = 0.68   # presence_intensity to enter liminal
        liminal_exit   = 0.45   # drop below this to leave liminal
        manifest_enter = 0.78   # coherence/collapse to enter manifest
        manifest_exit  = 0.52   # drop below this to leave manifest
    """

    liminal_enter: float = Field(
        default=0.68,
        ge=0.0,
        le=1.0,
        description="Minimum signal strength to transition formless → liminal.",
    )
    liminal_exit: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Signal must drop below this to leave liminal state.",
    )
    manifest_enter: float = Field(
        default=0.78,
        ge=0.0,
        le=1.0,
        description="Minimum collapse_tendency to transition liminal → manifest.",
    )
    manifest_exit: float = Field(
        default=0.52,
        ge=0.0,
        le=1.0,
        description="Signal must drop below this to leave manifest state.",
    )

    model_config = {"from_attributes": True}


class DwellConfig(BaseModel):
    """Minimum dwell times (milliseconds) per phase.

    A phase transition is blocked until the system has remained in the
    current phase for at least ``dwell_<phase>_ms`` milliseconds.  This
    prevents micro-flicker and perceptual jitter.

    Default values::

        liminal_ms  =  800
        manifest_ms = 1200
        receding_ms =  600
    """

    liminal_ms: int = Field(
        default=800,
        ge=0,
        description="Minimum time (ms) to stay in liminal before leaving.",
    )
    manifest_ms: int = Field(
        default=1200,
        ge=0,
        description="Minimum time (ms) to stay in manifest before leaving.",
    )
    receding_ms: int = Field(
        default=600,
        ge=0,
        description="Minimum time (ms) to stay in receding before returning to formless.",
    )

    model_config = {"from_attributes": True}


class FeatureFlags(BaseModel):
    """Runtime feature flags for the continuum system.

    Flags can be toggled without redeployment by updating the config
    object passed to the orchestrator.

    Note:
        When ``enabled=False`` the orchestrator returns a static formless
        ``ContinuumState`` and skips all computation, adding near-zero
        latency overhead.

    Per-component flags
    -------------------
    ``enable_perception``, ``enable_human_field``, ``enable_liminal_field``,
    and ``enable_decision_gate`` allow individual pipeline stages to be
    disabled independently.  Disabling a stage causes the orchestrator to
    substitute a safe default value for that stage's output while keeping
    all downstream stages operational.  Backward compatibility is preserved:
    all flags default to ``True``.

    Performance guardrails
    ----------------------
    ``max_tick_ms``
        Per-tick time budget in milliseconds.  When the pipeline exceeds
        this budget the result is discarded and a degraded formless state
        is returned (``degrade_reason="tick_budget_exceeded"``).
        ``0`` means *no limit* (default, preserves existing behaviour).
    ``sampling_rate``
        Fraction of ticks that are actually executed (0.0–1.0).  Ticks
        that are skipped return the previous state unchanged (or a
        ``formless_default`` on the very first call).
        ``1.0`` means *run every tick* (default).
    """

    enabled: bool = Field(
        default=True,
        description="Master switch.  When False, the continuum system is bypassed.",
    )
    debug: bool = Field(
        default=False,
        description=(
            "When True, emit verbose phase-transition and decision-gate "
            "events to the application log."
        ),
    )
    allow_emergency_jump: bool = Field(
        default=False,
        description=(
            "When True, allows the forbidden formless → manifest direct "
            "transition under explicit emergency conditions."
        ),
    )

    # ------------------------------------------------------------------
    # Per-component flags
    # ------------------------------------------------------------------

    enable_perception: bool = Field(
        default=True,
        description=(
            "When False, the perception/PerceptionFrame stage is skipped and a "
            "minimal default frame is used regardless of caller input."
        ),
    )
    enable_human_field: bool = Field(
        default=True,
        description=(
            "When False, HumanFieldInferrer is skipped and a default "
            "HumanFieldState is substituted."
        ),
    )
    enable_liminal_field: bool = Field(
        default=True,
        description=(
            "When False, LiminalFieldEngine is skipped; liminal metrics are "
            "zeroed and unified state is not enriched."
        ),
    )
    enable_decision_gate: bool = Field(
        default=True,
        description=(
            "When False, DecisionGate is skipped and a default DecisionState "
            "(action_level=OBSERVE) is attached."
        ),
    )

    # ------------------------------------------------------------------
    # Performance guardrails
    # ------------------------------------------------------------------

    max_tick_ms: float = Field(
        default=0.0,
        ge=0.0,
        description=(
            "Per-tick wall-clock time budget in milliseconds.  When the pipeline "
            "exceeds this value the result is discarded and a degraded formless "
            "state is returned.  0 means no limit (default)."
        ),
    )
    sampling_rate: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of continuum ticks that are actually executed.  "
            "Skipped ticks return the last cached state (or a formless default).  "
            "1.0 = run every tick (default)."
        ),
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Top-level config model
# ---------------------------------------------------------------------------


class ContinuumConfig(BaseModel):
    """Master configuration object for the state continuum system.

    All sub-configs carry sensible defaults so callers only need to
    supply the values they wish to override.

    Example override::

        cfg = ContinuumConfig(
            ema_alpha=0.3,
            hysteresis=HysteresisConfig(liminal_enter=0.72),
            flags=FeatureFlags(debug=True),
        )

    Typical config-file mapping (JSON / YAML key path → field)::

        continuum.enabled             → flags.enabled
        continuum.debug               → flags.debug
        continuum.tick_ms             → tick_ms
        continuum.ema_alpha           → ema_alpha
        continuum.max_delta_per_tick  → max_delta_per_tick
        continuum.hysteresis.*        → hysteresis.*
        continuum.dwell_ms.*          → dwell.*
    """

    tick_ms: int = Field(
        default=120,
        ge=10,
        description="Target evaluation interval in milliseconds.",
    )
    ema_alpha: float = Field(
        default=0.25,
        gt=0.0,
        le=1.0,
        description=(
            "Exponential moving-average smoothing factor. "
            "Lower = smoother but slower to react; higher = more responsive."
        ),
    )
    max_delta_per_tick: float = Field(
        default=0.08,
        gt=0.0,
        le=1.0,
        description=(
            "Maximum allowed change in presence_intensity per tick. "
            "Acts as a rate-limiter on top of EMA smoothing."
        ),
    )
    hysteresis: HysteresisConfig = Field(
        default_factory=HysteresisConfig,
        description="Dual-threshold hysteresis settings for each phase transition.",
    )
    dwell: DwellConfig = Field(
        default_factory=DwellConfig,
        description="Minimum dwell times per phase.",
    )
    flags: FeatureFlags = Field(
        default_factory=FeatureFlags,
        description="Runtime feature flags.",
    )
    timeout_receding_ms: int = Field(
        default=5000,
        ge=0,
        description=(
            "Milliseconds of inactivity after which the system initiates "
            "a forced receding transition from manifest."
        ),
    )
    min_presence_formless: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        description=(
            "Presence intensity floor below which the system snaps back to "
            "formless (used by the return engine during receding)."
        ),
    )

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Default singleton (import-ready)
# ---------------------------------------------------------------------------

DEFAULT_CONTINUUM_CONFIG: ContinuumConfig = ContinuumConfig()
"""Pre-built default config instance.

Import and use directly when no customisation is required::

    from core.continuum.config import DEFAULT_CONTINUUM_CONFIG
"""
