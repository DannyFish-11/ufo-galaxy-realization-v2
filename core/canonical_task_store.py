#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/canonical_task_store.py — CanonicalTask 的可持久化对象存储
================================================================

**Stage 1：给对象层一个能在进程重启后回答问题的地方。**

``CanonicalTaskRuntime`` 是权威的任务本体运行时，但它的存储是进程内的
``Dict`` 加一条 256 条的 ring buffer：

    _MAX_RING: int = 256
    self._tasks: Dict[str, CanonicalTask] = {}
    self._ring: Deque[CanonicalTaskRecord] = deque(maxlen=_MAX_RING)

进程一重启就没了，第 257 个任务把第 1 个挤掉。**它是可观测性缓冲区，不是对象库。**
后果是：任何"这台设备上次执行 X 为什么失败"这类问题，对象层都答不上来，
于是决策逻辑只能退回去查向量库——用相似度采样的文本去猜一个本该确定的事实。

本模块补上那个缺口：一份 append-only 的持久投影，按**类型化字段**确定性查询。

设计取舍
--------
1. **投影而非镜像。** 存的是 :class:`PersistedTaskRecord` ——把查询要用的字段
   (lifecycle / origin / session_id / targets / success …) 摊平到顶层，完整的
   ``to_dict()`` 负载挂在 ``payload`` 里备查。这样查询不必反序列化七层嵌套
   dataclass，也不需要给 ``CanonicalTask`` 补一个易碎的 ``from_dict``。
2. **不取代 ring buffer。** ring 继续服务可观测性，本存储是并行的持久投影。
   两者都不是对方的替代品——ring 快而短，store 慢而长。
3. **抄仓库自己的范式。** 落盘格式、热冷分层、TTL 逐出全部对齐
   ``core/task_memory.py``，零新依赖。

灰度
----
``GALAXY_CANONICAL_TASK_STORE`` = ``off`` | ``shadow`` | ``on``（默认 ``shadow``）。

- ``shadow``（默认）：**只写不读**。存储真实累积数据、可度量写入延迟与磁盘增长，
  但 ``query()`` / ``get()`` 一律返回空，任何消费者都拿不到东西——因此
  **默认档位不可能改变任何现有行为**。
- ``on``：读写都开，消费者可以查。
- ``off``：完全关闭，一键退回现状。

默认选 ``shadow`` 而不是 ``off``：``off`` 会让这层从上线第一天就是死代码，
而这个仓库对"写了没接"的东西有明确的教训（见 ``pytest.ini`` 关于 Node_71
那七个文件的说明——没接进 CI，于是安静地烂掉）。``shadow`` 让它真实在跑、
可被度量，同时不给任何人依赖它的机会。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.CanonicalTaskStore")

__all__ = [
    "CANONICAL_TASK_STORE_IS_AUTHORITY",
    "CANONICAL_TASK_STORE_DOES_NOT_DISPATCH_POLICY",
    "CANONICAL_TASK_STORE_COMPLEMENTS_RING_BUFFER_POLICY",
    "CANONICAL_TASK_STORE_DETERMINISTIC_QUERY_POLICY",
    "MODE_OFF",
    "MODE_SHADOW",
    "MODE_ON",
    "get_canonical_task_store_mode",
    "PersistedTaskRecord",
    "CanonicalTaskStore",
    "get_canonical_task_store",
    "reset_canonical_task_store",
]


# ---------------------------------------------------------------------------
# Authority / policy sentinels
# ---------------------------------------------------------------------------

CANONICAL_TASK_STORE_IS_AUTHORITY: str = (
    "CANONICAL_TASK_STORE::AUTHORITY: "
    "This module is the durable, queryable projection of CanonicalTask objects. "
    "CanonicalTaskRuntime remains the canonical in-process task authority; this "
    "store never becomes a second source of truth for live task state."
)

CANONICAL_TASK_STORE_DOES_NOT_DISPATCH_POLICY: str = (
    "CANONICAL_TASK_STORE::POLICY_1: "
    "The store is read/write only.  It MUST NOT dispatch, mutate live tasks, or "
    "participate in routing.  CommandRouter.route_envelope() remains the sole "
    "system-level dispatch spine."
)

CANONICAL_TASK_STORE_COMPLEMENTS_RING_BUFFER_POLICY: str = (
    "CANONICAL_TASK_STORE::POLICY_2: "
    "The 256-entry observability ring buffer in CanonicalTaskRuntime is NOT "
    "replaced.  Ring = short and fast, for operator observability.  Store = long "
    "and durable, for deterministic historical queries.  Neither supersedes the "
    "other and neither may be described as the single task history."
)

