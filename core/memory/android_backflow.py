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
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Memory.AndroidBackflow")

# Android MemoryEntry 的字段(见 OpenClawdMemoryBackflow.kt)
_ENTRY_FIELDS = ("task_id", "goal", "status", "summary", "steps", "route_mode", "timestamp_ms")


def _data_dir() -> str:
    d = os.getenv("GALAXY_DATA_DIR", "").strip() or os.path.join(os.getcwd(), "data")
    return d


class AndroidMemoryBackflow:
    """task_id 索引的任务记忆回流存储(+ 汇入统一记忆)。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        base = path or os.path.join(_data_dir(), "android_task_backflow.jsonl")
        self._path = base
        self._index: Dict[str, Dict[str, Any]] = {}
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
                        e = json.loads(line)
                        tid = str(e.get("task_id", "")).strip()
                        if tid:
                            self._index[tid] = e  # 后写覆盖
                    except Exception:
                        # 此前是裸 continue:损坏行被静默丢弃,而下面那句只报
                        # 载入成功的条数 —— 一个半数损坏的文件看起来和完整文件
                        # 一模一样,调用方无从知道记忆缺了一块。
                        n_bad += 1
                        continue
            if n_bad:
                logger.warning(
                    "Android 回流记忆:%d 行损坏已跳过(成功载入 %d 条): %s",
                    n_bad,
                    len(self._index),
                    self._path,
                )
            logger.info("Android 回流记忆载入 %d 条: %s", len(self._index), self._path)
        except Exception as exc:  # noqa: BLE001
            logger.debug("android backflow load skipped: %s", exc)

    def _append(self, entry: Dict[str, Any]) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001
            logger.debug("android backflow append skipped: %s", exc)

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
            self._index[tid] = norm
            self._append(norm)

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
        with self._lock:
            items = sorted(
                self._index.values(),
                key=lambda e: e.get("timestamp_ms", 0),
                reverse=True,
            )
        return items[: max(1, min(n, 200))]

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
