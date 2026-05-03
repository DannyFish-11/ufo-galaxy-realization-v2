from __future__ import annotations

import os


def _make_store(tmp_path):
    from core.mesh.body_mesh_persistence import BodyMeshPersistenceStore

    return BodyMeshPersistenceStore(store_path=os.path.join(str(tmp_path), "body_mesh.json"))


def test_registry_register_persists_snapshot(tmp_path):
    from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

    store = _make_store(tmp_path)
    registry = BodyMeshRegistry(persistence_store=store, auto_persist=True, auto_restore=False)
    registry.register(
        "persist_dev_1",
        roles=[DeviceRole.ACTION],
        session_id="sess_1",
        metadata={"source": "test"},
    )

    record = store.load()
    assert record is not None
    assert any(entry.get("device_id") == "persist_dev_1" for entry in record.entries)


def test_registry_restart_restores_entries_and_body_score(tmp_path):
    from core.mesh.body_mesh_registry import BodyMeshRegistry, DeviceRole

    store = _make_store(tmp_path)
    reg1 = BodyMeshRegistry(persistence_store=store, auto_persist=True, auto_restore=False)
    reg1.register(
        "persist_dev_2",
        roles=[DeviceRole.ACTION, DeviceRole.PRESENCE],
        session_id="sess_2",
        metadata={"display_name": "Persisted"},
    )
    reg1.score_entry("persist_dev_2", 0.75)

    reg2 = BodyMeshRegistry(persistence_store=store, auto_persist=True, auto_restore=True)
    restored = reg2.get("persist_dev_2")

    assert restored is not None
    assert restored.session_id == "sess_2"
    assert DeviceRole.ACTION in restored.roles
    assert DeviceRole.PRESENCE in restored.roles
    assert restored.body_score == reg1.get("persist_dev_2").body_score


def test_singleton_registry_restores_from_persisted_store(tmp_path, monkeypatch):
    from core.mesh.body_mesh_registry import get_body_mesh_registry, reset_body_mesh_registry
    from core.mesh.body_mesh_persistence import reset_body_mesh_persistence_store

    store = _make_store(tmp_path)
    seeded = {
        "entries": [
            {
                "device_id": "persist_dev_3",
                "roles": ["action"],
                "session_id": "sess_3",
                "body_score": 1.25,
                "registered_at": 1.0,
                "metadata": {"source": "seed"},
            }
        ]
    }
    store.save(seeded)

    reset_body_mesh_registry()
    reset_body_mesh_persistence_store()
    monkeypatch.setattr(
        "core.mesh.body_mesh_persistence.get_body_mesh_persistence_store",
        lambda store_path=None: store,
    )

    registry = get_body_mesh_registry()
    restored = registry.get("persist_dev_3")

    assert restored is not None
    assert restored.session_id == "sess_3"
    assert restored.body_score == 1.25

    reset_body_mesh_registry()
    reset_body_mesh_persistence_store()
