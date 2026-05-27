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
from .android_presence_participation import (
    AndroidPresenceParticipationMode,
    AndroidPresenceParticipationRecord,
    AndroidPresenceParticipationSummary,
    ANDROID_PRESENCE_PARTICIPATION_AUTHORITY,
    derive_android_presence_participation,
    summarise_android_presence_participation,
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
    "AndroidPresenceParticipationMode",
    "AndroidPresenceParticipationRecord",
    "AndroidPresenceParticipationSummary",
    "ANDROID_PRESENCE_PARTICIPATION_AUTHORITY",
    "derive_android_presence_participation",
    "summarise_android_presence_participation",
]
