#!/usr/bin/env python3
"""
Node_70_AutonomousLearning - 融合入口
自主学习节点
通过 execute(action, params) 接口供统一调用
"""

import os
import sys
import json
import asyncio
import logging
import traceback
import importlib.util

from nodes.common import service_entry

logger = logging.getLogger("Node_70_AutonomousLearning")


def _run_coro(coro):
    """Run a coroutine from this sync entry point safely.

    asyncio.run() manages loop creation/teardown correctly (unlike churning a
    new_event_loop per call). If a loop is already running in this thread
    (execute() invoked from an async context), running a loop here would raise
    "Cannot run the event loop while another loop is running", so offload to a
    worker thread with its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=120)

# 节点目录（绝对路径）
_node_dir = os.path.dirname(os.path.abspath(__file__))

# 服务实例（延迟初始化）
_service = None


def _import_from_node_main(class_name):
    """使用 importlib 从本节点的 main.py 导入类，避免 sys.path 污染"""
    main_path = os.path.join(_node_dir, "main.py")
    spec = importlib.util.spec_from_file_location(
        "Node_70_AutonomousLearning.main", main_path,
        submodule_search_locations=[_node_dir]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _get_service():
    """获取或初始化服务实例"""
    global _service
    if _service is None:
        try:
            cls = _import_from_node_main("AutonomousLearningEngine")
            _service = cls()
            logger.info("Node_70_AutonomousLearning 服务已初始化")
        except Exception as e:
            logger.error(f"Node_70_AutonomousLearning 服务初始化失败: {e}")
            raise
    return _service


def actions() -> dict:
    """这个节点真有的动作(服务对象上公开的方法,及其参数)—— help 与模型的节点目录(nodes__list)都用它。"""
    return service_entry.actions(_get_service())


def execute(action: str, params: dict = None) -> dict:
    """
    统一执行入口
    
    Args:
        action: 操作名称
        params: 操作参数字典
        
    Returns:
        dict: 执行结果
    """
    if params is None:
        params = {}
    
    try:
        service = _get_service()
        
        # 状态查询 / 有哪些动作:照实从服务对象上列(nodes/common/service_entry.py),不写死
        if action == "status":
            return {
                "node": "Node_70_AutonomousLearning",
                "status": "running",
                "service": type(service).__name__,
                "available_actions": sorted(actions()),
            }

        if action == "help":
            return {"node": "Node_70_AutonomousLearning", "description": "自主学习节点", "actions": actions()}

        method = service_entry.resolve(service, action)
        if method is not None:
            result = service_entry.call(method, params, _run_coro)
            return {
                "success": True,
                "action": action,
                "result": result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result)
            }

        # 未找到方法
        return {
            "success": False,
            "error": f"未找到操作: {action}",
            "available_methods": sorted(actions())[:40]
        }
        
    except Exception as e:
        logger.error(f"执行 {action} 失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


if __name__ == "__main__":
    import json as _json
    if len(sys.argv) > 1:
        action = sys.argv[1]
        params = _json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
        result = execute(action, params)
        print(_json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(_json.dumps(execute("help"), indent=2, ensure_ascii=False))
