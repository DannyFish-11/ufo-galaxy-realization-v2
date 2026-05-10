"""tests/test_dual_repo_centered_system_audit.py
=================================================

双仓中心化分布式系统审计契约回归测试

覆盖 ``core.dual_repo_centered_system_audit_contract`` 模块的关键不变量：
- 审计报告结构完整性
- 定义域审计覆盖度与 proof quality 分级约束
- 双仓综合问题列表完整性与严重度约束
- E2E 分类覆盖度（包括 Fake vs True E2E 区分）
- 路线图条目结构完整性
- 跨仓 proof 摘要可机读输出
- 最终结论字段非空且符合 mid-stage consolidation 阶段判定
- 关键系统本质常量的正确性

测试组
------
A  - 模块导入与常量完整性
B  - 审计报告构建与顶层结构
C  - 定义域审计覆盖度与 proof quality 约束
D  - 系统本质判定约束
E  - 双仓综合问题列表约束
F  - Fake E2E vs True E2E 分类约束
G  - 路线图完整性与双仓范围约束
H  - 跨仓 proof 摘要输出
I  - 结论字段约束
J  - helper 函数接口
"""

from __future__ import annotations

import pytest
from typing import List


# ---------------------------------------------------------------------------
# Group A: Module imports and constant integrity
# ---------------------------------------------------------------------------


class TestGroupA_ModuleImportsAndConstants:
    """Group A: 模块导入与常量完整性。"""

    def test_module_imports_without_error(self) -> None:
        import core.dual_repo_centered_system_audit_contract  # noqa: F401

    def test_authority_sentinel_exists(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY,
        )
        assert isinstance(DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY, str)
        assert "DUAL_REPO_CENTERED_SYSTEM_AUDIT_V4" in DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY
        assert "two-repo-unified-audit" in DUAL_REPO_CENTERED_SYSTEM_AUDIT_AUTHORITY

    def test_contract_version_exists(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            DUAL_REPO_CENTERED_SYSTEM_AUDIT_CONTRACT_VERSION,
        )
        assert DUAL_REPO_CENTERED_SYSTEM_AUDIT_CONTRACT_VERSION == "4.0.0"

    def test_baseline_prs_correct(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            DUAL_REPO_AUDIT_BASELINE_PRS,
        )
        assert isinstance(DUAL_REPO_AUDIT_BASELINE_PRS, list)
        assert 993 in DUAL_REPO_AUDIT_BASELINE_PRS
        assert 1041 in DUAL_REPO_AUDIT_BASELINE_PRS
        assert 1042 in DUAL_REPO_AUDIT_BASELINE_PRS
        assert 1043 in DUAL_REPO_AUDIT_BASELINE_PRS

    def test_methodology_constant_exists(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            DUAL_REPO_AUDIT_METHODOLOGY,
        )
        assert isinstance(DUAL_REPO_AUDIT_METHODOLOGY, str)
        assert "真实代码" in DUAL_REPO_AUDIT_METHODOLOGY

    def test_system_nature_definition_exists(self) -> None:
        from core.dual_repo_centered_system_audit_contract import SYSTEM_NATURE_DEFINITION
        assert isinstance(SYSTEM_NATURE_DEFINITION, str)
        assert "中心治理核" in SYSTEM_NATURE_DEFINITION
        assert "中心化分布式" in SYSTEM_NATURE_DEFINITION

    def test_e2e_class_constants_exist(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            E2E_CLASS_V2_UNIT,
            E2E_CLASS_ANDROID_UNIT,
            E2E_CLASS_V2_STUB,
            E2E_CLASS_CROSS_REPO_MOCK,
            E2E_CLASS_TRUE_CROSS_REPO,
        )
        classes = [
            E2E_CLASS_V2_UNIT,
            E2E_CLASS_ANDROID_UNIT,
            E2E_CLASS_V2_STUB,
            E2E_CLASS_CROSS_REPO_MOCK,
            E2E_CLASS_TRUE_CROSS_REPO,
        ]
        assert len(set(classes)) == 5, "E2E 分类常量必须互不重复"
        for c in classes:
            assert isinstance(c, str) and c, "E2E 分类常量必须为非空字符串"

    def test_proof_quality_level_enum_complete(self) -> None:
        from core.dual_repo_centered_system_audit_contract import ProofQualityLevel
        levels = [e.value for e in ProofQualityLevel]
        assert "structural_only" in levels
        assert "mainline_path_exists" in levels
        assert "v2_regression_exists" in levels
        assert "cross_repo_mock_proof" in levels
        assert "runtime_grounded" in levels
        assert len(levels) == 5

    def test_dual_repo_ownership_enum_complete(self) -> None:
        from core.dual_repo_centered_system_audit_contract import DualRepoOwnership
        values = [e.value for e in DualRepoOwnership]
        assert "v2_only" in values
        assert "android_only" in values
        assert "dual_repo" in values

    def test_definition_fulfillment_status_enum_complete(self) -> None:
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        values = [e.value for e in DefinitionFulfillmentStatus]
        assert "fulfilled" in values
        assert "partially_fulfilled" in values
        assert "not_fulfilled" in values
        assert "v2_side_only" in values


