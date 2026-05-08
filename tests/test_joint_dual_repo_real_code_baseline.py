from core.joint_dual_repo_real_code_baseline import (
    ANDROID_AUDITED_REF,
    GapClass,
    JOINT_BASELINE_AUTHORITY,
    JOINT_BASELINE_METHOD,
    JOINT_BASELINE_PR_TITLE,
    JointRealCodeBaselineReport,
    WorkPriority,
    build_joint_dual_repo_real_code_baseline,
)


def test_baseline_metadata_present() -> None:
    assert "JOINT_DUAL_REPO_REAL_CODE_BASELINE" in JOINT_BASELINE_AUTHORITY
    assert "Only current real code is used as evidence." in JOINT_BASELINE_METHOD
    assert len(ANDROID_AUDITED_REF) >= 12


def test_pr_title_focuses_on_joint_real_code_review() -> None:
    title = JOINT_BASELINE_PR_TITLE.lower()
    assert "joint dual-repo" in title
    assert "real-code" in title
    assert "remaining-gap" in title


def test_report_builds_with_required_domain_coverage() -> None:
    report = build_joint_dual_repo_real_code_baseline()
    assert isinstance(report, JointRealCodeBaselineReport)

    topics = {item.topic for item in report.domain_statuses}
    assert "authority / governance" in topics
    assert "execution runtime" in topics
    assert "routing / orchestration" in topics
    assert "runtime-state truth" in topics
    assert "Android runtime-node strength" in topics
    assert "capability / readiness / policy consistency" in topics
    assert "mesh / hybrid / delegated collaboration" in topics
    assert "multimodal chain" in topics
    assert "ingress unification" in topics
    assert "operator / panel / observability / manifestation surfaces" in topics
    assert "proof / tests / live runtime closure" in topics


def test_remaining_issues_are_structured_and_prioritized() -> None:
    report = build_joint_dual_repo_real_code_baseline()
    assert len(report.remaining_issues) >= 6

    priorities = {item.priority for item in report.remaining_issues}
    assert WorkPriority.MUST_FIRST in priorities
    assert WorkPriority.IMPORTANT_SECONDARY in priorities

    categories = {item.gap_class for item in report.remaining_issues}
    assert GapClass.ORCHESTRATION in categories
    assert GapClass.STATE_TRUTH in categories
    assert GapClass.GOVERNANCE in categories
    assert GapClass.RUNTIME in categories
    assert GapClass.MANIFESTATION_CONTROL in categories
    assert GapClass.PROOF in categories

    for item in report.remaining_issues:
        assert item.blocks
        assert item.v2_anchors
        assert item.android_anchors


def test_report_serialization_contains_core_fields() -> None:
    payload = build_joint_dual_repo_real_code_baseline().to_dict()
    assert payload["pr_title"] == JOINT_BASELINE_PR_TITLE
    assert payload["android_audited_ref"] == ANDROID_AUDITED_REF
    assert payload["overall_completion_pct"] > 0
    assert payload["domain_statuses"]
    assert payload["remaining_issues"]
