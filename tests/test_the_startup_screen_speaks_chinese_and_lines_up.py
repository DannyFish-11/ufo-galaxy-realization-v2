"""启动那一屏:说人话,而且对勾在同一列。

所有者看着真机输出提的两件事:

1. **"那些乱七八糟的英文字符串"** —— 屏幕上是
   ``runtime subject authority chain importable`` / ``environment checks passed`` /
   ``Desktop surface skipped (GALAXY_SKIP_DESKTOP_SURFACE)`` 这种只有写它的人
   看得懂的碎片,读的人根本不知道"到底好了没有"。
2. **"对勾对齐"** —— 同一屏里有两条对勾列:``cli_render.phase`` 那套走
   ``CONTENT_INDENT(2) + ICON_COL(2)``,对勾落在第 4 列;而
   ``config_preflight.format()`` 是手写的 ``"  " + "✓  ..."``,落在第 5 列。

修法是把两件事拆开而不是混在一起:``PhaseResult.detail`` 仍是给机器和判据 grep 的
证据串(``GALAXY_SKIP_DESKTOP_SURFACE`` / ``authority_boundary=`` 这些锚点不能翻译),
``PhaseResult.said`` 是产出结果的那一处自己说的人话,显示层只负责挑。
"""

import re
import textwrap

import pytest

from core.system_orchestrator import (
    PhaseResult,
    PhaseStatus,
    StartupPhase,
    SystemOrchestrator,
)

#: 至少要有一个汉字 —— "说人话"最起码的判据。
_CJK = re.compile(r"[一-鿿]")


@pytest.fixture(autouse=True)
def _no_npm(monkeypatch):
    monkeypatch.setenv("GALAXY_SKIP_DESKTOP_SURFACE", "1")


class TestEveryPhaseSaysSomethingAHumanCanRead:
    def test_every_phase_result_carries_a_chinese_sentence(self):
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()
        mute = [r.phase.name for r in summary.phase_results if not _CJK.search(r.said or "")]
        assert not mute, (
            "这些阶段没给人话,屏幕上只能退回英文的 detail: " f"{mute}。请在产出 PhaseResult 的那一处补 said="
        )

    def test_the_machine_evidence_is_still_there(self):
        """人话是新增的一层,不许把判据赖以 grep 的证据串顶掉。"""
        orch = SystemOrchestrator(continue_on_failure=True)
        summary = orch.run_startup_sequence()
        desktop = next(r for r in summary.phase_results if r.phase is StartupPhase.DESKTOP_SURFACE)
        assert "GALAXY_SKIP_DESKTOP_SURFACE" in desktop.detail, "detail 是证据串,不能被翻译掉"
        assert desktop.said and desktop.said != desktop.detail, "said 该是另一句话,不是 detail 的复制"

    def test_the_display_layer_prefers_said_but_never_invents_one(self, monkeypatch):
        from launcher import ui

        printed = []
        monkeypatch.setattr(ui, "step", lambda name, status="ok", value="", **kw: printed.append(value))

        ui.print_preflight_phase(
            StartupPhase.ENV_CHECKS,
            PhaseResult(StartupPhase.ENV_CHECKS, PhaseStatus.OK, detail="machine evidence", said="人话"),
        )
        assert printed == ["人话"]

        printed.clear()
        # 没有人话时必须原样露出 detail —— 猜着翻译比看不懂更糟。
        ui.print_preflight_phase(
            StartupPhase.ENV_CHECKS,
            PhaseResult(StartupPhase.ENV_CHECKS, PhaseStatus.OK, detail="machine evidence"),
        )
        assert printed == ["machine evidence"]


class TestTheTickColumnIsShared:
    """两套打印器的对勾必须落在同一列。"""

    def _icon_column(self, line: str) -> int:
        from core.ascii_art import display_width

        stripped = line.lstrip(" ")
        return display_width(line[: len(line) - len(stripped)])

    def test_the_preflight_block_uses_the_same_geometry_as_the_phase_rows(self, capsys):
        from core.ascii_art import CONTENT_INDENT, ICON_COL, display_width
        from core.config_preflight import run_preflight

        report = run_preflight(dry_run=True, mode="core", verbose=True)
        text = report.format(verbose=True)

        rows = [ln for ln in text.splitlines() if ln.startswith(" ") and ln.strip()[:1] in {"✓", "⚠", "✗", "•"}]
        assert rows, "预检块里一行带图标的都没有?这条判据要跟着改"
        for line in rows:
            assert self._icon_column(line) == CONTENT_INDENT, f"图标缩进不是 CONTENT_INDENT: {line!r}"
            body = line.lstrip(" ")
            glyph = body[:1]
            after = body[1:]
            pad = len(after) - len(after.lstrip(" "))
            assert display_width(glyph) + pad == ICON_COL, (
                "图标列宽与 cli_render.phase 不一致 —— 同一屏会出现两条对勾列: " f"{line!r}"
            )

    def test_no_hand_written_two_space_icon_remains(self):
        """回归钉子:图标后手写两个空格,就是当初错开一列的那个写法。

        只看**真正会被打出去的字符串常量**,不看文档串 —— 否则解释这个坑的注释
        自己会把判据踩红(第一版就是这么红的)。
        """
        import ast
        import inspect

        from core import config_preflight

        src = inspect.getsource(config_preflight.PreflightReport.format)
        tree = ast.parse(textwrap.dedent(src))

        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    docstrings.add(id(body[0].value))

        offenders = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
            and any(node.value.startswith(g + "  ") for g in ("✓", "⚠", "✗"))
        ]
        assert not offenders, f"又手写死了图标间距 {offenders!r},请走 pad_display(icon, ICON_COL)"


class TestThePreflightBlockIsInChinese:
    def test_the_frame_no_longer_shouts_english(self):
        from core.config_preflight import run_preflight

        text = run_preflight(dry_run=True, mode="core", verbose=True).format(verbose=True)
        for gone in (
            "Galaxy Pre-flight Configuration Check",
            "CRITICAL — startup blocked",
            "WARNING — degraded functionality",
            "All CRITICAL checks passed.",
        ):
            assert gone not in text, f"这句英文还在屏幕上: {gone!r}"

    def test_the_variable_names_and_commands_stay_verbatim(self):
        """人话只翻译说明,变量名与要照抄执行的命令一个字都不能动。"""
        from core.config_preflight import _CHECKS

        by_var = {c.var: c for c in _CHECKS}
        token = by_var["GALAXY_API_TOKEN"]
        assert "GALAXY_API_TOKEN=$(python3 -c" in token.hint, "要照抄的命令被翻译坏了"
        assert _CJK.search(token.description), "说明还没翻成人话"

    def test_every_check_speaks_chinese(self):
        from core.config_preflight import _CHECKS

        mute = [c.var for c in _CHECKS if not (_CJK.search(c.description) and _CJK.search(c.hint))]
        assert not mute, f"这些判据的说明/提示还是英文: {mute}"