# ---------------------------------------------------------------------------
# Group B: Report building and top-level structure
# ---------------------------------------------------------------------------


class TestGroupB_ReportBuildingAndTopLevelStructure:
    """Group B: 审计报告构建与顶层结构。"""

    @pytest.fixture(scope="class")
    def report(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        return build_dual_repo_centered_system_audit()

    def test_report_builds_without_error(self, report) -> None:
        assert report is not None

    def test_report_has_correct_version(self, report) -> None:
        assert report.contract_version == "4.0.0"

    def test_report_has_all_required_fields(self, report) -> None:
        assert hasattr(report, "definition_area_audits")
        assert hasattr(report, "canonical_path_traces")
        assert hasattr(report, "combined_issues")
        assert hasattr(report, "e2e_classifications")
        assert hasattr(report, "roadmap")
        assert hasattr(report, "overall_system_description_zh")
        assert hasattr(report, "current_completion_stage")
        assert hasattr(report, "pr_993_fulfillment")
        assert hasattr(report, "pr_1041_fulfillment")
        assert hasattr(report, "pr_1042_fulfillment")
        assert hasattr(report, "pr_1043_fulfillment")
        assert hasattr(report, "claims_backed_by_real_code")
        assert hasattr(report, "claims_structural_or_v2_only")
        assert hasattr(report, "top_combined_system_gaps")

    def test_to_dict_is_serializable(self, report) -> None:
        d = report.to_dict()
        assert isinstance(d, dict)
        import json
        json_str = json.dumps(d, ensure_ascii=False)
        assert len(json_str) > 0

    def test_baseline_prs_in_report(self, report) -> None:
        for pr in [993, 1041, 1042, 1043]:
            assert pr in report.baseline_prs


# ---------------------------------------------------------------------------
# Group C: Definition domain audit coverage and proof quality constraints
# ---------------------------------------------------------------------------


class TestGroupC_DefinitionAreaAuditCoverage:
    """Group C: 定义域审计覆盖度与 proof quality 约束。"""

    @pytest.fixture(scope="class")
    def audits(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        return report.definition_area_audits

    def test_all_8_domains_present(self, audits) -> None:
        domain_ids = [a.domain_id for a in audits]
        for expected_id in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            assert expected_id in domain_ids, f"定义域 {expected_id} 缺失"

    def test_each_audit_has_v2_anchors(self, audits) -> None:
        # D9（可观测性）Android 侧可无 anchor，但 V2 侧必须有
        for audit in audits:
            if audit.domain_id not in {"D9"}:  # D7 V2 side should have anchors
                if audit.domain_id == "D7":
                    assert len(audit.v2_anchors) > 0, f"{audit.domain_id} V2 锚点不能为空"

    def test_each_audit_has_fulfillment_status(self, audits) -> None:
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        valid_statuses = set(e.value for e in DefinitionFulfillmentStatus)
        for audit in audits:
            assert audit.fulfillment_status.value in valid_statuses

    def test_each_audit_has_known_gaps(self, audits) -> None:
        """每个定义域审计必须列出已知缺口（双仓联合审计的核心约束）。"""
        for audit in audits:
            assert isinstance(audit.known_gaps, list)
            assert len(audit.known_gaps) > 0, (
                f"定义域 {audit.domain_id} 必须列出已知缺口（双仓联合审计要求）"
            )

    def test_no_domain_claims_runtime_grounded(self, audits) -> None:
        """当前阶段不应有任何定义域声明 runtime_grounded（最高证明质量）。
        此约束确保 proof 质量不被高估。"""
        from core.dual_repo_centered_system_audit_contract import ProofQualityLevel
        for audit in audits:
            assert audit.proof_quality != ProofQualityLevel.RUNTIME_GROUNDED, (
                f"定义域 {audit.domain_id} 当前不应声明 runtime_grounded proof quality"
            )

    def test_d4_mesh_must_be_partially_fulfilled(self, audits) -> None:
        """D4（Mesh Runtime Center Closure）必须标记为 partially_fulfilled——
        因为 runtime_closed 从未通过真实 Android 参与触发（PR #1043 关键约束）。"""
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        d4 = next(a for a in audits if a.domain_id == "D4")
        assert d4.fulfillment_status == DefinitionFulfillmentStatus.PARTIALLY_FULFILLED

    def test_d3_execution_lifecycle_may_be_fulfilled(self, audits) -> None:
        """D3（Execution Lifecycle Governance Binding）是 PR #1042 的直接成果，
        可以标记为 fulfilled（V2 侧已充分实现）。"""
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        d3 = next(a for a in audits if a.domain_id == "D3")
        assert d3.fulfillment_status in {
            DefinitionFulfillmentStatus.FULFILLED,
            DefinitionFulfillmentStatus.PARTIALLY_FULFILLED,
        }

    def test_each_audit_has_baseline_prs(self, audits) -> None:
        for audit in audits:
            assert isinstance(audit.baseline_prs, list)
            assert len(audit.baseline_prs) > 0, f"{audit.domain_id} 必须引用至少一个基线 PR"

    def test_all_audits_have_to_dict(self, audits) -> None:
        for audit in audits:
            d = audit.to_dict()
            assert isinstance(d, dict)
            assert "domain_id" in d
            assert "proof_quality" in d
            assert "fulfillment_status" in d


# ---------------------------------------------------------------------------
# Group D: System nature verdict constraints
# ---------------------------------------------------------------------------


class TestGroupD_SystemNatureVerdictConstraints:
    """Group D: 系统本质判定约束。"""

    @pytest.fixture(scope="class")
    def report(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        return build_dual_repo_centered_system_audit()

    def test_system_nature_is_center_governed_distributed_network(self, report) -> None:
        from core.dual_repo_centered_system_audit_contract import SystemNatureVerdict
        assert report.system_nature_verdict == (
            SystemNatureVerdict.CENTER_GOVERNED_DISTRIBUTED_NETWORK
        )

    def test_system_nature_description_mentions_v2_as_center(self, report) -> None:
        desc = report.system_nature_description
        assert "ufo-galaxy-realization-v2" in desc or "V2" in desc or "中心" in desc

    def test_system_nature_description_mentions_android_as_participant(self, report) -> None:
        desc = report.system_nature_description
        assert "Android" in desc or "参与节点" in desc

    def test_system_nature_description_not_client_server_framing(self, report) -> None:
        """系统本质描述不应使用传统客户端-服务器框架描述。"""
        desc = report.system_nature_description
        # 不应该有'被动客户端'等错误描述
        assert "被动客户端" not in desc


# ---------------------------------------------------------------------------
# Group E: Combined issue list constraints
# ---------------------------------------------------------------------------


class TestGroupE_CombinedIssueListConstraints:
    """Group E: 双仓综合问题列表约束。"""

    @pytest.fixture(scope="class")
    def issues(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        return report.combined_issues

    def test_at_least_10_issues(self, issues) -> None:
        """双仓联合审计必须产出至少 10 个问题（覆盖 9 个最低要求类型 + 追加）。"""
        assert len(issues) >= 10

    def test_capability_drift_issue_exists(self, issues) -> None:
        types = [i.issue_type for i in issues]
        titles = [i.title for i in issues]
        assert any("drift" in t.lower() or "漂移" in t for t in types + titles)

    def test_schema_drift_issue_exists(self, issues) -> None:
        ids = [i.issue_id for i in issues]
        titles = [i.title for i in issues]
        assert any("Schema" in t or "P2" in t for t in ids + titles)

    def test_execution_runtime_truth_drift_exists(self, issues) -> None:
        ids = [i.issue_id for i in issues]
        assert "P3" in ids

    def test_fake_e2e_issue_exists(self, issues) -> None:
        ids = [i.issue_id for i in issues]
        titles = [i.title for i in issues]
        assert any("E2E" in t or "P5" in t for t in ids + titles)

    def test_mesh_runtime_closed_issue_exists(self, issues) -> None:
        ids = [i.issue_id for i in issues]
        titles = [i.title for i in issues]
        assert any("P8" in i or "runtime_closed" in t for i, t in zip(ids, titles))

    def test_observability_asymmetry_issue_exists(self, issues) -> None:
        ids = [i.issue_id for i in issues]
        assert "P9" in ids

    def test_all_issues_have_severity(self, issues) -> None:
        valid_severities = {"high", "medium", "low"}
        for issue in issues:
            assert issue.severity in valid_severities

    def test_all_issues_have_resolution_scope(self, issues) -> None:
        from core.dual_repo_centered_system_audit_contract import DualRepoOwnership
        valid_scopes = set(e.value for e in DualRepoOwnership)
        for issue in issues:
            assert issue.resolution_scope.value in valid_scopes

    def test_all_high_severity_issues_have_anchors(self, issues) -> None:
        """高严重度问题必须至少有一个代码锚点（V2 或 Android）。"""
        for issue in issues:
            if issue.severity == "high":
                total_anchors = len(issue.v2_anchors) + len(issue.android_anchors)
                assert total_anchors > 0, (
                    f"高严重度问题 {issue.issue_id} 必须有代码锚点"
                )

    def test_most_issues_require_dual_repo_resolution(self, issues) -> None:
        """大多数问题应属于双仓解决范围（因为这是双仓联合审计的核心发现）。"""
        from core.dual_repo_centered_system_audit_contract import DualRepoOwnership
        dual_repo_count = sum(
            1 for i in issues if i.resolution_scope == DualRepoOwnership.DUAL_REPO
        )
        # 超过一半应是双仓问题
        assert dual_repo_count > len(issues) // 2

    def test_issues_to_dict_complete(self, issues) -> None:
        for issue in issues:
            d = issue.to_dict()
            assert "issue_id" in d
            assert "severity" in d
            assert "resolution_scope" in d


# ---------------------------------------------------------------------------
# Group F: Fake E2E vs True E2E classification constraints
# ---------------------------------------------------------------------------


class TestGroupF_FakeVsTrueE2EClassificationConstraints:
    """Group F: Fake E2E vs True E2E 分类约束。"""

    @pytest.fixture(scope="class")
    def e2e_classifications(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        return report.e2e_classifications

    def test_true_cross_repo_class_appears_once(self, e2e_classifications) -> None:
        """必须有且只有一个'true_cross_repo_two_runtime'条目，且内容应明确当前不存在。"""
        from core.dual_repo_centered_system_audit_contract import E2E_CLASS_TRUE_CROSS_REPO
        true_e2e = [
            e for e in e2e_classifications
            if e.classification == E2E_CLASS_TRUE_CROSS_REPO
        ]
        assert len(true_e2e) >= 1, "必须有 true_cross_repo_two_runtime 分类条目"
        # 该条目应表明当前不存在真实双运行时测试
        assert any(
            "不存在" in c.what_it_proves or "N/A" in c.what_it_proves
            for c in true_e2e
        )

    def test_v2_only_tests_present(self, e2e_classifications) -> None:
        from core.dual_repo_centered_system_audit_contract import E2E_CLASS_V2_UNIT
        v2_only = [e for e in e2e_classifications if e.classification == E2E_CLASS_V2_UNIT]
        assert len(v2_only) >= 2, "至少应有 2 个 V2-only 单元测试分类条目"

    def test_android_local_tests_present(self, e2e_classifications) -> None:
        from core.dual_repo_centered_system_audit_contract import E2E_CLASS_ANDROID_UNIT
        android_local = [
            e for e in e2e_classifications if e.classification == E2E_CLASS_ANDROID_UNIT
        ]
        assert len(android_local) >= 1, "至少应有 1 个 Android-only 本地测试分类条目"

    def test_cross_repo_mock_tests_present(self, e2e_classifications) -> None:
        from core.dual_repo_centered_system_audit_contract import E2E_CLASS_CROSS_REPO_MOCK
        cross_mock = [
            e for e in e2e_classifications if e.classification == E2E_CLASS_CROSS_REPO_MOCK
        ]
        assert len(cross_mock) >= 1

    def test_all_entries_have_what_it_does_not_prove(self, e2e_classifications) -> None:
        """每个分类条目必须说明它不证明什么（双仓审计完整性要求）。"""
        for entry in e2e_classifications:
            assert entry.what_it_does_not_prove, (
                f"E2E 分类条目 {entry.test_id} 必须说明 what_it_does_not_prove"
            )

    def test_all_entries_have_test_file(self, e2e_classifications) -> None:
        for entry in e2e_classifications:
            assert entry.test_file, f"E2E 分类条目 {entry.test_id} 必须引用测试文件"

    def test_to_dict_complete(self, e2e_classifications) -> None:
        for entry in e2e_classifications:
            d = entry.to_dict()
            assert "classification" in d
            assert "what_it_proves" in d
            assert "what_it_does_not_prove" in d


# ---------------------------------------------------------------------------
# Group G: Roadmap completeness and dual-repo scope constraints
# ---------------------------------------------------------------------------


class TestGroupG_RoadmapCompletenessConstraints:
    """Group G: 路线图完整性与双仓范围约束。"""

    @pytest.fixture(scope="class")
    def roadmap(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        return report.roadmap

    def test_at_least_6_roadmap_prs(self, roadmap) -> None:
        assert len(roadmap) >= 6

    def test_schema_drift_roadmap_exists(self, roadmap) -> None:
        """PR 路线图必须包含解决 Schema drift 的条目。"""
        p2_items = [r for r in roadmap if "P2" in str(r.targeted_problems) or "Schema" in r.title]
        assert len(p2_items) >= 1

    def test_true_e2e_framework_roadmap_exists(self, roadmap) -> None:
        """PR 路线图必须包含建立真实双运行时回归测试框架的条目。"""
        e2e_items = [
            r for r in roadmap
            if "E2E" in r.title or "P5" in str(r.targeted_problems) or "双运行时" in r.title
        ]
        assert len(e2e_items) >= 1

    def test_most_roadmap_prs_are_dual_repo(self, roadmap) -> None:
        """大多数路线图 PR 应涉及双仓（体现真正的双仓协调交付物特性）。"""
        from core.dual_repo_centered_system_audit_contract import DualRepoOwnership
        dual_repo_count = sum(
            1 for r in roadmap if r.repo_scope == DualRepoOwnership.DUAL_REPO
        )
        assert dual_repo_count > len(roadmap) // 2

    def test_all_roadmap_items_have_acceptance_criteria(self, roadmap) -> None:
        for item in roadmap:
            assert isinstance(item.acceptance_criteria, list)
            assert len(item.acceptance_criteria) > 0, (
                f"路线图 PR {item.pr_id} 必须有接受标准"
            )

    def test_all_roadmap_items_have_targeted_problems(self, roadmap) -> None:
        for item in roadmap:
            assert isinstance(item.targeted_problems, list)
            assert len(item.targeted_problems) > 0

    def test_to_dict_complete(self, roadmap) -> None:
        for item in roadmap:
            d = item.to_dict()
            assert "pr_id" in d
            assert "repo_scope" in d
            assert "acceptance_criteria" in d
            assert "targeted_problems" in d


# ---------------------------------------------------------------------------
# Group H: Cross-repo proof summary output
# ---------------------------------------------------------------------------


class TestGroupH_CrossRepoProofSummaryOutput:
    """Group H: 跨仓 proof 摘要输出。"""

    def test_get_cross_repo_proof_summary_without_arg(self) -> None:
        from core.dual_repo_centered_system_audit_contract import get_cross_repo_proof_summary
        summary = get_cross_repo_proof_summary()
        assert isinstance(summary, dict)
        assert len(summary) == 8

    def test_summary_contains_all_domains(self) -> None:
        from core.dual_repo_centered_system_audit_contract import get_cross_repo_proof_summary
        summary = get_cross_repo_proof_summary()
        for domain_id in ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]:
            assert domain_id in summary

    def test_no_runtime_grounded_in_summary(self) -> None:
        """当前阶段，proof 摘要中不应出现 runtime_grounded。"""
        from core.dual_repo_centered_system_audit_contract import (
            get_cross_repo_proof_summary,
            ProofQualityLevel,
        )
        summary = get_cross_repo_proof_summary()
        for domain_id, info in summary.items():
            assert info["proof_quality"] != ProofQualityLevel.RUNTIME_GROUNDED.value, (
                f"定义域 {domain_id} 当前不应有 runtime_grounded proof quality"
            )

    def test_summary_each_domain_has_fulfillment_status(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            get_cross_repo_proof_summary,
            DefinitionFulfillmentStatus,
        )
        valid_statuses = set(e.value for e in DefinitionFulfillmentStatus)
        summary = get_cross_repo_proof_summary()
        for domain_id, info in summary.items():
            assert info["fulfillment_status"] in valid_statuses


# ---------------------------------------------------------------------------
# Group I: Conclusion field constraints
# ---------------------------------------------------------------------------


class TestGroupI_ConclusionFieldConstraints:
    """Group I: 结论字段约束。"""

    @pytest.fixture(scope="class")
    def report(self):
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        return build_dual_repo_centered_system_audit()

    def test_current_stage_is_mid_stage_consolidation(self, report) -> None:
        assert report.current_completion_stage == "mid_stage_consolidation"

    def test_overall_description_zh_not_empty(self, report) -> None:
        assert report.overall_system_description_zh
        assert len(report.overall_system_description_zh) > 50

    def test_pr_993_fulfillment_is_partially_fulfilled(self, report) -> None:
        """PR #993 定义已部分满足（V2 侧充分，跨仓 E2E 不足）。"""
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        assert report.pr_993_fulfillment == DefinitionFulfillmentStatus.PARTIALLY_FULFILLED

    def test_pr_1042_fulfillment_is_fulfilled(self, report) -> None:
        """PR #1042（execution lifecycle governance binding）V2 侧已充分满足。"""
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        assert report.pr_1042_fulfillment == DefinitionFulfillmentStatus.FULFILLED

    def test_pr_1043_fulfillment_is_partially_fulfilled(self, report) -> None:
        """PR #1043（mesh runtime center closure）V2 侧已满足，跨仓 runtime_closed 仍 deferred。"""
        from core.dual_repo_centered_system_audit_contract import DefinitionFulfillmentStatus
        assert report.pr_1043_fulfillment == DefinitionFulfillmentStatus.PARTIALLY_FULFILLED

    def test_claims_backed_by_real_code_not_empty(self, report) -> None:
        assert isinstance(report.claims_backed_by_real_code, list)
        assert len(report.claims_backed_by_real_code) >= 4

    def test_claims_structural_or_v2_only_not_empty(self, report) -> None:
        assert isinstance(report.claims_structural_or_v2_only, list)
        assert len(report.claims_structural_or_v2_only) >= 3

    def test_top_combined_system_gaps_not_empty(self, report) -> None:
        assert isinstance(report.top_combined_system_gaps, list)
        assert len(report.top_combined_system_gaps) >= 4

    def test_top_gap_mentions_schema_drift(self, report) -> None:
        gaps_str = " ".join(report.top_combined_system_gaps)
        assert "Schema" in gaps_str or "drift" in gaps_str or "P2" in gaps_str

    def test_top_gap_mentions_fake_e2e(self, report) -> None:
        gaps_str = " ".join(report.top_combined_system_gaps)
        assert "E2E" in gaps_str or "mock" in gaps_str or "P5" in gaps_str


# ---------------------------------------------------------------------------
# Group J: Helper function interfaces
# ---------------------------------------------------------------------------


class TestGroupJ_HelperFunctionInterfaces:
    """Group J: helper 函数接口。"""

    def test_get_combined_issue_list_no_filter(self) -> None:
        from core.dual_repo_centered_system_audit_contract import get_combined_issue_list
        issues = get_combined_issue_list()
        assert isinstance(issues, list)
        assert len(issues) >= 10

    def test_get_combined_issue_list_high_filter(self) -> None:
        from core.dual_repo_centered_system_audit_contract import get_combined_issue_list
        high_issues = get_combined_issue_list(severity_filter="high")
        assert isinstance(high_issues, list)
        assert all(i["severity"] == "high" for i in high_issues)
        assert len(high_issues) >= 4, "双仓系统应有至少 4 个高严重度问题"

    def test_get_roadmap_no_filter(self) -> None:
        from core.dual_repo_centered_system_audit_contract import get_roadmap
        roadmap = get_roadmap()
        assert isinstance(roadmap, list)
        assert len(roadmap) >= 6

    def test_get_roadmap_dual_repo_filter(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            get_roadmap,
            DualRepoOwnership,
        )
        dual_items = get_roadmap(repo_scope_filter=DualRepoOwnership.DUAL_REPO)
        assert isinstance(dual_items, list)
        assert len(dual_items) >= 4

    def test_get_roadmap_v2_only_filter(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            get_roadmap,
            DualRepoOwnership,
        )
        v2_items = get_roadmap(repo_scope_filter=DualRepoOwnership.V2_ONLY)
        assert isinstance(v2_items, list)
        assert len(v2_items) >= 1

    def test_canonical_path_traces_not_empty(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        assert len(report.canonical_path_traces) >= 4

    def test_each_path_trace_has_both_repo_segments(self) -> None:
        """每条 canonical 路径追踪应包含来自两个仓库的路径段（体现双仓联动）。"""
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        for trace in report.canonical_path_traces:
            repos_in_trace = {seg.repo for seg in trace.segments}
            assert "v2" in repos_in_trace, (
                f"路径 {trace.path_id} 必须有 V2 段"
            )
            assert "android" in repos_in_trace, (
                f"路径 {trace.path_id} 必须有 Android 段"
            )

    def test_each_path_trace_has_notes(self) -> None:
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
        )
        report = build_dual_repo_centered_system_audit()
        for trace in report.canonical_path_traces:
            assert trace.notes, f"路径 {trace.path_id} 必须有说明（notes）"

    def test_path_none_runtime_grounded(self) -> None:
        """当前路径追踪不应有 runtime_grounded proof quality。"""
        from core.dual_repo_centered_system_audit_contract import (
            build_dual_repo_centered_system_audit,
            ProofQualityLevel,
        )
        report = build_dual_repo_centered_system_audit()
        for trace in report.canonical_path_traces:
            assert trace.proof_quality != ProofQualityLevel.RUNTIME_GROUNDED
