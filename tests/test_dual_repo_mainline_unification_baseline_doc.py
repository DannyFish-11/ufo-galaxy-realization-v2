"""双仓主链/未一体化能力/重复建设风险正式基线约束。"""

from pathlib import Path


DOC_PATH = Path("audit/FORMAL_DUAL_REPO_MAINLINE_UNINTEGRATED_RISK_BASELINE_CN_2026.md")
UNINTEGRATED_APPENDIX = Path("audit/FORMAL_DUAL_REPO_UNINTEGRATED_CAPABILITIES_APPENDIX_CN_2026.md")
DUPLICATE_APPENDIX = Path("audit/FORMAL_DUAL_REPO_DUPLICATE_WHEEL_RISK_APPENDIX_CN_2026.md")


def _read(path: Path) -> str:
    assert path.exists(), f"missing document: {path}"
    return path.read_text(encoding="utf-8")


def test_main_doc_establishes_system_body_and_dual_mainline() -> None:
    content = _read(DOC_PATH)
    required = [
        "中心分布式 AI 系统",
        "普通多客户端产品",
        "中心治理核 + 分布式执行/感知/显现网络",
        "本地链路主链",
        "跨设备链路主链",
        "core/canonical_execution_chain.py",
        "core/openclawd.py",
        "core/command_router.py",
        "galaxy_gateway/device_router.py",
        "galaxy_gateway/routes/websocket.py",
        "galaxy_gateway/android/handlers/registration.py",
        "core/runtime/source_dispatch_orchestrator.py",
        "core/unified_result_ingress.py",
        "core/task_result_canonical_truth_chain.py",
    ]
    for item in required:
        assert item in content, f"missing mainline item: {item}"


def test_main_doc_positions_android_desktop_and_transport_layers_correctly() -> None:
    content = _read(DOC_PATH)
    required = [
        "Android",
        "强运行时节点",
        "GalaxyWebSocketClient.kt",
        "GalaxyConnectionService.kt",
        "AutonomousExecutionPipeline.kt",
        "LocalExecutionModeGate.kt",
        "RuntimeController.kt",
        "windows_client/status_board_v2/device_surface.py",
        "static/operator-console/index.html",
        "desktop_projection/*.py",
        "WS 是当前双仓主链",
        "Mesh 是 overlay",
        "relay / ws fallback 是 fallback",
        "NATS / MasterBrain 是可选 worker-domain 路径",
        "core/mesh_coordinator.py",
        "core/nats_bus.py",
        "core/master_brain.py",
    ]
    for item in required:
        assert item in content, f"missing transport/device item: {item}"


def test_main_doc_locks_tri_state_authority_and_demotions() -> None:
    content = _read(DOC_PATH)
    required = [
        "静态",
        "阈限态",
        "显现态",
        "core/desktop_presence_runtime.py::TriState",
        "TriState.SILENT",
        "TriState.LIMINAL",
        "TriState.MANIFEST",
        "内部协议态",
        "工程闭合态",
        "壳层 UI 状态",
        "近似态 / 派生态",
        "core/current_state_backbone_audit.py::ClosureState(established/partial/open)",
        "core/openclawd.py",
        "tri_state_phase",
        "system_integration/state_machine_ui_integration.py",
        "DORMANT/ISLAND/SIDESHEET/FULLAGENT",
    ]
    for item in required:
        assert item in content, f"missing tri-state item: {item}"


def test_main_doc_covers_repository_structure_unintegrated_capabilities_and_gaps() -> None:
    content = _read(DOC_PATH)
    required = [
        "状态模型",
        "执行策略",
        "任务链",
        "路由 / 调度 / dispatch",
        "设备接入 / registration / participation",
        "projection / operator / status board",
        "desktop shell",
        "多模态",
        "Android bridge / uplink",
        "测试 / 验收 / integration / e2e",
        "未一体化能力",
        "重复造轮子风险",
        "状态语义",
        "中心智能体",
        "真值链 / 结果链 / 验收链",
        "transport / network layer",
        "operator / control plane",
        "Android 一体化吸收",
        "测试 / 回归 / 活体验证",
    ]
    for item in required:
        assert item in content, f"missing structure/gap item: {item}"


def test_appendices_exist_and_are_referenced_by_main_doc() -> None:
    main_content = _read(DOC_PATH)
    unintegrated_content = _read(UNINTEGRATED_APPENDIX)
    duplicate_content = _read(DUPLICATE_APPENDIX)

    assert str(UNINTEGRATED_APPENDIX) in main_content
    assert str(DUPLICATE_APPENDIX) in main_content

    unintegrated_required = [
        "core/unified_orchestration_spine.py",
        "core/swarm_coordinator.py",
        "core/v2_unified_state_contract.py",
        "LocalExecutionModeGate.kt",
        "RuntimeController.kt",
        "core/transport_hierarchy.py",
        "core/nats_bus.py",
        "core/master_brain.py",
        "core/unified_panel_aggregation.py",
        "core/multimodal/ingress_bus.py",
        "core/perception/multimodal_bus.py",
        "core/unified/device_manager.py",
        "core/agent/capability_registry.py",
        "core/unified/capability_resolver.py",
    ]
    for item in unintegrated_required:
        assert item in unintegrated_content, f"missing unintegrated appendix item: {item}"

    duplicate_required = [
        "core/desktop_presence_runtime.py::TriState",
        "core/openclawd.py::tri_state_phase",
        "core/current_state_backbone_audit.py::ClosureState",
        "system_integration/state_machine_ui_integration.py::SystemState",
        "core/unified_orchestration_spine.py",
        "core/swarm_coordinator.py",
        "core/master_brain.py",
        "core/unified/device_manager.py",
        "core/device_registry.py",
        "core/agent/capability_registry.py",
        "core/capability_manager.py",
        "core/operator_surface.py",
        "core/routes/projection.py",
        "core/unified_panel_aggregation.py",
        "core/android_runtime_transition_reducer.py",
    ]
    for item in duplicate_required:
        assert item in duplicate_content, f"missing duplicate appendix item: {item}"


def test_non_regression_constraints_prevent_backsliding_to_shallow_cognition() -> None:
    content = _read(DOC_PATH)
    required = [
        "本 PR 合并后",
        "不回退约束",
        "只讲主链，不讲未一体化能力",
        "只讲缺口，不讲已有重复实现",
        "只讲认知，不讲具体代码落点",
        "把 Mesh / NATS / MasterBrain 重新包装成 Android ↔ V2 默认主链",
        "把 `ClosureState`、`tri_state_phase`、`DORMANT/ISLAND/SIDESHEET/FULLAGENT` 重新包装成主体三态",
    ]
    for item in required:
        assert item in content, f"missing non-regression constraint: {item}"
