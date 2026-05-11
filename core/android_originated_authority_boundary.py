"""core/android_originated_authority_boundary.py
=================================================
PR-Final: Android-Originated Authority Boundary Model
======================================================

背景
----
双仓系统中，Android 端不是纯执行壳，而是中心 authority 下的主动参与节点。
但 Android-originated 流量要成为系统能力，必须被 V2 中心主链统一接纳，而非形成旁挂路径。

本模块代码化以下 authority 边界模型：

1. **center_authority** — V2 中心侧，对所有完成真相、调度、编排持有唯一权威
2. **android_originated_participation** — Android 作为主动参与方，通过跨设备 NL 发起请求
3. **takeover_participation** — Android 接受/拒绝 takeover 的参与
4. **reconciliation_participation** — Android 信号可参与 reconciliation（受限）
5. **authority_adjacent_participation** — Android 可观察/建议，但不能影响决策

每类参与类型有明确的信号权限等级（``AndroidSignalPermissionLevel``）：

- ``observation_only`` — 仅可记录为证据/诊断信号，不影响任何决策
- ``suggestion_only`` — 可提出建议，但中心可完全忽略
- ``reconciliation_eligible`` — 经审核后可进入 reconciliation 流程
- ``takeover_eligible`` — 专用于 takeover accept/reject，受 authority 边界约束
- ``main_chain_carrier`` — Android 作为 NL carrier，主链语义权威仍是 V2 OpenClawd

关键约束
--------
- Android-originated NL 请求必须经由 V2 DesktopPresenceRuntime → OpenClawd 主链，
  而不是绕过主链直接进入中心决策层。
- Android 发起的任何信号，不能越过 V2 center_authority 直接修改闭环结论。
- takeover 参与仅在明确授权边界内合法。
- reconciliation 参与需要证据质量达到最低门槛。

机器可验证契约
--------------
::

    from core.android_originated_authority_boundary import (
        ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL,
        ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION,
        AndroidParticipationKind,
        AndroidSignalPermissionLevel,
        classify_android_participation,
        get_android_participation_permission,
        is_android_main_chain_eligible,
        ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY,
        ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY,
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional

# ---------------------------------------------------------------------------
# Contract sentinels & version
# ---------------------------------------------------------------------------

ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL: str = (
    "ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL::PR_FINAL::present "
    "core.android_originated_authority_boundary is the canonical authority "
    "boundary model for Android participation in the V2 center-distributed system. "
    "V2 is the center authority. Android is an active participant node, not a pure "
    "execution shell. Android-originated NL traffic MUST enter via the V2 main chain. "
    "All tests MUST reference this sentinel to confirm the boundary model is loaded."
)

ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION: str = "final.0.0"

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY: str = (
    "POLICY::ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_V1: "
    "Android-originated signals and participation MUST NOT override or bypass "
    "V2 center authority. V2 owns: completion truth, continuity legality truth, "
    "dispatch readiness truth, orchestration truth. Android may contribute "
    "evidence, signals, and proposals, but final authority always resides in V2. "
    "Any Android signal that attempts to directly modify center authority conclusions "
    "without going through reconciliation or main chain is a policy violation."
)

ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY: str = (
    "POLICY::ANDROID_NL_MUST_ENTER_MAIN_CHAIN_V1: "
    "Android-originated natural language requests (cross-device NL path) MUST "
    "enter the V2 main chain: DesktopPresenceRuntime.handle_request → OpenClawd "
    "+ AgentKernel + MultiLLMRouter. Android is the NL carrier; V2 OpenClawd is "
    "the sole LLM semantic authority. Android-originated NL MUST NOT create a "
    "parallel governance chain. It MUST carry origin/lineage/authority identifiers "
    "that allow the main chain to trace provenance."
)

ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_POLICY: str = (
    "POLICY::ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_V1: "
    "Android signals classified as reconciliation_eligible MUST have proof input "
    "class 'complete' (not stale, conflicting, malformed, unknown, downgraded, "
    "partial, or missing). Only complete evidence may enter the reconciliation "
    "flow. Degraded/stale evidence is classified as observation_only or "
    "suggestion_only and cannot influence reconciliation outcomes."
)

ANDROID_TAKEOVER_WITHIN_AUTHORITY_BOUNDARY_POLICY: str = (
    "POLICY::ANDROID_TAKEOVER_WITHIN_AUTHORITY_BOUNDARY_V1: "
    "Takeover participation by Android (accept/reject) is bounded by the "
    "takeover authority chain. Android CANNOT initiate takeover unilaterally. "
    "Takeover must be dispatched by V2 center. Android's accept/reject "
    "participation feeds back to the center via the lifecycle coordinator. "
    "Android does not own the takeover decision; V2 retains final authority."
)

# ---------------------------------------------------------------------------
# Participation kind enum
# ---------------------------------------------------------------------------


class AndroidParticipationKind(str, Enum):
    """Canonical participation types for Android in the V2 center-distributed system.

    Values
    ------
    center_authority
        V2 center-side authority. Android cannot hold this role.
        Included here for completeness in the boundary model.

    android_originated_nl
        Android acts as NL carrier for cross-device natural language requests.
        The NL goal is structured by GoalNormalizer → AIP v3 goal_execution →
        DesktopPresenceRuntime → V2 OpenClawd (semantic authority).
        Android is the transport/carrier, NOT the semantic authority.

    android_originated_signal
        Android emits runtime signals (execution progress, state updates,
        diagnostics) that flow into the center's evidence pipeline. Signals
        may be observation-only or reconciliation-eligible depending on quality.

    takeover_participation
        Android responds to a V2-dispatched takeover request.
        Android CANNOT initiate takeover independently.

    reconciliation_participation
        Android evidence/signals participate in the reconciliation flow.
        Requires minimum proof quality (complete, not stale/partial/conflicting).

    authority_adjacent_participation
        Android provides observations and advisory signals that may inform
        center decisions but cannot override V2 authority. Includes diagnostics,
        mesh evidence, recovery hints, and local state reports.
    """

    center_authority = "center_authority"
    android_originated_nl = "android_originated_nl"
    android_originated_signal = "android_originated_signal"
    takeover_participation = "takeover_participation"
    reconciliation_participation = "reconciliation_participation"
    authority_adjacent_participation = "authority_adjacent_participation"


# ---------------------------------------------------------------------------
# Signal permission level enum
# ---------------------------------------------------------------------------


class AndroidSignalPermissionLevel(str, Enum):
    """Permission level for Android-originated signals in the governance chain.

    Values
    ------
    observation_only
        Signal may only be recorded as diagnostics/audit evidence.
        Cannot influence any governance decision or reconciliation.
        Used for stale, partial, unknown, or degraded evidence.

    suggestion_only
        Signal may be recorded as a proposal or advisory input.
        Center governance may consult but is NOT required to act.
        Used for advisory hints, recovery suggestions, mesh advisory.

    reconciliation_eligible
        Signal has sufficient quality to enter the reconciliation flow.
        Requires complete proof input (not stale/partial/conflicting/missing).
        Subject to center-lifecycle authority override (I-03).

    takeover_eligible
        Signal is an accept/reject response to a V2-dispatched takeover.
        Bounded by the takeover authority chain; does not override center truth.

    main_chain_carrier
        Android-originated NL that MUST enter the V2 main chain.
        Android is the carrier; V2 OpenClawd is the semantic authority.
        This is the highest-priority Android participation type.
    """

    observation_only = "observation_only"
    suggestion_only = "suggestion_only"
    reconciliation_eligible = "reconciliation_eligible"
    takeover_eligible = "takeover_eligible"
    main_chain_carrier = "main_chain_carrier"


# ---------------------------------------------------------------------------
# Participation classification result
# ---------------------------------------------------------------------------


@dataclass
class AndroidParticipationClassification:
    """Result of classifying an Android-originated signal.

    Attributes
    ----------
    participation_kind
        The :class:`AndroidParticipationKind` of this signal.
    permission_level
        The :class:`AndroidSignalPermissionLevel` for this signal.
    can_enter_reconciliation
        True iff this signal may enter the reconciliation flow.
    can_override_center_authority
        Always False — Android signals MUST NOT override center authority.
    requires_main_chain_ingress
        True iff this signal must pass through the V2 main chain before
        influencing any center governance decision.
    reason
        Human-readable classification reason.
    policy
        Applicable policy sentinel.
    """

    participation_kind: AndroidParticipationKind
    permission_level: AndroidSignalPermissionLevel
    can_enter_reconciliation: bool
    can_override_center_authority: bool  # always False
    requires_main_chain_ingress: bool
    reason: str
    policy: str = ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY

    def to_dict(self) -> Dict[str, Any]:
        return {
            "participation_kind": self.participation_kind.value,
            "permission_level": self.permission_level.value,
            "can_enter_reconciliation": self.can_enter_reconciliation,
            "can_override_center_authority": self.can_override_center_authority,
            "requires_main_chain_ingress": self.requires_main_chain_ingress,
            "reason": self.reason,
            "policy": self.policy,
            "_sentinel": ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL,
            "_contract_version": ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION,
        }


# ---------------------------------------------------------------------------
# Authority boundary table
# ---------------------------------------------------------------------------

# Maps (participation_kind, signal_context) → permission_level + constraints.
# The table is the authoritative source for permission decisions.

_PERMISSION_TABLE: Dict[AndroidParticipationKind, AndroidSignalPermissionLevel] = {
    AndroidParticipationKind.center_authority: AndroidSignalPermissionLevel.main_chain_carrier,
    AndroidParticipationKind.android_originated_nl: AndroidSignalPermissionLevel.main_chain_carrier,
    AndroidParticipationKind.android_originated_signal: AndroidSignalPermissionLevel.reconciliation_eligible,
    AndroidParticipationKind.takeover_participation: AndroidSignalPermissionLevel.takeover_eligible,
    AndroidParticipationKind.reconciliation_participation: AndroidSignalPermissionLevel.reconciliation_eligible,
    AndroidParticipationKind.authority_adjacent_participation: AndroidSignalPermissionLevel.observation_only,
}

# Participation kinds that may enter reconciliation (subject to proof quality check).
_RECONCILIATION_ELIGIBLE_KINDS: FrozenSet[AndroidParticipationKind] = frozenset(
    {
        AndroidParticipationKind.android_originated_signal,
        AndroidParticipationKind.reconciliation_participation,
    }
)

# Participation kinds that require explicit main-chain ingress.
_REQUIRES_MAIN_CHAIN_KINDS: FrozenSet[AndroidParticipationKind] = frozenset(
    {
        AndroidParticipationKind.android_originated_nl,
    }
)

# Proof input classes that are allowed to enter reconciliation.
# Any other class downgrades to observation_only.
_RECONCILIATION_PASSING_PROOF_CLASSES: FrozenSet[str] = frozenset({"complete"})


# ---------------------------------------------------------------------------
# Public classification API
# ---------------------------------------------------------------------------


def classify_android_participation(
    participation_kind: AndroidParticipationKind,
    *,
    proof_input_class: str = "complete",
    is_stale: bool = False,
    is_replay: bool = False,
    is_recovery_assisted: bool = False,
) -> AndroidParticipationClassification:
    """Classify an Android-originated signal and return its authority boundary.

    Parameters
    ----------
    participation_kind:
        The type of Android participation for this signal.
    proof_input_class:
        Proof input quality class (e.g. ``"complete"``, ``"stale"``,
        ``"partial"``, ``"conflicting"``).  Only ``"complete"`` is
        reconciliation-passing.
    is_stale:
        True if the signal is known to be stale (overrides proof_input_class).
    is_replay:
        True if the signal came from a replay queue rather than real-time Android.
    is_recovery_assisted:
        True if the signal was generated by a recovery path (degraded evidence).

    Returns
    -------
    AndroidParticipationClassification
        The typed boundary classification for this signal.
    """
    base_permission = _PERMISSION_TABLE.get(
        participation_kind, AndroidSignalPermissionLevel.observation_only
    )

    # Stale/replay/recovery-assisted evidence is always downgraded to observation_only
    # or suggestion_only — it cannot enter reconciliation.
    evidence_degraded = is_stale or is_replay or is_recovery_assisted
    proof_non_passing = proof_input_class not in _RECONCILIATION_PASSING_PROOF_CLASSES

    can_enter_reconciliation = False
    requires_main_chain = participation_kind in _REQUIRES_MAIN_CHAIN_KINDS

    if participation_kind == AndroidParticipationKind.android_originated_nl:
        # NL signals always require main chain; permission is main_chain_carrier.
        effective_permission = AndroidSignalPermissionLevel.main_chain_carrier
        reason = (
            "Android-originated NL requires V2 main chain ingress. "
            "Android is the NL carrier; V2 OpenClawd is the semantic authority."
        )
        policy = ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY

    elif participation_kind == AndroidParticipationKind.takeover_participation:
        effective_permission = AndroidSignalPermissionLevel.takeover_eligible
        reason = (
            "Takeover participation: Android respond to V2-dispatched takeover. "
            "Bounded by takeover authority chain. Center retains final authority."
        )
        policy = ANDROID_TAKEOVER_WITHIN_AUTHORITY_BOUNDARY_POLICY

    elif participation_kind in _RECONCILIATION_ELIGIBLE_KINDS:
        if evidence_degraded or proof_non_passing:
            # Degrade to suggestion_only for stale/replay/recovery/non-complete evidence.
            effective_permission = AndroidSignalPermissionLevel.suggestion_only
            degradation_reasons = []
            if is_stale:
                degradation_reasons.append("stale evidence")
            if is_replay:
                degradation_reasons.append("replay evidence")
            if is_recovery_assisted:
                degradation_reasons.append("recovery-assisted evidence")
            if proof_non_passing:
                degradation_reasons.append(
                    f"proof_input_class={proof_input_class!r} (non-passing)"
                )
            reason = (
                f"Downgraded from reconciliation_eligible to suggestion_only: "
                + ", ".join(degradation_reasons)
                + ". Only 'complete' proof input may enter reconciliation."
            )
            policy = ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_POLICY
        else:
            effective_permission = AndroidSignalPermissionLevel.reconciliation_eligible
            can_enter_reconciliation = True
            reason = (
                "Android signal is reconciliation_eligible: complete proof input, "
                "real-time (not stale/replay/recovery-assisted)."
            )
            policy = ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_POLICY

    elif participation_kind == AndroidParticipationKind.authority_adjacent_participation:
        effective_permission = AndroidSignalPermissionLevel.observation_only
        reason = (
            "Authority-adjacent participation: observation and advisory only. "
            "Signals may be recorded as evidence but cannot influence decisions."
        )
        policy = ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY

    else:
        # Default / unknown: fall back to observation_only.
        effective_permission = AndroidSignalPermissionLevel.observation_only
        reason = (
            f"Unrecognized participation_kind={participation_kind!r}; "
            "defaulting to observation_only per authority boundary policy."
        )
        policy = ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY

    return AndroidParticipationClassification(
        participation_kind=participation_kind,
        permission_level=effective_permission,
        can_enter_reconciliation=can_enter_reconciliation,
        can_override_center_authority=False,  # invariant: always False
        requires_main_chain_ingress=requires_main_chain,
        reason=reason,
        policy=policy,
    )


def get_android_participation_permission(
    participation_kind: AndroidParticipationKind,
) -> AndroidSignalPermissionLevel:
    """Return the base permission level for *participation_kind*.

    This is the table-lookup variant without evidence quality adjustments.
    Use :func:`classify_android_participation` for context-aware classification.
    """
    return _PERMISSION_TABLE.get(
        participation_kind, AndroidSignalPermissionLevel.observation_only
    )


def is_android_main_chain_eligible(
    participation_kind: AndroidParticipationKind,
) -> bool:
    """Return True iff this participation type MUST enter the V2 main chain.

    Only :attr:`AndroidParticipationKind.android_originated_nl` requires
    main-chain ingress. All other participation types route through their
    own appropriate ingress paths.
    """
    return participation_kind in _REQUIRES_MAIN_CHAIN_KINDS


def assert_android_cannot_override_center(
    classification: AndroidParticipationClassification,
    context: str = "",
) -> None:
    """Assert that a classification never grants center authority override.

    This is a non-negotiable invariant. Any classification that has
    can_override_center_authority=True is a system error.

    Raises
    ------
    AssertionError
        If can_override_center_authority is True.
    """
    prefix = f"[{context}] " if context else ""
    assert classification.can_override_center_authority is False, (
        f"{prefix}INVARIANT VIOLATION: Android classification has "
        f"can_override_center_authority=True. This is never permitted. "
        f"participation_kind={classification.participation_kind!r}, "
        f"permission_level={classification.permission_level!r}. "
        f"Policy: {ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY}"
    )


# ---------------------------------------------------------------------------
# Module-level __all__
# ---------------------------------------------------------------------------

__all__ = [
    "ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_SENTINEL",
    "ANDROID_ORIGINATED_AUTHORITY_BOUNDARY_CONTRACT_VERSION",
    "ANDROID_CANNOT_OVERRIDE_CENTER_AUTHORITY_POLICY",
    "ANDROID_NL_MUST_ENTER_MAIN_CHAIN_POLICY",
    "ANDROID_RECONCILIATION_REQUIRES_MINIMUM_EVIDENCE_POLICY",
    "ANDROID_TAKEOVER_WITHIN_AUTHORITY_BOUNDARY_POLICY",
    "AndroidParticipationKind",
    "AndroidSignalPermissionLevel",
    "AndroidParticipationClassification",
    "classify_android_participation",
    "get_android_participation_permission",
    "is_android_main_chain_eligible",
    "assert_android_cannot_override_center",
]
