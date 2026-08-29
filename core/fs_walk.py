"""
core/fs_walk.py
===============
稳健的目录树遍历 —— **脚下的目录消失，不该把整轮扫描炸掉**。

这个模块修的是一个已复现的真实缺陷,不是防御性编程。

复现过程
--------
``launcher/doctor.py`` 的体检在 CI 上报过一次 ``FileNotFoundError``,单跑复现不了。
拿真实脚本压出来的 traceback 是::

    for p in Path(ROOT).rglob("*.py"):
      File "pathlib.py", line 397, in _iterate_directories
      File "pathlib.py", line 386, in _iterate_directories
        with scandir(parent_path) as scandir_it:
      File "pathlib.py", line 938, in _scandir
        return os.scandir(self)
    FileNotFoundError: [Errno 2] No such file or directory: '.../n8421'

原因在 CPython 的 ``pathlib`` 里:``_RecursiveWildcardSelector._iterate_directories``
对 ``scandir`` 只捕 ``PermissionError``::

    try:
        with scandir(parent_path) as scandir_it:   # ← 目录此刻消失就抛 FileNotFoundError
            ...
    except PermissionError:                        # ← 只挡权限,挡不住"没了"
        return

于是**遍历途中任何一个子目录被删掉,异常直接从迭代器穿透到调用方**。而调用方普遍写成::

    for path in root.rglob("*.py"):
        try:
            path.read_text(...)      # ← try 只包住循环体
        except OSError:
            continue                 # ← 包不住迭代器本身

——保护的位置正好差一层。

哪些改了、哪些没改
------------------
仓库里有九处这个形状,但**风险不均等**,所以只改真正会踩到的四处:

改了(扫的是**活的、正在被别人改的目录**):

* ``launcher/doctor.py``             —— 就是它报的那次红。它被测试调用,而并发跑的
  另一个 pytest 进程正在仓库里建删临时目录;
* ``scripts/cleanup_logs.py``        —— 一边遍历日志根一边删日志(自己动自己);
* ``core/crash_log_aggregator.py``   —— 遍历正在轮转的日志目录;
* ``nodes/Node_120_File``            —— 遍历**用户指定**的任意目录,用户那边随时在动。

Node_120 那处后果最直接:用户搜文件时目录一变,整个节点调用抛 ``FileNotFoundError``,
而它和上面几行"根路径不存在"抛的是同一个异常类型 —— 用户根本分不清是自己路径写错了,
还是扫描中途撞上了并发改动。

没改(``scripts/check_wiring`` / ``check_reachability`` / ``check_evidence_anchors`` /
``audit_udm_write_paths`` / ``check_debt_freeze``):形状一样,但它们是**独立跑在静态
检出上的 CI 门**,各自一个 job、同时没有别的东西在改那棵树 —— 风险是理论上的。而让
"检查 core/ 的门"反过来 import ``core/`` 是把门和被检对象耦在一起:``core/`` 一坏,
门就跑不起来了。这个代价换一个理论风险不划算。**哪天这些门开始并发跑,再回来改。**

设计
----
用 ``os.walk``(它对 ``scandir`` 的错误天然不致命)重写,并且:

* **自顶向下剪枝** —— ``skip_dirs`` 在下降前就剪掉,不是"全扫完再过滤"。原来
  ``check_wiring`` / ``check_reachability`` 都是 rglob 之后再 ``if ... in p.parts``
  过滤;改成剪枝是为了**语义干净**(不该看的目录根本不下降),**不是为了快** ——
  本仓实测:剪枝版扫全仓 ``*.py`` 87ms,裸 ``rglob`` 全走 68ms,**本模块反而更慢**。
  原因是逐文件的 ``PurePath.match`` 在 Python 层,比 pathlib 内部那条路径贵;省下的
  目录下降补不回来。这点差别对这些扫描器无所谓(都是几十毫秒量级的一次性检查),
  但不能反过来说成性能优化;
* **降级不静默** —— 消失或读不到的目录记进 ``unreadable``,调用方要看能看得到。
  本仓的规矩是降级可以发生、但不许悄悄发生,这里照办。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterator, List, Optional, Sequence

__all__ = ["iter_tree_files", "walk_tree_files"]

#: 扫描仓库/工程树时几乎总要跳过的目录。调用方可以覆盖,但不必每处各写一遍。
COMMON_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)


def iter_tree_files(
    root: Path,
    pattern: str = "*",
    *,
    recursive: bool = True,
    skip_dirs: Sequence[str] | frozenset = (),
    include_dirs: bool = False,
    unreadable: Optional[List[str]] = None,
) -> Iterator[Path]:
    """遍历 ``root`` 下匹配 ``pattern`` 的条目,**目录在脚下消失不会打断整轮**。

    语义与 ``Path.rglob`` / ``Path.glob`` 对齐(匹配走 :meth:`pathlib.PurePath.match`,
    所以 ``"*.py"``、``"sub/*.py"`` 这些都照旧),差别只在两点:遇到消失/无权限的目录
    是**跳过并记录**而不是抛异常;``skip_dirs`` 在下降前剪枝而不是事后过滤。

    Args:
        root: 起始目录。``root`` 自己不存在时不抛异常,只是产出为空并记进 ``unreadable``
            —— "根不存在"与"扫到一半没了"对调用方是同一件事:这棵树没得看。
            需要区分"路径写错了"的调用方应当在调用前自己 ``exists()`` 检查。
        pattern: 文件名/相对路径的 glob,如 ``"*.py"``、``"*.log"``、``"*"``。
        recursive: ``True`` 等价 ``rglob``,``False`` 等价 ``glob``(只看直接子项)。
        skip_dirs: 不下降的目录名集合(按**目录名**匹配,不是路径)。
        include_dirs: 是否也产出匹配到的**目录**。``rglob``/``glob`` 本来就会产出目录,
            所以替换那种调用、而下游又确实用得到目录时(如 Node_120 的文件搜索会把目录
            也报进结果),必须开这个开关才等价。默认关是因为绝大多数调用方紧接着就
            ``read_text``,拿到目录只会走进异常分支。
        unreadable: 可选列表;遍历途中消失或读不到的目录路径会被追加进来。
            传 ``None`` 即不关心 —— 但**降级本身仍然发生**,只是没人接收。

    Yields:
        匹配到的路径;``include_dirs=False``(默认)时只含文件。
    """
    skip = frozenset(skip_dirs)
    root = Path(root)

    def _record(path: str) -> None:
        if unreadable is not None:
            unreadable.append(path)

    def _on_error(exc: OSError) -> None:
        # os.walk 默认把 scandir 的错误**整个吞掉**(连 onerror 都不给)。这里显式接住,
        # 让"少扫了一棵子树"这件事至少留下痕迹。
        _record(getattr(exc, "filename", None) or str(exc))

    if not root.is_dir():
        _record(str(root))
        return

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=_on_error):
        if skip:
            # 原地改 dirnames 才能真正阻止 os.walk 下降(topdown 的契约)。
            dirnames[:] = [d for d in dirnames if d not in skip]

        # 先把"要产出的目录"抄下来,再决定"要不要下降" —— 两件事必须分开。
        # 合在一起写过一版:``recursive=False`` 时先把 dirnames 清空再取名字,于是
        # 非递归 + include_dirs 把目录全丢了(实测少 50 个)。而 ``glob("*")`` 是产出
        # 目录的 —— 不下降不等于不产出。
        yield_dirs = list(dirnames) if include_dirs else []
        if not recursive:
            dirnames[:] = []

        base = Path(dirpath)
        for name in [*filenames, *yield_dirs]:
            candidate = base / name
            if candidate.match(pattern):
                yield candidate


def walk_tree_files(
    root: Path,
    pattern: str = "*",
    *,
    recursive: bool = True,
    skip_dirs: Sequence[str] | frozenset = (),
    include_dirs: bool = False,
    unreadable: Optional[List[str]] = None,
) -> List[Path]:
    """:func:`iter_tree_files` 的排序物化版本。

    很多调用方原本写的是 ``sorted(root.rglob(...))`` —— 注意那种写法**同样会炸**:
    ``sorted()`` 会把迭代器跑完,异常照样在 ``sorted()`` 这一行抛出来。这里给出等价
    但不会炸的替代。
    """
    return sorted(
        iter_tree_files(
            root,
            pattern,
            recursive=recursive,
            skip_dirs=skip_dirs,
            include_dirs=include_dirs,
            unreadable=unreadable,
        )
    )
