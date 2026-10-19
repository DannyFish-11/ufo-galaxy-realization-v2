"""面板上不再列出的设置：内置键（机器自己定）与跨设备专属键（本地模式下不列）。

背景见 ``core/routes/panel_builtin.py``：186 行里 95 行不该由人填、15 行只在跨设备模式下才有意义。
这里钉的是**撤下来之后系统还是对的**：

* 撤下的键仍登记、仍能存能读，只是不列、不往 ``.env`` 里钉默认值；
* 登记的默认值 = 代码里真正用的默认值（保存一次设置就改了行为的那种漂移，这里抓过两处真的）；
* 路径默认都跟着数据总目录走，旧位置上已有数据的继续认旧位置；
* 没有任何代码在读的键不许登记（面板上有一行、改了没有任何效果）。
"""

from __future__ import annotations

import asyncio
import functools
import os
import re
from pathlib import Path

import pytest

from core.routes import config as cfg
from core.routes.config_bundles import CONFIG_BUNDLES
from core.routes.config_labels import LABELS
from core.routes.config_schema_registry import CONFIG_SCHEMA
from core.routes.panel_builtin import (
    BUILTIN_GROUPS,
    CROSS_DEVICE_ONLY_KEYS,
    LEGACY_PINNED_DEFAULTS,
    PANEL_BUILTIN_KEYS,
    unlisted_at_default,
)
from core.tuning import knob_keys

ROOT = Path(__file__).resolve().parent.parent

#: 登记过、后来没有任何代码在读的键 —— 面板上曾有一行，改了没有任何效果。
DEAD_KEYS = (
    "UFO_NODE_HOST",
    "MAIN_REPO_URL",
    "GALAXY_MARKET_STORE_DIR",  # 技能市场（core/api_market.py）早已删除
    "GALAXY_MAX_CONTEXT_TOKENS",
    "GALAXY_DEVICE_TOKEN_STORE",  # 每设备令牌注册表随 G 步骤删除
    "GALAXY_DEVICE_TOKEN_RETENTION_DAYS",
    "GALAXY_DEVICE_TOKEN_MAX_RECORDS",
)


def _all_listed(monkeypatch, *, cross_device: bool):
    for key in ("GALAXY_CROSS_DEVICE_ENABLED", "GALAXY_SYSTEM_MODE"):
        monkeypatch.delenv(key, raising=False)
    if cross_device:
        monkeypatch.setenv("GALAXY_CROSS_DEVICE_ENABLED", "true")
    return asyncio.run(cfg.get_config())


# ── 清单本身 ─────────────────────────────────────────────────────────────────


def test_every_builtin_and_cross_device_key_is_registered_and_named():
    for key in PANEL_BUILTIN_KEYS | CROSS_DEVICE_ONLY_KEYS:
        assert key in CONFIG_SCHEMA, f"{key} 不在 CONFIG_SCHEMA —— 撤下一个不存在的键没有意义"
        assert key in LABELS, f"{key} 没有中文名 —— 智能体、日志、文档提到它时只能报英文键名"


def test_the_groups_do_not_overlap_each_other_or_the_other_ways_of_leaving_the_panel():
    seen = {}
    for name, (reason, keys) in BUILTIN_GROUPS.items():
        assert len(reason) >= 10, name
        for key in keys:
            assert key not in seen, f"{key} 同时在 {seen[key]} 和 {name} 里"
            seen[key] = name
    assert not PANEL_BUILTIN_KEYS & CROSS_DEVICE_ONLY_KEYS
    assert not PANEL_BUILTIN_KEYS & cfg.PANEL_HIDDEN_KEYS, "元层 / 多机内部调参另有一份清单，不要两处都写"
    assert not PANEL_BUILTIN_KEYS & knob_keys(), "调参键由智能体按人的话调，不在内置清单里"
    assert not CROSS_DEVICE_ONLY_KEYS & knob_keys()
    primaries = {b["primary"] for b in CONFIG_BUNDLES}
    assert not (PANEL_BUILTIN_KEYS | CROSS_DEVICE_ONLY_KEYS) & primaries, "整档按钮的主键必须留着（标 bundle）"


def test_the_counts_the_docs_state_are_the_counts_the_lists_have():
    """AGENTS.md 与 docs/SYSTEM_STATUS.md 写的数目；清单变了数目要跟着改。"""
    assert len(PANEL_BUILTIN_KEYS) == 90
    assert len(CROSS_DEVICE_ONLY_KEYS) == 6  # 自建内网 / TURN / STUN 移出:手表手机连智能体要用,不分模式


