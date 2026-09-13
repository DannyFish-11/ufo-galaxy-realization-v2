"""没人按回车,启动也得走下去 —— 而且要说清楚是自动选的。

全新克隆真跑发现(不在所有者报的那五条里,是跑出来的):

两个容器运行时都装着时,启动会停下来问"用 Docker 还是 Podman",而这个
``input()`` **没有上界**。这个提示排在系统托盘**之前**::

    launcher/services.py:2051  基础设施(这里问)
                  ↓
    launcher/services.py:2308  系统托盘

所以没人按回车的话,后面**所有**步骤都不发生,右下角的托盘自然也不会出现。
所有者反馈的"卡在那儿"和"托盘没显示",在全新克隆上是同一件事的两个面。

判据:
1. 没人回答 → 到点必须返回默认项,不许卡住;
2. 没人回答 ≠ 用户按了回车 —— 两者屏幕上说的话要不一样(不许让人以为是自己选的);
3. 用户真的回答了 → 听用户的,上界不许抢答;
4. 非 TTY → 根本不问(这条是既有行为,别改坏了)。
"""

from __future__ import annotations

import time

import pytest


class TestNobodyAnsweringDoesNotStopTheLaunch:
    def test_it_returns_the_default_instead_of_waiting_forever(self, monkeypatch, capsys):
        import core.container_runtime as cr

        monkeypatch.setattr(cr.sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setenv("GALAXY_RUNTIME_PROMPT_TIMEOUT", "0.3")
        # 没人回答:读 stdin 的那条线程永远拿不到东西。
        monkeypatch.setattr(cr, "_input_with_timeout", lambda _p, _t: None)

        t0 = time.monotonic()
        picked = cr.interactive_select(["podman", "docker"])
        assert time.monotonic() - t0 < 5.0, "还是卡住了"
        assert picked in ("podman", "docker")

    def test_it_says_out_loud_that_nobody_chose(self, monkeypatch, capsys):
        """屏幕上不许让人以为这是自己选的。"""
        import core.container_runtime as cr

        monkeypatch.setattr(cr.sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setenv("GALAXY_RUNTIME_PROMPT_TIMEOUT", "0.3")
        monkeypatch.setattr(cr, "_input_with_timeout", lambda _p, _t: None)

        cr.interactive_select(["podman", "docker"])
        out = capsys.readouterr().out
        assert "没人选" in out, out
        assert "默认" in out

    def test_an_actual_answer_still_wins(self, monkeypatch):
        """用户真的选了就听用户的 —— 上界只管"没人在"这一种。"""
        import core.container_runtime as cr

        monkeypatch.setattr(cr.sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(cr, "_input_with_timeout", lambda _p, _t: "2")

        avail = cr._prefer_recommended(["podman", "docker"])
        assert cr.interactive_select(["podman", "docker"]) == avail[1]

    def test_pressing_enter_is_not_the_same_as_being_absent(self, monkeypatch, capsys):
        """按回车 = 明确选了默认;没人在 = 我们替你选的。两者的话不一样。"""
        import core.container_runtime as cr

        monkeypatch.setattr(cr.sys.stdin, "isatty", lambda: True, raising=False)
        monkeypatch.setattr(cr, "_input_with_timeout", lambda _p, _t: "")

        cr.interactive_select(["podman", "docker"])
        out = capsys.readouterr().out
        assert "没人选" not in out, "用户明明按了回车,却说成没人在:" + out

    def test_a_pipe_is_never_asked(self, monkeypatch):
        """非 TTY 根本不该问 —— 这是既有行为,顺手钉住别改坏。"""
        import core.container_runtime as cr

        monkeypatch.setattr(cr.sys.stdin, "isatty", lambda: False, raising=False)

        def _must_not_ask(*_a, **_k):
            raise AssertionError("非交互终端里还在问")

        monkeypatch.setattr(cr, "_input_with_timeout", _must_not_ask)
        assert cr.interactive_select(["docker", "podman"]) == "docker"


class TestTheTimeoutItself:
    def test_none_means_nobody_answered_not_empty_answer(self):
        """``None`` 是"没人在",``""`` 是"按了回车" —— 空 ≠ 未知,这里也一样。"""
        import core.container_runtime as cr

        got = cr._input_with_timeout("忽略我: ", 0.2)
        assert got is None, f"没人回答时应当是 None,拿到 {got!r}"

    def test_zero_means_wait_forever(self, monkeypatch):
        """设 0 = 一直等(有人明确想要这个行为)。"""
        import core.container_runtime as cr

        monkeypatch.setattr("builtins.input", lambda _p="": "docker")
        assert cr._input_with_timeout("p", 0) == "docker"

    def test_the_env_var_is_read(self, monkeypatch):
        import core.container_runtime as cr

        monkeypatch.setenv("GALAXY_RUNTIME_PROMPT_TIMEOUT", "7.5")
        assert cr._prompt_timeout_s() == 7.5

    def test_a_junk_value_falls_back_to_the_default(self, monkeypatch):
        """乱填不该让启动炸,也不该变成 0(那就又能卡死了)。"""
        import core.container_runtime as cr

        monkeypatch.setenv("GALAXY_RUNTIME_PROMPT_TIMEOUT", "十秒")
        assert cr._prompt_timeout_s() == cr.DEFAULT_PROMPT_TIMEOUT_S

    def test_it_is_configurable_from_the_panel(self):
        """能改才算数 —— 不在 CONFIG_SCHEMA 里的话面板上根本看不见它。"""
        from core.routes.config import CONFIG_SCHEMA

        assert "GALAXY_RUNTIME_PROMPT_TIMEOUT" in CONFIG_SCHEMA


class TestThePromptComesBeforeTheTray:
    def test_the_ordering_that_makes_this_matter_still_holds(self):
        """这道门的意义建立在"提示在托盘之前"上。哪天顺序变了,这里要提醒改判据。

        用源码顺序判是有意的:验的就是"谁排在谁前面"这件事本身。
        """
        src = open("launcher/services.py", encoding="utf-8").read()
        infra = src.index("基础设施 (Docker / Podman")
        tray = src.index("系统托盘（独立于 Electron")
        assert infra < tray, "顺序变了 —— 提示不再挡在托盘前面,这组判据的前提需要重写"
