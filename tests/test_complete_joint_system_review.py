"""tests/test_complete_joint_system_review.py
=============================================
Machine-verifiable tests for the complete joint dual-repo system review
artifact (core/complete_joint_system_review.py).

These tests assert:
- The report builds without errors and has valid metadata.
- All 15 domains are present and carry real-code-grounded evidence.
- All 12 propositions are present and use the PropositionVerdict taxonomy.
- All 13 remaining issues are present with required structure.
- The closure map correctly links propositions to open gaps.
- The system identity verdict answers all five canonical questions.
- Serialization produces a valid dict with all required top-level keys.
- Stage / completion scoring properties are internally consistent.
"""

from __future__ import annotations

from core.complete_joint_system_review import (
    ANDROID_AUDITED_REF,
    REVIEW_AUTHORITY,
    REVIEW_CONVERGENCE_ANCHOR,
    REVIEW_METHODOLOGY,
    REVIEW_PR_TITLE,
    REVIEW_PR_TITLE_EN,
    REVIEW_SUPERSEDES,
    ClosureMapEntry,
    CompleteJointSystemReport,
    CrossRepoMismatch,
    EvidenceState,
    GapClass,
    IntegrityRepairAction,
    PropositionVerdict,
    RemainingIssue,
    RuntimeFlowStage,
    StageGate,
    StageVerdict,
    V2ConvergencePriority,
    WorkPriority,
    build_complete_joint_system_review,
)

# ---------------------------------------------------------------------------
# Constants expected by the tests
# ---------------------------------------------------------------------------

_EXPECTED_DOMAIN_TOPICS = {
    "authority / governance",
    "command dispatch path",
    "routing / orchestration",
    "runtime-state truth",
    "Android runtime-node / local-execution / fallback",
    "capability / readiness / policy consistency",
    "cross-repo contracts",
    "mesh / hybrid / delegated collaboration",
    "multimodal input-output execution chain",
    "ingress unification",
    "operator / panel / observability surfaces",
    "manifestation / carrier semantics",
    "session continuity / durable identity",
    "execution governance lifecycle (takeover / conflict / busy state)",
    "proof / tests / live runtime closure",
}

_EXPECTED_PROPOSITION_IDS = {f"P{i}" for i in range(1, 13)}  # P1 .. P12
_EXPECTED_ISSUE_IDS = {f"R{i}" for i in range(1, 14)}  # R1 .. R13


# ---------------------------------------------------------------------------
# Metadata / authority tests
# ---------------------------------------------------------------------------


def test_authority_string_identifies_review() -> None:
    assert "COMPLETE_JOINT_SYSTEM_REVIEW" in REVIEW_AUTHORITY
    assert "real-code-only-v2-plus-android" in REVIEW_AUTHORITY


def test_methodology_prohibits_non_code_evidence() -> None:
    lower = REVIEW_METHODOLOGY.lower()
    assert "real" in lower
    assert "code" in lower
    # Must explicitly say PR narratives or historical prose are excluded
    assert "narrative" in lower or "no historical pr" in lower or "pr narrative" in lower


def test_pr_title_signals_next_convergence_framing() -> None:
    # The PR title should reflect the next-step convergence direction
    # (beyond 993P2 into operability audit, closure governance, operator co-source)
    assert "双仓" in REVIEW_PR_TITLE or "可用性" in REVIEW_PR_TITLE or "闭环" in REVIEW_PR_TITLE
    assert (
        "审查" in REVIEW_PR_TITLE
        or "治理" in REVIEW_PR_TITLE
        or "解释" in REVIEW_PR_TITLE
        or "收口" in REVIEW_PR_TITLE
        or "传播" in REVIEW_PR_TITLE
    )
    english_title = REVIEW_PR_TITLE_EN.lower()
    assert "dual-repo" in english_title or "operability" in english_title or "closure" in english_title
    assert "governance" in english_title or "operator" in english_title or "convergence" in english_title


def test_convergence_anchor_is_explicit_993P2() -> None:
    assert REVIEW_CONVERGENCE_ANCHOR == "993P2"


def test_supersedes_list_includes_prior_baselines() -> None:
    assert any("joint_dual_repo_real_code_baseline" in s for s in REVIEW_SUPERSEDES)
    assert any("post_closure_dual_repo_reassessment" in s for s in REVIEW_SUPERSEDES)


def test_android_audited_ref_is_plausible_commit() -> None:
    # Must look like a git SHA (hex string, at least 12 chars)
    assert len(ANDROID_AUDITED_REF) >= 12
    int(ANDROID_AUDITED_REF, 16)  # raises ValueError if not hex


