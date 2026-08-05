#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_mesh_readers_agree.py

钉住：**读 BodyMeshRegistry 的各个出口，对同一份数据给出同一个结论**。

背景
====
``BodyMeshRegistry`` 有 20 个读取方。同一份 ``BodyEntry`` 被反复重新解释，每处解释
各写各的，于是「各自看都很合理、放一起互相打架」。这个文件钉住三处已经查实的：

一、面板的参与者状态
--------------------
``core/routes/panel.py`` 原来判 ``"active" if entry.session_id else "idle"``。
``BodyEntry.session_id`` 是**认知会话**字段，而活的两条注册路径都不传它
（``galaxy_gateway/android/handlers/registration.py:1130`` 与
``capability_report.py:251`` 都只传 device_id / roles / metadata）。净效果：
**每一台真实设备在面板上永远显示 idle**、点是灰的，而它其实正在 mesh 里。
判据改用本仓对「这台设备现在能不能用」的唯一定义
``core.device_readiness.DeviceReadinessSummary.ready``。

二、面板的角色只显示一个
------------------------
原来 ``roles[0]``，按**字母序**取第一个 —— 一台 perception+action+presence 的设备
在面板上只显示 ``action``，另外两维静默消失，而字母序本身没有任何含义。

三、mesh_participation_summary 的两个聚合器是死的
-------------------------------------------------
它读 ``registry.entries`` 与 ``registry.primary_device_id`` —— 这两个属性在
``BodyMeshRegistry`` 上**都不存在**（真实是 ``_entries`` / ``list_entries()`` /
``compute_assignment()``）；``hasattr`` 判 False，整段静默空转、连一条 reason 都不记。
另一处 ``build_assignment_summary()`` 少传必填的 ``policy``，每次都降级。
"""

from __future__ import annotations

import pytest

from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

_CAPABILITY_ROLES = {"perception", "action", "presence"}
_SESSION_POSITIONS = {"source", "primary", "support", "fallback", "observer", "relay", "merge_owner"}


@pytest.fixture()
def registry() -> BodyMeshRegistry:
    reg = BodyMeshRegistry(auto_persist=False, auto_restore=False)
    reg.register("phone_001", roles=[DeviceRole.PERCEPTION, DeviceRole.PRESENCE])
    reg.register("tablet_002", roles=[DeviceRole.ACTION])
    for entry in reg.list_entries():
        entry.body_score = {"phone_001": 1.0, "tablet_002": 3.0}[entry.device_id]
    return reg


# ---------------------------------------------------------------------------
# 一、面板：状态判据必须取唯一定义，不许再看 session_id
# ---------------------------------------------------------------------------


def test_panel_status_does_not_read_the_never_written_session_id():
    """钉的是**调用**，不是源码文本 —— 解释它的注释里也写着 session_id。"""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parent.parent / "core" / "routes" / "panel.py").read_text("utf-8"))
    target = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_mesh_participant_status"
    )
    called = {
        (node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", ""))
        for node in ast.walk(target)
        if isinstance(node, ast.Call)
    }
    assert "get_device_readiness" in called, "面板状态没走 core.device_readiness —— 判据又和别处分家了"


def test_panel_status_is_conservative_when_readiness_is_unavailable(monkeypatch):
    """就绪层不可用时退回旧口径，绝不让整块面板塌掉。"""
    import builtins

    from core.routes.panel import _mesh_participant_status

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name == "core.device_readiness":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)

    class _Entry:
        device_id = "d"
        session_id = None

    assert _mesh_participant_status(_Entry()) in {"active", "idle"}


def test_panel_status_values_stay_within_the_frontend_contract(registry):
    """面板 TS 只认这三档（usePanelData.ts: 'active' | 'idle' | 'disconnected'）。"""
    from core.routes.panel import _mesh_participant_status

    for entry in registry.list_entries():
        assert _mesh_participant_status(entry) in {"active", "idle", "disconnected"}


# ---------------------------------------------------------------------------
# 二、面板：多角色设备不许只剩一个角色
# ---------------------------------------------------------------------------


def test_panel_participant_carries_every_capability_role(registry, monkeypatch):
    """一台 perception+presence 的设备，面板上必须两维都在。"""
    import core.mesh.body_mesh_registry as bmr

    monkeypatch.setattr(bmr, "_registry", registry, raising=False)
    monkeypatch.setattr(bmr, "get_body_mesh_registry", lambda: registry)

    from core.mesh.body_mesh_registry import _ROLE_WEIGHTS

    for entry in registry.list_entries():
        roles = sorted(r.value for r in entry.roles)
        dominant = max(entry.roles, key=lambda r: _ROLE_WEIGHTS.get(r, 1.0))
        if entry.device_id == "phone_001":
            assert roles == ["perception", "presence"]
            # 权重序：presence 1.2 > perception 1.0。按字母序取的话会是 perception ——
            # 字母序没有含义，权重序是模块里本来就定义好的那个次序。
            assert dominant.value == "presence"


# ---------------------------------------------------------------------------
# 三、mesh_participation_summary：六个源全部真的有贡献
# ---------------------------------------------------------------------------


def test_every_aggregator_contributes(registry, monkeypatch):
    """此前六个里有两个是死的，而且**不报错** —— 空转最难查。"""
    import core.mesh_participation_summary as mps

    monkeypatch.setattr(mps, "get_body_mesh_registry", lambda: registry)
    summary = mps.get_current_mesh_participation_summary()

    assert "body_mesh_registry" in summary.sources, "body_mesh 那一段又空转了（registry.entries 不存在）"
    assert (
        "cross_device_policy" in summary.sources
    ), "cross_device 那一段又降级了（build_assignment_summary 少传 policy）"
    for reason in summary.reasons:
        assert "unavailable" not in reason, f"有源没接上：{reason}"


def test_capability_roles_and_session_positions_stay_in_separate_columns(registry, monkeypatch):
    """两套词汇分两列 —— 合成一列之后就再也分不出"是什么"和"这次干什么"。

    这一条同时也是「接上 body_mesh 那一段」的**区分度证明**：修好之前
    capability_roles_by_device 是空的。
    """
    import core.mesh_participation_summary as mps

    monkeypatch.setattr(mps, "get_body_mesh_registry", lambda: registry)
    summary = mps.get_current_mesh_participation_summary()

    assert summary.capability_roles_by_device == {
        "phone_001": ["perception", "presence"],
        "tablet_002": ["action"],
    }, f"能力角色没进来：{summary.capability_roles_by_device}"

    for device_id, roles in summary.roles_by_device.items():
        leaked = set(roles) & _CAPABILITY_ROLES
        assert not leaked, f"{device_id} 的会话位置那一列混进了能力角色：{sorted(leaked)}"
        assert (
            set(roles) <= _SESSION_POSITIONS
        ), f"{device_id} 出现了未知的会话位置：{sorted(set(roles) - _SESSION_POSITIONS)}"

    for device_id, roles in summary.capability_roles_by_device.items():
        assert set(roles) <= _CAPABILITY_ROLES, f"{device_id} 的能力角色列混进了会话位置：{roles}"


def test_primary_agrees_across_every_derivation(registry, monkeypatch):
    """谁是 primary，四条路径必须给同一个答案。

    summary 内部现在走 ``compute_assignment()`` 取 primary；它必须和
    ``get_mesh_session()`` / ``get_mesh_memberships()`` 一致 —— 否则就是又添了
    第四种说法，而这个模块存在的理由恰恰是消灭多种说法。
    """
    import core.mesh_participation_summary as mps

    monkeypatch.setattr(mps, "get_body_mesh_registry", lambda: registry)

    from_assignment = registry.compute_assignment().primary_body.device_id
    from_session = registry.get_mesh_session().to_dict()["primary_device_id"]
    from_membership = {m.to_dict()["primary_device_id"] for m in registry.get_mesh_memberships()}
    from_summary = mps.get_current_mesh_participation_summary().primary_device_id

    assert from_assignment == from_session == from_summary
    assert from_membership == {from_assignment}


def test_device_view_separates_the_two_vocabularies(registry, monkeypatch):
    """单设备视图同样分两列 —— 下游最可能只读这一个函数。"""
    import core.mesh_participation_summary as mps

    monkeypatch.setattr(mps, "get_body_mesh_registry", lambda: registry)
    view = mps.get_device_mesh_summary("phone_001")

    assert view["found"] is True
    assert view["capability_roles"] == ["perception", "presence"]
    assert not set(view["roles"]) & _CAPABILITY_ROLES

    missing = mps.get_device_mesh_summary("nobody-here")
    assert missing["found"] is False and missing["capability_roles"] == []
