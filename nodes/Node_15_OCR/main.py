"""
Node_15_OCR - UFO Galaxy OCR 服务节点
=====================================

主引擎: DeepSeek OCR 2 (Visual Causal Flow)
降级引擎: Tesseract OCR (离线模式)

DeepSeek OCR 2 通过 OpenAI 兼容 API 调用，支持：
  - Novita.ai 云端 API
  - 本地 vLLM 部署
  - DeepSeek 官方 API（如可用）

版本: 2.0.0
日期: 2026-02-06
"""

import asyncio
import logging
import json
import os
import time
import base64
import io
import traceback
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Tuple
from PIL import Image
from aiohttp import web

# ==============================================================================
# 日志配置
# ==============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("Node_15_OCR")


# ==============================================================================
# 配置和状态定义
# ==============================================================================

class NodeStatus(Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    DEGRADED = "DEGRADED"


class OCREngine(Enum):
    """OCR 引擎类型"""
    DEEPSEEK_OCR2 = "deepseek_ocr2"       # DeepSeek OCR 2 (主引擎)
    DEEPSEEK_OCR2_LOCAL = "deepseek_ocr2_local"  # 本地部署的 DeepSeek OCR 2
    TESSERACT = "tesseract"                 # Tesseract (降级引擎)
    AUTO = "auto"                           # 自动选择


class OCRMode(Enum):
    """OCR 识别模式"""
    FREE_OCR = "free_ocr"                   # 自由 OCR（纯文本提取）
    DOCUMENT_MARKDOWN = "document_markdown"  # 文档转 Markdown（保留格式）
    UI_ANALYSIS = "ui_analysis"             # UI 元素分析
    TABLE_EXTRACT = "table_extract"         # 表格提取
    HANDWRITING = "handwriting"             # 手写识别


@dataclass
class OCRConfig:
    """OCR 节点配置"""
    node_name: str = "Node_15_OCR"
    host: str = "0.0.0.0"
    port: int = 8015

    # DeepSeek OCR 2 云端 API 配置 (Novita.ai)
    deepseek_ocr2_api_key: str = ""
    deepseek_ocr2_api_base: str = "https://api.novita.ai/openai"
    deepseek_ocr2_model: str = "deepseek/deepseek-ocr-2"

    # DeepSeek OCR 2 本地部署配置
    deepseek_ocr2_local_url: str = ""  # 例如 http://localhost:8000/v1
    deepseek_ocr2_local_model: str = "deepseek-ai/DeepSeek-OCR-2"

    # Tesseract 降级配置
    tesseract_cmd_path: Optional[str] = None
    default_language: str = "eng+chi_sim"
    supported_languages: List[str] = field(
        default_factory=lambda: ["eng", "chi_sim", "chi_tra", "jpn", "kor", "fra", "deu"]
    )

    # 引擎选择
    primary_engine: str = "deepseek_ocr2"
    fallback_engine: str = "tesseract"
    default_mode: str = "free_ocr"

    # 性能配置
    max_image_size: int = 4096  # 最大图像尺寸（像素）
    jpeg_quality: int = 85
    request_timeout: int = 60
    max_concurrent_requests: int = 10

    config_file_path: str = "config.json"


# ==============================================================================
# DeepSeek OCR 2 客户端
# ==============================================================================

class DeepSeekOCR2Client:
    """
    DeepSeek OCR 2 API 客户端
    
    通过 OpenAI 兼容 API 调用 DeepSeek OCR 2 模型。
    支持云端 API (Novita.ai) 和本地 vLLM 部署。
    """

    # DeepSeek OCR 2 的标准 Prompt
    PROMPTS = {
        OCRMode.FREE_OCR: "<image>\nFree OCR. ",
        OCRMode.DOCUMENT_MARKDOWN: "<image>\n<|grounding|>Convert the document to markdown. ",
        OCRMode.UI_ANALYSIS: (
            "<image>\nAnalyze this UI screenshot. Identify all interactive elements "
            "(buttons, text fields, links, menus) with their positions, text content, "
            "and element types. Output as structured JSON."
        ),
        OCRMode.TABLE_EXTRACT: (
            "<image>\n<|grounding|>Extract all tables from this document. "
            "Convert each table to markdown table format. Preserve the structure and content."
        ),
        OCRMode.HANDWRITING: "<image>\nRecognize all handwritten text in this image. ",
    }

    def __init__(self, config: OCRConfig):
        self.config = config
        self._session = None
        self._available = False
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "avg_latency_ms": 0,
        }
        logger.info("DeepSeek OCR 2 客户端已创建")

    async def initialize(self) -> bool:
        """初始化客户端，检查 API 可用性"""
        try:
            import aiohttp
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.config.request_timeout)
            )

            # 检查 API Key
            if not self.config.deepseek_ocr2_api_key:
                # 尝试从环境变量获取
                self.config.deepseek_ocr2_api_key = os.getenv("NOVITA_API_KEY", "")
                if not self.config.deepseek_ocr2_api_key:
                    self.config.deepseek_ocr2_api_key = os.getenv("DEEPSEEK_OCR_API_KEY", "")

            if self.config.deepseek_ocr2_api_key:
                self._available = True
                logger.info(
                    f"DeepSeek OCR 2 云端 API 已配置: {self.config.deepseek_ocr2_api_base}"
                )
            elif self.config.deepseek_ocr2_local_url:
                # 检查本地部署是否可用
                try:
                    async with self._session.get(
                        f"{self.config.deepseek_ocr2_local_url}/models"
                    ) as resp:
                        if resp.status == 200:
                            self._available = True
                            logger.info(
                                f"DeepSeek OCR 2 本地部署已连接: "
                                f"{self.config.deepseek_ocr2_local_url}"
                            )
                except Exception:
                    logger.warning("DeepSeek OCR 2 本地部署不可用")
            else:
                logger.warning(
                    "DeepSeek OCR 2 未配置 API Key 或本地部署地址，将使用降级引擎"
                )

            return self._available
        except Exception as e:
            logger.error(f"DeepSeek OCR 2 客户端初始化失败: {e}")
            return False

    @property
    def available(self) -> bool:
        return self._available

    @property
    def stats(self) -> Dict[str, Any]:
        return self._stats.copy()

    def _get_api_config(self) -> Tuple[str, str, Dict[str, str]]:
        """获取 API 配置（URL, 模型名, 请求头）"""
        if self.config.deepseek_ocr2_local_url:
            return (
                f"{self.config.deepseek_ocr2_local_url}/chat/completions",
                self.config.deepseek_ocr2_local_model,
                {"Content-Type": "application/json"},
            )
        else:
            return (
                f"{self.config.deepseek_ocr2_api_base}/chat/completions",
                self.config.deepseek_ocr2_model,
                {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.config.deepseek_ocr2_api_key}",
                },
            )

    def _prepare_image(self, image_bytes: bytes) -> str:
        """预处理图像并转为 base64"""
        image = Image.open(io.BytesIO(image_bytes))

        # 限制最大尺寸
        max_size = self.config.max_image_size
        if image.width > max_size or image.height > max_size:
            ratio = min(max_size / image.width, max_size / image.height)
            new_size = (int(image.width * ratio), int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"图像已缩放至 {new_size}")

        # 转为 JPEG base64
        buffer = io.BytesIO()
        if image.mode == "RGBA":
            image = image.convert("RGB")
        image.save(buffer, format="JPEG", quality=self.config.jpeg_quality)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")

    async def recognize(
        self,
        image_bytes: bytes,
        mode: OCRMode = OCRMode.FREE_OCR,
        custom_prompt: Optional[str] = None,
        language: str = "auto",
    ) -> Dict[str, Any]:
        """
        使用 DeepSeek OCR 2 进行识别

        参数:
            image_bytes: 图像字节数据
            mode: OCR 模式
            custom_prompt: 自定义 prompt（覆盖默认）
            language: 语言提示（auto 为自动检测）

        返回:
            包含识别结果的字典
        """
        if not self._available:
            return {"success": False, "error": "DeepSeek OCR 2 不可用"}

        start_time = time.time()
        self._stats["total_requests"] += 1

        try:
            # 准备图像
            image_b64 = self._prepare_image(image_bytes)

            # 构建 prompt
            if custom_prompt:
                prompt = custom_prompt
            else:
                prompt = self.PROMPTS.get(mode, self.PROMPTS[OCRMode.FREE_OCR])

            if language != "auto":
                lang_map = {
                    "chi_sim": "Chinese (Simplified)",
                    "chi_tra": "Chinese (Traditional)",
                    "eng": "English",
                    "jpn": "Japanese",
                    "kor": "Korean",
                    "fra": "French",
                    "deu": "German",
                }
                lang_name = lang_map.get(language, language)
                prompt += f"\nLanguage hint: {lang_name}"

            # 构建请求
            api_url, model_name, headers = self._get_api_config()

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

            # 发送请求
            async with self._session.post(
                api_url, json=payload, headers=headers
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    logger.error(
                        f"DeepSeek OCR 2 API 错误 [{resp.status}]: {error_text}"
                    )
                    self._stats["failed_requests"] += 1
                    return {
                        "success": False,
                        "error": f"API 错误 [{resp.status}]: {error_text}",
                    }

                result = await resp.json()

            # 解析结果
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            latency_ms = (time.time() - start_time) * 1000
            self._stats["successful_requests"] += 1
            total = self._stats["successful_requests"]
            self._stats["avg_latency_ms"] = (
                self._stats["avg_latency_ms"] * (total - 1) + latency_ms
            ) / total

            # 提取 token 使用信息
            usage = result.get("usage", {})

            logger.info(
                f"DeepSeek OCR 2 识别完成: "
                f"模式={mode.value}, "
                f"耗时={latency_ms:.0f}ms, "
                f"输入tokens={usage.get('prompt_tokens', 'N/A')}, "
                f"输出tokens={usage.get('completion_tokens', 'N/A')}"
            )

            return {
                "success": True,
                "engine": "deepseek_ocr2",
                "mode": mode.value,
                "text": content,
                "latency_ms": round(latency_ms, 2),
                "usage": usage,
            }

        except asyncio.TimeoutError:
            self._stats["failed_requests"] += 1
            logger.error("DeepSeek OCR 2 请求超时")
            return {"success": False, "error": "请求超时"}
        except Exception as e:
            self._stats["failed_requests"] += 1
            logger.error(f"DeepSeek OCR 2 识别失败: {e}\n{traceback.format_exc()}")
            return {"success": False, "error": str(e)}

    async def close(self):
        """关闭客户端"""
        if self._session:
            await self._session.close()


# ==============================================================================
# Tesseract 降级引擎
# ==============================================================================

class TesseractEngine:
    """Tesseract OCR 降级引擎"""

    def __init__(self, config: OCRConfig):
        self.config = config
        self._available = False

    async def initialize(self) -> bool:
        """初始化 Tesseract"""
        try:
            import pytesseract as pt
            self._pytesseract = pt

            if self.config.tesseract_cmd_path:
                pt.pytesseract.tesseract_cmd = self.config.tesseract_cmd_path

            version = pt.get_tesseract_version()
            self._available = True
            logger.info(f"Tesseract OCR 已就绪，版本: {version}")
            return True
        except Exception as e:
            logger.warning(f"Tesseract OCR 不可用: {e}")
            return False

    @property
    def available(self) -> bool:
        return self._available

    async def recognize(
        self, image_bytes: bytes, language: str = "eng"
    ) -> Dict[str, Any]:
        """使用 Tesseract 进行 OCR"""
        if not self._available:
            return {"success": False, "error": "Tesseract 不可用"}

        start_time = time.time()
        try:
            image = Image.open(io.BytesIO(image_bytes))
            loop = asyncio.get_running_loop()

            # 文本识别
            text = await loop.run_in_executor(
                None,
                lambda: self._pytesseract.image_to_string(image, lang=language),
            )

            # 带位置信息的识别
            data = await loop.run_in_executor(
                None,
                lambda: self._pytesseract.image_to_data(
                    image, lang=language, output_type=self._pytesseract.Output.DICT
                ),
            )

            # 构建文本块列表
            text_blocks = []
            n_boxes = len(data["text"])
            for i in range(n_boxes):
                if int(data["conf"][i]) > 30 and data["text"][i].strip():
                    text_blocks.append(
                        {
                            "text": data["text"][i],
                            "x": data["left"][i],
                            "y": data["top"][i],
                            "width": data["width"][i],
                            "height": data["height"][i],
                            "confidence": int(data["conf"][i]) / 100.0,
                        }
                    )

            latency_ms = (time.time() - start_time) * 1000

            return {
                "success": True,
                "engine": "tesseract",
                "mode": "free_ocr",
                "text": text.strip(),
                "text_blocks": text_blocks,
                "latency_ms": round(latency_ms, 2),
            }
        except Exception as e:
            logger.error(f"Tesseract OCR 失败: {e}")
            return {"success": False, "error": str(e)}


# ==============================================================================
# OCR 服务节点
# ==============================================================================

class OCRNode:
    """
    OCR 服务节点主类
    
    主引擎: DeepSeek OCR 2
    降级引擎: Tesseract OCR
    """

    def __init__(self):
        self.config = OCRConfig()
        self.status = NodeStatus.CREATED
        self.app = web.Application()

        # 引擎实例
        self.deepseek_client: Optional[DeepSeekOCR2Client] = None
        self.tesseract_engine: Optional[TesseractEngine] = None

        # 并发控制
        self._semaphore: Optional[asyncio.Semaphore] = None

        # 统计
        self._start_time = time.time()

        self._setup_routes()
        logger.info(f"节点 {self.config.node_name} 已创建")

    async def initialize(self):
        """初始化节点"""
        self.status = NodeStatus.INITIALIZING
        logger.info("=" * 60)
        logger.info("Node_15_OCR 初始化中...")
        logger.info("主引擎: DeepSeek OCR 2 (Visual Causal Flow)")
        logger.info("降级引擎: Tesseract OCR")
        logger.info("=" * 60)

        await self._load_config()

        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_requests)

        # 初始化 DeepSeek OCR 2
        self.deepseek_client = DeepSeekOCR2Client(self.config)
        deepseek_ok = await self.deepseek_client.initialize()

        # 初始化 Tesseract 降级引擎
        self.tesseract_engine = TesseractEngine(self.config)
        tesseract_ok = await self.tesseract_engine.initialize()

        if deepseek_ok:
            self.status = NodeStatus.RUNNING
            logger.info("✅ DeepSeek OCR 2 已就绪（主引擎）")
        elif tesseract_ok:
            self.status = NodeStatus.DEGRADED
            logger.warning("⚠️ DeepSeek OCR 2 不可用，降级到 Tesseract")
        else:
            self.status = NodeStatus.ERROR
            logger.error("❌ 所有 OCR 引擎均不可用")

        if tesseract_ok:
            logger.info("✅ Tesseract OCR 已就绪（降级引擎）")
        else:
            logger.warning("⚠️ Tesseract OCR 不可用")

        logger.info(f"节点状态: {self.status.value}")

    async def _load_config(self):
        """加载配置"""
        config_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), self.config.config_file_path
        )

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if hasattr(self.config, key):
                        setattr(self.config, key, value)
                logger.info(f"配置已从 {config_path} 加载")
            except Exception as e:
                logger.warning(f"加载配置失败: {e}，使用默认配置")

        # 从环境变量覆盖关键配置
        env_mappings = {
            "NOVITA_API_KEY": "deepseek_ocr2_api_key",
            "DEEPSEEK_OCR_API_KEY": "deepseek_ocr2_api_key",
            "DEEPSEEK_OCR2_API_BASE": "deepseek_ocr2_api_base",
            "DEEPSEEK_OCR2_LOCAL_URL": "deepseek_ocr2_local_url",
            "TESSERACT_CMD": "tesseract_cmd_path",
        }
        for env_key, config_key in env_mappings.items():
            env_val = os.getenv(env_key)
            if env_val:
                setattr(self.config, config_key, env_val)

    def _setup_routes(self):
        """设置 API 路由"""
        self.app.router.add_post("/ocr", self.handle_ocr)
        self.app.router.add_post("/ocr/batch", self.handle_ocr_batch)
        self.app.router.add_post("/ocr/document", self.handle_document_ocr)
        self.app.router.add_post("/ocr/ui-analysis", self.handle_ui_analysis)
        self.app.router.add_post("/upload", self.handle_upload)
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/status", self.handle_status)
        self.app.router.add_get("/engines", self.handle_engines)
        self.app.router.add_post("/mcp/call", self.handle_mcp_call)

    # ==========================================================================
    # 核心 OCR 逻辑
    # ==========================================================================

    async def perform_ocr(
        self,
        image_bytes: bytes,
        mode: OCRMode = OCRMode.FREE_OCR,
        engine: OCREngine = OCREngine.AUTO,
        language: str = "auto",
        custom_prompt: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        执行 OCR 识别

        参数:
            image_bytes: 图像字节数据
            mode: OCR 模式
            engine: 指定引擎（AUTO 自动选择）
            language: 语言
            custom_prompt: 自定义 prompt

        返回:
            识别结果字典
        """
        async with self._semaphore:
            # 自动选择引擎
            if engine == OCREngine.AUTO:
                if (
                    self.deepseek_client
                    and self.deepseek_client.available
                ):
                    engine = OCREngine.DEEPSEEK_OCR2
                elif (
                    self.tesseract_engine
                    and self.tesseract_engine.available
                ):
                    engine = OCREngine.TESSERACT
                else:
                    return {"success": False, "error": "没有可用的 OCR 引擎"}

            # DeepSeek OCR 2
            if engine in (OCREngine.DEEPSEEK_OCR2, OCREngine.DEEPSEEK_OCR2_LOCAL):
                result = await self.deepseek_client.recognize(
                    image_bytes, mode, custom_prompt, language
                )
                # 如果 DeepSeek 失败，尝试降级
                if (
                    not result["success"]
                    and self.tesseract_engine
                    and self.tesseract_engine.available
                ):
                    logger.warning("DeepSeek OCR 2 失败，降级到 Tesseract")
                    tess_lang = language if language != "auto" else "eng"
                    result = await self.tesseract_engine.recognize(
                        image_bytes, tess_lang
                    )
                    result["fallback"] = True
                return result

            # Tesseract
            elif engine == OCREngine.TESSERACT:
                tess_lang = language if language != "auto" else "eng"
                return await self.tesseract_engine.recognize(image_bytes, tess_lang)

            else:
                return {"success": False, "error": f"未知引擎: {engine}"}

    # ==========================================================================
    # API 接口处理
    # ==========================================================================

    async def handle_ocr(self, request: web.Request) -> web.Response:
        """
        POST /ocr - 通用 OCR 识别
        
        请求体:
        {
            "image": "base64_encoded_string",
            "mode": "free_ocr|document_markdown|ui_analysis|table_extract|handwriting",
            "engine": "auto|deepseek_ocr2|tesseract",
            "language": "auto|eng|chi_sim|...",
            "prompt": "可选的自定义 prompt"
        }
        """
        try:
            data = await request.json()
            if "image" not in data:
                return web.json_response(
                    {"error": "缺少 'image' 字段"}, status=400
                )

            image_bytes = base64.b64decode(data["image"])
            mode_str = data.get("mode", self.config.default_mode)
            engine_str = data.get("engine", "auto")
            language = data.get("language", "auto")
            custom_prompt = data.get("prompt")

            mode = OCRMode(mode_str) if mode_str in [m.value for m in OCRMode] else OCRMode.FREE_OCR
            engine = OCREngine(engine_str) if engine_str in [e.value for e in OCREngine] else OCREngine.AUTO

            result = await self.perform_ocr(
                image_bytes, mode, engine, language, custom_prompt
            )
            status_code = 200 if result.get("success") else 500
            return web.json_response(result, status=status_code)

        except json.JSONDecodeError:
            return web.json_response({"error": "无效的 JSON"}, status=400)
        except Exception as e:
            logger.error(f"OCR 请求处理失败: {e}")
            return web.json_response({"error": str(e)}, status=500)

    async def handle_ocr_batch(self, request: web.Request) -> web.Response:
        """
        POST /ocr/batch - 批量 OCR 识别
        
        请求体:
        {
            "images": ["base64_1", "base64_2", ...],
            "mode": "free_ocr",
            "language": "auto"
        }
        """
        try:
            data = await request.json()
            images = data.get("images", [])
            if not images:
                return web.json_response(
                    {"error": "缺少 'images' 字段"}, status=400
                )

            mode_str = data.get("mode", "free_ocr")
            mode = OCRMode(mode_str) if mode_str in [m.value for m in OCRMode] else OCRMode.FREE_OCR
            language = data.get("language", "auto")

            # 并发处理
            tasks = []
            for img_b64 in images:
                img_bytes = base64.b64decode(img_b64)
                tasks.append(
                    self.perform_ocr(img_bytes, mode, OCREngine.AUTO, language)
                )

            results = await asyncio.gather(*tasks, return_exceptions=True)

            processed = []
            for r in results:
                if isinstance(r, Exception):
                    processed.append({"success": False, "error": str(r)})
                else:
                    processed.append(r)

            return web.json_response(
                {"success": True, "count": len(processed), "results": processed}
            )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_document_ocr(self, request: web.Request) -> web.Response:
        """
        POST /ocr/document - 文档 OCR（转 Markdown）
        
        请求体:
        {
            "image": "base64_encoded_string",
            "language": "auto"
        }
        """
        try:
            data = await request.json()
            if "image" not in data:
                return web.json_response(
                    {"error": "缺少 'image' 字段"}, status=400
                )

            image_bytes = base64.b64decode(data["image"])
            language = data.get("language", "auto")

            result = await self.perform_ocr(
                image_bytes, OCRMode.DOCUMENT_MARKDOWN, OCREngine.AUTO, language
            )
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_ui_analysis(self, request: web.Request) -> web.Response:
        """
        POST /ocr/ui-analysis - UI 元素分析
        
        请求体:
        {
            "image": "base64_encoded_string",
            "instruction": "可选的指令"
        }
        """
        try:
            data = await request.json()
            if "image" not in data:
                return web.json_response(
                    {"error": "缺少 'image' 字段"}, status=400
                )

            image_bytes = base64.b64decode(data["image"])
            instruction = data.get("instruction", "")

            custom_prompt = None
            if instruction:
                custom_prompt = (
                    f"<image>\nAnalyze this UI screenshot. {instruction}\n"
                    f"Identify all interactive elements with positions and types. "
                    f"Output as structured JSON."
                )

            result = await self.perform_ocr(
                image_bytes, OCRMode.UI_ANALYSIS, OCREngine.AUTO, "auto", custom_prompt
            )
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_upload(self, request: web.Request) -> web.Response:
        """POST /upload - 上传文件进行 OCR"""
        try:
            reader = await request.multipart()
            field = await reader.next()
            if field is None:
                return web.json_response({"error": "没有上传文件"}, status=400)

            image_bytes = await field.read()
            result = await self.perform_ocr(image_bytes, OCRMode.FREE_OCR)
            return web.json_response(result)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def handle_health(self, request: web.Request) -> web.Response:
        """GET /health - 健康检查"""
        if self.status == NodeStatus.RUNNING:
            return web.json_response({"status": "ok", "engine": "deepseek_ocr2"})
        elif self.status == NodeStatus.DEGRADED:
            return web.json_response(
                {"status": "degraded", "engine": "tesseract"}, status=200
            )
        else:
            return web.json_response(
                {"status": "error", "detail": self.status.value}, status=503
            )

    async def handle_status(self, request: web.Request) -> web.Response:
        """GET /status - 详细状态"""
        uptime = time.time() - self._start_time
        return web.json_response(
            {
                "node_name": self.config.node_name,
                "status": self.status.value,
                "uptime_seconds": round(uptime, 2),
                "engines": {
                    "deepseek_ocr2": {
                        "available": (
                            self.deepseek_client.available
                            if self.deepseek_client
                            else False
                        ),
                        "model": self.config.deepseek_ocr2_model,
                        "api_base": self.config.deepseek_ocr2_api_base,
                        "stats": (
                            self.deepseek_client.stats
                            if self.deepseek_client
                            else {}
                        ),
                    },
                    "tesseract": {
                        "available": (
                            self.tesseract_engine.available
                            if self.tesseract_engine
                            else False
                        ),
                        "default_language": self.config.default_language,
                    },
                },
                "config": {
                    "primary_engine": self.config.primary_engine,
                    "fallback_engine": self.config.fallback_engine,
                    "default_mode": self.config.default_mode,
                    "max_concurrent": self.config.max_concurrent_requests,
                },
            }
        )

    async def handle_engines(self, request: web.Request) -> web.Response:
        """GET /engines - 列出可用引擎"""
        return web.json_response(
            {
                "engines": [
                    {
                        "name": "deepseek_ocr2",
                        "display_name": "DeepSeek OCR 2",
                        "description": (
                            "DeepSeek OCR 2 (Visual Causal Flow) - "
                            "SOTA 文档识别模型，支持多种模式"
                        ),
                        "available": (
                            self.deepseek_client.available
                            if self.deepseek_client
                            else False
                        ),
                        "modes": [m.value for m in OCRMode],
                        "primary": True,
                    },
                    {
                        "name": "tesseract",
                        "display_name": "Tesseract OCR",
                        "description": "开源 OCR 引擎（离线降级方案）",
                        "available": (
                            self.tesseract_engine.available
                            if self.tesseract_engine
                            else False
                        ),
                        "modes": ["free_ocr"],
                        "primary": False,
                    },
                ]
            }
        )

    async def handle_mcp_call(self, request: web.Request) -> web.Response:
        """POST /mcp/call - MCP 协议调用接口"""
        try:
            data = await request.json()
            tool = data.get("tool", "")
            params = data.get("params", {})

            if tool == "recognize":
                image_b64 = params.get("image", "")
                image_bytes = base64.b64decode(image_b64)
                mode_str = params.get("mode", "free_ocr")
                mode = OCRMode(mode_str) if mode_str in [m.value for m in OCRMode] else OCRMode.FREE_OCR
                result = await self.perform_ocr(image_bytes, mode)
                return web.json_response(result)
            elif tool == "status":
                return await self.handle_status(request)
            elif tool == "engines":
                return await self.handle_engines(request)
            else:
                return web.json_response(
                    {"error": f"未知工具: {tool}"}, status=400
                )
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    # ==========================================================================
    # 启动和停止
    # ==========================================================================

    async def start(self):
        """启动服务"""
        await self.initialize()
        if self.status in (NodeStatus.ERROR,):
            logger.error("初始化失败，节点无法启动")
            return

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.config.host, self.config.port)
        await site.start()
        logger.info(
            f"🚀 Node_15_OCR 已启动: http://{self.config.host}:{self.config.port}"
        )
        logger.info(f"   主引擎: DeepSeek OCR 2 ({self.config.deepseek_ocr2_model})")
        logger.info(f"   降级引擎: Tesseract OCR")

        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            logger.info("服务正在停止...")
        finally:
            if self.deepseek_client:
                await self.deepseek_client.close()
            await runner.cleanup()
            self.status = NodeStatus.STOPPED
            logger.info("服务已停止")

    async def shutdown(self):
        """关闭服务"""
        if self.deepseek_client:
            await self.deepseek_client.close()
        self.status = NodeStatus.STOPPED


async def main():
    """主入口"""
    node = OCRNode()
    try:
        await node.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.critical(f"致命错误: {e}", exc_info=True)
    finally:
        await node.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
