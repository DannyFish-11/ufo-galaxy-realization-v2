"""tests/test_durable_dispatch_idempotency.py
================================================
派发侧可持久化幂等库(core.durable_dispatch_idempotency):file-backed、原子写、
有界、跨"重启"存活。区别于结果侧去重(durable_result_idempotency)——这个防的是
【副作用被执行第二次】,不是结果被摄取第二次。
"""

from __future__ import annotations

import pytest

import core.durable_dispatch_idempotency as ddi


@pytest.fixture(autouse=True)
def _iso(tmp_path):
    ddi.reset_durable_dispatch_id_store()
    yield
    ddi.reset_durable_dispatch_id_store()


def test_add_contains_remove(tmp_path):
    s = ddi.DurableDispatchIdSet(str(tmp_path / "d.json"))
    assert s.add("k1") is True
    assert s.add("k1") is False  # 重复
    assert s.contains("k1")
    assert s.remove("k1") is True
    assert not s.contains("k1")


def test_survives_restart(tmp_path):
    p = str(tmp_path / "d.json")
    ddi.DurableDispatchIdSet(p).add("kX")
    # 新实例 = 模拟进程重启,应从盘上读回
    assert ddi.DurableDispatchIdSet(p).contains("kX")


def test_atomic_write_leaves_no_tmp(tmp_path):
    s = ddi.DurableDispatchIdSet(str(tmp_path / "d.json"))
    s.add("a")
    s.add("b")
    leftovers = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == []  # 写-临时-改名,不留 .tmp 残渣


def test_bounded_eviction(tmp_path):
    s = ddi.DurableDispatchIdSet(str(tmp_path / "d.json"), max_entries=3)
    for k in ("a", "b", "c", "d"):
        s.add(k)
    assert s.size() == 3
    assert not s.contains("a")  # 最旧被逐出
    assert s.contains("d")


def test_dispatch_key_priority():
    assert ddi.dispatch_key_for({"idempotency_key": "ik", "task_id": "t"}) == "ik"
    assert ddi.dispatch_key_for({"task_id": "t", "request_id": "r"}) == "t"
    assert ddi.dispatch_key_for({"request_id": "r"}) == "r"
    assert ddi.dispatch_key_for({}) == ""
    assert ddi.dispatch_key_for(None) == ""


def test_enabled_flag(monkeypatch):
    monkeypatch.delenv("GALAXY_DISPATCH_IDEMPOTENCY", raising=False)
    assert ddi.dispatch_idempotency_enabled() is True  # 默认开
    monkeypatch.setenv("GALAXY_DISPATCH_IDEMPOTENCY", "0")
    assert ddi.dispatch_idempotency_enabled() is False


def test_helpers_noop_on_empty_key(tmp_path, monkeypatch):
    monkeypatch.setattr(ddi, "_DEFAULT_DISPATCH_ID_STORE_PATH", str(tmp_path / "d.json"))
    assert ddi.already_dispatched("") is False
    assert ddi.mark_dispatched("") is False
    assert ddi.unmark_dispatched("") is False
    assert ddi.mark_dispatched("real") is True
    assert ddi.already_dispatched("real") is True
