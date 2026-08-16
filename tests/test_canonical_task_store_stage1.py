"""tests/test_canonical_task_store_stage1.py
=============================================
Tests for the durable CanonicalTask object store (Stage 1).

背景
----
``CanonicalTaskRuntime`` 的存储是进程内 ``Dict`` 加一条 256 条 ring buffer:
进程一重启就没了,第 257 个任务把第 1 个挤掉。它是**可观测性缓冲区,不是对象库**。
后果是"这台设备上次执行 X 为什么失败"这类问题对象层答不上来,决策只能退回去
查向量库——用相似度采样的文本去猜一个本该确定的事实。

本模块补上缺口:append-only JSONL + 热冷分层的持久投影,按类型化字段确定性查询。
落盘范式对齐 ``core/task_memory.py``,零新依赖。

Coverage matrix
---------------
Group A — Sentinel / policy assertions
  A01. CANONICAL_TASK_STORE_IS_AUTHORITY exists and defers to the runtime.
  A02. DOES_NOT_DISPATCH_POLICY exists.
  A03. COMPLEMENTS_RING_BUFFER_POLICY states the ring is not replaced.
  A04. DETERMINISTIC_QUERY_POLICY rules out similarity ranking.

Group B — Mode resolution
  B01. Default mode is "shadow" (live but unconsumable).
  B02. on / off / shadow resolve.
  B03. Unknown value degrades to shadow, not on.

Group C — PersistedTaskRecord projection
  C01. from_task hoists the queryable fields.
  C02. from_task on a malformed task degrades instead of raising.
  C03. to_dict / from_dict round-trip.

Group D — Write + durability
  D01. upsert stores and returns a record.
  D02. Records survive a fresh store instance (restart).
  D03. Hot tier respects hot_limit.
  D04. A record evicted from the hot tier is still findable on disk.
  D05. Idempotent upsert — one hot row per task, latest lifecycle wins.
  D06. Malformed lines in the file are skipped, not fatal.
  D07. Oversized payloads are truncated rather than written whole.

Group E — Deterministic query
  E01. filter by lifecycle.
  E02. filter by session_id.
  E03. filter by success.
  E04. filter by target membership.
  E05. filter by since (time window).
  E06. limit is honoured and ordering is newest-first.
  E07. combined filters intersect.

Group F — Rollout gating
  F01. shadow writes but get() returns None.
  F02. shadow writes but query() returns [].
  F03. off performs no write at all.
  F04. flag is registered in flags.py.

Group G — Runtime wiring
  G01. CanonicalTaskRuntime._project_to_store exists and is called by register().
  G02. A failing store never breaks task registration.
"""

from __future__ import annotations

import json
import os

import pytest

from core.canonical_task import TaskLifecycle, build_canonical_task
from core.canonical_task_store import (
    MODE_OFF,
    MODE_ON,
    MODE_SHADOW,
    CanonicalTaskStore,
    PersistedTaskRecord,
    get_canonical_task_store_mode,
)


@pytest.fixture(autouse=True)
def _on_mode(monkeypatch):
    """Most tests exercise real behaviour, which needs reads enabled."""
    monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", MODE_ON)


@pytest.fixture
def store(tmp_path):
    return CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=5)


def _task(goal="任务", session_id="", targets=None, success=None, lifecycle=None):
    t = build_canonical_task(goal=goal, session_id=session_id, register=False)
    if targets:
        t.routing.selected_targets = list(targets)
    if lifecycle is not None:
        t.advance_lifecycle(lifecycle)
    if success is not None:
        t.result.success = success
    return t


# ---------------------------------------------------------------------------
# Group A — Sentinels
# ---------------------------------------------------------------------------


