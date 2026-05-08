from core.joint_dual_repo_cognition_closure_review import (
    JOINT_COGNITION_CLOSURE_AUTHORITY,
    JOINT_COGNITION_CLOSURE_METHODOLOGY,
    ClosureBoundary,
    GapType,
    JointCognitionClosureReport,
    PropositionVerdict,
    SystemStage,
    WorkPriority,
    build_joint_dual_repo_cognition_closure_review,
)


def test_authority_and_methodology_present() -> None:
    assert "JOINT_DUAL_REPO_COGNITION_CLOSURE_REVIEW" in JOINT_COGNITION_CLOSURE_AUTHORITY
    assert "PR #993" in JOINT_COGNITION_CLOSURE_METHODOLOGY


def test_build_report_has_8_system_propositions() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    assert isinstance(report, JointCognitionClosureReport)
    assert len(report.propositions) == 8


def test_all_required_proposition_ids_present() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    ids = {p.proposition_id for p in report.propositions}
    assert ids == {
        "P1_unique_center_governance_kernel",
        "P2_android_strong_runtime_node",
        "P3_execution_governance_unified_semantics",
        "P4_multimodal_main_chain_closure",
        "P5_capability_authority_readiness_policy",
        "P6_mesh_collaboration_multi_device_runtime",
        "P7_autonomy_boundary_clarity",
        "P8_remaining_primary_axes",
    }


def test_non_closed_propositions_must_expose_constraints() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    for item in report.propositions:
        if item.boundary in {
            ClosureBoundary.PARTIAL,
            ClosureBoundary.CONSTRAINED,
            ClosureBoundary.DEFERRED,
        }:
            assert item.verdict in {
                PropositionVerdict.PARTIAL,
                PropositionVerdict.NOT_ESTABLISHED,
                PropositionVerdict.OVERESTIMATED,
            }


def test_mesh_proposition_explicitly_constrained() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    mesh = next(
        (p for p in report.propositions if p.proposition_id == "P6_mesh_collaboration_multi_device_runtime"),
        None,
    )
    assert mesh is not None
    assert mesh.boundary == ClosureBoundary.CONSTRAINED
    assert mesh.verdict == PropositionVerdict.PARTIAL
    assert (
        "full_mesh_runtime_execution_deferred_until_hybrid_execute_full_is_available"
        in mesh.constrained_or_deferred
    )
    assert (
        "barrier_coordination_deferred_until_cross_repo_runtime_contract_is_closed"
        in mesh.constrained_or_deferred
    )


def test_to_dict_is_json_ready() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    payload = report.to_dict()
    assert payload["authority"] == JOINT_COGNITION_CLOSURE_AUTHORITY
    assert len(payload["propositions"]) == 8
    assert payload["overall_completion_pct"] > 0.0
    assert payload["current_stage"] in {stage.value for stage in SystemStage}


def test_domain_scorecard_integrity() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    assert len(report.domain_scores) == 8
    assert sum(item.weight_pct for item in report.domain_scores) == 100.0
    for item in report.domain_scores:
        assert 0.0 <= item.completion_pct <= 100.0


def test_overall_completion_is_weighted_average() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    weighted = round(
        sum(item.weight_pct * item.completion_pct for item in report.domain_scores) / 100.0,
        1,
    )
    assert report.overall_completion_pct == weighted
    assert report.current_stage == SystemStage.MID_STAGE_CONSOLIDATION


def test_remaining_work_is_classified_and_prioritized() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    assert len(report.remaining_work) >= 5
    priorities = {item.priority for item in report.remaining_work}
    assert WorkPriority.MUST_DO in priorities
    assert WorkPriority.IMPORTANT_SECONDARY in priorities
    assert WorkPriority.ENHANCEMENT in priorities
    for item in report.remaining_work:
        assert item.gap_type in set(GapType)
        assert item.blocking_propositions
        assert item.evidence_anchors
