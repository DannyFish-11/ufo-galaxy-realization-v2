"""tests/test_pr24_post533_dispatch_selection_truth_consolidation.py
======================================================================
Tests for PR package 24 (post-533 dual-repo runtime unification master plan,
MAIN repo side): Dispatch Selection Truth Consolidation.

This test suite verifies that:

1. All PR-24 policy/authority sentinels are present in the orchestrator module.
2. ``select_dispatch_target()`` uses consolidated truth inputs (readiness,
   participation, registry, reuse) instead of ad-hoc first-active behaviour.
3. A candidate that fails the readiness gate is rejected with a stable reason.
4. A candidate that fails the participation gate is rejected with a stable reason.
5. An active registry session with good readiness + participation is selected.
6. Reuse eligibility boosts the candidate score (preference) but does not gate.
7. Multi-target situations select the best candidate by score (not just first).
8. When no registry-active candidates pass the gates, selection falls back
   gracefully with a stable fallback path (mesh or None).
9. Explicit ``target_device_id`` bypasses consolidated selection (fast path).
10. The projection sentinel is importable and is not UNAVAILABLE.
11. ``core.runtime`` re-exports all PR-24 sentinel symbols.

Coverage groups
---------------
A  — Orchestrator module: all PR-24 sentinels present.
B  — Projection: PR-24 sentinel is importable and not UNAVAILABLE.
C  — core.runtime re-exports all PR-24 sentinels.
D  — Explicit target_device_id bypasses consolidated selection.
E  — No registry sessions → no target selected (registry unavailable path).
F  — Readiness gate: not_registered → rejected.
G  — Readiness gate: not_routable → rejected.
H  — Participation gate: not_orchestration_eligible → rejected.
I  — Readiness + participation pass → candidate is selected.
J  — Reuse eligibility increases score but does not block selection.
K  — Multi-target: candidate with reuse wins over equally eligible candidate.
L  — Multi-target: best score wins across multiple registry candidates.
M  — All candidates rejected → no target (fallback to None or mesh).
N  — Mesh fallback path still works when registry path yields nothing.
O  — Selection reasons are stable strings (not None, not empty).
P  — build_source_dispatch_plan passes registry/readiness/participation/reuse
     through to select_dispatch_target.
Q  — _score_candidate: readiness unavailable → score=0, stable reason.
R  — _score_candidate: participation unavailable → score=0, stable reason.
S  — _score_candidate: all pass, reuse=True → score > baseline without reuse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Module availability guards
# ---------------------------------------------------------------------------

try:
    from core.runtime.source_dispatch_orchestrator import (
        DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL,
        SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY,
        SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY,
        SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY,
        SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY,
        SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY,
        _select_target_from_candidates,
        _score_candidate,
        select_dispatch_target,
        build_source_dispatch_plan,
    )

    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from core.attached_runtime_session_registry import (
        AttachedSessionRegistry,
        RegistryEntryState,
        register_session,
        detach_session,
        invalidate_session,
        InvalidationReason,
    )

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

try:
    from core.routes.projection import DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24

    _PROJECTION_AVAILABLE = True
except ImportError:
    _PROJECTION_AVAILABLE = False

try:
    import core.runtime as _core_runtime

    _CORE_RUNTIME_AVAILABLE = True
except ImportError:
    _CORE_RUNTIME_AVAILABLE = False

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class _FakeReadiness:
    """Minimal DeviceReadinessSummary-like object for test isolation."""

    device_id: str
    registered: bool = True
    online: bool = True
    connected: bool = True
    routable: bool = True
    capability_ready: bool = True
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "registered": self.registered,
            "online": self.online,
            "connected": self.connected,
            "routable": self.routable,
            "capability_ready": self.capability_ready,
        }


@dataclass
class _FakeParticipation:
    """Minimal ParticipationSummary-like object for test isolation."""

    device_id: str
    orchestration_eligible: bool = True
    registered: bool = True
    routable: bool = True
    assessed: bool = True
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "orchestration_eligible": self.orchestration_eligible,
            "registered": self.registered,
            "routable": self.routable,
            "assessed": self.assessed,
        }


def _make_registry_with_active_session(
    session_id: str,
    device_id: str,
) -> "AttachedSessionRegistry":
    """Return a fresh registry with one active session."""
    reg = AttachedSessionRegistry()
    register_session(session_id=session_id, device_id=device_id, registry=reg)
    return reg


def _make_registry_with_two_active_sessions(
    session_id_a: str,
    device_id_a: str,
    session_id_b: str,
    device_id_b: str,
) -> "AttachedSessionRegistry":
    """Return a fresh registry with two active sessions on different devices."""
    reg = AttachedSessionRegistry()
    register_session(session_id=session_id_a, device_id=device_id_a, registry=reg)
    register_session(session_id=session_id_b, device_id=device_id_b, registry=reg)
    return reg


# ===========================================================================
# Group A — Orchestrator module: all PR-24 sentinels present
# ===========================================================================


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable")
class TestPR24SentinelsPresent:
    def test_main_sentinel_is_string(self):
        assert isinstance(DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL, str)
        assert len(DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL) > 0

    def test_readiness_policy_is_string(self):
        assert isinstance(SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY, str)
        assert "READINESS" in SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY

    def test_participation_policy_is_string(self):
        assert isinstance(SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY, str)
        assert "PARTICIPATION" in SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY

    def test_registry_policy_is_string(self):
        assert isinstance(SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY, str)
        assert "REGISTRY" in SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY

    def test_reuse_policy_is_string(self):
        assert isinstance(SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY, str)
        assert "REUSE" in SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY

    def test_fallback_policy_is_string(self):
        assert isinstance(SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY, str)
        assert "FALLBACK" in SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY

    def test_main_sentinel_contains_pr24(self):
        assert "PR24" in DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL

    def test_sentinel_mentions_truth_inputs(self):
        sentinel = DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL
        assert "readiness" in sentinel.lower() or "registry" in sentinel.lower()


# ===========================================================================
# Group B — Projection sentinel importable and not UNAVAILABLE
# ===========================================================================


@pytest.mark.skipif(not _PROJECTION_AVAILABLE, reason="projection module unavailable")
class TestPR24ProjectionSentinel:
    def test_projection_sentinel_is_string(self):
        assert isinstance(DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24, str)

    def test_projection_sentinel_not_unavailable(self):
        assert "UNAVAILABLE" not in DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24

    def test_projection_sentinel_contains_pr24(self):
        assert "PR24" in DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24

    def test_projection_sentinel_mentions_readiness_or_registry(self):
        s = DISPATCH_SELECTION_TRUTH_CONSOLIDATED_ALIGNED_PR24.lower()
        assert "readiness" in s or "registry" in s


# ===========================================================================
# Group C — core.runtime re-exports all PR-24 sentinels
# ===========================================================================


@pytest.mark.skipif(not _CORE_RUNTIME_AVAILABLE, reason="core.runtime unavailable")
class TestCoreRuntimePR24Exports:
    def test_main_sentinel_exported(self):
        assert hasattr(_core_runtime, "DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL")

    def test_readiness_policy_exported(self):
        assert hasattr(_core_runtime, "SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY")

    def test_participation_policy_exported(self):
        assert hasattr(_core_runtime, "SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY")

    def test_registry_policy_exported(self):
        assert hasattr(_core_runtime, "SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY")

    def test_reuse_policy_exported(self):
        assert hasattr(_core_runtime, "SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY")

    def test_fallback_policy_exported(self):
        assert hasattr(_core_runtime, "SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY")

    def test_exported_values_are_strings(self):
        for name in [
            "DISPATCH_SELECTION_TRUTH_CONSOLIDATED_PR24_SENTINEL",
            "SELECTION_READINESS_IS_REQUIRED_TRUTH_PR24_POLICY",
            "SELECTION_PARTICIPATION_IS_REQUIRED_TRUTH_PR24_POLICY",
            "SELECTION_REGISTRY_IS_CANONICAL_GATE_PR24_POLICY",
            "SELECTION_REUSE_CONTRIBUTES_PREFERENCE_PR24_POLICY",
            "SELECTION_FALLBACK_IS_STABLE_AND_EXPLAINABLE_PR24_POLICY",
        ]:
            val = getattr(_core_runtime, name)
            assert isinstance(val, str), f"{name} should be str"
            assert len(val) > 0, f"{name} should not be empty"


# ===========================================================================
# Group D — Explicit target_device_id bypasses consolidated selection
# ===========================================================================


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator module unavailable")
class TestExplicitTargetBypassesConsolidation:
    def test_explicit_target_returns_immediately(self):
        result = select_dispatch_target(
            target_device_id="explicit-device-1",
            target_runtime_id="runtime-1",
        )
        assert result is not None
        assert result.target_device_id == "explicit-device-1"
        assert result.selection_reason == "explicit_target_device_id"

    def test_explicit_target_ignores_empty_registry(self):
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry unavailable")
        reg = AttachedSessionRegistry()
        result = select_dispatch_target(
            target_device_id="explicit-dev",
            registry=reg,
        )
        assert result is not None
        assert result.target_device_id == "explicit-dev"
        assert result.selection_reason == "explicit_target_device_id"

    def test_explicit_target_reason_is_stable(self):
        r1 = select_dispatch_target(target_device_id="dev-a")
        r2 = select_dispatch_target(target_device_id="dev-a")
        assert r1.selection_reason == r2.selection_reason == "explicit_target_device_id"


# ===========================================================================
# Group E — No active registry sessions → no target selected
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestNoActiveRegistrySessions:
    def test_empty_registry_returns_none(self):
        reg = AttachedSessionRegistry()
        result = _select_target_from_candidates(registry=reg)
        assert result is None

    def test_no_registry_arg_and_no_mesh_returns_none(self):
        # Pass an empty registry and no mesh → should get None
        reg = AttachedSessionRegistry()
        result = select_dispatch_target(registry=reg)
        assert result is None

    def test_detached_session_not_selected(self):
        reg = AttachedSessionRegistry()
        entry = register_session(session_id="sess-det", device_id="dev-det", registry=reg)
        detach_session(entry, registry=reg)
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-det": _FakeReadiness("dev-det")},
            participation_inputs={"dev-det": _FakeParticipation("dev-det")},
        )
        assert result is None


# ===========================================================================
# Group F — Readiness gate: not_registered → rejected
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestReadinessGateNotRegistered:
    def test_not_registered_rejected(self):
        reg = _make_registry_with_active_session("sess-f1", "dev-f1")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-f1": _FakeReadiness("dev-f1", registered=False, routable=True)
            },
            participation_inputs={"dev-f1": _FakeParticipation("dev-f1")},
        )
        assert result is None

    def test_not_registered_and_not_routable_rejected(self):
        reg = _make_registry_with_active_session("sess-f2", "dev-f2")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-f2": _FakeReadiness("dev-f2", registered=False, routable=False)
            },
            participation_inputs={"dev-f2": _FakeParticipation("dev-f2")},
        )
        assert result is None

    def test_score_candidate_not_registered(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d", registered=False),
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        assert score == 0
        assert "not_registered" in reason


# ===========================================================================
# Group G — Readiness gate: not_routable → rejected
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestReadinessGateNotRoutable:
    def test_not_routable_rejected(self):
        reg = _make_registry_with_active_session("sess-g1", "dev-g1")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-g1": _FakeReadiness("dev-g1", registered=True, routable=False)
            },
            participation_inputs={"dev-g1": _FakeParticipation("dev-g1")},
        )
        assert result is None

    def test_score_candidate_not_routable(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d", registered=True, routable=False),
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        assert score == 0
        assert "not_routable" in reason


# ===========================================================================
# Group H — Participation gate: not_orchestration_eligible → rejected
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestParticipationGateNotEligible:
    def test_not_orchestration_eligible_rejected(self):
        reg = _make_registry_with_active_session("sess-h1", "dev-h1")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-h1": _FakeReadiness("dev-h1")},
            participation_inputs={
                "dev-h1": _FakeParticipation("dev-h1", orchestration_eligible=False)
            },
        )
        assert result is None

    def test_score_candidate_not_orchestration_eligible(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d", orchestration_eligible=False),
            reuse_eligible=False,
        )
        assert score == 0
        assert "not_orchestration_eligible" in reason

    def test_participation_unavailable_rejected(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=None,
            reuse_eligible=False,
        )
        assert score == 0
        assert "unavailable" in reason


# ===========================================================================
# Group I — Readiness + participation pass → candidate is selected
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestCandidateIsSelected:
    def test_active_session_with_good_readiness_participation_is_selected(self):
        reg = _make_registry_with_active_session("sess-i1", "dev-i1")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-i1": _FakeReadiness("dev-i1")},
            participation_inputs={"dev-i1": _FakeParticipation("dev-i1")},
            reuse_inputs={"dev-i1": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-i1"

    def test_selected_reason_is_stable(self):
        reg = _make_registry_with_active_session("sess-i2", "dev-i2")
        r1 = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-i2": _FakeReadiness("dev-i2")},
            participation_inputs={"dev-i2": _FakeParticipation("dev-i2")},
            reuse_inputs={"dev-i2": False},
        )
        r2 = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-i2": _FakeReadiness("dev-i2")},
            participation_inputs={"dev-i2": _FakeParticipation("dev-i2")},
            reuse_inputs={"dev-i2": False},
        )
        assert r1 is not None
        assert r2 is not None
        assert r1.selection_reason == r2.selection_reason

    def test_selected_reason_contains_registry_and_readiness_and_participation(self):
        reg = _make_registry_with_active_session("sess-i3", "dev-i3")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-i3": _FakeReadiness("dev-i3")},
            participation_inputs={"dev-i3": _FakeParticipation("dev-i3")},
            reuse_inputs={"dev-i3": False},
        )
        assert result is not None
        reason = result.selection_reason or ""
        assert "registry" in reason
        assert "readiness" in reason
        assert "participation" in reason

    def test_selected_reason_not_empty(self):
        reg = _make_registry_with_active_session("sess-i4", "dev-i4")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-i4": _FakeReadiness("dev-i4")},
            participation_inputs={"dev-i4": _FakeParticipation("dev-i4")},
            reuse_inputs={"dev-i4": False},
        )
        assert result is not None
        assert result.selection_reason
        assert len(result.selection_reason) > 0

    def test_selected_via_select_dispatch_target_function(self):
        reg = _make_registry_with_active_session("sess-i5", "dev-i5")
        result = select_dispatch_target(
            registry=reg,
            readiness_inputs={"dev-i5": _FakeReadiness("dev-i5")},
            participation_inputs={"dev-i5": _FakeParticipation("dev-i5")},
            reuse_inputs={"dev-i5": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-i5"


# ===========================================================================
# Group J — Reuse eligibility increases score but does not block selection
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestReuseContributesToScore:
    def test_reuse_eligible_gives_higher_score(self):
        score_no_reuse, _ = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        score_reuse, _ = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=True,
        )
        assert score_reuse > score_no_reuse

    def test_candidate_selected_even_without_reuse(self):
        reg = _make_registry_with_active_session("sess-j1", "dev-j1")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-j1": _FakeReadiness("dev-j1")},
            participation_inputs={"dev-j1": _FakeParticipation("dev-j1")},
            reuse_inputs={"dev-j1": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-j1"

    def test_reuse_true_reflected_in_selection_reason(self):
        reg = _make_registry_with_active_session("sess-j2", "dev-j2")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-j2": _FakeReadiness("dev-j2")},
            participation_inputs={"dev-j2": _FakeParticipation("dev-j2")},
            reuse_inputs={"dev-j2": True},
        )
        assert result is not None
        assert "reuse_eligible" in (result.selection_reason or "")

    def test_reuse_false_not_in_selection_reason(self):
        reg = _make_registry_with_active_session("sess-j3", "dev-j3")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-j3": _FakeReadiness("dev-j3")},
            participation_inputs={"dev-j3": _FakeParticipation("dev-j3")},
            reuse_inputs={"dev-j3": False},
        )
        assert result is not None
        assert "reuse_eligible" not in (result.selection_reason or "")


# ===========================================================================
# Group K — Multi-target: candidate with reuse wins over equally-healthy one
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestMultiTargetReusePreference:
    def test_reuse_wins_over_no_reuse(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-k1a", "dev-k1a",
            "sess-k1b", "dev-k1b",
        )
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-k1a": _FakeReadiness("dev-k1a"),
                "dev-k1b": _FakeReadiness("dev-k1b"),
            },
            participation_inputs={
                "dev-k1a": _FakeParticipation("dev-k1a"),
                "dev-k1b": _FakeParticipation("dev-k1b"),
            },
            reuse_inputs={"dev-k1a": False, "dev-k1b": True},
        )
        assert result is not None
        # dev-k1b has reuse=True so should win
        assert result.target_device_id == "dev-k1b"

    def test_selection_is_deterministic(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-k2a", "dev-k2a",
            "sess-k2b", "dev-k2b",
        )
        r1 = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-k2a": _FakeReadiness("dev-k2a"),
                "dev-k2b": _FakeReadiness("dev-k2b"),
            },
            participation_inputs={
                "dev-k2a": _FakeParticipation("dev-k2a"),
                "dev-k2b": _FakeParticipation("dev-k2b"),
            },
            reuse_inputs={"dev-k2a": False, "dev-k2b": True},
        )
        r2 = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-k2a": _FakeReadiness("dev-k2a"),
                "dev-k2b": _FakeReadiness("dev-k2b"),
            },
            participation_inputs={
                "dev-k2a": _FakeParticipation("dev-k2a"),
                "dev-k2b": _FakeParticipation("dev-k2b"),
            },
            reuse_inputs={"dev-k2a": False, "dev-k2b": True},
        )
        assert r1 is not None
        assert r2 is not None
        assert r1.target_device_id == r2.target_device_id


# ===========================================================================
# Group L — Multi-target: best score wins across multiple registry candidates
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestMultiTargetBestScoreWins:
    def test_one_rejected_one_selected(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-l1a", "dev-l1a",
            "sess-l1b", "dev-l1b",
        )
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-l1a": _FakeReadiness("dev-l1a", registered=False),  # rejected
                "dev-l1b": _FakeReadiness("dev-l1b"),  # passes
            },
            participation_inputs={
                "dev-l1a": _FakeParticipation("dev-l1a"),
                "dev-l1b": _FakeParticipation("dev-l1b"),
            },
            reuse_inputs={"dev-l1a": False, "dev-l1b": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-l1b"

    def test_first_device_good_second_not_routable(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-l2a", "dev-l2a",
            "sess-l2b", "dev-l2b",
        )
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-l2a": _FakeReadiness("dev-l2a"),
                "dev-l2b": _FakeReadiness("dev-l2b", routable=False),  # rejected
            },
            participation_inputs={
                "dev-l2a": _FakeParticipation("dev-l2a"),
                "dev-l2b": _FakeParticipation("dev-l2b"),
            },
            reuse_inputs={"dev-l2a": False, "dev-l2b": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-l2a"

    def test_both_pass_reuse_decides_winner(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-l3a", "dev-l3a",
            "sess-l3b", "dev-l3b",
        )
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-l3a": _FakeReadiness("dev-l3a"),
                "dev-l3b": _FakeReadiness("dev-l3b"),
            },
            participation_inputs={
                "dev-l3a": _FakeParticipation("dev-l3a"),
                "dev-l3b": _FakeParticipation("dev-l3b"),
            },
            reuse_inputs={"dev-l3a": True, "dev-l3b": False},
        )
        assert result is not None
        assert result.target_device_id == "dev-l3a"


# ===========================================================================
# Group M — All candidates rejected → no target (graceful None)
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestAllCandidatesRejected:
    def test_all_not_routable_returns_none(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-m1a", "dev-m1a",
            "sess-m1b", "dev-m1b",
        )
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-m1a": _FakeReadiness("dev-m1a", routable=False),
                "dev-m1b": _FakeReadiness("dev-m1b", routable=False),
            },
            participation_inputs={
                "dev-m1a": _FakeParticipation("dev-m1a"),
                "dev-m1b": _FakeParticipation("dev-m1b"),
            },
        )
        assert result is None

    def test_all_not_eligible_returns_none(self):
        reg = _make_registry_with_two_active_sessions(
            "sess-m2a", "dev-m2a",
            "sess-m2b", "dev-m2b",
        )
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={
                "dev-m2a": _FakeReadiness("dev-m2a"),
                "dev-m2b": _FakeReadiness("dev-m2b"),
            },
            participation_inputs={
                "dev-m2a": _FakeParticipation("dev-m2a", orchestration_eligible=False),
                "dev-m2b": _FakeParticipation("dev-m2b", orchestration_eligible=False),
            },
        )
        assert result is None


# ===========================================================================
# Group N — Mesh fallback path still works when registry path yields nothing
# ===========================================================================


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator unavailable")
class TestMeshFallbackWhenRegistryEmpty:
    def test_mesh_session_fallback_when_no_registry_candidates(self):
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry unavailable")
        reg = AttachedSessionRegistry()
        mesh = {
            "session_id": "mesh-sess-1",
            "participants": [
                {"device_id": "mesh-dev-1", "runtime_id": "rt-1", "status": "active"}
            ],
        }
        result = select_dispatch_target(
            registry=reg,
            mesh_session=mesh,
        )
        assert result is not None
        assert result.target_device_id == "mesh-dev-1"
        assert "fallback" in (result.selection_reason or "")

    def test_mesh_fallback_reason_contains_fallback(self):
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry unavailable")
        reg = AttachedSessionRegistry()
        mesh = {
            "session_id": "mesh-sess-2",
            "participants": [
                {"device_id": "mesh-dev-2", "status": "joined"}
            ],
        }
        result = select_dispatch_target(
            registry=reg,
            mesh_session=mesh,
        )
        assert result is not None
        assert result.selection_reason is not None
        assert "fallback" in result.selection_reason


# ===========================================================================
# Group O — Selection reasons are stable strings
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestSelectionReasonsAreStable:
    def test_explicit_target_reason_constant(self):
        results = [
            select_dispatch_target(target_device_id=f"dev-{i}")
            for i in range(5)
        ]
        reasons = {r.selection_reason for r in results if r is not None}
        assert reasons == {"explicit_target_device_id"}

    def test_consolidated_selection_reason_stable_across_calls(self):
        reg = _make_registry_with_active_session("sess-o1", "dev-o1")
        r_map = {
            "dev-o1": _FakeReadiness("dev-o1"),
        }
        p_map = {
            "dev-o1": _FakeParticipation("dev-o1"),
        }
        reasons = set()
        for _ in range(3):
            r = _select_target_from_candidates(
                registry=reg,
                readiness_inputs=r_map,
                participation_inputs=p_map,
                reuse_inputs={"dev-o1": False},
            )
            if r is not None:
                reasons.add(r.selection_reason)
        assert len(reasons) == 1, f"reason should be stable; got {reasons}"

    def test_reason_is_not_none_on_successful_selection(self):
        reg = _make_registry_with_active_session("sess-o2", "dev-o2")
        result = _select_target_from_candidates(
            registry=reg,
            readiness_inputs={"dev-o2": _FakeReadiness("dev-o2")},
            participation_inputs={"dev-o2": _FakeParticipation("dev-o2")},
        )
        assert result is not None
        assert result.selection_reason is not None

    def test_fallback_reason_not_empty(self):
        if not _REGISTRY_AVAILABLE:
            pytest.skip("registry unavailable")
        reg = AttachedSessionRegistry()
        mesh = {
            "participants": [
                {"device_id": "mesh-dev-f", "status": "active"}
            ],
        }
        result = select_dispatch_target(registry=reg, mesh_session=mesh)
        if result is not None:
            assert result.selection_reason
            assert len(result.selection_reason) > 0


# ===========================================================================
# Group P — build_source_dispatch_plan passes truth inputs through
# ===========================================================================


@pytest.mark.skipif(
    not (_ORCHESTRATOR_AVAILABLE and _REGISTRY_AVAILABLE),
    reason="orchestrator or registry unavailable",
)
class TestBuildPlanPassesTruthInputs:
    def test_plan_built_with_consolidated_truth_inputs(self):
        reg = _make_registry_with_active_session("sess-p1", "dev-p1")
        plan = build_source_dispatch_plan(
            trace_id="trace-p1",
            target_device_id="dev-p1",
            registry=reg,
            readiness_inputs={"dev-p1": _FakeReadiness("dev-p1")},
            participation_inputs={"dev-p1": _FakeParticipation("dev-p1")},
            reuse_inputs={"dev-p1": False},
            policy_alignment={},
            governance_snapshot={},
            mesh_session={},
            mesh_memberships=[],
        )
        assert plan is not None

    def test_plan_accepts_registry_param_without_error(self):
        reg = AttachedSessionRegistry()
        plan = build_source_dispatch_plan(
            trace_id="trace-p2",
            registry=reg,
            policy_alignment={},
            governance_snapshot={},
            mesh_session={},
            mesh_memberships=[],
        )
        assert plan is not None

    def test_plan_readiness_and_participation_params_accepted(self):
        reg = _make_registry_with_active_session("sess-p3", "dev-p3")
        plan = build_source_dispatch_plan(
            trace_id="trace-p3",
            registry=reg,
            readiness_inputs={"dev-p3": _FakeReadiness("dev-p3")},
            participation_inputs={"dev-p3": _FakeParticipation("dev-p3")},
            reuse_inputs={"dev-p3": True},
            policy_alignment={},
            governance_snapshot={},
            mesh_session={},
            mesh_memberships=[],
        )
        assert plan is not None


# ===========================================================================
# Group Q — _score_candidate: readiness unavailable → score=0, stable reason
# ===========================================================================


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator unavailable")
class TestScoreCandidateReadinessUnavailable:
    def test_none_readiness_returns_zero_score(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=None,
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        assert score == 0
        assert reason
        assert len(reason) > 0

    def test_none_readiness_reason_contains_unavailable(self):
        _, reason = _score_candidate(
            "s", "d",
            readiness=None,
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        assert "unavailable" in reason


# ===========================================================================
# Group R — _score_candidate: participation unavailable → score=0, stable reason
# ===========================================================================


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator unavailable")
class TestScoreCandidateParticipationUnavailable:
    def test_none_participation_returns_zero_score(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=None,
            reuse_eligible=False,
        )
        assert score == 0
        assert reason
        assert len(reason) > 0

    def test_none_participation_reason_is_stable(self):
        _, r1 = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=None,
            reuse_eligible=False,
        )
        _, r2 = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=None,
            reuse_eligible=False,
        )
        assert r1 == r2


# ===========================================================================
# Group S — _score_candidate: all pass, reuse=True → score > no_reuse baseline
# ===========================================================================


@pytest.mark.skipif(not _ORCHESTRATOR_AVAILABLE, reason="orchestrator unavailable")
class TestScoreCandidateReuseEffect:
    def test_reuse_true_higher_score(self):
        score_no, _ = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        score_yes, _ = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=True,
        )
        assert score_yes > score_no

    def test_both_have_zero_rejection_reason_when_passing(self):
        _, r_no = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        _, r_yes = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=True,
        )
        assert r_no == ""
        assert r_yes == ""

    def test_score_is_positive_when_passing(self):
        score, reason = _score_candidate(
            "s", "d",
            readiness=_FakeReadiness("d"),
            participation=_FakeParticipation("d"),
            reuse_eligible=False,
        )
        assert score > 0
        assert reason == ""
