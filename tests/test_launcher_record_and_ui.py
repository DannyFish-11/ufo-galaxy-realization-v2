"""启动记录：事实与呈现的分离，以及三个渲染器读同一份事实。

要钉住什么
----------
启动器此前是"一边判断一边 ``print``"，判断结果只以彩色文本的形式存在过一瞬。
后果是启动失败时只能拿到截图、托盘/面板各自再问一遍状态、"上次降级了什么"
无处可查。

``launcher/record.py`` 持有事实，``launcher/ui.py`` 渲染。这个文件钉的是
**这条分离不许被抹平**，以及三个渲染器确实读的是同一份事实（不是各自重算）。
"""

from __future__ import annotations

import ast
import contextlib
import io
import json
import pathlib

import pytest

from launcher import record as REC
from launcher import ui as UI
from launcher.record import Column, StartupRecord, Status, StepResult


@pytest.fixture(autouse=True)
def _fresh_record():
    """每条用例开一份干净记录，避免互相污染（记录是进程级单例）。"""
    UI.begin("vTEST")
    UI.set_column(Column.ENV)
    yield
    UI.begin("vTEST")


# ---------------------------------------------------------------------------
# 1. 分离本身
# ---------------------------------------------------------------------------


class TestSeparationOfFactsFromPresentation:
    def test_record_module_imports_nothing_presentational(self) -> None:
        """``record.py`` 里不许出现任何渲染相关的 import。

        一旦事实层知道了自己会被怎么显示，分离就失效了 —— 那正是现状的病根。
        用 AST 查而不是 grep 字符串：注释里提到 ``cli_render`` 是可以的
        （record.py 的 docstring 就提了），真 import 才不行。
        """
        tree = ast.parse((pathlib.Path(REC.__file__)).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        forbidden = [m for m in imported if any(k in m for k in ("cli_render", "ascii_art", "ui"))]
        assert not forbidden, f"事实层 import 了呈现层：{forbidden}"

    def test_record_has_no_color_or_glyph_vocabulary(self) -> None:
        """事实层里不该出现颜色码、图标字符或缩进常量。"""
        src = pathlib.Path(REC.__file__).read_text(encoding="utf-8")
        # 只查代码，不查注释/docstring —— 注释里说明"图标映射在 ui.py"是合理的
        tree = ast.parse(src)
        literals: list[str] = [
            n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
        ]
        docstrings = {
            ast.get_docstring(n) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef))
        }
        code_literals = [s for s in literals if s not in docstrings]
        bad = [s for s in code_literals if "\x1b[" in s or any(g in s for g in ("✓", "⚠", "✗", "◐"))]
        assert not bad, f"事实层出现了呈现层词汇：{bad}"

    def test_glyph_mapping_lives_only_in_ui(self) -> None:
        """状态 → 图标的映射必须只有一处。"""
        assert set(UI._STATUS_GLYPH) == set(Status), "有 Status 没有对应的显示词汇"


# ---------------------------------------------------------------------------
# 2. step() 这个咽喉
# ---------------------------------------------------------------------------