# ── 面板上到底列不列 ─────────────────────────────────────────────────────────


def test_local_mode_lists_none_of_them(monkeypatch):
    listed = _all_listed(monkeypatch, cross_device=False)
    leaked = sorted((PANEL_BUILTIN_KEYS | CROSS_DEVICE_ONLY_KEYS) & set(listed))
    assert not leaked, leaked


def test_cross_device_mode_lists_the_cross_device_rows_but_still_no_builtin(monkeypatch):
    listed = _all_listed(monkeypatch, cross_device=True)
    assert CROSS_DEVICE_ONLY_KEYS <= set(listed), sorted(CROSS_DEVICE_ONLY_KEYS - set(listed))
    assert not PANEL_BUILTIN_KEYS & set(listed)


def test_the_mode_is_decided_by_the_one_rule_not_re_derived(monkeypatch):
    """GALAXY_SYSTEM_MODE=desktop-cross-device 与 GALAXY_CROSS_DEVICE_ENABLED 任一即是；NATS 地址不参与。"""
    for key in ("GALAXY_CROSS_DEVICE_ENABLED", "GALAXY_SYSTEM_MODE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GALAXY_NATS_URL", "nats://somewhere:4222")
    assert "GALAXY_NATS_URL" not in asyncio.run(cfg.get_config()), "只配了总线地址不等于开了跨设备"
    monkeypatch.setenv("GALAXY_SYSTEM_MODE", "desktop-cross-device")
    assert "GALAXY_NATS_URL" in asyncio.run(cfg.get_config())


# ── 保存设置不再把默认值钉进 .env ─────────────────────────────────────────────


@pytest.fixture()
def envfile(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg, "ENV_FILE", tmp_path / ".env.test")
    import core.config_store as store

    monkeypatch.setattr(
        store,
        "_singleton",
        store.ConfigStore(config_path=tmp_path / "config.json.test", secrets_path=tmp_path / "secrets.env.test"),
    )
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    for key in PANEL_BUILTIN_KEYS | CROSS_DEVICE_ONLY_KEYS:
        monkeypatch.delenv(key, raising=False)
    return tmp_path / ".env.test"


def _lines(path: Path):
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def test_hidden_keys_are_still_saveable_through_the_api_and_land_in_env(envfile, monkeypatch):
    """藏起来不等于没接上：POST /api/config 照收、.env 照写、环境变量照读。"""
    monkeypatch.setenv("NODE_92_URL", "http://localhost:8092")  # 让 monkeypatch 在测试后还原
    out = asyncio.run(cfg.update_config(cfg.ConfigUpdateRequest(config={"NODE_92_URL": "http://10.1.1.1:8092"})))
    body = getattr(out, "body", None)
    assert body is None or b"unknown" not in body.lower(), body
    assert os.environ["NODE_92_URL"] == "http://10.1.1.1:8092"
    assert "NODE_92_URL=http://10.1.1.1:8092" in _lines(envfile)


def test_saving_does_not_pin_the_defaults_of_unlisted_keys(envfile):
    cfg._write_env_file_with({"GALAXY_AUTONOMY": "safe"})
    text = envfile.read_text(encoding="utf-8")
    pinned = [k for k in PANEL_BUILTIN_KEYS | CROSS_DEVICE_ONLY_KEYS if re.search(rf"^{k}=", text, re.M)]
    assert not pinned, f"这些没人动过的内置键被钉进了 .env: {sorted(pinned)}"


def test_a_value_somebody_really_set_is_kept_even_for_an_unlisted_key(envfile, monkeypatch):
    monkeypatch.setenv("NODE_92_URL", "http://10.0.0.5:8092")
    monkeypatch.setenv("GALAXY_API_HOST", "0.0.0.0")
    cfg._write_env_file_with({"GALAXY_NATS_URL": "nats://bus:4222"})
    lines = _lines(envfile)
    assert "NODE_92_URL=http://10.0.0.5:8092" in lines
    assert "GALAXY_API_HOST=0.0.0.0" in lines
    assert "GALAXY_NATS_URL=nats://bus:4222" in lines, "明确写进来的哪怕面板上没列也要落盘"


