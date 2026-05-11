"""core/android_originated_main_chain_ingress.py
=================================================
PR-Final: Android-Originated Main Chain Ingress
================================================

背景
----
Android-originated NL 请求（跨设备 NL 路径）必须被 V2 中心主链统一接纳，
不能形成旁挂路径。本模块提供统一的 origin / lineage / authority 标识，
确保 Android-originated 流量进入现有 continuum / governance / truth /
reconciliation / closure 体系。

设计原则
--------
1. **不新增平行治理链** — 本模块是接纳标识层，不是新链路。
   所有 Android-originated 流量最终都经由现有主链处理。
2. **统一 lineage** — Android-originated 请求携带完整 lineage 标签，
   供 routing / protocol / dispatch / ingress / reconciliation / closure /
   audit 层一致追踪。
3. **全链 lineage 类型** — 定义以下所有 lineage：
   canonical, fallback, compat, degraded, android_originated,
   center_originated, replay_assisted, recovery_assisted.
4. **强制 main-chain 路由检查** — 在接纳时检查 Android NL 是否经过主链，
   未经主链的 Android-originated NL 被标记为 authority boundary violation。
5. **与闭环治理集成** — 提供 ``build_android_originated_governance_context()``
   供 closed_loop_governance_consolidation 层使用。

公共 API
--------
::

    from core.android_originated_main_chain_ingress import (
        ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL,
        ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION,
        ExecutionLineageKind,
        AndroidOriginatedIngressContext,
        AndroidOriginatedIngressResult,
        classify_execution_lineage,
        accept_android_originated_nl_into_main_chain,
        build_android_originated_governance_context,
        is_android_originated_main_chain_accepted,
        GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN,
        GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED,
        GAP_ANDROID_ORIGINATED_REPLAY_COMBINED,
        GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED,
    )
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional

from core.android_nl_semantic_chain_contract import (
    ANDROID_CROSS_DEVICE_NL_PATH_TYPE,
    ANDROID_NL_CARRIER_SOURCE,
    V2_SEMANTIC_AUTHORITY,
    is_android_nl_carrier,
    is_v2_semantic_authority_path,
)
from core.android_originated_authority_boundary import (
    ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY,
    AndroidParticipationKind,
    AndroidSignalPermissionLevel,
    classify_android_participation,
)

logger = logging.getLogger("Galaxy.AndroidOriginatedMainChainIngress")

# ---------------------------------------------------------------------------
# Contract sentinels & version
# ---------------------------------------------------------------------------

ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL: str = (
    "ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL::PR_FINAL::present "
    "core.android_originated_main_chain_ingress is the canonical center-side "
    "main chain acceptance layer for Android-originated NL traffic. "
    "Android-originated NL MUST enter via V2 DesktopPresenceRuntime → OpenClawd. "
    "All lineage types (canonical/fallback/compat/degraded/android_originated/ "
    "center_originated/replay_assisted/recovery_assisted) are unified here. "
    "All tests MUST reference this sentinel to confirm the ingress layer is loaded."
)

ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION: str = "final.0.0"

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ANDROID_ORIGINATED_MUST_CARRY_LINEAGE_POLICY: str = (
    "POLICY::ANDROID_ORIGINATED_MUST_CARRY_LINEAGE_V1: "
    "All Android-originated NL requests MUST carry a lineage identifier "
    "stamped at ingress time. The lineage MUST be preserved through "
    "routing / protocol / dispatch / ingress / reconciliation / closure / "
    "audit layers. A request without lineage is treated as non-canonical."
)

ANDROID_ORIGINATED_FALLBACK_BLOCKS_MATURE_CLOSURE_POLICY: str = (
    "POLICY::ANDROID_ORIGINATED_FALLBACK_BLOCKS_MATURE_CLOSURE_V1: "
    "An Android-originated request that also used a fallback path CANNOT "
    "result in a mature canonical closure. The combined android_originated + "
    "fallback lineage MUST be surfaced as a mature closure blocker."
)

ANDROID_ORIGINATED_REPLAY_BLOCKS_CANONICAL_LINEAGE_POLICY: str = (
    "POLICY::ANDROID_ORIGINATED_REPLAY_BLOCKS_CANONICAL_LINEAGE_V1: "
    "An Android-originated request assisted by replay or recovery CANNOT "
    "be classified as canonical_path_used. The replay/recovery lineage "
    "downgrades authority quality to 'replay_assisted' or 'recovery_assisted'."
)

# ---------------------------------------------------------------------------
# Gap type constants (for closed_loop_governance_consolidation integration)
# ---------------------------------------------------------------------------

GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN: str = "android_originated_without_main_chain"
GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED: str = "android_originated_fallback_combined"
GAP_ANDROID_ORIGINATED_REPLAY_COMBINED: str = "android_originated_replay_combined"
GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED: str = "android_originated_takeover_combined"
GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL: str = "android_originated_conflict_partial"
GAP_ANDROID_ORIGINATED_DUPLICATE: str = "android_originated_duplicate"
GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE: str = "android_originated_multi_device_race"
GAP_ANDROID_ORIGINATED_STALE_EVIDENCE: str = "android_originated_stale_evidence"

# ---------------------------------------------------------------------------
# Execution lineage kind enum
# ---------------------------------------------------------------------------


class ExecutionLineageKind(str, Enum):
    """Full-chain lineage classification for a governed execution.

    This enum unifies all lineage types across the dual-repo system,
    covering both normal and degraded paths.

    Values
    ------
    canonical
        The execution followed the canonical main chain path end-to-end.
        Center lifecycle authority confirmed, reconciliation fully accepted,
        no fallback/compat/degraded/replay paths used.

    center_originated
        The execution was originated by V2 center (not Android-originated).
        May be canonical or degraded depending on path quality.

    android_originated
        The execution was originated by Android via cross-device NL path.
        Android is the NL carrier; V2 OpenClawd is the semantic authority.
        Lineage is android_originated regardless of subsequent path quality.

    fallback
        A fallback path was used at some point in the execution lifecycle.
        Fallback prevents canonical closure classification.

    compat
        A compat path was used (e.g. uplink-only observation treated as
        compat terminal). Compat prevents canonical closure classification.

    degraded
        Execution completed via degraded path (unstable runtime health,
        partial observation, or accepted_partial_observation reconciliation).

    replay_assisted
        Execution evidence includes replay-queue data rather than
        real-time Android evidence. Replay-assisted cannot be canonical.

    recovery_assisted
        Execution was closed via recovery path (post-outage recovery,
        stale evidence recovery). Recovery-assisted cannot be canonical.

    android_originated_fallback
        Android-originated request that also used a fallback path.
        Worst combination: both origin uncertainty and path degradation.

    android_originated_replay
        Android-originated request with replay-assisted evidence.

    android_originated_recovery
        Android-originated request with recovery-assisted closure.

    android_originated_takeover
        Android-originated request during a takeover scenario.

    android_originated_conflict
        Android-originated request with conflict/partial/duplicate observations.

    unknown
        Lineage could not be determined.
    """

    canonical = "canonical"
    center_originated = "center_originated"
    android_originated = "android_originated"
    fallback = "fallback"
    compat = "compat"
    degraded = "degraded"
    replay_assisted = "replay_assisted"
    recovery_assisted = "recovery_assisted"
    android_originated_fallback = "android_originated_fallback"
    android_originated_replay = "android_originated_replay"
    android_originated_recovery = "android_originated_recovery"
    android_originated_takeover = "android_originated_takeover"
    android_originated_conflict = "android_originated_conflict"
    unknown = "unknown"


# Lineage kinds that block canonical closure.
_NON_CANONICAL_LINEAGE_KINDS: FrozenSet[ExecutionLineageKind] = frozenset(
    {
        ExecutionLineageKind.android_originated,
        ExecutionLineageKind.fallback,
        ExecutionLineageKind.compat,
        ExecutionLineageKind.degraded,
        ExecutionLineageKind.replay_assisted,
        ExecutionLineageKind.recovery_assisted,
        ExecutionLineageKind.android_originated_fallback,
        ExecutionLineageKind.android_originated_replay,
        ExecutionLineageKind.android_originated_recovery,
        ExecutionLineageKind.android_originated_takeover,
        ExecutionLineageKind.android_originated_conflict,
        ExecutionLineageKind.unknown,
    }
)


# ---------------------------------------------------------------------------
# Ingress context and result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AndroidOriginatedIngressContext:
    """Context for an Android-originated NL ingress request.

    This is stamped at the ingress boundary and carried through the main chain.
    All fields are machine-readable for lineage and audit purposes.

    Attributes
    ----------
    device_id
        The Android device that originated the NL request.
    session_id
        Conversation session ID for this request.
    invocation_id
        Correlation ID for this specific invocation.
    nl_path_type
        NL path type (should be ``android_cross_device_nl`` for main-chain traffic).
    carrier_source
        DPR source tag (``android_goal_execution`` for cross-device NL).
    semantic_authority
        Semantic authority (always ``v2_openclawd`` for main-chain paths).
    lineage
        Initial lineage classification at ingress time.
    is_main_chain_accepted
        True iff this request has been accepted into the V2 main chain.
    participation_kind
        Android participation type for this request.
    is_stale
        True if the evidence is stale.
    is_replay
        True if the request came from a replay queue.
    is_recovery_assisted
        True if this request is recovery-assisted.
    is_takeover_scenario
        True if this request is part of a takeover scenario.
    is_conflict_present
        True if there are conflicting observations.
    is_multi_device_concurrent
        True if multiple devices are concurrently active.
    ingress_ts
        Unix epoch timestamp of ingress.
    """

    device_id: str
    session_id: str
    invocation_id: str
    nl_path_type: str = ANDROID_CROSS_DEVICE_NL_PATH_TYPE
    carrier_source: str = ANDROID_NL_CARRIER_SOURCE
    semantic_authority: str = V2_SEMANTIC_AUTHORITY
    lineage: ExecutionLineageKind = ExecutionLineageKind.android_originated
    is_main_chain_accepted: bool = False
    participation_kind: AndroidParticipationKind = (
        AndroidParticipationKind.android_originated_nl
    )
    is_stale: bool = False
    is_replay: bool = False
    is_recovery_assisted: bool = False
    is_takeover_scenario: bool = False
    is_conflict_present: bool = False
    is_multi_device_concurrent: bool = False
    is_duplicate: bool = False
    ingress_ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "session_id": self.session_id,
            "invocation_id": self.invocation_id,
            "nl_path_type": self.nl_path_type,
            "carrier_source": self.carrier_source,
            "semantic_authority": self.semantic_authority,
            "lineage": self.lineage.value,
            "is_main_chain_accepted": self.is_main_chain_accepted,
            "participation_kind": self.participation_kind.value,
            "is_stale": self.is_stale,
            "is_replay": self.is_replay,
            "is_recovery_assisted": self.is_recovery_assisted,
            "is_takeover_scenario": self.is_takeover_scenario,
            "is_conflict_present": self.is_conflict_present,
            "is_multi_device_concurrent": self.is_multi_device_concurrent,
            "is_duplicate": self.is_duplicate,
            "ingress_ts": self.ingress_ts,
            "_sentinel": ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL,
            "_contract_version": ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION,
        }


@dataclass
class AndroidOriginatedIngressResult:
    """Result of accepting an Android-originated NL request into the main chain.

    Attributes
    ----------
    accepted
        True iff the request was successfully accepted into the V2 main chain.
    lineage
        Final lineage classification after acceptance.
    gap_types
        List of gap types that prevent canonical closure.
    authority_source
        Authority source for this request (should be ``v2_openclawd`` for
        main-chain accepted requests).
    is_main_chain_accepted
        True iff the request entered the V2 main chain.
    mature_closure_blocked
        True iff one or more gap types prevent mature canonical closure.
    blocking_reason
        Human-readable reason if acceptance was rejected or closure was blocked.
    context
        The ingress context that was evaluated.
    """

    accepted: bool
    lineage: ExecutionLineageKind
    gap_types: List[str]
    authority_source: str
    is_main_chain_accepted: bool
    mature_closure_blocked: bool
    blocking_reason: str
    context: AndroidOriginatedIngressContext

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted": self.accepted,
            "lineage": self.lineage.value,
            "gap_types": list(self.gap_types),
            "authority_source": self.authority_source,
            "is_main_chain_accepted": self.is_main_chain_accepted,
            "mature_closure_blocked": self.mature_closure_blocked,
            "blocking_reason": self.blocking_reason,
            "context": self.context.to_dict(),
            "_sentinel": ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL,
            "_contract_version": ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Lineage classification
# ---------------------------------------------------------------------------


def classify_execution_lineage(
    *,
    is_android_originated: bool,
    is_center_originated: bool = False,
    fallback_path_used: bool = False,
    compat_path_used: bool = False,
    degraded_path_used: bool = False,
    is_replay_assisted: bool = False,
    is_recovery_assisted: bool = False,
    is_takeover_scenario: bool = False,
    is_conflict_present: bool = False,
    is_fully_canonical: bool = False,
) -> ExecutionLineageKind:
    """Classify the full-chain execution lineage.

    Precedence:
    1. Combined android_originated + degradation scenarios (worst quality)
    2. Android-originated base case
    3. Pure degradation cases (center-originated)
    4. Canonical
    5. Unknown

    Parameters
    ----------
    is_android_originated:
        True iff the execution was originated by Android (NL carrier path).
    is_center_originated:
        True iff originated by V2 center directly.
    fallback_path_used:
        True iff a fallback path was used in execution.
    compat_path_used:
        True iff a compat path was used.
    degraded_path_used:
        True iff a degraded path was used.
    is_replay_assisted:
        True iff evidence included replay-queue data.
    is_recovery_assisted:
        True iff closure was recovery-assisted.
    is_takeover_scenario:
        True iff this is a takeover scenario.
    is_conflict_present:
        True iff there are conflicting/partial/duplicate observations.
    is_fully_canonical:
        True iff all canonical conditions are met (no degradation, center authority,
        full reconciliation).

    Returns
    -------
    ExecutionLineageKind
        The classified lineage for this execution.
    """
    # Combined android-originated + degradation scenarios (P0 gate cases)
    if is_android_originated:
        if fallback_path_used:
            return ExecutionLineageKind.android_originated_fallback
        if is_replay_assisted:
            return ExecutionLineageKind.android_originated_replay
        if is_recovery_assisted:
            return ExecutionLineageKind.android_originated_recovery
        if is_takeover_scenario:
            return ExecutionLineageKind.android_originated_takeover
        if is_conflict_present:
            return ExecutionLineageKind.android_originated_conflict
        # Pure android_originated (no additional degradation)
        return ExecutionLineageKind.android_originated

    # Center-originated degradation cases
    if fallback_path_used:
        return ExecutionLineageKind.fallback
    if compat_path_used:
        return ExecutionLineageKind.compat
    if degraded_path_used:
        return ExecutionLineageKind.degraded
    if is_replay_assisted:
        return ExecutionLineageKind.replay_assisted
    if is_recovery_assisted:
        return ExecutionLineageKind.recovery_assisted

    # Canonical (all conditions clean)
    if is_fully_canonical or is_center_originated:
        return ExecutionLineageKind.canonical

    return ExecutionLineageKind.unknown


def is_canonical_lineage(lineage: ExecutionLineageKind) -> bool:
    """Return True iff *lineage* represents a fully canonical execution.

    Only :attr:`ExecutionLineageKind.canonical` and
    :attr:`ExecutionLineageKind.center_originated` are canonical.
    All other lineage kinds block canonical closure.
    """
    return lineage not in _NON_CANONICAL_LINEAGE_KINDS


# ---------------------------------------------------------------------------
# Main chain acceptance
# ---------------------------------------------------------------------------


def accept_android_originated_nl_into_main_chain(
    *,
    device_id: str,
    session_id: str,
    invocation_id: str,
    ingress_carrier_context: Optional[Dict[str, Any]] = None,
    is_stale: bool = False,
    is_replay: bool = False,
    is_recovery_assisted: bool = False,
    is_takeover_scenario: bool = False,
    is_conflict_present: bool = False,
    is_multi_device_concurrent: bool = False,
    is_duplicate: bool = False,
) -> AndroidOriginatedIngressResult:
    """Accept an Android-originated NL request into the V2 main chain.

    This function is the canonical entry point for Android-originated NL traffic.
    It checks that the request carries proper main-chain markers (carrier context,
    semantic authority), classifies the lineage, and returns an acceptance result.

    Parameters
    ----------
    device_id:
        The Android device that originated the request.
    session_id:
        Conversation session ID.
    invocation_id:
        Correlation ID for this invocation.
    ingress_carrier_context:
        The ``ingress_carrier_context`` dict from DesktopPresenceRuntime,
        if available. Used to verify V2 as semantic authority.
    is_stale / is_replay / is_recovery_assisted / is_takeover_scenario /
    is_conflict_present / is_multi_device_concurrent / is_duplicate:
        Scenario flags that affect lineage classification and gap detection.

    Returns
    -------
    AndroidOriginatedIngressResult
        Acceptance result with lineage, gap types, and authority source.
    """
    # Build ingress context
    ctx = AndroidOriginatedIngressContext(
        device_id=device_id,
        session_id=session_id,
        invocation_id=invocation_id,
        is_stale=is_stale,
        is_replay=is_replay,
        is_recovery_assisted=is_recovery_assisted,
        is_takeover_scenario=is_takeover_scenario,
        is_conflict_present=is_conflict_present,
        is_multi_device_concurrent=is_multi_device_concurrent,
        is_duplicate=is_duplicate,
    )

    gap_types: List[str] = []
    blocking_reason = ""

    # Check main chain acceptance (semantic authority verification)
    if ingress_carrier_context is not None:
        main_chain_accepted = is_v2_semantic_authority_path(ingress_carrier_context)
    else:
        # Without carrier context we cannot confirm main-chain; mark as gap but accept
        # (in real runtime the carrier context should always be present for NL paths).
        main_chain_accepted = False
        gap_types.append(GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN)
        blocking_reason = (
            "Android-originated NL request lacks ingress_carrier_context. "
            "Cannot confirm V2 as semantic authority. "
            f"Policy: {ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY}"
        )
        logger.warning(
            "accept_android_originated_nl_into_main_chain: "
            "device_id=%r invocation_id=%r — no ingress_carrier_context; "
            "marking as GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN",
            device_id,
            invocation_id,
        )

    ctx.is_main_chain_accepted = main_chain_accepted

    # Classify participation
    participation_cls = classify_android_participation(
        AndroidParticipationKind.android_originated_nl,
        is_stale=is_stale,
        is_replay=is_replay,
        is_recovery_assisted=is_recovery_assisted,
    )

    # Detect complex scenario gaps
    if is_stale:
        gap_types.append(GAP_ANDROID_ORIGINATED_STALE_EVIDENCE)
    if is_replay and not is_stale:
        gap_types.append(GAP_ANDROID_ORIGINATED_REPLAY_COMBINED)
    if is_recovery_assisted:
        gap_types.append(GAP_ANDROID_ORIGINATED_REPLAY_COMBINED)
    if is_takeover_scenario:
        gap_types.append(GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED)
    if is_conflict_present or is_duplicate:
        gap_types.append(GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL)
    if is_multi_device_concurrent:
        gap_types.append(GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE)

    # Classify lineage
    lineage = classify_execution_lineage(
        is_android_originated=True,
        fallback_path_used=False,  # NL-level fallback detected separately in lifecycle
        is_replay_assisted=is_replay,
        is_recovery_assisted=is_recovery_assisted,
        is_takeover_scenario=is_takeover_scenario,
        is_conflict_present=is_conflict_present or is_duplicate,
    )
    ctx.lineage = lineage

    # Determine authority source
    if main_chain_accepted:
        authority_source = V2_SEMANTIC_AUTHORITY
    else:
        authority_source = "unknown"

    # Mature closure is blocked if any gaps or non-canonical lineage
    mature_closure_blocked = len(gap_types) > 0 or not is_canonical_lineage(lineage)

    if mature_closure_blocked and not blocking_reason:
        reasons = []
        if not is_canonical_lineage(lineage):
            reasons.append(f"non-canonical lineage={lineage.value!r}")
        if gap_types:
            reasons.append(f"gap_types={gap_types}")
        blocking_reason = "; ".join(reasons)

    return AndroidOriginatedIngressResult(
        accepted=True,  # Always accept for ingress; gaps inform closure quality
        lineage=lineage,
        gap_types=gap_types,
        authority_source=authority_source,
        is_main_chain_accepted=main_chain_accepted,
        mature_closure_blocked=mature_closure_blocked,
        blocking_reason=blocking_reason,
        context=ctx,
    )


def is_android_originated_main_chain_accepted(
    ingress_result: AndroidOriginatedIngressResult,
) -> bool:
    """Return True iff the ingress result confirms main-chain acceptance."""
    return (
        ingress_result.is_main_chain_accepted
        and ingress_result.authority_source == V2_SEMANTIC_AUTHORITY
    )


# ---------------------------------------------------------------------------
# Governance context builder (for closed_loop_governance integration)
# ---------------------------------------------------------------------------


def build_android_originated_governance_context(
    *,
    device_id: str,
    execution_id: str,
    ingress_result: AndroidOriginatedIngressResult,
) -> Dict[str, Any]:
    """Build a governance context dict for a governed Android-originated execution.

    This dict is intended to be passed to the closed_loop_governance layer
    as additional context for lineage tracking and audit.

    Parameters
    ----------
    device_id:
        Target device ID for this execution.
    execution_id:
        Correlation ID for the governed execution.
    ingress_result:
        The result from :func:`accept_android_originated_nl_into_main_chain`.

    Returns
    -------
    dict
        Governance context with lineage, gap types, and authority metadata.
    """
    return {
        "execution_id": execution_id,
        "device_id": device_id,
        "android_originated": True,
        "lineage": ingress_result.lineage.value,
        "is_main_chain_accepted": ingress_result.is_main_chain_accepted,
        "authority_source": ingress_result.authority_source,
        "gap_types": list(ingress_result.gap_types),
        "mature_closure_blocked": ingress_result.mature_closure_blocked,
        "blocking_reason": ingress_result.blocking_reason,
        "ingress_context": ingress_result.context.to_dict(),
        "_sentinel": ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL,
        "_contract_version": ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION,
    }


# ---------------------------------------------------------------------------
# Module-level __all__
# ---------------------------------------------------------------------------

__all__ = [
    "ANDROID_ORIGINATED_MAIN_CHAIN_INGRESS_SENTINEL",
    "ANDROID_ORIGINATED_MAIN_CHAIN_CONTRACT_VERSION",
    "ANDROID_ORIGINATED_MUST_CARRY_LINEAGE_POLICY",
    "ANDROID_ORIGINATED_FALLBACK_BLOCKS_MATURE_CLOSURE_POLICY",
    "ANDROID_ORIGINATED_REPLAY_BLOCKS_CANONICAL_LINEAGE_POLICY",
    "GAP_ANDROID_ORIGINATED_WITHOUT_MAIN_CHAIN",
    "GAP_ANDROID_ORIGINATED_FALLBACK_COMBINED",
    "GAP_ANDROID_ORIGINATED_REPLAY_COMBINED",
    "GAP_ANDROID_ORIGINATED_TAKEOVER_COMBINED",
    "GAP_ANDROID_ORIGINATED_CONFLICT_PARTIAL",
    "GAP_ANDROID_ORIGINATED_DUPLICATE",
    "GAP_ANDROID_ORIGINATED_MULTI_DEVICE_RACE",
    "GAP_ANDROID_ORIGINATED_STALE_EVIDENCE",
    "ExecutionLineageKind",
    "AndroidOriginatedIngressContext",
    "AndroidOriginatedIngressResult",
    "classify_execution_lineage",
    "is_canonical_lineage",
    "accept_android_originated_nl_into_main_chain",
    "is_android_originated_main_chain_accepted",
    "build_android_originated_governance_context",
]
