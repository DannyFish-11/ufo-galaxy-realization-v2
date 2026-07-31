"""
原子化 JSON 落盘
================

仓库里有大量"把状态写成 JSON 文件"的持久化点(幂等记录、设备令牌、任务生命周期、
peer 信任表、会话快照……)。它们此前多数是这么写的::

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)

这种写法在**进程被杀 / 机器断电 / 磁盘写满**时会留下一个被截断的半个 JSON,
下次启动 ``json.load`` 直接抛异常 —— 而这些文件恰恰是崩溃后最需要能读回来的那批。
更隐蔽的是:``open(path, "w")`` 在真正写入前就把原文件**清空**了,所以失败的结果
不是"保留旧值",而是"旧值也没了"。

正确做法是写临时文件再 ``os.replace`` —— 后者在 POSIX 上是原子的,在 Windows 上
自 Python 3.3 起也是覆盖式原子替换。读者要么看到完整的旧内容,要么看到完整的新内容,
不存在中间态。

本模块把这套逻辑收敛成一个函数。实现原样沿用 ``core.runtime_truth_governance``
里那份已经在跑的版本(含陈旧临时文件清扫),额外加了 ``fsync``:
``os.replace`` 只保证"替换"这一步原子,不保证新内容已经落到盘上;不 fsync 的话,
断电仍可能得到一个"替换成功但内容是空洞"的文件。
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any

#: 临时文件前缀。带上固定前缀才能在崩溃后把遗留的碎片认出来并清掉。
TMP_PREFIX = ".tmp-atomic-"

#: 超过这个秒数的临时文件视为上次崩溃的残留,写入前顺手清掉,避免无限堆积。
STALE_TMP_SECONDS = 6 * 60 * 60


def sweep_stale_tmp_files(directory: str, *, max_age: float = STALE_TMP_SECONDS) -> None:
    """清掉目录里遗留的过期临时文件。任何失败都吞掉 —— 清扫是尽力而为,不能反过来
    让真正的写入失败。"""
    try:
        for name in os.listdir(directory):
            if not (name.startswith(TMP_PREFIX) and name.endswith(".json")):
                continue
            candidate = os.path.join(directory, name)
            try:
                if time.time() - os.path.getmtime(candidate) > max_age:
                    os.remove(candidate)
            except OSError:
                pass
    except OSError:
        pass


def atomic_write_json(
    path: str | os.PathLike,
    payload: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    sort_keys: bool = False,
    default: Any = None,
    trailing_newline: bool = False,
    fsync: bool = True,
) -> None:
    """把 ``payload`` 原子地写成 ``path`` 处的 JSON 文件。

    失败时的保证:目标文件要么是**完整的旧内容**,要么是**完整的新内容**。
    序列化异常(payload 里有不可序列化的对象)会在临时文件阶段就抛出,此时目标文件
    一个字节都没动过 —— 这正是相对 ``open(path,"w")`` 的关键改进。

    :param sort_keys: 默认 ``False``。注意 ``runtime_truth_governance`` 那份历史实现
        是 ``True``,那里靠键序稳定来做内容比对,所以它保留自己的默认值;通用场景不该
        被迫改变键序,故此处默认关闭。
    :param default: 透传给 ``json.dump``,用于序列化它不认识的对象(常见写法
        ``default=str``)。存在这个参数是为了让本函数能**原样承接**既有调用点 ——
        改造持久化不该顺手改变落盘内容。
    :param trailing_newline: 在 JSON 之后补一个换行。同上,某些调用点原本就写了
        ``fh.write("\\n")``,保留该行为可使文件字节级不变。
    :param fsync: 替换前把临时文件刷到磁盘。默认开启;仅在明确不在乎断电丢失、且写入
        极其频繁的路径上才值得关掉。
    """
    path = os.fspath(path)
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    sweep_stale_tmp_files(directory)

    # 临时文件必须和目标【同目录】:os.replace 跨文件系统会失败,而 /tmp 与目标
    # 往往不在同一个挂载点上。
    fd, tmp_path = tempfile.mkstemp(prefix=TMP_PREFIX, suffix=".json", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(
                payload,
                handle,
                indent=indent,
                ensure_ascii=ensure_ascii,
                sort_keys=sort_keys,
                default=default,
            )
            if trailing_newline:
                handle.write("\n")
            handle.flush()
            if fsync:
                os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    finally:
        # 走到这里若临时文件还在,说明 replace 没发生(序列化抛了 / 写盘失败),清掉碎片。
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