class TestStepIsTheChokePoint:
    def test_step_records_and_prints(self, capsys: pytest.CaptureFixture) -> None:
        UI.step("Python", Status.OK, "3.11.15", column=Column.ENV, executable="/usr/bin/python3")
        out = capsys.readouterr().out
        assert "Python" in out and "3.11.15" in out
        rec = UI.current()
        assert len(rec.steps) == 1
        s = rec.steps[0]
        assert s.column is Column.ENV and s.status is Status.OK
        assert s.detail["executable"] == "/usr/bin/python3"

    @pytest.mark.parametrize(
        "legacy,expected",
        [
            ("ok", Status.OK),
            ("warn", Status.DEGRADED),
            ("error", Status.FAILED),
            ("info", Status.SKIPPED),
            ("完全没见过的词", Status.SKIPPED),
        ],
    )
    def test_legacy_status_vocabulary_is_translated(self, legacy: str, expected: Status) -> None:
        """``print_item`` 那 71 个老调用点用的是 ok/warn/error/info。"""
        assert UI.coerce_status(legacy) is expected

    def test_info_counts_as_skipped_not_ok(self) -> None:
        """``print_item(..., "info")`` 表达的是"仅提示"，算成 OK 会让"N 正常"虚高。

        那个数字是用户判断"能不能用"的第一眼依据，虚高比少报更危险。
        """
        UI.step("提示项", "info")
        assert UI.current().ok_count == 0

    def test_column_defaults_to_the_current_column(self) -> None:
        """``set_column`` 之后的 step 自动归入该栏 —— 71 个老调用点因此不用改。"""
        UI.set_column(Column.BRAIN)
        UI.step("模型", Status.OK, "qwen3:8b")
        assert UI.current().steps[-1].column is Column.BRAIN

    @pytest.mark.parametrize(
        "title,expected",
        [
            ("[Phase 0] 环境检查", Column.ENV),
            ("[Phase 2] 依赖确保", Column.DEPS),
            ("[Phase 1] 系统预检", Column.ENV),
            ("[系统启动]", Column.FABRIC),
            ("[系统停止]", Column.PRESENCE),
            ("AI 大脑", Column.BRAIN),
            ("桌面覆盖层", Column.PRESENCE),
        ],
    )
    def test_phase_titles_map_to_columns(self, title: str, expected: Column) -> None:
        """现存三套阶段编号的标题都要能归到栏目。"""
        assert UI.column_for_title(title) is expected

    def test_unknown_title_falls_back_without_crashing(self) -> None:
        """没见过的标题不该让启动崩，也不该污染「环境」栏。"""
        assert UI.column_for_title("某个从未出现过的标题") is Column.FABRIC


# ---------------------------------------------------------------------------
# 3. 汇总只算数，不决定显示
# ---------------------------------------------------------------------------


class TestRecordAggregation:
    def _rec(self) -> StartupRecord:
        r = StartupRecord(version="vTEST")
        r.add(StepResult(Column.ENV, "a", Status.OK))
        r.add(StepResult(Column.ENV, "b", Status.DEGRADED, hint="修 b"))
        r.add(StepResult(Column.FABRIC, "c", Status.FAILED))
        r.add(StepResult(Column.BRAIN, "d", Status.SKIPPED))
        return r

    def test_counts(self) -> None:
        r = self._rec()
        assert r.ok_count == 1
        assert [s.name for s in r.degraded] == ["b"]
        assert [s.name for s in r.failed] == ["c"]

    def test_columns_in_order_skips_empty_ones(self) -> None:
        r = self._rec()
        assert r.columns_in_order() == [Column.ENV, Column.FABRIC, Column.BRAIN]

    def test_worst_status_wins_per_column(self) -> None:
        """一栏里有失败就不能显示为正常 —— 折叠不该把问题折没。"""
        r = self._rec()
        assert UI._worst(r.by_column(Column.ENV)) is Status.DEGRADED
        assert UI._worst(r.by_column(Column.FABRIC)) is Status.FAILED


# ---------------------------------------------------------------------------
# 4. 三个渲染器读同一份事实
# ---------------------------------------------------------------------------


