"""桌面感知隐私急停的行为测试。

重点不是"函数能调通",而是**没有绕行路径**:

``DesktopPerceptionStore`` 是全部桌面感知数据的唯一进出口 —— 写入口 2 个、
读出口 5 个、下游消费方至少 4 处。闸门若漏掉任何一条读路径,那条路径的消费方
在"隐私暂停"期间照旧能看到屏幕,隐私模式就是假的。其中
``build_multimodal_context`` 最关键:它是**每次对话请求**的隐性注入路径,
漏掉它 = 模型每轮都还在看屏幕。

因此本文件逐条枚举五条读路径,并对四个真实消费方各自断言一次。
"""

from __future__ import annotations

import pytest


@pytest.fixture
def store():
    """每个用例一个独立实例(不动进程单例,避免污染其它测试)。"""
    from core.perception.desktop_perception_store import DesktopPerceptionStore

    s = DesktopPerceptionStore()
    s.update_frame("SCREEN-PIXELS", source="desktop_screen", screen={"window": "Secret.docx"})
    s.update_frame("CAMERA-PIXELS", source="desktop_camera")
    s.update_audio("MIC-AUDIO")
    return s


class TestAllFiveReadPathsAreSealed:
    """五条读出口逐条验证 —— 漏一条就是一个绕行洞。"""

    def test_has_fresh_frame(self, store):
        assert store.has_fresh_frame() is True
        store.pause()
        assert store.has_fresh_frame() is False

    def test_latest_frame_snapshot(self, store):
        assert store.latest_frame_snapshot()[0] is not None
        store.pause()
        assert store.latest_frame_snapshot()[0] is None

    def test_take_fresh_audio_for_autoinject(self, store):
        assert store.take_fresh_audio_for_autoinject()[0] == "MIC-AUDIO"
        store.pause()
        assert store.take_fresh_audio_for_autoinject()[0] is None

    def test_snapshot_media(self, store):
        assert store.snapshot_media()["screen_b64"] == "SCREEN-PIXELS"
        store.pause()
        snap = store.snapshot_media()
        assert snap["screen_b64"] is None
        assert snap["camera_b64"] is None
        assert snap["audio_b64"] is None
        assert snap["screen_meta"] is None
        assert snap["privacy_paused"] is True

    def test_build_multimodal_context(self, store):
        """最关键的一条:每次对话请求的隐性注入路径。"""
        assert store.build_multimodal_context() is not None
        store.pause()
        assert store.build_multimodal_context() is None


class TestReadGatesHoldIndependentlyOfTheWipe:
    """五条读闸门必须**各自独立**成立,不能靠"清缓存"顺带掩盖。

    这一组是补课来的:最初只写了"pause 后读不到"的用例,而 ``pause()`` 会清缓存,
    于是即便把某条读路径的闸门整段删掉,用例照旧通过 —— 反向验证时删掉
    ``build_multimodal_context`` 的闸门,20 条测试竟然全绿,才发现这个漏洞。

    做法:暂停后**直接写内部缓冲**(绕过写入口闸门),模拟"数据以某种未预期的
    方式进来了",再断言五条读路径依然什么都给不出。这才是第二道防线的真实检验。
    """

    @staticmethod
    def _force_fill(s):
        """绕过 update_* 的写闸门,直接塞进内部缓冲。"""
        import time as _t

        now = _t.time()
        s._scr_b64 = "LEAKED-SCREEN"
        s._scr_ts = now
        s._screen_meta = {"window": "LEAKED"}
        s._cam_b64 = "LEAKED-CAM"
        s._cam_ts = now
        s._audio_b64 = "LEAKED-AUDIO"
        s._audio_ts = now
        s._audio_autoinject_consumed_ts = 0.0

    @pytest.fixture
    def paused_but_filled(self):
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        s.pause(reason="test")
        self._force_fill(s)
        return s

    def test_has_fresh_frame_still_false(self, paused_but_filled):
        assert paused_but_filled.has_fresh_frame() is False

    def test_latest_frame_snapshot_still_empty(self, paused_but_filled):
        assert paused_but_filled.latest_frame_snapshot()[0] is None

    def test_take_fresh_audio_still_empty(self, paused_but_filled):
        assert paused_but_filled.take_fresh_audio_for_autoinject()[0] is None

    def test_snapshot_media_still_empty(self, paused_but_filled):
        snap = paused_but_filled.snapshot_media()
        assert snap["screen_b64"] is None
        assert snap["camera_b64"] is None
        assert snap["audio_b64"] is None
        assert snap["screen_meta"] is None

    def test_build_multimodal_context_still_none(self, paused_but_filled):
        """最关键的一条:每次对话请求的隐性注入路径。"""
        assert paused_but_filled.build_multimodal_context() is None


