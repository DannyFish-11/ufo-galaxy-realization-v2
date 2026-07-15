"""跨设备回包关联回归:send_to_device 的 future 必须双键(message_id + task_id)登记。

此前只按 `message_id or task_id` 单键登记 future,而结果处理器多按 task_id 解析
(task_lifecycle.py:968/1073/1203/1263)。若一条派发消息同时带 message_id 与 task_id、
设备只回 task_id,future 永远等不到 → "设备回了却超时"。本测试锁死:两个 id 都指向
同一 future,按 task_id 解析即可完成等待,且完成后两个键都被清理。
"""

import asyncio
from types import SimpleNamespace

import pytest

from galaxy_gateway.android_bridge import AndroidBridge


class _FakeWS:
    async def send_json(self, msg):  # noqa: ANN001
        return None


def _bridge_with_device(dev_id="dev1"):
    b = AndroidBridge.__new__(AndroidBridge)
    b._lock = asyncio.Lock()
    b._devices = {dev_id: SimpleNamespace(connected=True, websocket=_FakeWS())}
    b._pending_responses = {}
    return b


@pytest.mark.asyncio
async def test_future_registered_under_both_ids_and_resolves_by_task_id(monkeypatch):
    # 强制 AIPTransport 抛错 → 走 websocket.send_json 兜底路径(与真机同)。
    import core.aip_transport as _t

    monkeypatch.setattr(_t, "get_aip_transport", lambda: (_ for _ in ()).throw(RuntimeError("no transport")))

    b = _bridge_with_device()
    msg = {"type": "task_assign", "device_id": "dev1", "message_id": "mid-1", "task_id": "tid-1"}

    task = asyncio.create_task(b.send_to_device("dev1", msg, wait_response=True, timeout=3))
    # 让 send_to_device 跑到登记 future
    for _ in range(50):
        await asyncio.sleep(0.01)
        if "tid-1" in b._pending_responses:
            break

    # 双键都登记,且指向同一个 future
    assert "mid-1" in b._pending_responses, "message_id 未登记"
    assert "tid-1" in b._pending_responses, "task_id 未登记"
    assert b._pending_responses["mid-1"] is b._pending_responses["tid-1"]

    # 结果处理器按 task_id 解析(此前会 miss 掉 message_id 键的 future)
    b._pending_responses["tid-1"].set_result({"ok": True, "via": "task_id"})

    out = await asyncio.wait_for(task, timeout=3)
    assert out == {"ok": True, "via": "task_id"}, "按 task_id 解析应成功返回"

    # 完成后 done-callback 清掉两个键,无残留
    await asyncio.sleep(0.02)
    assert "mid-1" not in b._pending_responses
    assert "tid-1" not in b._pending_responses


@pytest.mark.asyncio
async def test_timeout_cleans_up_both_keys(monkeypatch):
    import core.aip_transport as _t

    monkeypatch.setattr(_t, "get_aip_transport", lambda: (_ for _ in ()).throw(RuntimeError("no transport")))

    b = _bridge_with_device()
    msg = {"type": "task_assign", "device_id": "dev1", "message_id": "mid-2", "task_id": "tid-2"}

    out = await b.send_to_device("dev1", msg, wait_response=True, timeout=0.1)
    assert out is None, "超时应返回 None"
    # 超时后两个键都不残留
    assert "mid-2" not in b._pending_responses
    assert "tid-2" not in b._pending_responses
