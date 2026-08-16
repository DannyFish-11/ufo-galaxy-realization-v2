"""tests/test_semantic_anchoring_stage2.py
==========================================
Tests for the decision-path anchoring doctrine and its executable guard (Stage 2).

判据
----
一次读取，如果它的结果会**改变控制流**——选策略、选设备、判权限、决定是否执行
动作——必须走对象层做确定性查询。如果结果只是**进入 prompt 供 LLM 参考**，
走检索是对的，也应该继续走。**该换的是决策路径，不是检索能力。**

为什么要有守卫而不只是哨兵
--------------------------
Stage 0 修掉的缺陷有一个可检测的具体签名:同一个函数里先 ``recall(...)`` 拿回
按相似度排序的文本,再用 ``re.search(...)`` 把结构抠出来做决策。哨兵是文档、
会被绕过;守卫是能在 CI 上失败的东西。

本测试最关键的一条是 C01——把守卫指向 **Stage 0 之前的真实历史代码**,
要求它确实抓得到那个已知缺陷。一道抓不到已知缺陷的守卫等于没有守卫。

Coverage matrix
---------------
Group A — Policy sentinels
  A01. SEMANTIC_ANCHORING_IS_AUTHORITY exists and disclaims doing any deciding.
  A02. POLICY_1 requires object-layer resolution for control flow.
  A03. POLICY_2 forbids parsing structure out of retrieved prose.
  A04. POLICY_3 protects legitimate retrieval from being deleted.
  A05. Decision-path module list is explicit and non-empty.
  A06. The audit record covers advisory / write / capability-gate uses.

Group B — Detector unit behaviour
  B01. Retrieval alone is not a violation.
  B02. Regex alone is not a violation.
  B03. str.split() is not counted as structure extraction.
  B04. Retrieval + re.search in one function IS a violation.
  B05. Split across two functions is not a violation.
  B06. Unparseable source yields no violations instead of raising.
  B07. Violation.describe() names the function and points at POLICY_2.
  B08. All configured retrieval names are detected.

Group C — Guard validated against real history
  C01. Scanning the pre-Stage-0 execution_planner catches
       _experience_strategy_adjust — the known, real defect.
  C02. The same file after Stage 0 is clean.

Group D — Live repository state
  D01. All decision-path modules currently scan clean.
  D02. build_audit_report() reports clean and is JSON-safe.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from core.semantic_anchoring import (
    AUDITED_RETRIEVAL_CALL_SITES,
    DECISION_PATH_MODULES,
    RETRIEVAL_CALL_NAMES,
    AnchoringViolation,
    build_audit_report,
    scan_decision_paths,
    scan_source_for_prose_derived_structure,
)

# Commit that still contained the superseded prose/regex decision path.
_PRE_STAGE0_COMMIT = "d219b79"
_PLANNER_PATH = "core/agent/execution_planner.py"


def _git_show(ref: str, path: str) -> str:
    proc = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"git object {ref}:{path} unavailable in this checkout")
    return proc.stdout


# ---------------------------------------------------------------------------
# Group A — Policy sentinels
# ---------------------------------------------------------------------------


class TestGroupAPolicies:
    def test_a01_authority(self):
        from core.semantic_anchoring import SEMANTIC_ANCHORING_IS_AUTHORITY

        text = SEMANTIC_ANCHORING_IS_AUTHORITY
        assert "AUTHORITY" in text
        # The doctrine module must not itself be a participant in decisions.
        assert "does not itself read, retrieve, or decide" in text

    def test_a02_object_layer_policy(self):
        from core.semantic_anchoring import DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY

        text = DECISION_PATHS_MUST_USE_OBJECT_LAYER_POLICY
        assert "POLICY_1" in text
        assert "control flow" in text
        assert "NEVER authoritative" in text

    def test_a03_advisory_only_policy(self):
        from core.semantic_anchoring import RETRIEVAL_IS_ADVISORY_ONLY_POLICY

        text = RETRIEVAL_IS_ADVISORY_ONLY_POLICY
        assert "POLICY_2" in text
        assert "MUST NOT parse structure back out of retrieved prose" in text

    def test_a04_retrieval_capability_protected(self):
        """The doctrine narrows where retrieval is believed, not whether it exists."""
        from core.semantic_anchoring import RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY

        text = RETRIEVAL_CAPABILITY_IS_NOT_THE_DEFECT_POLICY
        assert "POLICY_3" in text
        assert "MUST NOT be removed" in text
        assert "Node_105" in text

    def test_a05_decision_path_list_is_explicit(self):
        assert DECISION_PATH_MODULES
        assert "core.agent.execution_planner" in DECISION_PATH_MODULES
        # A whole-repo scan would drown in false positives and get switched off.
        assert len(DECISION_PATH_MODULES) < 25

    def test_a06_audit_covers_each_use_kind(self):
        kinds = {site["use"] for site in AUDITED_RETRIEVAL_CALL_SITES}
        assert {"advisory", "write", "capability-gate"} <= kinds
        assert all(site["verdict"].startswith("compliant") for site in AUDITED_RETRIEVAL_CALL_SITES)


# ---------------------------------------------------------------------------
# Group B — Detector behaviour
# ---------------------------------------------------------------------------


class TestGroupBDetector:
    def test_b01_retrieval_alone_is_fine(self):
        src = "def f(um, q):\n    hits = um.recall(q, top_k=3)\n    return [h.content for h in hits]\n"
        assert scan_source_for_prose_derived_structure(src) == []

    def test_b02_regex_alone_is_fine(self):
        src = "import re\ndef g(s):\n    return re.search(r'x(\\\\d+)', s)\n"
        assert scan_source_for_prose_derived_structure(src) == []

    def test_b03_str_split_is_not_structure_extraction(self):
        """`some_string.split()` is ordinary string work, not re-deriving structure."""
        src = "def h(um, q):\n    hits = um.recall(q)\n    return hits[0].content.split(',')\n"
        assert scan_source_for_prose_derived_structure(src) == []

    def test_b04_retrieval_plus_regex_is_a_violation(self):
        src = (
            "import re\n"
            "def bad(um, msg):\n"
            "    for h in um.recall(msg, top_k=8):\n"
            "        m = re.search(r'strategy\\\\[(.+?)\\\\]', h.content)\n"
            "        if m:\n"
            "            return m.group(1)\n"
        )
        found = scan_source_for_prose_derived_structure(src, "synthetic")
        assert len(found) == 1
        assert found[0].function == "bad"

    def test_b05_split_across_functions_is_not_a_violation(self):
        """Either half alone is legitimate; only the combination is the defect."""
        src = (
            "import re\n"
            "def fetch(um, q):\n"
            "    return um.recall(q)\n"
            "def parse(text):\n"
            "    return re.search(r'a(b)c', text)\n"
        )
        assert scan_source_for_prose_derived_structure(src) == []

    def test_b06_unparseable_source_is_not_fatal(self):
        """A guard that can crash the build on a syntax quirk gets disabled."""
        assert scan_source_for_prose_derived_structure("def broken(:\n  pass\n") == []

    def test_b07_describe_points_at_the_policy(self):
        v = AnchoringViolation(
            module="m", function="fn", lineno=7, retrieval_calls=["recall"], extraction_calls=["search"]
        )
        text = v.describe()
        assert "m.fn" in text and "line 7" in text
        assert "SEMANTIC_ANCHORING::POLICY_2" in text

    @pytest.mark.parametrize("name", sorted(RETRIEVAL_CALL_NAMES))
    def test_b08_every_configured_retrieval_name_is_detected(self, name):
        src = f"import re\ndef fn(o, q):\n    r = o.{name}(q)\n    return re.findall('x', str(r))\n"
        assert len(scan_source_for_prose_derived_structure(src)) == 1


# ---------------------------------------------------------------------------
# Group C — Validated against real history
# ---------------------------------------------------------------------------


class TestGroupCRealHistory:
    def test_c01_guard_catches_the_known_real_defect(self):
        """The decisive test: a guard that misses the known defect is not a guard.

        Points the scanner at the actual pre-Stage-0 source and requires that it
        finds _experience_strategy_adjust — the function whose prose/regex decision
        path Stage 0 removed.
        """
        source = _git_show(_PRE_STAGE0_COMMIT, _PLANNER_PATH)
        found = scan_source_for_prose_derived_structure(source, "execution_planner@pre-stage0")
        names = {v.function for v in found}
        assert "_experience_strategy_adjust" in names, (
            "the guard failed to detect the very defect it exists to prevent; " f"found instead: {sorted(names)}"
        )

    def test_c02_same_file_is_clean_after_stage0(self):
        import inspect

        import core.agent.execution_planner as mod

        found = scan_source_for_prose_derived_structure(inspect.getsource(mod), "execution_planner@head")
        assert found == [], [v.describe() for v in found]


# ---------------------------------------------------------------------------
# Group D — Live repository state
# ---------------------------------------------------------------------------


class TestGroupDLiveState:
    def test_d01_decision_paths_are_clean(self):
        violations = scan_decision_paths()
        assert violations == [], "\n".join(v.describe() for v in violations)

    def test_d02_audit_report_is_clean_and_json_safe(self):
        report = build_audit_report()
        json.dumps(report)
        assert report["clean"] is True
        assert report["violations"] == []
        assert report["scanned_modules"]
