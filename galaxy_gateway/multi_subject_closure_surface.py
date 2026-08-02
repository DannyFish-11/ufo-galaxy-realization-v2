"""galaxy_gateway/multi_subject_closure_surface.py — 多主体闭合的对外统一出口

修的是什么
----------
``core/multi_subject_closure_machine.py``（PR-8）的模块 docstring 把它的角色写死了：

    Provides the single ``ClosureCandidate`` output type that operator /
    projection / **outward-facing layers MUST consume** instead of
    reconstructing closure decisions ad-hoc.

而全仓**零处**真正 import 过它。两条活路径都在做它禁止的事 —— 直接摘 bridge 的
``closure.completion_state``：

    galaxy_gateway/cross_device_coordinator.py   result["completion_state"] = ...
    galaxy_gateway/device_router.py              _completion_state = ...

``ClosureCandidate`` 有 13 个字段，活路径只取一个字符串。丢掉的信息是有后果的：

===============================  ============  ==============================================
场景                              活路径报的      闭合机判定
===============================  ============  ==============================================
参与者全 lost，无接管候选          ``failed``    ``participant_lost`` + 需协调
failed 但存在 degraded 参与者      ``failed``    ``failed`` + 需协调（ambiguous_failure_…）
编队声明成员但快照 0 参与者        ``failed``    ``failed`` + 需协调（empty_formation_…）
全成功                            ``success``   ``success``，不需协调
===============================  ============  ==============================================

第一行最要命：**终态种类都不同**。「全体参与者失联」被对外报成「执行失败」——
这两件事的处置完全相反（失联要等待/触发接管，失败是重试或放弃）。

为什么单独一个 surface 模块
---------------------------
两条活路径在 ``galaxy_gateway/`` 下、结构一样、都要做同一件翻译。把它放在任一侧
都会让另一侧要么重复实现、要么跨模块反向依赖。独立成一个薄出口还有两个附带好处：

* 两个调用点各自只多一行，不把 ``cross_device_coordinator.py``（1118 行）与
  ``device_router.py``（2143 行）继续推高 —— 这两个文件都已在
  ``File Complexity Budget`` 的违规清单上。
* 「对外结果长什么样」有唯一定义处，将来加字段不会两边漂。

降级语义与 ``galaxy_gateway`` 既有做法一致：闭合机不可用或快照残缺时**不抛异常**，
保持调用方原有的结果内容不变（bridge 本身在两个调用点也都是 try/except 包着的）。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger("Galaxy.MultiSubjectClosureSurface")

__all__ = ["attach_closure_candidate", "build_closure_view"]


def build_closure_view(
    bridge_snapshot: Dict[str, Any],
    *,
    recovery_device_ids: Optional[Sequence[str]] = None,
    formation_member_count: int = 0,
) -> Optional[Dict[str, Any]]:
    """把 bridge 快照交给闭合机，返回可直接并进对外结果的字段字典。

    Returns
    -------
    ``None``
        快照为空、闭合机不可用、或判定过程抛异常（降级：调用方保持原样）。
    ``dict``
        ``completion_state`` / ``reconcile_required`` / ``reconcile_triggers``
        / ``closure_candidate``（完整 ``ClosureCandidate.to_dict()``）。

    ``completion_state`` 刻意取闭合机的 ``terminal_kind`` 而**不是** bridge 的
    ``closure.completion_state`` —— 两者会给出不同答案（见模块 docstring 的表），
    而按 PR-8 的契约，闭合机才是权威。
    """
    if not bridge_snapshot:
        return None
    try:
        from core.multi_subject_closure_machine import build_closure_candidate
    except Exception as exc:  # pragma: no cover - 依赖缺失时降级
        logger.debug("multi-subject closure machine unavailable (graceful degradation): %s", exc)
        return None

    try:
        candidate = build_closure_candidate(
            bridge_snapshot,
            recovery_device_ids=recovery_device_ids,
            formation_member_count=formation_member_count,
        )
    except Exception as exc:
        logger.warning(
            "MultiSubjectClosureSurface: closure machine raised — keeping bridge-level result: %s",
            exc,
        )
        return None

    terminal_kind = getattr(candidate.terminal_kind, "value", str(candidate.terminal_kind))
    view: Dict[str, Any] = {
        "completion_state": terminal_kind,
        "reconcile_required": bool(candidate.reconcile_required),
        "reconcile_triggers": list(candidate.reconcile_triggers or []),
        "closure_candidate": candidate.to_dict(),
    }
    if candidate.reconcile_required:
        logger.info(
            "MultiSubjectClosureSurface: closure NOT sealed — terminal_kind=%s triggers=%s "
            "participants=%d (success=%d degraded=%d lost=%d failed=%d)",
            terminal_kind,
            candidate.reconcile_triggers,
            candidate.participant_count,
            candidate.success_count,
            candidate.degraded_count,
            candidate.lost_count,
            candidate.failed_count,
        )
    return view


def attach_closure_candidate(
    result: Dict[str, Any],
    bridge_snapshot: Dict[str, Any],
    *,
    recovery_device_ids: Optional[Sequence[str]] = None,
    formation_member_count: int = 0,
) -> Dict[str, Any]:
    """就地把闭合判定并进 *result* 并返回它（便于链式使用）。

    快照缺失或闭合机不可用时 *result* 原样返回 —— 调用方无需自己判空。
    """
    view = build_closure_view(
        bridge_snapshot,
        recovery_device_ids=recovery_device_ids,
        formation_member_count=formation_member_count,
    )
    if view is not None:
        result.update(view)
    return result
