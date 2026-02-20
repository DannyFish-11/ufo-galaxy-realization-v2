#!/usr/bin/env python3
"""
Node_13_Web - 融合入口
Web 操作节点
通过 execute(action, params) 接口供统一调用
"""

import os
import sys
import json
import logging
import traceback
import importlib.util

logger = logging.getLogger("Node_13_Web")

# 节点目录（绝对路径）
_node_dir = os.path.dirname(os.path.abspath(__file__))

# 服务实例（延迟初始化）
_service = None


def _import_from_node_main(class_name):
    """使用 importlib 从本节点的 main.py 导入类，避免 sys.path 污染"""
    main_path = os.path.join(_node_dir, "main.py")
    spec = importlib.util.spec_from_file_location(
        "Node_13_Web.main", main_path,
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
            cls = _import_from_node_main("WebService")
            _service = cls()
            logger.info("Node_13_Web 服务已初始化")
        except Exception as e:
            logger.error(f"Node_13_Web 服务初始化失败: {e}")
            raise
    return _service


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
        
        # 状态查询
        if action == "status":
            return {
                "node": "Node_13_Web",
                "status": "running",
                "service": type(service).__name__,
                "available_actions": ['http_request', 'scrape', 'download', 'api_call']
            }
        
        if action == "help":
            return {
                "node": "Node_13_Web",
                "description": "Web 操作节点",
                "actions": {'http_request': '发送 HTTP 请求', 'scrape': '网页抓取', 'download': '下载文件', 'api_call': 'API 调用'}
            }
        
        # 查找并调用对应方法
        method_name = action.replace("-", "_")
        
        # 优先查找精确匹配的方法
        if hasattr(service, method_name):
            method = getattr(service, method_name)
            if callable(method):
                import asyncio
                import inspect
                if inspect.iscoroutinefunction(method):
                    loop = asyncio.new_event_loop()
                    try:
                        result = loop.run_until_complete(method(**params))
                    finally:
                        loop.close()
                else:
                    result = method(**params)
                return {
                    "success": True,
                    "action": action,
                    "result": result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result)
                }
        
        # 查找带前缀的方法
        for prefix in ["do_", "handle_", "process_", "run_", "perform_"]:
            prefixed = prefix + method_name
            if hasattr(service, prefixed):
                method = getattr(service, prefixed)
                if callable(method):
                    import asyncio
                    import inspect
                    if inspect.iscoroutinefunction(method):
                        loop = asyncio.new_event_loop()
                        try:
                            result = loop.run_until_complete(method(**params))
                        finally:
                            loop.close()
                    else:
                        result = method(**params)
                    return {
                        "success": True,
                        "action": action,
                        "result": result if isinstance(result, (dict, list, str, int, float, bool, type(None))) else str(result)
                    }
        
        # 未找到方法
        available = [m for m in dir(service) if not m.startswith("_") and callable(getattr(service, m, None))]
        return {
            "success": False,
            "error": f"未找到操作: {action}",
            "available_methods": available[:20]
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
