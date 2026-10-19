"""面板保存的 Key(``secrets.env``)与本机配置(``config.json``)随数据目录走,老装法的一个都不丢。

原先这两份写死在源码树 ``runtime/`` 下。容器里只有 ``/app/data``(``GALAXY_DATA_DIR``)是卷,
``runtime/`` 不是 —— 面板上填的各家 API Key 重建一次镜像就没了;真机上换个数据目录也一样。

读它的有四处,得是**同一条规则**,否则就是「存进去了,重启后读的是另一份」:
``ConfigStore``(面板读写)、``config_preflight``(启动前检查)、``launcher/env_check``(启动自检)、
以及 ``main.py`` 启动第一步把密钥库注回 ``os.environ`` 的 ``load_env_files_into_environ`` —— 它跑在
import 任何 core 之前,只能把规则照抄一遍,所以这里逐个场景核对它与 ``default_secrets_path`` 指向同一份。
自建 tailnet 的 ``deploy/headscale/init.sh`` 往密钥库里写网关的 API key,也核对同一条规则。
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture()
def clone(tmp_path, monkeypatch):
    """一份"装好的"目录:当前目录就是它(后端由 Electron 以仓库根为 cwd 拉起),环境里没有数据目录。"""
    monkeypatch.delenv("GALAXY_DATA_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    before = dict(os.environ)
    from core import config_store

    monkeypatch.setattr(config_store, "_REPO_ROOT", tmp_path)  # 老位置 runtime/ 也在这份目录里

    config_store.reset_config_store()
    try:
        yield tmp_path
    finally:
        os.environ.clear()
        os.environ.update(before)
        config_store.reset_config_store()


def _plant(path: Path, which: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"GALAXY__PROBE_STORE={which}\nOPENAI_API_KEY=FAKE_sk-test-{which}\n", encoding="utf-8")


def _loaded_by_main(root: Path) -> str:
    import main

    os.environ.pop("GALAXY__PROBE_STORE", None)
    os.environ.pop("OPENAI_API_KEY", None)
    main.load_env_files_into_environ(str(root))
    return os.environ.get("GALAXY__PROBE_STORE", "")


def _marker_at(path: Path) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("GALAXY__PROBE_STORE="):
            return line.split("=", 1)[1]
    return ""


SCENARIOS = {
    "只有老位置(升级上来的机器)": ({"runtime/secrets.env": "legacy"}, "", "legacy"),
    "两处都有,数据目录的优先": ({"runtime/secrets.env": "legacy", "data/secrets.env": "new"}, "", "new"),
    "只有数据目录": ({"data/secrets.env": "new"}, "", "new"),
    "数据目录只写在 .env 里": (
        {"runtime/secrets.env": "legacy", "elsewhere/secrets.env": "custom", "data/secrets.env": "new"},
        "GALAXY_DATA_DIR=elsewhere\n",
        "custom",
    ),
    ".env 里数据目录写成注释,当没写": ({"data/secrets.env": "new"}, "GALAXY_DATA_DIR= # e.g. /srv/galaxy\n", "new"),
    ".env 里数据目录留空,当没写": ({"data/secrets.env": "new"}, "GALAXY_DATA_DIR=\n", "new"),
}


@pytest.mark.parametrize("name", list(SCENARIOS))
def test_main_reads_the_same_secrets_file_the_store_uses(clone, name):
    files, dotenv, expected = SCENARIOS[name]
    for rel, which in files.items():
        _plant(clone / rel, which)
    (clone / ".env").write_text(dotenv, encoding="utf-8")

    got = _loaded_by_main(clone)

    from core.config_store import default_secrets_path

    assert got == expected, f"{name}: main.py 读的是 {got!r}"
    assert _marker_at(default_secrets_path(root=clone)) == expected, f"{name}: ConfigStore 用的不是同一份"


def test_a_key_saved_on_a_fresh_install_lands_in_the_data_dir_and_comes_back(clone):
    """新装的机器:面板保存 → 落在数据目录(容器里是卷)→ 重启后 main.py 注回环境。"""
    (clone / ".env").write_text("GALAXY_DATA_DIR=volume\n", encoding="utf-8")
    os.environ["GALAXY_DATA_DIR"] = "volume"  # 与重启前那次进程一样:.env 已经加载过
    from core.config_store import ConfigStore, default_config_path

    store = ConfigStore()
    store.write_secret("OPENAI_API_KEY", "FAKE_sk-test-saved-in-panel")
    store.write_config({"cross_device_enabled": False})
    assert (clone / "volume" / "secrets.env").is_file()
    assert Path(default_config_path(root=clone)) == Path("volume") / "config.json"
    assert not (clone / "runtime").exists(), "新装的机器不该再往源码树 runtime/ 里写"

    os.environ.clear()  # 重启:一个干净的进程
    import main

    main.load_env_files_into_environ(str(clone))
    assert os.environ.get("OPENAI_API_KEY") == "FAKE_sk-test-saved-in-panel"


def test_an_upgraded_install_keeps_writing_where_its_keys_already_are(clone):
    """升级上来的机器:``runtime/secrets.env`` 里已有 Key。新存的 Key 跟它们放在一起,不劈成两份。"""
    _plant(clone / "runtime" / "secrets.env", "legacy")
    from core.config_store import ConfigStore

    ConfigStore().write_secret("ANTHROPIC_API_KEY", "FAKE_sk-test-new-one")
    text = (clone / "runtime" / "secrets.env").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=FAKE_sk-test-legacy" in text and "ANTHROPIC_API_KEY=FAKE_sk-test-new-one" in text
    assert not (clone / "data" / "secrets.env").exists()


def test_preflight_loads_the_same_file(clone):
    _plant(clone / "data" / "secrets.env", "new")
    _plant(clone / "runtime" / "secrets.env", "legacy")
    os.environ.pop("GALAXY__PROBE_STORE", None)
    from core.config_preflight import _load_runtime_secrets_into_env

    assert "GALAXY__PROBE_STORE" in _load_runtime_secrets_into_env()
    assert os.environ["GALAXY__PROBE_STORE"] == "new"


def test_env_check_counts_keys_that_live_only_in_the_secrets_store(clone):
    """启动自检「.env 比模板少了哪些键」:面板存进密钥库的不算缺。

    原先这里 ``from core.unified.config_store import …`` —— 没有这个模块,``except`` 吞掉,
    密钥库一个键都没数上。
    """
    _plant(clone / "data" / "secrets.env", "new")
    os.environ.pop("OPENAI_API_KEY", None)
    (clone / ".env.example").write_text("A=1\nOPENAI_API_KEY=\n", encoding="utf-8")
    (clone / ".env").write_text("A=x\n", encoding="utf-8")
    from launcher import env_check

    _total, missing, sample = env_check._probe_env_staleness(clone / ".env", clone / ".env.example")
    assert missing == 0, sample


def test_the_secrets_store_in_the_data_dir_is_never_committed():
    out = subprocess.run(["git", "check-ignore", "-q", "data/secrets.env"], cwd=REPO, capture_output=True, text=True)
    assert out.returncode == 0, "data/secrets.env 没被 .gitignore 挡住 —— 里面是各家 API Key"


# ── 自建 tailnet 的初始化脚本写进的也是同一份 ──────────────────────────────────

_HS_STUB = """#!/usr/bin/env bash
case "$1" in
  health) exit 0 ;;
  users) echo '[{"name": "galaxy"}]' ;;
  apikeys) echo "FAKE_hs_apikey_value" ;;
