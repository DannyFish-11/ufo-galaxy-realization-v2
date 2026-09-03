#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_archive_retention_refuses_before_it_deletes.py

钉住：**归档回收宁可不删，也不删错。**

修的是什么
==========
上下文归档（:mod:`core.context_archive`）存的是被压掉那段对话的**唯一原文**，而它
此前**增长无界** —— 唯一的删除入口是用户点"清除对话"。长期跑下去磁盘会被吃满。

但"加个自动清理"是这一层最容易做坏的一件事：它删的不是缓存，是用户说过的话。
所以这套策略的每一条都是**朝着少删的方向**设计的：

1. 只删**整个**会话 —— 删半个会留下段号有洞的目录，模型按号去查会查到"不存在"，
   而它以为自己还有后路；
2. 绝不删**正在写**的那个会话；
3. **保留期压过总量上限** —— 超了上限但没有够旧的可删时，**一个都不删、只告警**。
   "撑爆磁盘"和"删掉用户上周说过的话"不是一个量级的坏事；
4. 删了要**说出来**；
5. 上限设 0 = 关掉自动删除。
"""

from __future__ import annotations

import os
import time

import pytest

import core.context_archive as ca


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ca, "_ROOT", tmp_path / "archive")
    for k in (ca._MAX_MB_KEY, ca._MIN_DAYS_KEY):
        monkeypatch.delenv(k, raising=False)


def _make_session(sid: str, kb: int = 512, age_days: float = 0.0) -> None:
    """造一个会话归档。

    造的时候**必须先把回收关掉**：``archive_segment`` 每次写完都会跑一遍回收，
    否则铺场景的过程本身就会把先造好的会话删掉 —— 第一版就是这么写的，两条测试
    因此假败。（顺带也说明那个自动触发确实在生效。）
    """
    saved = os.environ.get(ca._MAX_MB_KEY)
    os.environ[ca._MAX_MB_KEY] = "0"
    try:
        ca.archive_segment(sid, [{"role": "user", "content": "x" * (kb * 1024)}], "摘要")
    finally:
        if saved is None:
            os.environ.pop(ca._MAX_MB_KEY, None)
        else:
            os.environ[ca._MAX_MB_KEY] = saved
    if age_days:
        old = time.time() - age_days * 86400
        d = ca._dir(sid)
        for p in list(d.rglob("*")) + [d]:
            os.utime(p, (old, old))


class TestItRefusesWhenItCannotDeleteSafely:
    """这一组全是"不删"的情形 —— 每一条都是一次**有意的克制**。"""

    def test_under_budget_nothing_happens(self, monkeypatch):
        monkeypatch.setenv(ca._MAX_MB_KEY, "64")
        _make_session("a", kb=256)
        assert ca.enforce_retention() == []
        assert ca.list_segments("a") == [1]

    def test_a_zero_cap_disables_deletion_entirely(self, monkeypatch):
        """把上限设 0 = 磁盘我自己管，你别动。"""
        monkeypatch.setenv(ca._MAX_MB_KEY, "0")
        _make_session("old", kb=2048, age_days=999)
        assert ca.enforce_retention() == []
        assert ca.list_segments("old") == [1]

    def test_recent_sessions_survive_even_over_budget(self, monkeypatch, caplog):
        """**这条是整套策略的支点。**

        超了上限、但所有会话都还在保留期内 —— 正确动作是**一个都不删、大声告警**，
        把决定权交回给人。删掉用户上周说过的话，比磁盘多占几百兆坏得多。
        """
        monkeypatch.setenv(ca._MAX_MB_KEY, "1")
        monkeypatch.setenv(ca._MIN_DAYS_KEY, "30")
        _make_session("fresh-1", kb=800)
        _make_session("fresh-2", kb=800)
        with caplog.at_level("WARNING"):
            assert ca.enforce_retention() == [], "把保留期内的会话删了"
        assert ca.list_segments("fresh-1") and ca.list_segments("fresh-2")
        assert any("一个都没删" in r.message for r in caplog.records), "拒绝了却没说 —— 磁盘会一直涨而没人知道"

    def test_the_session_being_written_is_never_dropped(self, monkeypatch):
        """一边归档一边被回收，段号会错乱。"""
        monkeypatch.setenv(ca._MAX_MB_KEY, "1")
        monkeypatch.setenv(ca._MIN_DAYS_KEY, "0")
        _make_session("active", kb=800, age_days=999)
        _make_session("other", kb=800, age_days=999)
        dropped = ca.enforce_retention(active_session_id="active")
        assert ca.list_segments("active"), "把正在写的会话删了"
        assert "other" in str(dropped) or ca.list_segments("other") == []


class TestWhenItDoesDeleteItDeletesWholeSessions:
    """真到了该删的时候，也只按"整会话、从最旧开始"删。"""

    def test_the_oldest_expired_session_goes_first(self, monkeypatch, caplog):
        monkeypatch.setenv(ca._MAX_MB_KEY, "1")
        monkeypatch.setenv(ca._MIN_DAYS_KEY, "10")
        _make_session("ancient", kb=700, age_days=400)
        _make_session("old", kb=700, age_days=100)
        _make_session("recent", kb=700, age_days=1)

        with caplog.at_level("INFO"):
            dropped = ca.enforce_retention()

        assert dropped, "超了上限、又有过期会话，却一个没删"
        assert ca.list_segments("recent"), "保留期内的被删了"
        assert ca.list_segments("ancient") == [], "最旧的没有被优先删"
        assert any("已清掉最旧的会话" in r.message for r in caplog.records), "删了却没说"

    def test_it_never_leaves_half_a_session(self, monkeypatch):
        """删半个会留下段号有洞的目录：模型按号去查会查到"不存在"，而它以为还有后路。"""
        monkeypatch.setenv(ca._MAX_MB_KEY, "1")
        monkeypatch.setenv(ca._MIN_DAYS_KEY, "0")
        os.environ[ca._MAX_MB_KEY] = "0"
        for i in range(3):
            ca.archive_segment("multi", [{"role": "user", "content": "y" * 400_000}], f"第{i}段")
        monkeypatch.setenv(ca._MAX_MB_KEY, "1")
        ca.enforce_retention()
        segs = ca.list_segments("multi")
        assert segs == [] or segs == [1, 2, 3], f"留下了半个会话：{segs}"


class TestItIsWiredToARealCaller:
    """判据接上了但没人调，等于没接 —— 这一层此前就是无界增长的。"""

    def test_archiving_triggers_the_check(self):
        import inspect

        src = inspect.getsource(ca.archive_segment)
        assert "enforce_retention(" in src, "没有任何一处会触发回收 —— 归档仍然无界增长"
        assert src.index("atomic_write_json") < src.index("enforce_retention("), "回收要在写成功之后"

    def test_it_excludes_the_session_it_just_wrote(self):
        import inspect

        src = inspect.getsource(ca.archive_segment)
        assert "active_session_id=session_id" in src, "回收可能反手把刚写进去的这一段吃掉"

    def test_both_knobs_are_registered_where_users_can_change_them(self):
        """判据接上了但用户改不了，等于没接。"""
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        for key in (ca._MAX_MB_KEY, ca._MIN_DAYS_KEY):
            assert key in CONFIG_SCHEMA, f"{key} 没登记进 CONFIG_SCHEMA"

        panel = open("electron/renderer/panel/src/settings_inventory.ts", encoding="utf-8").read()
        for key in (ca._MAX_MB_KEY, ca._MIN_DAYS_KEY):
            assert key in panel, f"{key} 没出现在面板里"

    def test_a_bad_value_falls_back_loudly_instead_of_crashing(self, monkeypatch, caplog):
        monkeypatch.setenv(ca._MAX_MB_KEY, "两千兆")
        with caplog.at_level("WARNING"):
            assert ca._env_int(ca._MAX_MB_KEY, 2048) == 2048
        assert any("不是整数" in r.message for r in caplog.records)
