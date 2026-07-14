"""core/presence — Cross-device presence projection engine."""

from .android_presence_participation import (
    ANDROID_PRESENCE_PARTICIPATION_AUTHORITY,
    AndroidPresenceParticipationMode,
    AndroidPresenceParticipationRecord,
    AndroidPresenceParticipationSummary,
    derive_android_presence_participation,
    summarise_android_presence_participation,
)
from .presence_director import (
    DirectorConfig,
    PresenceDirector,
    get_presence_director,
    reset_presence_director,
)
from .presence_projection import (
    PresenceProjection,
    ProjectionEvent,
    ProjectionIntensity,
    get_presence_projection,
    reset_presence_projection,
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
