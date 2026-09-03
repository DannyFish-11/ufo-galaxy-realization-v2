"""视频必须真的送进模型，而不是只在感知层里存在。

这条链路此前**整条不存在**：
  - ``MultiModalContext`` 只有 images / audio，没有 video 字段；
  - 感知库每来一帧就覆盖上一帧，上一帧当场消失；
  - 于是「刚才屏幕上发生了什么」「动画卡在哪一步」结构上无法回答 ——
    模型永远只看得到提问那一瞬间的一张静止图。

音频那一侧是有原生路径的（core/audio_pipeline 会构造真的 input_audio /
inline_data），视频没有。本文件按真实调用链验证补上的那条：
  update_frame → 滚动关键帧环 → build_multimodal_context →
  build_user_message_content → 送进 LLM 的 content 数组
"""

from __future__ import annotations

import time

import pytest

from core.agent.multimodal_messages import build_user_message_content
from core.perception.desktop_perception_store import DesktopPerceptionStore
from core.schemas.multimodal import MultiModalContext, MultiModalVideo, MultiModalVideoFrame
from core.video_keyframes import MAX_KEYFRAMES, build_video_content_parts, sample_keyframes


@pytest.fixture
def native_mm_on(monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_MM_CHAT", "1")


@pytest.fixture
def store(monkeypatch):
    """每个用例一个干净实例 —— 单例会跨用例串数据。"""
    monkeypatch.setenv("GALAXY_PERCEPTION_KEYFRAMES", "4")
    monkeypatch.delenv("GALAXY_PERCEPTION_PRIVACY_DEFAULT", raising=False)
    return DesktopPerceptionStore()


def _feed(store, frames, source="desktop_screen", gap=0.01):
    for b in frames:
        store.update_frame(b, source=source)
        time.sleep(gap)


# ── 1. schema：视频字段存在且对既有调用方无影响 ────────────────────────


def test_context_video_defaults_to_empty():
    assert MultiModalContext().video == []


def test_video_frames_keep_their_offsets():
    v = MultiModalVideo(
        frames=[MultiModalVideoFrame(data="a", offset_ms=0), MultiModalVideoFrame(data="b", offset_ms=900)]
    )
    assert [f.offset_ms for f in v.frames] == [0, 900]


def test_negative_offset_is_rejected():
    """offset 是「从片段开头往后数」，负数只可能是算错了，让它当场炸而不是悄悄进模型。"""
    with pytest.raises(Exception):
        MultiModalVideoFrame(data="a", offset_ms=-1)


# ── 2. 抽帧：首尾必留 ─────────────────────────────────────────────────


def test_sampling_keeps_first_and_last():
    frames = list(range(100))
    picked = sample_keyframes(frames, max_frames=5)
    assert len(picked) == 5
    assert picked[0] == 0 and picked[-1] == 99, "首尾是「之前长什么样/现在长什么样」的答案本体"


def test_sampling_is_a_noop_when_under_the_cap():
    frames = [1, 2, 3]
    assert sample_keyframes(frames, max_frames=8) == frames


def test_sampling_is_monotonic():
    picked = sample_keyframes(list(range(50)), max_frames=6)
    assert picked == sorted(picked), "顺序错了时间轴就是错的"


def test_sampling_one_frame_takes_the_newest():
    assert sample_keyframes([1, 2, 3], max_frames=1) == [3]


def test_sampling_zero_returns_nothing():
    assert sample_keyframes([1, 2, 3], max_frames=0) == []


def test_sampling_of_empty_input():
    assert sample_keyframes([], max_frames=4) == []


# ── 3. content parts：时间轴必须以文字形式传达出去 ──────────────────────


def test_each_keyframe_is_preceded_by_a_timestamp_label():
    v = MultiModalVideo(
        source="desktop_screen",
        frames=[MultiModalVideoFrame(data="a", offset_ms=0), MultiModalVideoFrame(data="b", offset_ms=1200)],
    )
    parts = build_video_content_parts(v)
    assert [p["type"] for p in parts] == ["text", "image_url", "text", "image_url"]
    assert "t=+0.0s" in parts[0]["text"]
    assert "t=+1.2s" in parts[2]["text"]
    assert "desktop_screen" in parts[0]["text"]


def test_content_parts_respect_the_keyframe_cap():
    v = MultiModalVideo(frames=[MultiModalVideoFrame(data=f"f{i}", offset_ms=i * 100) for i in range(40)])
    parts = build_video_content_parts(v)
    assert len([p for p in parts if p["type"] == "image_url"]) == MAX_KEYFRAMES


def test_empty_frames_produce_nothing():
    assert build_video_content_parts(MultiModalVideo(frames=[])) == []


def test_frames_without_data_are_skipped():
    v = MultiModalVideo(frames=[MultiModalVideoFrame(data=""), MultiModalVideoFrame(data="b")])
    parts = build_video_content_parts(v)
    assert len([p for p in parts if p["type"] == "image_url"]) == 1


# ── 4. 滚动关键帧环：这是"视频"在本仓唯一真实的来源 ─────────────────────


def test_ring_keeps_history_instead_of_overwriting(store):
    _feed(store, ["AAA", "BBB", "CCC"])
    ctx = store.build_multimodal_context()
    assert len(ctx.video) == 1
    assert [f.data for f in ctx.video[0].frames] == ["AAA", "BBB", "CCC"]


def test_offsets_are_relative_to_the_first_frame(store):
    _feed(store, ["AAA", "BBB"], gap=0.05)
    frames = store.build_multimodal_context().video[0].frames
    assert frames[0].offset_ms == 0
    assert frames[1].offset_ms >= 40, "第二帧的偏移必须反映真实间隔"


def test_ring_is_bounded(store):
    _feed(store, [f"f{i}" for i in range(20)])
    frames = store.build_multimodal_context().video[0].frames
    assert len(frames) <= 4, "环必须有上限——每帧是整屏 base64"
    assert frames[-1].data == "f19", "满了要丢最旧的，不是丢最新的"


def test_identical_consecutive_frames_are_not_stored_twice(store):
    """静止画面下采集仍在跑；不去重的话「关键帧序列」就是一张图重复 N 次。"""
    _feed(store, ["SAME", "SAME", "SAME", "SAME"])
    assert store.build_multimodal_context().video == [], "只有一帧不同 → 不构成视频"


def test_single_frame_does_not_become_a_video(store):
    _feed(store, ["ONLY"])
    ctx = store.build_multimodal_context()
    assert ctx.video == [], "一帧的「序列」就是那张静止图，已经在 images 里了"
    assert len(ctx.images) == 1


def test_ring_disabled_by_env(monkeypatch):
    monkeypatch.setenv("GALAXY_PERCEPTION_KEYFRAMES", "0")
    st = DesktopPerceptionStore()
    _feed(st, ["AAA", "BBB", "CCC"])
    assert st.build_multimodal_context().video == []


def test_camera_frames_do_not_produce_video(store):
    """摄像头不做视频：这类问题几乎总是在问屏幕上的过程，多一路只是翻倍烧 token。"""
    _feed(store, ["CAM1", "CAM2", "CAM3"], source="desktop_camera")
    assert store.build_multimodal_context().video == []


def test_stale_frames_are_dropped(store, monkeypatch):
    _feed(store, ["OLD1", "OLD2"])
    store.ttl_sec = -1.0  # 全部判为过期
    assert store.build_multimodal_context() is None


# ── 5. 隐私急停必须连关键帧环一起清 ───────────────────────────────────


def test_pause_wipes_the_keyframe_ring(store):
    """漏清等于隐私急停只挡住了当下这一帧，却把此前几秒的完整过程留在内存里。"""
    _feed(store, ["AAA", "BBB", "CCC"])
    store.pause()
    store.resume()
    _feed(store, ["NEW"])
    ctx = store.build_multimodal_context()
    assert ctx.video == [], "暂停前那一段画面在恢复后仍然可读 —— 隐私急停名不副实"
    assert "AAA" not in str(ctx.model_dump())


def test_frames_are_rejected_while_paused(store):
    store.pause()
    _feed(store, ["AAA", "BBB", "CCC"])
    assert store.build_multimodal_context() is None
    store.resume()
    assert store.build_multimodal_context() is None, "暂停期间的帧不许在恢复后浮出来"


# ── 6. 端到端：真的进了送给模型的 content 数组 ────────────────────────


def test_keyframes_reach_the_model_content_array(store, native_mm_on):
    _feed(store, ["AAA", "BBB", "CCC"])
    content = build_user_message_content("刚才屏幕上发生了什么", store.build_multimodal_context())
    assert isinstance(content, list)
    urls = [p["image_url"]["url"] for p in content if p["type"] == "image_url"]
    assert any("AAA" in u for u in urls), "最早那一帧没送到 —— 那正是「之前长什么样」的答案"
    assert any("BBB" in u for u in urls)


def test_current_frame_is_not_sent_twice(store, native_mm_on):
    """最后一帧必然就是当前静止图，已作为 image 附过一次；发两遍是钱翻倍、信息不变。"""
    _feed(store, ["AAA", "BBB", "CCC"])
    content = build_user_message_content("看看", store.build_multimodal_context())
    urls = [p["image_url"]["url"] for p in content if p["type"] == "image_url"]
    assert len(urls) == len(set(urls)), f"同一张图被发了多次: {urls}"
    assert sum("CCC" in u for u in urls) == 1


def test_video_is_omitted_when_native_mm_is_off(store, monkeypatch):
    monkeypatch.setenv("GALAXY_NATIVE_MM_CHAT", "0")
    _feed(store, ["AAA", "BBB", "CCC"])
    assert isinstance(build_user_message_content("看看", store.build_multimodal_context()), str)


def test_video_only_context_still_produces_content_array(native_mm_on):
    """只有视频、没有静止图时也要走数组 —— 否则视频会被整段丢掉。"""
    ctx = MultiModalContext(
        video=[MultiModalVideo(frames=[MultiModalVideoFrame(data="a"), MultiModalVideoFrame(data="b", offset_ms=500)])]
    )
    content = build_user_message_content("看看", ctx)
    assert isinstance(content, list)
    assert len([p for p in content if p["type"] == "image_url"]) == 2


def test_text_only_context_is_still_plain_text(native_mm_on):
    assert build_user_message_content("hi", MultiModalContext()) == "hi"


# ── 7. 面板契约：新开关必须真的能在设置里调 ────────────────────────────


def test_keyframe_switch_is_registered_in_config_schema():
    """没登记就等于没接上：GET /api/config/all 不返回它,POST 还会当 unknown_keys 拒掉。"""
    from core.routes.config import CONFIG_SCHEMA

    assert "GALAXY_PERCEPTION_KEYFRAMES" in CONFIG_SCHEMA


def test_keyframe_schema_default_agrees_with_the_code(monkeypatch):
    """只比字面量拦不住「schema 改了、代码没改」——直接调读取函数比。"""
    from core.perception.desktop_perception_store import _keyframe_ring_size
    from core.routes.config import CONFIG_SCHEMA

    monkeypatch.delenv("GALAXY_PERCEPTION_KEYFRAMES", raising=False)
    assert _keyframe_ring_size() == int(CONFIG_SCHEMA["GALAXY_PERCEPTION_KEYFRAMES"]["default"])


def test_keyframe_switch_reaches_the_settings_panel():
    """面板源码里没有这个键，用户就永远看不到、也关不掉这个滚动缓冲。"""
    import pathlib

    src = pathlib.Path("electron/renderer/panel/src/components/SettingsTab.tsx").read_text(encoding="utf-8")
    assert "GALAXY_PERCEPTION_KEYFRAMES" in src


@pytest.mark.parametrize("raw,expected", [("", 4), ("abc", 4), ("-3", 0), ("999", 16), ("2", 2)])
def test_ring_size_is_clamped(monkeypatch, raw, expected):
    """上限 16：每帧是整屏 base64，不封顶就是几十 MB 常驻内存。"""
    from core.perception.desktop_perception_store import _keyframe_ring_size

    monkeypatch.setenv("GALAXY_PERCEPTION_KEYFRAMES", raw)
    assert _keyframe_ring_size() == expected
