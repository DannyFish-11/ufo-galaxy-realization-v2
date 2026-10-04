"""core.action_journal — 动手之前先记一笔，动手之后再记一笔

要解决什么
----------
它动你的键鼠时，"这一步到底执行了没有"有两种时刻答不上来：

* **被叫停 / 被取消的那一刻**：点击是发给另一个节点的 HTTP 请求，取消只能取消本端的
  等待 —— 请求可能已经到了、点击可能已经发生。
* **进程在两步之间崩了 / 被重启**：步骤记录在内存里（``StepRecord`` 列表），重启之后
  没有任何痕迹说明"有一步发出去了、结果没记上"。

两种时刻的正确回答都是「**不确定**」，而不是「失败」（人会据此重试，重复点一次）也不是
「成功」。借自 AFK-surf/Comma 的运行时：副作用先落盘再执行；写入结果不明时返回
``commit_indeterminate`` 且**不授予重放的权力**；文档里明说「不承诺外部操作恰好执行一次」。

这里就是那一笔账：

* ``begin``  —— 派发**之前**落一条意图（先落盘、fsync，再动手）；
* ``end``    —— 派发之后落结果：``ok`` / ``failed`` / ``unknown_after_cancel``；
* 进程重启时回放日志：只有 ``begin`` 没有 ``end`` 的，补一条 ``unknown_after_restart``
  并报出来 —— **绝不自动重放**。

与相邻模块的分工
----------------
``core.unified.idempotency`` / ``core.durable_result_idempotency`` 管的是「同一个 id 的
结果别处理两遍」（去重）。这里管的是「动手之前有没有留下意图」（写前日志）。两件事，
不互相替代。

刻意的边界
----------
* **不记敏感内容**：``type`` 的文字、密码类字段只记长度；其余字符串截断到 80 字。
  这份日志会被回放、会被报给面板，里面不该有人输入过的东西。
* **记账失败不拦动作**：磁盘写不了时降级为只在内存里记，并**留痕**（只说一次的告警、
  ``status()["degraded"]``）—— 可见性不能反过来拖垮执行，但「没写成」也不能装作写成了。
* **有界**：回放只读文件尾部 ``_MAX_LINES`` 行（一次运行里没了结的步骤本来就在尾部附近）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, Iterator, List, Optional

logger = logging.getLogger("Galaxy.ActionJournal")

__all__ = [
    "OUTCOME_FAILED",
    "OUTCOME_OK",
    "OUTCOME_UNKNOWN_CANCEL",
    "OUTCOME_UNKNOWN_RESTART",
    "UNKNOWN_OUTCOMES",
    "ActionJournal",
    "JournalEntry",
    "get_action_journal",
    "journaled",
    "reset_action_journal",
]

OUTCOME_OK = "ok"
OUTCOME_FAILED = "failed"
#: 被取消 / 被叫停时这一步正在飞：可能已经执行。
OUTCOME_UNKNOWN_CANCEL = "unknown_after_cancel"
#: 进程在这一步前后崩了 / 重启了：意图记下了、结果没记上。
OUTCOME_UNKNOWN_RESTART = "unknown_after_restart"
UNKNOWN_OUTCOMES = frozenset({OUTCOME_UNKNOWN_CANCEL, OUTCOME_UNKNOWN_RESTART})

_FILENAME = "action_journal.jsonl"
#: 回放时只保留尾部这么多行（begin/end 各占一行）。
_MAX_LINES = 2000
#: 内存里留多少条「结果不明」供查询。
_RECENT_UNKNOWN = 200
#: 默认只报最近这么久的「结果不明」—— 再久，屏幕早已不是当时的样子，报了只会误导。
DEFAULT_REPORT_WINDOW_S = 900.0

_SECRET_KEYS = frozenset({"text", "password", "passwd", "secret", "token", "value", "content", "data"})
_MAX_STR = 80


def _scrub(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """去掉敏感内容：被点名的字段只留长度，别的字符串截断，复杂值只留类型名。"""
    out: Dict[str, Any] = {}
    for key, value in (params or {}).items():
        k = str(key)
        if isinstance(value, str):
            out[k] = {"len": len(value)} if k.lower() in _SECRET_KEYS else value[:_MAX_STR]
        elif value is None or isinstance(value, (bool, int, float)):
            out[k] = value
        elif isinstance(value, (list, tuple)):
            out[k] = [v if isinstance(v, (bool, int, float)) else str(v)[:_MAX_STR] for v in list(value)[:8]]
        else:
            out[k] = type(value).__name__
    return out


def _summary(action: str, params: Dict[str, Any]) -> str:
    """给人看的一句话：``click(x=320, y=180)``。已经过 :func:`_scrub`，不含敏感内容。"""
    inner = ", ".join(
        f"{k}={json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v}"
        for k, v in list(params.items())[:4]
    )
    return f"{action}({inner})"


class JournalEntry:
    """一笔账。``outcome`` / ``error`` 由调用方在 ``with journaled(...)`` 里按需设置。"""

    __slots__ = ("id", "t_begin", "source", "action", "params", "runtime_session_id", "outcome", "error")

    def __init__(self, source: str, action: str, params: Dict[str, Any], runtime_session_id: str) -> None:
        self.id = uuid.uuid4().hex[:16]
        self.t_begin = time.time()
        self.source = source
        self.action = action
        self.params = params
        self.runtime_session_id = runtime_session_id
        self.outcome = ""
        self.error = ""

    def as_report(self, outcome: str, t_end: float) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "action": self.action,
            "summary": _summary(self.action, self.params),
            "outcome": outcome,
            "runtime_session_id": self.runtime_session_id,
            "t_begin": self.t_begin,
            "t_end": t_end,
        }


class ActionJournal:
    """追加式日志 + 内存索引。线程安全。"""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._open: Dict[str, JournalEntry] = {}
        self._unknown: Deque[Dict[str, Any]] = deque(maxlen=_RECENT_UNKNOWN)
        self._degraded = False
        self._degraded_reason = ""
        #: 回放时发现的、上次运行里没了结的那几步（已补记 unknown_after_restart）。
        self.recovered: List[Dict[str, Any]] = []
        self._replay()

    # ── 写 ────────────────────────────────────────────────────────────────

    def _append(self, record: Dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        try:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError as exc:
            # 记账失败不拦动作，但**不装作写成了**：只说一次，状态里留痕。
            if not self._degraded:
                self._degraded = True
                self._degraded_reason = f"{type(exc).__name__}: {exc}"
                logger.warning("动作日志写不进 %s，降级为只在内存里记（重启后无法回放）: %s", self._path, exc)

    def begin(
        self, source: str, action: str, params: Optional[Dict[str, Any]] = None, runtime_session_id: str = ""
    ) -> JournalEntry:
        """派发**之前**调：先落意图、fsync，再动手。"""
        entry = JournalEntry(source, action, _scrub(params), runtime_session_id)
        with self._lock:
            self._open[entry.id] = entry
            self._append(
                {
                    "v": 1,
                    "ev": "begin",
                    "id": entry.id,
                    "t": entry.t_begin,
                    "sid": runtime_session_id,
                    "source": source,
                    "action": action,
                    "params": entry.params,
                }
            )
        return entry

    def end(self, entry: JournalEntry, outcome: str, error: str = "") -> None:
        """派发之后调。重复调用无害（只记第一次）。"""
        now = time.time()
        with self._lock:
            if self._open.pop(entry.id, None) is None:
                return
            entry.outcome, entry.error = outcome, error[:200]
            self._append({"v": 1, "ev": "end", "id": entry.id, "t": now, "outcome": outcome, "error": entry.error})
            if outcome in UNKNOWN_OUTCOMES:
                self._unknown.append(entry.as_report(outcome, now))

    # ── 读 ────────────────────────────────────────────────────────────────

    def unknown_for(self, runtime_session_id: str) -> List[Dict[str, Any]]:
        """某个运行时会话里「结果不明」的那几步。叫停的结果里带的就是它。"""
        if not runtime_session_id:
            return []
        with self._lock:
            return [dict(r) for r in self._unknown if r["runtime_session_id"] == runtime_session_id]

    def recent_unknown(self, window_s: float = DEFAULT_REPORT_WINDOW_S) -> List[Dict[str, Any]]:
        """最近一段时间里所有「结果不明」的步骤（含上次运行里没了结的）。"""
        cutoff = time.time() - window_s
        with self._lock:
            return [dict(r) for r in self._unknown if r["t_end"] >= cutoff]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "path": self._path,
                "degraded": self._degraded,
                "degraded_reason": self._degraded_reason,
                "in_flight": len(self._open),
                "recovered_at_start": len(self.recovered),
            }

    # ── 回放 ──────────────────────────────────────────────────────────────

    def _replay(self) -> None:
        """读上次留下的日志：只有 begin 没有 end 的 → 补 unknown_after_restart，绝不重放。"""
        try:
            with open(self._path, encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except FileNotFoundError:
            return
        except OSError as exc:
            self._degraded, self._degraded_reason = True, f"{type(exc).__name__}: {exc}"
            logger.warning("动作日志读不了 %s，降级为只在内存里记（重启后无法回放）: %s", self._path, exc)
            return

        if len(lines) > _MAX_LINES:
            lines = lines[-_MAX_LINES:]
        begun: Dict[str, Dict[str, Any]] = {}
        ended: Dict[str, Dict[str, Any]] = {}
        for raw in lines:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue  # 半行（崩在写的途中）：丢掉，不当成事实
            if rec.get("ev") == "begin" and rec.get("id"):
                begun[rec["id"]] = rec
            elif rec.get("ev") == "end" and rec.get("id"):
                ended[rec["id"]] = rec

        for rid, rec in begun.items():
            end = ended.get(rid)
            entry = JournalEntry(
                str(rec.get("source", "")),
                str(rec.get("action", "")),
                rec.get("params") if isinstance(rec.get("params"), dict) else {},
                str(rec.get("sid", "")),
            )
            entry.id, entry.t_begin = rid, float(rec.get("t", 0) or 0)
            if end is None:
                now = time.time()
                self._append(
                    {"v": 1, "ev": "end", "id": rid, "t": now, "outcome": OUTCOME_UNKNOWN_RESTART, "error": ""}
                )
                report = entry.as_report(OUTCOME_UNKNOWN_RESTART, now)
                self.recovered.append(report)
                self._unknown.append(report)
            elif end.get("outcome") in UNKNOWN_OUTCOMES:
                self._unknown.append(entry.as_report(str(end["outcome"]), float(end.get("t", 0) or 0)))

        if self.recovered:
            logger.warning(
                "上次运行有 %d 步操作发出了意图、没留下结果（结果不明，不会自动重放）: %s",
                len(self.recovered),
                "; ".join(r["summary"] for r in self.recovered[:5]),
            )


# ── 进程级单例 ─────────────────────────────────────────────────────────────

_journal: Optional[ActionJournal] = None
_journal_lock = threading.Lock()


def _default_path() -> str:
    base = os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")
    return os.path.join(base, _FILENAME)


def get_action_journal() -> ActionJournal:
    global _journal
    if _journal is None:
        with _journal_lock:
            if _journal is None:
                _journal = ActionJournal(_default_path())
    return _journal


def reset_action_journal() -> None:
    """测试用：丢掉单例，下一次 ``get_action_journal()`` 按当前数据目录重建（并回放）。"""
    global _journal
    with _journal_lock:
        _journal = None


@contextlib.contextmanager
def journaled(
    source: str,
    action: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    runtime_session_id: Optional[str] = None,
) -> Iterator[JournalEntry]:
    """把一次动手包进「先记意图、后记结果」。

    ``with`` 体里可以是 ``await`` —— 被取消时 ``CancelledError`` 会落进这里，记成
    ``unknown_after_cancel`` 后原样抛出（取消不被吞）。体内可以设置 ``entry.outcome``
    / ``entry.error`` 来报告「调用没抛异常、但动作没成功」。
    """
    if runtime_session_id is None:
        from core.liminal_activity import current_runtime_session_id

        runtime_session_id = current_runtime_session_id()
    journal = get_action_journal()
    entry = journal.begin(source, action, params, runtime_session_id)
    try:
        yield entry
    except asyncio.CancelledError:
        journal.end(entry, OUTCOME_UNKNOWN_CANCEL)
        raise
    except Exception as exc:
        journal.end(entry, OUTCOME_FAILED, f"{type(exc).__name__}: {exc}")
        raise
    else:
        journal.end(entry, entry.outcome or OUTCOME_OK, entry.error)