def test_cors_wildcard_is_no_longer_the_registered_default_and_old_pins_are_cleared(envfile, monkeypatch):
    """登记表曾把 CORS_ALLOWED_ORIGINS / HEADERS 登记成 ``*``：网关带 allow_credentials=True 挂它，
    点一次「保存设置」就写成『任何网页都能带着凭据调本机接口』。代码里的默认是本机端口与显式请求头。"""
    assert CONFIG_SCHEMA["CORS_ALLOWED_ORIGINS"]["default"] == ""
    assert CONFIG_SCHEMA["CORS_ALLOWED_HEADERS"]["default"] == ""
    assert "CORS_ALLOWED_ORIGINS" in LEGACY_PINNED_DEFAULTS
    # 旧版本点保存时钉进 .env 的 ``*``，在下一次保存时清掉
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("CORS_ALLOWED_HEADERS", "*")
    cfg._write_env_file_with({"GALAXY_AUTONOMY": "safe"})
    text = envfile.read_text(encoding="utf-8")
    assert "CORS_ALLOWED_ORIGINS" not in text and "CORS_ALLOWED_HEADERS" not in text
    # 但有人这次明确写 * 就照写（API 调用方的决定）
    cfg._write_env_file_with({"CORS_ALLOWED_ORIGINS": "*"})
    assert "CORS_ALLOWED_ORIGINS=*" in _lines(envfile)
    # 一个明确的、不是旧默认的来源列表，保存时原样留着
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example")
    cfg._write_env_file_with(None)
    assert "CORS_ALLOWED_ORIGINS=https://app.example" in _lines(envfile)


def test_the_cors_defaults_the_code_uses_are_not_wildcards(monkeypatch):
    from nodes.common.cors_config import get_cors_headers, get_cors_methods, get_cors_origins

    for key in ("CORS_ALLOWED_ORIGINS", "CORS_ALLOWED_METHODS", "CORS_ALLOWED_HEADERS"):
        monkeypatch.delenv(key, raising=False)
    assert "*" not in get_cors_origins()
    assert "*" not in get_cors_headers()
    assert "*" not in get_cors_methods()
    assert ",".join(get_cors_methods()) == CONFIG_SCHEMA["CORS_ALLOWED_METHODS"]["default"]


def test_unlisted_at_default_semantics():
    assert unlisted_at_default("NODE_92_URL", "http://localhost:8092", "http://localhost:8092", explicit=False)
    assert not unlisted_at_default("NODE_92_URL", "http://localhost:8092", "http://localhost:8092", explicit=True)
    assert not unlisted_at_default("NODE_92_URL", "http://other:1", "http://localhost:8092", explicit=False)
    assert not unlisted_at_default("GALAXY_AUTONOMY", "safe", "safe", explicit=False), "面板上列着的键不适用"


# ── 登记的默认值 = 代码里的默认值 ──────────────────────────────────────────────

_SOURCE_DIRS = ("core", "launcher", "galaxy_gateway", "nodes", "enhancements")
_SKIP = ("config_schema_registry.py", "config_labels.py", "panel_builtin.py", "core/tuning.py")


@functools.lru_cache(maxsize=1)
def _sources():
    files = [ROOT / "main.py"] + [p for d in _SOURCE_DIRS for p in (ROOT / d).rglob("*.py")]
    out = []
    for p in files:
        rel = p.relative_to(ROOT).as_posix()
        if p.is_file() and not rel.endswith(_SKIP):
            out.append((rel, p.read_text(encoding="utf-8", errors="ignore")))
    return tuple(out)


def _literal_defaults(key: str):
    """代码里 ``getenv("KEY", "字面量")`` / ``environ.get("KEY", "字面量")`` 的字面量默认值（空串不算：那是『按链条往下找』）。"""
    pat = re.compile(r"""["']""" + re.escape(key) + r"""["']\s*,\s*["']([^"'\n]+)["']\s*\)""")
    return {m.group(1) for _rel, text in _sources() if key in text for m in pat.finditer(text)}


#: 登记表和代码写法不同、含义相同的：``GALAXY_HF_MIRROR`` 登记 true，代码里写 "1"。
_SAME_MEANING = {"GALAXY_HF_MIRROR": {"1": "true"}}


def test_registered_defaults_equal_the_literal_defaults_the_code_uses():
    bad = {}
    for key in sorted(PANEL_BUILTIN_KEYS | CROSS_DEVICE_ONLY_KEYS):
        registered = str(CONFIG_SCHEMA[key]["default"])
        if registered == "":
            continue
        for lit in _literal_defaults(key):
            lit = _SAME_MEANING.get(key, {}).get(lit, lit)
            if lit != registered:
                bad.setdefault(key, []).append((registered, lit))
    assert not bad, f"登记的默认值与代码里的默认值不一致（保存一次设置就悄悄改了行为）: {bad}"