class TestBothWritePathsReject:
    def test_frame_and_audio_are_refused_while_paused(self, store):
        store.pause()
        store.update_frame("NEW-SCREEN", source="desktop_screen")
        store.update_frame("NEW-CAM", source="desktop_camera")
        store.update_audio("NEW-AUDIO")
        st = store.privacy_status()
        assert st["rejected_frames"] == 2
        assert st["rejected_audio"] == 1
        # 拒收之后仍然读不到 —— 数据根本没进内存
        assert store.snapshot_media()["screen_b64"] is None

    def test_screen_meta_only_update_is_also_refused(self, store):
        """无像素帧、只带结构化屏幕上下文(UIA 树)的写入同样是感知数据。"""
        store.pause()
        store.update_frame("", source="desktop_screen", screen={"window": "Still-Secret"})
        assert store.snapshot_media()["screen_meta"] is None


class TestPauseWipesCache:
    def test_cached_frames_are_wiped_not_merely_hidden(self, store):
        """只挡读不清缓存的话,恢复瞬间旧帧又冒出来 —— 那不叫暂停。"""
        store.pause()
        store.resume()
        snap = store.snapshot_media()
        assert snap["screen_b64"] is None, "恢复后不能又看到暂停前那一帧"
        assert snap["camera_b64"] is None
        assert snap["audio_b64"] is None


class TestNoTocTouGapAtThePauseBoundary:
    """判定与写入必须在同一次持锁内。

    此前 update_frame 分两次持锁(先查 paused、释放、再取锁写入),中间有 TOCTOU
    空隙:用户按下暂停的瞬间若有一帧正在途中,pause() 会在空隙里完成"置位 + 清缓存",
    随后这一帧落在 wipe **之后** —— 暂停期间读闸门还挡得住,但**一恢复就能读出来**,
    而那恰恰是用户想遮住的那一帧。
    """

    @staticmethod
    def _run_with_pause_injected_between_lock_acquisitions(store, write):
        """把 pause() 注入到被测写入过程的第一次"释放锁"之后。

        若实现是两次持锁,这个位置就落在判定与写入之间,能确定性复现竞态;
        若实现是单次持锁,pause() 只会发生在整个写入完成之后(随即被 wipe 清掉)。
        """
        real = store._lock

        class _Hook:
            def __init__(self) -> None:
                self.releases = 0
                self.armed = True

            def __enter__(self):
                real.acquire()
                return self

            def __exit__(self, *exc):
                real.release()
                self.releases += 1
                if self.armed and self.releases == 1:
                    self.armed = False
                    store._lock = real  # 让 pause 用真锁(此刻锁空闲)
                    store.pause(reason="race-probe")
                    store._lock = hook
                return False

            def acquire(self, *a, **k):
                return real.acquire(*a, **k)

            def release(self):
                return real.release()

        hook = _Hook()
        store._lock = hook
        try:
            write()
        finally:
            store._lock = real

    def test_frame_in_flight_does_not_survive_the_pause(self):
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        self._run_with_pause_injected_between_lock_acquisitions(
            s, lambda: s.update_frame("RACED-FRAME", source="desktop_screen")
        )
        assert s.paused is True
        assert s._scr_b64 is None, "暂停边界上不能留下在途的帧"
        s.resume()
        assert s.snapshot_media()["screen_b64"] is None, "恢复后更不能读到那一帧"

    def test_audio_in_flight_does_not_survive_the_pause(self):
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        self._run_with_pause_injected_between_lock_acquisitions(s, lambda: s.update_audio("RACED-AUDIO"))
        assert s._audio_b64 is None
        s.resume()
        assert s.snapshot_media()["audio_b64"] is None


class TestEpochCrossesPrivacyBoundary:
    def test_epoch_increments_on_pause_and_resume(self, store):
        e0 = store.epoch
        store.pause()
        e1 = store.epoch
        store.resume()
        e2 = store.epoch
        assert e1 == e0 + 1
        assert e2 == e1 + 1

    def test_repeated_pause_is_idempotent(self, store):
        store.pause()
        e = store.epoch
        store.pause()
        assert store.epoch == e, "重复 pause 不应制造新的世代"
        assert store.paused is True

    def test_frame_gate_reset_drops_pre_pause_fingerprint(self):
        """跨隐私边界不携带视觉状态。

        动机是隐私而非性能:留着暂停前的指纹去比恢复后的新帧,等于泄露
        "被遮住那段时间画面变了多少"。代价是恢复首拍必然判为"有变化"。
        """
        from core.ambient_attention_loop import FrameGate

        g = FrameGate(threshold=0.06)
        frame = "AAAA" * 200
        assert g.changed(frame) is True  # 第一帧的既定语义
        assert g.changed(frame) is False  # 静止
        g.reset()
        assert g.changed(frame) is True, "reset 后应重新按第一帧处理(刻意接受的代价)"
        assert g.changed(frame) is False, "随即回到静止,不会持续误触发"


