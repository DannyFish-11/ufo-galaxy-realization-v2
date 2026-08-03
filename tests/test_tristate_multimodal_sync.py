"""三态×多模态一致性(动画随真实输入输出自然过渡)测试
============================================================

用户反馈的核查点:三态过渡是否自然、是否真的伴随多模态输入输出。
钉住两处根修:

  1. **speaking 生命周期归属**:相位切换(phase.silent/manifest)绝不踩掉
     speaking——它由 speech_output 的 set_ai_speaking(播放起止)全权管理。
     否则"响应文本一好 runtime 回 SILENT,TTS 还在播,嘴在动、动画已灭"。
     且说话期间桥端维持可见的在场深度地板,说完才自然缓落。
  2. **MANIFEST=首输出**:流式请求在第一个 token 流出的瞬间才 LIMINAL→MANIFEST,
     LLM 思考期(CPU 机上数十秒)停留在 LIMINAL(思考动画),不再"拿到车道
     就 manifest、阈限态几毫秒被跳过"。非流式调用保持原时序;零输出请求
     仍补齐 canonical 三段轨迹(liminal→manifest→silent)。
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. 桥端:speaking 不被相位踩灭 + 说话深度地板
# ---------------------------------------------------------------------------


class TestBridgeSpeakingOwnership:
    @pytest.mark.asyncio
    async def test_phase_silent_does_not_stomp_speaking(self):
        from core.lumiv_websocket_bridge import GalaxyPresenceBridge

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._loop = asyncio.get_running_loop()
        bridge._speaking = True  # TTS 播放中(set_ai_speaking(True) 已置)

        bridge._on_phase_silent({})  # 响应完成,runtime 回 SILENT
        assert bridge._speaking is True, "相位切换不得踩掉 speaking(播放未结束)"
        assert bridge._current_mode == "static"

        bridge._on_phase_manifest({})
        assert bridge._speaking is True

        bridge._speaking = False  # 复位,不污染其它测试

    @pytest.mark.asyncio
    async def test_speaking_floor_holds_visible_depth(self):
        """SILENT+speaking:广播的 depth 维持地板(≥liminal),说完落回相位深度。"""
        from core.lumiv_websocket_bridge import (
            MODE_DEPTH_MAP,
            GalaxyPresenceBridge,
        )

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._loop = asyncio.get_running_loop()
        bridge._on_phase_silent({})

        # 先取"没在说话时"的相位深度作基准。刻意不写死 MODE_DEPTH_MAP["static"]:
        # 深度现在由 core.phase_contract 从活的 ContinuumState 导出(塌缩/回撤倾向
        # 决定它在相位带内的位置),只有拿不到连续量时才恰好等于锚点。写死常数的
        # 断言在"进程里碰巧有活 continuum"的场景下会假红 —— 而那正是生产的常态。
        bridge._speaking = False
        baseline = bridge._build_message()["payload"]["depth_factor"]

        bridge._speaking = True
        msg = bridge._build_message()
        assert msg["payload"]["depth_factor"] >= MODE_DEPTH_MAP["liminal"], "说话中即使相位已静默,也要维持可见在场深度"
        assert msg["payload"]["speaking"] is True

        bridge._speaking = False
        msg = bridge._build_message()
        assert msg["payload"]["depth_factor"] == baseline, "说完自然落回相位深度(渲染端弹簧缓落)"

    @pytest.mark.asyncio
    async def test_manifest_depth_not_lowered_by_floor(self):
        """MANIFEST(0.92)本就高于地板:地板只抬不压。"""
        from core.lumiv_websocket_bridge import (
            MODE_DEPTH_MAP,
            GalaxyPresenceBridge,
        )

        bridge = GalaxyPresenceBridge.get_instance()
        bridge._loop = asyncio.get_running_loop()
        bridge._on_phase_manifest({})

        # "只抬不压"是一条【关系】,直接测这个关系,而不是钉某个常数:
        # 说话前后各取一次深度,断言说话没有把它压下去。
        #
        # 原断言是 depth == MODE_DEPTH_MAP["manifest"]（恒等于 0.92）。那在深度
        # 还是查表时成立,现在深度由 core.phase_contract 从活的 ContinuumState
        # 导出——manifest 带内会随 retreat_tendency 下移(实测 0.866)。测出来的
        # "不等于 0.92"其实是设计如此,不是回归;而"地板压低了 manifest"才是这条
        # 测试真正要防的事,那个性质完全没变。
        bridge._speaking = False
        without_floor = bridge._build_message()["payload"]["depth_factor"]

        bridge._speaking = True
        with_floor = bridge._build_message()["payload"]["depth_factor"]

        assert with_floor >= without_floor, "说话地板把 MANIFEST 的深度压低了 —— 地板只该抬,不该压"
        assert with_floor >= MODE_DEPTH_MAP["liminal"], "说话中深度必须在可见地板之上"

        bridge._speaking = False
        bridge._on_phase_silent({})


# ---------------------------------------------------------------------------
# 2. runtime:MANIFEST 由首输出驱动
# ---------------------------------------------------------------------------


def _phase_recorder():
    """订阅三个相位事件,返回 (记录列表, 退订函数)。"""
    from core.state_event_bus import get_state_event_bus

    bus = get_state_event_bus()
    seen = []
    tokens = [
        bus.subscribe(name, lambda e, _n=name: seen.append(_n.split(".")[1]))
        for name in ("phase.silent", "phase.liminal", "phase.manifest")
    ]

    def _cleanup():
        for t in tokens:
            try:
                bus.unsubscribe(t)
            except Exception:  # noqa: BLE001
                pass

    return seen, _cleanup


def _ok_result():
    return {"success": True, "response": "OK", "intent": "chat", "metadata": {"session_id": "s1"}}


class TestManifestOnFirstToken:
    @pytest.mark.asyncio
    async def test_streaming_manifest_fires_at_first_delta(self, monkeypatch):
        """流式请求:process 期间(思考)保持 LIMINAL;第一段文本流出瞬间进 MANIFEST。"""
        monkeypatch.setenv("GALAXY_MANIFEST_ON_FIRST_TOKEN", "1")
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.llm_stream import TokenStream, use_stream

        rt = DesktopPresenceRuntime()
        seen, cleanup = _phase_recorder()
        sink = TokenStream(on_delta=lambda t: None)
        phase_at_feed = {}

        async def _mock_process(**kwargs):
            # 思考期:尚未流出任何 token → 不得已进 MANIFEST
            phase_at_feed["before"] = list(seen)
            sink.feed("第一段")  # ← 首输出瞬间
            phase_at_feed["after"] = list(seen)
            return _ok_result()

        try:
            with patch("core.openclawd.get_openclawd") as mock_get:
                mock_clawd = MagicMock()
                mock_clawd.process = AsyncMock(side_effect=_mock_process)
                mock_get.return_value = mock_clawd
                with use_stream(sink):
                    result = await rt.handle_request(message="hi", source="chat")
        finally:
            cleanup()

        assert result["tristate"] == "silent"
        assert "manifest" not in phase_at_feed["before"], "思考期(无输出)不得提前进 MANIFEST"
        assert "manifest" in phase_at_feed["after"], "首 token 流出瞬间必须进 MANIFEST"
        # canonical 三段轨迹完整且有序
        assert seen.index("liminal") < seen.index("manifest") < seen.index("silent")

    @pytest.mark.asyncio
    async def test_streaming_sink_callback_restored_after_request(self, monkeypatch):
        monkeypatch.setenv("GALAXY_MANIFEST_ON_FIRST_TOKEN", "1")
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.llm_stream import TokenStream, use_stream

        rt = DesktopPresenceRuntime()
        orig_cb = lambda t: None  # noqa: E731
        sink = TokenStream(on_delta=orig_cb)

        with patch("core.openclawd.get_openclawd") as mock_get:
            mock_clawd = MagicMock()
            mock_clawd.process = AsyncMock(return_value=_ok_result())
            mock_get.return_value = mock_clawd
            with use_stream(sink):
                await rt.handle_request(message="hi", source="chat")

        assert sink._on_delta is orig_cb, "请求结束必须恢复 sink 回调(伪流式兜底不得触发死会话的相位钩子)"

    @pytest.mark.asyncio
    async def test_zero_output_request_still_emits_canonical_order(self, monkeypatch):
        """整个请求零输出(如异常):仍补齐 liminal→manifest→silent。"""
        monkeypatch.setenv("GALAXY_MANIFEST_ON_FIRST_TOKEN", "1")
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.llm_stream import TokenStream, use_stream

        rt = DesktopPresenceRuntime()
        seen, cleanup = _phase_recorder()
        sink = TokenStream(on_delta=lambda t: None)

        try:
            with patch("core.openclawd.get_openclawd") as mock_get:
                mock_clawd = MagicMock()
                mock_clawd.process = AsyncMock(side_effect=RuntimeError("boom"))
                mock_get.return_value = mock_clawd
                with use_stream(sink):
                    result = await rt.handle_request(message="hi", source="chat")
        finally:
            cleanup()

        assert result["tristate"] == "silent"
        assert seen.index("liminal") < seen.index("manifest") < seen.index("silent")

    @pytest.mark.asyncio
    async def test_non_streaming_keeps_original_timing(self, monkeypatch):
        """非流式调用:保持旧时序——派发前就已在 MANIFEST。"""
        monkeypatch.setenv("GALAXY_MANIFEST_ON_FIRST_TOKEN", "1")
        from core.desktop_presence_runtime import DesktopPresenceRuntime

        rt = DesktopPresenceRuntime()
        seen, cleanup = _phase_recorder()
        manifest_before_process = {}

        async def _mock_process(**kwargs):
            manifest_before_process["v"] = "manifest" in seen
            return _ok_result()

        try:
            with patch("core.openclawd.get_openclawd") as mock_get:
                mock_clawd = MagicMock()
                mock_clawd.process = AsyncMock(side_effect=_mock_process)
                mock_get.return_value = mock_clawd
                result = await rt.handle_request(message="hi", source="chat")
        finally:
            cleanup()

        assert manifest_before_process["v"] is True
        assert result["tristate"] == "silent"

    @pytest.mark.asyncio
    async def test_kill_switch_reverts_to_old_behavior(self, monkeypatch):
        """GALAXY_MANIFEST_ON_FIRST_TOKEN=0:流式也回旧时序(派发前 MANIFEST)。"""
        monkeypatch.setenv("GALAXY_MANIFEST_ON_FIRST_TOKEN", "0")
        from core.desktop_presence_runtime import DesktopPresenceRuntime
        from core.llm_stream import TokenStream, use_stream

        rt = DesktopPresenceRuntime()
        seen, cleanup = _phase_recorder()
        manifest_before_process = {}

        async def _mock_process(**kwargs):
            manifest_before_process["v"] = "manifest" in seen
            return _ok_result()

        try:
            with patch("core.openclawd.get_openclawd") as mock_get:
                mock_clawd = MagicMock()
                mock_clawd.process = AsyncMock(side_effect=_mock_process)
                mock_get.return_value = mock_clawd
                with use_stream(TokenStream(on_delta=lambda t: None)):
                    await rt.handle_request(message="hi", source="chat")
        finally:
            cleanup()

        assert manifest_before_process["v"] is True
