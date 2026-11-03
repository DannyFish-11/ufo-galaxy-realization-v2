#!/usr/bin/env python3
"""
Node_120_File - 融合入口
文件操作节点
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

logger = logging.getLogger("Node_120_File")


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


_main = None


def _main_module():
    """本节点的 main.py(只载一次:服务类与请求体要出自同一份模块,pydantic 才认得那个请求对象)。"""
    global _main
    if _main is None:
        main_path = os.path.join(_node_dir, "main.py")
        spec = importlib.util.spec_from_file_location(
            "Node_120_File.main", main_path,
            submodule_search_locations=[_node_dir]
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _main = module
    return _main


def _import_from_node_main(class_name):
    """使用 importlib 从本节点的 main.py 导入类，避免 sys.path 污染"""
    return getattr(_main_module(), class_name)


def _get_service():
    """获取或初始化服务实例"""
    global _service
    if _service is None:
        try:
            cls = _import_from_node_main("FileService")
            _service = cls()
            logger.info("Node_120_File 服务已初始化")
        except Exception as e:
            logger.error(f"Node_120_File 服务初始化失败: {e}")
            raise
    return _service


#: 声明的动作 → FileService 上的方法、它要的请求体。那些方法收**一个** pydantic 请求对象,不收散的关键字参数,
#: 名字也与动作名不同(list → list_directory)—— 此前按动作名在服务上找方法,声明的九个动作里七个都回「未找到操作」,
#: 而外层照报成功(tests/test_a_node_that_fails_is_reported_as_failed.py 那一轮修的就是这层伪装)。
_ACTIONS = {
    "read": ("read_file", "ReadRequest"),
    "write": ("write_file", "WriteRequest"),
    "append": ("append_file", "AppendRequest"),
    "delete": ("delete", "DeleteRequest"),
    "copy": ("copy", "CopyMoveRequest"),
    "move": ("move", "CopyMoveRequest"),
    "list": ("list_directory", "ListRequest"),
    "search": ("search", "SearchRequest"),
    "archive": ("create_archive", "ArchiveRequest"),
    "extract": ("extract_archive", "ExtractRequest"),
    "hash": ("calculate_hash", "HashRequest"),
}


def _declared(service, action: str, params: dict):
    """按 :data:`_ACTIONS` 调一个声明过的动作;不是声明过的返回 ``None``(走下面的通用查找)。"""
    if action == "info":
        return _run_coro(service.get_file_info(str(params.get("path") or "")))
    if action not in _ACTIONS:
        return None
    method_name, model_name = _ACTIONS[action]
    request = getattr(_main_module(), model_name)(**params)
    return _run_coro(getattr(service, method_name)(request))


def actions() -> dict:
    """这个节点认的动作(声明过的那些,及其参数)—— help 与模型的节点目录(nodes__list)都用它。"""
    service = _get_service()
    out = {name: service_entry.describe(getattr(service, method)) for name, (method, _model) in _ACTIONS.items()}
    out["info"] = service_entry.describe(service.get_file_info)
    return out


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
                "node": "Node_120_File",
                "status": "running",
                "service": type(service).__name__,
                "available_actions": sorted(actions()),
            }

        if action == "help":
            return {"node": "Node_120_File", "description": "文件操作节点", "actions": actions()}

        declared = _declared(service, action, params)
        if declared is not None:
            return {"success": True, "action": action, "result": declared}

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
