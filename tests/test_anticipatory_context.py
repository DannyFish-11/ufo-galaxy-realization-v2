"""预判式上下文注入(ACI)—— 契约测试
=====================================

被测的核心不是"能不能加速",而是**猜错的时候不会出事**。ACI 的价值上限由命中率
决定,但它的可用性下限由那四道闸决定:同会话 / 轮次未变 / 词法足够接近 / 一次性。
任何一道漏了,后果都是"模型看见了与当前问题无关的记忆",而这种错误在生产里
几乎无法从表象上归因。

所以这里的用例分布是刻意倾斜的:命中路径 5 条,**不该命中**的路径 9 条。
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _fresh_aci():
    from core.anticipatory_context import reset_anticipatory_context

    reset_anticipatory_context()
    yield
    reset_anticipatory_context()


@pytest.fixture()
def aci(monkeypatch):
    """一个不做真 I/O 的 ACI:预取加载器换成可控桩。

    真去跑 build_unified_context_uncached 会牵进长期记忆/向量后端/会话管理器,
    那是**它们**的测试要管的事;这里要验的是缓存与命中判定本身。
    """
    from core.anticipatory_context import AnticipatoryContext, get_anticipatory_context

    loaded: list = []

    def _fake_load(session_id, query):
        loaded.append((session_id, query))
        return [{"role": "system", "content": f"ctx-for::{query}"}]

    monkeypatch.setattr(AnticipatoryContext, "_load_context", staticmethod(_fake_load))
    monkeypatch.setenv("GALAXY_ACI_SETTLE_DELAY_S", "0")
    inst = get_anticipatory_context()
    inst._loaded = loaded  # 便于用例断言预取实际跑了什么
    return inst


async def _prefetch(aci, session_id, *, last_user_query, last_assistant_text=""):
    task = aci.schedule_after_turn(
        session_id,
        last_user_query=last_user_query,
        last_assistant_text=last_assistant_text,
    )
    if task is not None:
        await task
    return task


class TestPrediction:
    """预判必须是纯词法的 —— 不调用任何模型。"""

    def test_first_prediction_is_the_previous_user_query(self):
        from core.anticipatory_context import AnticipatoryContext

        out = AnticipatoryContext.predict_queries("帮我看看那份季度报告", "好的,报告在这里")
        assert out[0] == ("帮我看看那份季度报告", "topic_continuity")

    def test_second_prediction_comes_from_assistant_content_words(self):
        from core.anticipatory_context import AnticipatoryContext

        out = AnticipatoryContext.predict_queries("查一下", "季度报告的营收部分需要重算,营收口径变了")
        assert len(out) == 2
        assert out[1][1] == "assistant_topic"
        assert "营" in out[1][0] and "收" in out[1][0]

    def test_assistant_only_prediction_is_not_marked_topic_continuity(self):
        """没有上一轮用户问句时,助手猜测条目**不能**冒充 topic_continuity。

        按下标判种类的旧写法会让它落在 0 号位并被标成 topic_continuity,于是
        一句没有内容的"继续"就能命中一份纯猜测的上下文。种类是条目的固有属性。
        """
        from core.anticipatory_context import AnticipatoryContext

        out = AnticipatoryContext.predict_queries("", "营收 口径 重算")
        assert out and all(kind == "assistant_topic" for _, kind in out)

    def test_empty_input_predicts_nothing(self):
        from core.anticipatory_context import AnticipatoryContext

        assert AnticipatoryContext.predict_queries("", "") == []

    def test_prediction_respects_limit(self):
        from core.anticipatory_context import AnticipatoryContext

        assert len(AnticipatoryContext.predict_queries("a", "b c d", limit=1)) == 1


class TestHitPaths:
    def test_exact_match_hits(self, aci):
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        got = aci.take("s1", "帮我看看那份季度报告")

        assert got == [{"role": "system", "content": "ctx-for::帮我看看那份季度报告"}]
        assert aci.stats()["hit_exact"] == 1

    def test_case_and_whitespace_insensitive_exact_match(self, aci):
        asyncio.run(_prefetch(aci, "s1", last_user_query="Show me the Q3 report"))
        assert aci.take("s1", "  show me   the q3 REPORT ") is not None

    def test_lexically_close_query_hits(self, aci):
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        # 换了一个字,实词集合几乎一致 → Jaccard 过阈。
        assert aci.take("s1", "帮我看下那份季度报告") is not None
        assert aci.stats()["hit_lexical"] == 1

    def test_pure_continuation_hits_the_topic_continuity_entry(self, aci):
        """ "继续"没有实词,按 Jaccard 必然 miss —— 但它恰恰最该命中。"""
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        assert aci.take("s1", "继续") is not None
        assert aci.stats()["hit_continuation"] == 1

    def test_assistant_topic_entry_can_hit_on_its_own_words(self, aci):
        asyncio.run(
            _prefetch(
                aci,
                "s1",
                last_user_query="查一下",
                last_assistant_text="营收口径变了,营收需要重算",
            )
        )
        # 助手主题条目由高频实词拼成,用同一批词去问就该命中。
        assert aci.take("s1", "营收 重算 口径") is not None


class TestGuardsThatMustNotLetThrough:
    """四道闸。每一条都对应一种"喂错上下文"的具体事故。"""

    def test_different_session_never_reuses(self, aci):
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        assert aci.take("s2", "帮我看看那份季度报告") is None

    def test_new_turn_invalidates_prefetch(self, aci):
        """轮次一变,预取的上下文就**少一轮**,不能再用。"""
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        aci.note_turn_recorded("s1", "user")  # 新的一轮落库了

        assert aci.take("s1", "帮我看看那份季度报告") is None
        assert aci.stats()["stale_epoch"] >= 1

    def test_expired_entry_is_dropped(self, aci, monkeypatch):
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        monkeypatch.setenv("GALAXY_ACI_TTL_S", "0")

        assert aci.take("s1", "帮我看看那份季度报告") is None
        assert aci.stats()["expired"] >= 1

    def test_entry_is_single_use(self, aci):
        """一份预取不能喂给两个不同的问题。"""
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))

        assert aci.take("s1", "帮我看看那份季度报告") is not None
        assert aci.take("s1", "帮我看看那份季度报告") is None

    def test_unrelated_query_misses(self, aci):
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))
        assert aci.take("s1", "今天北京天气怎么样") is None
        assert aci.stats()["miss"] >= 1

    def test_continuation_does_not_hit_assistant_topic_entry(self, aci):
        """延续句只认"由上一轮用户问句派生"的那条。

        助手主题条目是**猜**出来的,让一句没有内容的"继续"去命中它,等于把一份
        猜测当成确定的上下文喂进模型。
        """
        asyncio.run(_prefetch(aci, "s1", last_user_query="", last_assistant_text="营收 口径 重算"))
        entries = aci._slots["s1"].entries
        assert entries and all(e.kind == "assistant_topic" for e in entries)

        assert aci.take("s1", "继续") is None

    def test_prefetch_skipped_when_request_in_flight(self, aci):
        """有请求在飞就不预取 —— 不跟正在服务用户的路径抢。"""
        aci.note_context_requested("s1")  # 一个请求正在组装上下文
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))

        assert aci.take("s1", "帮我看看那份季度报告") is None
        assert aci.stats()["prefetch_skipped_busy"] >= 1

    def test_disabled_switch_turns_everything_off(self, aci, monkeypatch):
        monkeypatch.setenv("GALAXY_ACI_ENABLED", "0")

        assert asyncio.run(_prefetch(aci, "s1", last_user_query="x")) is None
        assert aci.take("s1", "x") is None

    def test_no_running_loop_means_no_prefetch(self, aci):
        """同步上下文里不预取 —— 另起线程池会绕过"有请求在飞就放弃"的闸门。"""
        assert aci.schedule_after_turn("s1", last_user_query="帮我看看那份季度报告") is None


class TestFacadeWiring:
    def test_get_unified_context_serves_prefetched_result(self, aci, monkeypatch):
        """端到端:门命中缓存时不再走昂贵的组装体。"""
        import core.session_memory_facade as facade

        called: list = []

        def _expensive(session_id, query="", depth="auto", max_turns=10):
            called.append(query)
            return [{"role": "system", "content": "EXPENSIVE"}]

        monkeypatch.setattr(facade, "build_unified_context_uncached", _expensive)
        asyncio.run(_prefetch(aci, "s1", last_user_query="帮我看看那份季度报告"))

        got = facade.get_unified_context("s1", "帮我看看那份季度报告")

        assert got == [{"role": "system", "content": "ctx-for::帮我看看那份季度报告"}]
        assert called == [], "命中时不该再跑一遍组装体"

    def test_get_unified_context_falls_back_on_miss(self, aci, monkeypatch):
        """未命中时行为必须与 ACI 不存在时**完全一致**。"""
        import core.session_memory_facade as facade

        monkeypatch.setattr(
            facade,
            "build_unified_context_uncached",
            lambda session_id, query="", depth="auto", max_turns=10: [{"role": "system", "content": "EXPENSIVE"}],
        )

        got = facade.get_unified_context("s-never-prefetched", "随便问点什么")
        assert got == [{"role": "system", "content": "EXPENSIVE"}]

    def test_prefetch_loader_uses_the_uncached_builder(self, monkeypatch):
        """预取必须走**不带缓存**的组装体。

        若它调的还是带缓存的 ``get_unified_context``,预取就会去消费自己上一次的
        预取结果,缓存永远填不满、命中率恒为零 —— 而且不会有任何报错、不会有任何
        日志,只表现为"ACI 装了但一点也不快"。

        这里不打桩 ``_load_context``(那正是要验的东西),而是把门的两个出口都换掉:
        带缓存的那个换成炸弹,不带缓存的换成哨兵。
        """
        import core.session_memory_facade as facade
        from core.anticipatory_context import AnticipatoryContext

        def _must_not_be_called(*a, **k):
            raise AssertionError("预取走了带缓存的入口,会自己消费自己的预取结果")

        monkeypatch.setattr(facade, "get_unified_context", _must_not_be_called)
        monkeypatch.setattr(
            facade,
            "build_unified_context_uncached",
            lambda session_id, query="", depth="auto", max_turns=10: [{"role": "system", "content": "UNCACHED"}],
        )

        assert AnticipatoryContext._load_context("s1", "q") == [{"role": "system", "content": "UNCACHED"}]

    def test_stats_shape(self, aci):
        stats = aci.stats()
        for key in ("hits", "attempts", "hit_rate", "enabled", "sessions_tracked"):
            assert key in stats