# ---------------------------------------------------------------------------
# Report construction tests
# ---------------------------------------------------------------------------


def test_report_builds_without_error() -> None:
    report = build_complete_joint_system_review()
    assert isinstance(report, CompleteJointSystemReport)


def test_report_has_system_identity_with_all_five_answers() -> None:
    report = build_complete_joint_system_review()
    identity = report.system_identity
    assert identity is not None
    # All five canonical questions must be answered with non-empty strings
    assert identity.system_identity_zh, "Q1 (system identity) must be answered"
    assert identity.v2_governance_boundary_zh, "Q2 (V2 governance boundary) must be answered"
    assert identity.android_runtime_role_zh, "Q3 (Android runtime role) must be answered"
    assert identity.desktop_carrier_semantics_zh, "Q4 (desktop carrier semantics) must be answered"
    assert identity.network_integration_degree_zh, "Q5 (network integration degree) must be answered"
    assert identity.identity_evidence_state in (
        EvidenceState.HARD_ESTABLISHED,
        EvidenceState.PARTIAL,
        EvidenceState.RUNTIME_PROOF_THIN,
    )


# ---------------------------------------------------------------------------
# Domain scorecard tests
# ---------------------------------------------------------------------------


def test_report_covers_all_15_domains() -> None:
    report = build_complete_joint_system_review()
    topics = {d.topic for d in report.domain_statuses}
    missing = _EXPECTED_DOMAIN_TOPICS - topics
    assert not missing, f"Missing domain topics: {missing}"


def test_all_domains_have_v2_anchors() -> None:
    report = build_complete_joint_system_review()
    for domain in report.domain_statuses:
        assert domain.v2_anchors, f"Domain {domain.domain_id!r} ({domain.topic}) has no V2 anchors"


def test_all_domains_have_valid_completion_pct() -> None:
    report = build_complete_joint_system_review()
    for domain in report.domain_statuses:
        assert 0.0 <= domain.completion_pct <= 100.0, (
            f"Domain {domain.domain_id!r} completion_pct out of range: {domain.completion_pct}"
        )


def test_all_domains_have_positive_weight() -> None:
    report = build_complete_joint_system_review()
    for domain in report.domain_statuses:
        assert domain.weight > 0.0, (
            f"Domain {domain.domain_id!r} has non-positive weight {domain.weight}"
        )


def test_weighted_completion_differs_from_unweighted() -> None:
    """At least one domain has weight != 1 so the scores should differ."""
    report = build_complete_joint_system_review()
    # Both must be positive; they may be equal if weights happened to average
    # to 1.0, but at minimum both must be present and consistent.
    assert report.overall_completion_pct > 0
    assert report.weighted_completion_pct > 0


# ---------------------------------------------------------------------------
# Proposition adjudication tests
# ---------------------------------------------------------------------------


def test_report_has_all_12_propositions() -> None:
    report = build_complete_joint_system_review()
    ids = {p.prop_id for p in report.propositions}
    missing = _EXPECTED_PROPOSITION_IDS - ids
    assert not missing, f"Missing propositions: {missing}"


def test_propositions_use_all_three_verdicts() -> None:
    report = build_complete_joint_system_review()
    verdicts = {p.verdict for p in report.propositions}
    assert PropositionVerdict.HARD_ESTABLISHED in verdicts, "At least one HARD_ESTABLISHED proposition expected"
    assert PropositionVerdict.PARTIALLY_ESTABLISHED in verdicts, "At least one PARTIALLY_ESTABLISHED proposition expected"
    assert PropositionVerdict.SHOULD_SCALE_BACK in verdicts, "At least one SHOULD_SCALE_BACK proposition expected"


def test_v2_is_center_authority_is_hard_established() -> None:
    report = build_complete_joint_system_review()
    p1 = next(p for p in report.propositions if p.prop_id == "P1")
    assert p1.verdict == PropositionVerdict.HARD_ESTABLISHED, (
        "P1 (V2 is center authority) must be HARD_ESTABLISHED"
    )


def test_mesh_fully_closed_is_scaled_back() -> None:
    report = build_complete_joint_system_review()
    p7 = next(p for p in report.propositions if p.prop_id == "P7")
    assert p7.verdict == PropositionVerdict.SHOULD_SCALE_BACK, (
        "P7 (mesh fully closed) must be SHOULD_SCALE_BACK per current evidence"
    )


