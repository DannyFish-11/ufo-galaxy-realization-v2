"""启动链上不许有没上界的 ``input()``。

全新克隆真跑逮到的:启动链上有**四处** ``input()``,全都没有上界 ——

    core/container_runtime.py   两个运行时都装了 → 用哪个
    core/container_runtime.py   都没装 → 选偏好(两处)
    core/model_selection.py     AI 主脑档位选哪一档

而它们全都排在**系统托盘之前**。只要没人按回车,后面所有步骤都不发生 ——
右下角的托盘自然也不会出现。所有者反馈的"卡在那儿"和"托盘没显示",在全新
克隆上是同一件事的两个面。

第一版只修了运行时那一处。那正是这个仓库最常犯的"改一处漏三处":四个提示是
同一件事的四个实例。现在实现收到 ``core/console_prompt.ask()`` 这一份,
这道门负责挡住新加的裸 ``input()``。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent

#: 启动链会走到的模块。这些文件里出现裸 ``input()`` 就意味着"能把启动卡死"。
#:
#: ``core/console_prompt.py`` 自己不算 —— 那份实现**就是**带上界的那个,
#: 它内部当然要调 ``input()``。
_STARTUP_PATH = (
    "main.py",
    "launcher",
    "core/container_runtime.py",
    "core/model_selection.py",
    "core/startup.py",
    "core/local_brain_manager.py",
)

_EXEMPT = {"core/console_prompt.py"}


def _files() -> List[Path]:
    out: List[Path] = []
    for entry in _STARTUP_PATH:
        path = REPO_ROOT / entry
        if path.is_dir():
            out.extend(sorted(path.rglob("*.py")))
        elif path.exists():
            out.append(path)
    return [f for f in out if str(f.relative_to(REPO_ROOT)) not in _EXEMPT]


def _bare_input_calls() -> List[Tuple[str, int]]:
    hits: List[Tuple[str, int]] = []
    for path in _files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "input":
                hits.append((str(path.relative_to(REPO_ROOT)), node.lineno))
    return hits


class TestNoRawInputWhereItCanHangStartup:
    def test_no_bare_input_on_the_startup_path(self):
        hits = _bare_input_calls()
        assert not hits, (
            "以下地方直接调了 input() —— 没人回答就会把启动(连同右下角的托盘)卡死。\n"
            "改法:用 core.console_prompt.ask(),它带上界,到点返回 None。\n" + "\n".join(f"  {p}:{ln}" for p, ln in hits)
        )

    def test_the_four_known_prompts_all_go_through_the_authority(self):
        """四处提示现在都该引用那一份。少一处就是又漏了。"""
        for rel in ("core/container_runtime.py", "core/model_selection.py"):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "from core.console_prompt import" in src, f"{rel} 没用那份带上界的实现"


class TestTheAuthorityItself:
    def test_nobody_answering_is_none_not_empty_string(self):
        """``None`` = 没人在;``""`` = 按了回车。空 ≠ 未知,这里也一样。"""
        from core.console_prompt import ask

        assert ask("忽略我: ", timeout_s=0.2) is None

    def test_it_comes_back_within_the_bound(self):
        import time

        from core.console_prompt import ask

        t0 = time.monotonic()
        ask("忽略我: ", timeout_s=0.3)
        assert time.monotonic() - t0 < 5.0, "没在上界内回来"

    def test_an_answer_is_passed_through(self, monkeypatch):
        from core.console_prompt import ask

        monkeypatch.setattr("builtins.input", lambda _p="": "2")
        assert ask("p", timeout_s=5.0) == "2"

    def test_zero_means_wait_forever(self, monkeypatch):
        from core.console_prompt import ask

        monkeypatch.setattr("builtins.input", lambda _p="": "docker")
        assert ask("p", timeout_s=0) == "docker"

    def test_ctrl_c_means_person_present_but_move_on(self, monkeypatch):
        """Ctrl+C 是"人在,别问了" —— 当作按回车,不是"没人在"。"""
        from core.console_prompt import ask

        def _boom(_p=""):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", _boom)
        assert ask("p", timeout_s=5.0) == ""

    def test_closed_stdin_means_nobody(self, monkeypatch):
        from core.console_prompt import ask

        def _eof(_p=""):
            raise EOFError

        monkeypatch.setattr("builtins.input", _eof)
        assert ask("p", timeout_s=5.0) is None

    def test_junk_timeout_falls_back_to_default_not_zero(self, monkeypatch):
        """退回 0 的话就又能卡死了 —— 这条守的正是那个。"""
        from core.console_prompt import DEFAULT_PROMPT_TIMEOUT_S, prompt_timeout_s

        monkeypatch.setenv("GALAXY_RUNTIME_PROMPT_TIMEOUT", "二十秒")
        assert prompt_timeout_s() == DEFAULT_PROMPT_TIMEOUT_S

    def test_the_notice_says_it_was_not_your_choice(self):
        """屏幕上必须看得出"这不是你选的",否则人下次找不到地方改。"""
        from core.console_prompt import timed_out_notice

        said = timed_out_notice("运行时", "Podman", timeout_s=20)
        assert "没人选" in said
        assert "不是你选的" in said
        assert "Podman" in said

    def test_it_is_configurable_from_the_panel(self):
        from core.console_prompt import PROMPT_TIMEOUT_ENV
        from core.routes.config import CONFIG_SCHEMA

        assert PROMPT_TIMEOUT_ENV in CONFIG_SCHEMA, "面板上配不到这个上界"


class TestThePromptsStillComeBeforeTheTray:
    def test_the_ordering_that_makes_this_matter_still_holds(self):
        """这道门的意义建立在"提示排在托盘之前"上。顺序变了要提醒改判据。"""
        src = (REPO_ROOT / "launcher/services.py").read_text(encoding="utf-8")
        infra = src.index("基础设施 (Docker / Podman")
        brain = src.index("AI 大脑（含主脑模型选择）")
        tray = src.index("系统托盘（独立于 Electron")
        assert infra < tray and brain < tray, "顺序变了 —— 这组判据的前提需要重写"
