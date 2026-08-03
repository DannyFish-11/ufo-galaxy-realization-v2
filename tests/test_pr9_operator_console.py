#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_pr9_operator_console.py
====================================
PR-9 — Unified Visual Operator / Ecosystem Console —— 表层已删除后的续存部分。

``static/operator-console/index.html`` 这份并行 Web 表层已随面板收敛删除
（面板唯一表层 = Tauri/Electron 壳内的 React 面板）。原先 1/2/3/5 四组测试
断言的都是那份 HTML 的内容与它在 unified_launcher 里的挂载，随表层一并移除。

**没有连坐删掉的**：PR-9 真正的价值不在那份 HTML，而在它背后的约束——
operator 表层必须绑定 ``OPERATOR_ROUTES_V1``，不得另起一套并行事实源。
这条约束与前端是谁无关，因此保留并**加强**：

  1.  九条 operator API 路径必须真实存在于 ``core.routes.operator`` 上
      （原测试只断言"HTML 里出现过这个字符串"——那是弱断言，HTML 删了它就
      失去意义，而且字符串出现 ≠ 路由存在）。
  2.  所有 operator API 端点返回 OPERATOR_ROUTES_V1 背书的 JSON（数据绑定）。
  3.  不得引入第二个后端聚合路由。
  4.  回归钉：被删的 operator-console 表层不得重新出现。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _operator_router_paths() -> set[str]:
    """取 operator 路由器上真实注册的路径集合。

    注意用 ``create_router()`` 的返回值直接取,而不是把它 include 进 FastAPI 再
    遍历 ``app.routes``:新版 FastAPI 的 ``include_router`` 不再摊平路由,而是插入
    ``_IncludedRouter`` 包装对象,其 ``.path`` 是 ``None`` —— 那样遍历会得到空集,
    断言全部"通过"却什么都没测到。
    """
    from core.routes.operator import create_router

    return {p for r in create_router().routes if (p := getattr(r, "path", None))}


