#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_phase_wire_shape_is_single_sourced.py

三态相位报文的形状 —— **一处构造,两个消费方都读得到**。

这条报文为什么值得单独钉
========================
它有两个消费方,而它们读的**不是同一个位置**:

- 手机端(``GalaxyWebSocketClient``)读**顶层**的 ``event_category`` / ``event_action``
- 手表端(``GalaxyWearApplication.handleStateEvent``)读 ``payload.to_phase``

而生产方原来有三个,各写各的字典。其中"设备刚注册完推当前相位"那一份
**不带 payload** —— 于是正常路径(AIPTransport 成功)下,刚配好对的手表收到报文、
解析出空、静默丢弃。桌面日志写着"已推送 phase=silent",手表上什么也没发生;
只有 AIPTransport 抛异常掉进兜底 ``send_json`` 时,手表才拿得到相位。

这类缺陷不会让任何东西报错,所以只能靠**对着两个消费方的读法**去钉形状。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.cross_device_sync import build_phase_state_event

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 三个发送点。它们必须都经由 build_phase_state_event,而不是各自手写字典。
_EMITTER_FILES = (
    "core/cross_device_sync.py",
    "galaxy_gateway/android_bridge.py",
    "galaxy_gateway/android/handlers/registration.py",
)


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
def test_wearos_reads_payload_to_phase(phase):
    """手表端读 ``payload.to_phase`` —— 这正是初次推送当初丢掉的那半边。"""
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
# 二、推送当前状态时"来源相位"是未知的,不能假装知道
# ---------------------------------------------------------------------------


def test_pushing_current_state_says_from_is_unknown():
    """初次/重连推送只知道"现在是什么",不知道"从哪来"。

    随手填 ``silent`` 会让设备侧把它当成一次真实跃迁,触发不该有的震动与动效。
    """
    msg = build_phase_state_event(new_phase="manifest", sync_type="cross_device_initial_sync")
    assert msg["payload"]["from_phase"] == "unknown"


def test_sync_type_distinguishes_why_it_was_pushed():
    """初次同步、重连同步、变更广播是三件事,排障时要分得开。"""
    kinds = {
        build_phase_state_event(new_phase="silent", sync_type=st)["payload"]["sync_type"]
        for st in ("cross_device_initial_sync", "cross_device_reconnect_sync", "cross_device_broadcast")
    }
    assert len(kinds) == 3


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
# 三、三个发送点都得用这一处,不许再手写
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


@pytest.mark.parametrize("rel", _EMITTER_FILES)
def test_no_emitter_hand_writes_the_phase_message(rel):
    """手写字典就是这次缺陷的产生方式:三份形状,其中一份少了半边。

    区分度:把 build_phase_state_event 里的 payload 删掉,这条不会红 ——
    上面那批断言才会。这条盯的是**别再长出第四份**。
    """
    path = REPO_ROOT / rel
    lines = _phase_dict_literals(path)
    if rel == "core/cross_device_sync.py":
        # 构造器自己那一份是唯一允许的手写处。
        assert len(lines) == 1, f"{rel} 里除构造器外还有手写相位报文:{lines}"
    else:
        assert not lines, f"{rel} 又手写了一份相位报文(行 {lines}) —— 请改用 build_phase_state_event"


@pytest.mark.parametrize("rel", ("galaxy_gateway/android_bridge.py", "galaxy_gateway/android/handlers/registration.py"))
def test_push_sites_import_the_builder(rel):
    """光是"没手写"不够 —— 还得证明它们真的取用了那一处。"""
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    assert "build_phase_state_event" in src, f"{rel} 没有用统一构造器"
