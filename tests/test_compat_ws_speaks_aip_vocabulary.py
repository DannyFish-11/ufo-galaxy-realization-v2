#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_compat_ws_speaks_aip_vocabulary.py

钉住：core 兼容设备入口 ``/ws/device/{device_id}`` 听得懂 AIP 的类型别名。

背景
====
本仓的规范信封是 AIP v3（``galaxy_gateway/protocol/aip_v3.py``，
``dual_repo_system_map`` 标注为 *canonical cross-repo envelope*），v1↔v3 的别名
归一表在 ``galaxy_gateway/protocol/compat.py``。

但 core 侧那个兼容设备入口的分支名是**手抄的一套词汇**，从不问归一表。实测后果：

    device_heartbeat  -> {"type": "error", "message": "未知消息类型: device_heartbeat"}
    device_status     -> 同上

心跳被回 error 意味着 UDM 收不到心跳 —— 设备明明连着，却会被判离线。

这里钉三件事：分支清单不漂、别名真的解析得出、以及**两件不同的事没有被归一到一起**。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core.compat_ws_vocabulary import (
    COMPAT_WS_BRANCH_TYPES,
    build_compat_ws_alias_map,
    resolve_compat_ws_branch,
)

_API_ROUTES = Path(__file__).resolve().parent.parent / "core" / "api_routes.py"


def _branch_types_in_source() -> list:
    """从真实的 ``elif msg_type == "..."`` 链里抽出分支名。

    钉的是源码事实而不是常量自己 —— 常量与 elif 链分处两地，漂了的症状是
    「某些客户端的消息静默走不通」，指不回任何一处。
    """
    tree = ast.parse(_API_ROUTES.read_text(encoding="utf-8"))
    handler = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "device_websocket":
            handler = node
            break
    assert handler is not None, "core/api_routes.py 里找不到 device_websocket —— 兼容设备入口被改名或删了？"

    found = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "msg_type":
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                    found.append(comparator.value)
    return found


# ---------------------------------------------------------------------------
# 一、分支清单不漂
# ---------------------------------------------------------------------------


def test_branch_type_list_matches_the_actual_elif_chain():
    """``COMPAT_WS_BRANCH_TYPES`` 必须与真实 elif 链逐字一致。"""
    actual = _branch_types_in_source()
    assert sorted(actual) == sorted(COMPAT_WS_BRANCH_TYPES), (
        "兼容设备入口的分支清单与 COMPAT_WS_BRANCH_TYPES 对不上了。\n"
        f"  elif 链里有：{sorted(set(actual) - set(COMPAT_WS_BRANCH_TYPES))}\n"
        f"  常量里多出：{sorted(set(COMPAT_WS_BRANCH_TYPES) - set(actual))}\n"
        "清单漂掉时，新分支不会参与 AIP 别名解析——症状是那类消息只有旧客户端能发通。"
    )


# ---------------------------------------------------------------------------
# 二、AIP 别名真的解析得出
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "incoming,expected_branch",
    [
        # 正向：入帧是别名，AIP 归一后正好是本面分支名
        ("device_heartbeat", "heartbeat"),
        ("agent_heartbeat", "heartbeat"),
        # 反向：入帧已是 AIP 规范名，本面分支名才是那个别名
        ("device_status", "status_update"),
        # 两跳：v2 短名 → AIP 规范名 → 本面分支名
        ("status", "status_update"),
        ("update_status", "status_update"),
        # 本来就是分支名的，原样通过
        ("heartbeat", "heartbeat"),
        ("status_update", "status_update"),
        ("ai_intent", "ai_intent"),
    ],
)
def test_aip_aliases_resolve_to_a_real_branch(incoming, expected_branch):
    alias_map = build_compat_ws_alias_map()
    assert resolve_compat_ws_branch(incoming, alias_map) == expected_branch, (
        f"{incoming!r} 没有解析到分支 {expected_branch!r}。"
        "它会落进「未知消息类型」被回 error —— 如果这是心跳，UDM 就收不到，设备连着也判离线。"
    )


def test_resolution_actually_changes_something():
    """判据必须**有区分度**：至少有一个入帧被真的改道了。

    如果解析退化成恒等函数（比如归一表取不到、或别名表算空），上面那些用例里
    「本来就是分支名」的几条依然会通过，红不了。这一条专门盯那种情况。
    """
    alias_map = build_compat_ws_alias_map()
    rerouted = [
        t for t in ("device_heartbeat", "device_status", "status") if resolve_compat_ws_branch(t, alias_map) != t
    ]
    assert rerouted, "没有任何入帧被改道 —— AIP 别名解析实际上没生效（恒等降级？）"


# ---------------------------------------------------------------------------
# 三、两件不同的事没有被归一到一起
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("msg_type", ["command_result", "task_result", "goal_result", "goal_execution_result"])
def test_types_with_their_own_branch_are_never_rerouted(msg_type):
    """自带分支的类型绝不改道。

    AIP 把 ``command_result`` 归一成 ``task_result``（对网关而言二者确实同一件事），
    但本兼容面把它们当**两件事**：``command_result`` 要 resolve 一个挂起的命令 future
    （按 ``command_id``），``task_result`` 走统一结果归口（按 ``task_id``）。归一过去
    会让 future 永不落地，而症状是「命令发出去就没下文」，看不出与协议归一有关。
    """
    alias_map = build_compat_ws_alias_map()
    assert resolve_compat_ws_branch(msg_type, alias_map) == msg_type


def test_unknown_types_pass_through_untouched():
    """解析不出就原样返回，交给「未知消息类型」分支显式回 error。

    ``relay_forward`` / ``task_submit`` 在本面**确实没有实现**——那是功能缺口，
    不是命名不一致。解析器不该替它们编一个分支出来。
    """
    alias_map = build_compat_ws_alias_map()
    for msg_type in ("relay_forward", "task_submit", "definitely_not_a_type"):
        assert resolve_compat_ws_branch(msg_type, alias_map) == msg_type


# ---------------------------------------------------------------------------
# 四、归一表来源单一
# ---------------------------------------------------------------------------


def test_alias_map_is_derived_from_aip_not_hand_written():
    """别名表必须由 AIP 归一表推导。

    钉法：拿 AIP 自己的 ``canonical_message_type`` 重算一遍，结果必须一致。
    手写的表能通过「值恰好相等」的断言，但通不过「AIP 加了别名之后仍然相等」——
    而这正是它会出问题的时刻。
    """
    from galaxy_gateway.protocol.compat import canonical_message_type

    direct = set(COMPAT_WS_BRANCH_TYPES)
    expected = {
        canonical_message_type(b): b
        for b in COMPAT_WS_BRANCH_TYPES
        if canonical_message_type(b) != b and canonical_message_type(b) not in direct
    }
    assert build_compat_ws_alias_map() == expected


def test_canonical_message_type_leaves_unknown_names_alone():
    """归一函数回答「规范叫什么」，不回答「合不合法」——未知名原样返回。"""
    from galaxy_gateway.protocol.compat import canonical_message_type

    assert canonical_message_type("definitely_not_a_type") == "definitely_not_a_type"
    assert canonical_message_type("") == ""
    assert canonical_message_type("device_heartbeat") == "heartbeat"
