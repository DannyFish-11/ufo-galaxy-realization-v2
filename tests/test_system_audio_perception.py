"""系统播放声(回环)采集 + 感知库独立槽位的行为测试。

为什么这一路必须存在、而且必须单独存在
--------------------------------------
麦克风回答"用户说了什么";系统播放声回答"用户此刻在听什么"(视频/网课/游戏/会议)。
两者语义完全不同,合成一槽会互相覆盖,而且一旦混流就再也分不出"这段声音是人说的还是
扬声器放的"—— 那恰恰是模型最需要区分的一件事,也是反自激励门存在的原因。

这一路无法从浏览器侧拿到:``getUserMedia`` 只给输入设备,``getDisplayMedia`` 要每次
手动选窗口且跨浏览器支持残缺。所以只能在电脑端本机采集。**这是能力差异,不是性能
优化。**

本文件的两个重点
----------------
1. **设备解析逻辑**抽成了纯函数,可以用假设备表完整覆盖 —— 不必等到有 Windows 机器
   才能验证"到底会挑中哪个设备、挑不中时给什么原因"。
2. **新槽位没有绕过隐私闸门。** 系统声比麦克风更敏感(等于把用户正在听的一切完整送
   出去),所以每条写路径和读路径都必须逐条断言,而不是相信"它应该也被挡住了"。
"""

from __future__ import annotations

import time

import pytest

from core.multimodal.system_audio_ingest import (
    REASON_NO_LOOPBACK_DEVICE,
    REASON_NO_WASAPI_HOSTAPI,
    REASON_NO_WASAPI_SUPPORT,
    REASON_OK,
    REASON_UNSUPPORTED_OS,
    downmix_to_mono,
    probe,
    resolve_loopback_target,
)

# 鉴权默认已开（core/auth.py：只要存在一条公网可达的路，"只在局域网里"这个前提
# 就没了）。下面这些端点自带 ``Depends(require_auth)``/中间件，裸 TestClient 一律
# 401 —— 那样每条断言都停在鉴权上，考不到本来要考的东西。带上 conftest 的会话令牌。
from tests.conftest import GALAXY_TEST_API_TOKEN  # noqa: E402

_AUTH_HEADERS = {"Authorization": f"Bearer {GALAXY_TEST_API_TOKEN}"}


# ── 假设备表(形状与 sounddevice 的 query_devices()/query_hostapis() 一致)──────