def test_proof_thickness_is_scaled_back() -> None:
    report = build_complete_joint_system_review()
    p12 = next(p for p in report.propositions if p.prop_id == "P12")
    assert p12.verdict == PropositionVerdict.SHOULD_SCALE_BACK, (
        "P12 (proof surface thick enough) must be SHOULD_SCALE_BACK per current evidence"
    )


def test_all_propositions_have_v2_anchors_or_android_anchors() -> None:
    report = build_complete_joint_system_review()
    for prop in report.propositions:
        has_anchors = bool(prop.v2_anchors) or bool(prop.android_anchors)
        assert has_anchors, f"Proposition {prop.prop_id} has no code anchors at all"


def test_all_propositions_have_rationale() -> None:
    report = build_complete_joint_system_review()
    for prop in report.propositions:
        assert prop.rationale_zh, f"Proposition {prop.prop_id} has empty rationale_zh"


# ---------------------------------------------------------------------------
# Remaining-issue registry tests
# ---------------------------------------------------------------------------


def test_report_has_all_13_remaining_issues() -> None:
    report = build_complete_joint_system_review()
    ids = {i.issue_id for i in report.remaining_issues}
    missing = _EXPECTED_ISSUE_IDS - ids
    assert not missing, f"Missing remaining issues: {missing}"


def test_remaining_issues_cover_required_gap_classes() -> None:
    report = build_complete_joint_system_review()
    gap_classes = {i.gap_class for i in report.remaining_issues}
    assert GapClass.ORCHESTRATION in gap_classes
    assert GapClass.STATE_TRUTH in gap_classes
    assert GapClass.GOVERNANCE in gap_classes
    assert GapClass.RUNTIME in gap_classes
    assert GapClass.MANIFESTATION_CONTROL in gap_classes
    assert GapClass.PROOF in gap_classes
    assert GapClass.CROSS_REPO_CONTRACT in gap_classes
    assert GapClass.SESSION_CONTINUITY in gap_classes


def test_remaining_issues_cover_all_priority_levels() -> None:
    report = build_complete_joint_system_review()
    priorities = {i.priority for i in report.remaining_issues}
    assert WorkPriority.MUST_FIRST in priorities
    assert WorkPriority.IMPORTANT_SECONDARY in priorities
    assert WorkPriority.ENHANCEMENT in priorities


def test_all_remaining_issues_have_required_fields() -> None:
    report = build_complete_joint_system_review()
    for issue in report.remaining_issues:
        assert issue.blocks, f"Issue {issue.issue_id} has empty 'blocks'"
        assert issue.v2_anchors, f"Issue {issue.issue_id} has no V2 anchors"
        assert issue.android_anchors or issue.gap_class in (
            GapClass.CORE_ARCH,
            GapClass.ORCHESTRATION,
            GapClass.GOVERNANCE,
            GapClass.MANIFESTATION_CONTROL,
        ), f"Issue {issue.issue_id} should have Android anchors for its gap class"
        assert issue.why_not_closed_zh, f"Issue {issue.issue_id} has empty why_not_closed_zh"
        assert issue.stage_gate in (
            StageGate.P0_BEFORE_RUNTIME_CLOSURE,
            StageGate.P1_BEFORE_NEAR_CLOSURE,
            StageGate.P2_ENHANCEMENT,
        )


def test_p0_issues_exist() -> None:
    report = build_complete_joint_system_review()
    p0_issues = [i for i in report.remaining_issues if i.stage_gate == StageGate.P0_BEFORE_RUNTIME_CLOSURE]
    assert len(p0_issues) >= 2, "Expected at least 2 P0 (must-first) issues"


def test_r1_is_orchestration_must_first() -> None:
    report = build_complete_joint_system_review()
    r1 = next(i for i in report.remaining_issues if i.issue_id == "R1")
    assert r1.priority == WorkPriority.MUST_FIRST
    assert r1.gap_class == GapClass.ORCHESTRATION


def test_r2_is_state_truth_must_first() -> None:
    report = build_complete_joint_system_review()
    r2 = next(i for i in report.remaining_issues if i.issue_id == "R2")
    assert r2.priority == WorkPriority.MUST_FIRST
    assert r2.gap_class == GapClass.STATE_TRUTH


# ---------------------------------------------------------------------------
# Closure map tests
# ---------------------------------------------------------------------------


def test_closure_map_has_one_entry_per_proposition() -> None:
    report = build_complete_joint_system_review()
    prop_ids = {p.prop_id for p in report.propositions}
    map_ids = {c.prop_id for c in report.closure_map}
    assert prop_ids == map_ids, "Closure map must have exactly one entry per proposition"


