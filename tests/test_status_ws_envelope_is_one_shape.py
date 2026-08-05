#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_status_ws_envelope_is_one_shape.py

钉住：两个 ``/ws/status`` 的信封是**同一个形状**。

背景
====
本仓有两个 ``/ws/status``，路径同名、端口不同：

* ``core/api_routes.py``（主 app）      —— 事件名在 ``type``
* ``core/device_status_api.py``（:8766）—— 事件名在 ``event``

而 :8766 自己内部还不一致：推送用 ``event``、``pong`` 用 ``type``。

这不是"两种风格"。按其中一个端口调通的客户端连上另一个之后，``msg.type`` 是
``undefined`` —— 不报错、不断连、只是什么都解析不出来，而路径名一模一样，排查时
根本不会怀疑连错了端口。三仓当前零客户端，所以现在不疼；它疼的时刻恰恰是有人
开始写第一个客户端的时候。

判据：规范键是 ``type``（AIP v3 的 ``AIPMessage.type``、兼容设备入口、面板在场
通道都用它，``event`` 只在 :8766 一个文件里出现）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.status_ws_envelope import (
    STATUS_FRAME_CANONICAL_KEY,
    STATUS_FRAME_LEGACY_KEY,
    build_status_frame,
)

_REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 一、两个端点的真实首帧
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def main_app_client():
    from core.api_routes import create_websocket_routes

    app = FastAPI()
    create_websocket_routes(app)
    return TestClient(app)


@pytest.fixture(scope="module")
def device_status_client():
    from core.device_status_api import app as device_app

    return TestClient(device_app)


def test_both_status_endpoints_put_the_event_name_in_the_same_key(main_app_client, device_status_client):
    """两个端点的首帧都必须把事件名放在 ``type`` 里，且值相同。

    这是**真实连接**上取的帧，不是读源码 —— 源码里长得对但运行时走了别的分支，
    正是这类问题最常见的形态。
    """
    with main_app_client.websocket_connect("/ws/status") as ws:
        main_frame = ws.receive_json()
    with device_status_client.websocket_connect("/ws/status") as ws:
        device_frame = ws.receive_json()

    for label, frame in (("主 app", main_frame), (":8766", device_frame)):
        assert STATUS_FRAME_CANONICAL_KEY in frame, (
            f"{label} 的 /ws/status 首帧没有 {STATUS_FRAME_CANONICAL_KEY!r} 键：{sorted(frame)}。"
            "按另一个端口写的客户端连过来会 msg.type === undefined —— 不报错，只是什么都解析不出来。"
        )
    assert main_frame[STATUS_FRAME_CANONICAL_KEY] == device_frame[STATUS_FRAME_CANONICAL_KEY] == "initial_status"


def test_both_status_endpoints_answer_ping_the_same_way(main_app_client, device_status_client):
    """``ping`` 的应答也要同形状 —— 心跳是客户端第一个会写的东西。"""
    with main_app_client.websocket_connect("/ws/status") as ws:
        ws.receive_json()  # initial
        ws.send_text("ping")
        main_pong = ws.receive_json()
    with device_status_client.websocket_connect("/ws/status") as ws:
        ws.receive_json()  # initial
        ws.send_json({"type": "ping"})
        device_pong = ws.receive_json()

    assert main_pong[STATUS_FRAME_CANONICAL_KEY] == device_pong[STATUS_FRAME_CANONICAL_KEY] == "pong"
    for frame in (main_pong, device_pong):
        assert "timestamp" in frame, "pong 缺 timestamp —— :8766 那侧此前就缺，两端对不齐"


# ---------------------------------------------------------------------------
# 二、迁移垫片：同值，且只在该开的那一侧开
# ---------------------------------------------------------------------------


def test_legacy_key_carries_the_very_same_value():
    """``event`` 开着时必须与 ``type`` **同值**。

    两者出自同一个入参，结构上不可能不一致 —— 这条钉的是"以后别有人把它改成
    两个独立参数"。
    """
    frame = build_status_frame("device_registered", legacy_event_key=True, data={"x": 1})
    assert frame[STATUS_FRAME_LEGACY_KEY] == frame[STATUS_FRAME_CANONICAL_KEY] == "device_registered"


def test_legacy_key_is_off_by_default():
    """默认不带 ``event``：主 app 的帧从来没有过它，凭空加一个会让"规范键是哪个"重新可争论。"""
    assert STATUS_FRAME_LEGACY_KEY not in build_status_frame("initial_status")


def test_main_app_status_frames_never_grow_the_legacy_key(main_app_client):
    with main_app_client.websocket_connect("/ws/status") as ws:
        frame = ws.receive_json()
    assert STATUS_FRAME_LEGACY_KEY not in frame


def test_device_status_frames_keep_the_legacy_key_for_now(device_status_client):
    """:8766 侧保留 ``event`` —— 仓外可能有按它写的脚本（三仓里没有，但这里看不见）。

    这条不是"就该有两个键"，是"退役要显式"：真要去掉时改这里，而不是某天发现
    某个脚本静默不工作了。
    """
    with device_status_client.websocket_connect("/ws/status") as ws:
        frame = ws.receive_json()
    assert frame.get(STATUS_FRAME_LEGACY_KEY) == frame.get(STATUS_FRAME_CANONICAL_KEY)


# ---------------------------------------------------------------------------
# 三、不再有手搓信封
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("rel", ["core/device_status_api.py"])
def test_no_hand_rolled_event_envelopes_remain(rel):
    """源码里不该再出现手写的 ``{"event": ...}`` 字面量。

    钉源码而不是只钉行为：漏改一处的症状是"某一类推送帧没有 type"，而那类帧可能
    很久才发一次，行为测试抽不到。
    """
    tree = ast.parse((_REPO / rel).read_text(encoding="utf-8"))
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            keys = [k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if STATUS_FRAME_LEGACY_KEY in keys and STATUS_FRAME_CANONICAL_KEY not in keys:
                offenders.append(node.lineno)
    assert not offenders, (
        f"{rel} 第 {offenders} 行还在手搓 {{'{STATUS_FRAME_LEGACY_KEY}': ...}} 信封，"
        "没走 build_status_frame —— 这些帧不会有 type 键。"
    )
