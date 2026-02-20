"""
Node 15: OCR - 光学字符识别（增强版）

增强功能：
1. 支持 Tesseract OCR（原有）
2. 支持 PaddleOCR（新增，更准确的中文识别）
3. 支持多模态 LLM 分析（新增，理解文本上下文）
4. 支持批量识别
5. 支持区域识别

版本：3.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import tempfile
import base64
import io
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image

app = FastAPI(title="Node 15 - OCR (Enhanced)", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# OCR 引擎初始化
# ============================================================================

# Tesseract OCR
pytesseract = None
try:
    import pytesseract as _pytesseract
    pytesseract = _pytesseract
except ImportError:
    pass

# PaddleOCR
paddleocr = None
try:
    from paddleocr import PaddleOCR
    paddleocr = PaddleOCR(use_angle_cls=True, lang='ch')
except ImportError:
    pass

# 多模态 LLM
llm_client = None
try:
    from google import genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY:
        llm_client = genai.Client(api_key=GEMINI_API_KEY)
except ImportError:
    pass

# ============================================================================
# 数据模型
# ============================================================================

class OCRRequest(BaseModel):
    """OCR 请求"""
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    language: str = "eng+chi_sim"
    engine: str = "auto"  # auto, tesseract, paddleocr
    region: Optional[Dict[str, int]] = None  # {x, y, width, height}

class OCRBatchRequest(BaseModel):
    """批量 OCR 请求"""
    images: List[str]  # 图片路径或 Base64
    language: str = "eng+chi_sim"
    engine: str = "auto"

class OCRAnalysisRequest(BaseModel):
    """OCR 分析请求（使用 LLM）"""
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    query: str = "请提取并分析图片中的文本内容"
    language: str = "ch"

class OCRWord(BaseModel):
    """OCR 识别的单词"""
    text: str
    confidence: float
    x: int
    y: int
    width: int
    height: int

class OCRResult(BaseModel):
    """OCR 结果"""
    success: bool
    engine: str
    text: str
    words: List[Dict[str, Any]]
    word_count: int
    confidence: float
    error: Optional[str] = None

# ============================================================================
# 辅助函数
# ============================================================================

def load_image(image_path: Optional[str] = None, image_base64: Optional[str] = None) -> Image.Image:
    """加载图片"""
    if image_path:
        if not os.path.exists(image_path):
            raise HTTPException(status_code=404, detail="Image not found")
        return Image.open(image_path)
    elif image_base64:
        image_data = base64.b64decode(image_base64)
        return Image.open(io.BytesIO(image_data))
    else:
        raise HTTPException(status_code=400, detail="Provide image_path or image_base64")

def crop_image(image: Image.Image, region: Dict[str, int]) -> Image.Image:
    """裁剪图片"""
    x = region.get("x", 0)
    y = region.get("y", 0)
    width = region.get("width", image.width)
    height = region.get("height", image.height)
    return image.crop((x, y, x + width, y + height))

# ============================================================================
# Tesseract OCR
# ============================================================================

def recognize_with_tesseract(image: Image.Image, language: str = "eng+chi_sim") -> OCRResult:
    """使用 Tesseract 识别"""
    if not pytesseract:
        return OCRResult(
            success=False,
            engine="tesseract",
            text="",
            words=[],
            word_count=0,
            confidence=0.0,
            error="pytesseract not installed"
        )
    
    try:
        # 识别文本
        text = pytesseract.image_to_string(image, lang=language)
        
        # 获取详细数据
        data = pytesseract.image_to_data(image, lang=language, output_type=pytesseract.Output.DICT)
        
        # 解析单词
        words = []
        total_confidence = 0
        valid_words = 0
        
        for i, word in enumerate(data["text"]):
            if word.strip():
                conf = float(data["conf"][i])
                words.append({
                    "text": word,
                    "confidence": conf,
                    "x": data["left"][i],
                    "y": data["top"][i],
                    "width": data["width"][i],
                    "height": data["height"][i]
                })
                if conf > 0:
                    total_confidence += conf
                    valid_words += 1
        
        avg_confidence = total_confidence / valid_words if valid_words > 0 else 0.0
        
        return OCRResult(
            success=True,
            engine="tesseract",
            text=text.strip(),
            words=words,
            word_count=len(words),
            confidence=avg_confidence
        )
    
    except Exception as e:
        return OCRResult(
            success=False,
            engine="tesseract",
            text="",
            words=[],
            word_count=0,
            confidence=0.0,
            error=str(e)
        )

# ============================================================================
# PaddleOCR
# ============================================================================

def recognize_with_paddleocr(image: Image.Image, language: str = "ch") -> OCRResult:
    """使用 PaddleOCR 识别"""
    if not paddleocr:
        return OCRResult(
            success=False,
            engine="paddleocr",
            text="",
            words=[],
            word_count=0,
            confidence=0.0,
            error="paddleocr not installed"
        )
    
    try:
        # 转换为 numpy 数组
        import numpy as np
        img_array = np.array(image)
        
        # 识别
        result = paddleocr.ocr(img_array, cls=True)
        
        # 解析结果
        words = []
        full_text = []
        total_confidence = 0
        
        if result and result[0]:
            for line in result[0]:
                # 边界框
                box = line[0]
                x_min = int(min([p[0] for p in box]))
                y_min = int(min([p[1] for p in box]))
                x_max = int(max([p[0] for p in box]))
                y_max = int(max([p[1] for p in box]))
                
                # 文本和置信度
                text = line[1][0]
                confidence = float(line[1][1])
                
                words.append({
                    "text": text,
                    "confidence": confidence,
                    "x": x_min,
                    "y": y_min,
                    "width": x_max - x_min,
                    "height": y_max - y_min
                })
                
                full_text.append(text)
                total_confidence += confidence
        
        avg_confidence = total_confidence / len(words) if words else 0.0
        
        return OCRResult(
            success=True,
            engine="paddleocr",
            text="\n".join(full_text),
            words=words,
            word_count=len(words),
            confidence=avg_confidence
        )
    
    except Exception as e:
        return OCRResult(
            success=False,
            engine="paddleocr",
            text="",
            words=[],
            word_count=0,
            confidence=0.0,
            error=str(e)
        )

# ============================================================================
# 自动选择引擎
# ============================================================================

def recognize_auto(image: Image.Image, language: str = "eng+chi_sim") -> OCRResult:
    """自动选择最佳引擎"""
    # 优先使用 PaddleOCR（中文更准确）
    if paddleocr and ("chi" in language or "ch" in language):
        result = recognize_with_paddleocr(image, "ch")
        if result.success and result.confidence > 0.5:
            return result
    
    # 使用 Tesseract
    if pytesseract:
        result = recognize_with_tesseract(image, language)
        if result.success:
            return result
    
    # 都不可用
    return OCRResult(
        success=False,
        engine="none",
        text="",
        words=[],
        word_count=0,
        confidence=0.0,
        error="No OCR engine available"
    )

# ============================================================================
# API 端点
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy" if (pytesseract or paddleocr) else "degraded",
        "node_id": "15",
        "name": "OCR (Enhanced)",
        "version": "3.0.0",
        "engines": {
            "tesseract": pytesseract is not None,
            "paddleocr": paddleocr is not None,
            "llm": llm_client is not None
        },
        "timestamp": datetime.now().isoformat()
    }

@app.post("/recognize")
async def recognize_text(request: OCRRequest) -> OCRResult:
    """识别文本"""
    # 加载图片
    image = load_image(request.image_path, request.image_base64)
    
    # 裁剪区域（如果指定）
    if request.region:
        image = crop_image(image, request.region)
    
    # 选择引擎
    if request.engine == "tesseract":
        return recognize_with_tesseract(image, request.language)
    elif request.engine == "paddleocr":
        lang = "ch" if "chi" in request.language else "en"
        return recognize_with_paddleocr(image, lang)
    else:  # auto
        return recognize_auto(image, request.language)

@app.post("/recognize_batch")
async def recognize_batch(request: OCRBatchRequest) -> Dict[str, Any]:
    """批量识别"""
    results = []
    
    for img_data in request.images:
        # 判断是路径还是 Base64
        if os.path.exists(img_data):
            image = load_image(image_path=img_data)
        else:
            image = load_image(image_base64=img_data)
        
        # 识别
        if request.engine == "tesseract":
            result = recognize_with_tesseract(image, request.language)
        elif request.engine == "paddleocr":
            lang = "ch" if "chi" in request.language else "en"
            result = recognize_with_paddleocr(image, lang)
        else:
            result = recognize_auto(image, request.language)
        
        results.append(result.dict())
    
    return {
        "success": True,
        "count": len(results),
        "results": results
    }

@app.post("/analyze")
async def analyze_with_llm(request: OCRAnalysisRequest) -> Dict[str, Any]:
    """使用 LLM 分析文本"""
    if not llm_client:
        raise HTTPException(status_code=503, detail="LLM not available")
    
    # 加载图片
    image = load_image(request.image_path, request.image_base64)
    
    try:
        # 使用 Gemini 分析
        response = llm_client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[request.query, image]
        )
        
        return {
            "success": True,
            "query": request.query,
            "analysis": response.text
        }
    
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/upload")
async def upload_and_recognize(
    file: UploadFile = File(...),
    language: str = "eng+chi_sim",
    engine: str = "auto"
) -> OCRResult:
    """上传并识别"""
    # 保存临时文件
    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        # 加载图片
        image = Image.open(tmp_path)
        
        # 识别
        if engine == "tesseract":
            result = recognize_with_tesseract(image, language)
        elif engine == "paddleocr":
            lang = "ch" if "chi" in language else "en"
            result = recognize_with_paddleocr(image, lang)
        else:
            result = recognize_auto(image, language)
        
        return result
    
    finally:
        os.unlink(tmp_path)

@app.get("/languages")
async def list_languages() -> Dict[str, Any]:
    """列出支持的语言"""
    languages = {
        "tesseract": [],
        "paddleocr": ["ch", "en", "fr", "german", "korean", "japan"]
    }
    
    if pytesseract:
        try:
            languages["tesseract"] = pytesseract.get_languages()
        except Exception:
            pass
    
    return {
        "success": True,
        "languages": languages
    }

@app.get("/engines")
async def list_engines() -> Dict[str, Any]:
    """列出可用的引擎"""
    return {
        "success": True,
        "engines": {
            "tesseract": {
                "available": pytesseract is not None,
                "description": "Tesseract OCR - 通用 OCR 引擎"
            },
            "paddleocr": {
                "available": paddleocr is not None,
                "description": "PaddleOCR - 更准确的中文 OCR"
            },
            "llm": {
                "available": llm_client is not None,
                "description": "多模态 LLM - 文本分析和理解"
            }
        }
    }

@app.post("/mcp/call")
async def mcp_call(request: dict) -> Dict[str, Any]:
    """MCP 调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "recognize":
        result = await recognize_text(OCRRequest(**params))
        return result.dict()
    elif tool == "recognize_batch":
        return await recognize_batch(OCRBatchRequest(**params))
    elif tool == "analyze":
        return await analyze_with_llm(OCRAnalysisRequest(**params))
    elif tool == "languages":
        return await list_languages()
    elif tool == "engines":
        return await list_engines()
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8015)
