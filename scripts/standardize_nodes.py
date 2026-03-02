#!/usr/bin/env python3
import os
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("Standardizer")

ENTRY_TEMPLATE = """# 统一融合入口文件 - 由系统自动生成
import importlib
import logging
import asyncio
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

logger = logging.getLogger("{node_id}")

class FusionNode:
    def __init__(self):
        self.node_id = "{node_id}"
        self.instance = None
        self._load_original_logic()

    def _load_original_logic(self):
        try:
            module = importlib.import_module("main")
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
            content = ENTRY_TEMPLATE.format(node_id=node_id)
            with open(entry_file, "w", encoding="utf-8") as f:
                f.write(content)
            count += 1
            if count % 10 == 0:
                logger.info(f"⏳ Standardized {count} nodes...")
    logger.info(f"✨ Successfully standardized {count} nodes")

if __name__ == "__main__":
    standardize()
