"""M1 验收：验证由 harness 跑，结果由 harness 读，裁决由执法函数下。

这里的用例都跑**真的子进程**（在临时目录里放一个真的测试文件，让 harness 真的去跑
pytest），不替换 run_verification —— 状态机的单元测试在 test_pr6_* 里，这一份证明的是
整条链在真实世界里成立。

A. 命令规范化：白名单、必带参数、禁止改验证器自身的参数
B. 观测 → 证据状态 → 信任级别（表驱动）
C. 验收（架构书 R1）：模型报 passed=true 但实跑失败 → divergence，且不推进阶段
D. 验收（架构书 R2）：复现原失败 → 修正 → 同一检查转绿 → validated 进知识库
E. 无证据不受理：原文落不下盘时，退出码 0 也只是 provisional
F. openclawd 派发：验证在线程里跑，不堵事件循环
"""

from __future__ import annotations

import asyncio
import sys
import textwrap
from unittest.mock import MagicMock, patch

import pytest

import core.context_archive as context_archive
from core.engineering_verification import (
    VerificationObservation,
    normalize_verification_command,
    observation_to_evidence,
    run_verification,
)
from core.execution_evidence_model import EvidenceTrustLevel, ExecutionEvidenceState, classify_execution_evidence
from core.self_improvement import EngineeringStage, SelfHealingLoop


@pytest.fixture(autouse=True)
def _isolated_archive(tmp_path, monkeypatch):
    """原文归档落到临时目录，不写仓库的 runtime/。"""
    monkeypatch.setattr(context_archive, "_ROOT", tmp_path / "context_archive")


def _write_test(directory, body: str) -> str:
    path = directory / "test_subject.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return str(path)


PASSING = """
def test_ok():
    assert 1 + 1 == 2
"""

FAILING = """
def test_bug():
    assert 1 + 1 == 3
"""


def _loop_at_apply(loop: SelfHealingLoop, target: str = "") -> str:
    p = loop.submit_diagnosis("arithmetic is wrong", source="test")
    loop.attach_context(p.proposal_id, {})
    loop.plan_patch(p.proposal_id, "fix the arithmetic", [target] if target else [])
    loop.apply_patch(p.proposal_id)
    return p.proposal_id


# ---------------------------------------------------------------------------
# A. 命令规范化
# ---------------------------------------------------------------------------


class TestNormalize:
    def test_bare_pytest_becomes_a_module_call_on_this_interpreter(self):
        argv, why = normalize_verification_command("pytest tests/x.py -q")
        assert why == ""
        assert argv == (sys.executable, "-m", "pytest", "tests/x.py", "-q")

    def test_python_dash_m_is_accepted(self):
        argv, _ = normalize_verification_command("python -m flake8 core/")
        assert argv[:3] == (sys.executable, "-m", "flake8")

    def test_repo_guard_script_is_accepted_and_resolved(self):
        argv, why = normalize_verification_command("python scripts/check_verdict_independence.py")
        assert why == ""
        assert argv[0] == sys.executable and argv[1].endswith("scripts/check_verdict_independence.py")

    def test_nonexistent_guard_script_is_rejected(self):
        argv, why = normalize_verification_command("python scripts/check_does_not_exist.py")
        assert argv is None and "不存在" in why

    @pytest.mark.parametrize("cmd", ["true", "echo ok", "python -c 'print(1)'", "bash -c 'exit 0'", "rm -rf /"])
    def test_things_that_exit_zero_without_checking_anything_are_not_verifiers(self, cmd):
        argv, why = normalize_verification_command(cmd)
        assert argv is None and "不是认得的验证器" in why

    def test_formatter_without_check_flag_is_rejected(self):
        # 不带 --check 的 black 是改文件，不是验证。
        assert normalize_verification_command("black core/")[0] is None
        assert normalize_verification_command("black --check core/")[0] is not None
        assert normalize_verification_command("isort core/")[0] is None
        assert normalize_verification_command("isort --check-only core/")[0] is not None

    @pytest.mark.parametrize("flag", ["--update-baseline", "--fix", "--snapshot-update", "--update-baseline=1"])
    def test_flags_that_rewrite_the_verifier_are_rejected(self, flag):
        argv, why = normalize_verification_command(f"python scripts/check_verdict_independence.py {flag}")
        assert argv is None and "改判卷标准" in why

    @pytest.mark.parametrize("cmd", [None, "", "   "])
    def test_no_command_means_nothing_was_verified(self, cmd):
        argv, why = normalize_verification_command(cmd)
        assert argv is None and "什么都没验证" in why

    def test_native_verifier_prefix_does_not_match_under_python(self):
        assert normalize_verification_command("python node --test")[0] is None


