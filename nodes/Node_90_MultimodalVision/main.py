"""
Node 90: MultimodalVision - 多模态视觉理解

功能：
1. 统一的视觉理解接口
2. 集成 OCR（Tesseract + PaddleOCR）
3. 集成屏幕截图
4. 集成模板匹配
5. 集成多模态 LLM 分析
6. 提供高级视觉理解能力

版本：1.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import sys
import base64
import io
import asyncio
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image

app = FastAPI(title="Node 90 - MultimodalVision", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 配置
# ============================================================================

# 节点地址
NODE_15_OCR_URL = os.getenv("NODE_15_OCR_URL", "http://localhost:8015")
NODE_45_DESKTOP_URL = os.getenv("NODE_45_DESKTOP_URL", "http://localhost:8045")
NODE_95_WEBRTC_URL = os.getenv("NODE_95_WEBRTC_URL", "http://localhost:8095")

# 多模态 LLM
llm_client = None
try:
    from google import genai
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    if GEMINI_API_KEY:
        llm_client = genai.Client(api_key=GEMINI_API_KEY)
except ImportError:
    pass

# Qwen3-VL via OpenRouter
try:
    from openai import OpenAI
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
    if OPENROUTER_API_KEY:
        qwen_client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=OPENROUTER_API_KEY
        )
        QWEN_VL_AVAILABLE = True
    else:
        qwen_client = None
        QWEN_VL_AVAILABLE = False
except ImportError:
    qwen_client = None
    QWEN_VL_AVAILABLE = False

# ============================================================================
# 数据模型
# ============================================================================

class CaptureScreenRequest(BaseModel):
    """截取屏幕"""
    device_id: Optional[str] = None  # 设备 ID（用于远程设备）
    platform: str = "windows"  # windows, android

class OCRRequest(BaseModel):
    """OCR 识别"""
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    language: str = "eng+chi_sim"
    engine: str = "auto"

class FindElementRequest(BaseModel):
    """查找元素"""
    description: str
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    method: str = "auto"  # auto, ocr, template, llm
    confidence: float = 0.8

class AnalyzeScreenRequest(BaseModel):
    """分析屏幕"""
    query: str
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    provider: str = "auto"  # auto, gemini, qwen
    platform: str = "windows"  # windows, android
    device_id: Optional[str] = None  # 设备 ID（Android 必须）

class FindTextRequest(BaseModel):
    """查找文本"""
    text: str
    image_path: Optional[str] = None
    image_base64: Optional[str] = None

class FindTemplateRequest(BaseModel):
    """查找模板"""
    template_path: str
    image_path: Optional[str] = None
    image_base64: Optional[str] = None
    confidence: float = 0.9

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

def image_to_base64(image: Image.Image) -> str:
    """图片转 Base64"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

