"""PR #1185 严格补审文档校验。"""

from pathlib import Path


DOC_PATH = Path("audit/PR1185_STRICT_CENTER_DISTRIBUTED_WHOLE_SYSTEM_AUDIT_CN_2026.md")


def _read_doc() -> str:
    assert DOC_PATH.exists(), f"missing document: {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8")


def test_doc_explicitly_states_pr1185_unfinished_blindspots() -> None:
    content = _read_doc()
    assert "PR #1185" in content
    assert "盲点" in content
    assert "本地链路" in content
    assert "跨设备链路" in content


def test_doc_defines_intended_whole_system_model() -> None:
    content = _read_doc()
    assert "手机" in content
    assert "平板" in content
    assert "电脑" in content
    assert "每个设备既能自己做事" in content


def test_doc_audits_central_agent_completeness_not_just_dispatcher() -> None:
    content = _read_doc()
    assert "中心协调层存在" in content
    assert "完整中心智能体" in content
    assert "coordinator/dispatcher 已有" in content
    assert "规划" in content and "记忆" in content and "失败恢复" in content


def test_doc_covers_multi_device_cooperation_modes() -> None:
    content = _read_doc()
    assert "自设备执行" in content
    assert "委托执行" in content
    assert "中继执行" in content
    assert "多设备协同执行" in content


def test_doc_covers_mesh_nats_websocket_roles() -> None:
    content = _read_doc()
    assert "WebSocket" in content
    assert "mesh" in content.lower()
    assert "NATS" in content
    assert "GALAXY_NATS_URL" in content


def test_doc_covers_external_dependencies_and_runtime_boundaries() -> None:
    content = _read_doc()
    assert "外部依赖" in content
    assert "网络边界" in content
    assert "运行时边界" in content
    assert "模型边界" in content


def test_doc_treats_panel_incompleteness_as_system_incompleteness() -> None:
    content = _read_doc()
    assert "panel 不完整 = 系统不完整" in content
    assert "windows_client/status_board_v2/" in content
    assert "static/operator-console/index.html" in content


def test_doc_covers_typescript_full_stack_gap_and_desktop_shell() -> None:
    content = _read_doc()
    assert "TypeScript" in content
    assert "dashboard/frontend/" in content
    assert "desktop shell" in content
    assert "multimodal IO" in content


def test_doc_has_required_closure_classification() -> None:
    content = _read_doc()
    assert "REAL_CLOSURE" in content
    assert "PARTIAL_CLOSURE" in content
    assert "FAKE_CLOSURE" in content


def test_doc_has_cross_repo_code_anchors() -> None:
    content = _read_doc()
    required = [
        "core/openclawd.py",
        "core/command_router.py",
        "galaxy_gateway/device_router.py",
        "galaxy_gateway/routes/websocket.py",
        "core/mesh_coordinator.py",
        "core/nats_bus.py",
        "core/unified_result_ingress.py",
        "core/routes/projection.py",
        "app/src/main/java/com/ufo/galaxy/network/GalaxyWebSocketClient.kt",
        "app/src/main/java/com/ufo/galaxy/service/GalaxyConnectionService.kt",
        "app/src/main/java/com/ufo/galaxy/agent/AutonomousExecutionPipeline.kt",
    ]
    for anchor in required:
        assert anchor in content, f"missing anchor: {anchor}"