# ---------------------------------------------------------------------------
# B. 观测 → 证据 → 信任级别
# ---------------------------------------------------------------------------


def _obs(**kw) -> VerificationObservation:
    base = dict(
        command=(sys.executable, "-m", "pytest"),
        requested="pytest",
        recognized_verifier=True,
        executed=True,
        exit_code=0,
        timed_out=False,
        duration_s=0.1,
        evidence_ref="context_archive:x#1",
    )
    base.update(kw)
    return VerificationObservation(**base)


@pytest.mark.parametrize(
    "obs, state, trust",
    [
        (_obs(), ExecutionEvidenceState.locally_executed, EvidenceTrustLevel.trusted),
        (_obs(evidence_ref=""), ExecutionEvidenceState.locally_executed, EvidenceTrustLevel.provisional),
        (_obs(exit_code=1), ExecutionEvidenceState.failed, EvidenceTrustLevel.provisional),
        (_obs(exit_code=5), ExecutionEvidenceState.completed_degraded, EvidenceTrustLevel.quarantine),
        (_obs(timed_out=True, exit_code=None), ExecutionEvidenceState.interrupted, EvidenceTrustLevel.provisional),
        (
            _obs(executed=False, exit_code=None, evidence_ref=""),
            ExecutionEvidenceState.planned_not_started,
            EvidenceTrustLevel.quarantine,
        ),
    ],
    ids=["pass", "pass-no-archive", "fail", "no-tests-collected", "timeout", "not-run"],
)
def test_observation_to_trust_table(obs, state, trust):
    got_state, chain = observation_to_evidence(obs)
    assert got_state is state
    assert classify_execution_evidence(got_state, truth_chain_complete=chain) is trust


def test_only_a_pass_with_archived_evidence_is_trusted():
    """trusted 的全集只有一格：认得的验证器 + 真的跑了 + 退出码 0 + 原文落盘。"""
    trusted = []
    for recognized in (True, False):
        for executed in (True, False):
            for code in (0, 1, 5):
                for ref in ("context_archive:x#1", ""):
                    o = _obs(recognized_verifier=recognized, executed=executed, exit_code=code, evidence_ref=ref)
                    st, chain = observation_to_evidence(o)
                    if classify_execution_evidence(st, truth_chain_complete=chain) is EvidenceTrustLevel.trusted:
                        trusted.append((recognized, executed, code, bool(ref)))
    assert trusted == [(True, True, 0, True)]


# ---------------------------------------------------------------------------
# 真实子进程
# ---------------------------------------------------------------------------


