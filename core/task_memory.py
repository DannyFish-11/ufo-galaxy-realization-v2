"""
core/task_memory.py
====================
C阶段 4B — 任务记忆 / 长期记忆

功能：
  - 持久化任务摘要到本地文件（JSON Lines，data/task_memory.jsonl）
  - 提供 record_task() 写入一条任务摘要
  - 提供 get_recent_summaries(n) 读取最近 N 条摘要
  - 提供 inject_into_context() 将最近 N 条摘要注入执行上下文
  - 保持最小实现，向后兼容（不依赖外部向量库）

使用示例:
    from core.task_memory import get_task_memory

    mem = get_task_memory()

    # 记录一条任务摘要
    mem.record_task(
        task="搜索 Python 教程",
        result_summary="找到 5 篇教程",
        success=True,
        strategy="single",
    )

    # 在执行上下文中注入最近 3 条摘要
    context = []
    context = mem.inject_into_context(context, n=3)
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TaskMemory")

_DEFAULT_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_MEMORY_FILE = "task_memory.jsonl"
_MAX_IN_MEMORY = 200  # 内存中保留的最大条数
_CONTEXT_MARKER = "[TaskMemory]"  # 注入上下文时的标记，避免重复注入
_MAX_TASK_LENGTH = 500    # 任务描述最大存储长度（字符）
_MAX_SUMMARY_LENGTH = 300  # 结果摘要最大存储长度（字符）


# ============================================================================
# 数据模型
# ============================================================================

@dataclass
class TaskSummary:
    """单条任务执行摘要。"""
    summary_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    timestamp: float = field(default_factory=time.time)
    task: str = ""
    """原始任务描述（可截断）"""
    result_summary: str = ""
    """执行结果摘要"""
    success: bool = True
    strategy: str = ""
    """执行策略: single / specialized / swarm / fractal"""
    duration_ms: float = 0.0
    session_id: str = ""
    tags: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskSummary":
        return cls(
            summary_id=data.get("summary_id", str(uuid.uuid4())[:12]),
            timestamp=data.get("timestamp", 0.0),
            task=data.get("task", ""),
            result_summary=data.get("result_summary", ""),
            success=data.get("success", True),
            strategy=data.get("strategy", ""),
            duration_ms=data.get("duration_ms", 0.0),
            session_id=data.get("session_id", ""),
            tags=data.get("tags", []),
            extra=data.get("extra", {}),
        )

    def to_text(self) -> str:
        """转换为可读文本（注入 context 时使用）。"""
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(self.timestamp))
        status = "✓" if self.success else "✗"
        return (
            f"[{ts}] {status} {self.task[:80]}"
            + (f" → {self.result_summary[:100]}" if self.result_summary else "")
            + (f" (策略:{self.strategy})" if self.strategy else "")
        )


# ============================================================================
# TaskMemory
# ============================================================================

class TaskMemory:
    """本地文件持久化任务记忆。"""

    def __init__(self, data_dir: str = None):
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        os.makedirs(self._data_dir, exist_ok=True)
        self._file = os.path.join(self._data_dir, _MEMORY_FILE)
        self._records: List[TaskSummary] = []
        self._load_recent(_MAX_IN_MEMORY)

    # ── 写入 ──

    def record_task(
        self,
        task: str,
        result_summary: str = "",
        success: bool = True,
        strategy: str = "",
        duration_ms: float = 0.0,
        session_id: str = "",
        tags: List[str] = None,
        extra: Dict[str, Any] = None,
    ) -> TaskSummary:
        """记录一条任务摘要，持久化到本地文件。"""
        entry = TaskSummary(
            task=task[:_MAX_TASK_LENGTH],  # 截断避免过长
            result_summary=result_summary[:_MAX_SUMMARY_LENGTH],
            success=success,
            strategy=strategy,
            duration_ms=duration_ms,
            session_id=session_id,
            tags=tags or [],
            extra=extra or {},
        )
        self._records.append(entry)
        # 保持内存上限
        if len(self._records) > _MAX_IN_MEMORY:
            self._records = self._records[-_MAX_IN_MEMORY:]
        # 持久化
        self._append_to_file(entry)
        return entry

    # ── 读取 ──

    def get_recent_summaries(self, n: int = 5) -> List[TaskSummary]:
        """返回最近 n 条任务摘要（从内存中读取，内存不足则从文件补充）。"""
        if len(self._records) >= n:
            return list(self._records[-n:])
        # 内存条数不够，从文件重新加载
        self._load_recent(max(_MAX_IN_MEMORY, n))
        return list(self._records[-n:])

    def inject_into_context(
        self,
        context: List[Dict[str, str]],
        n: int = 3,
    ) -> List[Dict[str, str]]:
        """将最近 n 条任务摘要注入到 context（对话历史）中。

        若 context 中已有 [TaskMemory] 标记，则跳过注入（幂等）。

        Returns:
            注入后的 context（原始 context 不被修改）
        """
        # 幂等检查
        if any(_CONTEXT_MARKER in c.get("content", "") for c in context):
            return context

        summaries = self.get_recent_summaries(n)
        if not summaries:
            return context

        lines = [s.to_text() for s in summaries]
        hint_content = (
            f"{_CONTEXT_MARKER} 最近 {len(lines)} 条任务记忆（供参考）:\n"
            + "\n".join(f"  {i+1}. {line}" for i, line in enumerate(lines))
        )
        hint = {"role": "system", "content": hint_content}
        # 在历史最前面插入（不覆盖用户消息）
        return [hint] + list(context)

    def get_stats(self) -> Dict[str, Any]:
        """返回统计信息。"""
        total = len(self._records)
        successful = sum(1 for r in self._records if r.success)
        strategies = {}
        for r in self._records:
            if r.strategy:
                strategies[r.strategy] = strategies.get(r.strategy, 0) + 1
        return {
            "total": total,
            "successful": successful,
            "failed": total - successful,
            "strategy_distribution": strategies,
        }

    # ── 内部方法 ──

    def _load_recent(self, n: int) -> None:
        """从文件加载最近 n 条记录到内存。"""
        if not os.path.exists(self._file):
            return
        try:
            lines: List[str] = []
            with open(self._file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        lines.append(line)
            # 只取最后 n 条
            recent = lines[-n:] if len(lines) > n else lines
            loaded = []
            for line in recent:
                try:
                    data = json.loads(line)
                    loaded.append(TaskSummary.from_dict(data))
                except Exception:
                    pass
            self._records = loaded
        except Exception as e:
            logger.warning("TaskMemory: 加载文件失败: %s", e)

    def _append_to_file(self, entry: TaskSummary) -> None:
        """追加一条记录到文件。"""
        try:
            with open(self._file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("TaskMemory: 写入文件失败: %s", e)


# ============================================================================
# 单例
# ============================================================================

_instance: Optional[TaskMemory] = None


def get_task_memory(data_dir: str = None) -> TaskMemory:
    """返回全局单例 TaskMemory（首次调用时创建）。"""
    global _instance
    if _instance is None:
        _instance = TaskMemory(data_dir=data_dir)
    return _instance
