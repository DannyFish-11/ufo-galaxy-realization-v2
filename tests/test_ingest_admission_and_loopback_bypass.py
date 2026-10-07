"""感知帧积压时不拖垮整个后端：准入、本机绕过、纯 ASGI 计时。

被修的问题（Windows 真机日志）：事件循环卡几秒期间，采集端积压的几十份感知帧同时压进来，每份几百 KB 的
请求体都要走解析 + 4 层 BaseHTTPMiddleware，于是「几十个请求同一毫秒完成、各自耗时 5.4 秒」，面板的轻量接口也被拖到
5 秒。实测：一份 400KB 的帧在线上那条链上约 17ms CPU（0 层约 2ms，每层约 +1.2ms）。
"""

from __future__ import annotations

import asyncio
import base64
import os

import httpx
import pytest
from fastapi import FastAPI

from core.performance import (
    IngestAdmissionMiddleware,
    LoopbackBypass,
    RateLimitMiddleware,
    RequestTimerMiddleware,
    ResponseCompressor,
    install_performance_middlewares,
    rate_limit_keeps_loopback,
)


def _app_with_slow_ingest(hold: asyncio.Event | None = None):
    app = FastAPI()
    seen = {"handled": 0}

    @app.post("/api/perception/desktop/frame")
    async def frame(body: dict):
        seen["handled"] += 1
        if hold is not None:
            await hold.wait()
        return {"success": True, "stored": "frame"}

    @app.get("/api/v1/ping")
    async def ping():
        return {"ok": True}

    @app.post("/api/v1/other")
    async def other(body: dict):
        return {"ok": True}

    app.add_middleware(IngestAdmissionMiddleware)
    return app, seen


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


FRAME = {
    "image_base64": base64.b64encode(os.urandom(50_000)).decode(),
    "mime": "image/jpeg",
    "source": "desktop_screen",
}


class TestIngestAdmission:
    def test_a_burst_beyond_the_cap_is_refused_fast_and_the_rest_are_served(self):
        async def scenario():
            hold = asyncio.Event()
            app, seen = _app_with_slow_ingest(hold)
            async with _client(app) as c:
                posts = [asyncio.create_task(c.post("/api/perception/desktop/frame", json=FRAME)) for _ in range(10)]
                await asyncio.sleep(0.3)
                refused_now = [t for t in posts if t.done()]
                hold.set()
                results = await asyncio.gather(*posts)
            return refused_now, results, seen["handled"]

        refused_now, results, handled = asyncio.run(scenario())
        codes = sorted(r.status_code for r in results)
        assert codes.count(200) == IngestAdmissionMiddleware.MAX_IN_FLIGHT
        assert codes.count(429) == 10 - IngestAdmissionMiddleware.MAX_IN_FLIGHT
        assert handled == IngestAdmissionMiddleware.MAX_IN_FLIGHT, "多出来的请求不该进到处理函数（也就没解析请求体）"
        assert len(refused_now) == 10 - IngestAdmissionMiddleware.MAX_IN_FLIGHT, "被拒的没有立刻回"
        refused = next(r for r in results if r.status_code == 429)
        assert refused.json()["busy"] is True and refused.headers["retry-after"] == "1"

    def test_the_slot_is_given_back_so_later_frames_are_accepted(self):
        async def scenario():
            app, _ = _app_with_slow_ingest()
            async with _client(app) as c:
                first = [await c.post("/api/perception/desktop/frame", json=FRAME) for _ in range(5)]
            return [r.status_code for r in first]

        assert asyncio.run(scenario()) == [200] * 5

    def test_other_endpoints_are_never_throttled(self):
        async def scenario():
            hold = asyncio.Event()
            app, _ = _app_with_slow_ingest(hold)
            async with _client(app) as c:
                frames = [asyncio.create_task(c.post("/api/perception/desktop/frame", json=FRAME)) for _ in range(6)]
                await asyncio.sleep(0.2)
                others = await asyncio.gather(*[c.get("/api/v1/ping") for _ in range(20)])
                posts = await asyncio.gather(*[c.post("/api/v1/other", json={"a": 1}) for _ in range(20)])
                hold.set()
                await asyncio.gather(*frames)
            return [r.status_code for r in others + posts]

        assert set(asyncio.run(scenario())) == {200}


