"""
Node_15_OCR 融合入口（已修复 sys.path 污染）
===================

供 unified_launcher.py 和其他节点调用的统一入口。
整合 DeepSeek OCR 2 作为主引擎。
使用 importlib.util 绝对路径导入，避免跨节点模块污染。
"""

import importlib.util
import logging
import asyncio
import os
from typing import Dict, Any, Optional

_node_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_node_dir, '..', '..'))

logger = logging.getLogger("Node_15_OCR")


def _import_from_node(module_name, file_path):
    """使用 importlib.util 从指定路径导入模块，避免 sys.path 污染"""
    if not os.path.exists(file_path):
        return None
    spec = importlib.util.spec_from_file_location(
        module_name, file_path,
        submodule_search_locations=[os.path.dirname(file_path)]
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _import_node_main():
    """导入本节点的 main.py"""
    return _import_from_node(
        "Node_15_OCR.main",
        os.path.join(_node_dir, "main.py")
    )


def _import_deepseek_adapter():
    """导入 DeepSeek OCR 适配器"""
    adapter_path = os.path.join(_node_dir, "core", "deepseek_ocr_adapter.py")
    return _import_from_node("Node_15_OCR.core.deepseek_ocr_adapter", adapter_path)


def _import_vision_pipeline():
    """导入 VisionPipeline"""
    pipeline_path = os.path.join(_project_root, "core", "vision_pipeline.py")
    return _import_from_node("core.vision_pipeline", pipeline_path)


class FusionNode:
    """OCR 融合节点，通过 VisionPipeline 与 GUI 理解深度融合"""

    def __init__(self):
        self.node_id = "Node_15_OCR"
        self.instance = None
        self.ocr_adapter = None
        self.vision_pipeline = None
        self._load_original_logic()

    def _load_original_logic(self):
        """加载 OCR 节点主逻辑"""
        try:
            main_module = _import_node_main()
            if main_module and hasattr(main_module, 'OCRNode'):
                self.instance = main_module.OCRNode()
                logger.info(f"✅ {self.node_id} OCR 节点逻辑已加载 (DeepSeek OCR 2 + Tesseract)")
            elif main_module:
                self.instance = main_module
                logger.info(f"⚠️ {self.node_id} 以模块模式加载")
            else:
                logger.warning(f"⚠️ {self.node_id} main.py 未找到")
        except Exception as e:
            logger.error(f"❌ {self.node_id} 加载失败: {e}")

    async def initialize(self):
        """初始化 OCR 服务"""
        if self.instance and hasattr(self.instance, "initialize"):
            await self.instance.initialize()
            logger.info(f"✅ {self.node_id} 初始化完成")

        # 同时初始化适配器供其他节点调用
        try:
            adapter_module = _import_deepseek_adapter()
            if adapter_module and hasattr(adapter_module, 'DeepSeekOCRAdapter'):
                self.ocr_adapter = adapter_module.DeepSeekOCRAdapter()
                await self.ocr_adapter.initialize()
                logger.info(f"✅ {self.node_id} DeepSeek OCR 2 适配器已就绪")
            elif adapter_module and hasattr(adapter_module, 'DeepSeekOCR2Adapter'):
                self.ocr_adapter = adapter_module.DeepSeekOCR2Adapter()
                await self.ocr_adapter.initialize()
                logger.info(f"✅ {self.node_id} DeepSeek OCR 2 适配器已就绪")
        except Exception as e:
            logger.warning(f"⚠️ {self.node_id} 适配器初始化失败: {e}")

        # 接入 VisionPipeline（与 Node_90 共享同一管线实例）
        try:
            pipeline_module = _import_vision_pipeline()
            if pipeline_module and hasattr(pipeline_module, 'get_vision_pipeline'):
                self.vision_pipeline = pipeline_module.get_vision_pipeline()
                logger.info(f"✅ {self.node_id} 已接入 VisionPipeline 融合管线")
        except Exception as e:
            self.vision_pipeline = None
            logger.warning(f"⚠️ {self.node_id} VisionPipeline 未接入: {e}")

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
            if self.ocr_adapter and getattr(self.ocr_adapter, 'available', False):
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

                elif command == "ui_analysis_fused":
                    # 融合模式：通过 VisionPipeline 同时获取 OCR + GUI
                    if self.vision_pipeline:
                        import base64
                        if isinstance(image_source, str) and os.path.isfile(image_source):
                            with open(image_source, 'rb') as f:
                                img_b64 = base64.b64encode(f.read()).decode()
                        else:
                            img_b64 = image_source
                        result = await self.vision_pipeline.understand(
                            image_base64=img_b64, mode="full",
                            task_context=params.get("task_context", ""),
                        )
                        return {"success": result.success, "data": result.to_dict()}
                    else:
                        result = await self.ocr_adapter.analyze_ui(image_source)
                        return {"success": True, "data": result}

                elif command == "status":
                    return {
                        "success": True,
                        "data": {
                            "engine": "deepseek_ocr2",
                            "available": True,
                            "adapter": "DeepSeekOCRAdapter",
                            "vision_pipeline": self.vision_pipeline is not None,
                        },
                    }

            # 降级到节点实例
            if self.instance:
                if hasattr(self.instance, "perform_ocr"):
                    main_module = _import_node_main()
                    if main_module and hasattr(main_module, 'OCRMode'):
                        OCRMode = main_module.OCRMode
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

            if command == "status":
                return {
                    "success": True,
                    "data": {
                        "engine": "none",
                        "available": False,
                        "note": "OCR 引擎未初始化，请先调用 initialize()"
                    }
                }

            return {"success": False, "error": "No OCR engine available"}

        except Exception as e:
            logger.error(f"❌ {self.node_id} 执行错误: {e}")
            return {"success": False, "error": str(e)}

    async def shutdown(self):
        """关闭服务"""
        if self.ocr_adapter and hasattr(self.ocr_adapter, 'close'):
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
    adapter_module = _import_deepseek_adapter()
    if not adapter_module:
        return {"success": False, "error": "DeepSeek OCR adapter not found"}

    AdapterClass = getattr(adapter_module, 'DeepSeekOCRAdapter',
                           getattr(adapter_module, 'DeepSeekOCR2Adapter', None))
    if not AdapterClass:
        return {"success": False, "error": "No adapter class found"}

    adapter = AdapterClass()
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