def test_the_defaults_the_code_keeps_in_constants_match_the_registry():
    from core.interaction.high_risk_confirmation import DEFAULT_TIMEOUT_S
    from core.voice_duplex_session import _NATIVE_REALTIME_PATH_DEFAULT

    assert float(CONFIG_SCHEMA["GALAXY_HIGH_RISK_CONFIRM_TIMEOUT_S"]["default"]) == DEFAULT_TIMEOUT_S
    assert CONFIG_SCHEMA["GALAXY_NATIVE_REALTIME_PATH"]["default"] == _NATIVE_REALTIME_PATH_DEFAULT


# ── 路径：跟着数据总目录走，旧位置上已有的继续认旧位置 ──────────────────────────


def test_path_keys_default_to_the_data_dir_not_to_a_hard_coded_relative_path():
    """登记为空 = 『随数据总目录』。曾有 data/xxx、./data/xxx、./chroma 三种写法，其中 ./chroma 还是错的目录。"""
    follows = [
        "GALAXY_TASK_LEDGER_PATH",
        "GALAXY_OMNIMEM_DIR",
        "GALAXY_CLAP_DIR",
        "CHROMA_PERSIST_DIR",
        "GITHUB_INSTALL_DIR",
    ]
    for key in follows:
        assert CONFIG_SCHEMA[key]["default"] == "", key


def test_data_path_or_legacy_prefers_the_new_place_and_never_strands_old_data(tmp_path, monkeypatch):
    from core.data_paths import data_path_or_legacy, runtime_file, state_file

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "d"))
    legacy = tmp_path / "old" / "x.json"
    new = tmp_path / "d" / "x.json"
    assert data_path_or_legacy("x.json", str(legacy)) == str(new), "两处都没有：落数据目录"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}")
    assert data_path_or_legacy("x.json", str(legacy)) == str(legacy), "旧位置有、新位置没有：沿用旧的"
    new.parent.mkdir(parents=True)
    new.write_text("{}")
    assert data_path_or_legacy("x.json", str(legacy)) == str(new), "新位置也有了：以新的为准"

    monkeypatch.setenv("MY_STATE", str(tmp_path / "explicit.json"))
    assert state_file("x.json", str(legacy.parent), "MY_STATE") == str(tmp_path / "explicit.json")
    monkeypatch.chdir(tmp_path)
    assert runtime_file("nope.json") == str(tmp_path / "d" / "nope.json")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "old.json").write_text("{}")
    assert runtime_file("old.json") == os.path.join(str(tmp_path), "runtime", "old.json")


def test_chroma_default_follows_the_data_dir_and_keeps_an_existing_legacy_store(tmp_path, monkeypatch):
    from core import vector_backend

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CHROMA_PERSIST_DIR", raising=False)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "d"))
    seen = {}

    class _Fake:
        def __init__(self, path, *a, **k):
            seen["path"] = path

        def _try_init(self):
            return True

    monkeypatch.setattr(vector_backend, "_ChromaBackend", _Fake)
    vector_backend.create_vector_backend(backend="chroma")
    assert seen["path"] == str(tmp_path / "d" / "chroma_db"), "新装：落数据目录"
    (tmp_path / "chroma_db").mkdir()
    vector_backend.create_vector_backend(backend="chroma")
    assert seen["path"] == "./chroma_db", "已有旧目录 ./chroma_db：继续用它，别换成一套空记忆"
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "mine"))
    vector_backend.create_vector_backend(backend="chroma")
    assert seen["path"] == str(tmp_path / "mine"), "显式指定永远优先"


