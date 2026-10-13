"""一批请求同一毫秒一起慢 = 事件循环被一件同步的事占住了。慢请求日志只看得到受害者 ——
``core/loop_stall_watch.py`` 要说出凶手在仓库里哪几行。"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

import core.loop_stall_watch as w


def _hog_the_loop_for(seconds: float) -> None:
    time.sleep(seconds)  # 故意在事件循环里同步睡


class _Said(logging.Handler):
    """直接挂在这个 logger 上收:不依赖冒泡到根(同一进程里别的测试可能改过日志配置)。"""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.lines = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def said(monkeypatch):
    h = _Said()
    monkeypatch.setattr(w.logger, "disabled", False)
    monkeypatch.setattr(w.logger, "level", logging.NOTSET)
    w.logger.addHandler(h)
    yield h.lines
    w.logger.removeHandler(h)


def test_a_stall_is_reported_with_where_it_happened(monkeypatch, said):
    monkeypatch.setattr(w, "_started", False)
    monkeypatch.setattr(w, "STALL_S", 0.3)

    async def run():
        assert w.start()
        await asyncio.sleep(0.3)
        _hog_the_loop_for(0.9)
        await asyncio.sleep(0.6)

    asyncio.run(run())
    assert any("事件循环被卡住" in m and "_hog_the_loop_for" in m for m in said), said


def test_a_healthy_loop_says_nothing(monkeypatch, said):
    monkeypatch.setattr(w, "_started", False)

    async def run():
        assert w.start()
        for _ in range(8):
            await asyncio.sleep(0.1)

    asyncio.run(run())
    assert not [m for m in said if "事件循环被卡住" in m]


def test_no_running_loop_means_no_watch(monkeypatch):
    monkeypatch.setattr(w, "_started", False)
    assert w.start() is False


def test_the_launcher_starts_it_with_the_server():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "launcher" / "services.py").read_text(encoding="utf-8")
    serve = src.index("asyncio.create_task(server.serve())")
    assert "loop_stall_watch.start()" in src[serve : serve + 400]


def test_another_loop_in_the_same_process_does_not_hide_a_stall(monkeypatch, said):
    """心跳归各自的循环:另一个循环一直在跳,也不能把这边的卡顿盖住。"""
    import threading

    monkeypatch.setattr(w, "STALL_S", 0.3)
    other = asyncio.new_event_loop()
    stop = threading.Event()

    def run_other():
        monkeypatch.setattr(w, "_started", False)
        asyncio.set_event_loop(other)

        async def idle():
            w.start()
            while not stop.is_set():
                await asyncio.sleep(0.05)

        other.run_until_complete(idle())

    t = threading.Thread(target=run_other, daemon=True)
    t.start()
    time.sleep(0.3)

    async def run():
        monkeypatch.setattr(w, "_started", False)
        assert w.start()
        await asyncio.sleep(0.3)
        _hog_the_loop_for(0.9)
        await asyncio.sleep(0.6)

    asyncio.run(run())
    stop.set()
    t.join(2)
    other.close()
    assert any("事件循环被卡住" in m and "_hog_the_loop_for" in m for m in said), said


def test_frozen_import_frames_are_not_mistaken_for_repo_code(monkeypatch):
    """所有者日志:卡顿全报在 ``<frozen importlib._bootstrap_external>:991 exec_module`` 上。
    不是文件的帧(当前目录又正好是仓库根)被当成了仓库代码 —— 真正在 import 的那行反而没露面。"""
    import os
    import types

    monkeypatch.chdir(w._REPO)

    def frame(filename, lineno, name, back=None):
        return types.SimpleNamespace(
            f_code=types.SimpleNamespace(co_filename=filename, co_name=name), f_lineno=lineno, f_back=back
        )

    ours = frame(os.path.join(w._REPO, "launcher", "services.py"), 2300, "start_tray")
    stack = frame(
        "<frozen importlib._bootstrap_external>",
        991,
        "exec_module",
        frame("<frozen importlib._bootstrap>", 690, "_load_unlocked", ours),
    )
    said = w.where(stack)
    assert said.startswith(os.path.join("launcher", "services.py") + ":2300 start_tray"), said
    assert "frozen" not in said


def test_the_three_stalls_from_the_owners_startup_log_are_off_the_loop():
    """所有者那次启动里卡住事件循环的三处,都挪到线程里了:

    * 「API 网关」一起来就写 entrypoint.json —— 里面同步跑 ``tailscale ip -4``(2.1 秒,run_text);
    * 「启动自检」跑 ``git log`` 取代码版本;
    * 「系统托盘」import pystray / Pillow / win32(1.6 秒,importlib)。
    """
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "launcher" / "services.py").read_text(encoding="utf-8")
    assert src.count("await asyncio.to_thread(self._write_entrypoint_json)") == 2
    assert "self._write_entrypoint_json()\n" not in src.replace(
        "lambda _action, _details: self._write_entrypoint_json())", ""
    ), "还有在事件循环里同步写 entrypoint.json 的地方"
    assert "await asyncio.to_thread(_url_sentinel_audit)" in src
    assert 'await asyncio.to_thread(importlib.import_module, "windows_service.tray_icon")' in src


def test_fastapi_builds_its_routes_beside_the_loop_not_on_the_first_request():
    """FastAPI 0.14x 在第一个请求时才在事件循环里给全部路由建校验模型(所有者日志:启动时卡 3.8 秒)。
    网关起来前在旁边线程里先生成一遍 OpenAPI,第一个请求就不用现建了。"""
    import inspect
    import time

    from fastapi import APIRouter, FastAPI
    from pydantic import BaseModel
    from starlette.testclient import TestClient

    import launcher.services as svc

    src = inspect.getsource(svc.UnifiedWebUI.start)
    assert src.index("target=_warm_routes") < src.index("asyncio.create_task(server.serve())")

    app = FastAPI()
    for r in range(8):
        router = APIRouter(prefix=f"/r{r}")
        for i in range(25):
            model = type(f"M{r}_{i}", (BaseModel,), {"__annotations__": {"a": int, "b": str}})

            def ep(body: model, _i=i):  # noqa: B008
                return {"ok": _i}

            router.add_api_route(f"/x{i}", ep, methods=["POST"])
        app.include_router(router)

    @app.get("/health")
    def health():
        return {"ok": True}

    svc._warm_routes(app)
    t0 = time.perf_counter()
    assert TestClient(app).get("/health").status_code == 200
    assert time.perf_counter() - t0 < 0.15, "预热之后第一个请求还在现建路由"