class TestGroupASentinels:
    def test_a01_authority_defers_to_runtime(self):
        from core.canonical_task_store import CANONICAL_TASK_STORE_IS_AUTHORITY

        assert "AUTHORITY" in CANONICAL_TASK_STORE_IS_AUTHORITY
        # Must not claim to own live task state.
        assert "CanonicalTaskRuntime remains" in CANONICAL_TASK_STORE_IS_AUTHORITY

    def test_a02_does_not_dispatch(self):
        from core.canonical_task_store import CANONICAL_TASK_STORE_DOES_NOT_DISPATCH_POLICY

        text = CANONICAL_TASK_STORE_DOES_NOT_DISPATCH_POLICY
        assert "POLICY_1" in text
        assert "MUST NOT dispatch" in text

    def test_a03_complements_ring_buffer(self):
        from core.canonical_task_store import CANONICAL_TASK_STORE_COMPLEMENTS_RING_BUFFER_POLICY

        text = CANONICAL_TASK_STORE_COMPLEMENTS_RING_BUFFER_POLICY
        assert "POLICY_2" in text
        assert "NOT" in text and "replaced" in text
        assert "neither" in text.lower()

    def test_a04_deterministic_query(self):
        from core.canonical_task_store import CANONICAL_TASK_STORE_DETERMINISTIC_QUERY_POLICY

        text = CANONICAL_TASK_STORE_DETERMINISTIC_QUERY_POLICY
        assert "POLICY_3" in text
        assert "typed fields" in text
        assert "Similarity ranking" in text


# ---------------------------------------------------------------------------
# Group B — Modes
# ---------------------------------------------------------------------------


class TestGroupBModes:
    def test_b01_default_is_shadow(self, monkeypatch):
        monkeypatch.delenv("GALAXY_CANONICAL_TASK_STORE", raising=False)
        assert get_canonical_task_store_mode() == MODE_SHADOW

    @pytest.mark.parametrize("mode", [MODE_ON, MODE_OFF, MODE_SHADOW])
    def test_b02_modes_resolve(self, monkeypatch, mode):
        monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", mode)
        assert get_canonical_task_store_mode() == mode

    def test_b03_unknown_degrades_to_shadow_not_on(self, monkeypatch):
        """A typo must never hand live decisions a data source by accident."""
        monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", "enabled")
        assert get_canonical_task_store_mode() == MODE_SHADOW


# ---------------------------------------------------------------------------
# Group C — Projection
# ---------------------------------------------------------------------------


class TestGroupCProjection:
    def test_c01_hoists_queryable_fields(self):
        t = _task(goal="部署", session_id="s1", targets=["dev-a"], success=True, lifecycle=TaskLifecycle.COMPLETED)
        rec = PersistedTaskRecord.from_task(t)
        assert rec.task_id == t.identity.task_id
        assert rec.session_id == "s1"
        assert rec.targets == ["dev-a"]
        assert rec.success is True
        assert rec.lifecycle == TaskLifecycle.COMPLETED.value
        assert rec.payload  # full detail retained

    def test_c02_malformed_task_degrades(self):
        class Broken:
            identity = None
            intent = None
            routing = None
            execution = None
            result = None

            def to_dict(self):
                raise RuntimeError("nope")

        rec = PersistedTaskRecord.from_task(Broken())
        assert rec.task_id == ""
        assert rec.payload == {}

    def test_c03_round_trip(self):
        rec = PersistedTaskRecord.from_task(_task(session_id="s2", targets=["d1", "d2"], success=False))
        again = PersistedTaskRecord.from_dict(json.loads(json.dumps(rec.to_dict())))
        assert again.task_id == rec.task_id
        assert again.targets == rec.targets
        assert again.success is False


# ---------------------------------------------------------------------------
# Group D — Write + durability
# ---------------------------------------------------------------------------


