from core.joint_dual_repo_cognition_closure_review import (
    JOINT_COGNITION_CLOSURE_AUTHORITY,
    JOINT_COGNITION_CLOSURE_METHODOLOGY,
    ClosureBoundary,
    JointCognitionClosureReport,
    PropositionVerdict,
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
    mesh = next(p for p in report.propositions if p.proposition_id == "P6_mesh_collaboration_multi_device_runtime")
    assert mesh.boundary == ClosureBoundary.CONSTRAINED
    assert mesh.verdict == PropositionVerdict.PARTIAL
    assert any("deferred" in s for s in mesh.constrained_or_deferred)


def test_to_dict_is_json_ready() -> None:
    report = build_joint_dual_repo_cognition_closure_review()
    payload = report.to_dict()
    assert payload["authority"] == JOINT_COGNITION_CLOSURE_AUTHORITY
    assert len(payload["propositions"]) == 8
