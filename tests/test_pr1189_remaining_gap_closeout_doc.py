"""PR1189 剩余系统体收口过渡文档与代码约束测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

DOC_PATH = Path("audit/PR1189_REMAINING_GAP_CLOSEOUT_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


# ── 文档完整性约束 ─────────────────────────────────────────────────────────────

class TestDocumentCompleteness:
    """文档必须覆盖六大主题，且使用真实代码锚点。"""

    def test_doc_exists(self) -> None:
        assert DOC_PATH.exists()

    def test_doc_covers_native_three_state_closeout(self) -> None:
        content = _read_doc()
        assert "静态" in content
        assert "阈限态" in content
        assert "呈现态" in content
        assert "SILENT" in content
        assert "LIMINAL" in content
        assert "MANIFEST" in content

    def test_doc_maps_zh_to_code_values(self) -> None:
        content = _read_doc()
        # 每个中文术语必须有代码值映射
        assert "TriState.SILENT" in content
        assert "TriState.LIMINAL" in content
        assert "TriState.MANIFEST" in content
        assert "core.desktop_presence_runtime.TriState" in content

    def test_doc_distinguishes_still_absent_and_masked(self) -> None:
        content = _read_doc()
        assert "仍然缺失" in content
        assert "工程近似" in content
        assert "遮蔽" in content or "ClosureState" in content

    def test_doc_has_local_cross_multi_whole_model(self) -> None:
        content = _read_doc()
        assert "local" in content
        assert "cross-device" in content
        assert "multi-device" in content
        # 必须说明各层角色，不只是标签
        assert "任务起源" in content
        assert "委托" in content
        assert "结果回流" in content

    def test_doc_has_task_system_body_structural_analysis(self) -> None:
        content = _read_doc()
        # 六个切块必须都出现
        required_blocks = [
            "任务起源",
            "计划",
            "委托",
            "协作",
            "结果聚合",
            "真值更新",
        ]
        for block in required_blocks:
            assert block in content, f"task body block missing: {block}"

    def test_doc_classifies_central_agent_concretely(self) -> None:
        content = _read_doc()
        assert "中心智能体" in content
        assert "协调基础设施" in content
        assert "任务理解" in content
        assert "意图解析" in content
        assert "统一计划" in content

    def test_doc_improves_board_operator_usefulness(self) -> None:
        content = _read_doc()
        assert "board" in content or "operator" in content or "Board" in content
        assert "实用性" in content or "有用" in content

    def test_doc_has_remaining_work_split_by_layer(self) -> None:
        content = _read_doc()
        assert "V2" in content
        assert "Android" in content
        assert "panel" in content or "Panel" in content
        assert "desktop" in content or "Desktop" in content
        assert "多模态" in content or "multimodal" in content
        assert "外部依赖" in content or "external" in content

    def test_doc_has_real_code_anchors(self) -> None:
        content = _read_doc()
        required_anchors = [
            "core/current_state_backbone_audit.py",
            "core/routes/projection.py",
            "core/desktop_presence_runtime.py",
            "core/command_router.py",
            "core/capability_orchestrator.py",
            "core/agent_factory.py",
            "core/mesh_coordinator.py",
            "core/nats_bus.py",
            "core/unified_result_ingress.py",
        ]
        for anchor in required_anchors:
            assert anchor in content, f"missing code anchor: {anchor}"

    def test_doc_names_three_new_functions(self) -> None:
        content = _read_doc()
        assert "_build_native_three_state_closeout" in content
        assert "_build_central_agent_body_classification" in content
        assert "_build_remaining_work_split" in content

    def test_doc_names_three_new_snapshot_fields(self) -> None:
        content = _read_doc()
        assert "native_three_state_closeout" in content
        assert "central_agent_body_classification" in content
        assert "remaining_work_split" in content

    def test_doc_has_honest_remaining_boundary(self) -> None:
        content = _read_doc()
        assert "仍然缺失" in content
        assert "诚实" in content or "尚未" in content


# ── 代码结构约束 ─────────────────────────────────────────────────────────────


class TestBackboneAuditNewFunctions:
    """core.current_state_backbone_audit 必须包含三个新函数且输出正确结构。"""

    def test_native_three_state_closeout_function_exists(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_native_three_state_closeout,
        )
        assert callable(_build_native_three_state_closeout)

    def test_central_agent_body_classification_function_exists(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_central_agent_body_classification,
        )
        assert callable(_build_central_agent_body_classification)

    def test_remaining_work_split_function_exists(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_remaining_work_split,
        )
        assert callable(_build_remaining_work_split)

    def test_native_three_state_closeout_output_structure(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_native_three_state_closeout,
        )
        result = _build_native_three_state_closeout(mode_summary={}, layered_mode_model={})
        assert isinstance(result, dict)
        assert "closure_push_zh" in result
        assert "convergence_assessment" in result
        assert "zh_to_code_mapping" in result
        assert "hints_only" in result
        assert "still_absent" in result
        assert "masked_by_engineering_approximation" in result
        assert "hard_boundary_zh" in result

    def test_native_three_state_closeout_identifies_canonical_source(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_native_three_state_closeout,
        )
        result = _build_native_three_state_closeout(mode_summary={}, layered_mode_model={})
        # 当 TriState 存在时，应指出唯一权威源
        if result.get("canonical_source"):
            assert "desktop_presence_runtime" in result["canonical_source"]

    def test_native_three_state_closeout_maps_all_three_zh_terms(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_native_three_state_closeout,
        )
        result = _build_native_three_state_closeout(mode_summary={}, layered_mode_model={})
        mapping = result.get("zh_to_code_mapping", [])
        zh_terms = {item.get("zh_term") for item in mapping if isinstance(item, dict)}
        # 如果 TriState 枚举存在，三个中文术语都应被映射
        if mapping:
            assert "静态" in zh_terms, "missing zh_term: 静态"
            assert "阈限态" in zh_terms, "missing zh_term: 阈限态"
            assert "呈现态" in zh_terms, "missing zh_term: 呈现态"

    def test_central_agent_body_classification_output_structure(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_central_agent_body_classification,
        )
        result = _build_central_agent_body_classification()
        assert isinstance(result, dict)
        assert "verdict_zh" in result
        assert "existing_center_components" in result
        assert "only_coordination_infrastructure" in result
        assert "still_missing_capabilities" in result
        assert "classification_summary" in result

    def test_central_agent_body_classification_has_missing_capabilities(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_central_agent_body_classification,
        )
        result = _build_central_agent_body_classification()
        missing = result.get("still_missing_capabilities", [])
        assert len(missing) > 0, "must list at least one missing capability"
        # 每条缺失项必须有归属层
        for item in missing:
            assert "belongs_to" in item, f"missing belongs_to in: {item}"

    def test_central_agent_body_classification_full_agent_not_present(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_central_agent_body_classification,
        )
        result = _build_central_agent_body_classification()
        summary = result.get("classification_summary", {})
        # 系统诚实：完整中心智能体当前不存在
        assert summary.get("full_central_agent_present") is False

    def test_remaining_work_split_output_structure(self) -> None:
        from core.current_state_backbone_audit import (  # noqa: PLC0415
            _build_remaining_work_split,
        )
        result = _build_remaining_work_split()
        assert isinstance(result, dict)
        # 六大分层必须都在
        required_keys = ["V2", "Android", "panel_fullstack", "desktop_shell", "multimodal_io", "external_deps"]
        for key in required_keys:
            assert key in result, f"missing layer: {key}"
            layer = result[key]
            assert "remaining" in layer, f"layer {key} missing 'remaining' list"
            assert len(layer["remaining"]) > 0, f"layer {key} has empty remaining list"

    def test_build_system_backbone_snapshot_includes_new_fields(self) -> None:
        from core.current_state_backbone_audit import build_system_backbone_snapshot  # noqa: PLC0415

        snapshot = build_system_backbone_snapshot()
        assert isinstance(snapshot, dict)
        assert "native_three_state_closeout" in snapshot
        assert "central_agent_body_classification" in snapshot
        assert "remaining_work_split" in snapshot

    def test_backbone_snapshot_new_fields_are_dicts(self) -> None:
        from core.current_state_backbone_audit import build_system_backbone_snapshot  # noqa: PLC0415

        snapshot = build_system_backbone_snapshot()
        assert isinstance(snapshot.get("native_three_state_closeout"), dict)
        assert isinstance(snapshot.get("central_agent_body_classification"), dict)
        assert isinstance(snapshot.get("remaining_work_split"), dict)


# ── 投影层约束 ────────────────────────────────────────────────────────────────


class TestProjectionLayerNewFields:
    """_build_foundational_system_truth 必须透出三个新字段。"""

    def test_foundational_system_truth_has_native_three_state_closeout(self) -> None:
        pytest.importorskip("fastapi", reason="projection module requires fastapi")
        from core.routes.projection import _build_foundational_system_truth  # noqa: PLC0415

        result = _build_foundational_system_truth({})
        assert "native_three_state_closeout" in result
        assert isinstance(result["native_three_state_closeout"], dict)

    def test_foundational_system_truth_has_central_agent_body_classification(self) -> None:
        pytest.importorskip("fastapi", reason="projection module requires fastapi")
        from core.routes.projection import _build_foundational_system_truth  # noqa: PLC0415

        result = _build_foundational_system_truth({})
        assert "central_agent_body_classification" in result
        assert isinstance(result["central_agent_body_classification"], dict)

    def test_foundational_system_truth_has_remaining_work_split(self) -> None:
        pytest.importorskip("fastapi", reason="projection module requires fastapi")
        from core.routes.projection import _build_foundational_system_truth  # noqa: PLC0415

        result = _build_foundational_system_truth({})
        assert "remaining_work_split" in result
        assert isinstance(result["remaining_work_split"], dict)

    def test_foundational_system_truth_remaining_work_split_has_six_layers(self) -> None:
        pytest.importorskip("fastapi", reason="projection module requires fastapi")
        from core.routes.projection import _build_foundational_system_truth  # noqa: PLC0415

        result = _build_foundational_system_truth({})
        split = result.get("remaining_work_split", {})
        required_keys = ["V2", "Android", "panel_fullstack", "desktop_shell", "multimodal_io", "external_deps"]
        for key in required_keys:
            assert key in split, f"remaining_work_split missing layer: {key}"
