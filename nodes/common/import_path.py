"""节点目录会遮蔽仓库根的同名包 —— 这里把顺序摆正。

问题
====
启动器起节点用的是 ``python main.py``,而 ``cwd`` 是**节点自己的目录**
(``launcher/nodes.py:start_node``,那是刻意的:节点按相对路径读自带资源)。
于是 ``sys.path[0]`` 就是节点目录 —— 它**排在 PYTHONPATH 前面**,而且这个位置
是 Python 自己塞的,改环境变量改不掉。

有 12 个节点在自己目录下带着一个叫 ``core`` 的子包/子目录::

    Node_15_OCR  Node_70_AutonomousLearning  Node_71_MultiDeviceCoordination
    Node_108_MetaCognition  Node_109_ProactiveSensing  Node_110_SmartOrchestrator
    Node_111_ContextManager  Node_112_SelfHealing  Node_113_AndroidVLM
    Node_116_ExternalToolWrapper  Node_117_OpenCode  Node_118_NodeFactory

对这些节点,一句朴素的 ``from core.device_types import DeviceType``(想要的是
**仓库根**的 core)会命中**节点自己的** ``core`` 包。

Node_71 实测的样子::

    File "nodes/Node_71_MultiDeviceCoordination/main.py", line 43
        from core.device_types import DeviceType
    File "nodes/Node_71_MultiDeviceCoordination/core/__init__.py", line 31
        from .device_discovery import (
    File "nodes/Node_71_MultiDeviceCoordination/core/device_discovery.py", line 18
        from ..models.device import (
    ImportError: attempted relative import beyond top-level package

最后那句报错最有迷惑性:它说的是"相对导入越界",让人以为要去改
``device_discovery.py`` 的相对导入 —— 而那句相对导入**本身是对的**
(作为 ``nodes.Node_71_MultiDeviceCoordination.core.device_discovery`` 加载时完全
成立)。真正的毛病发生在上一层:``core`` 这个名字被解析错了。

与 tests/test_node_local_module_shadowing.py 的分工
===================================================
那份守卫钉的是**另一个方向**:节点写 ``from core.X``,而 ``X`` 只有节点自己有、
仓库根没有 —— 那种写法在"被当作模块加载"时会静默降级。

这里是反方向:``X`` **只有仓库根有**,所以那份扫描器判定它合法(它确实合法),
但运行时 ``core`` 这个名字先被节点自己的包占了。两个方向都会炸,判据不同,
所以分开守。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

__all__ = ["ensure_repo_root_precedes_node_dir"]

#: 仓库根 —— 本文件在 ``<repo>/nodes/common/import_path.py``,上溯三层。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def ensure_repo_root_precedes_node_dir(node_file: Optional[str] = None) -> str:
    """把仓库根挪到 ``sys.path`` 最前面,盖过节点目录。

    在节点 ``main.py`` 里**任何 ``core.*`` / ``contracts.*`` 之类的仓库级导入之前**
    调一次::

        from nodes.common.import_path import ensure_repo_root_precedes_node_dir

        ensure_repo_root_precedes_node_dir(__file__)

        from core.device_types import DeviceType   # 现在稳稳指向仓库根

    ``nodes.common`` 这一句本身不受影响 —— 节点目录下没有叫 ``nodes`` 的东西,
    它照常从仓库根解析。

    注意这**不会**把节点目录从 ``sys.path`` 拿掉:节点自己那些按裸名字的导入
    (``import main``、uvicorn 的 ``"main:app"``)仍然要靠它。这里只改先后顺序。

    Args:
        node_file: 调用方的 ``__file__``,仅用于日志/自检;不传也能工作。

    Returns:
        仓库根的绝对路径。
    """
    root = _REPO_ROOT
    # 已经在最前面就什么都不做 —— 重复调用是安全的(节点可能被 import 多次)。
    if sys.path and os.path.abspath(sys.path[0]) == root:
        return root
    # 先摘掉别处的同一条,避免 sys.path 里堆出重复项。
    sys.path[:] = [p for p in sys.path if os.path.abspath(p or os.getcwd()) != root]
    sys.path.insert(0, root)
    return root
