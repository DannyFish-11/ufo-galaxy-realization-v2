"""「保存设置」不再把没人动过的内部开关钉进 .env。

被修的问题
----------
面板只列 18 个真有取舍的开关，另外 78 个（内置 45 / 运维 28 / 并进整档 5）藏起来了 —— 但「保存设置」
会把登记表里全部键的默认值整体写进 ``.env``，于是这 78 个开关又整整齐齐地躺在那份几百行的文件里：
真正被人改过的几行淹没在里面，而钉死的默认值还会盖住以后代码里默认值的修正。

规则：面板不列的开关，值等于默认就不写；**值被改过的照旧写**（手写 ``GALAXY_DEV_MODE=true`` 不能被丢）。
面板上的开关不受影响。
"""

from __future__ import annotations

import pytest

from core.routes import config as config_routes
from core.routes.config_schema_registry import CONFIG_SCHEMA
from core.routes.panel_switch_policy import BUILTIN, MEMBER, OPS, PANEL, SWITCH_POLICY


@pytest.fixture()
def written(tmp_path, monkeypatch):
    target = tmp_path / ".env"
    monkeypatch.setattr(config_routes, "ENV_FILE", target)
    for key in CONFIG_SCHEMA:  # 干净环境：只看登记默认
        monkeypatch.delenv(key, raising=False)

    def run(**overrides):
        config_routes._write_env_file_with(overrides or None)
        text = target.read_text(encoding="utf-8")
        return {ln.split("=", 1)[0] for ln in text.splitlines() if "=" in ln and not ln.startswith("#")}, text

    return run


def _hidden_keys():
    return [k for k, v in SWITCH_POLICY.items() if v.disposition in (BUILTIN, OPS, MEMBER) and k in CONFIG_SCHEMA]


def test_there_are_hidden_switches_to_test():
    assert len(_hidden_keys()) >= 70


def test_untouched_hidden_switches_are_not_pinned(written):
    keys, _ = written()
    pinned = sorted(k for k in _hidden_keys() if k in keys)
    assert not pinned, f"没人动过的内部开关又被钉进了 .env: {pinned}"


def test_a_hand_set_hidden_switch_survives_a_save(written, monkeypatch):
    """手写 GALAXY_DEV_MODE=true（运维开关）后保存设置，它不能被丢掉。"""
    ops = next(k for k, v in SWITCH_POLICY.items() if v.disposition == OPS and CONFIG_SCHEMA[k]["type"] == "boolean")
    flipped = "false" if str(CONFIG_SCHEMA[ops]["default"]).lower() in ("true", "1") else "true"
    monkeypatch.setenv(ops, flipped)
    keys, text = written()
    assert ops in keys, f"{ops} 被改成了 {flipped}，保存后却从 .env 里消失了"
    assert f"{ops}={flipped}" in text


def test_a_member_written_by_hand_is_kept_even_when_it_equals_the_default(written, monkeypatch):
    """并进整档的成员（如 GALAXY_NATS_ENABLED）：本地模式下手写 true 要强行起总线，保存设置不能把它丢了。"""
    monkeypatch.setenv("GALAXY_NATS_ENABLED", "true")  # 与登记默认相同，但这是人写的
    keys, text = written()
    assert "GALAXY_NATS_ENABLED" in keys and "GALAXY_NATS_ENABLED=true" in text


def test_a_member_nobody_wrote_is_not_pinned(written):
    keys, _ = written()
    members = [k for k, v in SWITCH_POLICY.items() if v.disposition == MEMBER and k in CONFIG_SCHEMA]
    assert members and not [k for k in members if k in keys]


def test_panel_switches_are_unaffected(written):
    """面板上的开关照旧：默认值也写（它们是用户真有取舍的，.env 里留个明确的值）。"""
    panel_bools = [
        k
        for k, v in SWITCH_POLICY.items()
        if v.disposition == PANEL and k in CONFIG_SCHEMA and str(CONFIG_SCHEMA[k]["default"]).strip()
    ]
    assert panel_bools
    keys, _ = written()
    assert any(k in keys for k in panel_bools)


def test_non_switch_keys_are_unaffected(written):
    keys, _ = written()
    some_plain = [k for k, m in CONFIG_SCHEMA.items() if k not in SWITCH_POLICY and str(m["default"]).strip()]
    assert some_plain and any(k in keys for k in some_plain)
