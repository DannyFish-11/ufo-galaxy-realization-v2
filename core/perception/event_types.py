"""
Galaxy — Perception Event Type Aliases (PR 1)
=============================================

Re-exports the perception-specific ``EventType`` members from the canonical
``integration.event_bus`` so that callers inside ``core.perception`` can import
them without a circular-dependency chain.

Usage::

    from core.perception.event_types import PERCEPTION_INGESTED, PERCEPTION_FUSED
"""

from integration.event_bus import EventType

#: Fired by :class:`~core.perception.multimodal_bus.MultimodalBus` immediately
#: after raw multimodal inputs are received (before fusion).
PERCEPTION_INGESTED = EventType.PERCEPTION_INGESTED

#: Fired by :class:`~core.perception.multimodal_bus.MultimodalBus` after the
#: :class:`~core.perception.context_fuser.ContextFuser` has produced the
#: ``fusion_summary`` field.
PERCEPTION_FUSED = EventType.PERCEPTION_FUSED

__all__ = ["PERCEPTION_INGESTED", "PERCEPTION_FUSED"]
