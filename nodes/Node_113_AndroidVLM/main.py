"""
Node 113: AndroidVLM - Android GUI 理解服务

FastAPI 服务器

版本：1.1.0
日期：2026-03-07
"""
import asyncio


import os
import sys
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_NODE_DIR = os.path.dirname(os.path.abspath(__file__))

# 添加当前目录到 Python 路径
sys.path.insert(0, _NODE_DIR)


def _load_vlm_engine():
    """按**文件路径**加载本节点的 core/android_vlm_engine.py。

    这里不能写 ``from core.android_vlm_engine import ...``。``python main.py``
    起进程时它是对的（sys.path[0] 就是本目录）；但 fusion_entry.py 是以模块方式
    加载本文件的，那个进程里仓库根的 ``core`` 包早已在 sys.modules 里 ——
    ``core.android_vlm_engine`` 于是只会去仓库根 core/ 里找，找不到，ImportError
    被下面的 except 接住，``HAS_VLM_ENGINE`` 静默变成 False。

    症状是最难查的那一种：服务照常起来、/health 照常绿，只是 VLM 能力**不见了**，
    没有任何一行日志说它为什么不见。实测复现过（融合进程里 HAS_VLM_ENGINE=False）。
    按文件路径加载两种入口下都成立，且不依赖 sys.path 的先后顺序。
    """
    import importlib.util

    path = os.path.join(_NODE_DIR, "core", "android_vlm_engine.py")
    spec = importlib.util.spec_from_file_location("node113_android_vlm_engine", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    _vlm_engine = _load_vlm_engine()
    AndroidVLMEngine = _vlm_engine.AndroidVLMEngine
    SUPPORTED_VLM_PROVIDERS = _vlm_engine.SUPPORTED_VLM_PROVIDERS
    HAS_VLM_ENGINE = True
except Exception as _vlm_err:  # noqa: BLE001 — 缺依赖时降级可以,但不许无声
    print(f"[Node_113] VLM 引擎加载失败,已降级为无 VLM 模式:{_vlm_err}", file=sys.stderr)
    HAS_VLM_ENGINE = False
    AndroidVLMEngine = None
    SUPPORTED_VLM_PROVIDERS = []

try:
    from nodes.common.cors_config import get_cors_origins
except ImportError:
    def get_cors_origins():
        return ["*"]

app = FastAPI(title="Node 113 - AndroidVLM", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 初始化引擎
engine = AndroidVLMEngine() if AndroidVLMEngine else None

# ============================================================================
# 数据模型
# ============================================================================

class CaptureScreenRequest(BaseModel):
    """截取屏幕"""
    use_cache: bool = True

class AnalyzeScreenRequest(BaseModel):
    """分析屏幕"""
    query: str
    image_base64: Optional[str] = None
    provider: str = "auto"

class FindElementRequest(BaseModel):
    """查找元素"""
    description: str
    image_base64: Optional[str] = None
    confidence: float = 0.8

class SmartClickRequest(BaseModel):
    """智能点击"""
    description: str
    confidence: float = 0.8

class GenerateActionPlanRequest(BaseModel):
    """生成操作计划"""
    task_description: str
    max_steps: int = 10

class ExecuteActionPlanRequest(BaseModel):
    """执行操作计划"""
    steps: List[Dict[str, Any]]
    verify_each_step: bool = True

class SmartTaskExecutionRequest(BaseModel):
    """智能任务执行"""
    task_description: str
    max_steps: int = 10


class LongPressRequest(BaseModel):
    """长按操作"""
    description: str
    duration_ms: int = 1000
    confidence: float = 0.8


class DoubleClickRequest(BaseModel):
    """双击操作"""
    description: str
    interval_ms: int = 100
    confidence: float = 0.8

# ============================================================================
# API 端点
# ============================================================================

@app.get("/")
async def root():
    """根端点"""
    return {
        "node": "Node_113_AndroidVLM",
        "version": "1.1.0",
        "status": "running",
        "description": "Android GUI 理解引擎（VLM + 无障碍服务）",
        "supported_vlm_providers": SUPPORTED_VLM_PROVIDERS
    }

@app.get("/health")
async def health():
    """健康检查"""
    return {
        "status": "healthy",
        "node": "Node_113_AndroidVLM"
    }

@app.post("/capture_screen")
async def capture_screen(request: CaptureScreenRequest) -> Dict[str, Any]:
    """截取 Android 屏幕"""
    try:
        result = await engine.capture_android_screen(use_cache=request.use_cache)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze_screen")
async def analyze_screen(request: AnalyzeScreenRequest) -> Dict[str, Any]:
    """使用 VLM 分析屏幕"""
    try:
        result = await engine.analyze_screen(
            query=request.query,
            image_base64=request.image_base64,
            provider=request.provider
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/find_element")
async def find_element(request: FindElementRequest) -> Dict[str, Any]:
    """使用 VLM 查找元素"""
    try:
        result = await engine.find_element_with_vlm(
            description=request.description,
            image_base64=request.image_base64,
            confidence=request.confidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/smart_click")
async def smart_click(request: SmartClickRequest) -> Dict[str, Any]:
    """智能点击（截图 -> VLM 查找 -> 点击）"""
    try:
        result = await engine.smart_click(
            description=request.description,
            confidence=request.confidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/generate_action_plan")
async def generate_action_plan(request: GenerateActionPlanRequest) -> Dict[str, Any]:
    """生成操作计划"""
    try:
        result = await engine.generate_action_plan(
            task_description=request.task_description,
            max_steps=request.max_steps
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/execute_action_plan")
async def execute_action_plan(request: ExecuteActionPlanRequest) -> Dict[str, Any]:
    """执行操作计划"""
    try:
        result = await engine.execute_action_plan(
            steps=request.steps,
            verify_each_step=request.verify_each_step
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/smart_task_execution")
async def smart_task_execution(request: SmartTaskExecutionRequest) -> Dict[str, Any]:
    """智能任务执行（生成计划 -> 执行计划）"""
    try:
        result = await engine.smart_task_execution(
            task_description=request.task_description,
            max_steps=request.max_steps
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/long_press")
async def long_press(request: LongPressRequest) -> Dict[str, Any]:
    """长按操作（截图 -> VLM 查找 -> 长按）"""
    try:
        result = await engine.long_press(
            description=request.description,
            duration_ms=request.duration_ms,
            confidence=request.confidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/double_click")
async def double_click(request: DoubleClickRequest) -> Dict[str, Any]:
    """双击操作（截图 -> VLM 查找 -> 双击）"""
    try:
        result = await engine.double_click(
            description=request.description,
            interval_ms=request.interval_ms,
            confidence=request.confidence
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/supported_providers")
async def get_supported_providers():
    """获取支持的 VLM 提供商列表"""
    # engine 在 AndroidVLMEngine 导入失败时为 None(见模块级 `engine = ... if ... else None`),
    # 直接解引用会 500。降级模式下如实返回,不崩溃。
    if engine is None:
        return {
            "providers": SUPPORTED_VLM_PROVIDERS,
            "current": None,
            "claude_configured": False,
            "gpt4v_configured": False,
            "degraded": True,
        }
    return {
        "providers": SUPPORTED_VLM_PROVIDERS,
        "current": engine.vlm_provider,
        "claude_configured": bool(engine.claude_api_key),
        "gpt4v_configured": bool(engine.openai_api_key)
    }

# ============================================================================
# 启动服务
# ============================================================================



class MCPCallRequest(BaseModel):
    tool: str
    params: dict = {}

@app.post("/mcp/call")
async def mcp_call(request: MCPCallRequest):
    """MCP tool call dispatcher"""
    if request.tool == "health":
        return {"success": True, "tool": request.tool, "result": {"status": "healthy", "node": "Node_113_AndroidVLM"}}
    raise HTTPException(status_code=404, detail=f"Unknown tool: {request.tool}")


@app.get("/status")
async def get_status():
    """节点状态"""
    return {
        "node": "Node_113_AndroidVLM",
        "status": "running",
        "version": "1.0.0",
        "port": 8113,
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("NODE_113_PORT", "8113"))
    uvicorn.run(app, host="0.0.0.0", port=port)
