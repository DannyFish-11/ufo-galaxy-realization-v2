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

本模块把这套逻辑收敛成一个函数。骨架取自 ``core.runtime_truth_governance`` 里那份
已经在跑的实现,但有两处刻意的不同:

* 加了 ``fsync`` —— ``os.replace`` 只保证"替换"这一步原子,不保证新内容已经落到盘上;
  不 fsync 的话,断电仍可能得到一个"替换成功但内容是空洞"的文件。
* **不做**目录清扫(原因见下方 TMP_PREFIX 处的说明)。
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Any

#: 临时文件前缀。带上固定前缀,便于人工识别崩溃后遗留的碎片。
TMP_PREFIX = ".tmp-atomic-"

# 关于"顺手清扫目录里过期临时文件"这件事 —— 刻意不做。
#
# 初版照搬了 runtime_truth_governance 里的实现，它在每次写入前会 os.listdir 目标目录、
# 把超时的 .tmp-atomic-*.json 逐个 os.remove。在那个模块里只有一个调用点，尚可接受；
# 提升为全仓通用助手后，等于把一个【删除原语】连同调用方传入的路径一次性铺到 30 多个
# 调用点上，其中不少路径来自环境变量（SECRETVAULT_FILE、AUTH_USERS_FILE 等）。
#
# 而它取代的 open(path, "w") 从不删除任何东西 —— 这是我引入的能力扩张，不是原有行为。
# 收益也很薄：本函数在 finally 里已经清掉自己的临时文件，只有"写到一半进程被杀"才会
# 留下碎片，属于罕见情况，且碎片带固定前缀、可离线清理。
#
# 结论：写入函数就只做写入。需要清扫的话应当是一个显式的、单独调用的维护动作，
# 而不是每次落盘的隐式副作用。


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

    # 临时文件必须和目标【同目录】:os.replace 跨文件系统会失败,而 /tmp 与目标
    # 往往不在同一个挂载点上。
    fd, tmp_path = tempfile.mkstemp(prefix=TMP_PREFIX, suffix=".json", dir=directory)
    try:
        # 显式设定权限（B13）。
        #
        # mkstemp 建出来的临时文件本就是 0600，os.replace 会把这个模式一并带到目标
        # 文件上 —— 也就是说结果**碰巧**是安全的。但"碰巧"不是契约：
        #   * 谁都看不出这个 0600 是从哪来的，后来人把 mkstemp 换成 NamedTemporaryFile
        #     或 open() 就会静默变成 0644，而且没有任何测试会发现；
        #   * 本函数的调用点里有 SECRETVAULT_FILE / AUTH_USERS_FILE 这类路径。
        # 所以这里把它写成显式意图，并由 tests/test_atomic_json_permissions.py 锁住。
        #
        # 注意副作用：目标文件已存在且权限更宽时，替换后会被收紧到 0600。对本函数
        # 服务的这批文件（配置与凭据）这是想要的方向；确有共享读需求的调用点应当
        # 自行在写入后放宽，而不是让写入函数默认放宽。
        #
        # 用 fchmod(fd) 而不是 chmod(tmp_path)：
        #   1. **TOCTOU 安全**。按路径改权限要重新解析一次路径，中间存在被替换的
        #      窗口；按 fd 改权限作用于 mkstemp 刚交给我们的那个 inode，没有窗口。
        #   2. 顺带消掉 CodeQL 的 "Uncontrolled data used in path expression"
        #      —— tmp_path 派生自调用方传入的 path（部分调用点来自 SECRETVAULT_FILE
        #      等环境变量），把它从路径表达式里拿掉是对的方向，而不是加 suppress。
        #
        # Windows 没有 fchmod，且 os.chmod 在 Windows 上只切换只读位、**并不能**
        # 限制其他用户访问（那是 ACL 的事）。所以这里不在 Windows 上假装设权限 ——
        # 与之对应，tests/test_atomic_json_permissions.py 的权限断言也只在 POSIX 跑。
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
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
