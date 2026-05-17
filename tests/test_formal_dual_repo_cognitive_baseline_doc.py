"""正式双仓认知基线文档约束测试。"""

from pathlib import Path


DOC_PATH = Path("audit/FORMAL_DUAL_REPO_COGNITIVE_BASELINE_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_establishes_center_distributed_ai_body_not_multi_client_product() -> None:
    content = _read_doc()
    assert "中心分布式 AI 系统" in content
    assert "不能退回" in content
    assert "普通多客户端产品" in content
    assert "中心治理核 + 分布式执行/感知/交互/呈现网络" in content


def test_doc_lists_current_center_authorities_with_code_anchors() -> None:
    content = _read_doc()
    required = [
        "调度",
        "路由",
        "配置",
        "任务真值",
        "operator 聚合",
        "设备接入",
        "gateway",
        "结果汇聚",
        "投影 / 观察面",
        "core/openclawd.py",
        "core/command_router.py",
        "core/unified_config.py",
        "core/task_result_canonical_truth_chain.py",
        "galaxy_gateway/android/handlers/registration.py",
        "galaxy_gateway/routes/websocket.py",
        "core/unified_result_ingress.py",
        "core/routes/projection.py",
    ]
    for item in required:
        assert item in content, f"missing: {item}"


def test_doc_positions_android_desktop_and_other_devices_as_body_network_planes() -> None:
    content = _read_doc()
    required = [
        "Android 不是普通客户端",
        "桌面不是普通 UI",
        "执行面",
        "感知面",
        "交互面",
        "呈现面",
        "GalaxyWebSocketClient.kt",
        "GalaxyConnectionService.kt",
        "RuntimeController.kt",
        "LlamaCppPlannerService.kt",
        "NcnnGroundingService.kt",
        "LocalLoopExecutor.kt",
    ]
    for item in required:
        assert item in content, f"missing: {item}"


def test_doc_covers_local_and_cross_device_main_chains_and_closure() -> None:
    content = _read_doc()
    required = [
        "本地链路主链",
        "跨设备链路主链",
        "DesktopPresenceRuntime.handle_request()",
        "OpenClawd.process()",
        "CommandRouter.route_envelope()",
        "/ws/device/{device_id}",
        "AutonomousExecutionPipeline.kt",
        "unified_result_ingress.py",
        "两条并行一级执行主链",
        "已形成真实主链",
        "部分闭合",
    ]
    for item in required:
        assert item in content, f"missing: {item}"


def test_doc_binds_true_three_state_to_desktop_presence_runtime_only() -> None:
    content = _read_doc()
    required = [
        "唯一权威三态",
        "core/desktop_presence_runtime.py",
        "TriState",
        "SILENT",
        "LIMINAL",
        "MANIFEST",
        "内部协议态",
        "工程闭合态",
        "近似态 / 壳层态",
        "tri_state_phase",
        "ClosureState(established / partial / open)",
        "DORMANT / ISLAND / SIDESHEET / FULLAGENT",
    ]
    for item in required:
        assert item in content, f"missing: {item}"


def test_doc_classifies_websocket_mesh_and_nats_without_repromoting_overlays() -> None:
    content = _read_doc()
    required = [
        "WebSocket",
        "Mesh",
        "NATS",
        "sole canonical device ingress",
        "MESH::OVERLAY_ENRICHMENT_ONLY",
        "GALAXY_NATS_URL",
        "no-op mode",
        "主链",
        "overlay",
        "fallback",
        "可选层",
        "core/mesh_coordinator.py",
        "core/routes/hybrid.py",
        "core/nats_bus.py",
        "galaxy_gateway/routes/websocket.py",
    ]
    for item in required:
        assert item in content, f"missing: {item}"


def test_doc_honestly_records_android_autonomy_maturity_and_system_problems() -> None:
    content = _read_doc()
    required = [
        "LOCAL_ONLY",
        "CROSS_DEVICE_ACTIVE",
        "CROSS_DEVICE_DEGRADED",
        "自治执行节点",
        "被中心委托的执行节点",
        "已形成真实主链的部分",
        "弱证据部分",
        "假闭环部分",
        "缺失部分",
        "状态语义",
        "执行策略",
        "中心智能体",
        "真值链 / 结果链 / 验收链",
        "网络层 / transport",
        "operator / control plane",
        "产品壳层 / desktop shell",
        "多模态",
        "测试 / 回归 / 活体验证",
    ]
    for item in required:
        assert item in content, f"missing: {item}"
