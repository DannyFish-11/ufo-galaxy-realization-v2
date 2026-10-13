"""「保存设置」不把进程这一次自己推出来的值钉进 ``.env``。

真跑(``python main.py --backend -v``,本机已有 NATS)在面板上保存一个 Key,``.env`` 里多出了:

    GALAXY_SKIP_ELECTRON=1                 ← --backend 落的;之后正常 ``python main.py`` 也不开桌面窗口
    GALAXY_VERBOSE=1                       ← -v 落的
    GALAXY_NATS_URL=nats://localhost:4222  ← 内置 NATS 起在哪;非空就算「要用总线」,本地模式也起 NATS

``_write_env_file_with`` 把登记表每个键的 ``os.environ`` 现值整份写回去,分不清哪些是人配的、哪些是进程运行中
自己写进环境变量供别处读的。现在后者经 ``core.derived_env.export`` 写,保存时换回人配的那个(没配过就不写)。
"""

from __future__ import annotations

import pytest

from core import derived_env
from core.routes import config as config_routes
from core.routes.config_schema_registry import CONFIG_SCHEMA


@pytest.fixture()
def save(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr(config_routes, "ENV_FILE", target)
    monkeypatch.setattr(derived_env, "_ORIGINAL", {})
    monkeypatch.setattr(derived_env, "_EXPORTED", {})
    for key in CONFIG_SCHEMA:
        monkeypatch.delenv(key, raising=False)

    def run(**overrides):
        config_routes._write_env_file_with(overrides or None)
        lines = target.read_text(encoding="utf-8").splitlines()
        return {ln.split("=", 1)[0]: ln.split("=", 1)[1] for ln in lines if "=" in ln and not ln.startswith("#")}

    return run


def test_the_flags_of_this_run_are_not_pinned(save):
    derived_env.export("GALAXY_SKIP_ELECTRON", "1")  # --backend
    derived_env.export("GALAXY_VERBOSE", "1")  # -v
    derived_env.export("GALAXY_NATS_URL", "nats://localhost:4222")  # 内置 NATS 起在哪
    written = save()
    for key in ("GALAXY_SKIP_ELECTRON", "GALAXY_VERBOSE", "GALAXY_NATS_URL"):
        assert key in CONFIG_SCHEMA, key  # 确实是会被整份写回去的登记键
        assert key not in written, f"{key} 是这一次运行自己写的,却被钉进了 .env"


def test_what_the_person_configured_survives_a_runtime_override(save, monkeypatch):
    """人配了 B 档,这一次因为显存不够临时降到 A —— 保存时写回的是人配的 B,不是降出来的 A。"""
    monkeypatch.setenv("GALAXY_MODEL_TIER", "B")
    derived_env.export("GALAXY_MODEL_TIER", "A")
    assert save()["GALAXY_MODEL_TIER"] == "B"


def test_a_person_configured_value_that_equals_the_export_is_still_theirs(save, monkeypatch):
    """.env 里本来就写着 GALAXY_VERBOSE=1,再带 -v 启动:它仍是人配的,保存不丢。"""
    monkeypatch.setenv("GALAXY_VERBOSE", "1")
    derived_env.export("GALAXY_VERBOSE", "1")
    assert save().get("GALAXY_VERBOSE") == "1"


def test_keep_existing_leaves_a_configured_bus_alone(save, monkeypatch):
    """人在 .env 里指了别的机器上的总线;本机端口上恰好也有 NATS 在应答 —— 不改人指的那个。"""
    monkeypatch.setenv("GALAXY_NATS_URL", "nats://bus.lan:4222")
    derived_env.export("GALAXY_NATS_URL", "nats://localhost:4222", keep_existing=True)
    assert save()["GALAXY_NATS_URL"] == "nats://bus.lan:4222"


def test_a_value_the_person_then_saves_in_the_panel_is_written(save):
    derived_env.export("GALAXY_VERBOSE", "1")
    assert save(GALAXY_VERBOSE="true")["GALAXY_VERBOSE"] == "true"


def test_the_runtime_writers_go_through_derived_env():
    """这几处写环境变量的地方是「这一次」的值;改回裸 ``os.environ[...] =`` 就又会被钉进 .env。"""
    import inspect

    import core.llama_server as llama
    import core.model_selection as selection
    import core.native_modal as native
    import core.nats_server as nats
    import main

    expect = {
        nats: ["GALAXY_NATS_URL"],
        llama: ["GALAXY_LOCAL_OPENAI_URL", "GALAXY_LOCAL_OPENAI_SERVES"],
        native: ["GALAXY_NATIVE_AUDIO"],
        selection: ["GALAXY_MODEL_TIER"],
        main: ["GALAXY_SKIP_ELECTRON", "GALAXY_VERBOSE"],
    }
    for mod, keys in expect.items():
        src = inspect.getsource(mod)
        for key in keys:
            assert f'os.environ["{key}"] =' not in src and f'setdefault("{key}"' not in src, (mod.__name__, key)


def test_the_secrets_store_is_only_readable_by_its_owner(tmp_path):
    """面板存进来的各家 API Key:原先 ``open(..., "w")`` 建出来是 0644(同机任何账户都能读),写到一半还会把旧的全清掉。"""
    import os
    import stat

    from core.config_store import ConfigStore

    store = ConfigStore(config_path=tmp_path / "config.json", secrets_path=tmp_path / "secrets.env")
    store.write_secret("OPENAI_API_KEY", "FAKE_sk-test-owner-only")
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "secrets.env").stat().st_mode) == 0o600
    assert store.read_secrets()["OPENAI_API_KEY"] == "FAKE_sk-test-owner-only"
