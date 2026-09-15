"""画面上行：设备的视频轨真的进得了双工会话，而且挂断时真的停。

## 这条路以前到哪儿断了

`galaxy_gateway/voice_call_route.py` 的 `_on_track` 只认 `track.kind == "audio"`，
视频轨**静默丢弃** —— 设备推上来的画面进不了模型，而两端都没有任何现象。
`DuplexSession` 那边也没有送画面的入口。

现在两头都补上了，所以这个文件盯三件事：

1. **不收视频的 provider 不要假装在送。** 返回 False 并说清楚，而不是把每帧编码完
   再丢掉（白烧 CPU，还让人以为画面在送）。
2. **节流真的在节。** 视频轨是 15–30fps，双工面按时长计费；原样转发等于把账单
   乘以几十倍。
3. **挂断时视频泵真的停。** 这是最隐蔽的一个：音频停了，人会以为整通电话结束了，
   而画面还在往 provider 送、还在计费。
"""

import asyncio

import pytest


class _FakeAdapter:
    def __init__(self, name, video_ok):
        self.name = name
        self._video_ok = video_ok

    def video_frame(self, jpeg, mime="image/jpeg"):
        return {"v": len(jpeg)} if self._video_ok else None


class _FakeSession:
    """只实现 VoiceCall 真正会用到的那几个方法。"""

    def __init__(self, video_ok=True):
        self.adapter = _FakeAdapter("fake", video_ok)
        self.sent_video = []
        self.closed = False
        self.config = type("C", (), {"sample_rate": 16000})()

    def supports_video_uplink(self):
        return self.adapter.video_frame(b"\x00") is not None

    async def send_video_frame(self, jpeg, mime="image/jpeg"):
        if not self.supports_video_uplink():
            return False
        self.sent_video.append(jpeg)
        return True

    async def send_audio(self, pcm):
        return True

    async def close(self):
        self.closed = True


class _FakeVideoTrack:
    """吐固定张数的帧，然后像真轨道那样以 MediaStreamError 结束。"""

    kind = "video"

    def __init__(self, count, gap=0.0):
        self._left = count
        self._gap = gap

    async def recv(self):
        from aiortc.mediastreams import MediaStreamError

        if self._left <= 0:
            raise MediaStreamError
        self._left -= 1
        if self._gap:
            await asyncio.sleep(self._gap)
        return _FakeFrame()


class _FakeFrame:
    def to_image(self):
        from PIL import Image

        return Image.new("RGB", (32, 24), (10, 20, 30))


def _call(session):
    from core.voice_call_bridge import VoiceCall

    return VoiceCall("dev-1", session, send_event=None)


pytest.importorskip("aiortc")
pytest.importorskip("PIL")


class TestItRefusesRatherThanPretending:
    @pytest.mark.asyncio
    async def test_a_provider_without_video_does_not_start_the_pump(self):
        call = _call(_FakeSession(video_ok=False))
        assert call.attach_video_uplink(_FakeVideoTrack(5)) is False
        assert call._video_task is None, "不该起一个只会把帧编码完再丢掉的泵"
        await call.close()

    @pytest.mark.asyncio
    async def test_attaching_twice_is_refused(self):
        call = _call(_FakeSession())
        assert call.attach_video_uplink(_FakeVideoTrack(1)) is True
        assert call.attach_video_uplink(_FakeVideoTrack(1)) is False
        await call.close()


