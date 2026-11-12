"""最后兜底的两条下发路径,帧里也带设备读的 ``params``。

规范下发(``send_command_and_wait``)把参数放在 ``params``;安卓 ``DeviceCommandFrames.params`` 只读这个键。
``CommandRouter`` 的 WebSocket 兜底与 ``openclawd.send_gateway_command`` 的最终降级原先只放 ``payload`` ——
走到这两条时手机拿到的是空参数(核对两个 App 时记下的建议,第 18 轮补上)。``payload`` 留着给旧客户端。
"""

from __future__ import annotations

import asyncio
import inspect
import time
from types import SimpleNamespace


def test_the_command_router_fallback_frame_carries_params(monkeypatch):
    import core.routes._shared as shared
    from core.command_router import CommandRouter

    sent = []

    async def send_to_device(device_id, frame):
        sent.append((device_id, frame))
        return True

    monkeypatch.setattr(
        shared, "connection_manager", SimpleNamespace(is_online=lambda _d: True, send_to_device=send_to_device)
    )
    router = CommandRouter()
    router._executor = None

    async def no_device_router(**_kw):
        return None

    router._dispatch_via_device_router = no_device_router  # type: ignore[assignment]
    out = asyncio.run(
        router._dispatch_to_device(
            device_id="p1",
            command="notification",
            payload={"title": "中心", "text": "到了"},
            command_id="c1",
            task_id="t1",
            timeout=5,
            trace_base={},
            trace_id="tr1",
            t0=time.monotonic(),
        )
    )
    assert out["success"] is True, out
    ((did, frame),) = sent
    assert did == "p1" and frame["type"] == "command" and frame["command"] == "notification"
    assert frame["params"] == {"title": "中心", "text": "到了"}, "设备读的是 params"
    assert frame["payload"] == frame["params"], "旧客户端读 payload,照旧给"


def test_the_openclawd_last_resort_frame_carries_params():
    from core.openclawd import OpenClawd

    src = inspect.getsource(OpenClawd.send_gateway_command)
    tail = src[src.index("最终降级：WebSocket") :]
    frame = tail[: tail.index('"command_id"')]
    assert '"params": payload or {}' in frame and '"payload": payload or {}' in frame, frame