async def call_node(url: str, endpoint: str, data: dict) -> dict:
    """调用其他节点"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(f"{url}{endpoint}", json=data)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# 屏幕截图
# ============================================================================

@app.post("/capture_screen")
async def capture_screen(request: CaptureScreenRequest) -> Dict[str, Any]:
    """截取屏幕"""
    if request.platform == "windows":
        # 调用 Node_45_DesktopAuto
        result = await call_node(NODE_45_DESKTOP_URL, "/screenshot", {})
        return result
    elif request.platform == "android":
        # 调用 Node_95 获取 Android 画面
        if not request.device_id:
            return {"success": False, "error": "device_id is required for Android"}
        
        try:
            result = await call_node(
                NODE_95_WEBRTC_URL,
                "/get_latest_frame",
                {
                    "device_id": request.device_id,
                    "format": "jpeg"
                }
            )
            
            if result.get("success"):
                # 返回画面
                return {
                    "success": True,
                    "image_base64": result.get("frame_data"),
                    "timestamp": result.get("timestamp"),
                    "frame_size": result.get("frame_size"),
                    "source": "webrtc"
                }
            else:
                return {"success": False, "error": result.get("error", "Unknown error")}
        
        except Exception as e:
            return {"success": False, "error": f"Failed to get Android frame: {str(e)}"}
    else:
        return {"success": False, "error": f"Unsupported platform: {request.platform}"}

# ============================================================================
# OCR 识别
# ============================================================================

@app.post("/ocr")
async def ocr_recognize(request: OCRRequest) -> Dict[str, Any]:
    """OCR 识别"""
    # 调用 Node_15_OCR
    result = await call_node(NODE_15_OCR_URL, "/recognize", {
        "image_path": request.image_path,
        "image_base64": request.image_base64,
        "language": request.language,
        "engine": request.engine
    })
    return result

# ============================================================================
# 查找元素
# ============================================================================

@app.post("/find_element")
async def find_element(request: FindElementRequest) -> Dict[str, Any]:
    """查找元素（多种方法）"""
    
    # 加载图片
    if not request.image_path and not request.image_base64:
        # 截取屏幕
        platform = request.platform if hasattr(request, 'platform') else "windows"
        device_id = request.device_id if hasattr(request, 'device_id') else None
        
        screenshot_result = await capture_screen(
            CaptureScreenRequest(
                platform=platform,
                device_id=device_id
            )
        )
        
        if not screenshot_result.get("success"):
            return screenshot_result
        
        # 根据返回的字段名获取图片
        request.image_base64 = screenshot_result.get("image_base64") or screenshot_result.get("image")
    
    # 选择方法
    if request.method == "ocr" or (request.method == "auto" and len(request.description) < 20):
        # 使用 OCR 查找文本
        ocr_result = await ocr_recognize(OCRRequest(
            image_path=request.image_path,
            image_base64=request.image_base64,
            language="eng+chi_sim",
            engine="auto"
        ))
        
        if ocr_result.get("success"):
            # 查找匹配的文本
            for word in ocr_result.get("words", []):
                if request.description.lower() in word["text"].lower():
                    return {
                        "success": True,
                        "found": True,
                        "method": "ocr",
                        "element": word["text"],
                        "position": {
                            "x": word["x"] + word["width"] // 2,
                            "y": word["y"] + word["height"] // 2,
                            "width": word["width"],
                            "height": word["height"]
                        },
                        "confidence": word["confidence"]
                    }
            
            return {
                "success": True,
                "found": False,
                "method": "ocr",
                "reason": "Text not found in OCR results"
            }
    
    if request.method == "llm" or request.method == "auto":
        # 使用 LLM 查找元素
        if not llm_client:
            return {"success": False, "error": "LLM not available"}
        
        # 加载图片
        image = load_image(request.image_path, request.image_base64)
        
        # 构建查询
        query = f"""请分析这个屏幕截图，找到"{request.description}"的位置。

请以 JSON 格式返回（不要使用 markdown 代码块）：
{{
  "found": true/false,
  "element": "元素名称",
  "position": {{
    "x": 相对于屏幕左上角的 x 坐标（中心点）,
    "y": 相对于屏幕左上角的 y 坐标（中心点）,
    "width": 元素宽度,
    "height": 元素高度
  }},
  "confidence": 0.0-1.0,
  "description": "元素的详细描述"
}}

