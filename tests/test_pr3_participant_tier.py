from core.participant_tier import (
    PARTICIPANT_TIER_IS_AUTHORITY,
    ParticipantTier,
    resolve_participant_tier,
    tier_allows_runtime_dispatch,
)


def test_participant_tier_authority_sentinel_non_empty():
    assert isinstance(PARTICIPANT_TIER_IS_AUTHORITY, str)
    assert PARTICIPANT_TIER_IS_AUTHORITY


def test_resolve_explicit_full_runtime_host():
    tier = resolve_participant_tier(explicit_tier="FULL_RUNTIME_HOST")
    assert tier == ParticipantTier.FULL_RUNTIME_HOST


def test_resolve_observer_endpoint_from_role():
    tier = resolve_participant_tier(coordination_role="observer_only")
    assert tier == ParticipantTier.OBSERVER_ENDPOINT


def test_tier_allows_runtime_dispatch_only_for_runtime_tiers():
    assert tier_allows_runtime_dispatch(ParticipantTier.FULL_RUNTIME_HOST) is True
    assert tier_allows_runtime_dispatch(ParticipantTier.PARTIAL_RUNTIME_NODE) is True
    assert tier_allows_runtime_dispatch(ParticipantTier.COMMAND_ENDPOINT) is False
    assert tier_allows_runtime_dispatch(ParticipantTier.OBSERVER_ENDPOINT) is False