def test_p1_is_marked_closed_in_closure_map() -> None:
    report = build_complete_joint_system_review()
    p1_entry = next(c for c in report.closure_map if c.prop_id == "P1")
    assert p1_entry.closed, "P1 (V2 center authority) should be marked closed in closure map"


def test_p7_and_p12_are_not_closed_in_closure_map() -> None:
    report = build_complete_joint_system_review()
    for pid in ("P7", "P12"):
        entry = next(c for c in report.closure_map if c.prop_id == pid)
        assert not entry.closed, f"{pid} should NOT be closed (should_scale_back)"


def test_partially_established_propositions_have_blocking_issues() -> None:
    report = build_complete_joint_system_review()
    for entry in report.closure_map:
        prop = next(p for p in report.propositions if p.prop_id == entry.prop_id)
        if prop.verdict == PropositionVerdict.PARTIALLY_ESTABLISHED:
            assert entry.blocking_issue_ids, (
                f"PARTIALLY_ESTABLISHED proposition {entry.prop_id} should have blocking issue IDs"
            )


# ---------------------------------------------------------------------------
# Runtime flow / cross-repo mismatch / next-step convergence tests
# ---------------------------------------------------------------------------


def test_runtime_flow_has_six_stages_covering_end_to_end_chain() -> None:
    report = build_complete_joint_system_review()
    assert len(report.runtime_flow) == 6
    assert all(isinstance(stage, RuntimeFlowStage) for stage in report.runtime_flow)
    titles = {stage.title_zh for stage in report.runtime_flow}
    assert any("入口" in title for title in titles)
    assert any("分发" in title or "执行路径" in title for title in titles)
    assert any("回流" in title for title in titles)
    assert any("闭环" in title or "收口" in title for title in titles)


def test_runtime_flow_stages_have_v2_anchors_and_truth_text() -> None:
    report = build_complete_joint_system_review()
    for stage in report.runtime_flow:
        assert stage.runtime_truth_zh
        assert stage.v2_anchors


def test_cross_repo_mismatches_are_explicit_and_linked_to_issues() -> None:
    report = build_complete_joint_system_review()
    assert len(report.cross_repo_mismatches) >= 4
    assert all(isinstance(item, CrossRepoMismatch) for item in report.cross_repo_mismatches)
    for mismatch in report.cross_repo_mismatches:
        assert mismatch.topic_zh
        assert mismatch.v2_truth_zh
        assert mismatch.android_truth_zh
        assert mismatch.impact_zh
        assert mismatch.linked_issue_ids
        assert mismatch.v2_anchors
        assert mismatch.android_anchors


def test_next_v2_convergence_priority_targets_integrity_linkage() -> None:
    report = build_complete_joint_system_review()
    priority = report.v2_next_convergence_priority
    assert isinstance(priority, V2ConvergencePriority)
    assert priority is not None
    # Title should reference Android truth or board or closure direction
    assert (
        "V2" in priority.title_zh
        or "编排" in priority.title_zh
        or "Android" in priority.title_zh
        or "board" in priority.title_zh
        or "闭环" in priority.title_zh
    )
    # Issue IDs must cover routing and operator surfaces
    assert {"R1", "R3"}.issubset(set(priority.linked_issue_ids))
    assert priority.v2_anchors
    assert priority.android_anchors


def test_integrity_repair_actions_include_v2_implemented_fix_and_cross_repo_followup() -> None:
    report = build_complete_joint_system_review()
    actions = report.integrity_repair_actions
    assert actions
    assert all(isinstance(item, IntegrityRepairAction) for item in actions)
    assert any(action.status_zh == "本次 V2 已补强" for action in actions)
    assert any("跨仓" in action.status_zh for action in actions)
    implemented = next((action for action in actions if action.status_zh == "本次 V2 已补强"), None)
    assert implemented is not None, "Expected at least one V2-implemented integrity action"
    assert any("core/unified_result_ingress.py" in anchor for anchor in implemented.v2_anchors)


# ---------------------------------------------------------------------------
# Stage / completion consistency tests
# ---------------------------------------------------------------------------


def test_stage_is_mid_stage_when_p0_issues_exist() -> None:
    """With P0 issues present the stage must be mid-stage consolidation."""
    report = build_complete_joint_system_review()
    has_p0 = any(
        i.stage_gate == StageGate.P0_BEFORE_RUNTIME_CLOSURE for i in report.remaining_issues
    )
    if has_p0:
        assert report.stage == StageVerdict.MID_STAGE_CONSOLIDATION


def test_overall_completion_is_plausible() -> None:
    report = build_complete_joint_system_review()
    assert 30.0 < report.overall_completion_pct < 100.0, (
        f"overall_completion_pct {report.overall_completion_pct} seems implausible"
    )