如果找不到，请返回：
{{
  "found": false,
  "reason": "未找到的原因"
}}
"""
        
        try:
            # 使用 Gemini 分析
            response = llm_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[query, image]
            )
            
            # 解析 JSON
            import json
            response_text = response.text.strip()
            
            # 清理响应
            if response_text.startswith("```json"):
                response_text = response_text[7:]
            if response_text.startswith("```"):
                response_text = response_text[3:]
            if response_text.endswith("```"):
                response_text = response_text[:-3]
            response_text = response_text.strip()
            
            result = json.loads(response_text)
            
            if result.get("found") and result.get("confidence", 0) >= request.confidence:
                return {
                    "success": True,
                    "found": True,
                    "method": "llm",
                    **result
                }
            else:
                return {
                    "success": True,
                    "found": False,
                    "method": "llm",
                    "reason": result.get("reason", "Confidence too low")
                }
        
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "No suitable method found"}

# ============================================================================
# 分析屏幕
# ============================================================================

@app.post("/analyze_screen")
async def analyze_screen(request: AnalyzeScreenRequest) -> Dict[str, Any]:
    """分析屏幕（支持 Gemini 和 Qwen3-VL）"""
    # 选择 provider
    provider = request.provider
    if provider == "auto":
        # 优先使用 Qwen3-VL，其次 Gemini
        if QWEN_VL_AVAILABLE:
            provider = "qwen"
        elif llm_client:
            provider = "gemini"
        else:
            return {"success": False, "error": "No VLM provider available"}
    
    # 加载图片
    if not request.image_path and not request.image_base64:
        # 截取屏幕
        platform = request.platform if hasattr(request, 'platform') else "windows"
        device_id = request.device_id if hasattr(request, 'device_id') else None
        
        screenshot_result = await capture_screen(
            CaptureScreenRequest(
                platform=platform,
                device_id=device_id
            )
        )
        
        if not screenshot_result.get("success"):
            return screenshot_result
        
        # 根据返回的字段名获取图片
        request.image_base64 = screenshot_result.get("image_base64") or screenshot_result.get("image")
    
    try:
        if provider == "qwen":
            # 使用 Qwen3-VL via OpenRouter
            if not QWEN_VL_AVAILABLE:
                return {"success": False, "error": "Qwen3-VL not available"}
            
            # 上传图片并获取 URL
            if request.image_path:
                # 使用manus-upload-file 上传
                import subprocess
                result = subprocess.run(
                    ["manus-upload-file", request.image_path],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                image_url = result.stdout.strip()
            else:
                # 将 base64 保存为临时文件再上传
                import tempfile
                image_data = base64.b64decode(request.image_base64)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                    tmp.write(image_data)
                    tmp_path = tmp.name
                
                result = subprocess.run(
                    ["manus-upload-file", tmp_path],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                image_url = result.stdout.strip()
                os.unlink(tmp_path)
            
            # 调用 Qwen3-VL
            response = qwen_client.chat.completions.create(
                model="qwen/qwen3-vl-32b-instruct",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": request.query},
                        {"type": "image_url", "image_url": {"url": image_url}}
                    ]
                }],
                temperature=0.2,
                max_tokens=2048
            )
            
            return {
                "success": True,
                "query": request.query,
                "analysis": response.choices[0].message.content,
                "provider": "qwen"
            }
        
        elif provider == "gemini":
            # 使用 Gemini
            if not llm_client:
                return {"success": False, "error": "Gemini not available"}
            
            image = load_image(request.image_path, request.image_base64)
            response = llm_client.models.generate_content(
                model="gemini-2.0-flash-exp",
                contents=[request.query, image]
            )
            
            return {
                "success": True,
                "query": request.query,
                "analysis": response.text,
                "provider": "gemini"
            }
        
        else:
            return {"success": False, "error": f"Unknown provider: {provider}"}
    
    except Exception as e:
        return {"success": False, "error": str(e), "provider": provider}

# ============================================================================
# 查找文本
# ============================================================================

@app.post("/find_text")
async def find_text(request: FindTextRequest) -> Dict[str, Any]:
    """查找文本（使用 OCR）"""
    # 调用 OCR
    ocr_result = await ocr_recognize(OCRRequest(
        image_path=request.image_path,
        image_base64=request.image_base64,
        language="eng+chi_sim",
        engine="auto"
    ))
    
    if not ocr_result.get("success"):
        return ocr_result
    
    # 查找匹配的文本
    for word in ocr_result.get("words", []):
        if request.text.lower() in word["text"].lower():
            return {
                "success": True,
                "found": True,
                "text": word["text"],
                "position": {
                    "x": word["x"] + word["width"] // 2,
                    "y": word["y"] + word["height"] // 2,
                    "width": word["width"],
                    "height": word["height"]
                },
                "confidence": word["confidence"]
            }
    
    return {
        "success": True,
        "found": False,
        "reason": "Text not found"
    }

# ============================================================================
# 查找模板
# ============================================================================

@app.post("/find_template")
async def find_template(request: FindTemplateRequest) -> Dict[str, Any]:
    """查找模板（使用模板匹配）"""
    # 调用 Node_45_DesktopAuto
    result = await call_node(NODE_45_DESKTOP_URL, "/locate_advanced", {
        "image_path": request.template_path,
        "confidence": request.confidence
    })
    return result

# ============================================================================
# 健康检查
# ============================================================================

@app.get("/health")
async def health():
    """健康检查"""
    # 检查依赖节点
    node_15_status = "unknown"
    node_45_status = "unknown"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_15_OCR_URL}/health")
            if response.status_code == 200:
                node_15_status = "healthy"
    except Exception:
        node_15_status = "unhealthy"
    
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{NODE_45_DESKTOP_URL}/health")
            if response.status_code == 200:
                node_45_status = "healthy"
    except Exception:
        node_45_status = "unhealthy"
    
    return {
        "status": "healthy" if (node_15_status == "healthy" and node_45_status == "healthy") else "degraded",
        "node_id": "90",
        "name": "MultimodalVision",
        "version": "1.0.0",
        "dependencies": {
            "node_15_ocr": node_15_status,
            "node_45_desktop": node_45_status,
            "llm": llm_client is not None
        },
        "timestamp": datetime.now().isoformat()
    }

# ============================================================================
# MCP 调用接口
# ============================================================================

@app.post("/mcp/call")
async def mcp_call(request: dict) -> Dict[str, Any]:
    """MCP 调用接口"""
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    if tool == "capture_screen":
        return await capture_screen(CaptureScreenRequest(**params))
    elif tool == "ocr":
        return await ocr_recognize(OCRRequest(**params))
    elif tool == "find_element":
        return await find_element(FindElementRequest(**params))
    elif tool == "analyze_screen":
        return await analyze_screen(AnalyzeScreenRequest(**params))
    elif tool == "find_text":
        return await find_text(FindTextRequest(**params))
    elif tool == "find_template":
        return await find_template(FindTemplateRequest(**params))
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8090)
