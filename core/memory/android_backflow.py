"""
core/memory/android_backflow.py
===============================
Android ↔ 桌面大脑 的「任务记忆回流」桥。

背景（三仓一体打通点）
--------------------
Android 端(`ufo-galaxy-android`)的 `OpenClawdMemoryBackflow` 会在每次任务执行后，
把结果回流到网关的 `POST /api/v1/memory/store`，并可用 `GET /api/v1/memory/query?task_id=`
按 id 取回。但桌面端(v2)此前**从未实现这两个端点**——于是手机的任务历史既没进入
桌面的统一语义/跨模态记忆，`queryByTaskId` 也永远拿不到东西(静默失效)。

本模块补上接收侧，做两件事：
1. **精确存取**：按 Android 的 `task_id` 保存完整 `MemoryEntry`(goal/status/summary/
   steps/route_mode/timestamp)，持久化到 JSONL，支持按 id 精确取回——忠实满足
   Android 端契约(store→query 往返字段一致)。
2. **汇入统一记忆**：把任务摘要文本同时写进 `core.memory` 统一记忆层
   (`get_unified_memory().remember()`)，使手机端的任务历史进入桌面的语义/跨模态
   长程记忆，可被一句话召回。失败只告警，不影响存取。

设计：单例 + 线程锁；启动时从 JSONL 载入索引；任何依赖缺失都优雅降级。
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("Galaxy.Memory.AndroidBackflow")

# Android MemoryEntry 的字段(见 OpenClawdMemoryBackflow.kt)
#: 一条回流事件的字段。
#:
#: ``device_id`` + ``seq`` 是后补的,补它们不是为了多两个字段,是为了让这里能成为一本
#: **账本**:设备各自维护单调序号,断网时在本地缓存、联网后补传 —— 补传必然产生重复,
#: 而 (device_id, seq) 就是判重的唯一依据。少了这一对,重复与乱序都无从识别。
#:
#: 序号刻意**不由服务端分配**:服务端分配的号只反映"到达顺序",而断网缓存要保住的恰恰
#: 是"发生顺序"。两者在补传场景下必然不同,那正是需要序号的那个场景。
_ENTRY_FIELDS = (
    "task_id",
    "device_id",
    "seq",
    "goal",
    "status",
    "summary",
    "steps",
    "route_mode",
    "timestamp_ms",
)


def _data_dir() -> str:
    d = os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")
    return d


class AndroidMemoryBackflow:
    """task_id 索引的任务记忆回流存储(+ 汇入统一记忆)。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        base = path or os.path.join(_data_dir(), "android_task_backflow.jsonl")
        self._path = base
        #: 全部事件,按到达顺序。这才是账本本体。
        self._events: List[Dict[str, Any]] = []
        #: 派生视图:每个 task 的最新态。**必须保留** —— /api/v1/memory/query 返回
        #: ``[entry]``,而 Android 侧是 parseFirstEntry 取第一条;若改成返回全部历史,
        #: 安卓拿到的会是**最旧**那条,而且不报错。
        self._index: Dict[str, Dict[str, Any]] = {}
        #: 已见过的 (device_id, seq)。补传去重用。
        self._seen: Set[Tuple[str, int]] = set()
        self._load()

    # ── 持久化 ──────────────────────────────────────────────────────────
    def _load(self) -> None:
        n_bad = 0
        try:
            if not os.path.exists(self._path):
                return
            with open(self._path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        # 改前这里是 self._index[tid] = e —— 后写覆盖。文件本身是追加写
                        # 的,历史一直躺在磁盘上,但重启之后每个 task 只剩最后一条,中间
                        # 步骤全部消失。追加写却在载入时坍缩,等于白追加。
                        self._accept(json.loads(line), persist=False)
                    except Exception:
                        # 此前是裸 continue:损坏行被静默丢弃,而下面那句只报
                        # 载入成功的条数 —— 一个半数损坏的文件看起来和完整文件
                        # 一模一样,调用方无从知道记忆缺了一块。
                        n_bad += 1
                        continue
            # 报事件数与任务数两个 —— 只报其中一个都会误导:载入 900 条事件、
            # 落在 3 个任务上,和载入 3 条事件是完全不同的两件事。
            if n_bad:
                logger.warning(
                    "Android 回流记忆:%d 行损坏已跳过(载入 %d 条事件 / %d 个任务): %s",
                    n_bad,
                    len(self._events),
                    len(self._index),
                    self._path,
                )
            logger.info(
                "Android 回流记忆载入 %d 条事件 / %d 个任务: %s",
                len(self._events),
                len(self._index),
                self._path,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("android backflow load skipped: %s", exc)

    def _append(self, entry: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug("android backflow append skipped: %s", exc)

    def _accept(self, e: Dict[str, Any], *, persist: bool) -> bool:
        """收下一条事件。已经见过的 ``(device_id, seq)`` 返回 False 且不收。

        **调用方须持有 self._lock**(``_load`` 在构造期独占,``store`` 显式持锁)。

        去重只在 device_id 与 seq 都给全时才可能发生。两者缺一就退化成"照单全收" ——
        这是刻意的:发送侧还没补上这两个字段时,不应该因为"没有序号"就把事件丢掉或者
        把不同事件误判成同一条。宁可暂时不去重,不可误删。
        """
        tid = str(e.get("task_id", "")).strip()
        if not tid:
            return False

        dev = str(e.get("device_id") or "").strip()
        seq = e.get("seq")
        key: Optional[Tuple[str, int]] = None
        if dev and isinstance(seq, int):
            key = (dev, seq)
            if key in self._seen:
                return False

        self._events.append(e)
        self._index[tid] = e
        if key is not None:
            self._seen.add(key)
        if persist:
            self._append(e)
        return True

    # ── 公开 API ────────────────────────────────────────────────────────
    def store(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """保存一条 Android 任务记忆。返回规范化后的 entry。

        会精确按 task_id 落盘，并把摘要文本汇入统一语义/跨模态记忆。
        """
        norm = {k: entry.get(k) for k in _ENTRY_FIELDS}
        tid = str(norm.get("task_id") or "").strip()
        if not tid:
            tid = f"android_{int(time.time() * 1000)}"
            norm["task_id"] = tid
        if not norm.get("timestamp_ms"):
            norm["timestamp_ms"] = int(time.time() * 1000)
        if not isinstance(norm.get("steps"), list):
            norm["steps"] = [] if norm.get("steps") is None else [str(norm["steps"])]

        with self._lock:
            fresh = self._accept(norm, persist=True)
        if not fresh:
            # 补传重复:已经收过同一条 (device_id, seq)。直接返回规范化结果,
            # 调用方看到的仍是成功 —— 幂等的定义就是"重复提交与提交一次结果相同"。
            return norm

        # 汇入统一记忆(语义/跨模态)——best-effort，失败不影响存取
        try:
            self._mirror_to_unified(norm)
        except Exception as exc:  # noqa: BLE001
            logger.debug("mirror android entry to unified memory skipped: %s", exc)
        return norm

    def _mirror_to_unified(self, e: Dict[str, Any]) -> None:
        from core.memory import get_unified_memory

        goal = str(e.get("goal") or "").strip()
        summ = str(e.get("summary") or "").strip()
        status = str(e.get("status") or "").strip()
        steps = e.get("steps") or []
        text_parts = [f"[Android任务] {goal}"] if goal else ["[Android任务]"]
        if status:
            text_parts.append(f"结果:{status}")
        if summ:
            text_parts.append(summ)
        if steps:
            text_parts.append("步骤:" + " / ".join(str(s) for s in steps[:10]))
        content = "  ".join(text_parts).strip()
        if content:
            get_unified_memory().remember(
                content,
                metadata={
                    "source": "android_backflow",
                    "task_id": e.get("task_id"),
                    "status": status,
                    "route_mode": e.get("route_mode"),
                },
            )

    def get(self, task_id: str) -> Optional[Dict[str, Any]]:
        tid = str(task_id or "").strip()
        if not tid:
            return None
        with self._lock:
            return self._index.get(tid)

    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        """最近 n 条**事件**,新的在前。

        改前这里取的是 ``_index.values()`` —— 每个任务只有最新一条,所以"最近 20 条"
        实际是"最近 20 个任务的终态"。一个跑了三十步的任务在里面只占一行,中间发生过
        什么完全看不到,而那恰恰是"最近发生了什么"这个问题想问的东西。
        """
        with self._lock:
            items = sorted(
                self._events,
                key=lambda e: e.get("timestamp_ms", 0),
                reverse=True,
            )
        return items[: max(1, min(n, 200))]

    def history(self, task_id: str) -> List[Dict[str, Any]]:
        """一个任务的全部事件,按发生顺序。没有则空列表。

        与 :meth:`get` 的分工:``get`` 回答"这个任务现在什么状态"(给 Android 的
        parseFirstEntry 用),``history`` 回答"这个任务是怎么走到这一步的"。
        """
        tid = str(task_id or "").strip()
        if not tid:
            return []
        with self._lock:
            return [e for e in self._events if str(e.get("task_id", "")).strip() == tid]

    def count(self) -> int:
        with self._lock:
            return len(self._index)


# ── 单例 ────────────────────────────────────────────────────────────────
_instance: Optional[AndroidMemoryBackflow] = None
_instance_lock = threading.Lock()


def get_android_backflow() -> AndroidMemoryBackflow:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = AndroidMemoryBackflow()
    return _instance


def reset_android_backflow() -> None:
    """测试用：清空单例。"""
    global _instance
    with _instance_lock:
        _instance = None
