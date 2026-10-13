"""core/truth_chain_recovery.py — 真相链没收口的结果：后台补跑一次，仍不行就隔离待处理。

所有者的决定（2026-09-28）：``task_result`` 的四步真相链不完整时，**自动重试，失败再隔离**。

- **不挡用户**。回答照常先交出去；补跑排在后台、延迟 :data:`RETRY_DELAY_S` 秒、只跑一次。
- **只重跑失败的那几步**（:func:`~core.task_result_canonical_truth_chain.rerun_failed_steps`）。
  成功过的步骤不再执行 —— 真相写入、生命周期推进都不该做两遍。
- 补跑收口了 → 从 :class:`~core.task_result_canonical_truth_chain.IncompleteResultLedger` 撤掉，
  记进近期「已补齐」（有界，可审计）。
- 仍不收口 → 进**隔离队列**：落盘在 ``$GALAXY_DATA_DIR/isolated_results.json``，重启后还在；
  ``GET /api/v1/results/isolated`` 列出，面板「全部设置」最上面一段显示。人可以
  「再试一次」（同样只重跑失败步骤）或「知悉」（标 ``dismissed``，记录保留）。

判据只看 :class:`~core.task_result_canonical_truth_chain.TruthChainOutcome` 的类型化 status 字段，
与 ``_compute_completeness`` 同一口径；不从日志或文本里反解。

时机：调用方正处在事件循环里 → ``loop.call_later``（仍在循环线程上跑，与原处理同线程）；
不在 → 守护线程 ``threading.Timer``。两者都不阻塞调用方。

对外接口只给类型化字段（任务号、状态、失败步骤、原因、时间）。原始结果消息只留在本机存储里
供补跑使用，**不经接口返回**。

不止 ``task_result`` 一种（所有者 2026-10-13 选 A）
------------------------------------------------
Computer Use 的结果也走这条真相链：模型说「做完了」只是它的自报，独立核对没通过就是**没收口**
（:mod:`core.computer_use_verdict`）。这类条目带 ``kind``（如 ``"computer_use"``），补跑不是「重跑失败的
真相链步骤」，而是交给按 ``kind`` 登记的重跑器（:func:`register_rerunner`）—— 同样后台一次、仍不行进隔离队列、
人可以「再试一次」或「知悉」。

人对一条没收口的结果有三种处置（运维的「重开 / 驳回 / 确认闭环」就落在这三个上）：

* **再试一次**（重开）：``task_result`` 只重跑失败步骤；其它 ``kind`` 交给它的重跑器，在后台做；
* **知悉**（驳回）：标 ``dismissed`` —— 判它没做成，记录保留；
* **认可**（确认）：标 ``accepted`` —— 人看过了，认它做完了，记录保留。
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import threading
from collections import OrderedDict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

RETRY_DELAY_S: float = 5.0
"""没收口到补跑之间等多久。给瞬时故障（依赖刚重连、锁刚释放）留出恢复时间。"""

MAX_ISOLATED: int = 500
"""隔离队列上限。满了先挤掉最早的「已知悉」，再挤最早的。"""

MAX_RETAINED_MESSAGE_BYTES: int = 64 * 1024
"""原始消息超过这个大小就不留（隔离项仍在，只是不能再试）。"""

_RECENT_RECOVERED: int = 200

STATE_ISOLATED = "isolated"
STATE_DISMISSED = "dismissed"
STATE_RECOVERED = "recovered"
STATE_ACCEPTED = "accepted"

KIND_TASK_RESULT = "task_result"

#: ``kind`` → 重跑器:拿着留存的那份 ``message`` 再做一次,回 ``(收口没有, 原因)``。第二个参数说这次是不是人点的
#: (人点「再试一次」时不该因为「有人在用电脑」而不做 —— 点的就是那个人)。
Rerunner = Callable[[Dict[str, Any], bool], Awaitable[Tuple[bool, str]]]
_RERUNNERS: Dict[str, Rerunner] = {}

#: 重启之后队列里还留着某类条目、而它的重跑器还没被登记时,去哪儿找(按需 import、调它的 ``register()``)。
_RERUNNER_HOMES: Dict[str, str] = {"computer_use": "core.computer_use_verdict"}


def register_rerunner(kind: str, fn: Rerunner) -> None:
    """登记一种结果的重跑器(``task_result`` 之外的 kind 用)。"""
    _RERUNNERS[kind] = fn


def _rerunner(kind: str) -> Optional[Rerunner]:
    if kind not in _RERUNNERS and kind in _RERUNNER_HOMES:
        try:
            import importlib

            importlib.import_module(_RERUNNER_HOMES[kind]).register()
        except Exception as exc:  # noqa: BLE001
            logger.warning("truth_chain_recovery: %s 的重跑器登记不上: %s", kind, exc)
    return _RERUNNERS.get(kind)


_STORE_FILENAME = "isolated_results.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_store_path() -> Path:
    base = os.environ.get("GALAXY_DATA_DIR", "").strip()
    root = Path(base) if base else Path(__file__).resolve().parent.parent / "data"
    return root / _STORE_FILENAME


def _snapshot(message: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return copy.deepcopy(dict(message))
    except Exception:  # noqa: BLE001 — 深拷贝不了就浅拷贝，补跑只读它
        return dict(message)


def _device_id(message: Dict[str, Any]) -> str:
    payload = message.get("payload") if isinstance(message.get("payload"), dict) else {}
    return str(message.get("device_id") or payload.get("device_id") or "")


def _raised_steps(outcome: Any) -> List[str]:
    """哪几步是**抛了异常**（而不是模块缺席）没走通。

    只记步骤名，不记异常原文：记录会经接口外露，异常文本可能带内部细节（CodeQL
    py/stack-trace-exposure）。原文由各步骤自己的 ``logger.warning`` 写进日志，排障看日志。
    """
    from core.task_result_canonical_truth_chain import TRUTH_CHAIN_STEPS

    return [
        name for name, (_attr, exc_attr) in TRUTH_CHAIN_STEPS.items() if getattr(outcome, exc_attr, None) is not None
    ]


class TruthChainRecovery:
    """补跑排期 + 隔离队列。进程内单例见 :func:`get_truth_chain_recovery`。"""

    def __init__(self, *, store_path: Optional[Path] = None, delay_s: float = RETRY_DELAY_S) -> None:
        self._lock = threading.RLock()
        self._explicit_store_path = store_path
        self._store_path: Optional[Path] = None
        self.delay_s = delay_s
        # 排着队等补跑的：key → {"outcome", "message", "first_seen_at"}
        self._pending: Dict[str, Dict[str, Any]] = {}
        # 别的 kind 排着队等重跑的：key → {"kind", "record", "message", "first_seen_at"}
        self._pending_reruns: Dict[str, Dict[str, Any]] = {}
        self._timers: Dict[str, Any] = {}
        self._isolated: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
        self._recovered: Deque[Dict[str, Any]] = deque(maxlen=_RECENT_RECOVERED)
        self._loaded = False
        self._anon = 0
        # 后台重跑的协程:事件循环只弱引用 task,不留一份会被回收掉、跑到一半没了
        self._tasks: Set["asyncio.Task[Any]"] = set()

    # ------------------------------------------------------------------ 排期

    def schedule(self, outcome: Any, message: Dict[str, Any]) -> str:
        """登记一条没收口的结果，并排一次后台补跑。返回它在队列里的键。"""
        with self._lock:
            key = outcome.task_id
            if not key:
                self._anon += 1
                key = f"_notask_{self._anon}"
            already_armed = key in self._timers
            self._pending[key] = {"outcome": outcome, "message": _snapshot(message), "first_seen_at": _now()}
            if already_armed:
                # 同一任务又来一次没收口的结果：用新的这份，不重复排期。
                return key
            self._timers[key] = self._arm(key)
            return key

    def _arm(self, key: str) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            timer = threading.Timer(self.delay_s, self.run_pending, args=(key,))
            timer.daemon = True
            timer.start()
            return timer
        return loop.call_later(self.delay_s, self.run_pending, key)

    def run_pending(self, key: str) -> Optional[Dict[str, Any]]:
        """补跑 *key*（到点由计时器调用；测试可直接调）。返回处置结果，没有这条则 ``None``。"""
        with self._lock:
            self._timers.pop(key, None)
            entry = self._pending.pop(key, None)
        if entry is None:
            return None
        return self._retry_and_settle(key, entry["outcome"], entry["message"], entry["first_seen_at"], attempts=2)

    def _retry_and_settle(
        self,
        key: str,
        outcome: Any,
        message: Dict[str, Any],
        first_seen_at: str,
        *,
        attempts: int,
        first_reason: str = "",
    ) -> Dict[str, Any]:
        from core.task_result_canonical_truth_chain import (
            TRUTH_CHAIN_STEPS,
            failed_steps,
            get_incomplete_result_ledger,
            rerun_failed_steps,
        )

        before = failed_steps(outcome)
        try:
            retried = rerun_failed_steps(outcome, message)
        except Exception as exc:  # noqa: BLE001 — 补跑自己炸了也要落到隔离里，不能丢
            logger.warning("truth_chain_recovery: retry raised key=%r exc=%s", key, exc)  # 原文只进日志
            retried, raised = outcome, True
        else:
            raised = False

        if retried.is_truth_chain_complete and not raised:
            if outcome.task_id:
                get_incomplete_result_ledger().discard(outcome.task_id)
            record = {
                "key": key,
                "task_id": outcome.task_id,
                "result_status": outcome.result_status,
                "state": STATE_RECOVERED,
                "retried_steps": before,
                "first_seen_at": first_seen_at,
                "settled_at": _now(),
                "attempts": attempts,
            }
            with self._lock:
                self._recovered.append(record)
                self._ensure_loaded()
                if self._isolated.pop(key, None) is not None:
                    self._save()
            logger.info("truth_chain_recovery: recovered key=%r steps=%s", key, before)
            return record

        record = {
            "key": key,
            "task_id": outcome.task_id,
            "result_status": outcome.result_status,
            "device_id": _device_id(message),
            "message_type": str(message.get("type") or ""),
            "state": STATE_ISOLATED,
            "first_incomplete_reason": first_reason or outcome.incomplete_reason,
            "incomplete_reason": retried.incomplete_reason or outcome.incomplete_reason,
            "failed_steps": failed_steps(retried) or before,
            "step_status": {attr: getattr(retried, attr) for attr, _exc in TRUTH_CHAIN_STEPS.values()},
            "raised_steps": _raised_steps(retried),
            "retry_raised": raised,
            "first_seen_at": first_seen_at,
            "settled_at": _now(),
            "attempts": attempts,
        }
        retained = self._retainable(message)
        with self._lock:
            self._ensure_loaded()
            self._isolated.pop(key, None)
            self._isolated[key] = dict(record, message=retained)
            self._evict()
            self._save()
        logger.warning(
            "truth_chain_recovery: isolated key=%r failed_steps=%s reason=%r",
            key,
            record["failed_steps"],
            record["incomplete_reason"],
        )
        self._tell_the_island()
        return record

    # ------------------------------------------------------------------ 别的 kind(如 Computer Use)

    def schedule_rerun(self, key: str, kind: str, record: Dict[str, Any], message: Dict[str, Any]) -> str:
        """登记一条 ``kind`` 类的没收口结果,``delay_s`` 秒后交给它的重跑器在后台再做一次;仍不收口进隔离队列。

        必须在事件循环里调用(重跑器是协程)。
        """
        with self._lock:
            if key in self._timers:
                return key
            self._pending_reruns[key] = {
                "kind": kind,
                "record": dict(record),
                "message": _snapshot(message),
                "first_seen_at": _now(),
            }
            loop = asyncio.get_running_loop()
            self._timers[key] = loop.call_later(
                self.delay_s, lambda: self._keep(loop.create_task(self.run_pending_rerun(key)))
            )
        return key

    def _keep(self, task: "asyncio.Task[Any]") -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def run_pending_rerun(self, key: str) -> Optional[Dict[str, Any]]:
        """到点重跑 *key*(计时器调用;测试可直接 await)。"""
        with self._lock:
            self._timers.pop(key, None)
            entry = self._pending_reruns.pop(key, None)
        if entry is None:
            return None
        return await self._rerun_and_settle(
            key, entry["kind"], entry["record"], entry["message"], entry["first_seen_at"], attempts=2
        )

    async def _rerun_and_settle(
        self,
        key: str,
        kind: str,
        record: Dict[str, Any],
        message: Dict[str, Any],
        first_seen_at: str,
        *,
        attempts: int,
        by_human: bool = False,
    ) -> Dict[str, Any]:
        fn = _rerunner(kind)
        if fn is None:
            closed, reason = False, f"没有登记 {kind} 的重跑器"
        else:
            try:
                closed, reason = await fn(message, by_human)
            except Exception as exc:  # noqa: BLE001 — 重跑自己炸了也要落到隔离里,不能丢
                logger.warning("truth_chain_recovery: rerun raised key=%r kind=%s exc=%s", key, kind, exc)
                closed, reason = False, f"重跑出错: {type(exc).__name__}"
        if closed:
            done = {
                "key": key,
                "kind": kind,
                "task_id": record.get("task_id", ""),
                "state": STATE_RECOVERED,
                "first_seen_at": first_seen_at,
                "settled_at": _now(),
                "attempts": attempts,
                "recovered_reason": reason,
            }
            with self._lock:
                self._recovered.append(done)
                self._ensure_loaded()
                if self._isolated.pop(key, None) is not None:
                    self._save()
            logger.info("truth_chain_recovery: recovered key=%r kind=%s", key, kind)
            if kind == "computer_use":
                from core.island_cards import post_card

                post_card(
                    f"truth_chain:recovered:{key}",
                    kind="result",
                    title="补做完了",
                    subtitle="后台把没做完的部分做完了,核对通过",
                    tone="success",
                )
            return done
        return self.isolate(key, kind, record, message, reason, first_seen_at=first_seen_at, attempts=attempts)

    def isolate(
        self,
        key: str,
        kind: str,
        record: Dict[str, Any],
        message: Dict[str, Any],
        reason: str,
        *,
        first_seen_at: str = "",
        attempts: int = 1,
    ) -> Dict[str, Any]:
        """直接把一条 ``kind`` 类结果放进隔离队列(不排后台重跑),比如人正在用电脑、不该在后台动键鼠时。"""
        row = {
            **record,
            "key": key,
            "kind": kind,
            "state": STATE_ISOLATED,
            "first_incomplete_reason": record.get("first_incomplete_reason") or record.get("incomplete_reason", ""),
            "incomplete_reason": reason,
            "first_seen_at": first_seen_at or _now(),
            "settled_at": _now(),
            "attempts": attempts,
        }
        row.pop("retrying", None)
        retained = self._retainable(message)
        with self._lock:
            self._ensure_loaded()
            self._isolated.pop(key, None)
            self._isolated[key] = dict(row, message=retained)
            self._evict()
            self._save()
        logger.warning("truth_chain_recovery: isolated key=%r kind=%s reason=%r", key, kind, reason)
        self._tell_the_island()
        return row

    def _tell_the_island(self) -> None:
        """灵动岛上提一句「有结果没收口」(core.island_cards):一张汇总卡,不是一条一张。只有条数,不带内容。"""
        with self._lock:
            n = sum(1 for r in self._isolated.values() if r.get("state") == STATE_ISOLATED)
        if not n:
            return
        from core.island_cards import post_card

        post_card(
            "truth_chain:isolated",
            kind="result",
            title="有结果没收口",
            subtitle=f"{n} 条等你看 · 面板「全部设置」最上面",
            body="回答当时已经交出去了;这些结果后台补过一次仍没核实,要你看一眼:再试一次、认可,或知道了。",
            tone="warning",
            ttl_s=15,
            action="panel",
        )

    def _retry_kind(self, key: str, row: Dict[str, Any]) -> Dict[str, Any]:
        """人工「再试一次」—— 非 ``task_result`` 的条目:交给它的重跑器在后台做(可能要几十秒,不让请求干等)。"""
        message = row.get("message")
        if not isinstance(message, dict):
            return dict(self._public(row), retry_refused="message_not_retained")
        with self._lock:
            live = self._isolated.get(key)
            if live is not None and live.get("retrying"):
                return dict(self._public(live), state="retrying")
            if live is not None:
                live["retrying"] = True
                self._save()
        base = {k: v for k, v in row.items() if k != "message"}
        run = self._rerun_and_settle(
            key,
            str(row.get("kind")),
            base,
            message,
            row.get("first_seen_at") or _now(),
            attempts=int(row.get("attempts") or 2) + 1,
            by_human=True,
        )
        try:
            self._keep(asyncio.get_running_loop().create_task(run))
        except RuntimeError:  # 不在事件循环里(脚本 / 测试):就地跑完
            return asyncio.run(run)
        return dict(self._public(row), state="retrying")

    def accept(self, key: str) -> Optional[Dict[str, Any]]:
        """人工「认可」:人看过了、认它做完了。标 ``accepted``,记录保留。没有这条返回 ``None``。"""
        with self._lock:
            self._ensure_loaded()
            row = self._isolated.get(key)
            if row is None:
                return None
            row["state"] = STATE_ACCEPTED
            row["accepted_at"] = _now()
            row.pop("retrying", None)
            self._save()
            return self._public(row)

    def find_by_task_id(self, task_id: str) -> Optional[str]:
        """按任务号找它在队列里**还没收口**的那条(运维动作按任务号来);已认可 / 已知悉的不算,找不到返回 ``None``。"""
        if not task_id:
            return None
        with self._lock:
            self._ensure_loaded()
            for key, row in reversed(self._isolated.items()):
                if row.get("state") == STATE_ISOLATED and task_id in (key, row.get("task_id")):
                    return key
        return None

    @staticmethod
    def _retainable(message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        try:
            raw = json.dumps(message, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return None
        if len(raw.encode("utf-8")) > MAX_RETAINED_MESSAGE_BYTES:
            return None
        return json.loads(raw)

    # ------------------------------------------------------------------ 隔离队列（对外）

    def isolated(self, *, include_dismissed: bool = False) -> List[Dict[str, Any]]:
        """隔离项列表（新的在前）。不含原始消息，只有 ``message_retained`` 一个布尔。"""
        with self._lock:
            self._ensure_loaded()
            rows = [self._public(r) for r in self._isolated.values()]
        if not include_dismissed:
            rows = [r for r in rows if r["state"] == STATE_ISOLATED]  # 已知悉 / 已认可的只在要求时列出
        rows.reverse()
        return rows

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            self._ensure_loaded()
            row = self._isolated.get(key)
            return self._public(row) if row else None

    def retry_isolated(self, key: str) -> Optional[Dict[str, Any]]:
        """人工「再试一次」：同样只重跑失败步骤。补齐了就移出队列；没有这条返回 ``None``。"""
        from core.task_result_canonical_truth_chain import StepStatus, TruthChainOutcome

        with self._lock:
            self._ensure_loaded()
            row = self._isolated.get(key)
            if row is None:
                return None
            row = dict(row)
        if row.get("kind", KIND_TASK_RESULT) != KIND_TASK_RESULT:
            return self._retry_kind(key, row)
        message = row.get("message")
        if not isinstance(message, dict):
            return dict(self._public(row), retry_refused="message_not_retained")
        statuses = row.get("step_status") or {}
        outcome = TruthChainOutcome(
            task_id=row.get("task_id") or "",
            result_status=row.get("result_status") or "",
            truth_ingress_status=statuses.get("truth_ingress_status", StepStatus.COMPLETED),
            reconcile_status=statuses.get("reconcile_status", StepStatus.COMPLETED),
            authority_update_status=statuses.get("authority_update_status", StepStatus.COMPLETED),
            completion_linkage_status=statuses.get("completion_linkage_status", StepStatus.COMPLETED),
            incomplete_reason=row.get("incomplete_reason") or "",
        )
        return self._retry_and_settle(
            key,
            outcome,
            message,
            row.get("first_seen_at") or _now(),
            attempts=int(row.get("attempts") or 2) + 1,
            first_reason=row.get("first_incomplete_reason") or "",
        )

    def dismiss(self, key: str) -> Optional[Dict[str, Any]]:
        """人工「知悉」：标 ``dismissed``，记录保留（审计用）。没有这条返回 ``None``。"""
        with self._lock:
            self._ensure_loaded()
            row = self._isolated.get(key)
            if row is None:
                return None
            row["state"] = STATE_DISMISSED
            row["dismissed_at"] = _now()
            self._save()
            return self._public(row)

    def recent_recovered(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(reversed(self._recovered))

    def summary(self) -> Dict[str, Any]:
        with self._lock:
            self._ensure_loaded()
            states = [r.get("state") for r in self._isolated.values()]
            return {
                "pending_retry": len(self._pending) + len(self._pending_reruns),
                "isolated": states.count(STATE_ISOLATED),
                "dismissed": states.count(STATE_DISMISSED),
                "accepted": states.count(STATE_ACCEPTED),
                "recovered_recent": len(self._recovered),
                "retry_delay_s": self.delay_s,
            }

    @staticmethod
    def _public(row: Dict[str, Any]) -> Dict[str, Any]:
        out = {k: v for k, v in row.items() if k != "message"}
        out.setdefault("kind", KIND_TASK_RESULT)
        out["message_retained"] = isinstance(row.get("message"), dict)
        return out

    # ------------------------------------------------------------------ 存储

    def _path(self) -> Path:
        if self._store_path is None:
            self._store_path = self._explicit_store_path or _default_store_path()
        return self._store_path

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        path = self._path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for row in data.get("entries") or []:
                if isinstance(row, dict) and row.get("key"):
                    self._isolated[row["key"]] = row
        except Exception as exc:  # noqa: BLE001 — 存储坏了不能让结果处理跟着坏；从空开始并留痕
            logger.warning("truth_chain_recovery: store unreadable path=%s exc=%s", path, exc)

    def _evict(self) -> None:
        while len(self._isolated) > MAX_ISOLATED:
            victim = next((k for k, r in self._isolated.items() if r.get("state") == STATE_DISMISSED), None)
            self._isolated.pop(victim if victim is not None else next(iter(self._isolated)))

    def _save(self) -> None:
        path = self._path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            body = {"version": 1, "entries": list(self._isolated.values())}
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            os.replace(tmp, path)
        except Exception as exc:  # noqa: BLE001 — 落盘失败：内存里仍在、接口仍可见
            logger.warning("truth_chain_recovery: store write failed path=%s exc=%s", path, exc)

    # ------------------------------------------------------------------ 测试

    def reset(self) -> None:
        """取消所有未到点的补跑并清空内存状态（不删盘上的文件）。"""
        with self._lock:
            for handle in self._timers.values():
                try:
                    handle.cancel()
                except Exception:  # noqa: BLE001
                    pass
            self._timers.clear()
            for task in list(self._tasks):
                task.cancel()
            self._tasks.clear()
            self._pending.clear()
            self._pending_reruns.clear()
            self._isolated.clear()
            self._recovered.clear()
            self._loaded = False
            self._store_path = None


_recovery: Optional[TruthChainRecovery] = None
_recovery_lock = threading.Lock()


def get_truth_chain_recovery() -> TruthChainRecovery:
    """进程内单例。"""
    global _recovery
    with _recovery_lock:
        if _recovery is None:
            _recovery = TruthChainRecovery()
        return _recovery


__all__ = [
    "KIND_TASK_RESULT",
    "MAX_ISOLATED",
    "RETRY_DELAY_S",
    "STATE_ACCEPTED",
    "STATE_DISMISSED",
    "STATE_ISOLATED",
    "STATE_RECOVERED",
    "TruthChainRecovery",
    "get_truth_chain_recovery",
    "register_rerunner",
]
