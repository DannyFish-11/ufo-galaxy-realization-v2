"""
core.continuum — State Continuum Protocol
==========================================

Defines the data structures and configuration for OpenClawd's state continuum
system: a continuous, non-UI presence model with four phases:

    Formless → Liminal → Manifest → Receding

Public surface:
  - ContinuumPhase       (enum)
  - HumanFieldState      (Pydantic model)
  - UnifiedState         (Pydantic model)
  - ContinuumState       (Pydantic model)
  - DecisionState        (Pydantic model)
  - ExpressionState      (Pydantic model)
  - ContinuumConfig      (Pydantic model)
  - HysteresisConfig     (Pydantic model)
  - DwellConfig          (Pydantic model)
  - FeatureFlags         (Pydantic model)
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
]
