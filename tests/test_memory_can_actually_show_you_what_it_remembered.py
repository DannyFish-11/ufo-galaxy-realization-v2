"""记忆不只是"找得到"，还要"拿得回来"。

## 改这一版之前是什么样

``UnifiedMemory.remember_media()`` 走的是:

    base64 → tempfile.mkstemp() → 各后端摄入 → **finally: 删掉临时文件**

而它同时往 metadata 里记了 ``media_path``。那个路径指向的文件在函数返回的那一刻
就**保证已经不存在**了。于是记忆一直停在"跨模态检索"这一层:

* CLIP 把截图编成向量,所以"上次那个报错的界面"这句话真能召回它 —— 这一半是对的;
* 但召回之后**没有任何东西能把那张图拿回来**。谁照着 metadata 里的路径去 open(),
  拿到的只有 FileNotFoundError。召回给到模型的,自始至终只有一句 caption。

所以"记忆是多模态的"这句话,此前只在检索那一维成立,在输入那一维不成立。

## 这一套钉什么

1. 字节**真的留得下来**(``media_store``),而且有上限、逐出要留痕;
2. 召回**能把它还原成规范表示**,再由 ``core.modality`` 那个唯一的头决定这一轮
   的型号收不收、这条传输装不装得下;
3. 默认**不回放** —— 回放很贵,而多数轮次 caption 就够;
4. 字节丢了(被逐出/被删)要**说出来**,不能与"这条记忆本来就没有媒体"混为一谈。
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest

PNG_1PX = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
WAV_B64 = "UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA="


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """媒体库指到临时目录 —— 绝不在开发机上留下截图。"""
    monkeypatch.setenv("GALAXY_MEMORY_MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("GALAXY_MEMORY_MEDIA", "1")
    monkeypatch.delenv("GALAXY_MEMORY_REPLAY_MEDIA", raising=False)
    yield


def _hit(media_id: str, *, modality: str = "image", content: str = "上次那个界面"):
    return SimpleNamespace(content=content, modality=modality, metadata={"media_id": media_id, "modality": modality})


class TestTheBytesActuallySurvive:
    def test_what_goes_in_comes_back_out(self):
        from core.memory.media_store import load, store

        mid = store(PNG_1PX, mime="image/png", modality="image")
        assert mid, "存不进去"
        got = load(mid)
        assert got is not None
        assert got[0] == PNG_1PX and got[1] == "image/png"

    def test_the_same_bytes_stored_twice_take_one_slot(self):
        """内容寻址:桌面闭环每一步都截图,同一个界面会反复出现。

        不去重的话磁盘涨得比记忆本身还快。
        """
        from core.memory.media_store import stats, store

        a = store(PNG_1PX, mime="image/png")
        b = store(PNG_1PX, mime="image/png")
        assert a == b
        assert stats()["items"] == 1

    def test_a_missing_id_is_none_not_an_exception(self):
        from core.memory.media_store import load

        assert load("没这个东西") is None
        assert load("") is None

    def test_turning_it_off_stores_nothing(self, monkeypatch):
        """关掉之后记忆退回改这版之前的样子:找得到,看不见。"""
        from core.memory.media_store import store

        monkeypatch.setenv("GALAXY_MEMORY_MEDIA", "0")
        assert store(PNG_1PX, mime="image/png") == ""


class TestItDoesNotGrowForever:
    def test_the_budget_evicts_the_least_recently_recalled(self, monkeypatch):
        """超预算按**最久未访问**逐出,不是按最早存入。

        一张反复被召回的界面截图,存得早不代表没用;而一张存进来之后再没被想起过
        的,留着只是占地方。
        """
        from core.memory.media_store import load, stats, store

        # 预算刚好装得下 5 张 400 字节的图(2097 > 2000),装第 6 张才超。
        # 第一版这里填的是 0.001MB —— 那个库只装得下两张,五张还没存完最早那张
        # 就已经被逐出了,于是"刚回忆过的不该被逐出"这件事**根本没被测到**。
        monkeypatch.setenv("GALAXY_MEMORY_MEDIA_MB", "0.002")

        ids = [store(base64.b64encode(bytes([i]) * 400).decode(), mime="image/png") for i in range(5)]
        assert all(ids) and stats()["items"] == 5, "预算没装下五张,这条用例就测不到 LRU"

        load(ids[0])  # 第 0 张被"回忆"过一次 → 它的 atime 变成最新
        store(base64.b64encode(b"\xff" * 400).decode(), mime="image/png")  # 装第 6 张,触发逐出

        assert stats()["items"] < 6, "超了预算却一个都没逐出"
        assert load(ids[0]) is not None, "刚被回忆过的那张反而被逐出了 —— 逐出没按最久未访问"
        assert load(ids[1]) is None, "该被逐出的那张还在"


class TestRecallCanHandItBack:
    def test_media_comes_back_as_canonical_parts(self):
        from core.memory.media_store import media_parts_for, store

        mid = store(PNG_1PX, mime="image/png", modality="image")
        parts = media_parts_for([_hit(mid)], force=True)

        assert len(parts) == 1
        assert parts[0]["type"] == "image_url"
        assert PNG_1PX in parts[0]["image_url"]["url"]

    def test_audio_comes_back_in_the_canonical_audio_shape(self):
        from core.memory.media_store import media_parts_for, store

        mid = store(WAV_B64, mime="audio/wav", modality="audio")
        parts = media_parts_for([_hit(mid, modality="audio")], force=True)

        assert parts[0]["type"] == "input_audio"
        assert parts[0]["input_audio"]["format"] == "wav"

    def test_replay_is_off_by_default(self):
        """回放很贵:一次召回三条记忆、每条一张 1080p 截图就是几千视觉 token,
        而多数轮次 caption 已经够用了。"""
        from core.memory.media_store import media_parts_for, store

        mid = store(PNG_1PX, mime="image/png")
        assert media_parts_for([_hit(mid)]) == []

    def test_the_switch_turns_it_on(self, monkeypatch):
        from core.memory.media_store import media_parts_for, store

        monkeypatch.setenv("GALAXY_MEMORY_REPLAY_MEDIA", "1")
        mid = store(PNG_1PX, mime="image/png")
        assert len(media_parts_for([_hit(mid)])) == 1

    def test_bytes_that_are_gone_are_announced_not_silently_skipped(self, caplog):
        """被逐出、被手工删、当初就没存下 —— 对使用者是同一个现象(看不到图),
        对排查完全不同。"""
        import logging

        from core.memory.media_store import media_parts_for

        with caplog.at_level(logging.INFO, logger="Galaxy.Memory.MediaStore"):
            parts = media_parts_for([_hit("早就没了的 id")], force=True)

        assert parts == []
        assert any("不在库里" in r.getMessage() for r in caplog.records), "字节丢了却一声不吭"

    def test_a_memory_without_media_is_simply_skipped(self):
        """没有 media_id 的普通文字记忆不该被当成"丢了"。"""
        from core.memory.media_store import media_parts_for

        plain = SimpleNamespace(content="一条纯文字记忆", modality="text", metadata={})
        assert media_parts_for([plain], force=True) == []


class TestWritingMediaRecordsSomethingRetrievable:
    def test_remember_media_records_an_id_that_actually_resolves(self):
        """此前记的是一个**保证已被删除**的临时路径。现在记的必须是能取回来的。"""
        from core.memory.base import MemoryProvider
        from core.memory.media_store import load
        from core.memory.unified import UnifiedMemory

        seen = []

        class _Spy(MemoryProvider):
            backend_name = "spy"

            def available(self):  # noqa: D102
                return True

            def remember(self, content, *, modality="text", tags=None, metadata=None):  # noqa: D102
                seen.append(dict(metadata or {}))

            def recall(self, query, *, top_k=5):  # noqa: D102
                return []

        UnifiedMemory([_Spy()]).remember_media(PNG_1PX, modality="image", mime="image/png", caption="一张截图")

        media_id = seen[-1].get("media_id")
        assert media_id, "写入没有留下 media_id —— 召回时依然拿不回画面"
        assert load(media_id) is not None, "留下了 id,但按它取不回东西"


class TestVideoGetsInAsKeyframes:
    @staticmethod
    def _video(n: int):
        from core.schemas.multimodal import MultiModalVideo, MultiModalVideoFrame

        return MultiModalVideo(
            source="desktop_screen",
            frames=[MultiModalVideoFrame(data=PNG_1PX, mime="image/jpeg", offset_ms=i * 500) for i in range(n)],
        )

    @staticmethod
    def _spy_memory():
        from core.memory.base import MemoryProvider
        from core.memory.unified import UnifiedMemory

        seen = []

        class _Spy(MemoryProvider):
            backend_name = "spy"

            def available(self):  # noqa: D102
                return True

            def remember(self, content, *, modality="text", tags=None, metadata=None):  # noqa: D102
                seen.append({"content": content, "modality": modality, "metadata": dict(metadata or {})})

            def recall(self, query, *, top_k=5):  # noqa: D102
                return []

        return seen, UnifiedMemory([_Spy()])

    def test_each_keyframe_becomes_its_own_recallable_image(self):
        """一堆静止图说的是"屏幕上有什么",带时间偏移的有序帧说的是"发生了什么"。"""
        seen, um = self._spy_memory()
        um.remember_video(self._video(3), caption="[screen]")

        assert len(seen) == 3
        offsets = [w["metadata"].get("video_offset_ms") for w in seen]
        assert offsets == [0, 500, 1000], f"时间偏移没带上:{offsets}"
        assert all(w["metadata"].get("media_id") for w in seen), "帧没有进媒体库,召回时拿不回画面"

    def test_a_long_clip_is_sampled_not_dumped(self):
        """抽帧用的是送给模型的那同一个函数(均匀抽、首尾必留),不另写一份判据。"""
        from core.video_keyframes import MAX_KEYFRAMES

        seen, um = self._spy_memory()
        um.remember_video(self._video(MAX_KEYFRAMES * 3))
        assert len(seen) == MAX_KEYFRAMES

    def test_an_empty_clip_says_so_instead_of_doing_nothing(self):
        """悄悄什么都不做,调用方会以为这段视频记住了。"""
        seen, um = self._spy_memory()
        um.remember_video(self._video(0), caption="[screen]")

        assert len(seen) == 1
        assert "没有关键帧" in seen[0]["content"]
        assert seen[0]["metadata"]["video_frames"] == 0


class TestTheChainIsWiredEndToEnd:
    def test_the_desktop_loop_asks_for_parts_and_passes_the_media_on(self):
        """闭环必须**真的**把召回的画面带给规划那一步 —— 只召回不用等于没做。"""
        import inspect

        from core import computer_use_loop as loop

        src = inspect.getsource(loop)
        assert "recall_experience_parts" in src, "闭环还在用只返回文字的老召回"
        assert "experience_media" in src, "召回到的画面没有被带进规划那一步"

    def test_the_panel_tells_the_truth_about_which_backends_exist(self):
        """这句原来写的是「如 vector,graph」—— graph 根本不是支持的后端,
        照着填不会报错也不会生效;而两个多模态后端一个字没提。"""
        from core.memory.unified import _build  # noqa: F401  —— 确认这是同一处权威
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        desc = CONFIG_SCHEMA["GALAXY_MEMORY_BACKENDS"]["description"]
        assert "graph" not in desc, "面板还在举一个不存在的后端做例子"
        for real in ("vector", "clip", "clap", "omni"):
            assert real in desc, f"面板没提 {real} —— 想开它的人在界面上找不到这个词"

    @pytest.mark.parametrize(
        "key",
        ["GALAXY_MEMORY_MEDIA", "GALAXY_MEMORY_MEDIA_MB", "GALAXY_MEMORY_MEDIA_DIR", "GALAXY_MEMORY_REPLAY_MEDIA"],
    )
    def test_every_new_knob_is_settable_from_the_panel(self, key):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert key in CONFIG_SCHEMA, f"{key} 只认环境变量,面板上配不了 —— 等于没有开关"
        assert CONFIG_SCHEMA[key]["category"] == "memory"