class TestGroupDDurability:
    def test_d01_upsert_returns_record(self, store):
        assert store.upsert(_task()) is not None

    def test_d02_survives_restart(self, tmp_path):
        s1 = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        t = _task(goal="重启前")
        s1.upsert(t)
        s2 = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        assert s2.get(t.identity.task_id) is not None

    def test_d03_hot_limit_respected(self, store):
        for i in range(12):
            store.upsert(_task(goal=f"t{i}"))
        assert len(store._records) == 5

    def test_d04_evicted_record_still_on_disk(self, store):
        first = _task(goal="最早")
        store.upsert(first)
        for i in range(11):
            store.upsert(_task(goal=f"t{i}"))
        assert first.identity.task_id not in store._index  # evicted from hot
        assert store.get(first.identity.task_id) is not None  # found on disk

    def test_d05_idempotent_upsert_latest_wins(self, tmp_path):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        t = _task(goal="推进")
        for state in (TaskLifecycle.PLANNED, TaskLifecycle.DISPATCHED, TaskLifecycle.COMPLETED):
            t.advance_lifecycle(state)
            s.upsert(t)
        assert len(s._records) == 1
        assert s._records[0].lifecycle == TaskLifecycle.COMPLETED.value

    def test_d06_malformed_lines_skipped(self, tmp_path):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        t = _task(goal="好行")
        s.upsert(t)
        with open(os.path.join(str(tmp_path), "canonical_tasks.jsonl"), "a", encoding="utf-8") as fh:
            fh.write("{not json at all\n\n")
        s2 = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        assert s2.get(t.identity.task_id) is not None

    def test_d10_compaction_lands_under_the_target_and_does_not_retrigger(self, tmp_path, monkeypatch):
        """Compaction must be bounded by bytes, not by record count.

        Regression: an earlier draft kept "the newest N records". If those N were
        themselves oversized, the file stayed over the ceiling after compacting, so
        the next append compacted again — and every append after that, each a full
        file rewrite. Measured at the time: a 1500-write loop failed to finish in
        two minutes. A byte target guarantees the result is at most half the
        ceiling, putting the next compaction far away.
        """
        import time as _time

        import core.canonical_task_store as mod

        monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 60_000)
        monkeypatch.setattr(mod, "_COMPACT_CHECK_EVERY", 1)  # check every write
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=1000)
        path = os.path.join(str(tmp_path), "canonical_tasks.jsonl")

        started = _time.monotonic()
        for i in range(400):
            s.upsert(_task(goal=f"t{i}", targets=["dev-a", "dev-b"]))
        elapsed = _time.monotonic() - started

        size = os.path.getsize(path)
        assert size <= mod._MAX_FILE_BYTES, f"file still over ceiling after compaction: {size}"
        # The real symptom of the bug was wall-clock, not size.
        assert elapsed < 20, f"writes degraded to per-append full rewrites ({elapsed:.1f}s for 400)"
        assert CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=1000)._records

    def test_d08_file_compacts_when_oversized(self, tmp_path, monkeypatch):
        """An append-only file on a write path needs a ceiling, not just a hope.

        register() fires on every ingress *and* every lifecycle advance, so the
        file grows several times faster than task count.
        """
        import core.canonical_task_store as mod

        monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 20_000)
        monkeypatch.setattr(mod, "_COMPACT_CHECK_EVERY", 4)
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=200)
        for i in range(150):
            s.upsert(_task(goal=f"t{i}"))
        path = os.path.join(str(tmp_path), "canonical_tasks.jsonl")
        # The ceiling is *soft* by design: the size check is throttled to once per
        # _COMPACT_CHECK_EVERY appends, so the file may overshoot by up to that many
        # records between checks. What must hold is that it stays bounded — not that
        # it never exceeds the number by a byte.
        slack = mod._COMPACT_CHECK_EVERY * mod._MAX_PAYLOAD_CHARS
        assert os.path.getsize(path) <= mod._MAX_FILE_BYTES + slack
        # Without compaction 150 records would be far larger than the ceiling.
        assert os.path.getsize(path) < 150 * 1200, "file does not look compacted at all"
        # Compaction must preserve readability, not just shrink the file.
        assert CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=200)._records

    def test_d09_compaction_keeps_latest_state_per_task(self, tmp_path, monkeypatch):
        import core.canonical_task_store as mod

        monkeypatch.setattr(mod, "_MAX_FILE_BYTES", 4000)
        monkeypatch.setattr(mod, "_COMPACT_CHECK_EVERY", 2)
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=100)
        t = _task(goal="反复推进")
        for _ in range(30):
            t.advance_lifecycle(TaskLifecycle.PLANNED)
            s.upsert(t)
        t.advance_lifecycle(TaskLifecycle.COMPLETED)
        s.upsert(t)
        fresh = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=100)
        got = fresh.get(t.identity.task_id)
        assert got is not None
        assert got.lifecycle == TaskLifecycle.COMPLETED.value

    def test_d07_oversized_payload_truncated(self, tmp_path):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        t = _task(goal="巨大")
        t.execution.args = {"blob": "x" * 40000}
        s.upsert(t)
        line = open(os.path.join(str(tmp_path), "canonical_tasks.jsonl"), encoding="utf-8").readline()
        data = json.loads(line)
        assert data["payload"].get("_truncated") is True
        # Identity and queryable fields survive truncation — that is the point.
        assert data["task_id"] == t.identity.task_id


