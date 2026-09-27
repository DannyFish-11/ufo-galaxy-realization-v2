"""tests/test_device_registry_follows_data_dir.py — 设备注册表跟 GALAXY_DATA_DIR 走。

``core/routes/_shared.py`` 原先把注册表写死成仓库的 ``data/registered_devices.json``。其余持久化
状态都认 ``GALAXY_DATA_DIR``，``tests/conftest.py`` 也正是靠这个变量把测试状态引到临时目录；
唯独这一处照写仓库，跑一次测试，真实注册表里就多一批测试设备（复测时启动后列出过 106 台）。

这里钉住三件事：
* 设了 ``GALAXY_DATA_DIR`` 就读写那里，不碰仓库 data/；
* 没设就还是仓库 data/（行为不变）；
* 新位置还没有文件时，从旧位置读入一次，之后只写新位置，旧文件不删不改 ——
  设过这个变量的部署升级后不会「忘掉」已登记的设备。
"""

from __future__ import annotations

import json

import pytest

from core.routes import _shared


@pytest.fixture()
def legacy_file(tmp_path, monkeypatch):
    legacy = tmp_path / "repo_data" / "registered_devices.json"
    monkeypatch.setattr(_shared, "_LEGACY_DEVICE_REGISTRY_FILE", legacy)
    return legacy


def test_writes_go_to_the_data_dir_not_the_repo(tmp_path, monkeypatch, legacy_file):
    data_dir = tmp_path / "data_dir"
    monkeypatch.setenv("GALAXY_DATA_DIR", str(data_dir))

    _shared._save_registered_devices({"d1": {"device_id": "d1"}})

    assert json.loads((data_dir / "registered_devices.json").read_text(encoding="utf-8")) == {"d1": {"device_id": "d1"}}
    assert not legacy_file.exists(), "设了 GALAXY_DATA_DIR 还往仓库 data/ 写，测试会污染真实注册表"


def test_without_the_variable_it_stays_where_it_was(monkeypatch, legacy_file):
    monkeypatch.delenv("GALAXY_DATA_DIR", raising=False)
    assert _shared._device_registry_file() == legacy_file

    _shared._save_registered_devices({"d2": {"device_id": "d2"}})
    assert legacy_file.exists()


def test_an_upgraded_deployment_keeps_its_devices(tmp_path, monkeypatch, legacy_file):
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({"phone": {"device_id": "phone", "status": "online"}}), encoding="utf-8")
    data_dir = tmp_path / "data_dir"
    monkeypatch.setenv("GALAXY_DATA_DIR", str(data_dir))

    loaded = _shared._load_registered_devices()
    assert set(loaded) == {"phone"}, "新位置没有文件时，要从旧位置读入"
    assert loaded["phone"]["status"] == "offline", "读回来的设备一律离线，等它重新心跳"

    _shared._save_registered_devices(loaded)
    assert (data_dir / "registered_devices.json").exists(), "之后写新位置"
    assert json.loads(legacy_file.read_text(encoding="utf-8"))["phone"]["status"] == "online", "旧文件不改"


def test_once_the_new_file_exists_the_old_one_is_ignored(tmp_path, monkeypatch, legacy_file):
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(json.dumps({"stale": {"device_id": "stale"}}), encoding="utf-8")
    data_dir = tmp_path / "data_dir"
    data_dir.mkdir()
    (data_dir / "registered_devices.json").write_text(json.dumps({"fresh": {"device_id": "fresh"}}), encoding="utf-8")
    monkeypatch.setenv("GALAXY_DATA_DIR", str(data_dir))

    assert set(_shared._load_registered_devices()) == {"fresh"}
