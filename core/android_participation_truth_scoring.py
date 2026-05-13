"""Shared Android participation truth normalization and scoring helpers."""

from __future__ import annotations

from typing import Any, Dict, Optional

ANDROID_PARTICIPATION_TIER_SCORE_BONUS: Dict[str, int] = {
    # Keep increments modest and monotonic: higher participation tiers should
    # break ties among otherwise-ready candidates without overpowering hard
    # readiness/participation/posture gates or stronger runtime penalties.
    "fully_attached": 4,
    "dispatch_eligible": 8,
    "distributed_participant": 12,
}


def normalize_android_participation_tier(
    android_participation_evidence: Optional[Dict[str, Any]],
) -> str:
    if not isinstance(android_participation_evidence, dict):
        return ""
    tier_value = android_participation_evidence.get("tier")
    if tier_value is None:
        return ""
    return str(tier_value).strip().lower()


def get_android_participation_tier_score_bonus(
    android_participation_evidence: Optional[Dict[str, Any]],
) -> int:
    tier = normalize_android_participation_tier(android_participation_evidence)
    return ANDROID_PARTICIPATION_TIER_SCORE_BONUS.get(tier, 0)


__all__ = [
    "ANDROID_PARTICIPATION_TIER_SCORE_BONUS",
    "normalize_android_participation_tier",
    "get_android_participation_tier_score_bonus",
]
