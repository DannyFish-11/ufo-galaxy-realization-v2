"""
core.cognitive — Continuous Cognitive Engine (Block-3)
======================================================

Block-3 introduces a **continuous cognitive field** to the Galaxy system,
replacing discrete state triggers with a smooth, always-running cognitive loop.

Modules
-------
- :mod:`~core.cognitive.continuous_state`   — Continuous state variable definitions.
- :mod:`~core.cognitive.cognitive_field_engine` — Periodic tick engine.
- :mod:`~core.cognitive.state_interpreter`  — Maps continuous state to tri-state regions.
- :mod:`~core.cognitive.liminal_dynamics`   — Stabilises the liminal region.
- :mod:`~core.cognitive.decay_controller`   — Post-manifest decay & reabsorption.
- :mod:`~core.cognitive.working_memory`     — Short-lived per-task working memory.
- :mod:`~core.cognitive.long_term_memory`   — Persistent cross-session long-term memory.
- :mod:`~core.cognitive.memory_bias_layer`  — PR-19: bounded memory-informed runtime bias.

All modules are **additive** and do not break existing functionality.
"""

from core.cognitive.continuous_state import CognitiveState, get_cognitive_state
from core.cognitive.cognitive_field_engine import (
    CognitiveFieldEngine,
    get_cognitive_field_engine,
)
from core.cognitive.state_interpreter import StateInterpreter, get_state_interpreter
from core.cognitive.liminal_dynamics import LiminalDynamics, get_liminal_dynamics
from core.cognitive.decay_controller import DecayController, get_decay_controller
from core.cognitive.working_memory import WorkingMemory, get_working_memory
from core.cognitive.long_term_memory import LongTermMemory, get_long_term_memory
from core.cognitive.memory_bias_layer import (
    MemoryBias,
    MemoryPlannerGuidance,
    derive_memory_bias,
    get_memory_planner_guidance,
    build_memory_bias_diagnostics,
)

__all__ = [
    "CognitiveState",
    "get_cognitive_state",
    "CognitiveFieldEngine",
    "get_cognitive_field_engine",
    "StateInterpreter",
    "get_state_interpreter",
    "LiminalDynamics",
    "get_liminal_dynamics",
    "DecayController",
    "get_decay_controller",
    "WorkingMemory",
    "get_working_memory",
    "LongTermMemory",
    "get_long_term_memory",
    # PR-19: memory-informed runtime bias
    "MemoryBias",
    "MemoryPlannerGuidance",
    "derive_memory_bias",
    "get_memory_planner_guidance",
    "build_memory_bias_diagnostics",
]
