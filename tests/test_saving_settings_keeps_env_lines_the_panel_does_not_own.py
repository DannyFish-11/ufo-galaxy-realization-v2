"""面板「保存设置」不能把 ``.env`` 里登记表之外的手写行吞掉。

被修的问题：写 ``.env`` 的函数只遍历登记表。``.env.example`` 里一百个键（compose 必填口令、端口、镜像站、
``PICKLE_SECRET_KEY``……）不在登记表里，点一次保存它们就从 ``.env`` 里消失，下次启动悄悄回到代码默认值。
"""

from __future__ import annotations

import pytest

import core.routes.config as cfg
from core.routes.config_schema_registry import CONFIG_SCHEMA


@pytest.fixture()
def env_file(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    monkeypatch.setattr(cfg, "ENV_FILE", path)
    monkeypatch.setattr("core.config_store.get_config_store", lambda: _NoSecrets())
    return path


class _NoSecrets:
    def read_secrets(self):
        return {}


def test_lines_the_panel_does_not_own_survive_a_save(env_file):
    assert "TEMPORAL_DB_PASSWORD" not in CONFIG_SCHEMA and "HF_ENDPOINT" not in CONFIG_SCHEMA
    env_file.write_text(
        "# 手写的\nTEMPORAL_DB_PASSWORD=pw-from-the-owner\nHF_ENDPOINT=https://hf-mirror.example\nPORT=8123\n",
        encoding="utf-8",
    )
    cfg._write_env_file_with({"GALAXY_SPEAK_MAX_CHARS": "321"})
    text = env_file.read_text(encoding="utf-8")
    assert "TEMPORAL_DB_PASSWORD=pw-from-the-owner" in text
    assert "HF_ENDPOINT=https://hf-mirror.example" in text
    assert "PORT=8123" in text
    assert "GALAXY_SPEAK_MAX_CHARS=321" in text  # 登记表管的照旧写


def test_saving_twice_does_not_duplicate_them(env_file):
    env_file.write_text("HF_ENDPOINT=https://hf-mirror.example\n", encoding="utf-8")
    cfg._write_env_file_with(None)
    cfg._write_env_file_with(None)
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert [ln for ln in lines if ln.startswith("HF_ENDPOINT=")] == ["HF_ENDPOINT=https://hf-mirror.example"]


def test_the_last_duplicate_wins_like_dotenv_does(env_file):
    env_file.write_text("HF_ENDPOINT=first\nHF_ENDPOINT=second\n", encoding="utf-8")
    cfg._write_env_file_with(None)
    text = env_file.read_text(encoding="utf-8")
    assert "HF_ENDPOINT=second" in text and "HF_ENDPOINT=first" not in text


def test_registered_keys_are_not_copied_a_second_time(env_file):
    """登记表管的键由登记表写（值取环境现值）；旧文件里的那一行不再带回，否则同一个键出现两次。"""
    env_file.write_text("GALAXY_SPEAK_MAX_CHARS=111\n", encoding="utf-8")
    cfg._write_env_file_with({"GALAXY_SPEAK_MAX_CHARS": "222"})
    text = env_file.read_text(encoding="utf-8")
    assert text.count("GALAXY_SPEAK_MAX_CHARS=") == 1 and "GALAXY_SPEAK_MAX_CHARS=222" in text


def test_a_key_already_in_the_secret_store_is_not_written_back_in_plaintext(env_file, monkeypatch):
    class Store:
        def read_secrets(self):
            return {"PICKLE_SECRET_KEY": "x"}

    monkeypatch.setattr("core.config_store.get_config_store", lambda: Store())
    env_file.write_text("PICKLE_SECRET_KEY=plain\nHF_ENDPOINT=https://m\n", encoding="utf-8")
    cfg._write_env_file_with(None)
    text = env_file.read_text(encoding="utf-8")
    assert "PICKLE_SECRET_KEY" not in text and "HF_ENDPOINT=https://m" in text


def test_an_unreadable_old_file_does_not_make_the_save_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / "does-not-exist" / ".env")
    from core.routes.config_env_preserve import foreign_env_lines

    assert foreign_env_lines(tmp_path / "nope" / ".env", CONFIG_SCHEMA) == []


class TestDataDirDefaultsAreNotFrozen:
    """默认位置在 ``data/`` 下的键（账本、声音记忆库、SimpleMem……）没人改过就别钉进 ``.env``：
    钉成相对路径等于让它不再跟 ``GALAXY_DATA_DIR`` 走。"""

    def test_an_untouched_data_path_is_not_pinned(self, env_file, monkeypatch):
        monkeypatch.delenv("GALAXY_TASK_LEDGER_PATH", raising=False)
        cfg._write_env_file_with(None)
        text = env_file.read_text(encoding="utf-8")
        assert "GALAXY_TASK_LEDGER_PATH=" not in text
        assert "GALAXY_OMNIMEM_DIR=" not in text and "GALAXY_CLAP_DIR=" not in text

    def test_a_changed_path_is_written(self, env_file):
        cfg._write_env_file_with({"GALAXY_TASK_LEDGER_PATH": "/var/galaxy/ledger.jsonl"})
        assert "GALAXY_TASK_LEDGER_PATH=/var/galaxy/ledger.jsonl" in env_file.read_text(encoding="utf-8")

    def test_the_persistence_points_follow_the_data_dir(self, monkeypatch, tmp_path):
        from core.data_paths import data_path

        monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
        assert data_path("runtime", "x.json") == str(tmp_path / "runtime" / "x.json")
        monkeypatch.delenv("GALAXY_DATA_DIR")
        assert data_path("runtime", "x.json") == "data/runtime/x.json"
