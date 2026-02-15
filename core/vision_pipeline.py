"""
UFO Galaxy - 融合视觉理解管线 (Vision Pipeline)

将 OCR 和 GUI 理解深度融合为统一的视觉理解引擎。
核心思路：DeepSeek OCR 2 作为统一视觉前端，一次调用同时输出：
  1. OCR 文本（精确的文字内容和位置）
  2. GUI 元素树（UI 组件的类型、层级、可交互性）
  3. 场景语义（当前页面/应用的整体理解）

管线架构：
  截图 → VisionPipeline.understand() → VisionResult
    ├── ocr_result: 文本内容 + 位置坐标
    ├── gui_elements: UI 元素树（按钮、输入框、文本、图标等）
    ├── scene_context: 场景语义（应用名、页面类型、当前状态）
    └── action_hints: 可执行的动作建议

降级策略：
  Level 1: DeepSeek OCR 2 (UI 分析模式) — 快速、低成本
  Level 2: Gemini 2.0 Flash — 复杂场景理解
  Level 3: Qwen3-VL — 备选 VLM
  Level 4: Tesseract + 规则引擎 — 完全离线
"""

import asyncio
import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("VisionPipeline")


# =============================================================================
# 数据结构
# =============================================================================

class ElementType(str, Enum):
    """GUI 元素类型"""
    BUTTON = "button"
    TEXT = "text"
    INPUT = "input"
    IMAGE = "image"
    ICON = "icon"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    TOGGLE = "toggle"
    SLIDER = "slider"
    DROPDOWN = "dropdown"
    TAB = "tab"
    LINK = "link"
    MENU = "menu"
    TOOLBAR = "toolbar"
    STATUS_BAR = "status_bar"
    NAVIGATION = "navigation"
    DIALOG = "dialog"
    LIST_ITEM = "list_item"
    CARD = "card"
    CONTAINER = "container"
    UNKNOWN = "unknown"


class InteractionType(str, Enum):
    """交互类型"""
    CLICK = "click"
    LONG_PRESS = "long_press"
    TYPE = "type"
    SCROLL = "scroll"
    SWIPE = "swipe"
    DRAG = "drag"
    TOGGLE = "toggle"
    SELECT = "select"
    NONE = "none"


@dataclass
class BoundingBox:
    """元素边界框"""
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @property
    def area(self) -> int:
        return self.width * self.height

    def contains(self, px: int, py: int) -> bool:
        return self.x <= px <= self.x + self.width and self.y <= py <= self.y + self.height

    def overlap_ratio(self, other: 'BoundingBox') -> float:
        """计算两个边界框的重叠比例"""
        x1 = max(self.x, other.x)
        y1 = max(self.y, other.y)
        x2 = min(self.x + self.width, other.x + other.width)
        y2 = min(self.y + self.height, other.y + other.height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        intersection = (x2 - x1) * (y2 - y1)
        union = self.area + other.area - intersection
        return intersection / union if union > 0 else 0.0

    def to_dict(self) -> Dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height,
                "center_x": self.center[0], "center_y": self.center[1]}


@dataclass
class GUIElement:
    """GUI 元素"""
    element_id: str
    element_type: ElementType
    text: str
    bbox: BoundingBox
    confidence: float
    interactable: bool
    interaction_types: List[InteractionType] = field(default_factory=list)
    children: List['GUIElement'] = field(default_factory=list)
    parent_id: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type.value,
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "interactable": self.interactable,
            "interaction_types": [it.value for it in self.interaction_types],
            "children_count": len(self.children),
            "parent_id": self.parent_id,
            "attributes": self.attributes,
        }


@dataclass
class OCRWord:
    """OCR 识别的单词/文本块"""
    text: str
    bbox: BoundingBox
    confidence: float
    language: str = "unknown"
    is_handwritten: bool = False

    def to_dict(self) -> Dict:
        return {
            "text": self.text,
            "bbox": self.bbox.to_dict(),
            "confidence": self.confidence,
            "language": self.language,
            "is_handwritten": self.is_handwritten,
        }