# ---------------------------------------------------------------------------
# Group E — Deterministic query
# ---------------------------------------------------------------------------


class TestGroupEQuery:
    @pytest.fixture
    def populated(self, tmp_path):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=100)
        for i in range(10):
            s.upsert(
                _task(
                    goal=f"t{i}",
                    session_id="A" if i % 2 == 0 else "B",
                    targets=[f"dev-{i % 3}"],
                    success=(i % 4 == 0) or None,
                    lifecycle=TaskLifecycle.COMPLETED if i % 4 == 0 else None,
                )
            )
        return s

    def test_e01_by_lifecycle(self, populated):
        got = populated.query(lifecycle=TaskLifecycle.COMPLETED.value, limit=50)
        assert len(got) == 3
        assert all(r.lifecycle == TaskLifecycle.COMPLETED.value for r in got)

    def test_e02_by_session(self, populated):
        assert len(populated.query(session_id="A", limit=50)) == 5

    def test_e03_by_success(self, populated):
        got = populated.query(success=True, limit=50)
        assert len(got) == 3
        assert all(r.success is True for r in got)

    def test_e04_by_target_membership(self, populated):
        got = populated.query(target="dev-1", limit=50)
        assert len(got) == 3
        assert all("dev-1" in r.targets for r in got)

    def test_e05_by_since(self, populated):
        assert populated.query(since=9e12, limit=50) == []
        assert len(populated.query(since=0, limit=50)) == 10

    def test_e06_limit_and_ordering(self, populated):
        got = populated.query(limit=3)
        assert len(got) == 3
        stamps = [r.updated_at for r in got]
        assert stamps == sorted(stamps, reverse=True), "results must be newest-first"

    def test_e07_combined_filters_intersect(self, populated):
        got = populated.query(session_id="A", success=True, limit=50)
        assert all(r.session_id == "A" and r.success is True for r in got)
        assert len(got) == 3


# ---------------------------------------------------------------------------
# Group H — Relation walking (joins Stage 1 storage to Stage 3 Link Types)
# ---------------------------------------------------------------------------


