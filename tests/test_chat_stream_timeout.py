"""tests/test_chat_stream_timeout.py
=====================================
面板对话"一直转圈圈不回答"的回归防护。

根因:/api/v1/chat/stream 委派 DesktopPresenceRuntime.handle_request();若没配模型/
模型不可达/首调初始化慢/提供商挂起,该调用可能长时间(甚至无限)不返回,而 SSE
从不吐 done/error → 前端 spinner 永远转 → "转圈圈不回答"。

修复:chat_stream 用 asyncio.wait_for(超时=GALAXY_CHAT_TIMEOUT_S,默认 90s)包裹,
超时即吐一个 error 帧 + silent 相位并收流,保证前端 spinner 一定清除。
"""

from __future__ import annotations

import asyncio
import json

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _collect_frames(resp_iter):
    frames = []
    for line in resp_iter:
        if line and line.startswith("data: "):
            frames.append(json.loads(line[6:]))
    return frames


def test_chat_stream_times_out_instead_of_hanging(monkeypatch):
    """handle_request 挂起时,chat_stream 必须在超时后吐 error+silent 并收流。"""
    monkeypatch.setenv("GALAXY_CHAT_TIMEOUT_S", "2")

    import core.routes.chat as chat_mod
    import core.desktop_presence_runtime as dpr

    class _HangingRuntime:
        async def handle_request(self, *a, **k):
            await asyncio.sleep(999)  # 永不返回

    app = FastAPI()
    app.include_router(chat_mod.create_router(service_manager=None, config=None))
    client = TestClient(app)

    with patch.object(dpr, "get_desktop_presence_runtime", lambda: _HangingRuntime()):
        with client.stream(
            "POST", "/api/v1/chat/stream",
            json={"message": "你好", "session_id": "timeout-test"},
        ) as r:
            frames = _collect_frames(r.iter_lines())

    types = [f.get("type") for f in frames]
    # 必须以 error 收尾并回到 silent —— 前端据此清除 spinner。
    assert "error" in types, f"超时应吐 error 帧; got {types}"
    err = next(f for f in frames if f.get("type") == "error")
    assert "超时" in (err.get("error") or ""), f"error 文案应说明超时; got {err}"
    phases = [f.get("phase") for f in frames if f.get("type") == "phase"]
    assert phases and phases[-1] == "silent", f"末相位应回 silent; got {phases}"
