"""tests/test_curriculum.py — 横轴 Curriculum（M7）：选下一轮跑哪个算子，且说得出为什么。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.meta.artifacts import create_artifact
from core.meta.curriculum import arm_table, choice_history, choose_next, vertical_axis_readiness
from core.meta.kernel import SignalBundle
from core.meta.store import ArtifactStore

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path / "store")


class _Op:
    def __init__(self, name, scope, material=1, created_at="2099-01-01T00:00:00+00:00"):
        self.name, self.scope, self.version = name, scope, "1"
        self._material, self._created_at = material, created_at

    def collect(self, store):
        traces = tuple(
            create_artifact("trace", {"i": i, "op": self.name}, operator="runtime", created_at=self._created_at)
            for i in range(self._material)
        )
        return SignalBundle(traces=traces)


def _ops(data=1, harness=1, **kw):
    return {"data_rsi": _Op("data_rsi", "data", data, **kw), "harness_rsi": _Op("harness_rsi", "harness", harness)}


_counter = iter(range(10**6))


def _round(store, operator, outcome, *, version="1", level="L1"):
    patch = create_artifact(
        "patch",
        {"n": next(_counter), "verify_level": level, "rollback": {"kind": "restore_files", "files": {}}},
        operator=operator,
        operator_version=version,
    )
    pid = store.put(patch)
    store.put(create_artifact("lesson", {"outcome": outcome, "n": next(_counter)}, parents=(pid,), operator="kernel"))
    return pid


def test_arm_table_counts_outcomes(store):
    _round(store, "data_rsi", "committed")
    _round(store, "data_rsi", "rolled_back")
    _round(store, "harness_rsi", "rejected")
    table = arm_table(store)
    assert (table["data_rsi"].rounds, table["data_rsi"].trusted) == (2, 1)
    assert table["harness_rsi"].outcomes == {"rejected": 1}


def test_untried_arms_go_first_in_name_order(store):
    choice, signals = choose_next(store, _ops())
    assert choice.operator == "data_rsi" and "从没跑过" in choice.reason
    assert set(signals) == {"data_rsi", "harness_rsi"}
    _round(store, "data_rsi", "committed")
    assert choose_next(store, _ops())[0].operator == "harness_rsi"


def test_arms_without_material_are_skipped(store):
    choice, _ = choose_next(store, _ops(data=0, harness=0))
    assert choice.operator is None
    assert "没有材料" in choice.candidates["data_rsi"]["skipped"]


def test_stale_data_signals_are_skipped(store):
    store.record_commit("model", "patch:m", "verdict:m", "2100-01-01T00:00:00+00:00")
    choice, _ = choose_next(store, _ops())
    assert choice.operator == "harness_rsi"
    assert "不新鲜" in choice.candidates["data_rsi"]["skipped"]


def test_ucb_prefers_the_arm_that_earns_trusted_verdicts(store):
    for _ in range(3):
        _round(store, "data_rsi", "committed")
        _round(store, "harness_rsi", "rolled_back")
    choice, _ = choose_next(store, _ops())
    assert choice.operator == "data_rsi" and "UCB" in choice.reason
    assert choice.candidates["data_rsi"]["index"] > choice.candidates["harness_rsi"]["index"]


def test_ucb_prefers_the_less_tried_arm_at_equal_rates(store):
    for _ in range(4):
        _round(store, "data_rsi", "committed")
    _round(store, "harness_rsi", "committed")
    assert choose_next(store, _ops())[0].operator == "harness_rsi"


def test_every_choice_is_auditable(store):
    choice, _ = choose_next(store, _ops())
    task = store.get(choice.task_id)
    assert task.artifact_type == "task" and task.lineage.operator == "kernel"
    assert task.payload["operator"] == "data_rsi" and task.payload["reason"] == choice.reason
    [entry] = choice_history(store)
    assert entry["task_id"] == choice.task_id and set(entry["candidates"]) == {"data_rsi", "harness_rsi"}


def test_choice_is_deterministic(store, tmp_path):
    other = ArtifactStore(tmp_path / "other")
    for s in (store, other):
        _round(s, "data_rsi", "committed")
        _round(s, "harness_rsi", "rolled_back")
    a, _ = choose_next(store, _ops(), record=False)
    b, _ = choose_next(other, _ops(), record=False)
    assert (a.operator, a.candidates) == (b.operator, b.candidates)


def test_vertical_axis_stays_closed_until_all_three_conditions_hold(store):
    report = vertical_axis_readiness(store)
    assert report["ready"] is False
    assert set(report["conditions"]) == {
        "horizontal_two_versions",
        "curriculum_beats_random",
        "verification_is_cheap",
    }

    for version in ("1", "2"):
        _round(store, "data_rsi", "committed", version=version)
        _round(store, "data_rsi", "committed", version=version)
        _round(store, "harness_rsi", "rolled_back", version=version)
    choose_next(store, _ops())
    report = vertical_axis_readiness(store)
    assert report["conditions"]["horizontal_two_versions"]["met"]
    assert report["conditions"]["curriculum_beats_random"]["met"], report["conditions"]["curriculum_beats_random"]
    assert report["conditions"]["verification_is_cheap"]["met"]
    assert report["ready"] is True

    _round(store, "harness_rsi", "committed", level="L2")
    assert vertical_axis_readiness(store)["conditions"]["verification_is_cheap"]["met"] is False


def _cli(*args, env_extra=None, tmp_path=None):
    import os

    env = dict(os.environ, **(env_extra or {}))
    return subprocess.run(
        [sys.executable, "scripts/meta_rsi.py", "--store", str(tmp_path / "cli-store"), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        env=env,
    )


def test_cli_auto_respects_the_kill_switch(tmp_path):
    proc = _cli("run", "--operator", "auto", env_extra={"GALAXY_META_RSI": "off"}, tmp_path=tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["status"] == "disabled"


def test_cli_curriculum_reports_arms_and_vertical_axis(tmp_path):
    proc = _cli("curriculum", "--history", tmp_path=tmp_path)
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert set(payload["arms"]) == {"data_rsi", "harness_rsi"}
    assert payload["vertical_axis"]["ready"] is False and payload["history"] == []
