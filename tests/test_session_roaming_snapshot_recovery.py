"""会话迁移快照：迁移中途进程退出，重启时读回快照、回到原设备。

此前迁移开始时会把上下文快照写盘（_persist_snapshot），但「迁移中」这个状态从不写盘，快照也从不删、
没有任何地方读它 —— 进程在迁移中途退出后，快照只是躺在盘上的文件，重启后没人知道有一次迁移没做完。
"""

from __future__ import annotations

import importlib
import json

import pytest

from galaxy_gateway.session_roaming import SessionRoamingManager, SessionState

# 包属性 galaxy_gateway.session_roaming 是单例、不是模块，要改模块级常量得这样取
sr = importlib.import_module("galaxy_gateway.session_roaming")


@pytest.fixture
def roaming_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sr, "PERSISTENCE_DIR", tmp_path)
    monkeypatch.setattr(sr, "PERSISTENCE_FILE", tmp_path / "sessions.json")
    return tmp_path


def _snapshot_path(d, sid):
    return d / f"snapshot_{sid}.json"


def test_restart_after_interrupted_migration_restores_from_snapshot(roaming_dir):
    mgr = SessionRoamingManager()
    session = mgr.create_session("phone-1")
    sid = session.session_id
    at_migration_start = session.context.to_dict()

    # 迁移做到一半：快照已写、「迁移中」已写盘，推送还没完成进程就退出了
    session.state = SessionState.MIGRATING
    mgr._persist_snapshot(sid, at_migration_start)
    mgr._save_sessions_to_disk()
    assert json.loads((roaming_dir / "sessions.json").read_text())["sessions"][sid]["state"] == "migrating"

    restarted = SessionRoamingManager()
    recovered = restarted.get_session(sid)
    assert recovered.state == SessionState.ACTIVE
    assert recovered.device_id == "phone-1", "没做完的迁移要回到原设备"
    assert recovered.context.to_dict() == at_migration_start
    assert not _snapshot_path(roaming_dir, sid).exists(), "恢复后快照要删掉"
    on_disk = json.loads((roaming_dir / "sessions.json").read_text())["sessions"][sid]
    assert on_disk["state"] == "active"


@pytest.mark.asyncio
async def test_successful_migration_leaves_no_snapshot(roaming_dir, monkeypatch):
    mgr = SessionRoamingManager()
    sid = mgr.create_session("phone-1").session_id

    async def _push_ok(*_a, **_k):
        return True

    monkeypatch.setattr(mgr, "_push_context_to_device", _push_ok)
    assert await mgr.migrate_session(sid, "laptop-1") is True
    assert mgr.get_session(sid).device_id == "laptop-1"
    assert not _snapshot_path(roaming_dir, sid).exists()


@pytest.mark.asyncio
async def test_failed_push_rolls_back_on_disk_and_leaves_no_snapshot(roaming_dir, monkeypatch):
    mgr = SessionRoamingManager()
    sid = mgr.create_session("phone-1").session_id

    async def _push_fail(*_a, **_k):
        return False

    monkeypatch.setattr(mgr, "_push_context_to_device", _push_fail)
    assert await mgr.migrate_session(sid, "laptop-1") is False
    on_disk = json.loads((roaming_dir / "sessions.json").read_text())["sessions"][sid]
    assert on_disk["state"] == "active" and on_disk["device_id"] == "phone-1"
    assert not _snapshot_path(roaming_dir, sid).exists()