CANONICAL_TASK_STORE_DETERMINISTIC_QUERY_POLICY: str = (
    "CANONICAL_TASK_STORE::POLICY_3: "
    "Queries filter on typed fields only (lifecycle, origin, session_id, target, "
    "success, time window).  Similarity ranking and free-text matching are "
    "deliberately absent: this layer exists so control-flow decisions can stop "
    "inferring facts from retrieved prose."
)


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

MODE_OFF: str = "off"
MODE_SHADOW: str = "shadow"
MODE_ON: str = "on"

_VALID_MODES = (MODE_OFF, MODE_SHADOW, MODE_ON)
_ENV_MODE = "GALAXY_CANONICAL_TASK_STORE"


def get_canonical_task_store_mode() -> str:
    """Resolve the rollout mode; unknown values degrade to ``shadow``.

    Degrading to ``shadow`` rather than ``on`` matters: a typo in an env var must
    never silently hand live decisions a data source they were not meant to have.
    """
    raw = os.getenv(_ENV_MODE, MODE_SHADOW).strip().lower()
    if raw in _VALID_MODES:
        return raw
    logger.warning("%s=%r is not one of %s — falling back to %r", _ENV_MODE, raw, _VALID_MODES, MODE_SHADOW)
    return MODE_SHADOW


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_STORE_FILE = "canonical_tasks.jsonl"
_DEFAULT_HOT_LIMIT = 500
"""Records kept resident in memory.  Larger than task_memory's 200 because a
CanonicalTask projection is the unit decisions ask about, not a summary line."""

_MAX_PAYLOAD_CHARS = 20000
"""Upper bound on the serialised detail payload for one record.  A pathological
task (huge args dict, long result) must not be able to blow up the file."""

_MAX_FILE_BYTES = 32 * 1024 * 1024
"""Compact the file once it grows past this.

An append-only file on a write path with no ceiling is an operational hazard, not
a design: ``register()`` is called on every task ingress *and again on every
lifecycle advance*, so the file grows several times faster than task count.
Compaction rewrites it keeping only the latest line per task_id, which is exactly
what ``_load_recent`` would have reduced it to anyway."""

_COMPACT_TARGET_RATIO = 0.5
"""Compaction retains newest records until this fraction of _MAX_FILE_BYTES.

Compaction is bounded by **bytes, not by record count**, and that distinction is
load-bearing.  Keeping "the newest N records" cannot guarantee the result fits
under the ceiling: if those N records are themselves oversized, the file is still
over the limit after compacting, so the *next* append compacts again — and every
append after that.  Measured: with a count-based rule the store degraded to a full
file rewrite per write (O(n²)) and a 1500-write loop failed to finish in two
minutes.  A byte target guarantees the rewritten file is at most half the ceiling,
which puts the next compaction a long way off.
"""

_COMPACT_MAX_KEEP = 20000
"""Absolute cap on retained records, independent of the byte target."""

