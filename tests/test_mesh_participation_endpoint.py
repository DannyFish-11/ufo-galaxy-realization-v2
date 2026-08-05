"""tests/test_mesh_participation_endpoint.py
============================================

``GET /api/v1/mesh/participation-summary`` —— 把网格参与状态接出去。

``core/mesh_participation_summary.py`` 把六个子系统(设备编队、body mesh 注册表、
mesh session、mesh membership、session coordinator、跨设备策略)的状态摊平成一份
可序列化视图,只读、不改任何编排行为。

在这个端点之前它**没有任何生产消费方** —— 建好了却没接出去的诊断面,只有测试
在看。而"网格里现在到底谁在、各是什么角色"恰恰是排查多设备问题时第一个要问的。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.routes import diagnostics


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(diagnostics.create_router())
    return TestClient(app)


def test_endpoint_returns_the_participation_summary(client: TestClient):
    """200 + 摘要该有的那几个字段。"""
    r = client.get("/api/v1/mesh/participation-summary")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert "error" not in payload, f"聚合失败:{payload}"
    for key in ("session_id", "device_ids", "roles_by_device"):
        assert key in payload, f"缺字段 {key}:{sorted(payload)}"


def test_payload_is_json_serialisable_all_the_way_down(client: TestClient):
    """摘要里不能混进 enum / dataclass 这类 JSONResponse 编不了的东西。

    ``to_dict()`` 存在不等于它产出的每一层都是原生类型 —— 真正走一遍 HTTP
    才算数(TestClient 会真的做序列化)。
    """
    payload = client.get("/api/v1/mesh/participation-summary").json()
    assert isinstance(payload["device_ids"], list)
    assert isinstance(payload["roles_by_device"], dict)


def test_the_route_is_registered_under_the_diagnostics_router():
    """路由必须挂在**诊断**路由器上 —— 这决定了它跟着 /api/v1 一起被挂载。

    挂到一个没人 include 的路由器上,与"没接出去"是同一个结果:端点存在、
    却永远收不到请求。所以这里直接问 create_router() 出来的那个 router。
    """
    paths = {getattr(r, "path", "") for r in diagnostics.create_router().routes}
    assert "/api/v1/mesh/participation-summary" in paths


def test_aggregation_failure_returns_500_not_a_crash(client: TestClient, monkeypatch):
    """底下任何一个子系统炸了,端点回 500,而不是把整个进程带下去。

    这个摘要要聚合六个子系统,其中任何一个在半初始化状态下都可能抛。
    """
    import core.mesh_participation_summary as mod

    def _boom():
        raise RuntimeError("子系统没起来")

    monkeypatch.setattr(mod, "get_current_mesh_participation_summary", _boom)
    r = client.get("/api/v1/mesh/participation-summary")
    assert r.status_code == 500
    assert "unavailable" in r.json()["error"]


def test_failure_response_does_not_leak_exception_detail(client: TestClient, monkeypatch, caplog):
    """500 的响应体里不许出现异常细节,但日志里必须有。

    这条钉的是 CodeQL alert 1066(information exposure through an exception):
    这个端点最初就是 ``return JSONResponse({"error": str(e)})`` —— 六个子系统里
    任何一个抛出来的栈信息(内部模块路径、对象名)都会原样回给调用方。而这是个
    **诊断**端点,天生就是给"能连上但不该知道内部结构"的人用的。

    两头一起断言:响应体里查不到那句异常消息,服务端日志里查得到。只断言前者的话,
    "把错误吞了什么都不记"也能通过 —— 那是另一种坏。
    """
    import logging

    import core.mesh_participation_summary as mod

    secret = "内部模块路径不该外泄"

    def _boom():
        raise RuntimeError(secret)

    monkeypatch.setattr(mod, "get_current_mesh_participation_summary", _boom)
    with caplog.at_level(logging.ERROR, logger="Galaxy.API"):
        r = client.get("/api/v1/mesh/participation-summary")

    assert secret not in r.text, f"异常细节泄漏到响应体:{r.text}"
    assert secret in caplog.text, "异常细节也没进日志 —— 那就没法排查了"
