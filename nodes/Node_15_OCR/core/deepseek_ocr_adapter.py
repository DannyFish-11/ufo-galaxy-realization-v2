"""
Node 15: DeepSeek OCR Adapter
功能: 将原始图像转化为结构化 UI 树，供 Node 70 (ALE) 使用。
"""
import os
import base64
import httpx
from typing import Dict, Any
import logging

logger = logging.getLogger("DeepSeekOCRAdapter")

class DeepSeekOCRAdapter:
    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY")
        self.api_url = "https://api.deepseek.com/v1/ocr"
        logger.info("DeepSeek OCR Adapter Initialized.")

    async def analyze_ui(self, image_path: str) -> Dict[str, Any]:
        """分析截图，返回结构化 UI 树"""
        if not os.path.exists(image_path):
            return {"error": "Image file not found."}
            
        with open(image_path, "rb") as f:
            encoded_image = base64.b64encode(f.read()).decode('utf-8')
        
        payload = {
            "model": "deepseek-ocr-2",
            "image": encoded_image,
            "mode": "ui_analysis" # 假设 DeepSeek 支持 UI 结构化分析模式
        }
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(self.api_url, json=payload, headers=headers)
                response.raise_for_status()
                return response.json()
        except Exception as e:
            logger.error(f"DeepSeek OCR API Error: {e}")
            return {"error": str(e)}

