"""tests/test_check_wiring.py — 给"接线检查"本身上保险。

为什么这个工具需要测试
----------------------
``scripts/check_wiring.py`` 抓的是"能力存在但没人调用"。它自己恰恰最容易犯同一种病:
只要判据写松一点(比如引用侧不小心把 ``tests/`` 也扫进去),它就会**永远报 0 新增** ——
CI 恒绿,而它已经什么都不查了。这种失效没有任何外部表现,和它要抓的缺陷是同构的。

所以这里的用例几乎全是**反向断言**:构造一个确实未接线的函数,要求工具**必须**报出来。
"工具能跑通"不构成任何保证,"工具在该报的时候真的报了"才是。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location("check_wiring", REPO_ROOT / "scripts" / "check_wiring.py")
assert _SPEC and _SPEC.loader
cw = importlib.util.module_from_spec(_SPEC)
sys.modules["check_wiring"] = cw
_SPEC.loader.exec_module(cw)


def _write(tmp_path: Path, rel: str, source: str) -> Path:
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


class TestCoreJudgement:
    """判据本身:什么算"接上了"。"""

    def test_function_with_no_caller_is_reported(self, tmp_path):
        defs = _write(tmp_path, "core/thing.py", "def do_the_thing():\n    return 1\n")
        definitions, count = cw.collect_definitions([defs], tmp_path)
        referenced = cw.collect_references([defs])
        # 定义处自身不能自证 —— FunctionDef.name 不产生 Name/Attribute 节点。
        assert "do_the_thing" not in referenced
        assert cw.find_unwired(definitions, referenced, count) == [("do_the_thing", "core/thing.py:1")]

    def test_function_with_a_caller_is_not_reported(self, tmp_path):
        defs = _write(tmp_path, "core/thing.py", "def do_the_thing():\n    return 1\n")
        caller = _write(tmp_path, "nodes/n1.py", "from core.thing import do_the_thing\n\ndo_the_thing()\n")
        definitions, count = cw.collect_definitions([defs], tmp_path)
        referenced = cw.collect_references([defs, caller])
        assert cw.find_unwired(definitions, referenced, count) == []

    def test_method_called_through_self_counts_as_wired(self, tmp_path):
        defs = _write(
            tmp_path,
            "core/thing.py",
            "class A:\n"
            "    def helper(self):\n"
            "        return 1\n"
            "    def run(self):\n"
            "        return self.helper()\n",
        )
        definitions, count = cw.collect_definitions([defs], tmp_path)
        referenced = cw.collect_references([defs])
        assert [n for n, _ in cw.find_unwired(definitions, referenced, count)] == ["run"]

    def test_mention_in_a_comment_or_docstring_does_not_count(self, tmp_path):
        """这条是 AST-而非-正则 的全部理由。

        实测发生过:``core/routes/operator.py`` 的注释里提到了
        ``halt_ambient_presence``,而真正的调用点被改掉了。正则会认为它还接着。
        """
        defs = _write(
            tmp_path,
            "core/thing.py",
            '"""提到 do_the_thing 也不算调用。"""\n\n\ndef do_the_thing():\n    # do_the_thing 也不算\n    return 1\n',
        )
        definitions, count = cw.collect_definitions([defs], tmp_path)
        referenced = cw.collect_references([defs])
        assert [n for n, _ in cw.find_unwired(definitions, referenced, count)] == ["do_the_thing"]

    def test_string_constant_counts_as_a_reference(self, tmp_path):
        """``__all__ = ["foo"]`` / ``getattr(x, "foo")`` 是真实的动态引用。"""
        defs = _write(tmp_path, "core/thing.py", "def do_the_thing():\n    return 1\n")
        caller = _write(tmp_path, "core/exports.py", '__all__ = ["do_the_thing"]\n')
        definitions, count = cw.collect_definitions([defs], tmp_path)
        referenced = cw.collect_references([defs, caller])
        assert cw.find_unwired(definitions, referenced, count) == []

    def test_private_names_are_never_reported(self, tmp_path):
        defs = _write(tmp_path, "core/thing.py", "def _helper():\n    return 1\n")
        definitions, count = cw.collect_definitions([defs], tmp_path)
        assert cw.find_unwired(definitions, cw.collect_references([defs]), count) == []

    def test_duplicate_names_are_skipped_rather_than_guessed(self, tmp_path):
        """同名方法散在多个类上时,AST 分不清引用指向哪一个 —— 宁可漏报不误报。"""
        a = _write(tmp_path, "core/a.py", "class A:\n    def run(self):\n        return 1\n")
        b = _write(tmp_path, "core/b.py", "class B:\n    def run(self):\n        return 2\n")
        definitions, count = cw.collect_definitions([a, b], tmp_path)
        assert count["run"] == 2
        assert cw.find_unwired(definitions, cw.collect_references([a, b]), count) == []

    def test_syntax_error_file_is_skipped_not_fatal(self, tmp_path):
        broken = _write(tmp_path, "core/broken.py", "def (:\n")
        ok = _write(tmp_path, "core/ok.py", "def do_the_thing():\n    return 1\n")
        definitions, count = cw.collect_definitions([broken, ok], tmp_path)
        assert [n for n, _ in cw.find_unwired(definitions, cw.collect_references([broken, ok]), count)] == [
            "do_the_thing"
        ]


class TestExemptions:
    def test_route_modules_are_exempt_in_both_trees(self):
        """路由处理函数由装饰器注册,静态看不到调用方。

        两棵树都要豁免 —— 早先版本只豁免了 ``core/routes/``,
        ``galaxy_gateway/routes/`` 下 23 个处理函数因此被整片误报。
        """
        assert cw._is_exempt("core/routes/operator.py", "halt_presence")
        assert cw._is_exempt("galaxy_gateway/routes/android.py", "handle_push")
        assert not cw._is_exempt("core/desktop_presence_runtime.py", "halt_ambient_presence")

    def test_exempt_names_all_carry_a_reason(self):
        """豁免必须写理由 —— 没理由的豁免下次没人敢删,清单只会越来越长。"""
        for name, reason in cw._EXEMPT_NAMES.items():
            assert reason.strip(), f"{name} 的豁免没写理由"


class TestBaselineSemantics:
    """基线是**债的记账**,不是白名单。"""

    def test_baseline_file_exists_and_is_wellformed(self):
        names = cw.load_baseline()
        assert names, "基线为空 —— 要么没生成,要么读坏了;两种情况都会让这道闸失去『只看新增』的能力"
        assert all(isinstance(n, str) and n and not n.startswith("_") for n in names)

    def test_missing_baseline_degrades_to_reporting_everything(self, tmp_path, monkeypatch):
        """基线读不到时必须**全量报**,而不是静默放行。

        反过来(读不到就当作全都豁免)会造出一个恒绿的假闸 —— 这正是本工具要抓的病。
        """
        monkeypatch.setattr(cw, "BASELINE_PATH", tmp_path / "nope.json")
        assert cw.load_baseline() == set()

    def test_corrupt_baseline_also_degrades_to_reporting_everything(self, tmp_path, monkeypatch):
        bad = tmp_path / "wiring_baseline.json"
        bad.write_text("{ not json", encoding="utf-8")
        monkeypatch.setattr(cw, "BASELINE_PATH", bad)
        assert cw.load_baseline() == set()

    def test_roundtrip_write_then_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cw, "BASELINE_PATH", tmp_path / "wiring_baseline.json")
        cw.write_baseline(["b_thing", "a_thing"])
        assert cw.load_baseline() == {"a_thing", "b_thing"}
        # 排序落盘:否则每次重记都产生无意义的 diff,评审时看不出真正新增了什么。
        import json

        assert json.loads((tmp_path / "wiring_baseline.json").read_text(encoding="utf-8"))["unwired"] == [
            "a_thing",
            "b_thing",
        ]


class TestAgainstTheRealRepo:
    """对真实仓库跑一遍 —— 桩数据能证明逻辑,证明不了判据在真实规模下还成立。"""

    @pytest.mark.slow
    def test_repo_has_no_new_unwired_capabilities(self):
        definitions, count = cw.collect_definitions(cw._iter_definition_files())
        referenced = cw.collect_references(cw._iter_reference_files())
        unwired = cw.find_unwired(definitions, referenced, count)
        baseline = cw.load_baseline()
        new = sorted(n for n, _ in unwired if n not in baseline)
        assert not new, f"出现了基线之外的未接线公开能力:{new}"

    @pytest.mark.slow
    def test_reference_side_covers_more_than_the_definition_side(self):
        """引用侧必须扫全仓。

        早先版本引用侧也只扫 core/ 与 galaxy_gateway/,于是"只被 ``nodes/`` 或
        ``scripts/`` 调用"的能力被误判成未接线(实测多报约 100 条)。
        """
        assert len(cw._iter_reference_files()) > len(cw._iter_definition_files())

    @pytest.mark.slow
    def test_tests_directory_is_excluded_from_the_reference_side(self):
        """只有测试调用它,恰恰就是本工具要抓的情形 —— tests/ 绝不能算作"接上了"。"""
        assert "tests" in cw.REFERENCE_SKIP_PARTS
        assert not any("tests" in p.parts for p in cw._iter_reference_files())
