"""一轮对话不在事件循环里整份重写 ``sessions.json``。

每轮对话 ``ensure_session`` 写一次、用户那句和回答各写一次,每次都把**所有**会话(每个最多 200 条历史)
整份序列化、原子替换、fsync。原先在事件循环里同步做:本机 20 个会话 11 ms 一次,30 个满会话 2.6 MB
76 ms 一次(Windows 杀软逐个扫临时文件时更久)—— 一轮对话三次,感知帧、音频、面板请求全跟着停。

现在在工作线程里写,调用方照旧等它写完:``await add_message(...)`` 返回时文件已是新的(重启读得回来的
那些用例不用改)。
"""

from __future__ import annotations

import asyncio
import json
import threading

import pytest


@pytest.fixture
def sm(tmp_path, monkeypatch):
    import core.session_manager as smmod

    state = tmp_path / "sessions.json"
    monkeypatch.setattr(smmod, "_SESSION_FILE", str(state))
    writers: list = []
    real = smmod.atomic_write_json

    def spy(*a, **k):
        writers.append(threading.current_thread())
        return real(*a, **k)

    monkeypatch.setattr(smmod, "atomic_write_json", spy)
    mgr = smmod.SessionManager()
    mgr.state_file, mgr.writers = state, writers  # type: ignore[attr-defined]
    return mgr


@pytest.mark.asyncio
async def test_a_turn_writes_beside_the_loop_and_is_on_disk_when_it_returns(sm):
    loop_thread = threading.current_thread()
    s = await sm.ensure_session("turn-1", user_id="u", device_id="desktop")
    await sm.add_message(s.id, "user", "明天下午三点开会")
    await sm.add_message(s.id, "assistant", "记下了")

    assert len(sm.writers) == 3 and all(t is not loop_thread for t in sm.writers), sm.writers
    saved = json.loads(sm.state_file.read_text(encoding="utf-8"))
    assert [m["content"] for m in saved["sessions"]["turn-1"]["history"]] == ["明天下午三点开会", "记下了"]


@pytest.mark.asyncio
async def test_concurrent_messages_all_reach_the_file(sm):
    """写在旁边的线程里,先进来、后写完的旧快照不能把新的盖掉。"""
    s = await sm.ensure_session("busy", user_id="u")
    await asyncio.gather(*(sm.add_message(s.id, "user", f"第{i}句") for i in range(20)))
    saved = json.loads(sm.state_file.read_text(encoding="utf-8"))
    assert len(saved["sessions"]["busy"]["history"]) == 20


@pytest.mark.asyncio
async def test_during_shutdown_it_still_writes(sm, monkeypatch):
    """停机途中默认执行器已关,``to_thread`` 抛 RuntimeError —— 当场写,这句话不能丢。"""

    async def closed(*_a, **_k):
        raise RuntimeError("cannot schedule new futures after shutdown")

    s = await sm.ensure_session("bye", user_id="u")
    monkeypatch.setattr(asyncio, "to_thread", closed)
    await sm.add_message(s.id, "user", "再见")
    saved = json.loads(sm.state_file.read_text(encoding="utf-8"))
    assert saved["sessions"]["bye"]["history"][-1]["content"] == "再见"


def test_the_file_is_the_same_json_just_not_indented(tmp_path):
    """换成 C 编码器(一口气编完、不让出 GIL)不改内容:和 ``json.dumps`` 逐字节相同,缩进的照旧缩进。"""
    from core.atomic_json import atomic_write_json

    payload = {"会话": [{"k": 1.5, "v": None, "t": True}], "b": "x"}
    flat, pretty = tmp_path / "flat.json", tmp_path / "pretty.json"
    atomic_write_json(flat, payload, indent=None)
    atomic_write_json(pretty, payload)
    assert flat.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False)
    assert pretty.read_text(encoding="utf-8") == json.dumps(payload, ensure_ascii=False, indent=2)
