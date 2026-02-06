"""
DeepSeek OCR 2 适配器
====================

为 UFO Galaxy 其他节点提供统一的 OCR 调用接口。
其他节点（如 Node_70_ALE、Node_36_UIAWindows、Node_113_AndroidVLM）
可以直接导入此适配器来使用 DeepSeek OCR 2。

使用方式:
    from nodes.Node_15_OCR.core.deepseek_ocr_adapter import DeepSeekOCRAdapter

    adapter = DeepSeekOCRAdapter()
    await adapter.initialize()
    result = await adapter.analyze_ui("screenshot.png")
    result = await adapter.extract_text("document.jpg")
    result = await adapter.document_to_markdown("page.png")
"""

import os
import base64
import json
import logging
import time
import io
from typing import Dict, Any, Optional, List

logger = logging.getLogger("DeepSeekOCRAdapter")


class DeepSeekOCRAdapter:
    """
    DeepSeek OCR 2 统一适配器

    为 UFO Galaxy 系统内部各节点提供 OCR 能力。
    支持云端 API 和本地部署两种模式。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_base: Optional[str] = None,
        model: Optional[str] = None,
        local_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("NOVITA_API_KEY", "") or os.getenv("DEEPSEEK_OCR_API_KEY", "")
        self.api_base = api_base or os.getenv("DEEPSEEK_OCR2_API_BASE", "https://api.novita.ai/openai")
        self.model = model or "deepseek/deepseek-ocr-2"
        self.local_url = local_url or os.getenv("DEEPSEEK_OCR2_LOCAL_URL", "")
        self._session = None
        self._initialized = False
        logger.info("DeepSeek OCR 2 Adapter created")

    async def initialize(self) -> bool:
        """初始化适配器"""
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=60)
            )
            self._initialized = bool(self.api_key) or bool(self.local_url)
            if self._initialized:
                logger.info("DeepSeek OCR 2 Adapter initialized successfully")
            else:
                logger.warning("DeepSeek OCR 2 Adapter: no API key or local URL configured")
            return self._initialized
        except Exception as e:
            logger.error(f"DeepSeek OCR 2 Adapter initialization failed: {e}")
            return False

    @property
    def available(self) -> bool:
        return self._initialized

    def _encode_image(self, image_source: str) -> str:
        """将图像文件或字节编码为 base64"""
        if os.path.exists(image_source):
            with open(image_source, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        else:
            return image_source  # 假设已经是 base64

    def _encode_image_bytes(self, image_bytes: bytes) -> str:
        """将图像字节编码为 base64"""
        return base64.b64encode(image_bytes).decode("utf-8")

    async def _call_api(self, prompt: str, image_b64: str) -> Dict[str, Any]:
        """调用 DeepSeek OCR 2 API"""
        if not self._session:
            return {"error": "Adapter not initialized"}

        if self.local_url:
            url = f"{self.local_url}/chat/completions"
            headers = {"Content-Type": "application/json"}
            model_name = "deepseek-ai/DeepSeek-OCR-2"
        else:
            url = f"{self.api_base}/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            model_name = self.model

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 8192,
            "temperature": 0.1,
        }

        start_time = time.time()
        try:
            async with self._session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    return {"error": f"API error [{resp.status}]: {error}"}
                result = await resp.json()

            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            latency_ms = (time.time() - start_time) * 1000

            return {
                "success": True,
                "text": content,
                "latency_ms": round(latency_ms, 2),
                "usage": result.get("usage", {}),
            }
        except Exception as e:
            return {"error": str(e)}

    async def extract_text(self, image_source: str) -> Dict[str, Any]:
        """
        提取图像中的文本（自由 OCR）

        参数:
            image_source: 图像文件路径或 base64 字符串

        返回:
            {"success": True, "text": "...", ...}
        """
        image_b64 = self._encode_image(image_source)
        return await self._call_api("<image>\nFree OCR. ", image_b64)

    async def extract_text_from_bytes(self, image_bytes: bytes) -> Dict[str, Any]:
        """从图像字节提取文本"""
        image_b64 = self._encode_image_bytes(image_bytes)
        return await self._call_api("<image>\nFree OCR. ", image_b64)

    async def document_to_markdown(self, image_source: str) -> Dict[str, Any]:
        """
        将文档图像转换为 Markdown 格式

        参数:
            image_source: 图像文件路径或 base64 字符串

        返回:
            {"success": True, "text": "markdown content", ...}
        """
        image_b64 = self._encode_image(image_source)
        return await self._call_api(
            "<image>\n<|grounding|>Convert the document to markdown. ",
            image_b64,
        )

    async def analyze_ui(self, image_source: str) -> Dict[str, Any]:
        """
        分析 UI 截图，返回结构化 UI 元素信息

        参数:
            image_source: 图像文件路径或 base64 字符串

        返回:
            {"success": True, "text": "JSON structured UI elements", ...}
        """
        image_b64 = self._encode_image(image_source)
        prompt = (
            "<image>\nAnalyze this UI screenshot. Identify all interactive elements "
            "(buttons, text fields, links, menus, icons) with their approximate positions "
            "(x, y, width, height as percentage of image), text content, and element types. "
            "Output as a JSON array."
        )
        return await self._call_api(prompt, image_b64)

    async def extract_tables(self, image_source: str) -> Dict[str, Any]:
        """
        提取图像中的表格

        参数:
            image_source: 图像文件路径或 base64 字符串

        返回:
            {"success": True, "text": "markdown tables", ...}
        """
        image_b64 = self._encode_image(image_source)
        return await self._call_api(
            "<image>\n<|grounding|>Extract all tables from this document. "
            "Convert each table to markdown table format.",
            image_b64,
        )

    async def recognize_handwriting(self, image_source: str) -> Dict[str, Any]:
        """
        识别手写文本

        参数:
            image_source: 图像文件路径或 base64 字符串

        返回:
            {"success": True, "text": "recognized text", ...}
        """
        image_b64 = self._encode_image(image_source)
        return await self._call_api(
            "<image>\nRecognize all handwritten text in this image. ",
            image_b64,
        )

    async def custom_query(
        self, image_source: str, prompt: str
    ) -> Dict[str, Any]:
        """
        自定义查询

        参数:
            image_source: 图像文件路径或 base64 字符串
            prompt: 自定义 prompt

        返回:
            {"success": True, "text": "response", ...}
        """
        image_b64 = self._encode_image(image_source)
        return await self._call_api(prompt, image_b64)

    async def close(self):
        """关闭适配器"""
        if self._session:
            await self._session.close()
            self._session = None
