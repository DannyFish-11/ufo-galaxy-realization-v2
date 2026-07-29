"""core/react_progress.py — ReAct 循环的结果分类与进展检测。

本模块**不是**另一个循环。它是给 ``core.openclawd._react_loop`` 用的两个判断
原语,补上那条循环里仅有的两块空白:

1. :func:`classify_tool_outcome` —— **失败分类学**。
   原实现是二元的::

       status = SUCCESS if result.get("success", True) else ERROR

   于是"工具根本不存在"和"网络抖了一下"被当成同一种失败,循环无从判断
   "该重试还是该换路"。更要命的是 ``default=True``:处理器万一没带 ``success``
   键,就被**默认判成功** —— 与 L4 那条"未知命令返回 unknown 却记 SUCCESS"
   是同一个病,只不过这条在活路径上。

2. :class:`ProgressTracker` —— **无进展检测**。
   原实现只看"连续同名工具 3 次"。它拦得住 ``A A A``,拦不住:

   - ``A B A B A B`` —— 两个工具互相打转,每一步都不是"连续同名";
   - ``A(x) … A(x)`` —— 同名同参在中间隔了别的调用后重来,计数器已被清零;
   - 反复撞同一个错误 —— 参数每次都不同,但错误一模一样。

   这三种都是模型卡住的典型形态,原检测一个都看不见,只能靠 20 次总限频
   兜底 —— 那意味着白烧 20 次工具调用和十几轮 LLM 才停。

设计纪律:纯函数 + 无状态构造,不碰全局、不做 I/O,任何一处判断失误都只
影响"要不要早停",不改变工具本身的执行语义。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Deque, Dict, Tuple

__all__ = [
    "ToolOutcome",
    "classify_tool_outcome",
    "ProgressTracker",
    "ProgressVerdict",
]


class ToolOutcome(str, Enum):
    """一次工具调用的**性质**(而不只是成/败)。"""

    SUCCESS = "success"
    """真的成了。"""

    DENIED = "denied"
    """权限拒绝 / 需要用户确认。**不是失败**,是需要升级给人,重试毫无意义。"""

    PERMANENT = "permanent"
    """确定性失败:工具不存在、前缀未知、参数非法。重试同样的调用必然再失败,
    模型应当换工具或换参数,而不是重来一遍。"""

    TRANSIENT = "transient"
    """瞬时失败:超时、连接被拒、暂时不可用。**只有这一类值得重试**。"""

    FAILED = "failed"
    """工具真的执行了但没成(业务失败)。可以带着错误信息让模型自纠。"""

    CONTRACT_VIOLATION = "contract_violation"
    """处理器返回体里根本没有 ``success`` 键 —— 违反了 ``_dispatch_tool_call``
    的返回契约。**按失败处理并点名**,绝不默认判成功:静默放行会让"其实没干成"
    一路伪装成"干成了"流进对话与记忆。"""

    @property
    def is_success(self) -> bool:
        return self is ToolOutcome.SUCCESS

    @property
    def retriable(self) -> bool:
        """是否值得原样重试。只有瞬时故障配。"""
        return self is ToolOutcome.TRANSIENT


#: 判定为"瞬时"的错误特征(大小写不敏感)。
_TRANSIENT_PATTERNS = (
    r"\btimed?\s*out\b",
    r"\btimeout\b",
    r"执行超时",
    r"\bconnection (refused|reset|aborted|error)\b",
    r"\btemporarily unavailable\b",
    r"\bservice unavailable\b",
    r"\b(?:429|502|503|504)\b",
    r"\brate limit",
    r"暂时不可用",
    r"连接失败",
)

#: 判定为"确定性"的错误特征 —— 重试一万次也一样。
_PERMANENT_PATTERNS = (
    r"未知工具前缀",
    r"\bunknown tool\b",
    r"\bno such tool\b",
    r"工具不存在",
    r"未注册",
    r"\bnot registered\b",
    r"无效 ?MCP 工具名",
    r"\binvalid tool name\b",
    r"参数校验失败",
    r"\bvalidation (failed|error)\b",
    r"\bmissing required\b",
    r"缺少必填",
)

#: 判定为"被拒/待确认"的错误特征。
_DENIED_PATTERNS = (
    r"权限拒绝",
    r"\bpermission denied\b",
    r"\bnot allowed\b",
    r"需要用户确认",
    r"\brequires confirmation\b",
)

_TRANSIENT_RE = re.compile("|".join(_TRANSIENT_PATTERNS), re.IGNORECASE)
_PERMANENT_RE = re.compile("|".join(_PERMANENT_PATTERNS), re.IGNORECASE)
_DENIED_RE = re.compile("|".join(_DENIED_PATTERNS), re.IGNORECASE)


def classify_tool_outcome(result: Any) -> ToolOutcome:
    """把 ``_dispatch_tool_call`` 的返回体分类。

    :param result: 工具返回体。约定是
        ``{"success": bool, "result": Any, "error": Optional[str]}``。
    :returns: 该次调用的 :class:`ToolOutcome`。

    判定顺序是刻意的:

    1. 不是 dict → 契约违反(拿不到 success,不能猜);
    2. ``needs_confirmation`` → DENIED(即便 success=False,它也不是"失败");
    3. 没有 ``success`` 键 → 契约违反(**不默认成功**);
    4. ``success=True`` → SUCCESS;
    5. 否则按 error 文本细分 DENIED / PERMANENT / TRANSIENT,兜底 FAILED。
    """
    if not isinstance(result, dict):
        return ToolOutcome.CONTRACT_VIOLATION

    # 需要确认排在最前:这类返回里 success 恒为 False,但把它算作"失败"会让
    # 模型以为工具坏了而去重试,正确动作是把确认请求交给人。
    if result.get("needs_confirmation"):
        return ToolOutcome.DENIED

    if "success" not in result:
        return ToolOutcome.CONTRACT_VIOLATION

    if result.get("success"):
        return ToolOutcome.SUCCESS

    error_text = str(result.get("error") or "")
    if _DENIED_RE.search(error_text):
        return ToolOutcome.DENIED
    if _PERMANENT_RE.search(error_text):
        return ToolOutcome.PERMANENT
    if _TRANSIENT_RE.search(error_text):
        return ToolOutcome.TRANSIENT
    return ToolOutcome.FAILED


# ---------------------------------------------------------------------------
# 无进展检测
# ---------------------------------------------------------------------------

#: 判定"卡住"所需的重复次数。
REPEAT_THRESHOLD = 3

#: 判定"两个工具互相打转"所需的完整来回次数(A B A B → 2 个来回)。
THRASH_THRESHOLD = 3

#: 判定"反复撞同一个错误"所需次数。
SAME_ERROR_THRESHOLD = 3

#: 观察窗口长度(只看最近 N 次调用,避免长任务里早期历史误触发)。
WINDOW = 12


@dataclass(frozen=True)
class ProgressVerdict:
    """一次进展判定的结果。"""

    stuck: bool
    """是否判定为卡住。"""

    reason: str = ""
    """人话原因,可直接作为回喂给模型的系统提示。"""

    kind: str = ""
    """机器可读的类别:``repeat`` / ``thrash`` / ``same_error``。"""


def _fingerprint(tool_name: str, arguments: Any) -> str:
    """(工具名 + 参数)的稳定指纹。

    参数用 ``sort_keys`` 序列化,保证同一组参数不因 dict 顺序不同而算成两次。
    不可序列化的参数退回 ``repr``(仍然稳定,只是可能偏保守)。
    """
    try:
        payload = json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        payload = repr(arguments)
    digest = hashlib.sha256(f"{tool_name}\x00{payload}".encode("utf-8", "replace")).hexdigest()
    return digest[:16]


def _normalize_error(text: str) -> str:
    """把错误文本里的数字归一化,让"同一个错误、不同时间戳/ID"能被认出来。"""
    return re.sub(r"\d+", "#", (text or "").strip())[:200]


class ProgressTracker:
    """跨迭代观察工具调用序列,判断模型是不是在原地打转。

    只读地累积观测,不做任何副作用。调用方在每次工具调用**之后**
    :meth:`record`,拿到的 :class:`ProgressVerdict` 若 ``stuck`` 为真,
    就该早停并把 ``reason`` 作为系统提示回喂给模型。
    """

    def __init__(
        self,
        *,
        repeat_threshold: int = REPEAT_THRESHOLD,
        thrash_threshold: int = THRASH_THRESHOLD,
        same_error_threshold: int = SAME_ERROR_THRESHOLD,
        window: int = WINDOW,
    ) -> None:
        self.repeat_threshold = repeat_threshold
        self.thrash_threshold = thrash_threshold
        self.same_error_threshold = same_error_threshold
        self._calls: Deque[Tuple[str, str]] = deque(maxlen=window)
        self._fp_counts: Dict[str, int] = {}
        self._error_counts: Dict[str, int] = {}

    def record(self, tool_name: str, arguments: Any, outcome: ToolOutcome, error: str = "") -> ProgressVerdict:
        """登记一次调用并给出进展判定。"""
        fp = _fingerprint(tool_name, arguments)
        self._calls.append((tool_name, fp))
        self._fp_counts[fp] = self._fp_counts.get(fp, 0) + 1

        # ① 同名同参重复 —— 不要求相邻,中间隔了别的调用照样算。
        if self._fp_counts[fp] >= self.repeat_threshold:
            return ProgressVerdict(
                stuck=True,
                kind="repeat",
                reason=(
                    f"[系统] 已用完全相同的参数调用 {tool_name} {self._fp_counts[fp]} 次,"
                    "结果不会改变。请换一个工具或换一组参数,或直接根据已有信息给出最终回答。"
                ),
            )

        # ② 两个工具互相打转(A B A B …)。
        if len(self._calls) >= self.thrash_threshold * 2:
            recent = list(self._calls)[-self.thrash_threshold * 2 :]
            names = [n for n, _ in recent]
            if len(set(names)) == 2 and all(names[i] != names[i + 1] for i in range(len(names) - 1)):
                a, b = names[0], names[1]
                return ProgressVerdict(
                    stuck=True,
                    kind="thrash",
                    reason=(
                        f"[系统] 检测到在 {a} 与 {b} 之间反复来回 {self.thrash_threshold} 轮而没有进展。"
                        "请停止交替调用,直接根据已有信息给出最终回答。"
                    ),
                )

        # ③ 反复撞同一个错误(参数可以不同,错误一模一样)。
        if not outcome.is_success and error:
            key = _normalize_error(error)
            self._error_counts[key] = self._error_counts.get(key, 0) + 1
            if self._error_counts[key] >= self.same_error_threshold:
                return ProgressVerdict(
                    stuck=True,
                    kind="same_error",
                    reason=(
                        f"[系统] 同一个错误已重复出现 {self._error_counts[key]} 次:{key[:120]}。"
                        "继续沿这条路走不通,请换方案或直接说明为什么办不到。"
                    ),
                )

        return ProgressVerdict(stuck=False)