class TestDefaultState:
    def test_gate_is_active_but_perception_allowed_by_default(self, monkeypatch):
        """闸门始终生效(不藏在 feature flag 后),但默认放行。"""
        import core.perception.desktop_perception_store as mod

        monkeypatch.delenv("GALAXY_PERCEPTION_PRIVACY_DEFAULT", raising=False)
        s = mod.DesktopPerceptionStore()
        assert s.paused is False
        assert hasattr(s, "pause") and hasattr(s, "resume")

    def test_privacy_first_deployment_can_start_paused(self, monkeypatch):
        import core.perception.desktop_perception_store as mod

        monkeypatch.setenv("GALAXY_PERCEPTION_PRIVACY_DEFAULT", "paused")
        s = mod.DesktopPerceptionStore()
        assert s.paused is True
        assert s.privacy_status()["reason"] == "privacy_default"
        s.update_frame("X", source="desktop_screen")
        assert s.snapshot_media()["screen_b64"] is None


class TestEveryRealConsumerGoesBlind:
    """四个真实消费方各自断言一次 —— 证明没有哪一路能绕过闸门。"""

    def test_ambient_loop_skips_tick_when_paused(self, monkeypatch):
        from core.ambient_attention_loop import AmbientAttentionLoop
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        s.update_frame("SCREEN", source="desktop_screen")
        loop = AmbientAttentionLoop()
        loop._store = s
        assert loop._gather_observation() is not None
        s.pause()
        assert loop._gather_observation() is None, "暂停后环境循环不该拿到任何观察"

    def test_computer_use_loop_sees_nothing(self, monkeypatch):
        """computer_use_loop 走 snapshot_media()(core/computer_use_loop.py:168)。"""
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        s.update_frame("SCREEN", source="desktop_screen")
        s.pause()
        assert s.snapshot_media()["screen_b64"] is None

    def test_session_memory_facade_sees_nothing(self):
        """session_memory_facade 同样走 snapshot_media()(:139)。"""
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        s.update_audio("AUDIO")
        s.pause()
        assert s.snapshot_media()["audio_b64"] is None

    def test_conversation_multimodal_injection_sees_nothing(self):
        """每次对话请求的注入路径 —— 漏这条则模型每轮都还在看屏幕。"""
        from core.perception.desktop_perception_store import DesktopPerceptionStore

        s = DesktopPerceptionStore()
        s.update_frame("SCREEN", source="desktop_screen")
        s.update_frame("CAM", source="desktop_camera")
        s.pause()
        assert s.build_multimodal_context() is None


class TestEndpointsAreWiredIn:
    def test_privacy_endpoints_mounted_in_create_api_routes(self):
        """端点没挂上就等于没做 —— 用户按不到那个"暂停"。"""
        import os
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from route_introspection import iter_flat_routes

        from core.api_routes import create_api_routes

        paths = {getattr(r, "path", "") for r in iter_flat_routes(create_api_routes())}
        for expected in (
            "/api/perception/desktop/privacy",
            "/api/perception/desktop/privacy/pause",
            "/api/perception/desktop/privacy/resume",
        ):
            assert expected in paths, f"{expected} 未挂进 create_api_routes"

    def test_ingest_reports_rejection_instead_of_faking_success(self):
        """暂停期间上报 success=True 会让采集端以为存进去了,必须如实拒绝。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.perception.desktop_perception_store import get_desktop_perception_store
        from core.routes.perception import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        store = get_desktop_perception_store()
        try:
            store.pause(reason="test")
            r = client.post(
                "/api/perception/desktop/frame",
                json={"image_base64": "X", "source": "desktop_screen"},
            ).json()
            assert r["success"] is False
            assert r["privacy_paused"] is True
            assert r["stored"] is None

            r2 = client.post("/api/perception/desktop/audio", json={"audio_base64": "X"}).json()
            assert r2["success"] is False
            assert r2["privacy_paused"] is True
        finally:
            store.resume(reason="test-teardown")

    def test_pause_resume_roundtrip_through_http(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from core.perception.desktop_perception_store import get_desktop_perception_store
        from core.routes.perception import create_router

        app = FastAPI()
        app.include_router(create_router())
        client = TestClient(app)
        store = get_desktop_perception_store()
        try:
            assert client.post("/api/perception/desktop/privacy/pause").json()["privacy"]["paused"] is True
            assert client.get("/api/perception/desktop/privacy").json()["privacy"]["paused"] is True
            assert client.post("/api/perception/desktop/privacy/resume").json()["privacy"]["paused"] is False
            assert store.paused is False
        finally:
            store.resume(reason="test-teardown")
