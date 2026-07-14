"""core/task_cost_ledger.py — 任务成本账本(北极星:任务总消耗,不是单次 TPS)
================================================================================

哲学对齐:问题导向 + 解决质量为主、兼顾效率——优化的是「把一个任务真正办成
所花的总资源」这个比值的分母,而不是任何单点指标(TPS/单次延迟)。
不能优化你没度量的东西:本模块把散落的度量零件(router.call_history 记单次
LLM 调用、ToolCallRecord 记单次工具调用、runtime_session_id 串生命周期)
按【任务】聚合成一张账单:

    一个 runtime session(= 用户的一次请求)结束时,聚合:
    LLM 调了几次、总输入/输出 token、工具调了几次、ReAct 几轮、总墙钟。

用法(与 llm_stream 同款 contextvars 模式,零签名侵入):

    bill = open_task_bill(trace_id, source)      # runtime.handle_request 进入时
    ... 深链内任意层: add_llm_usage(...) / add_tool_call(...) / add_react_round()
    bill = close_task_bill()                     # 结束时:落账 + 返回账单

落账三路:内存环形账本(面板/诊断即查)、JSONL 追加(跨进程/长期积累,
将来微调专属小模型的原料)、INFO 一行日志(真机肉眼可读)。
全程 try/except,账本任何故障绝不影响主流程。
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.TaskCostLedger")

_LEDGER_PATH_DEFAULT = "data/task_cost_ledger.jsonl"


@dataclass
class TaskBill:
    """一个任务(一次 runtime 请求)的成本账单。"""

    trace_id: str
    source: str = "unknown"
    started_monotonic: float = field(default_factory=time.monotonic)
    started_at: float = field(default_factory=time.time)
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0
    react_rounds: int = 0
    providers: Dict[str, int] = field(default_factory=dict)  # provider → 调用次数
    cost_usd: float = 0.0
    success: Optional[bool] = None
    wall_ms: float = 0.0

    def add_llm(self, provider: str, input_tokens: int, output_tokens: int, cost: float = 0.0) -> None:
        self.llm_calls += 1
        self.input_tokens += max(0, int(input_tokens or 0))
        self.output_tokens += max(0, int(output_tokens or 0))
        self.cost_usd += float(cost or 0.0)
        if provider:
            self.providers[provider] = self.providers.get(provider, 0) + 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "source": self.source,
            "started_at": round(self.started_at, 3),
            "wall_ms": round(self.wall_ms, 1),
            "llm_calls": self.llm_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.input_tokens + self.output_tokens,
            "tool_calls": self.tool_calls,
            "react_rounds": self.react_rounds,
            "providers": dict(self.providers),
            "cost_usd": round(self.cost_usd, 6),
            "success": self.success,
        }


# 请求级上下文:runtime 开账,深链各层记账,互不串扰(同 llm_stream 模式)。
_current_bill: contextvars.ContextVar[Optional[TaskBill]] = contextvars.ContextVar(
    "galaxy_task_bill",
    default=None,
)


class TaskCostLedger:
    """进程级账本:内存环形 + JSONL 追加。"""

    _instance: Optional["TaskCostLedger"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._recent: deque = deque(maxlen=200)

    @classmethod
    def get_instance(cls) -> "TaskCostLedger":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def commit(self, bill: TaskBill) -> None:
        record = bill.to_dict()
        self._recent.append(record)
        # 真机一行可读:这就是"任务总消耗"北极星的日常观测面
        logger.info(
            "任务账单 | %s | LLM×%d tokens(in %d/out %d) 工具×%d 轮×%d %.1fs%s",
            bill.trace_id[:12],
            bill.llm_calls,
            bill.input_tokens,
            bill.output_tokens,
            bill.tool_calls,
            bill.react_rounds,
            bill.wall_ms / 1000.0,
            "" if bill.success is None else (" ✓" if bill.success else " ✗"),
        )
        try:
            path = os.environ.get("GALAXY_TASK_LEDGER_PATH", _LEDGER_PATH_DEFAULT)
            if path and path.strip().lower() not in ("0", "off", "none"):
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                with open(path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:  # noqa: BLE001 — 落盘失败不影响主流程
            logger.debug("任务账本落盘失败(忽略): %s", exc)

    def recent(self, n: int = 20) -> List[Dict[str, Any]]:
        return list(self._recent)[-n:]

    def summary(self) -> Dict[str, Any]:
        """聚合观测:近期任务的平均总 token / 工具数 / 墙钟(优化 before/after 的标尺)。"""
        bills = list(self._recent)
        if not bills:
            return {"tasks": 0}
        n = len(bills)
        return {
            "tasks": n,
            "avg_total_tokens": round(sum(b["total_tokens"] for b in bills) / n, 1),
            "avg_output_tokens": round(sum(b["output_tokens"] for b in bills) / n, 1),
            "avg_llm_calls": round(sum(b["llm_calls"] for b in bills) / n, 2),
            "avg_tool_calls": round(sum(b["tool_calls"] for b in bills) / n, 2),
            "avg_wall_ms": round(sum(b["wall_ms"] for b in bills) / n, 1),
            "success_rate": round(sum(1 for b in bills if b.get("success")) / n, 3),
        }


def get_task_cost_ledger() -> TaskCostLedger:
    return TaskCostLedger.get_instance()


# ---------------------------------------------------------------------------
# 深链记账入口(任何层都可安全调用;无在途账单时静默无操作)
# ---------------------------------------------------------------------------


def open_task_bill(trace_id: str, source: str = "unknown") -> contextvars.Token:
    """开账并挂到当前上下文;返回 token 供 close 时复位。"""
    bill = TaskBill(trace_id=trace_id, source=source)
    return _current_bill.set(bill)


def close_task_bill(token: contextvars.Token, success: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    """结账:定格墙钟、落账、复位上下文;返回账单 dict(供挂进响应 metadata)。"""
    bill = _current_bill.get()
    _current_bill.reset(token)
    if bill is None:
        return None
    bill.wall_ms = (time.monotonic() - bill.started_monotonic) * 1000.0
    bill.success = success
    try:
        get_task_cost_ledger().commit(bill)
    except Exception as exc:  # noqa: BLE001
        logger.debug("任务账本 commit 失败(忽略): %s", exc)
    return bill.to_dict()


def add_llm_usage(provider: str, input_tokens: int, output_tokens: int, cost: float = 0.0) -> None:
    bill = _current_bill.get()
    if bill is not None:
        bill.add_llm(provider, input_tokens, output_tokens, cost)


def add_tool_call() -> None:
    bill = _current_bill.get()
    if bill is not None:
        bill.tool_calls += 1


def add_react_round() -> None:
    bill = _current_bill.get()
    if bill is not None:
        bill.react_rounds += 1


def current_task_bill() -> Optional[TaskBill]:
    return _current_bill.get()
