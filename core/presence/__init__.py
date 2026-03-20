"""core/presence — Cross-device presence projection engine."""

from .presence_projection import (
    PresenceProjection,
    ProjectionEvent,
    ProjectionIntensity,
    get_presence_projection,
    reset_presence_projection,
)
from .presence_director import (
    PresenceDirector,
    DirectorConfig,
    get_presence_director,
    reset_presence_director,
)

__all__ = [
    "PresenceProjection",
    "ProjectionEvent",
    "ProjectionIntensity",
    "get_presence_projection",
    "reset_presence_projection",
    "PresenceDirector",
    "DirectorConfig",
    "get_presence_director",
    "reset_presence_director",
]
