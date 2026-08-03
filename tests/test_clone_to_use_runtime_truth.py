from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def _read(rel: str) -> str:
    return (REPO_ROOT / rel).read_text(encoding="utf-8")


def test_clone_to_use_reality_doc_exists_and_covers_core_questions() -> None:
    content = _read("docs/CLONE_TO_USE_REALITY.md")
    assert "python main.py" in content
    assert "/api/v1/chat" in content
    assert "/api/v1/projection/runtime" in content
    assert "cross-device" in content.lower()
    assert "read-only" in content.lower()


# 这里曾有两条测试:
#
#   test_windows_status_board_doc_matches_v2_runtime_path —— 钉 docs/WINDOWS_STATUS_BOARD.md
#   test_status_board_v2_default_port_aligned_with_main_runtime —— 钉终端状态板的默认端口
#
# 两者随 windows_client/status_board_v2/ 一并移除(面板表层收敛,唯一表层是
# Tauri/Electron 壳内的 React 面板)。上面那条也去掉了对
# ``python -m windows_client.status_board_v2`` 的断言。
#
# **端口对齐这条不变量没有丢**:它真正保障的是"消费方默认打的端口 = 主运行时
# 端口 9000"。状态板消失后,该不变量的承担者是网关自身的端口解析链,
# 已由 tests/test_presence_ipc_port_and_speaking_phase.py 等覆盖。