class TestFramesActuallyReachTheSession:
    @pytest.mark.asyncio
    async def test_frames_are_jpeg_encoded_and_sent(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DUPLEX_VIDEO_FPS", "0")  # 不节流，这条只验"送得到"
        session = _FakeSession()
        call = _call(session)
        call.attach_video_uplink(_FakeVideoTrack(3))
        await asyncio.wait_for(call._video_task, timeout=5)

        assert len(session.sent_video) == 3
        for jpeg in session.sent_video:
            assert jpeg[:2] == b"\xff\xd8", "送出去的得是真 JPEG（SOI 魔数），不是原始像素"
        assert call.stats.uplink_video_frames == 3
        assert call.stats.uplink_video_bytes == sum(len(j) for j in session.sent_video)
        await call.close()


class TestThrottling:
    @pytest.mark.asyncio
    async def test_extra_frames_are_dropped_and_counted(self, monkeypatch):
        """节流丢掉的帧要**计数**：不计的话，"帧率怎么这么低"无从解释。"""
        monkeypatch.setenv("GALAXY_DUPLEX_VIDEO_FPS", "1")  # 每秒一帧
        session = _FakeSession()
        call = _call(session)
        # 10 帧几乎瞬间到达 → 只有第一帧该被送出，其余 9 帧计入 dropped
        call.attach_video_uplink(_FakeVideoTrack(10))
        await asyncio.wait_for(call._video_task, timeout=5)

        assert len(session.sent_video) == 1, f"节流没生效，送了 {len(session.sent_video)} 帧"
        assert call.stats.uplink_video_dropped == 9
        await call.close()

    @pytest.mark.asyncio
    async def test_zero_fps_means_no_throttling_at_all(self, monkeypatch):
        """0 = 不节流是**显式选择**，允许，但不是默认。"""
        monkeypatch.setenv("GALAXY_DUPLEX_VIDEO_FPS", "0")
        session = _FakeSession()
        call = _call(session)
        call.attach_video_uplink(_FakeVideoTrack(6))
        await asyncio.wait_for(call._video_task, timeout=5)
        assert len(session.sent_video) == 6
        assert call.stats.uplink_video_dropped == 0
        await call.close()

    def test_the_default_is_one_frame_per_second_not_unthrottled(self, monkeypatch):
        from core.voice_call_bridge import _video_fps

        monkeypatch.delenv("GALAXY_DUPLEX_VIDEO_FPS", raising=False)
        assert _video_fps() == 1.0


class _StalledVideoTrack:
    """``recv()`` **永不返回**的轨道。

    这个形状是刻意的。第一版这条测试用的是"一直吐帧"的轨道，结果**抓不到 bug**：
    泵的循环条件是 ``while not self._closed``，``close()`` 把标志位翻了之后，
    下一轮自己就退出了 —— 于是"有没有 cancel 这个 task"根本没被验到。
    我把 ``close()`` 里的 cancel 去掉做变异，那一版测试照样全绿。

    真实里泵卡住的方式恰恰是这个：对端不再发帧、轨道也不报错，``await track.recv()``
    就那么悬着，``_closed`` 一辈子不会被重新读到。这时**只有 cancel 能收掉它**。
    """

    kind = "video"

    def __init__(self):
        self.recv_entered = asyncio.Event()

    async def recv(self):
        self.recv_entered.set()
        await asyncio.Event().wait()  # 永远不返回


class TestHangupStopsTheVideoPump:
    @pytest.mark.asyncio
    async def test_close_cancels_a_pump_that_is_stuck_in_recv(self, monkeypatch):
        """最隐蔽的一个：音频停了、人以为电话结束了，画面泵还挂着。

        判据必须是 ``task.cancelled()`` —— 用一个卡在 ``recv()`` 里的轨道，
        让"自己退出"这条路走不通，cancel 是唯一能收掉它的手段。
        """
        monkeypatch.setenv("GALAXY_DUPLEX_VIDEO_FPS", "0")
        session = _FakeSession()
        call = _call(session)
        track = _StalledVideoTrack()
        call.attach_video_uplink(track)
        await asyncio.wait_for(track.recv_entered.wait(), timeout=5)
        task = call._video_task
        assert not task.done(), "前提：泵此刻确实卡在 recv() 里"

        await call.close()
        await asyncio.sleep(0.05)
        assert task.cancelled(), "挂断后视频泵还挂着 —— 对端一旦恢复推流，画面会继续往 provider 送"
        assert session.closed


class TestABrokenFrameDoesNotKillTheStream:
    @pytest.mark.asyncio
    async def test_one_unencodable_frame_is_skipped_not_fatal(self, monkeypatch):
        monkeypatch.setenv("GALAXY_DUPLEX_VIDEO_FPS", "0")

        class _Mixed(_FakeVideoTrack):
            def __init__(self):
                super().__init__(3)
                self._n = 0

            async def recv(self):
                frame = await super().recv()
                self._n += 1
                if self._n == 2:  # 中间那帧编不出来
                    frame.to_image = lambda: (_ for _ in ()).throw(RuntimeError("坏帧"))
                return frame

        session = _FakeSession()
        call = _call(session)
        call.attach_video_uplink(_Mixed())
        await asyncio.wait_for(call._video_task, timeout=5)
        assert len(session.sent_video) == 2, "坏帧该被跳过，而不是把整条视频泵打断"
        await call.close()
