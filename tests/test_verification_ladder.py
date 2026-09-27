"""分级验证阶梯（M1.5 / 架构书 R8）的判据测试。

A. 依赖语义：在一个临时的小仓库里逐条钉住
   模块级传递 · 懒导入一跳 · 父包 #init · importlib 字面量 · 测试里的 patch 字符串与脚本路径 ·
   生产代码里的字符串不算 · conftest 作用域 · 非 Python 文件 · 相对导入
B. 已知盲区写成断言：两跳懒导入选不中；选不中时 L0 必须自称不可信
C. 升档：全局配置、空选择
D. 与 CI 分片同一套算法
E. 真实仓库的历史回放：M1 那次真的变红的测试必须在 L0 里
F. 端到端：ladder:L0 由 harness 按 target_files 选测试并跑；跑无关测试拿不到 trusted
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

import core.context_archive as context_archive
import core.engineering_verification as ev
import core.verification_ladder as vl

REPO_ROOT = Path(__file__).resolve().parents[1]

SYNTHETIC = {
    "conftest.py": "",
    "pkg/__init__.py": """
        from . import base

        def get_heavy():
            from . import heavy
            return heavy
    """,
    "pkg/base.py": "X = 1\n",
    "pkg/heavy.py": "Y = 2\n",
    "pkg/mid.py": "from pkg.base import X\n",
    "pkg/rel.py": "from .base import X\n",
    "pkg/lazy_user.py": """
        def f():
            from pkg import deep
            return deep.g()
    """,
    "pkg/deep.py": """
        def g():
            from pkg import deeper
            return deeper.Z
    """,
    "pkg/deeper.py": "Z = 3\n",
    "pkg/dyn.py": 'import importlib\nH = importlib.import_module("pkg.heavy")\n',
    "pkg/doc.py": 'NOTE = "see pkg.heavy and scripts/tool.py for details"\n',
    "scripts/tool.py": "import pkg.heavy\n",
    "settings.json": "{}\n",
    "tests/test_base.py": "from pkg.base import X\n\ndef test_x():\n    assert X == 1\n",
    "tests/test_mid.py": "import pkg.mid\n\ndef test_mid():\n    assert pkg.mid.X == 1\n",
    "tests/test_rel.py": "import pkg.rel\n\ndef test_rel():\n    assert pkg.rel.X == 1\n",
    "tests/test_sub.py": "import pkg.base\n\ndef test_sub():\n    assert pkg.base.X == 1\n",
    "tests/test_pkg_attr.py": "from pkg import get_heavy\n\ndef test_attr():\n    assert get_heavy().Y == 2\n",
    "tests/test_lazy.py": "from pkg.lazy_user import f\n\ndef test_lazy():\n    assert f() == 3\n",
    "tests/test_patch.py": (
        "from unittest.mock import patch\n\ndef test_patch():\n" '    with patch("pkg.heavy.Y", 5):\n        pass\n'
    ),
    "tests/test_script.py": 'SCRIPT = "scripts/tool.py"\n\ndef test_script():\n    assert SCRIPT\n',
    "tests/test_dyn.py": "import pkg.dyn\n\ndef test_dyn():\n    assert pkg.dyn.H.Y == 2\n",
    "tests/test_doc.py": "import pkg.doc\n\ndef test_doc():\n    assert pkg.doc.NOTE\n",
    "tests/test_reads_json.py": (
        'from pathlib import Path\n\ndef test_json():\n    assert (Path(__file__).parents[1] / "settings.json").exists()\n'
    ),
    "tests/sub/conftest.py": "import pytest\n\n@pytest.fixture\ndef b():\n    from pkg import base\n    return base\n",
    "tests/sub/test_in_scope.py": "def test_scope():\n    assert True\n",
}


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for rel, body in SYNTHETIC.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setattr(vl, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "runtime" / "idx.json")
    monkeypatch.setattr(ev, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(context_archive, "_ROOT", tmp_path / "runtime" / "archive")
    return tmp_path


def _l0(changed):
    return set(vl.select_affected_tests(changed, vl.build_dependency_index(use_cache=False)).tests)


# ---------------------------------------------------------------------------
# A. 依赖语义
# ---------------------------------------------------------------------------


class TestDependencySemantics:
    def test_module_level_imports_are_transitive(self, repo):
        affected = _l0(["pkg/base.py"])
        assert {"tests/test_base.py", "tests/test_mid.py", "tests/test_sub.py", "tests/test_rel.py"} <= affected

    def test_submodule_import_runs_parent_init_top_level_only(self, repo):
        # test_sub 只 import pkg.base：pkg/__init__ 的模块级代码会跑，get_heavy 里的懒导入不会。
        assert "tests/test_sub.py" not in _l0(["pkg/heavy.py"])

    def test_using_the_package_itself_pulls_its_lazy_imports(self, repo):
        # from pkg import get_heavy：调用的正是那个懒导入 heavy 的函数。
        assert "tests/test_pkg_attr.py" in _l0(["pkg/heavy.py"])

    def test_one_lazy_hop_is_followed(self, repo):
        assert "tests/test_lazy.py" in _l0(["pkg/deep.py"])

    def test_importlib_literal_is_a_dependency(self, repo):
        assert "tests/test_dyn.py" in _l0(["pkg/heavy.py"])

    def test_patch_target_string_in_a_test_is_a_dependency(self, repo):
        assert "tests/test_patch.py" in _l0(["pkg/heavy.py"])

    def test_script_path_string_in_a_test_is_a_dependency(self, repo):
        assert "tests/test_script.py" in _l0(["pkg/heavy.py"])

    def test_strings_in_production_code_are_not_dependencies(self, repo):
        # pkg/doc.py 的一句注释里提到了 pkg.heavy 与 scripts/tool.py —— 那不是依赖。
        assert "tests/test_doc.py" not in _l0(["pkg/heavy.py"])

    def test_conftest_scope_propagates(self, repo):
        assert "tests/sub/test_in_scope.py" in _l0(["pkg/base.py"])

    def test_non_python_file_is_read_by_whoever_names_it(self, repo):
        assert "tests/test_reads_json.py" in _l0(["settings.json"])

    def test_changed_test_file_selects_itself(self, repo):
        assert "tests/test_doc.py" in _l0(["tests/test_doc.py"])


# ---------------------------------------------------------------------------
# B. 已知盲区
# ---------------------------------------------------------------------------


class TestKnownBlindSpot:
    def test_two_lazy_hops_are_not_selected(self, repo):
        """test_lazy → lazy_user.f 懒导入 deep → deep.g 再懒导入 deeper：静态选不中。

        这是本选择器写明的盲区（见模块文档），不是 bug；其实际漏选率由
        scripts/replay_verification_ladder.py 的故障注入回放量出来。
        """
        assert "tests/test_lazy.py" not in _l0(["pkg/deeper.py"])

    def test_when_nothing_is_selected_l0_says_it_cannot_be_trusted(self, repo):
        plan = vl.select_affected_tests(["pkg/deeper.py"], vl.build_dependency_index(use_cache=False))
        assert plan.tests == ()
        assert not plan.l0_trustworthy and "什么都证明不了" in plan.escalate_reason
        assert vl.recommended_level(plan) == "L2"


# ---------------------------------------------------------------------------
# C. 升档
# ---------------------------------------------------------------------------


class TestEscalation:
    @pytest.mark.parametrize(
        "path", ["pytest.ini", "pyproject.toml", "requirements.txt", "requirements-dev.txt", ".github/workflows/ci.yml"]
    )
    def test_global_configuration_makes_l0_untrustworthy(self, repo, path):
        plan = vl.select_affected_tests([path], vl.build_dependency_index(use_cache=False))
        assert "全局配置" in plan.escalate_reason

    def test_commands_per_level(self, repo):
        plan = vl.select_affected_tests(["pkg/base.py"], vl.build_dependency_index(use_cache=False))
        l0, l1, l2, l3 = (plan.commands(level) for level in vl.LEVELS)
        assert len(l0) == 1 and l0[0].startswith("pytest ") and "tests/test_base.py" in l0[0]
        assert l1[0] == l0[0] and any("check_verdict_independence" in c for c in l1)
        assert any(c.startswith("pytest tests/") for c in l2)
        assert l3 == []
        for command in l0 + [c for c in l2 if c.startswith("pytest")]:
            assert ev.normalize_verification_command(command)[0] is not None, command

    def test_every_guard_command_is_a_recognized_verifier_in_the_real_repo(self):
        for script in vl.STATIC_GUARD_SCRIPTS:
            argv, why = ev.normalize_verification_command(f"python {script}")
            assert argv is not None, f"L1 的守卫门必须是认得的验证器：{script}（{why}）"

    def test_unknown_level_is_rejected(self, repo):
        plan = vl.select_affected_tests(["pkg/base.py"], vl.build_dependency_index(use_cache=False))
        with pytest.raises(ValueError):
            plan.commands("L9")


# ---------------------------------------------------------------------------
# D. 与 CI 分片同一套算法
# ---------------------------------------------------------------------------


def test_shard_assignment_matches_the_ci_shard_script():
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import ci_test_shard
    finally:
        sys.path.pop(0)
    files = ci_test_shard.all_test_files()[:200]
    for index in range(1, vl.CI_SHARD_COUNT + 1):
        for f in ci_test_shard.shard(files, index, vl.CI_SHARD_COUNT):
            assert vl._shard_of(f) == index


# ---------------------------------------------------------------------------
# E. 真实仓库的历史回放
# ---------------------------------------------------------------------------

#: 真实发生过的变红：提交 443cbf2（M1）改了这两个文件，这两份测试里有 5 条变红。
_M1_CHANGED = ("core/self_improvement.py", "core/openclawd.py")
_M1_WENT_RED = ("tests/test_pr6_self_healing_engineering_loop.py", "tests/test_knowledge_read_tool_surface.py")


def test_real_history_m1_red_tests_are_selected():
    plan = vl.select_affected_tests(_M1_CHANGED)
    assert plan.l0_trustworthy
    assert set(_M1_WENT_RED) <= set(plan.tests)


def test_real_repository_selection_is_selective():
    """L0 的全部价值在于它比全量小：一个只被自己测试覆盖的模块，不应拉起半个仓库。"""
    index = vl.build_dependency_index()
    plan = vl.select_affected_tests(["core/verdict_independence.py"], index)
    assert "tests/test_verdict_independence.py" in plan.tests
    assert len(plan.tests) < len(index.test_files) // 10


# ---------------------------------------------------------------------------
# F. 端到端：harness 按 target_files 跑阶梯
# ---------------------------------------------------------------------------


class TestLadderInTheEngineeringLoop:
    def _loop_at_apply(self, targets):
        from core.self_improvement import SelfHealingLoop

        loop = SelfHealingLoop()
        p = loop.submit_diagnosis("base constant", source="test")
        loop.attach_context(p.proposal_id, {})
        loop.plan_patch(p.proposal_id, "tweak X", list(targets))
        loop.apply_patch(p.proposal_id)
        return loop, p.proposal_id

    def test_ladder_l0_runs_the_affected_tests_and_is_trusted(self, repo):
        loop, pid = self._loop_at_apply(["pkg/base.py"])
        result = loop.validate(pid, command="ladder:L0")
        assert result["success"] is True, result.get("error")
        assert result["trust_level"] == "trusted"
        ran = " ".join(" ".join(c) for c in result["commands"])
        # 导入任何 pkg.* 都会执行 pkg/__init__ 的模块级代码，而它导入了 base —— 所以它们全受影响；
        # 不导入 pkg 的那一份不受影响。
        assert "tests/test_base.py" in ran and "tests/test_doc.py" in ran
        assert "tests/test_reads_json.py" not in ran

    def test_ladder_l0_surfaces_a_real_failure(self, repo):
        (repo / "pkg" / "base.py").write_text("X = 99\n", encoding="utf-8")
        loop, pid = self._loop_at_apply(["pkg/base.py"])
        result = loop.validate(pid, command="ladder:L0")
        assert result["success"] is False and result["exit_code"] == 1

    def test_running_an_unrelated_passing_test_is_not_trusted(self, repo):
        # 改的是 heavy；test_sub 只 import pkg.base（pkg/__init__ 的懒导入不触发），与 heavy 无关。
        loop, pid = self._loop_at_apply(["pkg/heavy.py"])
        result = loop.validate(pid, command="pytest tests/test_sub.py -q -p no:cacheprovider")
        assert result["exit_code"] == 0
        assert result["trust_level"] == "provisional" and result["success"] is False
        assert "都不依赖 target_files" in result["error"]

    def test_running_a_related_test_explicitly_is_trusted(self, repo):
        loop, pid = self._loop_at_apply(["pkg/heavy.py"])
        result = loop.validate(pid, command="pytest tests/test_dyn.py -q -p no:cacheprovider")
        assert result["trust_level"] == "trusted"

    def test_ladder_without_target_files_proves_nothing(self, repo):
        loop, pid = self._loop_at_apply([])
        result = loop.validate(pid, command="ladder:L0")
        assert result["trust_level"] == "quarantine" and "target_files" in result["error"]

    def test_ladder_l3_is_ci_only(self, repo):
        loop, pid = self._loop_at_apply(["pkg/base.py"])
        result = loop.validate(pid, command="ladder:L3")
        assert result["success"] is False and "CI" in result["error"]

    def test_untrustworthy_l0_refuses_and_points_upward(self, repo):
        loop, pid = self._loop_at_apply(["pkg/deeper.py"])
        result = loop.validate(pid, command="ladder:L0")
        assert result["success"] is False and "ladder:L2" in result["error"]


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------


def test_cli_prints_l0_and_flags_untrustworthy_plans():
    import subprocess

    run = dict(cwd=REPO_ROOT, capture_output=True, text=True, timeout=120)
    ok = subprocess.run([sys.executable, "scripts/select_affected_tests.py", "core/verdict_independence.py"], **run)
    assert ok.returncode == 0 and "tests/test_verdict_independence.py" in ok.stdout
    esc = subprocess.run([sys.executable, "scripts/select_affected_tests.py", "pytest.ini"], **run)
    assert esc.returncode == 2 and "全局配置" in esc.stderr


LAZY_PACKAGE_REPO = {
    "runtime/scratch.py": "import lazypkg.source\n",  # 仓库根目录下的 runtime/ 是运行期数据，不进图
    "lazypkg/__init__.py": """
        from importlib import import_module

        _SOURCES = (("lazypkg.source", ("VALUE",)),)

        def __getattr__(name):
            for module, names in _SOURCES:
                if name in names:
                    return getattr(import_module(module), name)
            raise AttributeError(name)
    """,
    "lazypkg/source.py": "VALUE = 1\n",
    "lazypkg/sibling.py": "OTHER = 2\n",
    "core/__init__.py": "",
    "core/runtime/__init__.py": "",
    "core/runtime/sink.py": "EVENTS = []\n",
    "tests/test_uses_lazy_name.py": "from lazypkg import VALUE\n\ndef test_v():\n    assert VALUE == 1\n",
    "tests/test_uses_submodule.py": "from lazypkg.sibling import OTHER\n\ndef test_o():\n    assert OTHER == 2\n",
    "tests/test_nested_runtime.py": "from core.runtime.sink import EVENTS\n\ndef test_e():\n    assert EVENTS == []\n",
}


@pytest.fixture
def lazy_repo(tmp_path, monkeypatch):
    for rel, body in LAZY_PACKAGE_REPO.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    monkeypatch.setattr(vl, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(vl, "_CACHE_PATH", tmp_path / "runtime" / "idx.json")
    return tmp_path


def test_pep562_lazy_package_names_are_one_hop_edges(lazy_repo):
    """``from lazypkg import VALUE`` 依赖 VALUE 的来源模块；只导入子模块的不依赖它。"""
    assert _l0(["lazypkg/source.py"]) == {"tests/test_uses_lazy_name.py"}


def test_only_the_root_runtime_dir_is_excluded(lazy_repo):
    """``core/runtime/`` 是真实的包 —— 按名字全局排除 runtime 会让它从依赖图里消失（改它选出 0 个测试）。"""
    index = vl.build_dependency_index(use_cache=False)
    assert "core/runtime/sink.py" in index.files
    assert "runtime/scratch.py" not in index.files
    assert _l0(["core/runtime/sink.py"]) == {"tests/test_nested_runtime.py"}


def test_real_nested_runtime_package_selects_its_tests():
    plan = vl.select_affected_tests(["core/runtime/runtime_observability_sink.py"], vl.build_dependency_index())
    assert plan.tests, "core/runtime/ 下的模块必须选得出测试"