class TestThreeRenderersOneTruth:
    def test_json_contains_every_step(self, tmp_path: pathlib.Path) -> None:
        UI.step("A", Status.OK, "1", column=Column.ENV, probe="x")
        UI.step("B", Status.DEGRADED, "2", column=Column.FABRIC, hint="修 B")
        UI.finish(REC.EXIT_OK, tui=False)
        UI.render_json(root=str(tmp_path))
        data = json.loads((tmp_path / "runtime" / "startup.json").read_text(encoding="utf-8"))
        assert [s["name"] for s in data["steps"]] == ["A", "B"]
        assert data["steps"][0]["detail"] == {"probe": "x"}
        assert data["steps"][1]["hint"] == "修 B"
        assert data["counts"]["degraded"] == 1

    def test_json_records_exit_code_and_meaning(self, tmp_path: pathlib.Path) -> None:
        UI.step("X", Status.FAILED, column=Column.DEPS)
        UI.finish(REC.EXIT_DEPENDENCY, tui=False)
        UI.render_json(root=str(tmp_path))
        data = json.loads((tmp_path / "runtime" / "startup.json").read_text(encoding="utf-8"))
        assert data["exit_code"] == REC.EXIT_DEPENDENCY
        assert data["exit_meaning"] == "依赖缺失"

    def test_json_write_failure_does_not_raise(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """落盘只是排障辅助，写失败绝不能挡启动 —— 但必须记 warning，不许静默。"""
        monkeypatch.setattr(UI.pathlib.Path, "mkdir", _boom)
        assert UI.render_json(root="/definitely/not/writable") is None

    def test_tui_shows_degraded_hint(self, capsys: pytest.CaptureFixture) -> None:
        """每项降级各带专属建议 —— 不共用一句话。"""
        UI.step("Docker", Status.DEGRADED, "未安装", column=Column.FABRIC, hint="装后重跑即恢复")
        UI.step("模型", Status.DEGRADED, "未拉取", column=Column.BRAIN, hint="python main.py --select-model")
        UI.render_tui()
        out = capsys.readouterr().out
        assert "装后重跑即恢复" in out
        assert "python main.py --select-model" in out

    def test_tui_column_summary_names_the_degraded_item(self, capsys: pytest.CaptureFixture) -> None:
        UI.step("好项", Status.OK, "ok", column=Column.FABRIC)
        UI.step("坏项", Status.DEGRADED, "坏", column=Column.FABRIC)
        UI.render_tui()
        out = capsys.readouterr().out
        assert "坏项" in out, "折叠后降级项没有被点名，问题被折没了"


def _boom(*_a, **_kw):
    raise OSError("simulated")


# ---------------------------------------------------------------------------
# 5. 退出码
# ---------------------------------------------------------------------------


class TestExitCodes:
    def test_codes_are_distinct(self) -> None:
        codes = [
            REC.EXIT_OK,
            REC.EXIT_ERROR,
            REC.EXIT_USAGE,
            REC.EXIT_DEPENDENCY,
            REC.EXIT_PORT_IN_USE,
            REC.EXIT_ENVIRONMENT,
            REC.EXIT_INTERRUPTED,
        ]
        assert len(set(codes)) == len(codes), "退出码有重复，自动化就分不清失败原因"

    def test_every_code_has_a_meaning(self) -> None:
        for code in (
            REC.EXIT_OK,
            REC.EXIT_ERROR,
            REC.EXIT_USAGE,
            REC.EXIT_DEPENDENCY,
            REC.EXIT_PORT_IN_USE,
            REC.EXIT_ENVIRONMENT,
            REC.EXIT_INTERRUPTED,
        ):
            assert REC.EXIT_MEANING.get(code), f"退出码 {code} 没有人话解释"

    def test_interrupt_uses_the_shell_convention(self) -> None:
        """128 + SIGINT(2) = 130。此前 Ctrl+C 也返回 0，自动化区分不出来。"""
        assert REC.EXIT_INTERRUPTED == 130


# ---------------------------------------------------------------------------
# 6. main.py 真的接上了（不是建了一套没人用的）
# ---------------------------------------------------------------------------


class TestMainIsWired:
    def _main_src(self) -> str:
        return (pathlib.Path(__file__).parent.parent / "main.py").read_text(encoding="utf-8")

    def test_print_item_delegates_to_ui_step(self) -> None:
        src = self._main_src()
        assert "from launcher import ui as _ui" in src
        assert "_ui.step(name, status, detail)" in src, "print_item 没有转调 ui.step"

    def test_print_phase_sets_the_column(self) -> None:
        assert "_ui.set_column(_ui.column_for_title(title))" in self._main_src()

    def test_main_writes_the_startup_record(self) -> None:
        assert "_ui.finish(" in self._main_src(), "main 结束时没有封盘落盘"

    def test_main_has_version_flag(self) -> None:
        assert '"--version"' in self._main_src()

    def test_interrupt_returns_nonzero(self) -> None:
        assert "_record.EXIT_INTERRUPTED" in self._main_src(), "Ctrl+C 仍返回 0"


def test_step_survives_render_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    """渲染层挂了也不能挡启动 —— 但必须仍然打出这一行（降级为纯 ASCII）。"""
    import core.cli_render as R

    monkeypatch.setattr(R, "phase", _boom)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        UI.step("关键项", Status.OK, "值")
    assert "关键项" in buf.getvalue()
    assert len(UI.current().steps) == 1, "渲染失败时记录也必须留下"
