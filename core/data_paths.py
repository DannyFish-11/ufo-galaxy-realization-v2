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


def data_path_or_legacy(name: str, *legacy: str) -> str:
    """``data_path(name)``；但数据目录下还没有、而旧位置已经有数据时，**继续用旧位置**。

    把默认位置挪进数据目录，不能把已经存在的数据甩在后面（向量库换了目录等于换了一套记忆，装进来的项目换了目录等于
    全都找不到）。新装的机器 —— 两处都没有 —— 一律落数据目录。
    """
    new = data_path(name)
    if os.path.exists(new):
        return new
    for old in legacy:
        if os.path.exists(old):
            return old
    return new


def state_file(name: str, legacy_dir: str, env: str = "") -> str:
    """状态文件的位置：环境变量 ``env`` 显式指定 > 数据目录下的 ``name``；旧位置（``legacy_dir/name``）上已有、
    新位置还没有时沿用旧的。"""
    explicit = (os.environ.get(env) or "").strip() if env else ""
    return explicit or data_path_or_legacy(name, os.path.join(legacy_dir, name))


def runtime_file(name: str, env: str = "") -> str:
    """原先写在 ``<当前目录>/runtime/`` 下的状态文件，现在落数据目录；``runtime/`` 里已有的继续用。"""
    return state_file(name, os.path.join(os.getcwd(), "runtime"), env)
