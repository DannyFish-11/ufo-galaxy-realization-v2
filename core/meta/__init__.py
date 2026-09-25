"""core/meta — OpenClawd 的元层：一个被学习信号闭合、并被权威边界切过一次的循环。

蓝本是 MetaRSI（arXiv 2609.06396）：改进 = 三个类型化算子的有序组合；一个 Kernel、
三个算子、每个算子只有一个可写面。artifact 结构与合并语义取自 CosmosMind-ai/rsi-harness
的源码实现。设计规格见《Galaxy 元层设计规格》。

本包刻意很轻
============
导入 ``core.meta`` 不会带起 Kernel、存储或任何算子 —— 它们都在子模块里按需导入。理由
是守卫 G10：元层**不得进热路径**（``core/openclawd.py``、``core/command_router.py``、
``core/desktop_presence_runtime.py`` 都不许 import 本包，见 :mod:`core.meta.guards`）。
每个请求都要做的「分流」判定因此不在这里。

灰度（G8）
==========
``GALAXY_META_RSI = off | shadow | on``，默认 ``off``：

* ``off``    —— Kernel 拒绝运行。系统行为与未引入元层时逐位一致（G12）。
* ``shadow`` —— 完整跑循环、落全部 artifact，但**永不生效**：补丁只在隔离工作区里验证。
* ``on``     —— 只有拿到 ``trusted`` 裁决的补丁才落到真实目录。
"""

from __future__ import annotations

import os
from typing import Tuple

META_LAYER_IS_OFF_THE_HOT_PATH: str = (
    "META_LAYER::OFF_THE_HOT_PATH: core/meta is the recursive self-improvement "
    "loop (artifacts, store, kernel, operators).  No per-request module imports "
    "it (guard G10); the per-request presence-line decision lives outside "
    "this package.  Default GALAXY_META_RSI=off leaves the system "
    "bit-for-bit unchanged."
)

META_MODES: Tuple[str, ...] = ("off", "shadow", "on")
DEFAULT_META_MODE: str = "off"
META_MODE_ENV: str = "GALAXY_META_RSI"


def meta_rsi_mode() -> str:
    """当前灰度档位；取值不认得时按 ``off`` 处理（宁可不跑，不可误跑）。"""
    raw = (os.environ.get(META_MODE_ENV, DEFAULT_META_MODE) or DEFAULT_META_MODE).strip().lower()
    return raw if raw in META_MODES else DEFAULT_META_MODE


__all__ = [
    "DEFAULT_META_MODE",
    "META_LAYER_IS_OFF_THE_HOT_PATH",
    "META_MODES",
    "META_MODE_ENV",
    "meta_rsi_mode",
]
