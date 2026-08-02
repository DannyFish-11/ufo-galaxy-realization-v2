"""常驻在场叫停 与 设备维模态协商的 HTTP 入口 —— 契约测试
=============================================================

为什么单开这个文件
-------------------
先前那两组能力(``halt_ambient_presence`` / ``negotiate(device=)``)在运行时里写完了、
单测也齐了,但审一遍调用方才发现**它们在生产里零调用点** —— 能力存在,却没有任何
一条真实路径会用到它。那和"定义了但没接"是同一件事:单测全绿,系统里什么也没发生。

所以这里验的不是"函数行为对不对"(那是 test_duplex_presence_bridge /
test_modality_capability_device_dim 的活),而是**接线在不在**:从 HTTP 打进去,
运行时那边是不是真的动了。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from core.routes.modality import router as modality_router
    from core.routes.operator import create_router as operator_create_router

    app = FastAPI()
    app.include_router(operator_create_router())
    app.include_router(modality_router)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def runtime(monkeypatch):
    """把端点用的运行时换成一个干净实例,不碰进程级单例。"""
    from core.desktop_presence_runtime import DesktopPresenceRuntime
    from core.desktop_presence_system import DesktopPresenceStateMachine

    rt = DesktopPresenceRuntime.__new__(DesktopPresenceRuntime)
    rt._active_sessions = {}
    rt._presence_state_machine = DesktopPresenceStateMachine()
    rt._latest_presence_runtime_hint = {}
    rt._latest_subject_projection = {}
    monkeypatch.setattr(
        "core.desktop_presence_runtime.get_desktop_presence_runtime",
        lambda: rt,
    )
    return rt


class TestAmbientPresenceEndpoints:
    def test_snapshot_reports_open_presences(self, client, runtime):
        runtime.open_ambient_presence("voice_duplex", reason="listening", on_halt=lambda: None)

        body = client.get("/api/v1/operator/presence/ambient").json()

        assert body["active"] == 1
        assert body["entries"][0]["source"] == "voice_duplex"
        assert body["all_haltable"] is True

    def test_snapshot_flags_a_presence_the_centre_cannot_stop(self, client, runtime):
        """没交叫停钩子的常驻通路必须在面板上可见 —— 那是接线漏了,不是配置。"""
        runtime.open_ambient_presence("mystery_channel")  # 故意不给 on_halt

        body = client.get("/api/v1/operator/presence/ambient").json()

        assert body["all_haltable"] is False
        assert body["entries"][0]["haltable"] is False

    def test_halt_closes_the_real_duplex_session(self, client, runtime, monkeypatch):
        """端到端:HTTP 打进去 → 那条实时 WebSocket 真的被关。

        这条是本文件的核心。端点返回 200 只证明它没崩;要证明**接上了**,必须
        看到 DuplexSession.close 被 await 过。
        """
        from core.duplex_presence_bridge import DuplexPresenceBridge

        session = MagicMock()
        session.close = AsyncMock()
        bridge = DuplexPresenceBridge(session, conversation_session_id="s1")

        import asyncio

        asyncio.get_event_loop_policy().new_event_loop()  # 保证 open() 有循环可用
        asyncio.run(bridge.open())
        assert runtime.ambient_presence_snapshot()["active"] == 1

        body = client.post("/api/v1/operator/presence/ambient/halt?reason=operator_stop").json()

        session.close.assert_awaited_once()
        assert body["halted"] == [bridge.presence_handle] if bridge.presence_handle else body["halted"]
        assert runtime.ambient_presence_snapshot()["active"] == 0

    def test_halt_is_idempotent_for_unknown_handle(self, client, runtime):
        body = client.post("/api/v1/operator/presence/ambient/halt?handle=never-existed").json()

        assert body["halted"] == []
        assert body["errors"] == {}

    def test_halt_reports_hook_failure_but_still_reclaims(self, client, runtime):
        async def _boom():
            raise RuntimeError("ws already dead")

        handle = runtime.open_ambient_presence("voice_duplex", on_halt=_boom)

        body = client.post("/api/v1/operator/presence/ambient/halt").json()

        assert body["halted"] == [handle]
        assert "ws already dead" in body["errors"][handle]
        assert runtime.ambient_presence_snapshot()["active"] == 0, "钩子失败也必须停下来"


class TestModalityDeviceEndpoints:
    def test_plan_without_device_is_unchanged(self, client):
        """不传 device_id 时结果与加入设备维之前一致(device_id 为空串)。"""
        body = client.get("/api/v1/modality/plan").json()

        assert body["success"] is True
        assert body["plan"]["device_id"] == ""

    def test_plan_accepts_device_id_and_carries_it(self, client, monkeypatch):
        import core.modality_capability as mod
        from core.unified.models import UnifiedDevice

        monkeypatch.setattr(
            mod,
            "_lookup_device",
            lambda did: UnifiedDevice(device_id=did, capabilities=["microphone", "speaker"]),
        )
        body = client.get("/api/v1/modality/plan?device_id=watch-1").json()

        assert body["plan"]["device_id"] == "watch-1"
        # 手表没摄像头 → 看被关掉,且如实标明是**设备**限制。
        assert body["plan"]["vision_in"]["mode"] == "unavailable"
        assert body["plan"]["vision_in"]["limited_by"] == "device"

    def test_device_matrix_answers_which_device_can_do_what(self, client, monkeypatch):
        """跨设备派发挑设备时问的就是这张表 —— 没有它只能派出去再等超时。

        ``capable`` 是**三维合起来**的答案("这台设备端到端能不能做"),所以它同时
        受模型档位与服务/桥现实影响:本机没装 ASR 桥时 audio_in 对谁都是不可用,
        和设备有没有麦克风无关。把期望写死成 ``["phone","watch"]`` 会在没装
        faster-whisper 的机器上假红 —— 那不是 bug,是这个函数本来就该这么答。

        所以基准取"不带设备的计划":某模态在后端层面就不可用时,``capable`` 必须是
        空的;后端可用时,才轮到设备维决定谁进名单。
        """
        from core.unified.models import UnifiedDevice

        devices = [
            UnifiedDevice(device_id="phone", capabilities=["camera", "microphone", "speaker", "screen"]),
            UnifiedDevice(device_id="watch", capabilities=["microphone", "speaker"]),
        ]

        class _UDM:
            def list_devices(self):
                return devices

        monkeypatch.setattr(
            "core.unified.device_manager.get_unified_device_manager",
            lambda: _UDM(),
        )
        baseline = client.get("/api/v1/modality/plan").json()["plan"]
        body = client.get("/api/v1/modality/devices").json()

        assert body["success"] is True
        assert body["device_count"] == 2

        for modality, expected_when_backend_ok in (
            ("vision_in", ["phone"]),  # 手表没摄像头
            ("video_in", ["phone"]),
            ("audio_in", ["phone", "watch"]),  # 两台都有麦克风
            ("audio_out", ["phone", "watch"]),
        ):
            expected = expected_when_backend_ok if baseline[modality]["usable"] else []
            assert body["capable"][modality] == expected, (
                f"{modality}: 后端 usable={baseline[modality]['usable']},"
                f" 期望 {expected},实得 {body['capable'][modality]}"
            )

        # 无论后端如何,手表都不可能进"能看"的名单 —— 这条与环境无关。
        assert "watch" not in body["capable"]["vision_in"]

    def test_matrix_distinguishes_no_hardware_from_no_declaration(self, client, monkeypatch):
        """ "设备没这个硬件"和"没人填过它的能力表"必须分得开。

        混在一起会让人以为设备坏了。前者靠 plan 里的 unavailable,后者靠
        gate.gating_active=false。
        """
        from core.unified.models import UnifiedDevice

        class _UDM:
            def list_devices(self):
                return [UnifiedDevice(device_id="unfilled", capabilities=[])]

        monkeypatch.setattr(
            "core.unified.device_manager.get_unified_device_manager",
            lambda: _UDM(),
        )
        body = client.get("/api/v1/modality/devices").json()
        row = body["devices"][0]

        assert row["gate"]["gating_active"] is False
        assert row["device_id"] in body["capable"]["vision_in"], "未申报 ≠ 不能做,不该被排除出可派发范围"
