"""认知型 PR 启动基线文档约束测试。"""

from pathlib import Path


DOC_PATH = Path("audit/COGNITIVE_PR_PROBLEM_STATEMENT_BOOTSTRAP_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_has_scope_and_method_sections() -> None:
    content = _read_doc()
    assert "问题背景与当前理解" in content
    assert "证据边界与方法" in content
    assert "问题范围推断" in content
    assert "影响面分析" in content
    assert "建议的后续步骤" in content


def test_doc_contains_real_code_anchors() -> None:
    content = _read_doc()
    required_anchors = [
        "main.py",
        "core/unified_config.py",
        "core/system_integration.py",
        "core/api_routes.py",
        "core/device_registry.py",
        "core/device_communication.py",
        "core/mcp_loader.py",
        "core/skill_loader.py",
        "core/agent_factory.py",
        "core/routes/protocols.py",
        "core/routes/devices.py",
        "dashboard/backend/main.py",
    ]
    for anchor in required_anchors:
        assert anchor in content, f"missing anchor: {anchor}"


def test_doc_declares_minimal_low_risk_change_boundary() -> None:
    content = _read_doc()
    assert "最小必要" in content
    assert "不修改生产代码逻辑" in content
    assert "不在本 PR 内做" in content
