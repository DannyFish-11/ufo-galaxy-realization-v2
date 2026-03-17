"""
Galaxy — Interaction Mode Engine (PR 2)
========================================

Exposes the public surface of the interaction-mode sub-package::

    from core.interaction import SceneInterpreter, InteractionMode, InteractionDecision
"""

from core.interaction.interaction_types import InteractionDecision, InteractionMode
from core.interaction.mode_selector import ModeSelector
from core.interaction.scene_interpreter import SceneInterpreter

__all__ = [
    "InteractionDecision",
    "InteractionMode",
    "ModeSelector",
    "SceneInterpreter",
]
