"""记忆节点的数据库位置在本机上要能用。

全面排查(``python main.py --check-only``):``Node_100_MemorySystem  OperationalError: unable to open
database file``。原因是 ``.env.example`` 写着 ``MEMORY_DB_PATH=/app/data/galaxy_memory.db`` —— 容器路径;
启动时自动从模板生成 ``.env``,于是本机(Windows 上 ``/app/data`` 不存在)建库失败,记忆节点整个用不了。
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_env_template_does_not_hand_out_a_container_path():
    lines = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()
    active = [ln for ln in lines if ln.strip().startswith("MEMORY_DB_PATH=")]
    assert not active, f".env.example 不该给 MEMORY_DB_PATH 写死值(容器路径会被带到本机):{active}"


def _usable():
    import importlib

    return importlib.import_module("nodes.Node_100_MemorySystem.main")._usable_db_path


def test_a_container_path_on_a_native_machine_falls_back(tmp_path, monkeypatch):
    usable = _usable()
    real_isdir = os.path.isdir
    monkeypatch.setattr(os.path, "isdir", lambda p: False if p == "/app/data" else real_isdir(p))
    fallback = str(tmp_path / "galaxy_memory.db")
    assert usable("/app/data/galaxy_memory.db", fallback) == fallback


def test_a_real_path_is_kept_and_its_directory_created(tmp_path):
    usable = _usable()
    wanted = tmp_path / "deep" / "dir" / "m.db"
    assert usable(str(wanted), str(tmp_path / "fallback.db")) == str(wanted)
    assert wanted.parent.is_dir()


def test_unset_means_the_default(tmp_path):
    assert _usable()("", str(tmp_path / "d.db")) == str(tmp_path / "d.db")
