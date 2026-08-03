#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_partition_observability_wiring.py
================================================
阶段 0（分区可见化）接入的回归钉。

融入点（都是既有汇聚处，不是平行系统）：
* `core/nats_bus._absorb_nats_state` —— 连接/断开/重连/意外断开四条路径的共同出口；
* `galaxy_gateway/websocket_handler` 设备注册成功 / 断开两处；
* 消费面 `/api/v1/health`（routes/health.py）。

判据是外部可观察结果：真的调用 nats 状态汇聚 / 真的走设备断开路径之后，
观测器快照里必须出现对应变化；health 路由的返回体里必须带分区快照。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from core.node_communication import get_link_observer, reset_link_observer


@pytest.fixture(autouse=True)
def _fresh_observer():
    reset_link_observer()
    yield
    reset_link_observer()


# ===========================================================================
# 一、观测器本体行为
# ===========================================================================


def test_observer_snapshot_reports_islands_and_center_plane() -> None:
    o = get_link_observer()
    o.record_device_link("dev_a", True)
    o.record_device_link("dev_b", True)
    o.record_device_link("dev_b", False, detail="probe")
    o.record_center_link("nats", False, detail="probe")

    snap = o.snapshot()
    assert snap["partitioned"] is True
    assert snap["islands"] == ["dev_b"], f"孤岛判定错误：{snap['islands']}"
    assert snap["connected_devices"] == ["dev_a"]
    assert snap["center_links"]["nats"]["up"] is False
    # 状态翻转要留痕（运维要能看到最近发生了什么）
    assert any(t["link"] == "device:dev_b" and t["up"] is False for t in snap["recent_transitions"])


def test_observer_recovery_clears_partition() -> None:
    o = get_link_observer()
    o.record_device_link("dev_a", False)
    o.record_center_link("nats", False)
    o.record_device_link("dev_a", True)
    o.record_center_link("nats", True)
    snap = o.snapshot()
    assert snap["partitioned"] is False and snap["islands"] == []


# ===========================================================================
# 二、缝 1：nats_bus 四路共同出口真的喂了观测器
# ===========================================================================


def test_nats_state_absorption_feeds_observer() -> None:
    """直接调用真实的 _absorb_nats_state（四条 NATS 路径的共同出口）。"""
    from core.nats_bus import _absorb_nats_state

    _absorb_nats_state(is_connected=False)
    snap = get_link_observer().snapshot()
    assert "nats" in snap["center_links"], "NATS 状态没有进入链路观测器 —— 缝 1 断了"
    assert snap["center_links"]["nats"]["up"] is False
    assert snap["partitioned"] is True

    _absorb_nats_state(is_connected=True, url="nats://probe:4222")
    snap = get_link_observer().snapshot()
    assert snap["center_links"]["nats"]["up"] is True


def test_nats_startup_failure_also_feeds_observer(monkeypatch) -> None:
    """真实调用 NATSBus.connect() 连一个必然失败的地址 —— 启动失败出口也必须喂观测器。

    真实路径复跑发现:三条启动失败出口(内嵌起不来/auto-local 全败/显式 URL 连不上)
    此前直接 return,「中心从一开始就不在」恰好是分区可见化漏掉的最重要场景。
    """
    from core.nats_bus import NATSBus

    # 测试环境默认 GALAXY_NATS_ENABLED=false 会走本地降级出口 —— 这里要钉的是
    # 真实连接失败出口,故显式启用。
    monkeypatch.setenv("GALAXY_NATS_ENABLED", "true")
    bus = NATSBus()
    bus._url = "nats://127.0.0.1:1"
    bus._auto_local = False
    res = asyncio.run(bus.connect("nats://127.0.0.1:1"))
    assert res.get("success") is False
    snap = get_link_observer().snapshot()
    assert snap["center_links"].get("nats", {}).get("up") is False, "启动失败没有进观测器 —— 中心缺席不可见"


# ===========================================================================
# 三、缝 2：设备 WS 断开真的把链路标 DOWN
# ===========================================================================


def test_ws_disconnect_marks_device_link_down() -> None:
    """驱动 websocket_handler 里真实的 disconnect() 路径。"""
    from galaxy_gateway.websocket_handler import GatewayWSManager

    cm = GatewayWSManager()
    cm.active_connections["conn1"] = MagicMock()
    cm.device_connections["dev_ws_probe"] = "conn1"

    # 先标 UP（注册缝的对称面），再走真实断开路径
    get_link_observer().record_device_link("dev_ws_probe", True)

    with patch("galaxy_gateway.websocket_handler.udm_write_unregister", return_value=True):
        asyncio.run(cm.disconnect("conn1"))

    snap = get_link_observer().snapshot()
    assert "dev_ws_probe" in snap["islands"], f"设备断开后没有成为孤岛 —— 缝 2 断了。快照：islands={snap['islands']}"


def test_ws_register_seam_is_present_in_source() -> None:
    """注册缝在真实处理器深处（需整套网关运行时才能驱动），以源码钉住 +
    观测器侧行为已由上面用例覆盖。"""
    import inspect

    import galaxy_gateway.websocket_handler as wsh

    src = inspect.getsource(wsh)
    assert (
        'record_device_link(device_id, True, detail="ws_register")' in src
    ), "注册成功不再标记链路 UP —— 设备恢复后将永远显示为孤岛"


# ===========================================================================
# 四、缝 3：health 路由真的暴露分区快照
# ===========================================================================


def test_health_route_exposes_partition_snapshot() -> None:
    from galaxy_gateway.routes.health import enhanced_health_check

    get_link_observer().record_device_link("dev_health_probe", False)

    wsm = MagicMock()
    wsm.get_device_count.return_value = 0
    result: Dict[str, Any] = asyncio.run(enhanced_health_check(wsm=wsm, openclawd=None, llm=None))

    assert "network_partition" in result, "health 返回体里没有分区快照 —— 缝 3 断了"
    snap = result["network_partition"]
    assert snap.get("partitioned") is True
    assert "dev_health_probe" in snap.get("islands", [])
