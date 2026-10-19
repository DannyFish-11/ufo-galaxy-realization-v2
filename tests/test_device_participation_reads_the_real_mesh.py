"""设备参与度的 mesh 成员 / 所在会话,读的是进程里真有的那两份。

原先 ``core.device_participation`` 调的是三个不存在的入口(``BodyMeshRegistry.get_instance``、
``contracts.mesh_session_coordinator.get_active_session_for_device``、
``source_dispatch_orchestrator.get_active_mesh_session``)。每次都抛、每次记一条 WARNING —— 真跑一轮,
面板每 3 秒对 8 台设备各问一次,日志里 600 多条 ``Exception suppressed: cannot import name ...``;
而「这台设备在不在 mesh 里、在不在哪段会话里」从来答不出来。
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def fresh(monkeypatch):
    from core.mesh import body_mesh_registry, mesh_session_lifecycle

    body_mesh_registry.reset_body_mesh_registry()
    monkeypatch.setattr(
        mesh_session_lifecycle,
        "_coordinator_singleton",
        mesh_session_lifecycle.MeshSessionLifecycleCoordinator(store=MagicMock()),
    )
    yield
    body_mesh_registry.reset_body_mesh_registry()


def test_a_device_in_the_body_mesh_is_a_member(fresh):
    from core.device_participation import _get_mesh_membership
    from core.mesh.body_mesh_registry import DeviceRole, get_body_mesh_registry

    get_body_mesh_registry().register("phone-1", roles=[DeviceRole.ACTION])
    m = _get_mesh_membership("phone-1")
    assert m is not None and m.member_device_id == "phone-1"


def test_an_active_session_is_found_for_its_participants_only(fresh):
    from contracts.mesh_session import MeshSessionParticipant, build_mesh_session
    from core.device_participation import _get_mesh_session
    from core.mesh.mesh_session_lifecycle import get_lifecycle_coordinator

    session = build_mesh_session(
        session_id="msess_test",
        source_device_id="phone-1",
        primary_device_id="pc-1",
        participants=[MeshSessionParticipant(device_id=d) for d in ("phone-1", "pc-1", "tablet-1")],
    )
    coord = get_lifecycle_coordinator()
    coord.create_session(session)
    assert _get_mesh_session("tablet-1") is None, "还没开始的会话不算「在会话里」"

    coord.activate_session("msess_test")
    for dev in ("phone-1", "pc-1", "tablet-1"):
        found = _get_mesh_session(dev)
        assert found is not None and found.session_id == "msess_test", dev
    assert _get_mesh_session("watch-1") is None


def test_asking_about_a_device_logs_no_warnings(fresh, caplog):
    from core.device_participation import get_device_participation

    with caplog.at_level(logging.WARNING):
        get_device_participation("nobody-1")
    noisy = [
        r.getMessage()
        for r in caplog.records
        if "cannot import name" in r.getMessage() or "get_instance" in r.getMessage()
    ]
    assert not noisy, noisy
