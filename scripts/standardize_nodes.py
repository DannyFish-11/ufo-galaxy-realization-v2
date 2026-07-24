#!/usr/bin/env python3
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Standardizer")

# 模板与 nodes/*/fusion_entry.py 现存(已修复)生成物保持一致。
# 旧模板的 `sys.path.append + importlib.import_module("main")` 有两个致命问题:
# 1) 仓库根本身有 main.py 且 append 只排在 sys.path 尾部 → 全部节点实际加载的是
#    仓库根的 main.py;
# 2) 顶级模块名 "main" 进入 sys.modules 缓存后,后续每个节点的 import 都命中第一个
#    节点的缓存 → 125 个节点互相串模块。
# 修复版用 spec_from_file_location + 以节点目录名限定的唯一模块名,按文件路径加载,
# 不碰 sys.path 也不占用 "main" 这个模块名。若再次运行本脚本,严禁回退到旧模板。
ENTRY_TEMPLATE = """# 统一融合入口文件 - 由系统自动生成（已修复 sys.path 污染）
import importlib.util
import logging
import asyncio
import os

_node_dir = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("{node_id}")


def _import_node_main():
    \"\"\"使用 importlib.util 从本节点的 main.py 导入，避免 sys.path 污染\"\"\"
    main_path = os.path.join(_node_dir, "main.py")
    if not os.path.exists(main_path):
        return None
    spec = importlib.util.spec_from_file_location(
        "{node_dir_name}.main", main_path,
        submodule_search_locations=[_node_dir]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FusionNode:
    def __init__(self):
        self.node_id = "{node_id}"
        self.instance = None
        self._load_original_logic()

    def _load_original_logic(self):
        try:
            module = _import_node_main()
            if module is None:
                logger.warning(f"{{self.node_id}} main.py not found")
                return
            if hasattr(module, "get_instance"):
                self.instance = module.get_instance()
            elif hasattr(module, "Node"):
                self.instance = module.Node()
            else:
                self.instance = module
            logger.info(f"✅ {{self.node_id}} logic loaded successfully")
        except Exception as e:
            logger.error(f"❌ {{self.node_id}} failed to load logic: {{e}}")

    async def execute(self, command, **params):
        if not self.instance:
            return {{"success": False, "error": "Logic not loaded"}}
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
                    return {{"success": False, "error": "No executable method found"}}
            return {{"success": True, "data": result}}
        except Exception as e:
            logger.error(f"❌ {{self.node_id}} execution error: {{e}}")
            return {{"success": False, "error": str(e)}}


def get_node_instance():
    return FusionNode()
"""

def standardize():
    nodes_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nodes")
    if not os.path.exists(nodes_dir):
        return
    count = 0
    for item in os.listdir(nodes_dir):
        if item.startswith("Node_") and os.path.isdir(os.path.join(nodes_dir, item)):
            node_id = "_".join(item.split('_')[:2])
            entry_file = os.path.join(nodes_dir, item, "fusion_entry.py")
            # 只在文件缺失、或仍是旧坏模板(import_module("main") 会加载错误模块且
            # 跨节点串缓存)时才生成;绝不覆盖已修复/手工定制过的入口文件
            # (现存 125 个里有 43 个带定制差异,如 Node_130 的深度定制)。
            if os.path.exists(entry_file):
                with open(entry_file, "r", encoding="utf-8") as f:
                    existing = f.read()
                if 'importlib.import_module("main")' not in existing:
                    continue
            content = ENTRY_TEMPLATE.format(node_id=node_id, node_dir_name=item)
            with open(entry_file, "w", encoding="utf-8") as f:
                f.write(content)
            count += 1
            if count % 10 == 0:
                logger.info(f"⏳ Standardized {count} nodes...")
    logger.info(f"✨ Successfully standardized {count} nodes")

if __name__ == "__main__":
    standardize()
