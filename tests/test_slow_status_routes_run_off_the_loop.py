"""三个状态接口在工作线程里算，不占事件循环。

全面排查第 6 轮真跑（沙箱里第一次有了 Docker）：把 245 条 GET 打一遍，卡顿记录抓到事件循环被卡 0.4 秒 ——
``/api/v1/operator/board/operable-truth`` 在循环里同步聚合整块看板（约 0.45 秒）；``/api/v1/system/container-runtime``
在循环里跑 docker / podman 子进程（这里 0.27 秒，Windows 上 Podman 虚机没起来时一次就是几秒）；
``/api/v1/system/completion-status`` 同步重建整份完成度报告。循环卡住的那一下，面板、覆盖层、对话流的请求一起等。

判据：被调的那个函数里拿不到正在跑的事件循环（工作线程里没有循环）。
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _on_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


class _Report:
    def __init__(self, seen):
        self.seen = seen

    def to_dict(self):
        self.seen.append(("to_dict", _on_loop()))
        return {"ok": True}


@pytest.fixture()
def api():
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    with TestClient(app) as c:
        yield c


def test_the_operator_board_is_built_off_the_loop(api, auth_headers, monkeypatch):
    import core.pr4_operator_action_governance as gov

    seen = []

    def build():
        seen.append(("build", _on_loop()))
        return _Report(seen)

    monkeypatch.setattr(gov, "build_operator_board_projection", build)
    r = api.get("/api/v1/operator/board/operable-truth", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert seen == [("build", False), ("to_dict", False)], f"看板在事件循环里算了: {seen}"


def test_the_container_runtime_probe_runs_off_the_loop(api, auth_headers, monkeypatch):
    import core.container_runtime as cr

    seen = []
    monkeypatch.setattr(cr, "inspect_runtime_state", lambda: seen.append(_on_loop()) or {"runtime": None})
    monkeypatch.setattr(cr, "test_runtime", lambda rt: seen.append(_on_loop()) or {"ok": False})
    monkeypatch.setattr(cr, "set_runtime_choice", lambda rt, source="": seen.append(_on_loop()) or {"ok": True})
    assert api.get("/api/v1/system/container-runtime", headers=auth_headers).status_code == 200
    assert (
        api.post("/api/v1/system/container-runtime/test", json={"runtime": "docker"}, headers=auth_headers).status_code
        == 200
    )
    assert (
        api.post(
            "/api/v1/system/container-runtime/choice", json={"runtime": "docker"}, headers=auth_headers
        ).status_code
        == 200
    )
    assert seen == [False, False, False], f"docker / podman 子进程在事件循环里跑了: {seen}"


def test_the_completion_status_is_built_off_the_loop(api, auth_headers, monkeypatch):
    import core.system_completion_status as scs

    seen = []

    def build(force_rebuild=False):
        seen.append(("build", _on_loop()))
        return _Report(seen)

    monkeypatch.setattr(scs, "get_system_completion_status", build)
    assert api.get("/api/v1/system/completion-status", headers=auth_headers).status_code == 200
    assert seen == [("build", False), ("to_dict", False)], f"完成度报告在事件循环里算了: {seen}"