esac
"""


@pytest.mark.skipif(shutil.which("bash") is None, reason="需要 bash")
@pytest.mark.parametrize(
    "files,dotenv",
    [
        ({}, ""),
        ({"runtime/secrets.env": "legacy"}, ""),
        ({"runtime/secrets.env": "legacy", "data/secrets.env": "new"}, ""),
        ({"runtime/secrets.env": "legacy"}, 'GALAXY_DATA_DIR="elsewhere"\n'),
    ],
)
def test_headscale_init_writes_the_key_where_the_gateway_reads_it(clone, files, dotenv):
    script = clone / "deploy" / "headscale" / "init.sh"
    script.parent.mkdir(parents=True)
    shutil.copy(REPO / "deploy" / "headscale" / "init.sh", script)
    (script.parent / "config.yaml").write_text("server_url: https://hs.galaxy.test\n", encoding="utf-8")
    stub = clone / "hs_stub.sh"
    stub.write_text(_HS_STUB, encoding="utf-8")
    for rel, which in files.items():
        _plant(clone / rel, which)
    (clone / ".env").write_text(dotenv, encoding="utf-8")

    r = subprocess.run(
        ["bash", str(script)],
        env={"PATH": "/usr/bin:/bin", "HS_CMD": f"bash {stub}"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stdout + r.stderr

    import main

    main.load_env_files_into_environ(str(clone))  # 网关重启:把 .env(含数据目录)与密钥库注回环境
    from core.config_store import default_secrets_path

    target = default_secrets_path(root=clone)
    assert "GALAXY_HEADSCALE_API_KEY=FAKE_hs_apikey_value" in target.read_text(encoding="utf-8"), target
    assert os.environ.get("GALAXY_HEADSCALE_API_KEY") == "FAKE_hs_apikey_value"


# ── 任务投影库(canonical_tasks.jsonl)同样随数据目录走,启动只读文件末尾 ─────────────────────


def test_the_task_projection_store_follows_the_data_dir(clone, monkeypatch):
    """原先写死仓库 ``data/``:容器重建就没了,测试也绕不开(仓库那份被测试写到了 16 MB)。"""
    from core import canonical_task_store as cts

    monkeypatch.setattr(cts, "_REPO_DATA_DIR", str(clone / "repo_data"))
    monkeypatch.setenv("GALAXY_DATA_DIR", str(clone / "volume"))
    assert cts.CanonicalTaskStore()._file == str(clone / "volume" / "canonical_tasks.jsonl")

    (clone / "repo_data").mkdir()
    (clone / "repo_data" / "canonical_tasks.jsonl").write_text("", encoding="utf-8")
    assert cts.CanonicalTaskStore()._file == str(clone / "repo_data" / "canonical_tasks.jsonl"), "老装法已有的继续用"


def test_startup_reads_only_the_tail_of_a_big_projection_file(clone, monkeypatch):
    """热层只要最新的几百条;原先整份读(上限 32 MB),第一次建是在事件循环里,真跑 16 MB 卡 0.6 秒。"""
    import json

    from core import canonical_task_store as cts

    lines = [json.dumps({"task_id": f"t{i}", "updated_at": float(i), "status": "done"}) for i in range(4000)]
    (clone / "canonical_tasks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(cts, "_LOAD_TAIL_BYTES", 20000)

    store = cts.CanonicalTaskStore(data_dir=str(clone), hot_limit=50)
    assert [r.task_id for r in store._records][-1] == "t3999"
    assert len(store._records) == 50
    assert store._stats["load_errors"] == 0, "落在半行里的那一行应当丢掉,不该算坏行"
    assert sum(1 for _ in store._iter_file_records(tail_bytes=20000)) < 1000