@dataclass
class SceneContext:
    """场景语义上下文"""
    app_name: str = ""
    page_type: str = ""  # login, home, settings, chat, browser, editor, etc.
    platform: str = ""  # android, windows, web
    description: str = ""
    state: str = ""  # idle, loading, error, input_required, etc.
    key_info: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "app_name": self.app_name,
            "page_type": self.page_type,
            "platform": self.platform,
            "description": self.description,
            "state": self.state,
            "key_info": self.key_info,
        }


@dataclass
class ActionHint:
    """动作建议"""
    action: str
    target_element_id: Optional[str]
    description: str
    priority: float  # 0.0 - 1.0
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "action": self.action,
            "target_element_id": self.target_element_id,
            "description": self.description,
            "priority": self.priority,
            "parameters": self.parameters,
        }


@dataclass
class VisionResult:
    """统一视觉理解结果"""
    success: bool
    ocr_words: List[OCRWord] = field(default_factory=list)
    gui_elements: List[GUIElement] = field(default_factory=list)
    scene: SceneContext = field(default_factory=SceneContext)
    action_hints: List[ActionHint] = field(default_factory=list)
    raw_text: str = ""
    engine_used: str = ""
    processing_time_ms: float = 0
    error: str = ""

    @property
    def full_text(self) -> str:
        """获取所有 OCR 文本拼接"""
        if self.raw_text:
            return self.raw_text
        return " ".join(w.text for w in self.ocr_words)

    @property
    def interactable_elements(self) -> List[GUIElement]:
        """获取所有可交互元素"""
        return [e for e in self.gui_elements if e.interactable]

    def find_element_by_text(self, text: str, fuzzy: bool = True) -> Optional[GUIElement]:
        """通过文本查找 GUI 元素"""
        text_lower = text.lower()
        for elem in self.gui_elements:
            if fuzzy:
                if text_lower in elem.text.lower():
                    return elem
            else:
                if text_lower == elem.text.lower():
                    return elem
        return None

    def find_elements_by_type(self, element_type: ElementType) -> List[GUIElement]:
        """通过类型查找 GUI 元素"""
        return [e for e in self.gui_elements if e.element_type == element_type]

    def find_element_at(self, x: int, y: int) -> Optional[GUIElement]:
        """通过坐标查找 GUI 元素"""
        candidates = [e for e in self.gui_elements if e.bbox.contains(x, y)]
        if not candidates:
            return None
        # 返回面积最小的（最精确的）
        return min(candidates, key=lambda e: e.bbox.area)

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "ocr_words": [w.to_dict() for w in self.ocr_words],
            "gui_elements": [e.to_dict() for e in self.gui_elements],
            "scene": self.scene.to_dict(),
            "action_hints": [a.to_dict() for a in self.action_hints],
            "full_text": self.full_text,
            "interactable_count": len(self.interactable_elements),
            "total_elements": len(self.gui_elements),
            "engine_used": self.engine_used,
            "processing_time_ms": self.processing_time_ms,
            "error": self.error,
        }


# =============================================================================
# 融合视觉引擎
# =============================================================================

