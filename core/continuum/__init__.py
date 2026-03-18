"""
core.continuum — State Continuum Protocol
==========================================

Defines the data structures, configuration, and engines for
OpenClawd's state continuum system: a continuous, non-UI presence model
with four phases:

    Formless → Liminal → Manifest → Receding

Public surface:
  - ContinuumPhase           (enum)
  - HumanFieldState          (Pydantic model)
  - UnifiedState             (Pydantic model)
  - ContinuumState           (Pydantic model)
  - DecisionState            (Pydantic model)
  - ExpressionState          (Pydantic model)
  - ContinuumConfig          (Pydantic model)
  - HysteresisConfig         (Pydantic model)
  - DwellConfig              (Pydantic model)
  - FeatureFlags             (Pydantic model)
  - TemporalEngine           (engine class)
  - HysteresisGate           (component class)
  - DwellGuard               (component class)
  - apply_ema                (signal helper)
  - apply_rate_limit         (signal helper)
  - apply_decay              (signal helper)
  - HumanFieldInferrer       (engine class)
  - InteractionRhythm        (data class)
  - StateFusion              (engine class)
  - LiminalFieldEngine       (engine class)
  - LiminalMetrics           (data class)
"""

from core.continuum.types import (
    ContinuumPhase,
    HumanFieldState,
    UnifiedState,
    ContinuumState,
    DecisionState,
    ExpressionState,
    ActionLevel,
    FormSignature,
    SpatialPresence,
)
from core.continuum.config import (
    ContinuumConfig,
    HysteresisConfig,
    DwellConfig,
    FeatureFlags,
    DEFAULT_CONTINUUM_CONFIG,
)
from core.continuum.temporal_engine import (
    TemporalEngine,
    HysteresisGate,
    DwellGuard,
    apply_ema,
    apply_rate_limit,
    apply_decay,
)
from core.continuum.human_field import HumanFieldInferrer, InteractionRhythm
from core.continuum.state_fusion import StateFusion
from core.continuum.liminal_field import LiminalFieldEngine, LiminalMetrics

__all__ = [
    # Enums
    "ContinuumPhase",
    "ActionLevel",
    "FormSignature",
    "SpatialPresence",
    # State models
    "HumanFieldState",
    "UnifiedState",
    "ContinuumState",
    "DecisionState",
    "ExpressionState",
    # Config models
    "ContinuumConfig",
    "HysteresisConfig",
    "DwellConfig",
    "FeatureFlags",
    "DEFAULT_CONTINUUM_CONFIG",
    # Temporal engine
    "TemporalEngine",
    "HysteresisGate",
    "DwellGuard",
    "apply_ema",
    "apply_rate_limit",
    "apply_decay",
    # Human field engine
    "HumanFieldInferrer",
    "InteractionRhythm",
    # State fusion
    "StateFusion",
    # Liminal field engine
    "LiminalFieldEngine",
    "LiminalMetrics",
]
