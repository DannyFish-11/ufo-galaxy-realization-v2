"""Task 1 — 正式系统定义文档约束测试。

确保 docs/SYSTEM_FORMAL_DEFINITION_V1.md 与
docs/DUAL_REPO_UNIFIED_GLOSSARY_V1.md 中的核心术语、
代码锚点与架构边界声明不被后续 PR 静默删除或漂移。
"""

from pathlib import Path

FORMAL_DEF_PATH = Path("docs/SYSTEM_FORMAL_DEFINITION_V1.md")
GLOSSARY_PATH = Path("docs/DUAL_REPO_UNIFIED_GLOSSARY_V1.md")


def _read(path: Path) -> str:
    assert path.exists(), f"missing document: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests for SYSTEM_FORMAL_DEFINITION_V1.md
# ---------------------------------------------------------------------------


def test_formal_def_exists() -> None:
    assert FORMAL_DEF_PATH.exists(), f"missing: {FORMAL_DEF_PATH}"


def test_formal_def_states_correct_architecture_name() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "中心 canonical 治理" in content
    assert "有界相对主体 runtime" in content
    assert "分布式 AI 执行架构" in content


def test_formal_def_declares_v2_as_sole_canonical_center() -> None:
    content = _read(FORMAL_DEF_PATH)
    required = [
        "canonical governance",
        "truth convergence",
        "dispatch arbitration",
        "closure authority",
    ]
    for term in required:
        assert term in content, f"missing term: {term!r}"


def test_formal_def_prohibits_android_as_passive_endpoint() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "不是" in content
    assert "passive execution endpoint" in content or "被动执行" in content or "被动" in content


def test_formal_def_prohibits_android_as_parallel_center() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "平行" in content
    assert "平行双中心" in content or "平行 canonical center" in content


def test_formal_def_declares_android_as_bounded_relative_subject_runtime() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "bounded relative subject runtime" in content
    assert "local lifecycle" in content or "本地 lifecycle" in content
    assert "local continuity" in content or "本地 continuity" in content
    assert "local execution judgment" in content or "local AI system consumption" in content


def test_formal_def_references_real_core_modules() -> None:
    content = _read(FORMAL_DEF_PATH)
    required_modules = [
        "core/command_router.py",
        "core/unified_runtime_truth_ingress.py",
        "core/unified_result_ingress.py",
        "core/unified_continuity_legality_authority.py",
        "core/android_participant_truth_ingress.py",
        "core/operator_surface.py",
        "core/routes/operator.py",
    ]
    for mod in required_modules:
        assert mod in content, f"missing module reference: {mod!r}"


def test_formal_def_references_android_real_modules() -> None:
    content = _read(FORMAL_DEF_PATH)
    required = [
        "RuntimeController.kt",
        "GalaxyConnectionService.kt",
        "GalaxyWebSocketClient.kt",
        "LocalExecutionModeGate.kt",
        "AutonomousExecutionPipeline.kt",
    ]
    for item in required:
        assert item in content, f"missing Android module reference: {item!r}"


def test_formal_def_defines_truth_closure_continuity_verdict_semantics() -> None:
    content = _read(FORMAL_DEF_PATH)
    required = [
        "verdict",
        "truth",
        "closure",
        "continuity",
    ]
    for term in required:
        assert term in content, f"missing semantic term: {term!r}"


def test_formal_def_references_hot_path_chain() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "CommandRouter" in content or "command_router" in content
    assert "UnifiedRuntimeTruthIngress" in content or "unified_runtime_truth_ingress" in content
    assert "UnifiedResultIngress" in content or "unified_result_ingress" in content


def test_formal_def_lists_prohibited_drift_directions() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "不允许" in content or "禁止" in content
    assert "漂移" in content or "prohibited" in content or "Prohibited" in content or "明确禁止" in content


def test_formal_def_references_glossary() -> None:
    content = _read(FORMAL_DEF_PATH)
    assert "DUAL_REPO_UNIFIED_GLOSSARY_V1.md" in content


# ---------------------------------------------------------------------------
# Tests for DUAL_REPO_UNIFIED_GLOSSARY_V1.md
# ---------------------------------------------------------------------------


def test_glossary_exists() -> None:
    assert GLOSSARY_PATH.exists(), f"missing: {GLOSSARY_PATH}"


def test_glossary_defines_all_required_terms() -> None:
    content = _read(GLOSSARY_PATH)
    required_terms = [
        "center",
        "subject",
        "participant",
        "target",
        "truth",
        "dispatch",
        "continuity",
        "closure",
        "bounded authority",
    ]
    for term in required_terms:
        assert term in content, f"missing glossary term: {term!r}"


def test_glossary_classifies_truth_into_three_kinds() -> None:
    content = _read(GLOSSARY_PATH)
    assert "authority_truth" in content
    assert "acceptance_closure_readiness_truth" in content
    assert "outward_projection_operator_truth" in content


def test_glossary_defines_participant_roles() -> None:
    content = _read(GLOSSARY_PATH)
    required_roles = ["primary", "assistant", "fallback", "suspended", "takeover_candidate", "degraded"]
    for role in required_roles:
        assert role in content, f"missing participant role: {role!r}"


def test_glossary_defines_usage_rules() -> None:
    content = _read(GLOSSARY_PATH)
    assert "R1" in content
    assert "R2" in content
    assert "canonical truth" in content
    assert "dispatch authority" in content


def test_glossary_bounded_authority_references_ingress_modules() -> None:
    content = _read(GLOSSARY_PATH)
    assert "android_participant_truth_ingress" in content
    assert "unified_runtime_truth_ingress" in content


def test_glossary_references_formal_definition_doc() -> None:
    content = _read(GLOSSARY_PATH)
    assert "SYSTEM_FORMAL_DEFINITION_V1.md" in content


# ---------------------------------------------------------------------------
# Cross-validation: referenced code modules actually exist
# ---------------------------------------------------------------------------


def test_core_command_router_exists() -> None:
    assert Path("core/command_router.py").exists()


def test_core_unified_runtime_truth_ingress_exists() -> None:
    assert Path("core/unified_runtime_truth_ingress.py").exists()


def test_core_unified_result_ingress_exists() -> None:
    assert Path("core/unified_result_ingress.py").exists()


def test_core_unified_continuity_legality_authority_exists() -> None:
    assert Path("core/unified_continuity_legality_authority.py").exists()


def test_core_android_participant_truth_ingress_exists() -> None:
    assert Path("core/android_participant_truth_ingress.py").exists()


def test_core_operator_surface_exists() -> None:
    assert Path("core/operator_surface.py").exists()


def test_core_routes_operator_exists() -> None:
    assert Path("core/routes/operator.py").exists()
