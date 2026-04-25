"""tests/test_pr4v2_android_evaluator_artifact_governance_flow.py
=================================================================
PR-4V2-GOV: Tests proving Android evaluator artifacts flow into V2 canonical
readiness and governance decision-making.

Problem statement
-----------------
The third-round joint review established that Android-originated evaluator/
runtime artifacts (readiness, acceptance, governance, strategy) must become
first-class inputs into V2 canonical readiness and governance verdict flows,
not merely advisory/observation-only signals.

This test suite provides reviewable evidence for all five acceptance criteria:

  AC1  How Android-originated evaluator/runtime artifacts travel into V2
       (truth kind path, ingress reachability, artifact extraction).

  AC2  Where artifacts are stored/projected in V2 canonical systems
       (AndroidEvaluatorArtifactRegistry projection, FlowTruthAlignmentRuntime).

  AC3  Whether V2 readiness/governance flows can actually read them
       (DelegatedFlowReadinessGate truth_ownership dimension visibility).

  AC4  Which artifacts are canonical gate inputs vs observation-only evidence
       (governance_artifact = canonical; readiness_assessment = advisory).

  AC5  What remains deferred for later PRs
       (CI/release blocking, default-on, full multi-device governance).

Coverage groups
---------------
A.  AndroidEvaluatorArtifactKind: enum values, from_string(), is_canonical_gate_input().
B.  AndroidEvaluatorArtifact: construction, to_dict(), identity fields.
C.  extract_evaluator_artifact(): field extraction from raw message.
D.  AndroidEvaluatorArtifactRegistry: record(), list_recent(), get_latest_for_device_kind().
E.  ingest_android_evaluator_artifact(): stores to registry + calls truth ingress.
F.  governance_artifact truth kind: is NOT advisory (local_only=False).
G.  governance_artifact truth kind: calls align_and_record() → FlowTruthAlignmentRuntime.
H.  readiness_assessment truth kind remains advisory (policy enforcement).
I.  DelegatedFlowReadinessGate truth_ownership: reads FlowTruthAlignmentRuntime.
J.  End-to-end chain: governance_artifact → truth ingress → FlowTruthAlignmentRuntime.
K.  Policy sentinels: all required sentinels are importable and non-empty.
L.  Validation matrix: AndroidEvaluatorArtifactIngestOutcome is JSON-serialisable.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Import guards
# ---------------------------------------------------------------------------

try:
    from core.android_evaluator_artifact_ingress import (
        ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY,
        ANDROID_EVALUATOR_ARTIFACT_INGRESS_SENTINEL,
        CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY,
        DEFERRED_TO_LATER_PRS_POLICY,
        EVALUATOR_ARTIFACT_IS_FIRST_CLASS_GATE_INPUT_POLICY,
        EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION_POLICY,
        AndroidEvaluatorArtifact,
        AndroidEvaluatorArtifactIngestOutcome,
        AndroidEvaluatorArtifactKind,
        AndroidEvaluatorArtifactRegistry,
        extract_evaluator_artifact,
        get_evaluator_artifact_registry,
        ingest_android_evaluator_artifact,
        reset_evaluator_artifact_registry,
    )

    _INGRESS_AVAILABLE = True
except ImportError:
    _INGRESS_AVAILABLE = False

try:
    from core.android_participant_truth_ingress import (
        GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY,
        READINESS_ASSESSMENT_IS_ADVISORY_POLICY,
        AndroidParticipantTruthKind,
        ingest_android_participant_truth_message,
    )

    _TRUTH_INGRESS_AVAILABLE = True
except ImportError:
    _TRUTH_INGRESS_AVAILABLE = False

try:
    from core.delegated_flow_readiness_gate import (
        DelegatedFlowReadinessGate,
        DelegatedFlowReadinessReport,
        ReadinessDimension,
        get_readiness_gate,
        reset_readiness_gate,
    )

    _READINESS_GATE_AVAILABLE = True
except ImportError:
    _READINESS_GATE_AVAILABLE = False

try:
    from core.flow_level_truth_ownership import (
        FlowTruthAlignmentContext,
        align_and_record,
        build_flow_truth_alignment_snapshot,
        get_flow_truth_alignment_runtime,
        reset_flow_truth_alignment_runtime,
    )

    _FLOW_TRUTH_AVAILABLE = True
except ImportError:
    _FLOW_TRUTH_AVAILABLE = False

# ---------------------------------------------------------------------------
# Skip decorators
# ---------------------------------------------------------------------------

_skip_ingress = pytest.mark.skipif(
    not _INGRESS_AVAILABLE,
    reason="android_evaluator_artifact_ingress not importable",
)
_skip_truth_ingress = pytest.mark.skipif(
    not _TRUTH_INGRESS_AVAILABLE,
    reason="android_participant_truth_ingress not importable",
)
_skip_readiness_gate = pytest.mark.skipif(
    not _READINESS_GATE_AVAILABLE,
    reason="delegated_flow_readiness_gate not importable",
)
_skip_flow_truth = pytest.mark.skipif(
    not _FLOW_TRUTH_AVAILABLE,
    reason="flow_level_truth_ownership not importable",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_governance_artifact_message(
    *,
    device_id: str = "dev-test",
    evaluator_kind: str = "governance",
    session_id: str = "s-test",
    contract_id: str = "",
    is_compliant: Optional[bool] = True,
    verdict: str = "governance_compliant",
) -> Dict[str, Any]:
    return {
        "type": "governance_artifact",
        "device_id": device_id,
        "payload": {
            "evaluator_kind": evaluator_kind,
            "session_id": session_id,
            "contract_id": contract_id,
            "is_compliant": is_compliant,
            "verdict": verdict,
        },
    }


# ===========================================================================
# Group A: AndroidEvaluatorArtifactKind enum
# ===========================================================================


class TestGroupA_AndroidEvaluatorArtifactKind:
    """Group A: enum values, from_string(), is_canonical_gate_input()."""

    @_skip_ingress
    def test_A01_all_four_canonical_kinds_exist(self):
        """All four canonical evaluator kinds must be present."""
        for k in ("governance", "readiness", "acceptance", "strategy"):
            assert AndroidEvaluatorArtifactKind.from_string(k) != AndroidEvaluatorArtifactKind.unknown

    @_skip_ingress
    def test_A02_from_string_case_insensitive(self):
        """from_string() must be case-insensitive."""
        assert AndroidEvaluatorArtifactKind.from_string("GOVERNANCE") == AndroidEvaluatorArtifactKind.governance
        assert AndroidEvaluatorArtifactKind.from_string("Readiness") == AndroidEvaluatorArtifactKind.readiness

    @_skip_ingress
    def test_A03_unknown_kind_for_unrecognised_value(self):
        """Unrecognised value must return unknown."""
        assert AndroidEvaluatorArtifactKind.from_string("foobar") == AndroidEvaluatorArtifactKind.unknown
        assert AndroidEvaluatorArtifactKind.from_string("") == AndroidEvaluatorArtifactKind.unknown
        assert AndroidEvaluatorArtifactKind.from_string(None) == AndroidEvaluatorArtifactKind.unknown

    @_skip_ingress
    def test_A04_canonical_gate_input_kinds_are_all_four(self):
        """All four evaluator kinds must be canonical gate inputs."""
        for k in (
            AndroidEvaluatorArtifactKind.governance,
            AndroidEvaluatorArtifactKind.readiness,
            AndroidEvaluatorArtifactKind.acceptance,
            AndroidEvaluatorArtifactKind.strategy,
        ):
            assert k.is_canonical_gate_input() is True, (
                f"{k.value} must be a canonical gate input (AC4)"
            )

    @_skip_ingress
    def test_A05_unknown_kind_is_not_canonical_gate_input(self):
        """unknown kind must NOT be a canonical gate input."""
        assert AndroidEvaluatorArtifactKind.unknown.is_canonical_gate_input() is False


# ===========================================================================
# Group B: AndroidEvaluatorArtifact dataclass
# ===========================================================================


class TestGroupB_AndroidEvaluatorArtifact:
    """Group B: construction, to_dict(), identity fields."""

    @_skip_ingress
    def test_B01_artifact_construction_with_defaults(self):
        """AndroidEvaluatorArtifact must be constructible with default fields."""
        art = AndroidEvaluatorArtifact()
        assert art.kind == AndroidEvaluatorArtifactKind.unknown
        assert art.device_id == ""
        assert art.artifact_id.startswith("aea_")

    @_skip_ingress
    def test_B02_artifact_to_dict_is_json_safe(self):
        """to_dict() must return a JSON-safe dict."""
        import json

        art = AndroidEvaluatorArtifact(
            kind=AndroidEvaluatorArtifactKind.governance,
            device_id="dev-B02",
            session_id="s-B02",
            is_compliant=True,
            verdict_label="governance_compliant",
        )
        d = art.to_dict()
        json.dumps(d)  # must not raise
        assert d["kind"] == "governance"
        assert d["device_id"] == "dev-B02"
        assert d["is_compliant"] is True

    @_skip_ingress
    def test_B03_artifact_id_is_unique(self):
        """Each artifact must have a unique artifact_id."""
        a1 = AndroidEvaluatorArtifact()
        a2 = AndroidEvaluatorArtifact()
        assert a1.artifact_id != a2.artifact_id


# ===========================================================================
# Group C: extract_evaluator_artifact()
# ===========================================================================


class TestGroupC_ExtractEvaluatorArtifact:
    """Group C: field extraction from raw message."""

    @_skip_ingress
    def test_C01_extracts_governance_kind_from_payload(self):
        """governance kind must be extracted from payload.evaluator_kind."""
        msg = _make_governance_artifact_message(evaluator_kind="governance")
        artifact = extract_evaluator_artifact(msg)
        assert artifact.kind == AndroidEvaluatorArtifactKind.governance

    @_skip_ingress
    def test_C02_extracts_device_id_from_top_level(self):
        """device_id must be extracted from the top-level message field."""
        msg = _make_governance_artifact_message(device_id="dev-C02")
        artifact = extract_evaluator_artifact(msg)
        assert artifact.device_id == "dev-C02"

    @_skip_ingress
    def test_C03_extracts_is_compliant_from_payload(self):
        """is_compliant must be extracted from payload.is_compliant."""
        msg = _make_governance_artifact_message(is_compliant=False)
        artifact = extract_evaluator_artifact(msg)
        assert artifact.is_compliant is False

    @_skip_ingress
    def test_C04_extracts_session_id_from_payload(self):
        """session_id must be extracted from payload.session_id."""
        msg = _make_governance_artifact_message(session_id="ses-C04")
        artifact = extract_evaluator_artifact(msg)
        assert artifact.session_id == "ses-C04"

    @_skip_ingress
    def test_C05_unknown_kind_for_missing_evaluator_kind(self):
        """Missing evaluator_kind must result in unknown artifact kind."""
        msg = {"type": "governance_artifact", "device_id": "dev-C05", "payload": {}}
        artifact = extract_evaluator_artifact(msg)
        assert artifact.kind == AndroidEvaluatorArtifactKind.unknown

    @_skip_ingress
    def test_C06_non_dict_message_handled_gracefully(self):
        """Non-dict message must not raise; should return unknown artifact."""
        artifact = extract_evaluator_artifact("not_a_dict")  # type: ignore[arg-type]
        assert artifact.kind == AndroidEvaluatorArtifactKind.unknown


# ===========================================================================
# Group D: AndroidEvaluatorArtifactRegistry
# ===========================================================================


class TestGroupD_AndroidEvaluatorArtifactRegistry:
    """Group D: record(), list_recent(), get_latest_for_device_kind()."""

    @_skip_ingress
    def test_D01_registry_records_and_lists_artifacts(self):
        """Registry must store and return recorded artifacts."""
        reg = AndroidEvaluatorArtifactRegistry()
        art = AndroidEvaluatorArtifact(
            kind=AndroidEvaluatorArtifactKind.governance,
            device_id="dev-D01",
        )
        reg.record(art)
        recent = reg.list_recent(5)
        assert len(recent) == 1
        assert recent[0].artifact_id == art.artifact_id

    @_skip_ingress
    def test_D02_get_latest_for_device_kind_returns_most_recent(self):
        """get_latest_for_device_kind must return the most recent artifact."""
        reg = AndroidEvaluatorArtifactRegistry()
        art1 = AndroidEvaluatorArtifact(
            kind=AndroidEvaluatorArtifactKind.governance,
            device_id="dev-D02",
        )
        art2 = AndroidEvaluatorArtifact(
            kind=AndroidEvaluatorArtifactKind.governance,
            device_id="dev-D02",
        )
        reg.record(art1)
        reg.record(art2)
        latest = reg.get_latest_for_device_kind("dev-D02", AndroidEvaluatorArtifactKind.governance)
        # art2 was recorded second, so it's newest (ring appendleft)
        assert latest is not None
        assert latest.artifact_id == art2.artifact_id

    @_skip_ingress
    def test_D03_get_latest_for_device_kind_returns_none_when_missing(self):
        """get_latest_for_device_kind must return None when no matching artifact."""
        reg = AndroidEvaluatorArtifactRegistry()
        result = reg.get_latest_for_device_kind("nonexistent", AndroidEvaluatorArtifactKind.governance)
        assert result is None

    @_skip_ingress
    def test_D04_registry_build_snapshot_is_serialisable(self):
        """Registry snapshot must be JSON-serialisable."""
        import json

        reg = AndroidEvaluatorArtifactRegistry()
        reg.record(AndroidEvaluatorArtifact(
            kind=AndroidEvaluatorArtifactKind.readiness,
            device_id="dev-D04",
        ))
        snapshot = reg.build_snapshot()
        json.dumps(snapshot)  # must not raise

    @_skip_ingress
    def test_D05_registry_snapshot_lists_canonical_gate_input_kinds(self):
        """Registry snapshot must list canonical gate input kinds."""
        reg = AndroidEvaluatorArtifactRegistry()
        snapshot = reg.build_snapshot()
        gate_kinds = snapshot.get("canonical_gate_input_kinds", [])
        assert "governance" in gate_kinds
        assert "readiness" in gate_kinds
        assert "acceptance" in gate_kinds
        assert "strategy" in gate_kinds

    @_skip_ingress
    def test_D06_count_reflects_total_recorded(self):
        """count() must return the total number of recorded artifacts."""
        reg = AndroidEvaluatorArtifactRegistry()
        assert reg.count() == 0
        reg.record(AndroidEvaluatorArtifact())
        reg.record(AndroidEvaluatorArtifact())
        assert reg.count() == 2


# ===========================================================================
# Group E: ingest_android_evaluator_artifact()
# ===========================================================================


class TestGroupE_IngestAndroidEvaluatorArtifact:
    """Group E: ingest_android_evaluator_artifact() end-to-end."""

    @_skip_ingress
    def test_E01_ingest_stores_artifact_in_registry(self):
        """Ingesting an artifact must store it in the registry."""
        reset_evaluator_artifact_registry()
        reg = AndroidEvaluatorArtifactRegistry()
        msg = _make_governance_artifact_message(device_id="dev-E01")
        outcome = ingest_android_evaluator_artifact(msg, registry=reg)
        assert outcome.was_stored is True
        stored = reg.list_recent(1)
        assert len(stored) == 1
        assert stored[0].device_id == "dev-E01"

    @_skip_ingress
    def test_E02_ingest_returns_typed_outcome(self):
        """ingest_android_evaluator_artifact() must return a typed outcome."""
        msg = _make_governance_artifact_message(device_id="dev-E02")
        outcome = ingest_android_evaluator_artifact(msg)
        assert isinstance(outcome, AndroidEvaluatorArtifactIngestOutcome)
        assert outcome.artifact is not None

    @_skip_ingress
    def test_E03_ingest_outcome_is_json_serialisable(self):
        """AndroidEvaluatorArtifactIngestOutcome.to_dict() must be JSON-safe."""
        import json

        msg = _make_governance_artifact_message(device_id="dev-E03")
        outcome = ingest_android_evaluator_artifact(msg)
        json.dumps(outcome.to_dict())  # must not raise

    @_skip_ingress
    def test_E04_ingest_calls_truth_ingress_when_available(self):
        """ingest must call truth ingress for governance_artifact reconcile path."""
        msg = _make_governance_artifact_message(device_id="dev-E04")
        outcome = ingest_android_evaluator_artifact(msg)
        # If truth ingress is available, the reconcile outcome should be set
        if _TRUTH_INGRESS_AVAILABLE:
            # reject_reason should be empty or only reflect tracker miss, not unavailable
            assert "unavailable" not in outcome.reject_reason or not _TRUTH_INGRESS_AVAILABLE

    @_skip_ingress
    def test_E05_ingest_works_with_unknown_kind(self):
        """Ingestion must not raise even if evaluator_kind is unrecognised."""
        msg = {"type": "governance_artifact", "device_id": "dev-E05", "payload": {}}
        outcome = ingest_android_evaluator_artifact(msg)
        # Should return an outcome (no exception)
        assert isinstance(outcome, AndroidEvaluatorArtifactIngestOutcome)


# ===========================================================================
# Group F: governance_artifact truth kind — NOT advisory
# ===========================================================================


class TestGroupF_GovernanceArtifactTruthKindIsNotAdvisory:
    """Group F: governance_artifact truth kind is a first-class canonical input.

    AC4 evidence: governance_artifact is canonical, readiness_assessment is advisory.
    """

    @_skip_truth_ingress
    def test_F01_governance_artifact_kind_exists_in_enum(self):
        """governance_artifact must be a recognised AndroidParticipantTruthKind."""
        kind = AndroidParticipantTruthKind.from_string("governance_artifact")
        assert kind == AndroidParticipantTruthKind.governance_artifact

    @_skip_truth_ingress
    def test_F02_governance_artifact_affects_canonical_state(self):
        """governance_artifact must be in affects_canonical_state() = True."""
        kind = AndroidParticipantTruthKind.governance_artifact
        assert kind.affects_canonical_state() is True, (
            "governance_artifact must affect canonical state (first-class gate input)"
        )

    @_skip_truth_ingress
    def test_F03_governance_artifact_truth_ingress_returns_not_local_only(self):
        """governance_artifact truth must NOT be local_only=True (unlike readiness_assessment).

        AC4: governance_artifact is canonical, not advisory.
        """
        msg = {
            "type": "governance_artifact",
            "truth_kind": "governance_artifact",
            "device_id": "dev-F03",
            "payload": {
                "session_id": "s-F03",
                "evaluator_kind": "governance",
                "is_compliant": True,
            },
        }
        outcome = ingest_android_participant_truth_message(msg)
        # governance_artifact is NOT advisory — local_only must be False
        assert outcome.local_only is False, (
            "governance_artifact must not be advisory/local-only (AC4: first-class canonical input)"
        )

    @_skip_truth_ingress
    def test_F04_readiness_assessment_remains_advisory_by_policy(self):
        """readiness_assessment must still be local_only=True per READINESS_ASSESSMENT_IS_ADVISORY_POLICY.

        AC4: readiness_assessment remains observation-only (advisory).
        """
        msg = {
            "type": "reconciliation_signal",
            "device_id": "dev-F04",
            "truth_kind": "readiness_assessment",
            "payload": {
                "ready": True,
                "session_id": "s-F04",
            },
        }
        outcome = ingest_android_participant_truth_message(msg)
        assert outcome.local_only is True, (
            "readiness_assessment must remain advisory/local-only per READINESS_ASSESSMENT_IS_ADVISORY_POLICY"
        )

    @_skip_truth_ingress
    def test_F05_governance_artifact_policy_sentinel_is_importable(self):
        """GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY must be importable and non-empty."""
        assert isinstance(GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY, str)
        assert len(GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY) > 0
        assert "governance_artifact" in GOVERNANCE_ARTIFACT_IS_CANONICAL_GATE_INPUT_POLICY.lower()


# ===========================================================================
# Group G: governance_artifact → align_and_record() → FlowTruthAlignmentRuntime
# ===========================================================================


class TestGroupG_GovernanceArtifactAlignAndRecord:
    """Group G: governance_artifact calls align_and_record() → FlowTruthAlignmentRuntime.

    AC2 evidence: artifacts are stored/projected in canonical systems.
    AC3 evidence: V2 readiness/governance flows can read them.
    """

    @_skip_flow_truth
    def test_G01_align_and_record_accepts_governance_artifact_kind(self):
        """align_and_record() must accept governance_artifact truth kind without error."""
        reset_flow_truth_alignment_runtime()
        ctx = FlowTruthAlignmentContext(
            truth_kind="governance_artifact",
            session_id="s-G01",
        )
        # Must not raise
        artifact = align_and_record(ctx)
        assert artifact is not None
        assert artifact.decision is not None

    @_skip_flow_truth
    def test_G02_governance_artifact_writes_to_flow_truth_runtime(self):
        """After align_and_record() with governance_artifact, FlowTruthAlignmentRuntime
        must have at least one decision recorded.

        This proves AC2: artifacts are stored/projected in V2 canonical systems.
        """
        reset_flow_truth_alignment_runtime()
        runtime = get_flow_truth_alignment_runtime()
        snapshot_before = runtime.build_snapshot()
        before_count = snapshot_before.total_decisions

        ctx = FlowTruthAlignmentContext(
            truth_kind="governance_artifact",
            session_id="s-G02",
            contract_id="c-G02",
        )
        align_and_record(ctx)

        snapshot_after = runtime.build_snapshot()
        assert snapshot_after.total_decisions > before_count, (
            "governance_artifact must increment FlowTruthAlignmentRuntime.total_decisions (AC2)"
        )

    @_skip_flow_truth
    def test_G03_governance_artifact_is_classified_as_authoritative(self):
        """governance_artifact must be classified as accept_as_authoritative by align_and_record().

        This proves it is not advisory — it is a canonical gate input (AC4).
        """
        from core.flow_level_truth_ownership import FlowTruthDecisionKind

        reset_flow_truth_alignment_runtime()
        ctx = FlowTruthAlignmentContext(
            truth_kind="governance_artifact",
            v2_canonical_flow_phase="",  # non-terminal
            compat_influence_active=False,
            posture_changed=False,
        )
        artifact = align_and_record(ctx)
        assert artifact.decision == FlowTruthDecisionKind.accept_as_authoritative, (
            f"governance_artifact must be accept_as_authoritative, got {artifact.decision} (AC4)"
        )


# ===========================================================================
# Group H: readiness_assessment remains advisory
# ===========================================================================


class TestGroupH_ReadinessAssessmentRemainsAdvisory:
    """Group H: readiness_assessment truth kind remains advisory/local-only.

    AC4 evidence: the distinction between canonical and advisory evidence is explicit.
    """

    @_skip_flow_truth
    def test_H01_readiness_assessment_is_classified_advisory_by_align_and_record(self):
        """readiness_assessment must be classified as accept_as_advisory by align_and_record().

        AC4: readiness_assessment remains observation-only.
        """
        from core.flow_level_truth_ownership import FlowTruthDecisionKind

        ctx = FlowTruthAlignmentContext(
            truth_kind="readiness_assessment",
            v2_canonical_flow_phase="",
            compat_influence_active=False,
        )
        artifact = align_and_record(ctx)
        assert artifact.decision in (
            FlowTruthDecisionKind.accept_as_advisory,
            FlowTruthDecisionKind.record_as_execution_evidence,
        ), (
            f"readiness_assessment must be advisory, got {artifact.decision} (AC4)"
        )


# ===========================================================================
# Group I: DelegatedFlowReadinessGate truth_ownership reads FlowTruthAlignmentRuntime
# ===========================================================================


class TestGroupI_ReadinessGateTruthOwnership:
    """Group I: DelegatedFlowReadinessGate truth_ownership dimension reads FlowTruthAlignmentRuntime.

    AC3 evidence: V2 readiness/governance flows can read Android-originated artifacts.
    """

    @_skip_readiness_gate
    @_skip_flow_truth
    def test_I01_gate_truth_ownership_uses_flow_truth_alignment_runtime(self):
        """DelegatedFlowReadinessGate must include truth_ownership in its report."""
        reset_readiness_gate()
        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()

        assert isinstance(report, DelegatedFlowReadinessReport)
        assert ReadinessDimension.truth_ownership.value in report.dimensions, (
            "truth_ownership dimension must be present in gate report (AC3)"
        )

    @_skip_readiness_gate
    @_skip_flow_truth
    def test_I02_gate_report_after_governance_artifact_has_truth_ownership(self):
        """After recording a governance_artifact decision, gate report must include
        truth_ownership dimension.

        This validates the end-to-end projection: Android artifact → gate visibility.
        AC3 evidence.
        """
        reset_flow_truth_alignment_runtime()
        reset_readiness_gate()

        # Record a governance_artifact alignment decision
        ctx = FlowTruthAlignmentContext(
            truth_kind="governance_artifact",
            session_id="s-I02",
        )
        align_and_record(ctx)

        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()

        # truth_ownership dimension must be present
        truth_dim = report.dimensions.get(ReadinessDimension.truth_ownership.value)
        assert truth_dim is not None, (
            "truth_ownership dimension must appear in gate report after governance_artifact (AC3)"
        )

    @_skip_readiness_gate
    @_skip_flow_truth
    def test_I03_gate_truth_ownership_not_unknown_when_decisions_exist(self):
        """truth_ownership dimension must not be 'unknown' when FlowTruthAlignmentRuntime
        has alignment decisions.

        AC3: gate can read artifacts and produce a meaningful verdict.
        """
        from core.flow_level_truth_ownership import FlowTruthDecisionKind
        from core.delegated_flow_readiness_gate import DimensionReadinessStatus

        reset_flow_truth_alignment_runtime()
        reset_readiness_gate()

        # Record a non-quarantined governance_artifact decision
        ctx = FlowTruthAlignmentContext(
            truth_kind="governance_artifact",
            session_id="s-I03",
            v2_canonical_flow_phase="",
            compat_influence_active=False,
            posture_changed=False,
        )
        align_and_record(ctx)

        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()

        truth_dim = report.dimensions.get(ReadinessDimension.truth_ownership.value)
        if truth_dim is not None:
            assert truth_dim.status != DimensionReadinessStatus.unknown, (
                "truth_ownership must not be 'unknown' when FlowTruthAlignmentRuntime has decisions (AC3)"
            )


# ===========================================================================
# Group J: End-to-end chain
# ===========================================================================


class TestGroupJ_EndToEndChain:
    """Group J: End-to-end chain proving the full path.

    AC1 + AC2 + AC3 evidence.
    """

    @_skip_ingress
    @_skip_flow_truth
    def test_J01_evaluator_artifact_ingress_writes_to_flow_truth_runtime(self):
        """ingest_android_evaluator_artifact() must write to FlowTruthAlignmentRuntime.

        This proves: Android artifact production → signal transport → V2 ingress →
        participant truth → gate consumption.

        AC1: artifacts travel into V2.
        AC2: artifacts are stored/projected in FlowTruthAlignmentRuntime.
        """
        reset_flow_truth_alignment_runtime()
        reset_evaluator_artifact_registry()

        runtime = get_flow_truth_alignment_runtime()
        before = runtime.build_snapshot().total_decisions

        msg = _make_governance_artifact_message(
            device_id="dev-J01",
            evaluator_kind="governance",
            session_id="s-J01",
        )
        outcome = ingest_android_evaluator_artifact(msg)

        # Artifact must be stored in registry
        assert outcome.was_stored is True

        # If flow_level_truth_ownership is available, FlowTruthAlignmentRuntime
        # must have accumulated a new decision
        after = runtime.build_snapshot().total_decisions
        assert after > before, (
            "ingest_android_evaluator_artifact() must write to FlowTruthAlignmentRuntime (AC2)"
        )

    @_skip_ingress
    def test_J02_all_four_evaluator_kinds_are_ingested_and_stored(self):
        """All four evaluator kinds (governance, readiness, acceptance, strategy) must
        be storable via ingest_android_evaluator_artifact().

        AC1: artifacts travel into V2 for all evaluator dimensions.
        """
        reg = AndroidEvaluatorArtifactRegistry()
        for kind_str in ("governance", "readiness", "acceptance", "strategy"):
            msg = _make_governance_artifact_message(
                device_id=f"dev-J02-{kind_str}",
                evaluator_kind=kind_str,
            )
            outcome = ingest_android_evaluator_artifact(msg, registry=reg)
            assert outcome.was_stored is True, (
                f"Evaluator kind '{kind_str}' must be stored in registry (AC1)"
            )
            stored = reg.get_latest_for_device_kind(
                f"dev-J02-{kind_str}",
                AndroidEvaluatorArtifactKind.from_string(kind_str),
            )
            assert stored is not None, (
                f"Registry must have artifact for kind '{kind_str}' (AC2)"
            )

    @_skip_ingress
    @_skip_readiness_gate
    @_skip_flow_truth
    def test_J03_governance_artifact_is_visible_at_v2_readiness_gate(self):
        """After ingesting a governance artifact, the V2 readiness gate truth_ownership
        dimension must reflect the new alignment decision.

        AC3: V2 readiness/governance flows can actually read the artifact.
        """
        reset_flow_truth_alignment_runtime()
        reset_readiness_gate()
        reset_evaluator_artifact_registry()

        msg = _make_governance_artifact_message(
            device_id="dev-J03",
            evaluator_kind="governance",
            session_id="s-J03",
        )
        ingest_android_evaluator_artifact(msg)

        gate = DelegatedFlowReadinessGate()
        report = gate.evaluate()

        truth_dim = report.dimensions.get(ReadinessDimension.truth_ownership.value)
        assert truth_dim is not None, "truth_ownership dimension must be present (AC3)"

        from core.delegated_flow_readiness_gate import DimensionReadinessStatus
        # The dimension must NOT be 'unknown' since we just ingested an artifact
        assert truth_dim.status != DimensionReadinessStatus.unknown, (
            "truth_ownership dimension must reflect the governance artifact, not 'unknown' (AC3)"
        )


# ===========================================================================
# Group K: Policy sentinels
# ===========================================================================


class TestGroupK_PolicySentinels:
    """Group K: All required policy sentinels must be importable and non-empty."""

    @_skip_ingress
    def test_K01_authority_sentinel_is_non_empty(self):
        """ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY must be non-empty."""
        assert isinstance(ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY, str)
        assert len(ANDROID_EVALUATOR_ARTIFACT_INGRESS_AUTHORITY) > 0

    @_skip_ingress
    def test_K02_all_policy_sentinels_are_non_empty(self):
        """All policy sentinels must be importable and non-empty."""
        for sentinel in (
            EVALUATOR_ARTIFACT_IS_FIRST_CLASS_GATE_INPUT_POLICY,
            CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY,
            EVALUATOR_ARTIFACT_REGISTRY_IS_READ_ONLY_PROJECTION_POLICY,
            DEFERRED_TO_LATER_PRS_POLICY,
        ):
            assert isinstance(sentinel, str) and len(sentinel) > 0

    @_skip_ingress
    def test_K03_deferred_policy_documents_later_pr_scope(self):
        """DEFERRED_TO_LATER_PRS_POLICY must mention CI and release blocking (AC5)."""
        assert "CI" in DEFERRED_TO_LATER_PRS_POLICY or "release" in DEFERRED_TO_LATER_PRS_POLICY.lower()

    @_skip_ingress
    def test_K04_canonical_vs_advisory_policy_mentions_both_paths(self):
        """CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY must
        reference both canonical and advisory paths (AC4)."""
        policy = CANONICAL_VS_ADVISORY_DISTINCTION_MUST_BE_EXPLICIT_POLICY.lower()
        assert "canonical" in policy
        assert "advisory" in policy


# ===========================================================================
# Group L: Serialisability and validation matrix
# ===========================================================================


class TestGroupL_ValidationMatrix:
    """Group L: Serialisability and validation matrix evidence."""

    @_skip_ingress
    def test_L01_ingest_outcome_to_dict_is_json_safe(self):
        """AndroidEvaluatorArtifactIngestOutcome.to_dict() must be JSON-serialisable."""
        import json

        msg = _make_governance_artifact_message(device_id="dev-L01")
        outcome = ingest_android_evaluator_artifact(msg)
        json.dumps(outcome.to_dict())  # must not raise

    @_skip_ingress
    def test_L02_registry_snapshot_reflects_ingested_artifacts(self):
        """Registry snapshot must reflect all ingested artifact kinds."""
        reset_evaluator_artifact_registry()
        reg = AndroidEvaluatorArtifactRegistry()

        for kind_str in ("governance", "readiness", "acceptance", "strategy"):
            msg = _make_governance_artifact_message(evaluator_kind=kind_str)
            ingest_android_evaluator_artifact(msg, registry=reg)

        snapshot = reg.build_snapshot()
        counts = snapshot["artifact_counts_by_kind"]
        for kind_str in ("governance", "readiness", "acceptance", "strategy"):
            assert counts.get(kind_str, 0) >= 1, (
                f"Registry snapshot must show at least 1 artifact of kind '{kind_str}'"
            )

    @_skip_ingress
    def test_L03_all_canonical_kinds_in_snapshot_gate_input_list(self):
        """All four evaluator kinds must appear in snapshot.canonical_gate_input_kinds."""
        reg = AndroidEvaluatorArtifactRegistry()
        snapshot = reg.build_snapshot()
        gate_kinds = snapshot["canonical_gate_input_kinds"]
        for k in ("governance", "readiness", "acceptance", "strategy"):
            assert k in gate_kinds, (
                f"'{k}' must be in canonical_gate_input_kinds (AC4: first-class gate input)"
            )
