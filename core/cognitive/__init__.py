"""
core.cognitive — Galaxy Cognitive Evolution System
===================================================
PR-25/26/27 — Integrated learning, reflection, and adaptive prediction layer.

This module provides the **cognitive evolution** capabilities for Galaxy:
three interconnected layers that form a closed learning loop:

    ReflectionEngine       — Pre/post-execution verbal reflection
         ↓
    PatternMiner           — Hierarchical pattern discovery from history
         ↓
    AdaptivePredictor      — Pre-execution strategy recommendation
         ↓
    (back to ReflectionEngine via execution outcomes)

Quick start::

    from core.cognitive import (
        get_reflection_engine,
        get_pattern_miner,
        get_adaptive_predictor,
    )

    # Before executing a task — get adaptive recommendation
    rec = get_adaptive_predictor().recommend(task="check weather")
    if rec.strategy:
        print(f"Suggested strategy: {rec.strategy} ({rec.strategy_confidence:.0%})")

    # After task completes — reflection is auto-triggered
    # Query discovered patterns
    patterns = get_pattern_miner().match_patterns(task_type="weather")
    for p in patterns:
        print(f"Pattern: {p.description}")

Modules
-------
reflection_engine:
    Dual-mode reflection (prospective/retrospective) producing natural
    language insights. Inspired by Reflexion (Shinn et al., 2023) and
    PreFlect (2025).

pattern_miner:
    Hierarchical pattern mining with contrastive learning (ExpeL-style),
    recursive abstraction (Generative Agents-style), and activation decay
    (Soar/ACT-R base-level activation).

adaptive_predictor:
    Pre-execution recommendation engine fusing pattern matches and
    reflection insights into actionable strategy hints.

continuous_state, decay_controller, memory_bias_layer, working_memory,
long_term_memory, cognitive_field_engine:
    Existing cognitive infrastructure that the evolution layer builds upon.
"""

from __future__ import annotations

# ── PR-25: Reflection Engine ────────────────────────────────────────────
from core.cognitive.reflection_engine import (
    ReflectionEngine,
    ReflectionRecord,
    get_reflection_engine,
    reset_reflection_engine,
)

# ── PR-26: Pattern Miner ────────────────────────────────────────────────
from core.cognitive.pattern_miner import (
    AbstractionLevel,
    BehaviorPattern,
    PatternMiner,
    get_pattern_miner,
    reset_pattern_miner,
)

# ── PR-27: Adaptive Predictor ───────────────────────────────────────────
from core.cognitive.adaptive_predictor import (
    AdaptivePredictor,
    ExecutionRecommendation,
    get_adaptive_predictor,
    reset_adaptive_predictor,
)

# ── PR-25/26/27: Evolution System Bootstrap ─────────────────────────────
from core.cognitive.evolution_system import (
    init_cognitive_evolution,
    shutdown_cognitive_evolution,
    get_cognitive_health,
)

# ── Existing cognitive infrastructure ────────────────────────────────────
from core.cognitive.continuous_state import (
    CognitiveState,
    get_cognitive_state,
    reset_cognitive_state,
)
from core.cognitive.decay_controller import (
    DecayController,
    get_decay_controller,
    reset_decay_controller,
)
from core.cognitive.memory_bias_layer import (
    MemoryBias,
    MemoryPlannerGuidance,
    derive_memory_bias,
    get_memory_planner_guidance,
    build_memory_bias_diagnostics,
    FALLBACK_MEMORY_BIAS,
    POSTURE_CONTINUITY,
    POSTURE_RETRIEVAL,
    POSTURE_NOVELTY,
)

__all__ = [
    # Reflection Engine (PR-25)
    "ReflectionEngine",
    "ReflectionRecord",
    "get_reflection_engine",
    "reset_reflection_engine",
    # Pattern Miner (PR-26)
    "AbstractionLevel",
    "BehaviorPattern",
    "PatternMiner",
    "get_pattern_miner",
    "reset_pattern_miner",
    # Adaptive Predictor (PR-27)
    "AdaptivePredictor",
    "ExecutionRecommendation",
    "get_adaptive_predictor",
    "reset_adaptive_predictor",
    # Evolution System Bootstrap
    "init_cognitive_evolution",
    "shutdown_cognitive_evolution",
    "get_cognitive_health",
    # Continuous state
    "CognitiveState",
    "get_cognitive_state",
    "reset_cognitive_state",
    # Decay
    "DecayController",
    "get_decay_controller",
    "reset_decay_controller",
    # Memory bias
    "MemoryBias",
    "MemoryPlannerGuidance",
    "derive_memory_bias",
    "get_memory_planner_guidance",
    "build_memory_bias_diagnostics",
    "FALLBACK_MEMORY_BIAS",
    "POSTURE_CONTINUITY",
    "POSTURE_RETRIEVAL",
    "POSTURE_NOVELTY",
]