def test_runtime_state_files_follow_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.delenv("GALAXY_TASK_ALLOCATION_STATE_PATH", raising=False)
    monkeypatch.delenv("ANDROID_DEVICE_STATE_STORE_PATH", raising=False)

    import tempfile

    from core.android_device_state_store import _resolve_store_state_path
    from core.canonical_task import CanonicalTaskRuntime

    (tmp_path / "tmp").mkdir()
    monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "tmp"))

    assert CanonicalTaskRuntime()._allocation_state_path == str(tmp_path / "d" / "task_allocation_truth.json")
    assert _resolve_store_state_path() == str(tmp_path / "d" / "galaxy_android_device_state_store.json")
    # 系统临时目录里已经有旧文件：继续认它（别把已存的设备快照甩在后面）
    old = tmp_path / "tmp" / "galaxy_android_device_state_store.json"
    old.write_text("{}")
    assert _resolve_store_state_path() == str(old)
    old.unlink()
    monkeypatch.setenv("ANDROID_DEVICE_STATE_STORE_PATH", "")
    assert _resolve_store_state_path() is None, "显式配成空 = 不落盘（原有语义不变）"
    monkeypatch.setenv("ANDROID_DEVICE_STATE_STORE_PATH", " /x/y.json ")
    assert _resolve_store_state_path() == "/x/y.json"
    monkeypatch.setenv("GALAXY_TASK_ALLOCATION_STATE_PATH", str(tmp_path / "alloc.json"))
    assert CanonicalTaskRuntime()._allocation_state_path == str(tmp_path / "alloc.json")


def test_the_addon_install_dir_follows_the_data_dir_with_a_legacy_fallback(tmp_path, monkeypatch):
    from core import addon_dependency_isolation as iso

    legacy = tmp_path / "repo" / "data" / "github_addons"
    monkeypatch.setattr(iso, "_LEGACY_ADDON_ROOT", legacy)
    monkeypatch.delenv("GITHUB_INSTALL_DIR", raising=False)

    monkeypatch.delenv("GALAXY_DATA_DIR", raising=False)
    assert iso.addon_root() == legacy.resolve(), "没配数据总目录：行为不变"

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path / "d"))
    assert iso.addon_root() == (tmp_path / "d" / "github_addons").resolve(), "配了：装进数据目录"
    legacy.mkdir(parents=True)
    assert iso.addon_root() == legacy.resolve(), "旧位置已经装着东西、新位置还没有：继续认旧的"
    (tmp_path / "d" / "github_addons").mkdir(parents=True)
    assert iso.addon_root() == (tmp_path / "d" / "github_addons").resolve(), "新位置有了：以新的为准"

    monkeypatch.setenv("GITHUB_INSTALL_DIR", str(tmp_path / "mine"))
    assert iso.addon_root() == (tmp_path / "mine").resolve(), "显式指定永远优先"


def test_the_installer_and_the_isolation_check_agree_on_the_one_root(tmp_path, monkeypatch):
    from core.addon_dependency_isolation import addon_root
    from core.github_installer import _get_install_dir

    monkeypatch.setenv("GALAXY_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("GITHUB_INSTALL_DIR", raising=False)
    assert _get_install_dir() == addon_root()


# ── 没人读的键不许登记 ─────────────────────────────────────────────────────────


def test_dead_keys_stay_deleted():
    for key in DEAD_KEYS:
        assert key not in CONFIG_SCHEMA, f"{key} 没有任何代码在读，不该再登记"
        assert key not in LABELS, key
        assert key not in PANEL_BUILTIN_KEYS, key


#: 只"声明"键、不"读取"键的文件：登记表、中文名表、面板清单、文档生成脚本、示例 .env、测试与文档。
_DECLARATION_ONLY = (
    "core/routes/config_schema_registry.py",
    "core/routes/config_labels.py",
    "core/routes/panel_builtin.py",
    "core/routes/panel_switch_policy.py",
    "core/routes/config_bundles.py",
    "core/routes/config_restart.py",
    "core/routes/config_schema_multimachine.py",
    "core/tuning.py",
    "electron/renderer/panel/src/settings_inventory.ts",
)


@functools.lru_cache(maxsize=1)
def _reader_corpus() -> str:
    parts = []
    for p in ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel in _DECLARATION_ONLY or rel.startswith(("tests/", "docs/", "scripts/gen_", ".git/")):
            continue
        if any(seg in rel for seg in ("node_modules/", "__pycache__/", "/dist/", ".venv/")):
            continue
        if p.suffix not in {".py", ".js", ".ts", ".rs", ".sh", ".ps1", ".bat", ".cmd", ".yml", ".yaml", ".kt", ".go"}:
            continue
        parts.append(p.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def test_every_registered_key_is_read_by_something():
    """面板上有一行、改了没有任何效果 —— 最糟的一种设置。登记一个键，就得有代码在读它。"""
    corpus = _reader_corpus()
    unread = sorted(k for k in CONFIG_SCHEMA if k not in corpus)
    assert not unread, f"这些键登记了，却没有任何代码（Python / JS / Rust / 脚本 / 编排文件）在读: {unread}"