def _launcher_text() -> str:
    return (PROJECT_ROOT / "unified_launcher.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def op_app():
    from core.android_device_state_store import reset_android_device_state_store
    from core.routes.operator import create_router

    reset_android_device_state_store()
    app = FastAPI()
    app.include_router(create_router())
    return app


@pytest.fixture(scope="module")
def op_client(op_app):
    return TestClient(op_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1.  Operator API 路径必须真实存在（取代原"HTML 里提到过这个字符串"）
# ---------------------------------------------------------------------------

REQUIRED_API_PATHS = [
    "/api/v1/readiness",
    "/api/v1/operator/snapshot",
    "/api/v1/operator/flows",
    "/api/v1/operator/llm",
    "/api/v1/operator/nats",
    "/api/v1/operator/heartbeat",
    "/api/v1/ports",
    "/api/v1/operator/devices/ecosystem",
    "/api/v1/operator/devices/execution-events",
]


class TestOperatorSurfaceExists:
    @pytest.mark.parametrize("api_path", REQUIRED_API_PATHS)
    def test_operator_router_registers_path(self, api_path):
        assert (
            api_path in _operator_router_paths()
        ), f"operator 路由器上没有 {api_path}——PR-9 要求的 operator 表层不完整"

    def test_helper_actually_sees_routes(self):
        """自证:确认 _operator_router_paths() 不是恒返回空集。

        上面那组参数化断言若因为取路由的方式不对而拿到空集,会**全部失败**而非
        全部通过,所以它本身不会假绿。但这条把"取得到路由"这件事单独钉死,
        以后有人改取法时能立刻看出是取法坏了,而不是九条路由同时消失了。
        """
        assert len(_operator_router_paths()) >= len(REQUIRED_API_PATHS)


# ---------------------------------------------------------------------------
# 4.  Data-binding — operator API endpoints return correct payload shapes
# ---------------------------------------------------------------------------


class TestReadinessBinding:
    def test_readiness_returns_200(self, op_client):
        r = op_client.get("/api/v1/readiness")
        assert r.status_code == 200

    def test_readiness_has_verdict(self, op_client):
        data = op_client.get("/api/v1/readiness").json()
        assert "verdict" in data

    def test_readiness_has_dimensions_list(self, op_client):
        data = op_client.get("/api/v1/readiness").json()
        assert "dimensions" in data
        assert isinstance(data["dimensions"], list)


class TestSnapshotBinding:
    def test_snapshot_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/snapshot")
        assert r.status_code == 200

    def test_snapshot_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/snapshot").json()
        # The snapshot endpoint carries OPERATOR_SURFACE_V1 (from the
        # OperatorSurface layer) or OPERATOR_ROUTES_V1 — either is valid.
        auth = data.get("authority", "")
        assert "OPERATOR" in auth, f"Expected an OPERATOR authority, got: {auth!r}"


class TestFlowsBinding:
    def test_flows_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/flows")
        assert r.status_code == 200

    def test_flows_has_flows_list(self, op_client):
        data = op_client.get("/api/v1/operator/flows").json()
        assert "flows" in data
        assert isinstance(data["flows"], list)

    def test_flows_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/flows").json()
        assert data.get("authority") == "OPERATOR_ROUTES_V1"


class TestNatsBinding:
    def test_nats_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/nats")
        assert r.status_code == 200

    def test_nats_has_connected_key(self, op_client):
        data = op_client.get("/api/v1/operator/nats").json()
        assert "connected" in data


class TestHeartbeatBinding:
    def test_heartbeat_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/heartbeat")
        assert r.status_code == 200

    def test_heartbeat_has_enabled_key(self, op_client):
        data = op_client.get("/api/v1/operator/heartbeat").json()
        assert "enabled" in data


class TestPortsBinding:
    def test_ports_returns_200(self, op_client):
        r = op_client.get("/api/v1/ports")
        assert r.status_code == 200

    def test_ports_returns_object(self, op_client):
        data = op_client.get("/api/v1/ports").json()
        assert isinstance(data, dict)


class TestEcosystemBinding:
    def test_ecosystem_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/devices/ecosystem")
        assert r.status_code == 200

    def test_ecosystem_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/devices/ecosystem").json()
        assert data.get("authority") == "OPERATOR_ROUTES_V1"


class TestExecutionEventsBinding:
    def test_execution_events_returns_200(self, op_client):
        r = op_client.get("/api/v1/operator/devices/execution-events")
        assert r.status_code == 200

    def test_execution_events_has_events_list(self, op_client):
        data = op_client.get("/api/v1/operator/devices/execution-events").json()
        assert "events" in data
        assert isinstance(data["events"], list)

    def test_execution_events_has_authority(self, op_client):
        data = op_client.get("/api/v1/operator/devices/execution-events").json()
        assert data.get("authority") == "OPERATOR_ROUTES_V1"

    def test_execution_events_has_diagnostics_source_fingerprint(self, op_client):
        data = op_client.get("/api/v1/operator/devices/execution-events").json()
        fp = data.get("authority_source_fingerprint")
        assert isinstance(fp, dict)
        assert fp.get("surface_path") == "/api/v1/operator/devices/execution-events"
        assert fp.get("primary_source_kind") == "diagnostics_visible_state"


# ---------------------------------------------------------------------------
# 5.  回归钉：被删的并行 Web 表层不得重新出现
# ---------------------------------------------------------------------------


class TestParallelWebSurfacesStayDeleted:
    """面板收敛：唯一表层是 Tauri/Electron 壳内的 React 面板。

    这里钉的是**目录不存在 + 启动器不挂载**,而不是"启动器源码里不出现某个
    字符串"——后者会被解释性注释误伤(本仓的注释里就写着这两个路径的来历,
    那是应该保留的历史说明)。所以断言落在可执行的事实上:目录没了、
    路由函数没了。
    """

    def test_operator_console_dir_is_gone(self):
        p = PROJECT_ROOT / "static" / "operator-console"
        assert not p.exists(), f"operator-console 表层已删除,不应重新出现: {p}"

    def test_api_manager_dir_is_gone(self):
        p = PROJECT_ROOT / "static" / "api-manager"
        assert not p.exists(), f"api-manager 表层已删除,不应重新出现: {p}"

    def test_launcher_no_longer_defines_console_routes(self):
        text = _launcher_text()
        assert "async def operator_console_index_route" not in text
        assert "async def api_manager_index" not in text

    def test_launcher_no_longer_mounts_static_assets(self):
        """/assets 静态挂载随 api-manager 一并移除。"""
        text = _launcher_text()
        assert "StaticFiles(directory=" not in text


# ---------------------------------------------------------------------------
# 6.  No new backend aggregation route introduced
# ---------------------------------------------------------------------------


class TestNoSecondAggregationLayer:
    def test_operator_console_route_not_in_operator_py(self):
        op_py = (PROJECT_ROOT / "core" / "routes" / "operator.py").read_text()
        # The operator-console HTML route should live in the launcher, not in
        # operator.py (which is the API truth surface, not a UI server).
        assert "/operator-console" not in op_py

    def test_no_aggregation_route_added_to_operator_py(self):
        op_py = (PROJECT_ROOT / "core" / "routes" / "operator.py").read_text()
        # Guard against accidental addition of an aggregation endpoint that
        # merges multiple truth sources outside the canonical operator surface.
        assert "aggregate_all" not in op_py
        assert "/api/v1/operator/console" not in op_py
