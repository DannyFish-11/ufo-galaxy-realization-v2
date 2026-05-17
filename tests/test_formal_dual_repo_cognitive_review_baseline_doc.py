"""正式双仓认知审查基线文档约束。"""

from pathlib import Path


DOC_PATH = Path("audit/FORMAL_DUAL_REPO_COGNITIVE_REVIEW_BASELINE_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_system_identity() -> None:
    content = _read_doc()
    assert "中心分布式 AI 系统" in content
    assert "普通多客户端产品" in content
    assert "中心治理核 + 分布式执行/感知/显现网络" in content
    assert "不能把它退回成“PC + Android 客户端”的普通多客户端产品认知" in content


def test_center_authority() -> None:
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
        "core/runtime/source_dispatch_orchestrator.py",
        "core/command_router.py",
        "galaxy_gateway/device_router.py",
        "core/unified_config.py",
        "core/unified_result_ingress.py",
        "core/task_result_canonical_truth_chain.py",
        "core/operator_surface.py",
        "core/routes/operator.py",
        "core/routes/projection.py",
    ]
    for item in required:
        assert item in content, f"missing center authority item: {item}"


def test_device_positioning() -> None:
    content = _read_doc()
    assert "Android 是强运行时节点" in content
    assert "不是被动终端" in content
    assert "显现载体" in content
    assert "执行面 / 感知面 / 被委托运行时节点" in content
    assert "显现面 / operator 观察面 / 控制承接面" in content
    required_anchors = [
        "app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt",
        "app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt",
        "app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt",
        "app/src/main/java/com/ufo/galaxy/runtime/LocalExecutionModeGate.kt",
        "app/src/main/java/com/ufo/galaxy/runtime/RuntimeController.kt",
        "windows_client/status_board_v2/device_surface.py",
        "static/operator-console/index.html",
    ]
    for anchor in required_anchors:
        assert anchor in content, f"missing device-positioning anchor: {anchor}"


def test_execution_chains() -> None:
    content = _read_doc()
    assert "本地链路主链" in content
    assert "跨设备链路主链" in content
    assert "两条主链如何并存" in content
    assert "已形成真实主链" in content
    assert "部分闭环" in content
    assert "/ws/device/{device_id}" in content
    assert "galaxy_gateway/android/handlers/registration.py" in content


def test_tri_state_convergence() -> None:
    content = _read_doc()
    assert "静态" in content
    assert "阈限态" in content
    assert "显现态" in content
    for state in ["SILENT", "LIMINAL", "MANIFEST"]:
        assert f"TriState.{state}" in content or state in content
    assert "唯一权威实现" in content
    assert "core/desktop_presence_runtime.py" in content
    assert "工程闭合态" in content
    assert "内部协议态" in content
    assert "近似态" in content
    assert "ClosureState(established/partial/open)" in content
    assert "core.continuum.tri_state_phase" in content


def test_transport_layering() -> None:
    content = _read_doc()
    assert "WS = 当前双仓主链" in content
    assert "Mesh = 建立在当前主链之上的协作 overlay" in content
    assert "NATS = 可选层" in content
    assert "主链" in content
    assert "overlay" in content
    assert "fallback" in content
    assert "可选层" in content
    assert "core/mesh_coordinator.py" in content
    assert "core/nats_bus.py" in content


def test_android_runtime_role() -> None:
    content = _read_doc()
    assert "Android 具备真实本地执行链路" in content
    assert "可自治、也可被中心委托的强运行时节点" in content
    assert "自治场景" in content
    assert "中心委托场景" in content
    assert "GalaxyWebSocketClient.kt" in content
    assert "GalaxyConnectionService.kt" in content
    assert "AutonomousExecutionPipeline.kt" in content


def test_maturity_and_problem_domains() -> None:
    content = _read_doc()
    maturity_items = [
        "已形成真实主链的部分",
        "部分闭合的部分",
        "弱证据部分",
        "假闭环部分",
        "缺失部分",
    ]
    for item in maturity_items:
        assert item in content, f"missing maturity item: {item}"
    problem_domains = [
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
    for item in problem_domains:
        assert item in content, f"missing problem domain: {item}"


def test_non_regression_constraints() -> None:
    content = _read_doc()
    assert "本 PR 合并后" in content
    assert "不回退约束" in content
    assert "Android 必须维持“强运行时节点”定位" in content
    assert "桌面必须维持“显现载体 / 观察承接面”定位" in content