WIN_HOSTAPIS = [
    {"name": "MME", "default_output_device": 4},
    {"name": "Windows WASAPI", "default_output_device": 7, "default_input_device": 6},
]
WIN_DEVICES = [
    {"name": "Mic (MME)", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "out-a", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "out-b", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "out-c", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Speakers (MME)", "hostapi": 0, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Other WASAPI out", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
    {"name": "Microphone (WASAPI)", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Speakers (Realtek) WASAPI", "hostapi": 1, "max_input_channels": 0, "max_output_channels": 2},
]
LINUX_HOSTAPIS = [{"name": "ALSA"}]
LINUX_DEVICES = [
    {"name": "HDA Intel PCH", "hostapi": 0, "max_input_channels": 2, "max_output_channels": 0},
    {
        "name": "Monitor of Built-in Audio Analog Stereo",
        "hostapi": 0,
        "max_input_channels": 2,
        "max_output_channels": 0,
    },
]


class TestDeviceResolutionOnWindows:
    def test_picks_the_wasapi_default_output_device(self):
        """回环要打开的是【输出】设备,而且应当优先默认输出 —— 那才是用户真正在听的
        那一个。挑错设备的症状是"采到一片静音",极难排查。"""
        target, reason = resolve_loopback_target(WIN_DEVICES, WIN_HOSTAPIS, os_name="Windows", has_wasapi_settings=True)
        assert reason == REASON_OK
        assert target is not None
        assert target.device == 7, "必须是 WASAPI hostapi 的默认输出设备"
        assert target.needs_wasapi_loopback is True
        assert WIN_DEVICES[target.device]["max_output_channels"] > 0

    def test_falls_back_to_enumeration_when_there_is_no_default_output(self):
        hostapis = [{"name": "MME"}, {"name": "Windows WASAPI", "default_output_device": -1}]
        target, reason = resolve_loopback_target(WIN_DEVICES, hostapis, os_name="Windows", has_wasapi_settings=True)
        assert reason == REASON_OK
        assert target is not None
        assert WIN_DEVICES[target.device]["hostapi"] == 1
        assert WIN_DEVICES[target.device]["max_output_channels"] > 0

    def test_old_sounddevice_reports_a_fixable_reason(self):
        """PortAudio 支持但 sounddevice 太老没暴露 WasapiSettings —— 这是最容易踩的坑,
        必须给出"升级 sounddevice"这个明确原因,不能笼统地说"不支持"。"""
        target, reason = resolve_loopback_target(
            WIN_DEVICES, WIN_HOSTAPIS, os_name="Windows", has_wasapi_settings=False
        )
        assert target is None
        assert reason == REASON_NO_WASAPI_SUPPORT

    def test_missing_wasapi_hostapi_is_distinguished_from_missing_device(self):
        target, reason = resolve_loopback_target(
            WIN_DEVICES, [{"name": "MME"}], os_name="Windows", has_wasapi_settings=True
        )
        assert target is None
        assert reason == REASON_NO_WASAPI_HOSTAPI

    def test_input_only_host_finds_nothing(self):
        devices = [{"name": "Mic", "hostapi": 1, "max_input_channels": 2, "max_output_channels": 0}]
        target, reason = resolve_loopback_target(
            devices,
            [{"name": "MME"}, {"name": "Windows WASAPI"}],
            os_name="Windows",
            has_wasapi_settings=True,
        )
        assert target is None
        assert reason == REASON_NO_LOOPBACK_DEVICE


class TestDeviceResolutionElsewhere:
    def test_linux_uses_the_pulseaudio_monitor_source(self):
        """Linux 上 monitor 源是普通【输入】设备,不需要 WASAPI 那套 extra_settings。"""
        target, reason = resolve_loopback_target(
            LINUX_DEVICES, LINUX_HOSTAPIS, os_name="Linux", has_wasapi_settings=False
        )
        assert reason == REASON_OK
        assert target is not None
        assert target.device == 1
        assert target.needs_wasapi_loopback is False

    def test_linux_without_a_monitor_source(self):
        target, reason = resolve_loopback_target(
            [LINUX_DEVICES[0]], LINUX_HOSTAPIS, os_name="Linux", has_wasapi_settings=False
        )
        assert target is None
        assert reason == REASON_NO_LOOPBACK_DEVICE

    def test_macos_has_no_system_level_loopback(self):
        target, reason = resolve_loopback_target(
            LINUX_DEVICES, [{"name": "CoreAudio"}], os_name="Darwin", has_wasapi_settings=False
        )
        assert target is None
        assert reason == REASON_UNSUPPORTED_OS


class TestProbeDegradesGracefully:
    def test_probe_never_raises_and_always_explains_itself(self):
        """探测结果要么可用,要么带一句**可执行的**原因。静默的 False 等于让用户
        面对"模型不知道我在看什么"却查不到任何线索。"""
        result = probe()
        assert set(result) >= {"available", "reason", "reason_text", "os"}
        assert isinstance(result["available"], bool)
        assert result["reason_text"], "不可用时必须给出人能看懂的原因"

    def test_missing_sounddevice_is_not_treated_as_an_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def _no_sounddevice(name, *args, **kwargs):
            if name == "sounddevice":
                raise ImportError("No module named 'sounddevice'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", _no_sounddevice)
        result = probe()
        assert result["available"] is False
        assert "sounddevice" in result["reason"]


class TestDownmix:
    def test_stereo_is_averaged_to_mono(self):
        np = pytest.importorskip("numpy")
        stereo = np.array([[1.0, 3.0], [2.0, 4.0]], dtype="float32")
        assert downmix_to_mono(stereo).tolist() == [2.0, 3.0]

    def test_mono_shapes_pass_through(self):
        np = pytest.importorskip("numpy")
        assert downmix_to_mono(np.array([1.0, 2.0], dtype="float32")).tolist() == [1.0, 2.0]
        assert downmix_to_mono(np.array([[1.0], [2.0]], dtype="float32")).tolist() == [1.0, 2.0]


# ── 感知库:独立槽位 ─────────────────────────────────────────────────────────


@pytest.fixture
def store():
    from core.perception.desktop_perception_store import DesktopPerceptionStore

    return DesktopPerceptionStore()


class TestSeparateSlot:
    def test_system_audio_does_not_overwrite_the_microphone(self, store):
        """两路混一槽的话后到的会覆盖先到的,模型就只能拿到其中一路。"""
        store.update_audio("MIC")
        store.update_system_audio("SYS")
        snap = store.snapshot_media()
        assert snap["audio_b64"] == "MIC"
        assert snap["system_audio_b64"] == "SYS"

    def test_both_reach_the_model_with_distinguishable_sources(self, store):
        """source 必须能区分,否则模型无从判断"这段是人在说话"还是"屏幕里在放"。"""
        store.update_audio("MIC")
        store.update_system_audio("SYS")
        ctx = store.build_multimodal_context()
        assert ctx is not None
        assert [(a.source, a.data) for a in ctx.audio] == [
            ("desktop_microphone", "MIC"),
            ("desktop_system_audio", "SYS"),
        ]
        assert "system_audio" in ctx.metadata["modalities"]

    def test_system_audio_alone_still_triggers_injection(self, store):
        """只有系统声、没有任何其它模态时也必须注入 —— 否则"用户在看视频、没说话、
        没动屏幕"这个最典型的陪看场景里,这一路等于没接。"""
        store.update_system_audio("ONLY-SYS")
        ctx = store.build_multimodal_context()
        assert ctx is not None
        assert ctx.metadata["modalities"] == ["system_audio"]

    def test_stale_system_audio_is_not_injected(self, store):
        store.update_system_audio("OLD")
        store._sys_audio_ts = time.time() - (store.ttl_sec + 5)
        assert store.build_multimodal_context() is None
        assert store.snapshot_media()["system_audio_b64"] is None

    def test_autoinject_watermarks_are_independent(self, store):
        """共用一个消费水位会让先到的那路把后到的一起标记为"已消费",另一路从此
        永远取不到东西。"""
        store.update_audio("MIC")
        store.update_system_audio("SYS")
        assert store.take_fresh_audio_for_autoinject() == ("MIC", "audio/webm")
        assert store.take_fresh_system_audio_for_autoinject() == ("SYS", "audio/webm")
        # 同一片段不重复消费
        assert store.take_fresh_audio_for_autoinject() == (None, None)
        assert store.take_fresh_system_audio_for_autoinject() == (None, None)

    def test_counters_are_tracked_separately(self, store):
        store.update_system_audio("A")
        store.update_system_audio("B")
        status = store.status()
        assert status["system_audio_received"] == 2
        assert status["audio_received"] == 0


class TestSystemAudioHonoursThePrivacyGate:
    """系统声比麦克风更敏感 —— 它等于把用户正在听的一切内容(会议、私信语音、视频)
    完整送出去。所以它必须走**同一道**闸门,不能另开旁路。逐条枚举,不靠推测。"""

    def test_writes_are_rejected_while_paused(self, store):
        store.pause("test")
        store.update_system_audio("LEAK")
        assert store.privacy_status()["rejected_system_audio"] == 1
        assert store.snapshot_media()["system_audio_b64"] is None

    def test_pause_wipes_already_cached_system_audio(self, store):
        store.update_system_audio("SECRET")
        store.pause("test")
        store.resume("test")  # 恢复后也不能重新读到暂停前那一段
        assert store.snapshot_media()["system_audio_b64"] is None

    @pytest.mark.parametrize(
        "read",
        [
            lambda s: s.snapshot_media()["system_audio_b64"],
            lambda s: s.take_fresh_system_audio_for_autoinject()[0],
            lambda s: s.build_multimodal_context(),
        ],
    )
    def test_read_gates_hold_independently_of_the_wipe(self, store, read):
        """pause() 会清缓存,所以"读到空"可能只是因为缓存空了,而不是因为读闸门存在。
        这里在暂停之后**绕过写闸门**直接把内部缓冲填满,单独检验第二道防线 ——
        否则某条读路径漏了闸门,测试也会因为清缓存而误报通过。"""
        store.pause("test")
        store._sys_audio_b64 = "FORCED-INTO-CACHE"
        store._sys_audio_ts = time.time()
        assert read(store) is None

    def test_status_exposes_the_rejection_counter(self, store):
        store.pause("test")
        store.update_system_audio("X")
        store.update_system_audio("Y")
        assert store.status()["privacy"]["rejected_system_audio"] == 2


# ── 路由接线 ─────────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from core.routes.perception import create_router

    app = FastAPI()
    app.include_router(create_router())
    return TestClient(app, headers=_AUTH_HEADERS)


class TestRoutes:
    def test_ingest_stores_into_the_system_audio_slot(self, client):
        from core.perception.desktop_perception_store import get_desktop_perception_store

        store = get_desktop_perception_store()
        store.resume("test-setup")
        before = store.status()["system_audio_received"]
        resp = client.post("/api/perception/desktop/system_audio", json={"audio_base64": "AAA"})
        assert resp.json() == {"success": True, "stored": "system_audio"}
        assert store.status()["system_audio_received"] == before + 1

    def test_ingest_reports_rejection_honestly_while_paused(self, client):
        """暂停期间若照旧回 stored=... ,采集端会以为存进去了而继续按原节奏推送。
        必须如实告知被丢弃,客户端才能降频或提示用户"感知已暂停"。"""
        from core.perception.desktop_perception_store import get_desktop_perception_store

        store = get_desktop_perception_store()
        store.pause("test")
        try:
            body = client.post("/api/perception/desktop/system_audio", json={"audio_base64": "BBB"}).json()
            assert body["success"] is False
            assert body["privacy_paused"] is True
            assert body["stored"] is None
        finally:
            store.resume("test")

    def test_probe_endpoint_answers_with_a_reason(self, client):
        body = client.get("/api/perception/desktop/system_audio/probe").json()
        assert body["success"] is True
        assert isinstance(body["available"], bool)
        assert body["reason_text"]

    def test_status_exposes_system_audio_freshness(self, client):
        store_status = client.get("/api/perception/desktop/status").json()["store"]
        assert "system_audio_received" in store_status
        assert "system_audio_fresh" in store_status
        assert "system_audio_age_sec" in store_status


class TestInternalErrorsDoNotLeakImplementationDetail:
    """把 ``str(exc)`` 回给调用方会泄露文件路径、模块名等实现细节
    (CodeQL "Information exposure through an exception")。

    响应里只能有稳定的 ``error_code``;真正的堆栈用 ``exc_info=True`` 留在服务端日志里 ——
    排查能力不打折,但不经由 HTTP 响应外泄。
    """

    _SECRETY = "/home/somebody/private/module.py 内部细节"

    def test_ingest_error_response_carries_no_exception_text(self, client, monkeypatch, caplog):
        import core.perception.desktop_perception_store as store_mod

        def _boom():
            raise RuntimeError(self._SECRETY)

        monkeypatch.setattr(store_mod, "get_desktop_perception_store", _boom)
        with caplog.at_level("ERROR"):
            body = client.post("/api/perception/desktop/system_audio", json={"audio_base64": "A"}).json()

        assert body["success"] is False
        assert body["error_code"] == "system_audio_ingest"
        assert self._SECRETY not in str(body)
        assert "/home/" not in str(body)
        assert self._SECRETY in caplog.text, "细节必须仍然留在服务端日志里,否则等于丢了排查能力"

    def test_probe_error_response_carries_no_exception_text(self, client, monkeypatch, caplog):
        import core.multimodal.system_audio_ingest as ingest_mod

        def _boom():
            raise RuntimeError(self._SECRETY)

        monkeypatch.setattr(ingest_mod, "probe", _boom)
        with caplog.at_level("ERROR"):
            body = client.get("/api/perception/desktop/system_audio/probe").json()

        assert body["success"] is False
        assert body["available"] is False, "探测失败必须明确回不可用,不能含糊"
        assert body["error_code"] == "system_audio_probe"
        assert self._SECRETY not in str(body)
        assert self._SECRETY in caplog.text