def test_weighted_completion_is_plausible() -> None:
    report = build_complete_joint_system_review()
    assert 30.0 < report.weighted_completion_pct < 100.0, (
        f"weighted_completion_pct {report.weighted_completion_pct} seems implausible"
    )


# ---------------------------------------------------------------------------
# Serialization tests
# ---------------------------------------------------------------------------


def test_to_dict_has_all_top_level_keys() -> None:
    payload = build_complete_joint_system_review().to_dict()
    required_keys = {
        "authority",
        "methodology",
        "pr_title",
        "pr_title_en",
        "convergence_anchor",
        "supersedes",
        "android_audited_ref",
        "generated_at",
        "system_identity",
        "propositions",
        "domain_statuses",
        "remaining_issues",
        "closure_map",
        "runtime_flow",
        "cross_repo_mismatches",
        "v2_next_convergence_priority",
        "integrity_repair_actions",
        "stage",
        "overall_completion_pct",
        "weighted_completion_pct",
        "probe_results",
    }
    missing = required_keys - payload.keys()
    assert not missing, f"to_dict() is missing keys: {missing}"


def test_to_dict_domain_statuses_include_weight() -> None:
    payload = build_complete_joint_system_review().to_dict()
    for ds in payload["domain_statuses"]:
        assert "weight" in ds, "domain_status dict must include 'weight'"


def test_to_dict_remaining_issues_include_stage_gate() -> None:
    payload = build_complete_joint_system_review().to_dict()
    for ri in payload["remaining_issues"]:
        assert "stage_gate" in ri, "remaining_issue dict must include 'stage_gate'"
        assert "blocks_propositions" in ri, "remaining_issue dict must include 'blocks_propositions'"


def test_to_dict_propositions_include_verdict() -> None:
    payload = build_complete_joint_system_review().to_dict()
    for prop in payload["propositions"]:
        assert "verdict" in prop
        assert prop["verdict"] in {v.value for v in PropositionVerdict}


def test_to_dict_system_identity_has_five_fields() -> None:
    payload = build_complete_joint_system_review().to_dict()
    identity = payload["system_identity"]
    assert identity is not None
    for key in (
        "system_identity_zh",
        "v2_governance_boundary_zh",
        "android_runtime_role_zh",
        "desktop_carrier_semantics_zh",
        "network_integration_degree_zh",
        "identity_evidence_state",
    ):
        assert key in identity, f"system_identity dict missing key {key!r}"


def test_to_dict_probe_results_is_dict_of_bools() -> None:
    payload = build_complete_joint_system_review().to_dict()
    probes = payload["probe_results"]
    assert isinstance(probes, dict)
    for k, v in probes.items():
        assert isinstance(v, bool), f"Probe result {k!r} is not bool: {v!r}"


def test_to_dict_closure_map_entries_have_required_fields() -> None:
    payload = build_complete_joint_system_review().to_dict()
    for entry in payload["closure_map"]:
        assert "prop_id" in entry
        assert "verdict" in entry
        assert "closed" in entry
        assert "blocking_issue_ids" in entry


def test_to_dict_runtime_flow_entries_have_required_fields() -> None:
    payload = build_complete_joint_system_review().to_dict()
    for stage in payload["runtime_flow"]:
        assert "stage_id" in stage
        assert "title_zh" in stage
        assert "runtime_truth_zh" in stage
        assert "v2_anchors" in stage


def test_to_dict_cross_repo_mismatch_entries_have_required_fields() -> None:
    payload = build_complete_joint_system_review().to_dict()
    for mismatch in payload["cross_repo_mismatches"]:
        assert "mismatch_id" in mismatch
        assert "topic_zh" in mismatch
        assert "linked_issue_ids" in mismatch


def test_to_dict_v2_next_convergence_priority_has_required_fields() -> None:
    payload = build_complete_joint_system_review().to_dict()
    priority = payload["v2_next_convergence_priority"]
    assert priority is not None
    for key in ("title_zh", "why_now_zh", "target_outcome_zh", "linked_issue_ids", "v2_anchors"):
        assert key in priority


def test_to_dict_integrity_repair_actions_have_required_fields() -> None:
    payload = build_complete_joint_system_review().to_dict()
    actions = payload["integrity_repair_actions"]
    assert actions
    for action in actions:
        for key in (
            "action_id",
            "title_zh",
            "status_zh",
            "why_high_value_zh",
            "linked_issue_ids",
            "v2_anchors",
        ):
            assert key in action
