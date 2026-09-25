"""元层骨架（M2 / 架构书 R4 / 规格 §01 §02 §05 §06 §07）的判据测试。

A. artifact：内容寻址、完整性、谁能产生什么、verdict 四值且必须有证据、patch 必须有回滚句柄
B. 存储：只追加、同 id 不同内容拒绝、祖先链、生效记录
C. Kernel：off 不跑 · G5 越界 · G6 写验证器 · model 不开写 · shadow 永不生效 · on 只让 trusted 生效 ·
   过期补丁 · 新鲜度 M→D · verdict 的证据链 · 整包回退
D. 真实隔离工作区（git worktree）：补丁只在工作区里，活树不动
E. 守卫：G6 两表不相交、G10 热路径不加载元层；默认 off 时导入热路径不带起元层（G12）
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from core.engineering_verification import VerificationObservation
from core.meta import meta_rsi_mode
from core.meta.artifacts import ArtifactError, create_artifact, verify_integrity
from core.meta.kernel import (
    FileChange,
    GitWorktreeSandbox,
    PatchProposal,
    SignalBundle,
    freshness_violation,
    revert_patch,
    run_cycle,
    write_surface_violation,
)
from core.meta.store import ArtifactStore

REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _obs(exit_code=0, ref="context_archive:meta#1"):
    return VerificationObservation(
        command=(sys.executable, "-m", "pytest"),
        requested="pytest",
        recognized_verifier=True,
        executed=True,
        exit_code=exit_code,
        timed_out=False,
        duration_s=0.01,
        evidence_ref=ref,
    )


class FixedVerifier:
    """返回给定观测的验证器；同时记下它是在哪个工作区里被调用的。"""

    def __init__(self, observations):
        self.observations = observations
        self.seen_workspace = None
        self.seen_content = None

    def run(self, proposal, workspace):
        self.seen_workspace = workspace
        first = proposal.changes[0]
        target = workspace / first.path
        self.seen_content = target.read_text(encoding="utf-8") if target.exists() else None
        return list(self.observations)


def _dir_sandbox(root: Path):
    """一个普通目录充当隔离工作区（真实的 git worktree 在 D 组单独测）。"""

    @contextmanager
    def factory():
        root.mkdir(parents=True, exist_ok=True)

        class _S:
            path = root

        yield _S()

    return factory


class Op:
    def __init__(self, proposals, name="harness_rsi", scope="harness"):
        self.name, self.scope, self.version = name, scope, "test-1"
        self._proposals = proposals

    def propose(self, signals):
        return list(self._proposals)


def _genome_patch(before=None, after='{"x": 1}\n', path="config/genomes/test/component.json", scope="harness"):
    return PatchProposal(
        scope=scope, slot="instructions", changes=(FileChange(path, before, after),), rationale="试一下"
    )


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / "store")


@pytest.fixture
def live(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    return root


def _cycle(op, store, live, tmp_path, verifier, mode, signals=SignalBundle()):
    return run_cycle(
        op,
        signals,
        store=store,
        verifier=verifier,
        mode=mode,
        sandbox_factory=_dir_sandbox(tmp_path / "sandbox"),
        live_root=live,
    )


# ---------------------------------------------------------------------------
# A. artifact
# ---------------------------------------------------------------------------


class TestArtifacts:
    def test_id_is_derived_from_content(self):
        a = create_artifact("task", {"goal": "x"}, operator="kernel", created_at="t0")
        b = create_artifact("task", {"goal": "x"}, operator="kernel", created_at="t1")
        c = create_artifact("task", {"goal": "y"}, operator="kernel", created_at="t0")
        assert a.artifact_id == b.artifact_id and a.artifact_id != c.artifact_id
        assert a.artifact_id.startswith("task:") and len(a.artifact_id) == len("task:") + 16

    def test_tampering_is_detectable(self):
        a = create_artifact("lesson", {"hypothesis": "h"}, operator="kernel")
        forged = type(a)(**{**a.__dict__, "payload": {"hypothesis": "改过了"}})
        assert verify_integrity(a) and not verify_integrity(forged)

    @pytest.mark.parametrize("kind", ["score", "verdict"])
    def test_proposers_cannot_produce_score_or_verdict(self, kind):
        payload = {"level": "trusted"} if kind == "verdict" else {}
        with pytest.raises(ArtifactError, match="提案者不得写"):
            create_artifact(kind, payload, operator="harness_rsi", evidence=("e",))

    def test_verdict_is_four_valued_not_a_score(self):
        with pytest.raises(ArtifactError, match="不是分数"):
            create_artifact("verdict", {"level": 0.93}, operator="authority", evidence=("e",))

    def test_verdict_without_evidence_is_refused(self):
        with pytest.raises(ArtifactError, match="没有 evidence"):
            create_artifact("verdict", {"level": "trusted"}, operator="authority")

    def test_patch_without_rollback_is_refused(self):
        with pytest.raises(ArtifactError, match="回滚句柄"):
            create_artifact("patch", {"changes": []}, operator="harness_rsi")

    def test_unknown_type_is_refused(self):
        with pytest.raises(ArtifactError):
            create_artifact("opinion", {}, operator="kernel")


# ---------------------------------------------------------------------------
# B. 存储
# ---------------------------------------------------------------------------


class TestStore:
    def test_put_is_idempotent_and_get_round_trips(self, store):
        a = create_artifact("task", {"goal": "x"}, operator="kernel")
        assert store.put(a) == store.put(a) == a.artifact_id
        assert store.get(a.artifact_id) == a
        assert len(store.list("task")) == 1

    def test_history_cannot_be_rewritten(self, store):
        a = create_artifact("task", {"goal": "x"}, operator="kernel")
        store.put(a)
        path = store._path_of(a.artifact_id)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["payload"] = {"goal": "改过了"}
        path.write_text(json.dumps(data), encoding="utf-8")
        assert store.get(a.artifact_id) is None, "被改过的文件读出来就是不可信的"
        with pytest.raises(ArtifactError, match="历史不可改写"):
            store.put(a)

    def test_forged_artifact_is_refused(self, store):
        a = create_artifact("task", {"goal": "x"}, operator="kernel")
        forged = type(a)(**{**a.__dict__, "payload": {"goal": "y"}})
        with pytest.raises(ArtifactError, match="对不上"):
            store.put(forged)

    def test_ancestry_follows_lineage(self, store):
        t = create_artifact("task", {"g": 1}, operator="kernel")
        p = create_artifact("patch", {"rollback": {"k": 1}}, parents=(t.artifact_id,), operator="harness_rsi")
        s = create_artifact("score", {}, parents=(p.artifact_id,), operator="verifier")
        for a in (t, p, s):
            store.put(a)
        assert [a.artifact_id for a in store.ancestry(s.artifact_id)] == [p.artifact_id, t.artifact_id]

    def test_commits_and_last_commit(self, store):
        assert store.last_commit_at("model") == ""
        store.record_commit("model", "patch:a", "verdict:b", "2026-01-01T00:00:00+00:00")
        store.record_commit("model", "patch:c", "verdict:d", "2026-02-01T00:00:00+00:00")
        assert store.last_commit_at("model") == "2026-02-01T00:00:00+00:00"
        assert store.last_commit_at("data") == ""


# ---------------------------------------------------------------------------
# C. Kernel
# ---------------------------------------------------------------------------


class TestKernel:
    def test_default_mode_is_off(self, monkeypatch):
        monkeypatch.delenv("GALAXY_META_RSI", raising=False)
        assert meta_rsi_mode() == "off"
        monkeypatch.setenv("GALAXY_META_RSI", "yes please")
        assert meta_rsi_mode() == "off", "认不得的取值按 off —— 宁可不跑，不可误跑"

    def test_off_does_nothing(self, store, live, tmp_path):
        report = _cycle(Op([_genome_patch()]), store, live, tmp_path, FixedVerifier([_obs()]), "off")
        assert report.status == "disabled" and store.list() == []

    def test_operator_name_and_scope_must_match(self, store, live, tmp_path):
        report = _cycle(Op([_genome_patch()], name="harness_rsi", scope="data"), store, live, tmp_path, None, "on")
        assert report.status == "rejected"

    def test_g5_patch_outside_operator_scope_is_rejected(self, store, live, tmp_path):
        patch = _genome_patch(path="config/eval_cases/x.jsonl", scope="data")
        report = _cycle(Op([patch]), store, live, tmp_path, FixedVerifier([_obs()]), "on")
        assert report.outcomes[0].outcome == "rejected" and "G5" in report.outcomes[0].reason
        assert not (live / "config/eval_cases/x.jsonl").exists()

    @pytest.mark.parametrize(
        "path",
        ["scripts/check_wiring.py", "tests/test_x.py", "core/eval/scorer.py", "core/meta/kernel.py", ".github/x.yml"],
    )
    def test_g6_writing_a_verifier_is_rejected(self, path):
        assert "G6" in write_surface_violation("harness", [path]) or "G5" in write_surface_violation("harness", [path])
        assert "G6" in write_surface_violation("data", [path]) or "G5" in write_surface_violation("data", [path])

    @pytest.mark.parametrize("path", ["../etc/passwd", "/etc/passwd", "config/genomes/../../scripts/x.py"])
    def test_path_traversal_is_rejected(self, path):
        assert write_surface_violation("harness", [path])

    def test_model_scope_is_closed_in_phase_one(self, store, live, tmp_path):
        patch = PatchProposal(scope="model", slot="weights", changes=(FileChange("w.bin", None, "x"),), rationale="")
        report = _cycle(Op([patch], name="model_rsi", scope="model"), store, live, tmp_path, FixedVerifier([]), "on")
        assert report.outcomes[0].outcome == "rejected" and "不开写" in report.outcomes[0].reason

    def test_shadow_never_commits_even_when_trusted(self, store, live, tmp_path):
        verifier = FixedVerifier([_obs(0)])
        report = _cycle(Op([_genome_patch()]), store, live, tmp_path, verifier, "shadow")
        outcome = report.outcomes[0]
        assert outcome.level == "trusted" and outcome.outcome == "shadow"
        assert verifier.seen_content == '{"x": 1}\n', "补丁在隔离工作区里落了地、被验证了"
        assert not (live / "config/genomes/test/component.json").exists(), "活树一个字节都没动"
        assert store.commits() == []

    def test_on_commits_only_trusted(self, store, live, tmp_path):
        report = _cycle(Op([_genome_patch()]), store, live, tmp_path, FixedVerifier([_obs(0)]), "on")
        assert report.outcomes[0].outcome == "committed"
        assert (live / "config/genomes/test/component.json").read_text(encoding="utf-8") == '{"x": 1}\n'
        assert [c["scope"] for c in store.commits()] == ["harness"]

    @pytest.mark.parametrize("exit_code, ref", [(1, "context_archive:meta#1"), (0, "")])
    def test_on_rolls_back_anything_not_trusted(self, store, live, tmp_path, exit_code, ref):
        report = _cycle(Op([_genome_patch()]), store, live, tmp_path, FixedVerifier([_obs(exit_code, ref)]), "on")
        assert report.outcomes[0].outcome == "rolled_back" and report.outcomes[0].level == "provisional"
        assert not (live / "config/genomes/test/component.json").exists()

    def test_patch_computed_from_stale_content_is_not_applied(self, store, live, tmp_path):
        target = live / "config/genomes/test/component.json"
        target.parent.mkdir(parents=True)
        target.write_text("别人刚改过\n", encoding="utf-8")
        sandbox = tmp_path / "sandbox" / "config/genomes/test/component.json"
        sandbox.parent.mkdir(parents=True)
        sandbox.write_text("旧内容\n", encoding="utf-8")
        report = _cycle(Op([_genome_patch(before="旧内容\n")]), store, live, tmp_path, FixedVerifier([_obs(0)]), "on")
        assert report.outcomes[0].outcome == "stale_patch"
        assert target.read_text(encoding="utf-8") == "别人刚改过\n"

    def test_every_step_leaves_an_artifact_with_lineage(self, store, live, tmp_path):
        report = _cycle(Op([_genome_patch()]), store, live, tmp_path, FixedVerifier([_obs(0)]), "on")
        o = report.outcomes[0]
        verdict = store.get(o.verdict_id)
        assert verdict.lineage.operator == "authority"
        assert o.score_id in verdict.lineage.evidence and "context_archive:meta#1" in verdict.lineage.evidence
        assert set(verdict.lineage.parents) == {o.patch_id, o.score_id}
        lesson = store.get(o.lesson_id)
        assert lesson.payload["preconditions"]["paths"] == ["config/genomes/test/component.json"]
        assert store.get(o.score_id).lineage.operator == "verifier"
        assert store.get(o.patch_id).lineage.operator == "harness_rsi"

    def test_freshness_m_to_d(self, store):
        old = create_artifact("trace", {"t": 1}, operator="runtime", created_at="2026-01-01T00:00:00+00:00")
        new = create_artifact("trace", {"t": 2}, operator="runtime", created_at="2026-03-01T00:00:00+00:00")
        assert freshness_violation("data", SignalBundle(traces=(old,)), store) == ""
        store.record_commit("model", "patch:x", "verdict:y", "2026-02-01T00:00:00+00:00")
        assert "M→D" in freshness_violation("data", SignalBundle(traces=(old,)), store)
        assert freshness_violation("data", SignalBundle(traces=(new,)), store) == ""
        assert freshness_violation("harness", SignalBundle(traces=(old,)), store) == "", "只有 M→D 这一对不成立"

    def test_stale_signals_stop_the_data_cycle(self, store, live, tmp_path):
        old = create_artifact("trace", {"t": 1}, operator="runtime", created_at="2026-01-01T00:00:00+00:00")
        store.record_commit("model", "patch:x", "verdict:y", "2026-02-01T00:00:00+00:00")
        op = Op([_genome_patch(path="config/eval_cases/a.jsonl", scope="data")], name="data_rsi", scope="data")
        report = _cycle(op, store, live, tmp_path, FixedVerifier([_obs()]), "on", SignalBundle(traces=(old,)))
        assert report.status == "stale_signals"

    def test_committed_patch_can_be_reverted_whole(self, store, live, tmp_path):
        report = _cycle(Op([_genome_patch()]), store, live, tmp_path, FixedVerifier([_obs(0)]), "on")
        target = live / "config/genomes/test/component.json"
        assert target.exists()
        assert revert_patch(report.outcomes[0].patch_id, store=store, live_root=live) == ""
        assert not target.exists(), "改动前文件不存在，回退就是删掉它"
        assert store.commits()[-1]["verdict_id"].startswith("revert:")


# ---------------------------------------------------------------------------
# D. 真实隔离工作区
# ---------------------------------------------------------------------------


def test_real_git_worktree_sandbox_isolates_the_live_tree(store, tmp_path):
    before = subprocess.run(["git", "worktree", "list"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    verifier = FixedVerifier([_obs(0)])
    report = run_cycle(
        Op([_genome_patch()]), SignalBundle(), store=store, verifier=verifier, mode="shadow", live_root=tmp_path
    )
    assert report.outcomes[0].outcome == "shadow"
    assert verifier.seen_workspace != REPO_ROOT and verifier.seen_content == '{"x": 1}\n'
    assert not (REPO_ROOT / "config/genomes/test/component.json").exists()
    after = subprocess.run(["git", "worktree", "list"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert after == before, "隔离工作区用完即删"


def test_sandbox_refuses_outside_a_git_checkout(tmp_path):
    from core.meta.kernel import SandboxUnavailable

    with pytest.raises(SandboxUnavailable):
        with GitWorktreeSandbox(tmp_path):
            pass


# ---------------------------------------------------------------------------
# E. 守卫
# ---------------------------------------------------------------------------


class TestGuards:
    def test_repository_passes_meta_guards(self):
        from core.meta.guards import check_meta_layer

        assert check_meta_layer() == []

    def test_g10_detects_any_form_of_import(self):
        from core.meta.guards import direct_meta_imports

        src = (
            "import core.meta\n"
            "from core.meta.kernel import run_cycle\n"
            "from core import meta\n"
            "def f():\n    import importlib\n    importlib.import_module('core.meta.store')\n"
        )
        assert [t for _, t in direct_meta_imports(src)] == [
            "core.meta",
            "core.meta.kernel",
            "core.meta",
            "core.meta.store",
        ]
        assert direct_meta_imports("import core.metadata_store\nfrom core import metrics\n") == []

    def test_g6_overlapping_tables_are_caught(self, monkeypatch):
        import core.meta.kernel as kernel
        from core.meta.guards import check_write_surfaces

        monkeypatch.setitem(kernel.WRITABLE_SURFACES, "harness", ("config/genomes/", "tests/fixtures/"))
        assert any(v.guard == "G6" for v in check_write_surfaces())

    def test_gate_script_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, "scripts/check_meta_layer.py"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=120
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def test_importing_the_hot_path_does_not_load_the_meta_layer(self):
        """G12：默认 off 时系统行为不变 —— 最硬的说法是：热路径压根不加载元层。"""
        code = (
            "import sys, core.openclawd, core.desktop_presence_runtime, core.command_router\n"
            "print(sorted(m for m in sys.modules if m == 'core.meta' or m.startswith('core.meta.')))\n"
        )
        proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, timeout=300)
        assert proc.returncode == 0, proc.stderr[-2000:]
        assert proc.stdout.strip().splitlines()[-1] == "[]"


def test_cli_status_runs_with_an_empty_store(tmp_path):
    proc = subprocess.run(
        [sys.executable, "scripts/meta_rsi.py", "--store", str(tmp_path / "s"), "status"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["mode"] in ("off", "shadow", "on")
