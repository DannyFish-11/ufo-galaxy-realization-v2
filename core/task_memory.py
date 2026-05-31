"""
core/task_memory.py
====================
C阶段 4B — 任务记忆 / 长期记忆
G6 增强: TTL / 冷热分层 / 漂移检测

功能：
  - 持久化任务摘要到本地文件（JSON Lines，data/task_memory.jsonl）
  - 提供 record_task() 写入一条任务摘要（支持 task_type 字段，向后兼容）
  - 提供 get_recent_summaries(n, task_type) 读取最近 N 条摘要（可按类型过滤）
  - 提供 inject_into_context() 将最近 N 条摘要注入执行上下文
  - TTL 支持：热区记录超时后自动排除（ttl_seconds=0 禁用，向后兼容）
  - 冷热分层：热区（最近 hot_limit 条）驻内存；超出部分为冷区，可通过
    query_cold_storage(n, task_type) 按需查询
  - 漂移检测：check_consistency() 对比新结果与缓存摘要；超阈值触发
    "rerun" 或 "human_review"（通过 configure_drift() 配置）
  - 保持最小实现，向后兼容（不依赖外部向量库）

使用示例:
    from core.task_memory import get_task_memory

    mem = get_task_memory()

    # 记录一条任务摘要（含类型）
    mem.record_task(
        task="搜索 Python 教程",
        result_summary="找到 5 篇教程",
        success=True,
        strategy="single",
        task_type="search",
    )

    # 在执行上下文中注入最近 3 条摘要
    context = []
    context = mem.inject_into_context(context, n=3)

    # 查询冷区历史（按类型）
    cold = mem.query_cold_storage(n=20, task_type="search")

    # 漂移检测
    result = mem.check_consistency(
        task_key="搜索 Python 教程",
        new_result="找到 3 篇教程",
        task_type="search",
    )
    if result.is_drift:
        print(f"漂移! 相似度={result.similarity:.2f}, 动作={result.action}")
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
_MAX_IN_MEMORY = 200  # 热区默认大小（向后兼容）
_CONTEXT_MARKER = "[TaskMemory]"  # 注入上下文时的标记，避免重复注入
_MAX_TASK_LENGTH = 500    # 任务描述最大存储长度（字符）
_MAX_SUMMARY_LENGTH = 300  # 结果摘要最大存储长度（字符）

# G6: 漂移检测默认值
_DEFAULT_DRIFT_THRESHOLD = 0.5   # Jaccard 相似度低于此值视为漂移
_DEFAULT_DRIFT_ACTION = "human_review"  # "rerun" | "human_review" | "none"


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
    # G6: 任务类型（向后兼容，旧记录反序列化时默认为空字符串）
    task_type: str = ""

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
            task_type=data.get("task_type", ""),  # G6: 旧记录兼容
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


# G6: 漂移检测结果
@dataclass
class DriftCheckResult:
    """漂移检测结果。"""
    is_drift: bool = False
    similarity: float = 1.0   # 0.0–1.0；越高越相似
    action: str = "none"      # "none" | "rerun" | "human_review"
    threshold: float = _DEFAULT_DRIFT_THRESHOLD
    cached_summary: Optional[str] = None
    task_key: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_drift": self.is_drift,
            "similarity": self.similarity,
            "action": self.action,
            "threshold": self.threshold,
            "cached_summary": self.cached_summary,
            "task_key": self.task_key,
        }


# ============================================================================
# 内部工具函数
# ============================================================================

def _text_similarity(a: str, b: str) -> float:
    """词级 Jaccard 相似度 (0.0–1.0)。空字符串视为无内容；两者均空返回 1.0。"""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    set_a = set(a.lower().split())
    set_b = set(b.lower().split())
    if not set_a and not set_b:
        return 1.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


# ============================================================================
# TaskMemory
# ============================================================================

class TaskMemory:
    """本地文件持久化任务记忆（含 TTL / 冷热分层 / 漂移检测）。

    参数:
        data_dir:      持久化目录（默认 data/）
        hot_limit:     热区最大条数，默认 200（与旧版 _MAX_IN_MEMORY 一致）
        ttl_seconds:   热区 TTL（秒）；0 表示不过期（向后兼容默认值）
    """

    def __init__(
        self,
        data_dir: str = None,
        hot_limit: int = _MAX_IN_MEMORY,
        ttl_seconds: float = 0.0,
    ):
        self._data_dir = data_dir or _DEFAULT_DATA_DIR
        os.makedirs(self._data_dir, exist_ok=True)
        self._file = os.path.join(self._data_dir, _MEMORY_FILE)
        self._hot_limit = hot_limit
        self._ttl_seconds = ttl_seconds  # 0 = 不过期
        # G6: 漂移检测配置
        self._drift_threshold: float = _DEFAULT_DRIFT_THRESHOLD
        self._drift_action: str = _DEFAULT_DRIFT_ACTION
        self._records: List[TaskSummary] = []
        self._load_recent(self._hot_limit)

    # ── 漂移检测配置 (G6) ──

    def configure_drift(
        self,
        threshold: float = _DEFAULT_DRIFT_THRESHOLD,
        action: str = _DEFAULT_DRIFT_ACTION,
    ) -> None:
        """配置漂移检测参数。

        参数:
            threshold: Jaccard 相似度阈值（0.0–1.0）；低于此值视为漂移
            action:    漂移时的动作："rerun" | "human_review" | "none"
        """
        if action not in ("rerun", "human_review", "none"):
            raise ValueError(
                f"action 必须为 'rerun'、'human_review' 或 'none'，实际收到: {action!r}"
            )
        self._drift_threshold = max(0.0, min(1.0, threshold))
        self._drift_action = action

    def get_drift_config(self) -> Dict[str, Any]:
        """返回当前漂移检测配置。"""
        return {
            "threshold": self._drift_threshold,
            "action": self._drift_action,
        }

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
        task_type: str = "",  # G6: 新增，向后兼容（默认为空字符串）
    ) -> TaskSummary:
        """记录一条任务摘要，持久化到本地文件。"""
        entry = TaskSummary(
            task=task[:_MAX_TASK_LENGTH],
            result_summary=result_summary[:_MAX_SUMMARY_LENGTH],
            success=success,
            strategy=strategy,
            duration_ms=duration_ms,
            session_id=session_id,
            tags=tags or [],
            extra=extra or {},
            task_type=task_type,
        )
        self._records.append(entry)
        # 保持热区上限（溢出条目仍保留在文件中，可通过冷区查询）
        if len(self._records) > self._hot_limit:
            self._records = self._records[-self._hot_limit:]
        # 持久化
        self._append_to_file(entry)
        return entry

    # ── 读取 ──

    def get_recent_summaries(
        self,
        n: int = 5,
        task_type: Optional[str] = None,
    ) -> List[TaskSummary]:
        """返回最近 n 条任务摘要。

        参数:
            n:          返回条数上限
            task_type:  仅返回此类型的记录（空字符串或 None 表示不过滤）
        """
        candidates = self._filter_hot(task_type)
        if len(candidates) >= n:
            return list(candidates[-n:])

        if not task_type:
            # 无类型过滤：从文件重新加载（与旧版行为一致）
            self._load_recent(max(self._hot_limit, n))
            candidates = self._filter_hot(task_type)
        else:
            # 有类型过滤且热区不足：补充冷区记录
            cold = self.query_cold_storage(n=n, task_type=task_type)
            hot_ids = {r.summary_id for r in candidates}
            extra_cold = [c for c in cold if c.summary_id not in hot_ids]
            combined = list(candidates) + extra_cold
            combined.sort(key=lambda r: r.timestamp)
            candidates = combined

        return list(candidates[-n:])

    def query_cold_storage(
        self,
        n: int = 50,
        task_type: Optional[str] = None,
    ) -> List[TaskSummary]:
        """查询冷区记录（热区之外的历史记录）。

        从持久化文件中读取，跳过当前热区条目，可按 task_type 过滤。
        结果按时间降序（最新在前）返回。

        参数:
            n:          返回条数上限
            task_type:  仅返回此类型（None 或空字符串表示不过滤）
        """
        if not os.path.exists(self._file):
            return []
        hot_ids = {r.summary_id for r in self._records}
        now = time.time()
        results: List[TaskSummary] = []
        try:
            with open(self._file, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
            for line in reversed(lines):
                try:
                    data = json.loads(line)
                    entry = TaskSummary.from_dict(data)
                    if entry.summary_id in hot_ids:
                        continue
                    if self._ttl_seconds > 0 and (now - entry.timestamp) > self._ttl_seconds:
                        continue
                    if task_type and entry.task_type != task_type:
                        continue
                    results.append(entry)
                    if len(results) >= n:
                        break
                except Exception as parse_err:
                    logger.debug("TaskMemory: 冷区记录解析失败（跳过）: %s", parse_err)
        except Exception as e:
            logger.warning("TaskMemory: 查询冷区失败: %s", e)
        return results

    def evict_expired(self) -> int:
        """从热区移除已过期条目，返回移除数量。TTL 为 0 时为空操作。"""
        if self._ttl_seconds <= 0:
            return 0
        before = len(self._records)
        now = time.time()
        self._records = [
            r for r in self._records
            if (now - r.timestamp) <= self._ttl_seconds
        ]
        return before - len(self._records)

    # ── 语义压缩 (SimpleMem-inspired) ──

    def compress_turn(self, raw_text: str) -> List[str]:
        """将原始对话压缩为原子事实列表。"""
        if not raw_text or not raw_text.strip():
            return []
        sentences = re.split(r'[。\.\n]+', raw_text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        stop_words = {"的", "了", "在", "是", "和", "或", "the", "a", "is", "to", "of"}
        facts = []
        for sent in sentences:
            words = sent.split() if sent.isascii() else list(sent)
            filtered = [w for w in words if w.lower() not in stop_words]
            if len(filtered) >= 3:
                facts.append("".join(filtered) if not sent.isascii() else " ".join(filtered))
        return facts if facts else [raw_text[:200]]

    # ── 跨会话相似度检索 ──

    def retrieve_similar(self, query: str, k: int = 5, min_score: float = 0.3) -> List[TaskSummary]:
        """跨会话检索与 query 最相似的历史任务。"""
        if not query or not self._records:
            return []
        query_words = set(self._tokenize(query))
        scored = []
        for rec in self._records:
            text = f"{rec.task} {rec.result_summary}"
            text_words = set(self._tokenize(text))
            score = self.jaccard(query_words, text_words)
            if score >= min_score:
                scored.append((score, rec))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [rec for _, rec in scored[:k]]

    # ── 意图感知检索深度 ──

    def adaptive_context(self, task_query: str, depth: str = "auto") -> str:
        """根据查询意图动态选择检索深度。"""
        if depth == "auto":
            depth = "shallow" if len(task_query) < 20 else "standard" if len(task_query) < 100 else "deep"
        parts = []
        if depth == "shallow":
            parts.append(self._fmt(self.get_recent_summaries(3), "Recent"))
        elif depth == "standard":
            parts.append(self._fmt(self.get_recent_summaries(5), "Recent"))
            parts.append(self._fmt(self.retrieve_similar(task_query, 3), "Related"))
        elif depth == "deep":
            parts.append(self._fmt(self.get_recent_summaries(10), "Recent"))
            parts.append(self._fmt(self.retrieve_similar(task_query, 5), "Related"))
            facts = self.compress_turn(task_query)
            if facts:
                parts.append("Facts: " + "; ".join(facts[:5]))
        ctx = "\n".join(filter(None, parts))
        return f"\n{_CONTEXT_MARKER}\n{ctx}\n{_CONTEXT_MARKER}\n" if ctx else ""

    def _fmt(self, records, label):
        if not records:
            return ""
        lines = [f"- {r.task} → {r.result_summary[:60]}" for r in records]
        return f"{label}:\n" + "\n".join(lines)

    # ── 完整事件链 ──

    def get_event_chain(self, session_id: str) -> List[TaskSummary]:
        """获取一个会话的完整事件链。"""
        return [r for r in self._records if r.session_id == session_id]

    def get_task_lineage(self, keyword: str) -> List[TaskSummary]:
        """获取包含关键字的任务家族。"""
        return sorted(self.retrieve_similar(keyword, 10), key=lambda r: r.timestamp)

    # ── 上下文注入 (G6) ──

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

    # ── 漂移检测 (G6) ──

    def check_consistency(
        self,
        task_key: str,
        new_result: str,
        threshold: Optional[float] = None,
        action: Optional[str] = None,
        task_type: str = "",
    ) -> DriftCheckResult:
        """对比新结果与缓存摘要，检测结果漂移。

        查找策略（按优先级）：
          1. 若指定 task_type，优先在热区中匹配同类型的最近记录；
          2. 否则按 task_key 文本在热区中模糊匹配；
          3. 热区未找到则返回"无缓存"（is_drift=False, action="none"）。

        参数:
            task_key:  任务标识（任务描述文本或关键词）
            new_result: 本次执行的结果摘要
            threshold: 覆盖实例级阈值（可选）
            action:    覆盖实例级动作（可选）
            task_type: 优先匹配此类型的缓存记录

        Returns:
            DriftCheckResult
        """
        eff_threshold = threshold if threshold is not None else self._drift_threshold
        eff_action = action if action is not None else self._drift_action

        cached: Optional[TaskSummary] = None

        # 按 task_type 查找
        if task_type:
            for r in reversed(self._records):
                if r.task_type == task_type:
                    cached = r
                    break

        # 按 task_key 模糊查找
        if cached is None:
            for r in reversed(self._records):
                if task_key in r.task or r.task in task_key:
                    cached = r
                    break

        if cached is None:
            return DriftCheckResult(
                is_drift=False,
                similarity=1.0,
                action="none",
                threshold=eff_threshold,
                cached_summary=None,
                task_key=task_key,
            )

        sim = _text_similarity(cached.result_summary, new_result)
        is_drift = sim < eff_threshold
        chosen_action = eff_action if is_drift else "none"

        return DriftCheckResult(
            is_drift=is_drift,
            similarity=round(sim, 4),
            action=chosen_action,
            threshold=eff_threshold,
            cached_summary=cached.result_summary,
            task_key=task_key,
        )

    def get_stats(self) -> Dict[str, Any]:
        """返回统计信息（含 TTL / 热区配置）。"""
        total = len(self._records)
        successful = sum(1 for r in self._records if r.success)
        strategies: Dict[str, int] = {}
        task_types: Dict[str, int] = {}
        for r in self._records:
            if r.strategy:
                strategies[r.strategy] = strategies.get(r.strategy, 0) + 1
            if r.task_type:
                task_types[r.task_type] = task_types.get(r.task_type, 0) + 1
        return {
            "total": total,
            "successful": successful,
            "failed": total - successful,
            "strategy_distribution": strategies,
            # G6 新增字段
            "task_type_distribution": task_types,
            "hot_limit": self._hot_limit,
            "ttl_seconds": self._ttl_seconds,
        }

    # ── 内部方法 ──

    def _filter_hot(self, task_type: Optional[str] = None) -> List[TaskSummary]:
        """返回热区中满足条件的记录（TTL 过滤 + 可选类型过滤）。"""
        now = time.time()
        result = []
        for r in self._records:
            if self._ttl_seconds > 0 and (now - r.timestamp) > self._ttl_seconds:
                continue
            if task_type and r.task_type != task_type:
                continue
            result.append(r)
        return result

    def _load_recent(self, n: int) -> None:
        """从文件加载最近 n 条非过期记录到热区内存。"""
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
            now = time.time()
            loaded = []
            for line in recent:
                try:
                    data = json.loads(line)
                    entry = TaskSummary.from_dict(data)
                    # G6: 跳过已过期条目
                    if self._ttl_seconds > 0 and (now - entry.timestamp) > self._ttl_seconds:
                        continue
                    loaded.append(entry)
                except Exception as exc:
                    logger.warning("Exception suppressed: %s", exc)
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
