#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_phase_wire_shape_is_single_sourced.py

中心发给设备的相位报文 —— **一处构造**。

现在它只有一个用途:一台设备发起的请求,智能体处理到哪了(在想 / 在做 / 做完),只回给那台设备
(``core.cross_device_sync.tell_origin_device``)。电脑自己的三态不推给任何设备。

手机读**顶层** ``event_category`` / ``event_action``,并靠 ``payload.sync_type`` 认出这是请求进度。
生产方原来有三个(登记补推、重连补推、变更广播),各写各的字典,形状还不一样;三处都已删掉,
这里钉住不再长出第二份。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.cross_device_sync import build_phase_state_event

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 唯一允许手写相位报文字典的地方(构造器本身)。
_BUILDER_FILE = "core/cross_device_sync.py"


# ---------------------------------------------------------------------------
# 一、两个消费方各自要读的字段,一份报文里都得有
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("phase", ["silent", "liminal", "manifest"])
def test_android_reads_the_top_level_fields(phase):
    """手机端读顶层 ``event_category`` / ``event_action``。"""
    msg = build_phase_state_event(new_phase=phase)
    assert msg["type"] == "state_event"
    assert msg["event_category"] == "phase"
    assert msg["event_action"] == phase


@pytest.mark.parametrize("phase", ["silent", "liminal", "manifest"])
def test_payload_carries_the_phase_too(phase):
    msg = build_phase_state_event(new_phase=phase)
    assert msg["payload"]["to_phase"] == phase


def test_the_two_readings_never_disagree():
    """顶层与 payload 说的必须是同一个相位。

    两处各填各的话,两台设备会同时显示两个不同的状态,而且都"有依据"。
    """
    msg = build_phase_state_event(new_phase="liminal", old_phase="silent")
    assert msg["event_action"] == msg["payload"]["to_phase"] == msg["phase"] == "liminal"
    assert msg["payload"]["from_phase"] == "silent"


def test_legacy_top_level_phase_is_kept():
    """旧版手机端读顶层 ``phase``。删掉它等于让没升级的设备静默失去三态。"""
    assert build_phase_state_event(new_phase="manifest")["phase"] == "manifest"


# ---------------------------------------------------------------------------
# 二、报文说明自己是请求进度
# ---------------------------------------------------------------------------


def test_it_says_it_is_request_progress():
    """手机只认带这个标记的相位报文 —— 电脑的三态(就算哪天又有人推)不会显示成「智能体在处理你这件事」。"""
    from core.cross_device_sync import REQUEST_PROGRESS

    assert (
        build_phase_state_event(new_phase="liminal")["payload"]["sync_type"] == REQUEST_PROGRESS == "request_progress"
    )


def test_optional_correlation_fields_are_omitted_when_absent():
    """没有会话就不要塞一个空 session_id —— 空串会被当成"有个叫''的会话"。"""
    bare = build_phase_state_event(new_phase="silent")
    assert "session_id" not in bare and "trace_id" not in bare

    withs = build_phase_state_event(new_phase="silent", session_id="s-1")
    assert withs["session_id"] == "s-1"
    # trace_id 缺省回落到 session_id:跨设备排障时两边至少还能对上一条线。
    assert withs["trace_id"] == "s-1"


def test_timestamp_is_milliseconds():
    """设备侧按毫秒解读。发秒会让"最近一次更新"看起来在 1970 年附近。"""
    msg = build_phase_state_event(new_phase="silent", now_ms=1_700_000_000_000)
    assert msg["timestamp"] == 1_700_000_000_000
    assert isinstance(build_phase_state_event(new_phase="silent")["timestamp"], int)


# ---------------------------------------------------------------------------
# 三、只有这一处
# ---------------------------------------------------------------------------


def _phase_dict_literals(path: Path) -> list:
    """找出源码里手写的、带 ``event_category: "phase"`` 的字典字面量。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "event_category"
                and isinstance(value, ast.Constant)
                and value.value == "phase"
            ):
                found.append(node.lineno)
    return found


def test_nothing_else_hand_writes_a_phase_message_or_calls_the_builder():
    """手写字典是当初三份形状不一的来由;别的模块调构造器,就是又长出了一个往设备推相位的地方。"""
    offenders = []
    for root in ("core", "galaxy_gateway"):
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            literals = _phase_dict_literals(path)
            if rel == _BUILDER_FILE:
                assert len(literals) == 1, f"{rel} 里除构造器外还有手写相位报文:{literals}"
                continue
            if literals:
                offenders.append(f"{rel} 手写相位报文(行 {literals})")
            if "build_phase_state_event" in path.read_text(encoding="utf-8"):
                offenders.append(f"{rel} 调了相位报文构造器")
    assert not offenders, offenders
