"""多机模式里清点时查出、此前留着没动的两处真问题。

1. 主脑状态文件缺省落系统临时目录，不认 ``GALAXY_DATA_DIR``（本仓所有持久化点的约定）；
2. ``GALAXY_NATS_EXECUTOR_FALLBACK`` 登记成 ``sync / async / reject`` 三选一，代码只把它当开关读 ——
   选 ``reject`` 实际是开着回退，选项的意思相反。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.master_brain_state import STATE_FILE_NAME, default_state_path
from core.routes.config_schema_registry import CONFIG_SCHEMA


def test_the_state_file_follows_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("GALAXY_MASTER_BRAIN_STATE_PATH", raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    assert default_state_path() == tmp_path / STATE_FILE_NAME
    assert Path(tempfile.gettempdir()) not in default_state_path().parents or tmp_path.is_relative_to(
        tempfile.gettempdir()
    )


def test_an_explicit_path_still_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GALAXY_MASTER_BRAIN_STATE_PATH", str(tmp_path / "mine.json"))
    assert default_state_path() == tmp_path / "mine.json"


def test_without_a_data_dir_it_is_the_repo_data_folder(monkeypatch):
    monkeypatch.delenv("GALAXY_MASTER_BRAIN_STATE_PATH", raising=False)
    monkeypatch.delenv("GALAXY_DATA_DIR", raising=False)
    assert default_state_path().parent.name == "data"
    assert default_state_path().name == STATE_FILE_NAME


def test_the_master_brain_really_persists_under_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv("GALAXY_MASTER_BRAIN_STATE_PATH", raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    from core.master_brain import MasterBrain

    brain = MasterBrain()
    assert brain._state_path == tmp_path / STATE_FILE_NAME
    assert MasterBrain(state_path=tmp_path / "x.json")._state_path == tmp_path / "x.json"


@pytest.mark.parametrize(
    "value,fallback",
    [("sync", True), ("true", True), ("SYNC", True), ("", True), ("reject", False), ("false", False), ("0", False)],
)
def test_the_executor_fallback_means_what_the_registry_says(monkeypatch, value, fallback):
    from core.command_router import NATSExecutor

    if value:
        monkeypatch.setenv("GALAXY_NATS_EXECUTOR_FALLBACK", value)
    else:
        monkeypatch.delenv("GALAXY_NATS_EXECUTOR_FALLBACK", raising=False)
    assert NATSExecutor()._fallback_enabled is fallback


def test_the_registry_offers_only_what_the_code_distinguishes():
    meta = CONFIG_SCHEMA["GALAXY_NATS_EXECUTOR_FALLBACK"]
    assert meta["options"] == ["sync", "reject"] and meta["default"] == "sync"
