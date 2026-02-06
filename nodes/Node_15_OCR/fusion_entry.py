"""
Node_15_OCR 融合入口
===================

供 unified_launcher.py 和其他节点调用的统一入口。
整合 DeepSeek OCR 2 作为主引擎。
"""

import importlib
import logging
import asyncio
import sys
import os
from typing import Dict, Any, Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

logger = logging.getLogger("Node_15_OCR")


class FusionNode:
    """OCR 融合节点，支持 DeepSeek OCR 2 和 Tesseract 双引擎"""

    def __init__(self):
        self.node_id = "Node_15_OCR"
        self.instance = None
        self.ocr_adapter = None
        self._load_original_logic()

    def _load_original_logic(self):
        """加载 OCR 节点主逻辑"""
        try:
            from main import OCRNode
            self.instance = OCRNode()
            logger.info(f"✅ {self.node_id} OCR 节点逻辑已加载 (DeepSeek OCR 2 + Tesseract)")
        except Exception as e:
            logger.error(f"❌ {self.node_id} 加载失败: {e}")
            try:
                module = importlib.import_module("main")
                self.instance = module
                logger.info(f"⚠️ {self.node_id} 以模块模式加载")
            except Exception as e2:
                logger.error(f"❌ {self.node_id} 完全加载失败: {e2}")

    async def initialize(self):
        """初始化 OCR 服务"""
        if self.instance and hasattr(self.instance, "initialize"):
            await self.instance.initialize()
            logger.info(f"✅ {self.node_id} 初始化完成")

        # 同时初始化适配器供其他节点调用
        try:
            from core.deepseek_ocr_adapter import DeepSeekOCRAdapter
            self.ocr_adapter = DeepSeekOCRAdapter()
            await self.ocr_adapter.initialize()
            logger.info(f"✅ {self.node_id} DeepSeek OCR 2 适配器已就绪")
        except Exception as e:
            logger.warning(f"⚠️ {self.node_id} 适配器初始化失败: {e}")

    async def execute(self, command: str, **params) -> Dict[str, Any]:
        """
        执行 OCR 命令

        支持的命令:
            - ocr / extract_text: 自由文本提取
            - document_markdown: 文档转 Markdown
            - ui_analysis: UI 元素分析
            - table_extract: 表格提取
            - handwriting: 手写识别
            - status: 查询状态
        """
        try:
            # 优先使用适配器
            if self.ocr_adapter and self.ocr_adapter.available:
                image_source = params.get("image_path", params.get("image", ""))

                if command in ("ocr", "extract_text", "free_ocr"):
                    if isinstance(image_source, bytes):
                        result = await self.ocr_adapter.extract_text_from_bytes(image_source)
                    else:
                        result = await self.ocr_adapter.extract_text(image_source)
                    return {"success": True, "data": result}

                elif command == "document_markdown":
                    result = await self.ocr_adapter.document_to_markdown(image_source)
                    return {"success": True, "data": result}

                elif command == "ui_analysis":
                    result = await self.ocr_adapter.analyze_ui(image_source)
                    return {"success": True, "data": result}

                elif command == "table_extract":
                    result = await self.ocr_adapter.extract_tables(image_source)
                    return {"success": True, "data": result}

                elif command == "handwriting":
                    result = await self.ocr_adapter.recognize_handwriting(image_source)
                    return {"success": True, "data": result}

                elif command == "custom":
                    prompt = params.get("prompt", "")
                    result = await self.ocr_adapter.custom_query(image_source, prompt)
                    return {"success": True, "data": result}

                elif command == "status":
                    return {
                        "success": True,
                        "data": {
                            "engine": "deepseek_ocr2",
                            "available": True,
                            "adapter": "DeepSeekOCRAdapter",
                        },
                    }

            # 降级到节点实例
            if self.instance:
                if hasattr(self.instance, "perform_ocr"):
                    from main import OCRMode
                    mode_map = {
                        "ocr": OCRMode.FREE_OCR,
                        "extract_text": OCRMode.FREE_OCR,
                        "free_ocr": OCRMode.FREE_OCR,
                        "document_markdown": OCRMode.DOCUMENT_MARKDOWN,
                        "ui_analysis": OCRMode.UI_ANALYSIS,
                        "table_extract": OCRMode.TABLE_EXTRACT,
                        "handwriting": OCRMode.HANDWRITING,
                    }
                    mode = mode_map.get(command, OCRMode.FREE_OCR)
                    image_bytes = params.get("image_bytes", b"")
                    result = await self.instance.perform_ocr(image_bytes, mode)
                    return {"success": True, "data": result}

            return {"success": False, "error": "No OCR engine available"}

        except Exception as e:
            logger.error(f"❌ {self.node_id} 执行错误: {e}")
            return {"success": False, "error": str(e)}

    async def shutdown(self):
        """关闭服务"""
        if self.ocr_adapter:
            await self.ocr_adapter.close()
        if self.instance and hasattr(self.instance, "shutdown"):
            await self.instance.shutdown()


def get_node_instance():
    """获取节点实例"""
    return FusionNode()


async def quick_ocr(image_path: str, mode: str = "free_ocr") -> Dict[str, Any]:
    """
    快速 OCR 调用（一次性使用，供其他节点直接调用）

    参数:
        image_path: 图像文件路径
        mode: OCR 模式

    返回:
        识别结果
    """
    from core.deepseek_ocr_adapter import DeepSeekOCRAdapter

    adapter = DeepSeekOCRAdapter()
    await adapter.initialize()

    try:
        if mode == "free_ocr":
            return await adapter.extract_text(image_path)
        elif mode == "document_markdown":
            return await adapter.document_to_markdown(image_path)
        elif mode == "ui_analysis":
            return await adapter.analyze_ui(image_path)
        elif mode == "table_extract":
            return await adapter.extract_tables(image_path)
        elif mode == "handwriting":
            return await adapter.recognize_handwriting(image_path)
        else:
            return await adapter.extract_text(image_path)
    finally:
        await adapter.close()
