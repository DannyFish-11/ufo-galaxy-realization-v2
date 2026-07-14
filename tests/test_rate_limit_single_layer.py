"""tests/test_rate_limit_single_layer.py
==========================================
回归防护:HTTP 限流【单层收口】—— 主 app 不再叠加两个独立限流器。

背景
----
主 app 曾同时安装两个 HTTP 速率限制中间件:
  1. core.performance.RateLimitMiddleware —— core/startup.py 步骤 3
     (apikey-or-ip 分桶、可配置、回环豁免)。权威层。
  2. core.security_middleware 的 RateLimitMiddleware —— SecurityManager.setup_middleware
     经 create_rate_limit_middleware 安装(按 IP、120rpm)。

两者挂在同一个 app 上 → 同一条 HTTP 请求被两个独立限流器双重计数,阈值/分桶键
还不一致(更严的静默生效)。这是意外重复,非有意分层。

修复:SecurityManager.setup_middleware 增加 include_rate_limit 开关;主 app 挂载时
传 False,把 HTTP 限流收口到性能层唯一一处。SecurityManager 单独使用(无性能层)时
默认仍自带限流。
"""

from __future__ import annotations

from fastapi import FastAPI

from core.security_middleware import SecurityManager


def test_setup_middleware_can_omit_rate_limit_layer():
    """include_rate_limit=False 时,应恰好少装一个中间件(那一层限流)。"""
    with_rl = FastAPI()
    SecurityManager().setup_middleware(with_rl, include_rate_limit=True)

    without_rl = FastAPI()
    SecurityManager().setup_middleware(without_rl, include_rate_limit=False)

    delta = len(with_rl.user_middleware) - len(without_rl.user_middleware)
    assert delta == 1, f"include_rate_limit 应恰好切换一个限流中间件,实际差 {delta} 个"


def test_default_still_includes_rate_limit_for_standalone_use():
    """默认(不传参)保持含限流——SecurityManager 单独用时不丢保护。"""
    default_app = FastAPI()
    SecurityManager().setup_middleware(default_app)

    explicit_off = FastAPI()
    SecurityManager().setup_middleware(explicit_off, include_rate_limit=False)

    assert len(default_app.user_middleware) == len(explicit_off.user_middleware) + 1


def test_startup_wires_security_without_its_own_rate_limit():
    """core/startup.py 必须以 include_rate_limit=False 调 setup_middleware,
    确保 HTTP 限流只由性能层承担(源码级断言,避免有人日后又叠回去)。"""
    import inspect

    import core.startup as startup

    src = inspect.getsource(startup)
    assert "include_rate_limit=False" in src, (
        "core/startup.py 应以 include_rate_limit=False 安装安全中间件," "把 HTTP 限流收口到性能层唯一一处"
    )
