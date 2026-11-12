"""整份落盘不在事件循环里做,新的不会被旧的盖掉(``core/persist_off_loop.py``)。

第 17 轮真跑:设备断连时 ``android_device_state_store`` 在事件循环里把整份状态重新编码写盘,卡住循环 0.6 秒。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time

from core.persist_off_loop import OffLoopWriter


def test_outside_a_loop_it_writes_in_place():
    seen = []
    OffLoopWriter(seen.append, "t").submit("a")
    assert seen == ["a"]


def test_on_the_loop_the_write_happens_on_another_thread_and_newest_wins():
    written, threads = [], []
    gate = threading.Event()

    def slow_write(text):
        if text == "old":
            gate.wait(2)  # 旧的那份拖到新的写完以后
        threads.append(threading.get_ident())
        written.append(text)

    w = OffLoopWriter(slow_write, "t")

    async def main():
        loop_thread = threading.get_ident()
        w.submit("old")
        await asyncio.sleep(0.05)
        w.submit("new")
        await asyncio.sleep(0.2)
        gate.set()
        await asyncio.sleep(0.2)
        return loop_thread

    loop_thread = asyncio.run(main())
    assert loop_thread not in threads, "不在事件循环线程上写"
    # 旧的那份先拿到了写锁、写在新的之前,或者被跳过 —— 最后落盘的一定是新的
    assert written[-1] == "new", written


def test_dropped_writes_are_not_written_back_after_a_clear():
    written = []
    gate = threading.Event()

    def write(text):
        gate.wait(2)
        written.append(text)

    w = OffLoopWriter(write, "t")

    async def main():
        w.submit("first")  # 拿到写锁、卡在 gate 上
        await asyncio.sleep(0.05)
        w.submit("pending")
        await asyncio.sleep(0.05)
        threading.Thread(target=lambda: (time.sleep(0.1), gate.set())).start()
        await asyncio.to_thread(w.drop_pending)
        await asyncio.sleep(0.2)

    asyncio.run(main())
    assert "pending" not in written, written


def test_the_android_device_state_store_writes_off_the_loop(tmp_path, monkeypatch):
    import core.persist_off_loop as pol
    from core.android_device_state_store import (
        absorb_device_state_snapshot,
        get_device_state_snapshot,
        reset_android_device_state_store,
    )

    path = tmp_path / "store.json"
    monkeypatch.setenv("ANDROID_DEVICE_STATE_STORE_PATH", str(path))
    reset_android_device_state_store(clear_durable_state=True)
    where = []
    real = pol.OffLoopWriter._write

    def spy(self, seq, text):
        where.append(threading.get_ident())
        return real(self, seq, text)

    monkeypatch.setattr(pol.OffLoopWriter, "_write", spy)

    async def main():
        absorb_device_state_snapshot("d1", {"model_ready": True, "snapshot_seq": 1})
        for _ in range(50):
            if path.exists():
                break
            await asyncio.sleep(0.02)
        return threading.get_ident()

    loop_thread = asyncio.run(main())
    assert where and loop_thread not in where
    assert json.loads(path.read_text(encoding="utf-8"))["snapshots"][0]["device_id"] == "d1"
    reset_android_device_state_store(clear_durable_state=False)
    assert get_device_state_snapshot("d1") is not None, "重启后照样读得回来"
    reset_android_device_state_store(clear_durable_state=True)
