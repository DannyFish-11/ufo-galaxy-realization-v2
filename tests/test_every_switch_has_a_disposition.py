"""每个布尔开关都有一个去处：留在面板 / 内置 / 开发运维。新增开关必须先在清单里说清楚。

背景见 ``core/routes/panel_switch_policy.py`` 与 ``docs/PANEL_SWITCHES.md``。仓库所有者的要求是「不要乱加开关」，
这是它的可执行形式：``CONFIG_SCHEMA`` 里多一个布尔键而清单里没有，这里就红。

另钉住清点时查出的几处真问题（登记表默认值与代码不一致、面板只认字面量 "true"）。
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from core.routes.config import CONFIG_SCHEMA, PANEL_HIDDEN_KEYS, _bool_text, get_config
from core.routes.panel_switch_policy import BUILTIN, DISPOSITIONS, OPS, PANEL, PANEL_HIDDEN_SWITCH_KEYS, SWITCH_POLICY

REPO = Path(__file__).resolve().parent.parent


def _bool_keys() -> set:
    return {k for k, m in CONFIG_SCHEMA.items() if m["type"] in ("boolean", "bool")}


def test_every_boolean_switch_has_a_disposition_and_nothing_else_does():
    switches = _bool_keys()
    missing = sorted(switches - set(SWITCH_POLICY))
    stale = sorted(set(SWITCH_POLICY) - switches)
    assert not missing, (
        f"这些布尔开关还没在 core/routes/panel_switch_policy.py 里说它是留在面板、内置还是开发运维：{missing}。"
        "新增开关要先回答：用户真有取舍吗？（有 → panel；没有 → builtin / ops，并说为什么）"
    )
    assert not stale, f"清单里有不再是布尔开关的键：{stale}"


def test_every_entry_says_what_and_why():
    for key, pol in SWITCH_POLICY.items():
        assert pol.disposition in DISPOSITIONS, key
        assert pol.group, f"{key} 没写分组"
        assert len(pol.reason) >= 8, f"{key} 的理由太短，写清楚为什么"


def test_switches_are_declared_as_boolean_not_bool():
    """设置页只把 type == 'boolean' 画成推拉开关，'bool' 会被画成文本框。"""
    assert [k for k, m in CONFIG_SCHEMA.items() if m["type"] == "bool"] == []


def test_boolean_defaults_are_literal_true_or_false():
    """「保存设置」会把登记表默认值整体写进 .env —— 默认值必须是无歧义的字面量。"""
    odd = {
        k: m["default"]
        for k, m in CONFIG_SCHEMA.items()
        if m["type"] == "boolean" and m["default"] not in ("true", "false")
    }
    assert not odd, f"这些布尔开关的默认值不是 true/false：{odd}"


def test_builtin_switches_default_on_because_nobody_should_be_turning_them_off():
    for key, pol in SWITCH_POLICY.items():
        if pol.disposition == BUILTIN:
            assert CONFIG_SCHEMA[key]["default"] == "true", f"{key} 说是不该有人去关的内置机制，默认却是关"


def test_the_panel_hides_exactly_the_builtin_and_ops_switches_and_lists_the_panel_ones():
    assert PANEL_HIDDEN_SWITCH_KEYS == {k for k, p in SWITCH_POLICY.items() if p.disposition in (BUILTIN, OPS)}
    assert PANEL_HIDDEN_SWITCH_KEYS <= PANEL_HIDDEN_KEYS
    listed = asyncio.run(get_config())
    for key, pol in SWITCH_POLICY.items():
        if pol.disposition == PANEL:
            assert key in listed, f"{key} 该留在面板上，/api/config/all 却没列"
        else:
            assert key not in listed, f"{key} 是 {pol.disposition}，不该列在面板上"


def test_hidden_switches_are_still_registered_so_they_can_be_saved_and_read():
    assert PANEL_HIDDEN_SWITCH_KEYS <= set(CONFIG_SCHEMA)


def test_the_panel_only_ever_receives_true_or_false_for_a_switch(monkeypatch):
    """设置页只认字面量 "true" 为开。.env 里手写的 =1 / =on 代码都认作开，面板却显示成关。"""
    monkeypatch.setenv("GALAXY_AEC", "1")
    monkeypatch.setenv("GALAXY_SPEAK", "OFF")
    listed = asyncio.run(get_config())
    assert listed["GALAXY_AEC"]["value"] == "true"
    assert listed["GALAXY_SPEAK"]["value"] == "false"
    for key, item in listed.items():
        if item["type"] == "boolean":
            assert item["default"] in ("true", "false"), key


def test_bool_text_does_not_guess_for_values_it_does_not_recognise():
    assert [_bool_text(v) for v in ("1", "true", "YES", " on ")] == ["true"] * 4
    assert [_bool_text(v) for v in ("0", "false", "No", "off", "")] == ["false"] * 5
    assert _bool_text("maybe") == "maybe"


def test_registry_defaults_match_what_the_code_does_when_nothing_is_set():
    """清点时查出的三处：登记成与代码相反的默认值，保存一次设置就把错的写进 .env。"""
    assert CONFIG_SCHEMA["GALAXY_MEMORY_MEDIA"]["default"] == "false", "截图/录音落盘在代码里默认关"
    assert CONFIG_SCHEMA["GALAXY_ENTRYMODE_USE_READINESS"]["default"] == "false", "就绪度判定在代码里默认关"
    assert CONFIG_SCHEMA["GALAXY_PREFLIGHT_FAIL_FAST"]["default"] == "true", "预检命令行默认失败就停"


def test_the_readiness_flag_accepts_what_the_panel_writes(monkeypatch):
    """面板写的是 true/false，代码以前只认 "1" —— 面板上打开了，实际没生效。"""
    from core.unified.entrypoint_router import readiness_path_enabled

    monkeypatch.delenv("GALAXY_ENTRYMODE_USE_READINESS", raising=False)
    assert readiness_path_enabled() is False, "默认关"
    for on in ("1", "true", "True", "on"):
        monkeypatch.setenv("GALAXY_ENTRYMODE_USE_READINESS", on)
        assert readiness_path_enabled() is True, on
    for off in ("0", "false", ""):
        monkeypatch.setenv("GALAXY_ENTRYMODE_USE_READINESS", off)
        assert readiness_path_enabled() is False, off


def test_the_switches_document_is_generated_from_the_list_and_not_stale():
    r = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "gen_panel_switches_doc.py"), "--check"],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert r.returncode == 0, r.stderr or r.stdout
