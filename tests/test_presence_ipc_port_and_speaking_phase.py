"""tests/test_presence_ipc_port_and_speaking_phase.py
=======================================================
桌面覆盖层"第二态说话动画换不起来"的根因回归防护(阶段1 a/b)。

根因 a(决定性):Python 在场桥 POST 到端口 9229,而 Electron overlay 监听 9231
(GALAXY_IPC_PORT)。overlay 只走 IPC、无 WS 兜底 → 收不到任何后端状态 → 冻在硬编码
SILENT 默认。shader 的收回/灵动岛/阈限空间动画本已实现,只是没数据。
修:桥与 Electron【同读 GALAXY_IPC_PORT、同默认 9231】。

根因 b(语义):TTS 在相位已回 SILENT 之后才发声,说话期 phase="static" —— 话没说完,
画面先睡了。修:_build_message 在 speaking 时不报静息。

**报的是 manifest,不是 liminal。** 这里原先报 liminal,是给已删掉的 React 面板
(usePhase 只认 phase 字符串)打的补丁。换成双轴契约之后,liminal 在覆盖层上就是
沙盘空间:每次语音回答,空间收回去刚开始执行,又因为开口说话被重新推开一遍,念完才
消散 —— 一句回答,空间开合两次。朗读是对外表达,生命周期文档里 manifest 就写着
"出字、控设备"。
"""

from __future__ import annotations

import core.lumiv_websocket_bridge as bridge_mod
from core.lumiv_websocket_bridge import GalaxyPresenceBridge, resolve_electron_ipc_port


# ── a. 端口契约 ─────────────────────────────────────────────────────────────
def test_ipc_port_defaults_to_9231_matching_electron():
    assert resolve_electron_ipc_port({}) == 9231, "默认必须与 electron/main.js 的 9231 一致"


def test_ipc_port_reads_galaxy_ipc_port():
    assert resolve_electron_ipc_port({"GALAXY_IPC_PORT": "9300"}) == 9300


def test_ipc_port_legacy_electron_port_takes_precedence():
    env = {"GALAXY_ELECTRON_PORT": "9400", "GALAXY_IPC_PORT": "9300"}
    assert resolve_electron_ipc_port(env) == 9400


def test_ipc_port_invalid_falls_back_to_default():
    assert resolve_electron_ipc_port({"GALAXY_IPC_PORT": "not-a-port"}) == 9231


def test_module_default_url_uses_9231():
    # 模块级默认(无 env 覆盖时)必须落在 9231,而非旧的 9229。
    assert resolve_electron_ipc_port() in (9231,) or "GALAXY_IPC_PORT" in __import__("os").environ


# ── b. 说话 → 表达(manifest)语义 ──────────────────────────────────────────
def test_build_message_reports_manifest_phase_while_speaking():
    b = GalaxyPresenceBridge.get_instance()
    saved = (b._current_mode, b._current_depth, b._speaking)
    try:
        b._current_mode = "static"
        b._current_depth = 0.05
        b._speaking = False
        # 未说话:phase 就是当前 static
        msg = b._build_message()
        assert msg["payload"]["phase"] == "static"

        # 说话:即使相位已回 static,phase/mode 也报 manifest(朗读是表达),depth 抬到表达地板
        msg2 = b._build_message(speaking_override=True)
        p = msg2["payload"]
        assert p["phase"] == "manifest", "说话时报的是表达 —— 报 liminal 会让覆盖层把沙盘重新推开"
        assert p["mode"] == "manifest"
        assert p["speaking"] is True
        assert p["depth_factor"] >= bridge_mod.MODE_DEPTH_MAP["manifest"] - 1e-9
        # 主轴同样是表达;渲染契约与遗留 phase 必须说同一件事。
        assert p["render"]["lifecycle"] == "manifest"
    finally:
        b._current_mode, b._current_depth, b._speaking = saved


def test_build_message_keeps_manifest_phase_when_speaking_during_manifest():
    # 说话发生在 manifest(执行中)时照实报 manifest。
    b = GalaxyPresenceBridge.get_instance()
    saved = (b._current_mode, b._current_depth, b._speaking)
    try:
        b._current_mode = "manifest"
        b._current_depth = 0.92
        msg = b._build_message(speaking_override=True)
        assert msg["payload"]["phase"] == "manifest"
    finally:
        b._current_mode, b._current_depth, b._speaking = saved


def test_speaking_does_not_mask_a_real_liminal_phase():
    """只提升 static。相位本来就在 liminal(上一句还在念、新请求已经进来审议)时照实报,
    不拿"在说话"去盖掉真实的相位。"""
    b = GalaxyPresenceBridge.get_instance()
    saved = (b._current_mode, b._current_depth, b._speaking)
    try:
        b._current_mode = "liminal"
        b._current_depth = 0.62
        msg = b._build_message(speaking_override=True)
        assert msg["payload"]["phase"] == "liminal"
    finally:
        b._current_mode, b._current_depth, b._speaking = saved
