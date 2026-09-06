"""回流存储的账本性质。

这个模块此前**一条测试都没有**,而它承担的是"上下文只有一份"里那一份的落盘。

要钉的三件事
------------
1. 历史不能在载入时坍缩。文件本来就是追加写的,但重启后每个任务只剩最新一条 ——
   追加了却在载入时丢掉,等于白追加。
2. 补传要幂等。断网缓存、联网补传是设计里明写的形态,补传必然产生重复;
   ``(device_id, seq)`` 是判重的唯一依据。
3. ``get()`` 的形状不能变。``/api/v1/memory/query`` 返回 ``[entry]``,Android 侧是
   parseFirstEntry 取第一条 —— 改成返回全部历史,安卓拿到的会是**最旧**那条,而且不报错。
"""

from __future__ import annotations

import json

import pytest

from core.memory.android_backflow import AndroidMemoryBackflow


@pytest.fixture
def store(tmp_path, monkeypatch):
    """一个落在临时目录、且不触碰统一记忆的存储。

    统一记忆首次写入会拉起嵌入模型;这一组测试要钉的是账本语义,不该为此等模型加载。
    """
    inst = AndroidMemoryBackflow(path=str(tmp_path / "backflow.jsonl"))
    monkeypatch.setattr(inst, "_mirror_to_unified", lambda e: None)
    return inst


def _entry(task_id: str, seq: int, *, device: str = "phone_a", status: str = "running", **kw):
    base = {
        "task_id": task_id,
        "device_id": device,
        "seq": seq,
        "goal": "打开设置",
        "status": status,
        "summary": f"第 {seq} 步",
        "steps": [f"step{seq}"],
        "route_mode": "local",
        "timestamp_ms": 1_700_000_000_000 + seq,
    }
    base.update(kw)
    return base


# ── 1. 历史不再坍缩 ────────────────────────────────────────────────────


def test_a_task_keeps_every_event_not_just_the_last(store):
    for i in (1, 2, 3):
        store.store(_entry("t1", i))

    assert len(store.history("t1")) == 3, "同一任务的中间步骤被吞掉了"
    assert [e["summary"] for e in store.history("t1")] == ["第 1 步", "第 2 步", "第 3 步"]


def test_history_survives_a_reload(tmp_path, monkeypatch):
    """重启之后历史还在 —— 这是改动前真正丢东西的地方。

    改动前 ``_load`` 是 ``self._index[tid] = e``,后写覆盖:磁盘上三行,内存里一条。
    """
    path = str(tmp_path / "backflow.jsonl")
    first = AndroidMemoryBackflow(path=path)
    monkeypatch.setattr(first, "_mirror_to_unified", lambda e: None)
    for i in (1, 2, 3):
        first.store(_entry("t1", i))

    reloaded = AndroidMemoryBackflow(path=path)

    assert len(reloaded.history("t1")) == 3, "重启后中间步骤丢了 —— 磁盘上有,内存里没了"


def test_recent_counts_events_not_tasks(store):
    """ "最近 20 条"问的是最近发生了什么,不是最近 20 个任务的终态。"""
    for i in (1, 2, 3):
        store.store(_entry("t1", i))
    store.store(_entry("t2", 4))

    recent = store.recent(10)

    assert len(recent) == 4
    assert recent[0]["seq"] == 4, "recent 应当新的在前"


# ── 2. 补传幂等 ────────────────────────────────────────────────────────


def test_a_replayed_event_is_not_stored_twice(store):
    """断网缓存 + 联网补传必然重复。(device_id, seq) 相同就是同一条。"""
    e = _entry("t1", 7)
    store.store(e)
    store.store(dict(e))  # 补传:同一条又发了一次

    assert len(store.history("t1")) == 1, "补传把同一条事件记了两遍"


def test_same_seq_from_a_different_device_is_a_different_event(store):
    """序号是**每设备**单调的。两台设备各自的 seq=1 是两件事,不是重复。"""
    store.store(_entry("t1", 1, device="phone_a"))
    store.store(_entry("t1", 1, device="watch_b"))

    assert len(store.history("t1")) == 2, "把两台设备的同号事件当成了重复"


def test_events_without_seq_are_all_kept(store):
    """发送侧还没补上 device_id/seq 时,退化成照单全收。

    宁可暂时不去重,不可误删 —— 没有序号时无法证明两条是同一条,而删错一条事件
    是不可逆的。
    """
    for _ in range(3):
        store.store({"task_id": "t1", "goal": "g", "status": "running", "summary": "s"})

    assert len(store.history("t1")) == 3


def test_replay_is_idempotent_across_reload(tmp_path, monkeypatch):
    """整个文件重放一遍,结果必须和只放一遍一样。"""
    path = str(tmp_path / "backflow.jsonl")
    first = AndroidMemoryBackflow(path=path)
    monkeypatch.setattr(first, "_mirror_to_unified", lambda e: None)
    for i in (1, 2):
        first.store(_entry("t1", i))

    # 把文件内容整个再追加一遍,模拟"补传了一批已经收过的事件"
    with open(path, encoding="utf-8") as fh:
        lines = fh.readlines()
    with open(path, "a", encoding="utf-8") as fh:
        fh.writelines(lines)

    reloaded = AndroidMemoryBackflow(path=path)

    assert len(reloaded.history("t1")) == 2, "重放整个文件之后事件翻倍了"


# ── 3. get() 的形状不能变 ──────────────────────────────────────────────


def test_get_still_returns_the_latest_state(store):
    """Android 侧 parseFirstEntry 取的就是这一条。"""
    store.store(_entry("t1", 1, status="running"))
    store.store(_entry("t1", 2, status="done"))

    latest = store.get("t1")

    assert latest is not None
    assert latest["status"] == "done", "get() 必须回答'现在什么状态',不是'最早什么状态'"
    assert latest["seq"] == 2


def test_get_returns_none_for_unknown_task(store):
    assert store.get("nope") is None
    assert store.history("nope") == []


# ── 4. 落盘仍然是追加写 ────────────────────────────────────────────────


def test_every_event_reaches_disk(store, tmp_path):
    for i in (1, 2, 3):
        store.store(_entry("t1", i))

    lines = [json.loads(x) for x in open(store._path, encoding="utf-8") if x.strip()]

    assert len(lines) == 3, "磁盘上少了事件 —— 账本的前提是每条都落下去"
    assert [x["seq"] for x in lines] == [1, 2, 3]


def test_a_corrupt_line_does_not_swallow_the_rest(tmp_path, monkeypatch):
    """半个损坏的文件不能看起来和完整文件一样。"""
    path = tmp_path / "backflow.jsonl"
    good = json.dumps(_entry("t1", 1), ensure_ascii=False)
    path.write_text(good + "\n{ 这行坏了\n" + json.dumps(_entry("t1", 2), ensure_ascii=False) + "\n", encoding="utf-8")

    inst = AndroidMemoryBackflow(path=str(path))

    assert len(inst.history("t1")) == 2, "坏行把后面的好行一起丢了"