class TestRealRuns:
    def test_passing_run_is_archived_and_retrievable(self, tmp_path):
        test_file = _write_test(tmp_path, PASSING)
        obs = run_verification(f"pytest {test_file} -q -p no:cacheprovider", proposal_id="p1")
        assert obs.executed and obs.exit_code == 0
        assert obs.evidence_ref.startswith("context_archive:engineering-verification:p1#")
        session, seg = obs.evidence_ref.split(":", 1)[1].rsplit("#", 1)
        segment = context_archive.load_segment(session, int(seg))
        assert segment is not None and "1 passed" in segment["entries"][0]["content"]

    def test_failing_run_reports_nonzero(self, tmp_path):
        test_file = _write_test(tmp_path, FAILING)
        obs = run_verification(f"pytest {test_file} -q -p no:cacheprovider", proposal_id="p2")
        assert obs.executed and obs.exit_code == 1

    def test_deselecting_everything_is_not_a_pass(self, tmp_path):
        test_file = _write_test(tmp_path, PASSING)
        obs = run_verification(f"pytest {test_file} -q -p no:cacheprovider -k nothing_matches", proposal_id="p3")
        assert obs.exit_code == 5
        state, chain = observation_to_evidence(obs)
        assert classify_execution_evidence(state, truth_chain_complete=chain) is not EvidenceTrustLevel.trusted

    def test_timeout_is_an_observation_not_an_exception(self, tmp_path):
        slow = _write_test(tmp_path, "import time\ndef test_slow():\n    time.sleep(30)\n")
        obs = run_verification(f"pytest {slow} -q -p no:cacheprovider", proposal_id="p4", timeout_s=2)
        assert obs.timed_out and obs.exit_code is None

    def test_rejected_command_never_runs(self):
        obs = run_verification("rm -rf /", proposal_id="p5")
        assert not obs.executed and obs.exit_code is None and obs.command == ()


# ---------------------------------------------------------------------------
# C. 验收 R1：声明 ≠ 裁决
# ---------------------------------------------------------------------------


class TestClaimIsNotAVerdict:
    def test_claimed_pass_with_failing_run_is_a_divergence_and_does_not_advance(self, tmp_path):
        loop = SelfHealingLoop()
        pid = _loop_at_apply(loop)
        test_file = _write_test(tmp_path, FAILING)

        result = loop.validate(pid, passed=True, command=f"pytest {test_file} -q -p no:cacheprovider")

        assert result["success"] is False
        assert result["validation_passed"] is False
        assert result["stage"] == EngineeringStage.APPLY.value, "失败的验证不得推进阶段"
        assert result["divergence"] == {
            "claimed_passed": True,
            "evidence_verified": False,
            "trust_level": "provisional",
            "exit_code": 1,
            "evidence_ref": result["evidence_ref"],
        }
        proposal = loop.get_proposal(pid)
        assert proposal.claimed_passed is True and proposal.validation_passed is False

    def test_divergent_outcome_never_reaches_the_knowledge_core_as_validated(self, tmp_path):
        loop = SelfHealingLoop()
        pid = _loop_at_apply(loop)
        test_file = _write_test(tmp_path, FAILING)
        loop.validate(pid, passed=True, command=f"pytest {test_file} -q -p no:cacheprovider")
        rag = MagicMock()
        rag.ingest_knowledge.return_value = "kc"
        with patch("core.self_improvement.get_rag_memory", return_value=rag):
            out = loop.record_outcome(pid)
        assert out["success"] is True and out["outcome"] == "unvalidated"
        tags = rag.ingest_knowledge.call_args.kwargs["tags"]
        assert "validated" not in tags and "unvalidated" in tags and "trust:provisional" in tags
        assert loop.snapshot().verdict_divergence_count == 1

    def test_a_claim_without_any_command_proves_nothing(self):
        """Node_112 的形状：只有 AutoFixer 自己说「修好了」，没有任何验证。"""
        loop = SelfHealingLoop()
        pid = _loop_at_apply(loop)
        result = loop.validate(pid, validation_notes="AutoFixer says fixed", passed=True)
        assert result["success"] is False and result["trust_level"] == "quarantine"
        assert result["stage"] == EngineeringStage.APPLY.value
        # 结局仍然可以记 —— 带着「没有验证」这件事本身作为证据，不会永远挂在 pending 里。
        with patch("core.self_improvement.get_rag_memory", return_value=MagicMock()):
            assert loop.record_outcome(pid)["outcome"] == "unvalidated"
        assert loop.get_proposal(pid) is None

    def test_record_outcome_still_refuses_when_nothing_was_ever_observed(self):
        loop = SelfHealingLoop()
        pid = _loop_at_apply(loop)
        assert loop.record_outcome(pid)["success"] is False


