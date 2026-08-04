#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_wearos_contract_gate.py
======================================
WearOS ↔ V2 的**直接**契约门(此前只有 android↔V2 两道门间接覆盖)。

钉三件事:手表上行信封能被 V2 解析;手表经 command 包装的专用类型
(voice_query/phase_report)在 websocket_handler 里仍有真实路由;手表上行
用到的信封 type 都是 V2 MessageType 的合法值。
来源:galaxy-wearos AIPClient.kt 的真实构造(经 shared-protocol canonical 信封)。
"""

from __future__ import annotations

import ast
import inspect


def test_wear_uplink_envelope_parses_as_aip_v3() -> None:
    """shared canonical 信封(kotlinx 线格式,毫秒时间戳/protocol/version 等键)
    必须能被 V2 的 parse_message 校验通过 —— 这是手表↔V2 的功能性互通钉。"""
    from galaxy_gateway.protocol import parse_message

    wear_frame = {
        "type": "command",
        "payload": {"command": "voice_query", "text": "开灯", "source": "wear_os"},
        "correlation_id": "cmd_1",
        "protocol": "AIP/1.0",
        "version": "3.0",
        "timestamp": 1700000000000,  # 端侧是 epoch 毫秒
        "device_id": "watch_probe",
        "trace_id": "t1",
        "session_id": "",
    }
    msg = parse_message(wear_frame)
    assert msg.type.value == "command" and msg.device_id == "watch_probe"
    assert msg.payload.get("command") == "voice_query"


def test_wear_command_wrapped_types_still_routed() -> None:
    """手表专用能力经 command 包装上行;websocket_handler 必须保有对
    voice_query 与 phase_report 的真实比较分支(AST 层钉,注释不算)。"""
    import galaxy_gateway.websocket_handler as wsh

    tree = ast.parse(inspect.getsource(wsh))
    compared = {
        node.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Compare)
        for node in ast.walk(n)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    for required in ("voice_query", "phase_report"):
        assert required in compared, f"websocket_handler 不再路由手表的 {required} —— 手表该能力静默失效"


def test_wear_uplink_types_are_valid_v2_types() -> None:
    """手表上行信封 type 全集(AIPClient 真实构造)必须都是 V2 MessageType 合法值。"""
    from galaxy_gateway.protocol import MessageType

    wear_uplink_types = {"auth", "ping", "command", "heartbeat", "command_result"}
    v2_values = {m.value for m in MessageType}
    missing = wear_uplink_types - v2_values
    assert not missing, f"手表上行类型不再被 V2 协议接受:{missing}"
