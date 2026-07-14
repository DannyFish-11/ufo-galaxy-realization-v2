"""tests/test_rate_limit_loopback_exemption.py
=================================================
用户反馈:「模型」tab 填好 API Key 点保存,显示"保存失败"——排查过 InputValidation
(不是它)、CORS/IPC(不是它)后，定位到真正根因：速率限制误伤本机流量。

根因:本仓库是本机可信单用户桌面应用——Electron 主进程 + 渲染层 + 面板轮询
(/api/v1/panel/feed 每 5 秒)+ WS + 桌面连续感知帧上传，全部从 127.0.0.1 打向
同一个本地后端。两处独立的速率限制中间件(core/security_middleware.py 的
120 req/min·突发 30，core/performance.py 的 200 req/60s)都按【客户端 IP】
分桶——本机所有这些流量共享同一个令牌桶。仅面板启动的初始化请求
(GET /api/config、/api/config/all、/api/v1/system/mcp、/api/v1/system/skills…)
加上 WS 握手、轮询、感知帧，就足以在几秒内把预算耗尽。用户点"保存"这种偶发
交互，只要撞上预算耗尽的窗口，就会被无差别 429——跟 API Key 内容、保存逻辑
完全无关(纯负载巧合，代码层面难以稳定复现，这也是为何早前的单元测试/集成
测试都测不出这个问题)。

修复:两处限流中间件都默认放行回环地址(127.0.0.1/::1/localhost)的流量——
对本机应用限制自己没有实际防护意义(不存在"限制自己攻自己"这种威胁模型)。
GALAXY_RATE_LIMIT_LOOPBACK=1 可强制对回环地址也限流(如需专门测试限流行为)。
外部(非回环)IP 的限流保护完全不受影响。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.performance import RateLimitMiddleware as PerformanceRateLimitMiddleware
from core.security_middleware import RateLimiter as SecurityRateLimiter
from core.security_middleware import create_rate_limit_middleware


class TestSecurityMiddlewareLoopbackExemption:
    """core/security_middleware.py 的限流层(默认 120rpm/突发 30)。"""

    def _make_app(self, burst=1, rpm=1):
        app = FastAPI()

        @app.post("/api/config")
        async def save_config():
            return {"success": True}

        limiter = SecurityRateLimiter(requests_per_minute=rpm, burst_size=burst)
        create_rate_limit_middleware(app, limiter)
        return app

    def test_loopback_traffic_not_blocked_after_budget_exhausted(self, monkeypatch):
        monkeypatch.delenv("GALAXY_RATE_LIMIT_LOOPBACK", raising=False)
        app = self._make_app(burst=1, rpm=1)
        client = TestClient(app, client=("127.0.0.1", 12345))

        r1 = client.post("/api/config", json={"config": {}})
        assert r1.status_code == 200
        r2 = client.post("/api/config", json={"config": {}})
        assert r2.status_code == 200, (
            "本机回环地址的请求不该被本应用自己的轮询流量误伤限流——" '这正是用户反馈的"保存失败"根因'
        )

    def test_external_ip_still_rate_limited(self, monkeypatch):
        """修复不能削弱对真实外部客户端的限流保护。"""
        monkeypatch.delenv("GALAXY_RATE_LIMIT_LOOPBACK", raising=False)
        app = self._make_app(burst=1, rpm=1)
        client = TestClient(app, client=("203.0.113.7", 54321))

        r1 = client.post("/api/config", json={"config": {}})
        assert r1.status_code == 200
        r2 = client.post("/api/config", json={"config": {}})
        assert r2.status_code == 429, "外部(非回环)IP 依然应该被正常限流"

    def test_env_override_forces_loopback_rate_limiting(self, monkeypatch):
        """GALAXY_RATE_LIMIT_LOOPBACK=1 时,回环地址也应恢复限流(用于专门测试限流本身)。"""
        monkeypatch.setenv("GALAXY_RATE_LIMIT_LOOPBACK", "1")
        app = self._make_app(burst=1, rpm=1)
        client = TestClient(app, client=("127.0.0.1", 12345))

        r1 = client.post("/api/config", json={"config": {}})
        assert r1.status_code == 200
        r2 = client.post("/api/config", json={"config": {}})
        assert r2.status_code == 429


class TestPerformanceMiddlewareLoopbackExemption:
    """core/performance.py 的第二道限流层(默认 200 req/60s)。

    注意:这道限流层的 RateLimiter.burst 固定用类默认值 20(RateLimitMiddleware
    未把 burst 暴露为可配置参数)——只有 current_count >= max_requests 【且】
    最近 1 秒内的请求数 >= 20 才会真正拒绝,所以复现"外部 IP 应被限流"要发
    足够多(> 20)的高速请求，而不能只送 2 个。
    """

    def _make_app(self, max_requests=1, window_seconds=60):
        app = FastAPI()

        @app.post("/api/config")
        async def save_config():
            return {"success": True}

        app.add_middleware(
            PerformanceRateLimitMiddleware,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        return app

    def test_loopback_traffic_not_blocked(self, monkeypatch):
        monkeypatch.delenv("GALAXY_RATE_LIMIT_LOOPBACK", raising=False)
        app = self._make_app(max_requests=1)
        client = TestClient(app, client=("127.0.0.1", 12345))

        for _ in range(25):
            r = client.post("/api/config", json={"config": {}})
            assert r.status_code == 200, "本机回环地址不该被这道限流层误伤，无论打多少次"

    def test_external_ip_still_rate_limited(self, monkeypatch):
        monkeypatch.delenv("GALAXY_RATE_LIMIT_LOOPBACK", raising=False)
        app = self._make_app(max_requests=1)
        client = TestClient(app, client=("203.0.113.7", 54321))

        statuses = [client.post("/api/config", json={"config": {}}).status_code for _ in range(25)]
        assert 429 in statuses, f"外部(非回环)IP 高速打 25 次请求，应该在某一次触发 429；" f"实际全部状态码: {statuses}"