class TestGroupHRelations:
    @pytest.fixture
    def linked(self, tmp_path):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        parent = _task(goal="父", session_id="sess-7")
        child = build_canonical_task(goal="子", parent_task_id=parent.identity.task_id, register=False)
        parent.graph.children = [child.identity.task_id]
        parent.graph.dependencies = ["dep-1", "dep-2"]
        parent.routing.selected_targets = ["dev-a", "dev-b"]
        s.upsert(parent)
        s.upsert(child)
        return s, parent, child

    def test_h01_walks_task_to_task(self, linked):
        s, parent, child = linked
        assert s.related(parent.identity.task_id, "task_depends_on") == ["dep-1", "dep-2"]
        assert s.related(parent.identity.task_id, "task_has_child") == [child.identity.task_id]
        assert s.related(child.identity.task_id, "task_has_parent") == [parent.identity.task_id]

    def test_h02_walks_task_to_device(self, linked):
        s, parent, _ = linked
        assert s.related(parent.identity.task_id, "task_targets_device") == ["dev-a", "dev-b"]

    def test_h03_relations_survive_restart(self, linked, tmp_path):
        """The point of Stages 1+3 together: the object layer answers after a restart.

        This is exactly the question the 256-entry ring buffer could not answer,
        and the reason decisions used to fall back to similarity search.
        """
        _, parent, _ = linked
        fresh = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        assert fresh.related(parent.identity.task_id, "task_targets_device") == ["dev-a", "dev-b"]

    def test_h04_unknown_task_is_empty_not_an_error(self, linked):
        s, _, _ = linked
        assert s.related("no-such-task", "task_depends_on") == []

    def test_h05_undeclared_link_raises(self, linked):
        s, parent, _ = linked
        with pytest.raises(KeyError):
            s.related(parent.identity.task_id, "task_eats_pizza")

    def test_h06_truncated_payload_resolves_empty(self, tmp_path, monkeypatch):
        """A record whose detail was dropped must resolve to [], not explode."""
        import core.canonical_task_store as mod

        monkeypatch.setattr(mod, "_MAX_PAYLOAD_CHARS", 200)
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        t = _task(goal="巨大")
        t.execution.args = {"blob": "x" * 5000}
        s.upsert(t)
        fresh = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        assert fresh.related(t.identity.task_id, "task_depends_on") == []

    def test_h07_relations_blind_in_shadow_mode(self, linked, monkeypatch):
        """related() reads through get(), so shadow gating applies to it too."""
        s, parent, _ = linked
        monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", MODE_SHADOW)
        assert s.related(parent.identity.task_id, "task_depends_on") == []


# ---------------------------------------------------------------------------
# Group F — Rollout gating
# ---------------------------------------------------------------------------


class TestGroupFGating:
    def test_f01_shadow_writes_but_get_is_blind(self, tmp_path, monkeypatch):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        t = _task()
        monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", MODE_SHADOW)
        assert s.upsert(t) is not None, "shadow must still accumulate data"
        assert s.get(t.identity.task_id) is None, "shadow must not serve reads"

    def test_f02_shadow_query_returns_empty(self, tmp_path, monkeypatch):
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        s.upsert(_task())
        monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", MODE_SHADOW)
        assert s.query(limit=50) == []

    def test_f03_off_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GALAXY_CANONICAL_TASK_STORE", MODE_OFF)
        s = CanonicalTaskStore(data_dir=str(tmp_path), hot_limit=50)
        assert s.upsert(_task()) is None
        assert not os.path.exists(os.path.join(str(tmp_path), "canonical_tasks.jsonl"))

    def test_f04_flag_registered(self):
        from flags import get_flag

        flag = get_flag("canonical_task_store")
        assert flag is not None
        assert flag.env_var == "GALAXY_CANONICAL_TASK_STORE"
        assert flag.default == MODE_SHADOW
        assert flag.rollout_plan and flag.cleanup_condition


# ---------------------------------------------------------------------------
# Group G — Runtime wiring
# ---------------------------------------------------------------------------


class TestGroupGWiring:
    def test_g01_register_projects_to_store(self):
        import inspect

        from core.canonical_task import CanonicalTaskRuntime

        assert hasattr(CanonicalTaskRuntime, "_project_to_store")
        src = inspect.getsource(CanonicalTaskRuntime.register)
        assert "_project_to_store" in src, "register() must mirror into the store"

    def test_g02_failing_store_does_not_break_registration(self, monkeypatch):
        """Registration is on the ingress path — a projection failure is not fatal."""
        import core.canonical_task_store as store_mod

        def boom():
            raise RuntimeError("store exploded")

        monkeypatch.setattr(store_mod, "get_canonical_task_store", boom)

        from core.canonical_task import CanonicalTaskRuntime

        runtime = CanonicalTaskRuntime()
        task = _task(goal="即使存储爆炸也要注册成功")
        assert runtime.register(task) is task
        assert runtime.get_by_task_id(task.identity.task_id) is task
