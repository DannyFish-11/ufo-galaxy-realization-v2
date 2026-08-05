#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mesh_session_identity_is_stable.py

钉住：**同一段 mesh 会话，每次读到的是同一个 session_id**。

背景
====
``BodyMeshRegistry.get_mesh_session()`` 是按当前注册表状态**即时构造**契约对象的，
而 ``build_mesh_session(session_id=None)`` 在没人给 ID 时会**当场生成一个新的**。
于是同一段会话每读一次就换一个 ID —— 什么都没变，ID 变了：

    get_mesh_session().session_id  →  msess_c91de147a9b1
    get_mesh_session().session_id  →  msess_7647d2ca7b86

后果不是"难看"。``/api/v1/projection/runtime/multi-device`` 在**同一个响应体**里
放了两块：``mesh_sessions[0]`` 走 ``get_mesh_session()``、``coordinator_summaries[0]``
走 ``get_mesh_session_coordinator()``。两次独立调用 → 两个不同的随机串，描述的却是
同一段会话。实测：

    mesh_sessions[0].session_id           msess_0a0057e5878f
    coordinator_summaries[0].session_id   msess_0385128ce9ff

拿 session_id 去 join 这两块的消费方，join 到的是空；轮询这个端点的客户端也分不出
"会话换了"和"我又读了一次"。

判据：会话 ID 在**会话本身**变化时才变。这里的"会话"由成员集合界定。
"""

from __future__ import annotations

import pytest

from contracts.mesh_session_coordinator import build_coordinator_summary
from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole


@pytest.fixture()
def registry() -> BodyMeshRegistry:
    """独立实例 —— 不碰进程单例，避免和别的用例互相污染。"""
    reg = BodyMeshRegistry(auto_persist=False, auto_restore=False)
    reg.register("phone_001", roles=[DeviceRole.PERCEPTION])
    reg.register("tablet_002", roles=[DeviceRole.ACTION])
    return reg


# ---------------------------------------------------------------------------
# 一、同一段会话：读多少次都是同一个 ID
# ---------------------------------------------------------------------------


def test_repeated_reads_return_the_same_session_id(registry):
    """这就是被修掉的那条。"""
    ids = [registry.get_mesh_session().session_id for _ in range(5)]
    assert len(set(ids)) == 1, f"什么都没变，ID 却换了 {len(set(ids))} 个：{ids}"


def test_session_and_coordinator_agree_within_one_payload(registry):
    """``/api/v1/projection/runtime/multi-device`` 的两块必须说的是同一段会话。

    这条按那个端点的**真实取数顺序**复刻：先 get_mesh_session，再
    get_mesh_session_coordinator + build_coordinator_summary。
    """
    session = registry.get_mesh_session(mesh_id="default_mesh")
    coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
    summary = build_coordinator_summary(coordinator=coordinator)

    sid_session = session.to_dict()["session_id"]
    sid_coordinator = summary.to_dict()["session_id"]
    assert sid_session == sid_coordinator, (
        f"同一个响应体里 mesh_sessions[0]={sid_session}、"
        f"coordinator_summaries[0]={sid_coordinator} —— 拿 session_id join 这两块会 join 到空。"
    )


# ---------------------------------------------------------------------------
# 二、判据要**有区分度**：会话真的变了就必须换 ID
# ---------------------------------------------------------------------------


def test_membership_change_mints_a_new_session_id(registry):
    """光"稳定"是不够的：返回一个常量也能让上面两条过。

    成员集合变了就是另一段会话 —— 这一条钉的是 ID 仍然**携带信息**。
    """
    before = registry.get_mesh_session().session_id
    registry.register("watch_003", roles=[DeviceRole.PRESENCE])
    after = registry.get_mesh_session().session_id
    assert before != after, "加了一台设备，会话 ID 没变 —— ID 不再表示是哪一段会话了"

    registry.unregister("watch_003")
    restored = registry.get_mesh_session().session_id
    assert restored not in (before, after), (
        "设备离开又回来，拿回了旧 ID —— 那是时间上的**另一段**会话，" "复用 ID 会让两段会话在日志里粘成一段。"
    )
    assert restored == registry.get_mesh_session().session_id, "重铸之后又不稳定了"


def test_explicit_session_id_is_still_honoured(registry):
    """调用方显式指定时，稳定化逻辑不许把它盖掉。"""
    session = registry.get_mesh_session(session_id="sess_explicit")
    assert session is not None
    assert session.to_dict()["session_id"] == "sess_explicit"


def test_distinct_meshes_do_not_share_one_identity(registry):
    """按 mesh_id 分别记 —— 两个 mesh 拿到同一个会话 ID 是另一种打架。"""
    a = registry.get_mesh_session(mesh_id="mesh_a").session_id
    b = registry.get_mesh_session(mesh_id="mesh_b").session_id
    assert a != b
    assert a == registry.get_mesh_session(mesh_id="mesh_a").session_id


def test_empty_mesh_is_also_stable():
    """没有成员的 mesh 也走同一条路径 —— 空态此前同样每读一次换一个 ID。"""
    empty = BodyMeshRegistry(auto_persist=False, auto_restore=False)
    ids = [empty.get_mesh_session().session_id for _ in range(3)]
    assert len(set(ids)) == 1, f"空 mesh 的 ID 仍在漂：{ids}"