class TestLoopbackBypass:
    def _wrapped_app(self, **kw):
        app = FastAPI()
        order = []

        class Marker:
            def __init__(self, app, **_):
                self.app = app

            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    order.append("marker")
                await self.app(scope, receive, send)

        @app.get("/x")
        async def x():
            return {"ok": True}

        app.add_middleware(LoopbackBypass, middleware_cls=Marker, **kw)
        return app, order

    def _call(self, app, client_addr, headers=None):
        async def go():
            transport = httpx.ASGITransport(app=app, client=client_addr)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return await c.get("/x", headers=headers or {})

        return asyncio.run(go())

    def test_local_requests_skip_the_layer(self):
        app, order = self._wrapped_app()
        assert self._call(app, ("127.0.0.1", 5000)).status_code == 200
        assert order == []

    def test_ipv6_loopback_too(self):
        app, order = self._wrapped_app()
        self._call(app, ("::1", 5000))
        assert order == []

    def test_other_clients_still_go_through_it(self):
        app, order = self._wrapped_app()
        assert self._call(app, ("203.0.113.9", 5000)).status_code == 200
        assert order == ["marker"]

    def test_keep_if_can_force_a_local_request_through(self):
        app, order = self._wrapped_app(keep_if=lambda scope: True)
        self._call(app, ("127.0.0.1", 5000))
        assert order == ["marker"]


class TestRateLimitStillWorksWhereItShould:
    def test_the_rate_limiter_is_still_applied_to_external_clients_and_to_local_api_keys(self, monkeypatch):
        monkeypatch.delenv("GALAXY_RATE_LIMIT_LOOPBACK", raising=False)
        app = FastAPI()

        @app.get("/x")
        async def x():
            return {"ok": True}

        app.add_middleware(
            LoopbackBypass,
            middleware_cls=RateLimitMiddleware,
            keep_if=rate_limit_keeps_loopback,
            max_requests=1,
            window_seconds=60,
        )

        async def codes(addr, headers=None, n=3):
            transport = httpx.ASGITransport(app=app, client=addr)
            async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
                return [(await c.get("/x", headers=headers or {})).status_code for _ in range(n)]

        assert asyncio.run(codes(("127.0.0.1", 1))) == [200, 200, 200], "本机回环默认放行"
        external = asyncio.run(codes(("203.0.113.7", 1)))
        assert external[0] == 200 and 429 in external, "外部地址的限流不能被绕过"
        keyed = asyncio.run(codes(("127.0.0.1", 1), headers={"x-api-key": "k1"}))
        assert 429 in keyed, "本机请求显式带 x-api-key 时仍按 key 限流"

    def test_forcing_loopback_limits_via_the_existing_env(self, monkeypatch):
        monkeypatch.setenv("GALAXY_RATE_LIMIT_LOOPBACK", "1")
        assert rate_limit_keeps_loopback({"headers": []}) is True


class TestTimerIsPureAsgiAndKeepsItsContract:
    def test_response_time_header_and_slow_log(self, caplog):
        app = FastAPI()

        @app.get("/slow")
        async def slow():
            await asyncio.sleep(0.05)
            return {"ok": True}

        @app.get("/boom")
        async def boom():
            raise RuntimeError("x")

        app.add_middleware(RequestTimerMiddleware, slow_threshold_ms=10)

        async def go():
            async with _client(app) as c:
                ok = await c.get("/slow")
                with pytest.raises(RuntimeError):
                    await c.get("/boom")
                return ok

        with caplog.at_level("WARNING", logger="Galaxy.Performance"):
            ok = asyncio.run(go())
        assert ok.headers["x-response-time"].endswith("ms")
        assert any("Slow request: GET /slow" in r.getMessage() for r in caplog.records)

    def test_the_timer_is_not_a_basehttp_middleware_any_more(self):
        from starlette.middleware.base import BaseHTTPMiddleware

        assert not issubclass(RequestTimerMiddleware, BaseHTTPMiddleware)


def test_the_installed_chain_has_the_expected_order():
    app = FastAPI()
    install_performance_middlewares(app, cache=None)
    names = [m.cls.__name__ for m in app.user_middleware]  # 最外层在前
    assert names[:2] == ["ClientDisconnectGuardMiddleware", "IngestAdmissionMiddleware"]
    assert "RequestTimerMiddleware" in names and names.count("LoopbackBypass") == 2
    wrapped = [m.kwargs["middleware_cls"] for m in app.user_middleware if m.cls.__name__ == "LoopbackBypass"]
    assert ResponseCompressor in wrapped and RateLimitMiddleware in wrapped
