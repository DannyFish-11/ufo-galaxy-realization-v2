"""tests/test_tts_demote_concurrency.py
=========================================
并发朗读下 demote 误拉黑健康引擎的回归防护。

根因:demote_current_engine 原来只按【全局 _engine】拉黑,不管调用方实际失败的是哪个。
两路朗读(chat 增量 + voice/ambient 整段)共用同一全局引擎缓存:A 路把 edge 降级成健康
的 kokoro 后,B 路(还握着旧 edge)再失败时会按全局 _engine=kokoro 去拉黑,把【健康的
kokoro】误拉黑,一路拉到 SAPI/静默。修复让调用方传入【实际失败的引擎实例】,它已不是
现役引擎时直接返回现役,绝不误拉黑。
"""

from __future__ import annotations

import core.speech_output as so


class _EngA:
    pass


class _EngB:
    pass


def test_demote_does_not_blacklist_healthy_current_when_stale_engine_fails():
    old_engine = so._engine
    old_failed = set(so._failed_engine_types)
    try:
        healthy = _EngB()
        so._engine = healthy  # 现役=健康引擎(模拟 A 路已降级到它)
        so._failed_engine_types = set()
        stale = _EngA()  # B 路仍握着的旧引擎(已失败)

        result = so.demote_current_engine("stale failed", failed_engine=stale)

        # 现役健康引擎【不能】被拉黑,且应原样返回
        assert result is healthy, "传入陈旧失败引擎时应返回现役健康引擎,不重选"
        assert "_EngB" not in so._failed_engine_types, "绝不能误拉黑健康的现役引擎"
        assert so._engine is healthy
    finally:
        so._engine = old_engine
        so._failed_engine_types = old_failed


def test_demote_blacklists_the_actually_failed_engine_when_it_is_current():
    old_engine = so._engine
    old_failed = set(so._failed_engine_types)
    try:
        cur = _EngA()
        so._engine = cur
        so._failed_engine_types = set()

        # 失败的就是现役引擎 → 应拉黑它并重选(重选会走 _get_engine,可能得 None,无妨)
        so.demote_current_engine("cur failed", failed_engine=cur)
        assert "_EngA" in so._failed_engine_types, "失败的现役引擎应被拉黑"
    finally:
        so._engine = old_engine
        so._failed_engine_types = old_failed
