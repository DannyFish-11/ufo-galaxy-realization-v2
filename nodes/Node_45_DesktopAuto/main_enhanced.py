"""
Node 45: DesktopAuto - 跨平台桌面自动化（增强版）

增强功能：
1. 支持 pyautogui 自动化（原有）
2. 支持智能元素定位（新增，使用多模态 LLM）
3. 支持屏幕分析（新增，理解屏幕内容）
4. 支持高级图像识别（新增，更准确的模板匹配）

版本：3.0.0
日期：2026-01-22
作者：Manus AI
"""

import os
import sys
import time
import base64
import io
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from PIL import Image

app = FastAPI(title="Node 45 - DesktopAuto (Enhanced)", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# ============================================================================
# 依赖初始化
# ============================================================================

# pyautogui
pyautogui = None
try:
    import pyautogui as _pyautogui
    _pyautogui.FAILSAFE = True
    _pyautogui.PAUSE = 0.1
    pyautogui = _pyautogui
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

# OpenCV（用于高级图像识别）
cv2 = None
try:
    import cv2 as _cv2
    cv2 = _cv2
except ImportError:
    pass

# ============================================================================
# 数据模型
# ============================================================================

class ClickRequest(BaseModel):
    x: int
    y: int
    clicks: int = 1
    button: str = "left"

class TypeRequest(BaseModel):
    text: str
    interval: float = 0.05

class KeyRequest(BaseModel):
    keys: str

class MoveRequest(BaseModel):
    x: int
    y: int
    duration: float = 0.5

class LocateRequest(BaseModel):
    image_path: str
    confidence: float = 0.9

class FindByDescriptionRequest(BaseModel):
    """通过描述查找元素"""
    description: str
    confidence: float = 0.8

class AnalyzeScreenRequest(BaseModel):
    """分析屏幕"""
    query: str = "请描述屏幕上的主要内容和 UI 元素"

class SmartClickRequest(BaseModel):
    """智能点击（通过描述）"""
    description: str
    clicks: int = 1
    button: str = "left"

# ============================================================================
# 辅助函数
# ============================================================================

def take_screenshot_pil() -> Image.Image:
    """截取屏幕（返回 PIL Image）"""
    if not pyautogui:
        raise HTTPException(status_code=503, detail="pyautogui not installed")
    return pyautogui.screenshot()

def image_to_base64(image: Image.Image) -> str:
    """图片转 Base64"""
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    return base64.b64encode(buffered.getvalue()).decode()

# ============================================================================
# 智能定位（使用 LLM）
# ============================================================================

async def find_element_by_description(description: str, confidence: float = 0.8) -> Optional[Dict[str, Any]]:
    """通过描述查找元素"""
    if not llm_client:
        return None
    
    # 截取屏幕
    screenshot = take_screenshot_pil()
    
    # 构建查询
    query = f"""请分析这个屏幕截图，找到"{description}"的位置。

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
            contents=[query, screenshot]
        )
        
        # 解析 JSON
        import json
        response_text = response.text.strip()
        
        # 清理响应（移除可能的 markdown 代码块）
        if response_text.startswith("```json"):
            response_text = response_text[7:]
        if response_text.startswith("```"):
            response_text = response_text[3:]
        if response_text.endswith("```"):
            response_text = response_text[:-3]
        response_text = response_text.strip()
        
        result = json.loads(response_text)
        
        # 检查置信度
        if result.get("found") and result.get("confidence", 0) >= confidence:
            return result
        
        return None
    
    except Exception as e:
        print(f"查找元素失败: {e}")
        return None

async def analyze_screen_with_llm(query: str) -> Optional[str]:
    """使用 LLM 分析屏幕"""
    if not llm_client:
        return None
    
    # 截取屏幕
    screenshot = take_screenshot_pil()
    
    try:
        # 使用 Gemini 分析
        response = llm_client.models.generate_content(
            model="gemini-2.0-flash-exp",
            contents=[query, screenshot]
        )
        
        return response.text
    
    except Exception as e:
        print(f"分析屏幕失败: {e}")
        return None

# ============================================================================
# 高级图像识别
# ============================================================================

def find_template_advanced(template_path: str, confidence: float = 0.9) -> Optional[Dict[str, Any]]:
    """高级模板匹配（使用 OpenCV）"""
    if not cv2 or not pyautogui:
        return None
    
    try:
        # 截取屏幕
        screenshot = pyautogui.screenshot()
        screenshot_cv = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        
        # 读取模板
        template = cv2.imread(template_path)
        if template is None:
            return None
        
        # 多尺度模板匹配
        import numpy as np
        
        best_match = None
        best_val = 0
        
        for scale in [0.5, 0.75, 1.0, 1.25, 1.5]:
            # 缩放模板
            width = int(template.shape[1] * scale)
            height = int(template.shape[0] * scale)
            resized_template = cv2.resize(template, (width, height))
            
            # 模板匹配
            result = cv2.matchTemplate(screenshot_cv, resized_template, cv2.TM_CCOEFF_NORMED)
            min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
            
            if max_val > best_val:
                best_val = max_val
                best_match = {
                    "x": max_loc[0] + width // 2,
                    "y": max_loc[1] + height // 2,
                    "width": width,
                    "height": height,
                    "confidence": max_val,
                    "scale": scale
                }
        
        # 检查阈值
        if best_match and best_match["confidence"] >= confidence:
            return best_match
        
        return None
    
    except Exception as e:
        print(f"高级模板匹配失败: {e}")
        return None

# ============================================================================
# API 端点（原有功能）
# ============================================================================

@app.get("/health")
async def health():
    return {
        "status": "healthy" if pyautogui else "degraded",
        "node_id": "45",
        "name": "DesktopAuto (Enhanced)",
        "version": "3.0.0",
        "features": {
            "pyautogui": pyautogui is not None,
            "llm": llm_client is not None,
            "opencv": cv2 is not None
        },
        "platform": sys.platform,
        "timestamp": datetime.now().isoformat()
    }

@app.post("/click")
async def click(request: ClickRequest):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        pyautogui.click(x=request.x, y=request.y, clicks=request.clicks, button=request.button)
        return {"success": True, "x": request.x, "y": request.y, "clicks": request.clicks}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/double_click")
async def double_click(x: int, y: int):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        pyautogui.doubleClick(x=x, y=y)
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/type")
async def type_text(request: TypeRequest):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        pyautogui.write(request.text, interval=request.interval)
        return {"success": True, "typed": len(request.text)}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/hotkey")
async def press_hotkey(request: KeyRequest):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        keys = request.keys.split("+")
        pyautogui.hotkey(*keys)
        return {"success": True, "keys": keys}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/press")
async def press_key(key: str):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        pyautogui.press(key)
        return {"success": True, "key": key}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/move")
async def move_mouse(request: MoveRequest):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        pyautogui.moveTo(request.x, request.y, duration=request.duration)
        return {"success": True, "x": request.x, "y": request.y}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/scroll")
async def scroll(amount: int, x: Optional[int] = None, y: Optional[int] = None):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        pyautogui.scroll(amount, x=x, y=y)
        return {"success": True, "amount": amount}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/screenshot")
async def take_screenshot():
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        screenshot = take_screenshot_pil()
        img_base64 = image_to_base64(screenshot)
        return {
            "success": True,
            "image": img_base64,
            "width": screenshot.width,
            "height": screenshot.height
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/position")
async def get_position():
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        x, y = pyautogui.position()
        return {"success": True, "x": x, "y": y}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/screen_size")
async def get_screen_size():
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        width, height = pyautogui.size()
        return {"success": True, "width": width, "height": height}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/locate")
async def locate_on_screen(request: LocateRequest):
    if not pyautogui:
        return {"success": False, "error": "pyautogui not installed"}
    
    try:
        location = pyautogui.locateOnScreen(request.image_path, confidence=request.confidence)
        if location:
            center = pyautogui.center(location)
            return {
                "success": True,
                "found": True,
                "x": center.x,
                "y": center.y,
                "region": {
                    "left": location.left,
                    "top": location.top,
                    "width": location.width,
                    "height": location.height
                }
            }
        return {"success": True, "found": False}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============================================================================
# API 端点（新增功能）
# ============================================================================

@app.post("/find_by_description")
async def find_by_description(request: FindByDescriptionRequest):
    """通过描述查找元素"""
    if not llm_client:
        return {"success": False, "error": "LLM not available"}
    
    result = await find_element_by_description(request.description, request.confidence)
    
    if result and result.get("found"):
        return {
            "success": True,
            "found": True,
            "element": result.get("element"),
            "position": result.get("position"),
            "confidence": result.get("confidence"),
            "description": result.get("description")
        }
    else:
        return {
            "success": True,
            "found": False,
            "reason": result.get("reason") if result else "LLM failed to find element"
        }

@app.post("/analyze_screen")
async def analyze_screen(request: AnalyzeScreenRequest):
    """分析屏幕"""
    if not llm_client:
        return {"success": False, "error": "LLM not available"}
    
    analysis = await analyze_screen_with_llm(request.query)
    
    if analysis:
        return {
            "success": True,
            "query": request.query,
            "analysis": analysis
        }
    else:
        return {
            "success": False,
            "error": "Failed to analyze screen"
        }

@app.post("/smart_click")
async def smart_click(request: SmartClickRequest):
    """智能点击（通过描述查找并点击）"""
    if not llm_client or not pyautogui:
        return {"success": False, "error": "LLM or pyautogui not available"}
    
    # 查找元素
    result = await find_element_by_description(request.description, 0.8)
    
    if result and result.get("found"):
        position = result["position"]
        x = position["x"]
        y = position["y"]
        
        # 点击
        try:
            pyautogui.click(x=x, y=y, clicks=request.clicks, button=request.button)
            return {
                "success": True,
                "element": result.get("element"),
                "x": x,
                "y": y,
                "clicks": request.clicks
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    else:
        return {
            "success": False,
            "error": f"Element not found: {request.description}"
        }

@app.post("/locate_advanced")
async def locate_advanced(request: LocateRequest):
    """高级模板匹配"""
    if not cv2:
        # 回退到普通模板匹配
        return await locate_on_screen(request)
    
    result = find_template_advanced(request.image_path, request.confidence)
    
    if result:
        return {
            "success": True,
            "found": True,
            "x": result["x"],
            "y": result["y"],
            "region": {
                "width": result["width"],
                "height": result["height"]
            },
            "confidence": result["confidence"],
            "scale": result["scale"]
        }
    else:
        return {"success": True, "found": False}

# ============================================================================
# MCP 调用接口
# ============================================================================

@app.post("/mcp/call")
async def mcp_call(request: dict):
    tool = request.get("tool", "")
    params = request.get("params", {})
    
    # 原有工具
    if tool == "click":
        return await click(ClickRequest(**params))
    elif tool == "double_click":
        return await double_click(params.get("x", 0), params.get("y", 0))
    elif tool == "type":
        return await type_text(TypeRequest(**params))
    elif tool == "hotkey":
        return await press_hotkey(KeyRequest(**params))
    elif tool == "press":
        return await press_key(params.get("key", ""))
    elif tool == "move":
        return await move_mouse(MoveRequest(**params))
    elif tool == "scroll":
        return await scroll(params.get("amount", 0), params.get("x"), params.get("y"))
    elif tool == "screenshot":
        return await take_screenshot()
    elif tool == "position":
        return await get_position()
    elif tool == "screen_size":
        return await get_screen_size()
    elif tool == "locate":
        return await locate_on_screen(LocateRequest(**params))
    
    # 新增工具
    elif tool == "find_by_description":
        return await find_by_description(FindByDescriptionRequest(**params))
    elif tool == "analyze_screen":
        return await analyze_screen(AnalyzeScreenRequest(**params))
    elif tool == "smart_click":
        return await smart_click(SmartClickRequest(**params))
    elif tool == "locate_advanced":
        return await locate_advanced(LocateRequest(**params))
    
    raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

# ============================================================================
# 启动服务
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8045)
