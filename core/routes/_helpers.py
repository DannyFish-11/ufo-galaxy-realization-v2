"""
Galaxy - Node Execution Helpers
=====================================

Shared helpers for loading and executing node fusion_entry.py modules.
Used by: nodes, agent, command, and chat route modules.
"""

import asyncio
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.API")

# Root path to the nodes/ directory
nodes_root: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "nodes"
)

# Cache of loaded node instances: node_id → node_info dict
_node_instances: Dict[str, Any] = {}


def _load_node(node_id: str, node_dir: str, fusion_entry_path: str) -> Optional[Dict]:
    """加载节点模块，支持模块级 execute 函数和类实例两种模式

    不修改 sys.path，避免跨节点导入污染。
    """
    if node_id in _node_instances:
        return _node_instances[node_id]

    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"nodes.{node_id}.fusion_entry", fusion_entry_path,
        submodule_search_locations=[node_dir]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # 模式1：模块级 execute 函数（新版 fusion_entry）
    if hasattr(module, 'execute') and callable(module.execute):
        _node_instances[node_id] = {"type": "function", "execute": module.execute, "module": module}
        return _node_instances[node_id]

    # 模式2：通过 get_node_instance() 获取类实例
    if hasattr(module, 'get_node_instance'):
        instance = module.get_node_instance()
        if hasattr(instance, 'execute'):
            _node_instances[node_id] = {"type": "instance", "instance": instance, "module": module}
            return _node_instances[node_id]

    # 模式3：查找模块中的第一个有 execute 方法的类
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and hasattr(attr, 'execute'):
            try:
                instance = attr()
                _node_instances[node_id] = {"type": "instance", "instance": instance, "module": module}
                return _node_instances[node_id]
            except Exception:
                continue

    return None


async def _execute_node(node_info: dict, action: str, params: dict):
    """执行节点操作，处理同步和异步两种方法"""
    import inspect

    if node_info["type"] == "function":
        func = node_info["execute"]
        if inspect.iscoroutinefunction(func):
            return await func(action, params)
        else:
            return await asyncio.get_running_loop().run_in_executor(
                None, func, action, params
            )
    elif node_info["type"] == "instance":
        instance = node_info["instance"]
        method = instance.execute
        if inspect.iscoroutinefunction(method):
            return await method(action, **params)
        else:
            return await asyncio.get_running_loop().run_in_executor(
                None, lambda: method(action, **params)
            )
    raise ValueError(f"Unsupported node type: {node_info.get('type')}")