class VisionPipeline:
    """
    融合视觉理解管线

    将 OCR 和 GUI 理解融合为一次调用，通过 DeepSeek OCR 2 的 UI 分析模式
    同时获取文本内容和 GUI 元素结构。
    """

    # DeepSeek OCR 2 的 UI 分析 Prompt
    UI_ANALYSIS_PROMPT = """Analyze this screenshot and provide a comprehensive understanding in JSON format.

You must return ONLY valid JSON (no markdown, no code blocks) with this exact structure:
{
  "scene": {
    "app_name": "application name or empty string",
    "page_type": "login|home|settings|chat|browser|editor|list|detail|search|media|notification|dialog|other",
    "platform": "android|windows|web|ios|unknown",
    "description": "brief description of what's on screen",
    "state": "idle|loading|error|input_required|playing|paused|completed",
    "key_info": {"key": "value pairs of important information visible"}
  },
  "elements": [
    {
      "id": "elem_0",
      "type": "button|text|input|image|icon|checkbox|radio|toggle|slider|dropdown|tab|link|menu|toolbar|status_bar|navigation|dialog|list_item|card|container",
      "text": "visible text content",
      "bbox": [x, y, width, height],
      "confidence": 0.95,
      "interactable": true,
      "interactions": ["click", "long_press", "type", "scroll", "swipe", "drag", "toggle", "select"],
      "attributes": {}
    }
  ],
  "ocr_texts": [
    {
      "text": "recognized text",
      "bbox": [x, y, width, height],
      "confidence": 0.98
    }
  ],
  "action_hints": [
    {
      "action": "suggested action description",
      "target": "elem_0",
      "priority": 0.8
    }
  ]
}

Rules:
1. bbox coordinates are [x, y, width, height] in pixels from top-left
2. List ALL visible text as ocr_texts entries
3. List ALL interactive elements (buttons, inputs, links, etc.)
4. Identify the current app/page context accurately
5. Suggest logical next actions based on the screen state
6. confidence values range from 0.0 to 1.0"""

    # 纯 OCR Prompt（当只需要文本时）
    OCR_ONLY_PROMPT = """Extract ALL visible text from this image. Return ONLY valid JSON:
{
  "texts": [
    {"text": "recognized text", "bbox": [x, y, width, height], "confidence": 0.98}
  ],
  "full_text": "all text concatenated with newlines"
}"""

    # 元素定位 Prompt
    FIND_ELEMENT_PROMPT_TEMPLATE = """Find the UI element matching this description: "{description}"

Return ONLY valid JSON:
{{
  "found": true,
  "element": {{
    "text": "element text",
    "type": "button|text|input|...",
    "bbox": [x, y, width, height],
    "confidence": 0.95
  }},
  "context": "brief description of where the element is"
}}

If not found, return: {{"found": false, "reason": "why not found"}}"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # DeepSeek OCR 2 配置
        self.deepseek_api_key = self.config.get("deepseek_ocr2_api_key",
            os.getenv("DEEPSEEK_OCR2_API_KEY", os.getenv("NOVITA_API_KEY", "")))
        self.deepseek_api_base = self.config.get("deepseek_ocr2_api_base",
            os.getenv("DEEPSEEK_OCR2_API_BASE", "https://api.novita.ai/v3/openai"))
        self.deepseek_model = self.config.get("deepseek_ocr2_model",
            os.getenv("DEEPSEEK_OCR2_MODEL", "deepseek/deepseek-ocr2"))

        # Gemini 配置（Level 2 降级）
        self.gemini_api_key = self.config.get("gemini_api_key",
            os.getenv("GEMINI_API_KEY", ""))

        # OpenRouter 配置（Level 3 降级，Qwen3-VL）
        self.openrouter_api_key = self.config.get("openrouter_api_key",
            os.getenv("OPENROUTER_API_KEY", ""))

        # 本地 vLLM 配置
        self.local_vllm_url = self.config.get("local_vllm_url",
            os.getenv("LOCAL_VLLM_URL", ""))

        # 统计
        self._stats = {
            "total_calls": 0,
            "deepseek_calls": 0,
            "gemini_calls": 0,
            "qwen_calls": 0,
            "tesseract_calls": 0,
            "avg_time_ms": 0,
            "errors": 0,
        }

        # HTTP 客户端
        self._client: Optional[httpx.AsyncClient] = None

        logger.info("VisionPipeline 初始化完成")
        logger.info(f"  DeepSeek OCR 2: {'✅ 已配置' if self.deepseek_api_key else '❌ 未配置'}")
        logger.info(f"  Gemini: {'✅ 已配置' if self.gemini_api_key else '❌ 未配置'}")
        logger.info(f"  Qwen3-VL: {'✅ 已配置' if self.openrouter_api_key else '❌ 未配置'}")
        logger.info(f"  本地 vLLM: {'✅ 已配置' if self.local_vllm_url else '❌ 未配置'}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # =========================================================================
    # 核心方法：统一视觉理解
    # =========================================================================

    async def understand(
        self,
        image_base64: Optional[str] = None,
        image_path: Optional[str] = None,
        mode: str = "full",
        task_context: str = "",
    ) -> VisionResult:
        """
        统一视觉理解入口

        Args:
            image_base64: Base64 编码的图片
            image_path: 图片文件路径
            mode: 理解模式
                - "full": 完整分析（OCR + GUI + 场景 + 动作建议）
                - "ocr_only": 仅 OCR 文本提取
                - "gui_only": 仅 GUI 元素分析
                - "find_element": 查找特定元素（需要 task_context 描述）
            task_context: 任务上下文（用于 find_element 模式或增强理解）

        Returns:
            VisionResult: 统一的视觉理解结果
        """
        start_time = time.time()
        self._stats["total_calls"] += 1

        # 准备图片
        if image_path and not image_base64:
            try:
                with open(image_path, "rb") as f:
                    image_base64 = base64.b64encode(f.read()).decode()
            except Exception as e:
                return VisionResult(success=False, error=f"无法读取图片: {e}")

        if not image_base64:
            return VisionResult(success=False, error="未提供图片数据")

        # 选择 Prompt
        if mode == "ocr_only":
            prompt = self.OCR_ONLY_PROMPT
        elif mode == "find_element" and task_context:
            prompt = self.FIND_ELEMENT_PROMPT_TEMPLATE.format(description=task_context)
        else:
            prompt = self.UI_ANALYSIS_PROMPT
            if task_context:
                prompt += f"\n\nAdditional context: {task_context}"

        # 按降级策略尝试各引擎
        result = None
        engine_used = ""

        # Level 1: DeepSeek OCR 2
        if self.deepseek_api_key or self.local_vllm_url:
            result = await self._call_deepseek_ocr2(image_base64, prompt)
            if result:
                engine_used = "deepseek_ocr2"
                self._stats["deepseek_calls"] += 1

        # Level 2: Gemini
        if not result and self.gemini_api_key:
            result = await self._call_gemini(image_base64, prompt)
            if result:
                engine_used = "gemini"
                self._stats["gemini_calls"] += 1

        # Level 3: Qwen3-VL via OpenRouter
        if not result and self.openrouter_api_key:
            result = await self._call_qwen_vl(image_base64, prompt)
            if result:
                engine_used = "qwen3_vl"
                self._stats["qwen_calls"] += 1

        # Level 4: Tesseract 离线降级
        if not result:
            result = await self._call_tesseract_fallback(image_base64)
            if result:
                engine_used = "tesseract"
                self._stats["tesseract_calls"] += 1

        if not result:
            self._stats["errors"] += 1
            return VisionResult(success=False, error="所有视觉引擎均不可用")

        # 解析结果
        processing_time = (time.time() - start_time) * 1000
        vision_result = self._parse_result(result, mode, engine_used)
        vision_result.processing_time_ms = processing_time
        vision_result.engine_used = engine_used

        # 融合：将 OCR 文本与 GUI 元素关联
        if mode == "full":
            self._fuse_ocr_and_gui(vision_result)

        # 更新统计
        total = self._stats["total_calls"]
        self._stats["avg_time_ms"] = (
            (self._stats["avg_time_ms"] * (total - 1) + processing_time) / total
        )

        return vision_result

    async def find_element(
        self,
        description: str,
        image_base64: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> Optional[GUIElement]:
        """
        查找特定 GUI 元素

        Args:
            description: 元素描述（如 "登录按钮"、"搜索输入框"）
            image_base64: Base64 编码的图片
            image_path: 图片文件路径

        Returns:
            找到的 GUIElement 或 None
        """
        result = await self.understand(
            image_base64=image_base64,
            image_path=image_path,
            mode="find_element",
            task_context=description,
        )

        if not result.success:
            return None

        # 如果 find_element 模式直接返回了元素
        if result.gui_elements:
            return result.gui_elements[0]

        # 否则在完整分析结果中查找
        return result.find_element_by_text(description)

    async def extract_text(
        self,
        image_base64: Optional[str] = None,
        image_path: Optional[str] = None,
    ) -> str:
        """
        提取图片中的所有文本

        Args:
            image_base64: Base64 编码的图片
            image_path: 图片文件路径

        Returns:
            提取的文本
        """
        result = await self.understand(
            image_base64=image_base64,
            image_path=image_path,
            mode="ocr_only",
        )
        return result.full_text if result.success else ""

    def get_stats(self) -> Dict:
        """获取统计信息"""
        return dict(self._stats)

    # =========================================================================
    # 引擎调用
    # =========================================================================

    async def _call_deepseek_ocr2(self, image_base64: str, prompt: str) -> Optional[Dict]:
        """调用 DeepSeek OCR 2"""
        try:
            client = await self._get_client()

            # 优先使用本地 vLLM
            api_base = self.local_vllm_url if self.local_vllm_url else self.deepseek_api_base
            api_key = self.deepseek_api_key if not self.local_vllm_url else "local"

            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": self.deepseek_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                "max_tokens": 4096,
                "temperature": 0.1,
            }

            response = await client.post(
                f"{api_base}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            return self._extract_json(content)

        except Exception as e:
            logger.warning(f"DeepSeek OCR 2 调用失败: {e}")
            return None

    async def _call_gemini(self, image_base64: str, prompt: str) -> Optional[Dict]:
        """调用 Gemini 2.0 Flash"""
        try:
            client = await self._get_client()

            headers = {"Content-Type": "application/json"}
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={self.gemini_api_key}"

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"inline_data": {"mime_type": "image/png", "data": image_base64}},
                            {"text": prompt},
                        ]
                    }
                ],
                "generationConfig": {"temperature": 0.1, "maxOutputTokens": 4096},
            }

            response = await client.post(url, headers=headers, json=payload, timeout=60.0)
            response.raise_for_status()
            data = response.json()

            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return self._extract_json(content)

        except Exception as e:
            logger.warning(f"Gemini 调用失败: {e}")
            return None

    async def _call_qwen_vl(self, image_base64: str, prompt: str) -> Optional[Dict]:
        """调用 Qwen3-VL via OpenRouter"""
        try:
            client = await self._get_client()

            headers = {
                "Authorization": f"Bearer {self.openrouter_api_key}",
                "Content-Type": "application/json",
            }

            payload = {
                "model": "qwen/qwen-2.5-vl-72b-instruct",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                            {"type": "text", "text": prompt},
                        ],
                    }
                ],
                "max_tokens": 4096,
                "temperature": 0.1,
            }

            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

            content = data["choices"][0]["message"]["content"]
            return self._extract_json(content)

        except Exception as e:
            logger.warning(f"Qwen3-VL 调用失败: {e}")
            return None

    async def _call_tesseract_fallback(self, image_base64: str) -> Optional[Dict]:
        """Tesseract 离线降级"""
        try:
            import pytesseract
            from PIL import Image
            import io

            image_data = base64.b64decode(image_base64)
            image = Image.open(io.BytesIO(image_data))

            # 获取详细 OCR 数据
            ocr_data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)

            texts = []
            for i in range(len(ocr_data["text"])):
                text = ocr_data["text"][i].strip()
                conf = int(ocr_data["conf"][i])
                if text and conf > 30:
                    texts.append({
                        "text": text,
                        "bbox": [
                            ocr_data["left"][i],
                            ocr_data["top"][i],
                            ocr_data["width"][i],
                            ocr_data["height"][i],
                        ],
                        "confidence": conf / 100.0,
                    })

            full_text = pytesseract.image_to_string(image)

            return {
                "ocr_texts": texts,
                "full_text": full_text,
                "scene": {
                    "app_name": "",
                    "page_type": "unknown",
                    "platform": "unknown",
                    "description": "Tesseract offline OCR result",
                    "state": "idle",
                    "key_info": {},
                },
                "elements": [],
                "action_hints": [],
            }

        except Exception as e:
            logger.warning(f"Tesseract 降级失败: {e}")
            return None

    # =========================================================================
    # 结果解析和融合
    # =========================================================================

    def _extract_json(self, text: str) -> Optional[Dict]:
        """从 LLM 响应中提取 JSON"""
        text = text.strip()

        # 去除 markdown 代码块
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到 JSON 对象
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            logger.warning(f"无法解析 JSON 响应: {text[:200]}...")
            return None

    def _parse_result(self, raw: Dict, mode: str, engine: str) -> VisionResult:
        """解析原始结果为 VisionResult"""
        result = VisionResult(success=True)

        # 解析 OCR 文本
        for item in raw.get("ocr_texts", raw.get("texts", [])):
            bbox_data = item.get("bbox", [0, 0, 0, 0])
            result.ocr_words.append(OCRWord(
                text=item.get("text", ""),
                bbox=BoundingBox(
                    x=int(bbox_data[0]),
                    y=int(bbox_data[1]),
                    width=int(bbox_data[2]) if len(bbox_data) > 2 else 0,
                    height=int(bbox_data[3]) if len(bbox_data) > 3 else 0,
                ),
                confidence=float(item.get("confidence", 0.5)),
            ))

        result.raw_text = raw.get("full_text", "")

        # 解析 GUI 元素
        for item in raw.get("elements", []):
            bbox_data = item.get("bbox", [0, 0, 0, 0])
            elem_type_str = item.get("type", "unknown")
            try:
                elem_type = ElementType(elem_type_str)
            except ValueError:
                elem_type = ElementType.UNKNOWN

            interactions = []
            for it_str in item.get("interactions", []):
                try:
                    interactions.append(InteractionType(it_str))
                except ValueError:
                    pass

            result.gui_elements.append(GUIElement(
                element_id=item.get("id", f"elem_{len(result.gui_elements)}"),
                element_type=elem_type,
                text=item.get("text", ""),
                bbox=BoundingBox(
                    x=int(bbox_data[0]),
                    y=int(bbox_data[1]),
                    width=int(bbox_data[2]) if len(bbox_data) > 2 else 0,
                    height=int(bbox_data[3]) if len(bbox_data) > 3 else 0,
                ),
                confidence=float(item.get("confidence", 0.5)),
                interactable=item.get("interactable", False),
                interaction_types=interactions,
                attributes=item.get("attributes", {}),
            ))

        # 解析场景
        scene_data = raw.get("scene", {})
        result.scene = SceneContext(
            app_name=scene_data.get("app_name", ""),
            page_type=scene_data.get("page_type", ""),
            platform=scene_data.get("platform", ""),
            description=scene_data.get("description", ""),
            state=scene_data.get("state", ""),
            key_info=scene_data.get("key_info", {}),
        )

        # 解析动作建议
        for item in raw.get("action_hints", []):
            result.action_hints.append(ActionHint(
                action=item.get("action", ""),
                target_element_id=item.get("target"),
                description=item.get("action", ""),
                priority=float(item.get("priority", 0.5)),
            ))

        # 处理 find_element 模式
        if mode == "find_element" and raw.get("found"):
            elem_data = raw.get("element", {})
            if elem_data:
                bbox_data = elem_data.get("bbox", [0, 0, 0, 0])
                elem_type_str = elem_data.get("type", "unknown")
                try:
                    elem_type = ElementType(elem_type_str)
                except ValueError:
                    elem_type = ElementType.UNKNOWN

                result.gui_elements = [GUIElement(
                    element_id="found_0",
                    element_type=elem_type,
                    text=elem_data.get("text", ""),
                    bbox=BoundingBox(
                        x=int(bbox_data[0]),
                        y=int(bbox_data[1]),
                        width=int(bbox_data[2]) if len(bbox_data) > 2 else 0,
                        height=int(bbox_data[3]) if len(bbox_data) > 3 else 0,
                    ),
                    confidence=float(elem_data.get("confidence", 0.5)),
                    interactable=True,
                    interaction_types=[InteractionType.CLICK],
                )]

        return result

    def _fuse_ocr_and_gui(self, result: VisionResult):
        """
        融合 OCR 和 GUI 结果

        核心融合逻辑：
        1. 将 OCR 文本块关联到最近的 GUI 元素
        2. 为没有文本的 GUI 元素补充 OCR 文本
        3. 为没有对应 GUI 元素的 OCR 文本创建 TEXT 类型元素
        4. 合并重叠的元素
        """
        if not result.ocr_words or not result.gui_elements:
            return

        # Step 1: 关联 OCR 文本到 GUI 元素
        matched_ocr = set()
        for elem in result.gui_elements:
            if not elem.text:
                # 查找与该元素重叠的 OCR 文本
                best_match = None
                best_overlap = 0
                for i, word in enumerate(result.ocr_words):
                    if i in matched_ocr:
                        continue
                    overlap = elem.bbox.overlap_ratio(word.bbox)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_match = i

                if best_match is not None and best_overlap > 0.3:
                    elem.text = result.ocr_words[best_match].text
                    matched_ocr.add(best_match)

        # Step 2: 为未匹配的 OCR 文本创建 TEXT 元素
        for i, word in enumerate(result.ocr_words):
            if i not in matched_ocr:
                # 检查是否与任何现有元素高度重叠
                is_covered = False
                for elem in result.gui_elements:
                    if elem.bbox.overlap_ratio(word.bbox) > 0.5:
                        is_covered = True
                        break

                if not is_covered:
                    result.gui_elements.append(GUIElement(
                        element_id=f"ocr_text_{i}",
                        element_type=ElementType.TEXT,
                        text=word.text,
                        bbox=word.bbox,
                        confidence=word.confidence,
                        interactable=False,
                    ))

        # Step 3: 合并高度重叠的元素
        merged = []
        skip = set()
        for i, elem_a in enumerate(result.gui_elements):
            if i in skip:
                continue
            for j, elem_b in enumerate(result.gui_elements):
                if j <= i or j in skip:
                    continue
                if elem_a.bbox.overlap_ratio(elem_b.bbox) > 0.8:
                    # 保留信息更丰富的那个
                    if len(elem_b.text) > len(elem_a.text):
                        elem_a.text = elem_b.text
                    if elem_b.interactable and not elem_a.interactable:
                        elem_a.interactable = True
                        elem_a.interaction_types = elem_b.interaction_types
                    if elem_b.confidence > elem_a.confidence:
                        elem_a.confidence = elem_b.confidence
                    skip.add(j)
            merged.append(elem_a)

        result.gui_elements = merged


# =============================================================================
# 全局实例
# =============================================================================

_pipeline_instance: Optional[VisionPipeline] = None


def get_vision_pipeline(config: Optional[Dict] = None) -> VisionPipeline:
    """获取全局 VisionPipeline 实例"""
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = VisionPipeline(config)
    return _pipeline_instance


async def understand_screen(
    image_base64: Optional[str] = None,
    image_path: Optional[str] = None,
    mode: str = "full",
    task_context: str = "",
) -> VisionResult:
    """便捷函数：理解屏幕"""
    pipeline = get_vision_pipeline()
    return await pipeline.understand(image_base64, image_path, mode, task_context)


async def find_element(
    description: str,
    image_base64: Optional[str] = None,
    image_path: Optional[str] = None,
) -> Optional[GUIElement]:
    """便捷函数：查找元素"""
    pipeline = get_vision_pipeline()
    return await pipeline.find_element(description, image_base64, image_path)


async def extract_text(
    image_base64: Optional[str] = None,
    image_path: Optional[str] = None,
) -> str:
    """便捷函数：提取文本"""
    pipeline = get_vision_pipeline()
    return await pipeline.extract_text(image_base64, image_path)
