"""core.continuum_readout — 只读地看一眼活的 continuum

为什么单独成模块
----------------
两套渲染契约都要用它：一维遗留投影（``core.phase_posture_legacy``）与双轴忠实
契约（``core.phase_contract``）。把它留在其中任何一边，另一边就得反向依赖，
拆开时必然出现循环导入。它本身也确实是一件独立的事：**在不构造任何东西的前提下，
读进程里已经存在的那份状态**。

刻意的边界
----------
* **绝不构造**。``core.openclawd.get_openclawd()`` 会**创建** OpenClawd 实例，
  而本模块的调用方是在场桥的每一拍。用 ``sys.modules.get`` 只看已经被导入过的
  模块，看不到就返回 ``None``。
* **零依赖**。只用标准库，导入代价可以忽略 —— 调用方（``phase_contract``）
  自身约 6ms 且被每一次相位事件调用，这里再加负担是不行的。
"""

from __future__ import annotations

import sys
from typing import Any, Optional

__all__ = ["last_continuum_posture", "clamp"]


# ---------------------------------------------------------------------------
# 取数（只读，绝不构造）
# ---------------------------------------------------------------------------


def last_continuum_posture() -> Optional[Any]:
    """取最近一拍 :class:`~core.continuum.types.ContinuumState`，拿不到返回 None。

    **绝不构造任何东西**：只读进程里已经存在的实例。三种情况直接返回 None：

    * ``core.openclawd`` 还没被 import（例如只跑了在场桥的进程）；
    * OpenClawd 单例还没建；
    * 还没跑过一次 continuum（``_continuum_orchestrator`` 或 ``_last_state`` 为 None）。

    刻意用 ``sys.modules.get`` 而不是 ``import core.openclawd``：后者会真的执行
    模块导入（这个模块很重），而本函数可能在每一次相位事件里被调到。
    """
    mod = sys.modules.get("core.openclawd")
    if mod is None:
        return None
    inst = getattr(mod, "_openclawd_instance", None)
    if inst is None:
        return None
    orch = getattr(inst, "_continuum_orchestrator", None)
    if orch is None:
        return None
    return getattr(orch, "_last_state", None)


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def clamp(v: float, lo: float, hi: float) -> float:
    """夹紧到 [lo, hi]。两套契约都用它做归一量的最后一道保险。"""
    return lo if v < lo else (hi if v > hi else v)
