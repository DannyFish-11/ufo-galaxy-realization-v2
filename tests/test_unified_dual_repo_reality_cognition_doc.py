"""双仓一体化认知文档完整性校验。"""

from pathlib import Path


DOC_PATH = Path("audit/UNIFIED_DUAL_REPO_REALITY_COGNITION_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_covers_two_repositories_and_methodology() -> None:
    content = _read_doc()
    assert "ufo-galaxy-realization-v2" in content
    assert "ufo-galaxy-android" in content
    assert "只看真实代码" in content


def test_doc_covers_end_to_end_experience_map() -> None:
    content = _read_doc()
    assert "clone 两个仓库" in content
    assert "device_register" in content
    assert "task_assign" in content
    assert "goal_execution" in content
    assert "可参与可调度" in content


def test_doc_explicitly_covers_typescript_full_stack_gap() -> None:
    content = _read_doc()
    assert "TypeScript" in content
    assert "dashboard/frontend/" in content
    assert "operator web console" in content


def test_doc_covers_agent_mechanism_and_maturity_gaps() -> None:
    content = _read_doc()
    assert "智能体机制设计" in content
    assert "规划-执行-验收-记忆回流" in content
    assert "硬阻断" in content
    assert "次级增强" in content


def test_doc_has_cross_repo_code_anchors() -> None:
    content = _read_doc()
    required_anchors = [
        "galaxy_gateway/android/handlers/registration.py",
        "core/task_result_canonical_truth_chain.py",
        "core/unified_result_ingress.py",
        "app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt",
        "app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt",
        "app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt",
    ]
    for anchor in required_anchors:
        assert anchor in content, f"missing anchor: {anchor}"
