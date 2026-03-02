# -*- coding: utf-8 -*-
"""
Node 113 — Android VLM (DeepSeek VL variant)

Uses DeepSeek's OpenAI-compatible chat API with vision to analyse
Android screenshots and extract UI element information.

Requires:
    DEEPSEEK_API_KEY environment variable
    httpx (already in requirements.txt)
"""

import os
import json
import base64
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekAndroidVLM:
    """
    使用 DeepSeek VL 增强的安卓视觉语言模型节点。

    DeepSeek 提供 OpenAI 兼容的 chat/completions 端点，
    支持 vision 输入（base64 图片）。
    """

    def __init__(self):
        self.api_key = os.getenv("DEEPSEEK_API_KEY", "")
        self.model = os.getenv("DEEPSEEK_VL_MODEL", DEFAULT_MODEL)
        self.base_url = os.getenv(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).rstrip("/")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def understand_screen(
        self, screenshot_path: str, prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分析安卓截屏，提取 UI 元素和屏幕描述。

        Args:
            screenshot_path: 截图文件路径 (PNG/JPG)
            prompt: 自定义分析提示词（可选）

        Returns:
            {"ui_elements": [...], "description": "...", "raw_response": "..."}
        """
        if not self.api_key:
            logger.warning("DEEPSEEK_API_KEY not set, returning empty result")
            return {
                "ui_elements": [],
                "description": "[no API key] Unable to analyse screenshot",
                "error": "DEEPSEEK_API_KEY not configured",
            }

        image_b64 = self._load_image_base64(screenshot_path)
        if not image_b64:
            return {
                "ui_elements": [],
                "description": "",
                "error": f"Cannot read image: {screenshot_path}",
            }

        analysis_prompt = prompt or (
            "Analyze this Android screenshot. "
            "Return a JSON object with two keys:\n"
            '1. "ui_elements": a list of visible UI elements, each with '
            '{"type", "text", "bounds_description", "clickable"}\n'
            '2. "description": a one-paragraph summary of what the screen shows.\n'
            "Return ONLY valid JSON, no markdown."
        )

        try:
            response_text = await self._call_deepseek_vl(image_b64, analysis_prompt)
            return self._parse_response(response_text)
        except Exception as e:
            logger.error(f"DeepSeek VL call failed: {e}")
            return {
                "ui_elements": [],
                "description": "",
                "error": str(e),
            }

    async def find_element(
        self, screenshot_path: str, element_description: str
    ) -> Dict[str, Any]:
        """
        在截屏中定位指定元素的大致位置。

        Returns:
            {"found": bool, "x": int, "y": int, "confidence": str, ...}
        """
        if not self.api_key:
            return {"found": False, "error": "DEEPSEEK_API_KEY not configured"}

        image_b64 = self._load_image_base64(screenshot_path)
        if not image_b64:
            return {"found": False, "error": f"Cannot read image: {screenshot_path}"}

        prompt = (
            f'Find the UI element matching this description: "{element_description}". '
            "Return a JSON object: "
            '{"found": true/false, "x": pixel_x, "y": pixel_y, '
            '"confidence": "high"/"medium"/"low", "element_text": "..."}. '
            "Return ONLY valid JSON."
        )

        try:
            response_text = await self._call_deepseek_vl(image_b64, prompt)
            return self._parse_json_safe(response_text, {"found": False})
        except Exception as e:
            return {"found": False, "error": str(e)}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _call_deepseek_vl(self, image_b64: str, prompt: str) -> str:
        """调用 DeepSeek VL chat API (OpenAI 兼容格式)"""
        try:
            import httpx
        except ImportError:
            raise RuntimeError("httpx is required — pip install httpx")

        url = f"{self.base_url}/chat/completions"

        # DeepSeek 的 vision 格式与 OpenAI 兼容
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_b64}"
                        },
                    },
                ],
            }
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.1,
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        return data["choices"][0]["message"]["content"]

    @staticmethod
    def _load_image_base64(path: str) -> Optional[str]:
        """读取图片并返回 base64 编码"""
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except (FileNotFoundError, PermissionError, OSError) as e:
            logger.error(f"Failed to read image {path}: {e}")
            return None

    @staticmethod
    def _parse_response(raw: str) -> Dict[str, Any]:
        """尝试解析 LLM 返回的 JSON，容错处理"""
        result = {"ui_elements": [], "description": "", "raw_response": raw}

        # 尝试直接 JSON 解析
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # 去掉 markdown code fence
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            parsed = json.loads(cleaned)
            result["ui_elements"] = parsed.get("ui_elements", [])
            result["description"] = parsed.get("description", "")
        except json.JSONDecodeError:
            # LLM 没返回合法 JSON，把整段作为描述
            result["description"] = raw.strip()

        return result

    @staticmethod
    def _parse_json_safe(raw: str, default: Dict) -> Dict[str, Any]:
        """安全解析 JSON，失败返回 default"""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {**default, "raw_response": raw}


node_instance = DeepSeekAndroidVLM()