_COMPACT_CHECK_EVERY = 32
"""Only stat the file every N appends.

Even with a byte target, checking on every single write costs a syscall per write
for no benefit — the file cannot cross the ceiling in one append.

Consequence worth stating plainly: this makes ``_MAX_FILE_BYTES`` a **soft**
ceiling.  Between two checks the file may overshoot by up to N records, so the
real bound is ``_MAX_FILE_BYTES + N * _MAX_PAYLOAD_CHARS``.  That is the intended
trade — a hard ceiling would cost a stat syscall on every single write."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class PersistedTaskRecord:
    """A flattened, queryable projection of one :class:`CanonicalTask`.

    Query-relevant fields are hoisted to the top level so filtering never has to
    walk the nested payload.  ``payload`` keeps the full ``CanonicalTask.to_dict()``
    for callers that need detail after locating a record.
    """

    task_id: str = ""
    trace_id: str = ""
    session_id: str = ""
    lifecycle: str = ""
    origin: str = ""
    tool: str = ""
    targets: List[str] = field(default_factory=list)
    success: Optional[bool] = None
    created_at: float = 0.0
    updated_at: float = field(default_factory=time.time)
    payload: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_task(cls, task: Any) -> "PersistedTaskRecord":
        """Project a live CanonicalTask into a persistable record.

        Defensive throughout: this runs on the task-registration path, so a
        malformed task must degrade to a thin record rather than raise.
        """
        identity = getattr(task, "identity", None)
        intent = getattr(task, "intent", None)
        routing = getattr(task, "routing", None)
        execution = getattr(task, "execution", None)
        result = getattr(task, "result", None)

        lifecycle = getattr(task, "lifecycle", "")
        origin = getattr(intent, "origin", "") if intent is not None else ""

        try:
            payload = task.to_dict()
        except Exception as exc:  # noqa: BLE001 — detail is optional, identity is not
            logger.debug("CanonicalTask.to_dict failed, storing thin record: %s", exc)
            payload = {}

        return cls(
            task_id=str(getattr(identity, "task_id", "") or ""),
            trace_id=str(getattr(identity, "trace_id", "") or ""),
            session_id=str(getattr(identity, "session_id", "") or ""),
            lifecycle=str(getattr(lifecycle, "value", lifecycle) or ""),
            origin=str(getattr(origin, "value", origin) or ""),
            tool=str(
                (getattr(execution, "tool", "") if execution is not None else "")
                or (getattr(intent, "requested_action", "") if intent is not None else "")
            ),
            targets=list(getattr(routing, "selected_targets", []) or []) if routing is not None else [],
            success=getattr(result, "success", None) if result is not None else None,
            created_at=float(getattr(task, "created_at", 0.0) or 0.0),
            payload=payload,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersistedTaskRecord":
        success = data.get("success")
        return cls(
            task_id=str(data.get("task_id") or ""),
            trace_id=str(data.get("trace_id") or ""),
            session_id=str(data.get("session_id") or ""),
            lifecycle=str(data.get("lifecycle") or ""),
            origin=str(data.get("origin") or ""),
            tool=str(data.get("tool") or ""),
            targets=list(data.get("targets") or []),
            success=None if success is None else bool(success),
            created_at=float(data.get("created_at") or 0.0),
            updated_at=float(data.get("updated_at") or 0.0),
            payload=dict(data.get("payload") or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "lifecycle": self.lifecycle,
            "origin": self.origin,
            "tool": self.tool,
            "targets": self.targets,
            "success": self.success,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "payload": self.payload,
        }


class _PayloadView:
    """Attribute-style view over a stored ``CanonicalTask.to_dict()`` payload.

    Link resolvers are written against the live object shape
    (``task.graph.dependencies``), and a stored record holds the same shape as
    nested dicts.  Rather than duplicate every resolver for the dict form — two
    copies that would drift — this adapts the dict to the attribute access the
    resolvers already use.  Missing keys yield another empty view, so a partial
    or truncated payload resolves to ``[]`` instead of raising.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Any) -> None:
        self._data = data if isinstance(data, dict) else {}

    def __getattr__(self, name: str) -> Any:
        value = self._data.get(name)
        if isinstance(value, dict):
            return _PayloadView(value)
        return value


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class CanonicalTaskStore:
    """Durable, queryable projection of CanonicalTask objects.

    Storage shape mirrors :mod:`core.task_memory`: an append-only JSONL file with
    a hot in-memory tier and a cold on-disk tier, so this introduces no new
    dependency and no new operational concept.

    Thread-safe: ``CanonicalTaskRuntime.register()`` may be called from multiple
    threads, and the runtime already guards its own allocation truth with a lock.
    """

    def __init__(
        self,
        data_dir: Optional[str] = None,
        hot_limit: int = _DEFAULT_HOT_LIMIT,
        ttl_seconds: float = 0.0,
    ) -> None:
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        try:
            os.makedirs(self._data_dir, exist_ok=True)
        except Exception as exc:  # noqa: BLE001 — an unwritable dir must not break startup
            logger.debug("CanonicalTaskStore data dir unavailable: %s", exc)
        self._file = os.path.join(self._data_dir, _STORE_FILE)
        self._hot_limit = max(1, int(hot_limit))
        self._ttl_seconds = float(ttl_seconds)
        self._lock = threading.Lock()
        self._records: List[PersistedTaskRecord] = []
        self._index: Dict[str, PersistedTaskRecord] = {}
        self._appends_since_check = 0
        self._stats = {"upserts": 0, "queries": 0, "load_errors": 0}
        self._load_recent()

    # ── Write ─────────────────────────────────────────────────────────────

    def upsert(self, task: Any) -> Optional[PersistedTaskRecord]:
        """Record (or update) the projection of *task*.

        Returns the stored record, or ``None`` when the store is disabled or the
        task carries no id.  Never raises — task registration must not fail
        because a projection could not be written.
        """
        if get_canonical_task_store_mode() == MODE_OFF:
            return None
        try:
            record = PersistedTaskRecord.from_task(task)
            if not record.task_id:
                return None
            record.updated_at = time.time()
            with self._lock:
                existing = self._index.get(record.task_id)
                if existing is not None:
                    # Idempotent upsert: same identity replaces in place, so the
                    # hot tier holds one row per task rather than one per state
                    # transition (register() is called again on every advance).
                    #
                    # Located by identity, not by ``list.index``: PersistedTaskRecord
                    # is a dataclass, so ``==`` compares field values and index()
                    # would happily return a *different* row that merely looks the
                    # same (two thin records with empty fields, say).
                    for i, r in enumerate(self._records):
                        if r is existing:
                            self._records[i] = record
                            break
                    else:
                        self._records.append(record)
                else:
                    self._records.append(record)
                    if len(self._records) > self._hot_limit:
                        evicted = self._records.pop(0)
                        self._index.pop(evicted.task_id, None)
                self._index[record.task_id] = record
                self._stats["upserts"] += 1
            self._append_to_file(record)
            return record
        except Exception as exc:  # noqa: BLE001 — projection is best-effort
            logger.debug("CanonicalTaskStore.upsert skipped: %s", exc)
            return None

    # ── Read ──────────────────────────────────────────────────────────────

    def get(self, task_id: str) -> Optional[PersistedTaskRecord]:
        """Return the record for *task_id*, or ``None``.

        Returns ``None`` in ``shadow`` mode regardless of what is stored — that is
        the whole point of shadow: data accumulates, nothing consumes it.
        """
        if get_canonical_task_store_mode() != MODE_ON:
            return None
        tid = str(task_id or "").strip()
        if not tid:
            return None
        with self._lock:
            self._stats["queries"] += 1
            hit = self._index.get(tid)
        if hit is not None:
            return hit
        cold = self._scan_cold(lambda r: r.task_id == tid, limit=1)
        return cold[0] if cold else None

    def query(
        self,
        *,
        lifecycle: str = "",
        origin: str = "",
        session_id: str = "",
        trace_id: str = "",
        target: str = "",
        success: Optional[bool] = None,
        since: float = 0.0,
        limit: int = 50,
        include_cold: bool = False,
    ) -> List[PersistedTaskRecord]:
        """Deterministically filter stored tasks by typed fields.

        Every filter is an exact match on a typed field — there is no similarity
        ranking here by design (see CANONICAL_TASK_STORE_DETERMINISTIC_QUERY_POLICY).
        Results are newest-first.

        Returns ``[]`` in ``shadow``/``off`` mode.
        """
        if get_canonical_task_store_mode() != MODE_ON:
            return []

        def _matches(r: PersistedTaskRecord) -> bool:
            if lifecycle and r.lifecycle != lifecycle:
                return False
            if origin and r.origin != origin:
                return False
            if session_id and r.session_id != session_id:
                return False
            if trace_id and r.trace_id != trace_id:
                return False
            if target and target not in (r.targets or []):
                return False
            if success is not None and r.success is not success:
                return False
            if since and r.updated_at < since:
                return False
            return True

        with self._lock:
            self._stats["queries"] += 1
            hot = [r for r in self._records if _matches(r)]

        if include_cold:
            hot_ids = {r.task_id for r in hot}
            for r in self._scan_cold(_matches, limit=max(limit * 4, 200)):
                if r.task_id not in hot_ids:
                    hot.append(r)
                    hot_ids.add(r.task_id)

        hot.sort(key=lambda r: r.updated_at, reverse=True)
        return hot[: max(0, int(limit))]

    def related(self, task_id: str, link_name: str) -> List[str]:
        """Walk a declared relation out of a stored task.

        This is where the Link Type layer (:mod:`core.ontology.links`) becomes
        usable: the store holds the durable objects, the link registry declares
        how relations are walked, and this method joins them.  ``"task_depends_on"``,
        ``"task_targets_device"``, ``"task_has_child"`` … are resolved from the
        stored projection's own fields — no inference, no similarity.

        Raises ``KeyError`` for an undeclared link (asking for a relation that does
        not exist is a programming error).  Returns ``[]`` when the task is not
        stored, or when the store is not in ``on`` mode.
        """
        record = self.get(task_id)
        if record is None:
            return []
        try:
            from core.ontology.links import get_link_registry

            registry = get_link_registry()
        except Exception as exc:  # noqa: BLE001 — the relation layer is optional
            logger.debug("link registry unavailable: %s", exc)
            return []
        # Resolvers read the live CanonicalTask shape, so walk the stored payload
        # through a lightweight view exposing the same attribute path.
        return registry.resolve(_PayloadView(record.payload), link_name)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "mode": get_canonical_task_store_mode(),
                "hot_records": len(self._records),
                "hot_limit": self._hot_limit,
                "file": self._file,
            }

    # ── Persistence ───────────────────────────────────────────────────────

    def _append_to_file(self, record: PersistedTaskRecord) -> None:
        try:
            payload = record.to_dict()
            line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            if len(line) > _MAX_PAYLOAD_CHARS:
                # Drop the detail payload rather than the record: identity and the
                # queryable fields are what decisions need; detail is a nicety.
                payload["payload"] = {"_truncated": True}
                line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            with open(self._file, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._maybe_compact()
        except Exception as exc:  # noqa: BLE001
            logger.debug("CanonicalTaskStore append failed: %s", exc)

    def _maybe_compact(self) -> None:
        """Rewrite the file to the newest line per task, under a byte target.

        Two guards keep this from becoming the hot path:
        - the size check runs once every ``_COMPACT_CHECK_EVERY`` appends;
        - retention is bounded by bytes, so a compaction always lands well under
          the ceiling and cannot immediately re-trigger.
        """
        self._appends_since_check += 1
        if self._appends_since_check < _COMPACT_CHECK_EVERY:
            return
        self._appends_since_check = 0
        try:
            if os.path.getsize(self._file) <= _MAX_FILE_BYTES:
                return
        except OSError:
            return
        try:
            latest: Dict[str, PersistedTaskRecord] = {}
            for rec in self._iter_file_records():
                if rec.task_id:
                    latest[rec.task_id] = rec  # later line wins

            target_bytes = int(_MAX_FILE_BYTES * _COMPACT_TARGET_RATIO)
            newest_first = sorted(latest.values(), key=lambda r: r.updated_at, reverse=True)

            kept_lines: List[str] = []
            total = 0
            for rec in newest_first:
                line = json.dumps(rec.to_dict(), ensure_ascii=False, separators=(",", ":"))
                # +1 for the newline. Stop on the first record that would cross the
                # target rather than after it, so the target is a ceiling not a floor.
                if total + len(line) + 1 > target_bytes or len(kept_lines) >= _COMPACT_MAX_KEEP:
                    break
                kept_lines.append(line)
                total += len(line) + 1

            tmp_path = f"{self._file}.compact"
            with open(tmp_path, "w", encoding="utf-8") as fh:
                for line in reversed(kept_lines):  # restore oldest-first order
                    fh.write(line + "\n")
            os.replace(tmp_path, self._file)
            logger.info(
                "CanonicalTaskStore compacted to %d projections (%d bytes, target %d)",
                len(kept_lines),
                total,
                target_bytes,
            )
        except Exception as exc:  # noqa: BLE001 — compaction failure must not break writes
            logger.debug("CanonicalTaskStore compaction skipped: %s", exc)

    def _iter_file_records(self):
        """Yield records from the file oldest-first, skipping malformed lines."""
        if not os.path.exists(self._file):
            return
        try:
            with open(self._file, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield PersistedTaskRecord.from_dict(json.loads(line))
                    except Exception:  # noqa: BLE001 — one bad line must not kill the read
                        self._stats["load_errors"] += 1
        except Exception as exc:  # noqa: BLE001
            logger.debug("CanonicalTaskStore read failed: %s", exc)

    def _load_recent(self) -> None:
        """Populate the hot tier from the tail of the file.

        Later lines win: the file is append-only, so a task that advanced through
        several lifecycle states appears more than once and the last write is the
        current projection.
        """
        now = time.time()
        latest: Dict[str, PersistedTaskRecord] = {}
        for rec in self._iter_file_records():
            if not rec.task_id:
                continue
            if self._ttl_seconds > 0 and (now - rec.updated_at) > self._ttl_seconds:
                continue
            latest[rec.task_id] = rec
        ordered = sorted(latest.values(), key=lambda r: r.updated_at)
        self._records = ordered[-self._hot_limit :]
        self._index = {r.task_id: r for r in self._records}
        if self._records:
            logger.info("CanonicalTaskStore loaded %d task projections", len(self._records))

    def _scan_cold(self, predicate, limit: int) -> List[PersistedTaskRecord]:
        """Scan the on-disk tier for records the hot tier no longer holds."""
        out: Dict[str, PersistedTaskRecord] = {}
        for rec in self._iter_file_records():
            if rec.task_id and predicate(rec):
                out[rec.task_id] = rec  # later line wins
        results = sorted(out.values(), key=lambda r: r.updated_at, reverse=True)
        return results[: max(0, int(limit))]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[CanonicalTaskStore] = None
_instance_lock = threading.Lock()


def get_canonical_task_store() -> CanonicalTaskStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CanonicalTaskStore()
    return _instance


def reset_canonical_task_store() -> None:
    """Testing/reconfiguration only: drop the singleton."""
    global _instance
    with _instance_lock:
        _instance = None
