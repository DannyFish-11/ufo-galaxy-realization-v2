"""PR1188 最终系统体纠偏文档约束测试。"""

from pathlib import Path


DOC_PATH = Path("audit/PR1188_FINAL_SYSTEM_BODY_CORRECTIVE_PASS_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_honestly_bounds_native_three_state() -> None:
    content = _read_doc()
    assert "原生三态" in content
    assert "尚未收敛" in content
    assert "工程闭合三态" in content


def test_doc_distinguishes_local_cross_multi_foundations() -> None:
    content = _read_doc()
    assert "local" in content
    assert "cross-device" in content
    assert "multi-device" in content
    assert "基础层" in content


def test_doc_reaudits_task_system_body_not_only_surface() -> None:
    content = _read_doc()
    required = [
        "origination_understanding",
        "planning_and_local_remote_selection",
        "delegation_and_execution",
        "cooperation_and_recovery",
        "result_aggregation_and_backflow",
        "truth_update_and_operator_projection",
    ]
    for item in required:
        assert item in content


def test_doc_records_structural_repairs_and_remaining_gaps() -> None:
    content = _read_doc()
    assert "build_system_backbone_snapshot" in content
    assert "foundational_system_truth" in content
    assert "native_three_state_final_audit" in content
    assert "local_cross_multi_foundation_audit" in content
    assert "task_system_body_final_audit" in content
    assert "仍然缺失" in content


def test_doc_contains_real_code_anchors() -> None:
    content = _read_doc()
    required = [
        "core/current_state_backbone_audit.py",
        "core/routes/projection.py",
        "core/command_router.py",
        "core/runtime/source_dispatch_orchestrator.py",
        "galaxy_gateway/device_router.py",
        "core/mesh_coordinator.py",
        "core/nats_bus.py",
        "core/unified_result_ingress.py",
    ]
    for anchor in required:
        assert anchor in content, f"missing anchor: {anchor}"
