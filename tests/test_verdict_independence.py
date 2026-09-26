"""裁决不得由被裁决者自己报 —— core/verdict_independence.py 的判据测试。

A. 每个签名在最小样例上抓得到，在最近似的正当写法上不误报
B. S3 按数据流判：改参数名绕不过去
C. S4 按推导范围判：新模块一写裁决就红，豁免表不许腐烂
D. 仓库现状：扫描结果与存量清单**完全相等**；门的退出码
E. git 回放：把扫描器指向修复前的真实代码，它必须抓到那四处 —— 抓不到已知缺陷的守卫等于没有守卫
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import core.verdict_independence as vi
from core.verdict_independence import (
    KNOWN_UNRESOLVED,
    VERDICT_WRITER_EXEMPTIONS,
    scan_repository,
    scan_source_for_self_certification,
    stale_known_entries,
    unresolved_findings,
)

REPO_ROOT = Path(__file__).resolve().parents[1]

# 仍然带着 engineer__validate 自报成绩那条链的提交（M1 之前的 main）。
_PRE_M1_COMMIT = "f49d0c7"


def _git_show(ref: str, path: str) -> str:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], cwd=REPO_ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"git object {ref}:{path} unavailable in this checkout")
    return proc.stdout


def _sigs(source: str) -> list[str]:
    return [f.signature for f in scan_source_for_self_certification(textwrap.dedent(source), "sample.py")]


# ---------------------------------------------------------------------------
# A. 各签名的正例与反例
# ---------------------------------------------------------------------------


class TestS1ToolSchema:
    def test_boolean_success_field_in_tool_parameters_is_flagged(self):
        src = """
        TOOLS = [{"type": "function", "function": {
            "name": "x__validate",
            "parameters": {"type": "object", "properties": {
                "proposal_id": {"type": "string"},
                "passed": {"type": "boolean", "description": "通过了吗"},
            }},
        }}]
        """
        findings = scan_source_for_self_certification(textwrap.dedent(src), "s.py")
        assert [f.signature for f in findings] == ["S1"]
        assert findings[0].symbol == "x__validate.passed"

    def test_anthropic_style_input_schema_is_also_covered(self):
        src = """
        T = {"name": "t", "input_schema": {"properties": {"verified": {"type": "boolean"}}}}
        """
        assert _sigs(src) == ["S1"]

    def test_non_boolean_field_with_same_name_is_not_flagged(self):
        # 一条要跑的命令、一段说明 —— 模型提议什么是允许的。
        src = """
        T = {"name": "t", "parameters": {"properties": {
            "passed": {"type": "string"},
            "command": {"type": "string"},
        }}}
        """
        assert _sigs(src) == []

    def test_boolean_field_that_is_not_a_verdict_is_not_flagged(self):
        src = """
        T = {"name": "t", "parameters": {"properties": {"dry_run": {"type": "boolean"}}}}
        """
        assert _sigs(src) == []

    def test_tool_result_dict_is_not_a_schema(self):
        src = """
        def f():
            return {"success": True, "passed": False}
        """
        assert _sigs(src) == []


class TestS2ReadFromModelArguments:
    def test_get_with_default_true_is_flagged(self):
        src = """
        def dispatch(action, arguments):
            passed = bool(arguments.get("passed", True))
            return passed
        """
        findings = scan_source_for_self_certification(textwrap.dedent(src), "s.py")
        assert [f.signature for f in findings] == ["S2"]
        assert findings[0].symbol == "dispatch:passed"

    def test_subscript_read_is_flagged(self):
        src = """
        def dispatch(tool_args):
            return tool_args["verified"]
        """
        assert _sigs(src) == ["S2"]

    def test_reading_a_non_verdict_field_is_fine(self):
        src = """
        def dispatch(arguments):
            return arguments.get("proposal_id", "")
        """
        assert _sigs(src) == []

    def test_reading_success_from_a_result_dict_is_fine(self):
        # 读**执行结果**的 success 是正当的：那是 harness 的观测，不是模型的声明。
        src = """
        def consume(result):
            return result.get("success", False)
        """
        assert _sigs(src) == []


class TestS3VerdictFromParameter:
    def test_parameter_written_into_verdict_attribute_is_flagged(self):
        src = """
        def validate(self, proposal_id, passed: bool = True):
            proposal = self.lookup(proposal_id)
            proposal.validation_passed = passed
        """
        findings = scan_source_for_self_certification(textwrap.dedent(src), "s.py")
        assert [f.signature for f in findings] == ["S3"]
        assert findings[0].symbol == "validate:validation_passed<-passed"

    def test_bool_wrapper_does_not_hide_it(self):
        src = """
        def validate(self, p, ok):
            p.verified = bool(ok)
        """
        assert _sigs(src) == ["S3"]

    def test_computed_verdict_is_fine(self):
        src = """
        def validate(self, proposal, exit_code):
            trust = classify(exit_code)
            proposal.validation_passed = trust is TRUSTED
        """
        assert _sigs(src) == []

    def test_constructor_and_deserialisation_are_not_adjudication(self):
        src = """
        class R:
            def __init__(self, validation_passed):
                self.validation_passed = validation_passed
            @classmethod
            def from_dict(cls, validation_passed):
                r = cls(None)
                r.validation_passed = validation_passed
                return r
        """
        assert _sigs(src) == []


class TestParsing:
    def test_unparseable_source_is_not_fatal(self):
        assert scan_source_for_self_certification("def (:", "broken.py") == []


# ---------------------------------------------------------------------------
# B. 按数据流判：改名绕不过去
# ---------------------------------------------------------------------------


class TestRenameResistance:
    @pytest.mark.parametrize("param", ["passed", "claimed_ok", "llm_said_it_worked", "x"])
    def test_any_parameter_name_flowing_into_verdict_is_caught(self, param):
        src = f"""
        def validate(self, proposal, {param}):
            proposal.validation_passed = {param}
        """
        assert _sigs(src) == ["S3"]


# ---------------------------------------------------------------------------
# C. S4：推导范围与豁免表
# ---------------------------------------------------------------------------


class TestS4DerivedScope:
    def _repo(self, tmp_path, monkeypatch, files: dict[str, str]):
        for rel, body in files.items():
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(textwrap.dedent(body), encoding="utf-8")
        monkeypatch.setattr(vi, "REPO_ROOT", tmp_path)

    def test_new_verdict_writer_without_enforcement_is_flagged(self, tmp_path, monkeypatch):
        self._repo(
            tmp_path,
            monkeypatch,
            {"core/new_loop.py": """
                def finish(record, trust):
                    record.trust_level = trust.upgrade()
                """},
        )
        findings = scan_repository(("core",))
        assert [(f.signature, f.path) for f in findings] == [("S4", "core/new_loop.py")]

    def test_writer_that_goes_through_the_enforcement_function_is_fine(self, tmp_path, monkeypatch):
        self._repo(
            tmp_path,
            monkeypatch,
            {"core/new_loop.py": """
                from core.execution_evidence_model import classify_execution_evidence
                def finish(record, state):
                    record.trust_level = classify_execution_evidence(state)
                """},
        )
        assert scan_repository(("core",)) == []

    def test_every_exemption_still_names_a_real_verdict_writer(self):
        """豁免表不许腐烂：豁免了一个不存在、或已经不写裁决的模块，就是在给空气开证明。"""
        for rel in VERDICT_WRITER_EXEMPTIONS:
            path = REPO_ROOT / rel
            assert path.is_file(), f"豁免的模块不存在：{rel}"
            import ast

            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert vi._writes_verdict_attribute(tree) is not None, f"{rel} 已经不写裁决属性，豁免应删除"

    def test_every_exemption_carries_a_reason(self):
        for rel, reason in VERDICT_WRITER_EXEMPTIONS.items():
            assert len(reason) >= 20, f"{rel} 的豁免理由太短，写不出理由就不该豁免"


# ---------------------------------------------------------------------------
# D. 仓库现状
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def live_findings():
    return scan_repository()


class TestLiveRepository:
    def test_scan_matches_the_known_list_exactly(self, live_findings):
        """守卫在当前仓上必须扫出 engineer__validate 那条链 —— 扫不出即守卫写错。

        同时不许多出一条：多出来的就是新缺陷。
        """
        found = {f.key for f in live_findings}
        assert found == set(KNOWN_UNRESOLVED)

    def test_no_unresolved_and_no_stale_entries(self, live_findings):
        assert unresolved_findings(live_findings) == []
        assert stale_known_entries(live_findings) == []

    def test_gate_script_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, "scripts/check_verdict_independence.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_file_mode_flags_a_file_outside_the_repo(self, tmp_path):
        bad = tmp_path / "patch.py"
        bad.write_text('def d(arguments):\n    return arguments.get("passed", True)\n', encoding="utf-8")
        good = tmp_path / "ok.py"
        good.write_text("def d(arguments):\n    return arguments.get('command')\n", encoding="utf-8")
        script = [sys.executable, "scripts/check_verdict_independence.py"]
        run = dict(cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
        assert subprocess.run(script + ["--file", str(bad)], **run).returncode == 1
        assert subprocess.run(script + ["--file", str(good)], **run).returncode == 0

    @pytest.mark.slow
    def test_text_prefilter_never_skips_a_real_hit(self):
        """预筛是一次优化，不许丢东西：被它跳过的每个文件，完整扫描也必须为空。"""
        skipped_with_hits = []
        for path in vi._iter_python_files(vi.DEFAULT_SCAN_ROOTS):
            source = path.read_text(encoding="utf-8", errors="replace")
            if vi._may_contain_signature(source):
                continue
            if scan_source_for_self_certification(source, str(path)):
                skipped_with_hits.append(str(path))
        assert skipped_with_hits == []

    def test_json_report_is_serialisable_and_complete(self):
        import json

        report = vi.build_verdict_independence_report()
        text = json.dumps(report, ensure_ascii=False)
        assert "PROPOSER_MUST_NOT_SELF_CERTIFY" in text
        assert set(report) >= {"findings", "unresolved", "stale_known_entries", "exemptions"}


# ---------------------------------------------------------------------------
# E. git 回放
# ---------------------------------------------------------------------------


class TestRealHistory:
    def test_guard_catches_the_real_defect_in_openclawd(self):
        src = _git_show(_PRE_M1_COMMIT, "core/openclawd.py")
        keys = {f.key for f in scan_source_for_self_certification(src, "core/openclawd.py")}
        assert ("S1", "core/openclawd.py", "engineer__validate.passed") in keys
        assert ("S2", "core/openclawd.py", "_dispatch_engineer_tool:passed") in keys

    def test_guard_catches_the_real_defect_in_self_improvement(self):
        import ast

        src = _git_show(_PRE_M1_COMMIT, "core/self_improvement.py")
        keys = {f.key for f in scan_source_for_self_certification(src, "core/self_improvement.py")}
        assert ("S3", "core/self_improvement.py", "validate:validation_passed<-passed") in keys
        tree = ast.parse(src)
        assert vi._writes_verdict_attribute(tree) is not None
        assert not vi._references_name(tree, vi.CANONICAL_ENFORCEMENT_FUNCTION), "修复前它不走执法函数（S4）"

    def test_same_files_are_clean_now(self):
        for rel in ("core/openclawd.py", "core/self_improvement.py"):
            src = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert scan_source_for_self_certification(src, rel) == []
