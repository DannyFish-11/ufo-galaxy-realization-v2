# 统一融合入口文件 - 由系统自动生成（已修复 sys.path 污染）
import importlib.util
import logging
import asyncio
import os

_node_dir = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("Node_10")


def _import_node_main():
    """使用 importlib.util 从本节点的 main.py 导入，避免 sys.path 污染"""
    main_path = os.path.join(_node_dir, "main.py")
    if not os.path.exists(main_path):
        return None
    spec = importlib.util.spec_from_file_location(
        "Node_10_Slack.main", main_path,
        submodule_search_locations=[_node_dir]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FusionNode:
    def __init__(self):
        self.node_id = "Node_10"
        self.instance = None
        self._load_original_logic()

    def _load_original_logic(self):
        try:
            module = _import_node_main()
            if module is None:
                logger.warning(f"{self.node_id} main.py not found")
                return
            if hasattr(module, "get_instance"):
                self.instance = module.get_instance()
            elif hasattr(module, "Node"):
                self.instance = module.Node()
            else:
                self.instance = module
            logger.info(f"✅ {self.node_id} logic loaded successfully")
        except Exception as e:
            logger.error(f"❌ {self.node_id} failed to load logic: {e}")

    async def execute(self, command, **params):
        if not self.instance:
            return {"success": False, "error": "Logic not loaded"}
        try:
            method = None
            for m in ["process", "execute", "run", "handle"]:
                if hasattr(self.instance, m):
                    method = getattr(self.instance, m)
                    break
            if method:
                if asyncio.iscoroutinefunction(method):
                    result = await method(command, **params)
                else:
                    result = method(command, **params)
            else:
                if callable(self.instance):
                    result = self.instance(command, **params)
                else:
                    return {"success": False, "error": "No executable method found"}
            return {"success": True, "data": result}
        except Exception as e:
            logger.error(f"❌ {self.node_id} execution error: {e}")
            return {"success": False, "error": str(e)}


def get_node_instance():
    return FusionNode()
