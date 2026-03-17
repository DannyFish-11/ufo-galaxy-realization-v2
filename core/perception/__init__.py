"""
Galaxy — Multimodal Perception Bus (PR 1)
==========================================

Public surface for the perception sub-package:

    from core.perception import MultimodalBus, ContextFuser
    from core.perception.event_types import PERCEPTION_INGESTED, PERCEPTION_FUSED
"""

from core.perception.context_fuser import ContextFuser
from core.perception.multimodal_bus import MultimodalBus

__all__ = ["MultimodalBus", "ContextFuser"]
