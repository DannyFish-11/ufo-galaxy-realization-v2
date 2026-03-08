# 统一融合入口文件 - 由系统自动生成（已修复 sys.path 污染）
# 同时集成 autonomous_coding_engine_v2 的高级编码能力
import importlib.util
import logging
import asyncio
import os

_node_dir = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("Node_101")

# autonomous coding engine v2（延迟初始化）
_coding_engine = None


def _import_node_main():
    """使用 importlib.util 从本节点的 main.py 导入，避免 sys.path 污染"""
    main_path = os.path.join(_node_dir, "main.py")
    if not os.path.exists(main_path):
        return None
    spec = importlib.util.spec_from_file_location(
        "Node_101_CodeEngine.main", main_path,
        submodule_search_locations=[_node_dir]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _get_coding_engine():
    """延迟加载 autonomous_coding_engine_v2"""
    global _coding_engine
    if _coding_engine is None:
        try:
            from enhancements.coding.autonomous_coding_engine_v2 import AutonomousCodingEngineV2
            project_root = os.path.dirname(os.path.dirname(_node_dir))
            _coding_engine = AutonomousCodingEngineV2(workspace_root=project_root)
            logger.info("AutonomousCodingEngineV2 loaded as Node_101 backend")
        except Exception as e:
            logger.warning(f"AutonomousCodingEngineV2 not available: {e}")
    return _coding_engine


# autonomous coding engine action → CodingTaskType 映射
_ACE_TASK_MAP = {
    "generate_code": "FEATURE",
    "feature": "FEATURE",
    "fix_bug": "BUG_FIX",
    "bug_fix": "BUG_FIX",
    "write_tests": "TEST",
    "test": "TEST",
    "optimize": "OPTIMIZE",
    "refactor": "REFACTOR",
    "document": "DOCUMENT",
}


class FusionNode:
    def __init__(self):
        self.node_id = "Node_101"
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
            logger.info(f"{self.node_id} logic loaded successfully")
        except Exception as e:
            logger.error(f"{self.node_id} failed to load logic: {e}")

    async def execute(self, command, **params):
        # 优先尝试 autonomous coding engine v2 的高级操作
        if command in _ACE_TASK_MAP:
            result = await self._try_ace_v2(command, params)
            if result is not None:
                return result

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
            logger.error(f"{self.node_id} execution error: {e}")
            return {"success": False, "error": str(e)}

    async def _try_ace_v2(self, action: str, params: dict):
        """尝试通过 autonomous_coding_engine_v2 执行高级编码任务"""
        engine = _get_coding_engine()
        if engine is None:
            return None  # fallback 到原有逻辑
        try:
            from enhancements.coding.autonomous_coding_engine_v2 import (
                CodingContext, CodingTaskType,
            )
            task_type = getattr(CodingTaskType, _ACE_TASK_MAP[action], None)
            if task_type is None:
                return None
            ctx = CodingContext(
                task_type=task_type,
                description=params.get("description", ""),
                target_files=params.get("target_files", []),
                language=params.get("language", "python"),
                workspace_root=params.get("workspace_root", engine.workspace_root),
            )
            result = await engine.execute_task(ctx)
            return {
                "success": result.success,
                "code_changes": result.code_changes,
                "explanation": result.explanation,
                "quality_score": result.quality_score,
                "errors": result.errors,
                "warnings": result.warnings,
            }
        except Exception as e:
            logger.warning(f"ACE v2 fallback for {action}: {e}")
            return None  # fallback 到原有逻辑


def get_node_instance():
    return FusionNode()
