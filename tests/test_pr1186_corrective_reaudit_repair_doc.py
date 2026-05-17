"""PR1186 纠偏重审 + 修复文档约束测试。"""

from pathlib import Path


DOC_PATH = Path("audit/PR1186_V2_ANDROID_CORRECTIVE_REAUDIT_AND_REPAIR_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_separates_cross_device_and_multi_device() -> None:
    content = _read_doc()
    assert "跨设备" in content
    assert "多设备" in content
    assert "路由能力层" in content
    assert "参与结构层" in content


def test_doc_defines_real_three_state_from_code_not_generic_ui() -> None:
    content = _read_doc()
    assert "工程闭合三态" in content
    assert "established" in content
    assert "partial" in content
    assert "open" in content
    assert "不是通用助手 UI 三态" in content


def test_doc_covers_task_system_layered_whole_stack() -> None:
    content = _read_doc()
    assert "请求/派发链" in content
    assert "执行链" in content
    assert "结果回流链" in content
    assert "闭环验收链" in content
    assert "投影链" in content


def test_doc_records_concrete_repairs_not_only_cognition() -> None:
    content = _read_doc()
    assert "_build_foundational_system_truth" in content
    assert "foundational_system_truth" in content
    assert "status_board_v2/device_surface.py" in content
    assert "projection_reader.py" in content


def test_doc_contains_v2_and_android_code_anchors() -> None:
    content = _read_doc()
    required = [
        "core/current_state_backbone_audit.py",
        "core/command_router.py",
        "galaxy_gateway/device_router.py",
        "core/unified_result_ingress.py",
        "core/routes/projection.py",
        "app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt",
        "app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt",
        "app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt",
    ]
    for anchor in required:
        assert anchor in content, f"missing anchor: {anchor}"


def test_doc_explicitly_lists_done_and_unfinished() -> None:
    content = _read_doc()
    assert "已修" in content
    assert "仍未完成" in content
    assert "完整中心智能体" in content