# ---------------------------------------------------------------------------
# D. 验收 R2：复现原失败 → 修正 → 同一检查转绿（融合动作）
# ---------------------------------------------------------------------------


class TestReproduceThenFix:
    def test_same_check_fails_then_passes_and_only_then_is_validated(self, tmp_path):
        loop = SelfHealingLoop()
        subject = _write_test(tmp_path, FAILING)
        command = f"pytest {subject} -q -p no:cacheprovider"

        p = loop.submit_diagnosis("arithmetic is wrong", source="test")
        loop.attach_context(p.proposal_id, {})
        loop.plan_patch(p.proposal_id, "fix the arithmetic", [subject])

        # 融合动作：apply 之后 harness 当场跑验证 —— 原失败被复现，停在 APPLY。
        first = loop.apply_patch(p.proposal_id, verify_command=command)
        assert first["verification"]["exit_code"] == 1
        assert first["stage"] == EngineeringStage.APPLY.value

        # 修正，然后用**同一条检查**再验。
        _write_test(tmp_path, PASSING)
        second = loop.validate(p.proposal_id, command=command)
        assert second["success"] is True and second["trust_level"] == "trusted"
        assert second["stage"] == EngineeringStage.VALIDATE.value

        rag = MagicMock()
        rag.ingest_knowledge.return_value = "kc_fixed"
        with patch("core.self_improvement.get_rag_memory", return_value=rag):
            out = loop.record_outcome(p.proposal_id)
        assert out["outcome"] == "validated" and "validated" in rag.ingest_knowledge.call_args.kwargs["tags"]
        record = loop.recent_records()[-1]
        assert len(record.evidence_refs) == 2, "两次实跑的原文都在：失败的那次和转绿的那次"


# ---------------------------------------------------------------------------
# E. 无证据不受理
# ---------------------------------------------------------------------------


def test_exit_zero_without_archived_output_is_not_trusted(tmp_path, monkeypatch):
    monkeypatch.setattr(context_archive, "archive_segment", lambda *a, **k: None)
    loop = SelfHealingLoop()
    pid = _loop_at_apply(loop)
    test_file = _write_test(tmp_path, PASSING)
    result = loop.validate(pid, command=f"pytest {test_file} -q -p no:cacheprovider")
    assert result["exit_code"] == 0
    assert result["trust_level"] == "provisional" and result["success"] is False
    assert "没能落盘" in result["error"]


# ---------------------------------------------------------------------------
# F. openclawd 派发
# ---------------------------------------------------------------------------


def test_dispatch_runs_real_verification_off_the_event_loop(tmp_path):
    import core.openclawd as oc
    from core.self_improvement import get_self_healing_loop, reset_self_healing_loop

    reset_self_healing_loop()
    loop = get_self_healing_loop()
    pid = _loop_at_apply(loop)
    test_file = _write_test(tmp_path, PASSING)
    bare = oc.OpenClawd.__new__(oc.OpenClawd)

    async def _go():
        ticks = 0

        async def _heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        hb = asyncio.create_task(_heartbeat())
        try:
            return (
                await bare._dispatch_engineer_tool(
                    "validate", {"proposal_id": pid, "command": f"pytest {test_file} -q -p no:cacheprovider"}
                ),
                ticks,
            )
        finally:
            hb.cancel()

    result, ticks = asyncio.run(_go())
    assert result["success"] is True and result["trust_level"] == "trusted"
    assert ticks > 0, "验证期间事件循环必须还在转 —— 子进程不能在协程里同步阻塞"
