"""运行时数据目录的唯一取法：``$GALAXY_DATA_DIR``，没设就是相对当前目录的 ``data/``（与此前写死的一致）。

新加的持久化点用 ``data_path("runtime", "x.json")``，别再写死 ``"data/..."`` —— 写死的那几处（网络图、
拓扑、节点注册表、委托执行追踪、成本账本、Agent 状态、设备注册快照）在 ``GALAXY_DATA_DIR`` 指到别处时
（容器、``tests/conftest.py`` 的隔离目录）会被劈成两处：别的状态写新目录，它们仍写源码树里的 ``data/``。
"""

from __future__ import annotations

import os


def data_path(*parts: str) -> str:
    """``$GALAXY_DATA_DIR/<parts>``；``GALAXY_DATA_DIR`` 没设（或为空）时为 ``data/<parts>``。"""
    base = (os.environ.get("GALAXY_DATA_DIR") or "").strip() or "data"
    return os.path.join(base, *parts)
