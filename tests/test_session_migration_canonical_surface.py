"""会话迁移的规范面 core.session_migration（路线图 D3）。

钉住的事实：
1. 一个入口，先找会话在哪个存储里：核心优先、再漫游；都没有 → 404；
2. 漫游会话（唤醒事件建的）以前任何端点都迁不了（网关列得出来、迁移却 404），现在经规范面交给
   ``SessionRoamingManager.migrate_session``；
3. 作用域判据对两个存储一视同仁：不许迁 → 409，而且漫游引擎一次都没被调用；
4. 失败语义与核心存储一致：推送失败 → 502、源设备不对 → 409；
5. 迁移成功会发 ``SESSION_MIGRATED``：核心存储由规范面发，漫游存储由 EventBridge 挂上的迁移回调发。
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import core.session_migration as sm_mod
from galaxy_gateway.session_roaming import SessionRoamingManager


class _EmptyCore:
    def get_session(self, _sid: str) -> None:
        return None


@pytest.fixture
def roaming(tmp_path, monkeypatch) -> SessionRoamingManager:
    sr = importlib.import_module("galaxy_gateway.session_roaming")  # 包里同名属性是单例，不是模块

    monkeypatch.setattr(sr, "PERSISTENCE_DIR", tmp_path)
    monkeypatch.setattr(sr, "PERSISTENCE_FILE", tmp_path / "sessions.json")
    mgr = SessionRoamingManager()
    mgr._sessions.clear()
    mgr._device_session_map.clear()
    return mgr


@pytest.fixture(autouse=True)
def _local_scope(monkeypatch):
    """作用域判据给「本机 → 漫游」，与生产里单机的默认判定一致；个别用例自己覆盖。"""
    import core.scope_authority as sa

    monkeypatch.setattr(sa, "require_migration", lambda sid, scope: SimpleNamespace(migration="roaming", to_dict=dict))
    monkeypatch.setattr(sa, "current_scope", lambda: "local")


async def _migrate(roaming: Any, **kw: Any) -> Dict[str, Any]:
    return await sm_mod.migrate_session(
        session_manager=kw.pop("core", _EmptyCore()),
        ws_connection_manager=kw.pop("cm", MagicMock()),
        roaming_manager=roaming,
        **kw,
    )


@pytest.mark.asyncio
async def test_wake_created_roaming_session_is_migratable_through_the_canonical_surface(roaming) -> None:
    s = roaming.create_session(device_id="watch-1", wake_word="hey")
    with patch.object(roaming, "_push_context_to_device", AsyncMock(return_value=True)):
        res = await _migrate(roaming, session_id=s.session_id, target_device="desktop-1", context_override={"k": 1})
    assert res["success"] is True and res["status_code"] == 200
    assert res["store"] == sm_mod.STORE_ROAMING and res["migration_semantics"] == "roaming"
    assert res["source_device"] == "watch-1" and res["active_device"] == "desktop-1"
    assert roaming.get_session(s.session_id).device_id == "desktop-1"
    assert roaming.get_session(s.session_id).context.meta["migration_context"] == {"k": 1}


@pytest.mark.asyncio
async def test_core_store_wins_when_both_have_the_id(roaming) -> None:
    s = roaming.create_session(device_id="watch-1")
    core_session = SimpleNamespace(
        devices=["phone-1"], active_device="phone-1", metadata={}, updated_at=0.0, session_id=s.session_id
    )
    core = MagicMock()
    core.get_session.return_value = core_session
    core.get_full_history.return_value = [{"role": "user", "content": "hi"}]
    cm = MagicMock()
    cm.send_to_device = AsyncMock(return_value=True)
    roaming_migrate = AsyncMock()
    with patch.object(roaming, "migrate_session", roaming_migrate):
        res = await _migrate(roaming, core=core, cm=cm, session_id=s.session_id, target_device="desktop-1")
    assert res["success"] is True and res["store"] == sm_mod.STORE_CORE
    assert res["migration_semantics"] == "roaming"
    assert core_session.devices == ["desktop-1"], "本机作用域 → 漫游语义：源设备移出"
    roaming_migrate.assert_not_called()


@pytest.mark.asyncio
async def test_unknown_everywhere_is_404(roaming) -> None:
    res = await _migrate(roaming, session_id="nope", target_device="desktop-1")
    assert res["success"] is False and res["status_code"] == 404


@pytest.mark.asyncio
async def test_scope_refusal_applies_to_the_roaming_store_too(roaming, monkeypatch) -> None:
    import core.scope_authority as sa

    def _refuse(_sid: str, _scope: Any) -> Any:
        raise RuntimeError("transition: 不迁")

    monkeypatch.setattr(sa, "require_migration", _refuse)
    s = roaming.create_session(device_id="watch-1")
    engine = AsyncMock(return_value=True)
    with patch.object(roaming, "migrate_session", engine):
        res = await _migrate(roaming, session_id=s.session_id, target_device="desktop-1")
    assert res["status_code"] == 409 and "不迁" in res["error"]
    engine.assert_not_called()


@pytest.mark.asyncio
async def test_roaming_push_failure_is_502_and_rolls_back(roaming) -> None:
    s = roaming.create_session(device_id="watch-1")
    with patch.object(roaming, "_push_context_to_device", AsyncMock(return_value=False)):
        res = await _migrate(roaming, session_id=s.session_id, target_device="desktop-1")
    assert res["status_code"] == 502 and res["store"] == sm_mod.STORE_ROAMING
    assert roaming.get_session(s.session_id).device_id == "watch-1", "推送失败不算迁移"


@pytest.mark.asyncio
async def test_roaming_wrong_source_device_is_409(roaming) -> None:
    s = roaming.create_session(device_id="watch-1")
    res = await _migrate(roaming, session_id=s.session_id, target_device="desktop-1", source_device="phone-9")
    assert res["status_code"] == 409


@pytest.mark.asyncio
async def test_core_migration_announces_session_migrated(roaming) -> None:
    from integration.event_bus import EventType, event_bus

    core_session = SimpleNamespace(devices=["phone-1"], active_device="phone-1", metadata={}, updated_at=0.0)
    core = MagicMock()
    core.get_session.return_value = core_session
    core.get_full_history.return_value = []
    cm = MagicMock()
    cm.send_to_device = AsyncMock(return_value=True)
    await _migrate(roaming, core=core, cm=cm, session_id="s-core", target_device="desktop-1")
    events = [
        e for e in event_bus.get_event_history(EventType.SESSION_MIGRATED) if e.data.get("session_id") == "s-core"
    ]
    assert events and events[-1].data == {"session_id": "s-core", "from_device": "phone-1", "to_device": "desktop-1"}


@pytest.mark.asyncio
async def test_event_bridge_hooks_the_real_roaming_callback(roaming) -> None:
    """EventBridge 以前写的是不存在的 ``_on_session_migrated``；现在经 ``set_migration_callback`` 挂上。"""
    from core import upper_ports
    from core.event_bridge import EventBridge
    from integration.event_bus import EventType, event_bus

    upper_ports.register("gateway.session_roaming.session_roaming", roaming)
    try:
        await EventBridge().wire()
    finally:
        upper_ports.unregister("gateway.session_roaming.session_roaming")
    assert roaming._on_migrated is not None, "迁移回调没挂上 —— SESSION_MIGRATED 又会一条都发不出来"

    s = roaming.create_session(device_id="watch-1")
    with patch.object(roaming, "_push_context_to_device", AsyncMock(return_value=True)):
        assert await roaming.migrate_session(s.session_id, "desktop-1") is True
    seen: List[Any] = [
        e for e in event_bus.get_event_history(EventType.SESSION_MIGRATED) if e.data.get("session_id") == s.session_id
    ]
    assert seen and seen[-1].data["to_device"] == "desktop-1"


def test_roaming_store_follows_galaxy_data_dir() -> None:
    """漫游会话落盘跟随 GALAXY_DATA_DIR（tests/conftest.py 把它指到临时目录）。"""
    import os
    from pathlib import Path

    sr = importlib.import_module("galaxy_gateway.session_roaming")

    assert Path(os.environ["GALAXY_DATA_DIR"]) in sr.PERSISTENCE_DIR.parents or sr.PERSISTENCE_DIR.parent == Path(
        os.environ["GALAXY_DATA_DIR"]
    )
