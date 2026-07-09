"""tests/test_memory_turn_fusion.py
=======================================

域3 · 记忆融合(轮次唯一属主):对话轮次此前在 SessionManager / WorkingMemory /
ConversationMemory 三处各存一份(record_session_turn 四写 + 跨store去重),现在
SessionManager 是唯一属主,WM/CM 变成它的读视图:

- record_session_turn 【单写】SM;WM/CM 不再各存副本。
- WorkingMemory.get: SM 认识的会话透传 SM;易失 scratch 会话(如 ambient)仍走本地
  deque(高频写不落盘)。
- ConversationMemory: add_turn 直写 SM(带相邻去重);get_context/get_summary 读 SM;
  独有的偏好学习保留(learn 钩子)。
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture()
def sm(tmp_path, monkeypatch):
    """隔离到临时状态文件的全新 SessionManager,并设为全局单例。"""
    import core.session_manager as smmod

    monkeypatch.setattr(smmod, "_SESSION_FILE", str(tmp_path / "sessions.json"))
    mgr = smmod.SessionManager()
    monkeypatch.setattr(smmod, "_session_manager", mgr)
    return mgr


@pytest.fixture()
def wm(monkeypatch):
    """全新 WorkingMemory 并设为全局单例。"""
    import core.cognitive.working_memory as wmmod

    mem = wmmod.WorkingMemory(capacity=10, enabled=True)
    monkeypatch.setattr(wmmod, "_working_memory", mem, raising=False)
    return mem


@pytest.fixture()
def cm(monkeypatch):
    """全新 ConversationMemory 并设为全局单例。"""
    import core.ai_intent as ai

    mem = ai.ConversationMemory()
    monkeypatch.setattr(ai, "_conversation_memory", mem, raising=False)
    return mem


def _record(session_id: str, role: str, content: str, **kw):
    from core.session_memory_facade import record_session_turn
    asyncio.run(record_session_turn(
        conversation_session_id=session_id, role=role, content=content, **kw))


# ── 单写:一轮只落在唯一属主 ──

class TestSingleWrite:
    def test_turn_lands_in_sm_only(self, sm, wm, cm):
        _record("s1", "user", "你好")
        # 唯一属主有
        assert [m["content"] for m in sm.get_full_history("s1")] == ["你好"]
        # WM 本地 deque 没有副本(读视图除外)
        assert "s1" not in wm._store
        # CM 本地列表没有副本
        assert "s1" not in cm._sessions

    def test_adjacent_duplicate_skipped(self, sm, wm, cm):
        _record("s1", "user", "重复")
        _record("s1", "user", "重复")
        assert len(sm.get_full_history("s1")) == 1

    def test_preference_learning_still_fires(self, sm, wm, cm):
        _record("s1", "user", "帮我截取屏幕")
        profile = cm.get_user_profile("s1")
        assert profile["interaction_count"] == 1


# ── 读视图:WM/CM 透传唯一属主 ──

class TestReadThrough:
    def test_wm_get_reads_sm(self, sm, wm, cm):
        _record("s2", "user", "问题一", device_id="phone")
        _record("s2", "assistant", "回答一")
        entries = wm.get(session_id="s2")
        assert [(e["role"], e["content"]) for e in entries] == [
            ("user", "问题一"), ("assistant", "回答一")]
        # metadata 里带 device_id(去重/跨设备语义依赖它)
        assert entries[0]["metadata"].get("device_id") == "phone"

    def test_wm_get_last_n(self, sm, wm, cm):
        for i in range(5):
            _record("s3", "user", f"m{i}")
            _record("s3", "assistant", f"r{i}")
        assert len(wm.get(session_id="s3", last_n=3)) == 3

    def test_cm_get_context_reads_sm(self, sm, wm, cm):
        _record("s4", "user", "甲")
        _record("s4", "assistant", "乙")
        ctx = asyncio.run(cm.get_context("s4"))
        assert ctx == [{"role": "user", "content": "甲"},
                       {"role": "assistant", "content": "乙"}]

    def test_cm_get_summary_reads_sm(self, sm, wm, cm):
        _record("s5", "user", "聊聊天气")
        summary = asyncio.run(cm.get_summary("s5"))
        assert "1 轮" in summary and "聊聊天气" in summary

    def test_facade_get_session_context_reads_sm(self, sm, wm, cm):
        from core.session_memory_facade import get_session_context
        _record("s6", "user", "上下文")
        assert get_session_context("s6") == [{"role": "user", "content": "上下文"}]


# ── CM.add_turn 直写唯一属主(routes/ai 路径) ──

class TestAddTurnDoor:
    def test_add_turn_writes_sm(self, sm, wm, cm):
        asyncio.run(cm.add_turn("s7", "user", "经CM进来"))
        assert [m["content"] for m in sm.get_full_history("s7")] == ["经CM进来"]
        assert "s7" not in cm._sessions  # 不再本地另存

    def test_add_turn_dedups_against_facade_write(self, sm, wm, cm):
        # 同一轮先经门面、再经 CM(routes/ai 与主链并存的场景)→ 只留一条
        _record("s8", "user", "同一句")
        asyncio.run(cm.add_turn("s8", "user", "同一句"))
        assert len(sm.get_full_history("s8")) == 1

    def test_add_turn_learns_preference(self, sm, wm, cm):
        asyncio.run(cm.add_turn("s9", "user", "搜索文件"))
        assert cm.get_user_profile("s9")["interaction_count"] == 1


# ── 易失 scratch 会话(ambient)仍走本地 deque ──

class TestVolatileSessions:
    def test_ambient_stays_local(self, sm, wm, cm):
        # SM 不认识 "ambient" → 本地 deque 承接(高频写不落盘)
        wm.add(session_id="ambient", role="ambient", content="观察: 用户在写代码")
        wm.add(session_id="ambient", role="ambient", content="观察: 屏幕无变化")
        entries = wm.get(session_id="ambient")
        assert len(entries) == 2
        assert entries[0]["role"] == "ambient"
        # 且绝不污染 SM
        assert sm.get_session("ambient") is None

    def test_volatile_capacity_eviction(self, sm, wm, cm):
        for i in range(15):
            wm.add(session_id="ambient", role="ambient", content=f"o{i}")
        entries = wm.get(session_id="ambient")
        assert len(entries) == 10  # capacity=10 FIFO
        assert entries[-1]["content"] == "o14"
