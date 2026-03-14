"""
Galaxy - Shared Request/Response Models
============================================

Pydantic models and enums shared across all route modules.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ============================================================================
# Request/Response Models
# ============================================================================

class DeviceRegisterRequest(BaseModel):
    device_id: str
    device_type: str = "android"
    device_name: str = ""
    capabilities: List[str] = []
    os_version: str = ""
    app_version: str = ""


class DeviceStatusUpdate(BaseModel):
    device_id: str
    status: Dict[str, Any] = {}


class VisionRequest(BaseModel):
    image_base64: Optional[str] = None
    video_chunk: Optional[str] = None  # Base64 encoded video chunk
    mode: str = "full"
    instruction: str = ""
    session_id: Optional[str] = None   # For video stream context
    is_last_chunk: bool = False


class TaskRequest(BaseModel):
    task_type: str
    payload: Dict[str, Any] = {}
    device_id: str = ""
    priority: int = 5


class ChatRequest(BaseModel):
    message: str
    device_id: str = ""
    context: List[Dict[str, str]] = []
    user_id: str = ""          # 用户标识（跨设备统一会话）
    session_id: str = ""       # 会话 ID（跨设备共享）
    required_capabilities: Optional[List[str]] = None  # Phase 2: scheduler hint


class NodeCallRequest(BaseModel):
    node_id: str
    action: str
    params: Dict[str, Any] = {}


class OCRRequest(BaseModel):
    image_base64: str
    mode: str = "free_ocr"
    language: str = "auto"


class CommandDispatchRequest(BaseModel):
    """命令分发请求"""
    source: str = "api"
    targets: List[str] = []
    command: str
    params: Dict[str, Any] = {}
    mode: str = "sync"   # sync | async | parallel | serial
    timeout: float = 30.0
    max_retries: int = 2
    notify_ws: bool = True
    priority: int = 5
    metadata: Dict[str, Any] = {}


class AIIntentRequest(BaseModel):
    """AI 意图解析请求"""
    text: str
    session_id: str = ""
    context: Dict[str, Any] = {}


class ConversationRequest(BaseModel):
    """对话记忆请求"""
    session_id: str
    role: str = "user"
    content: str
    metadata: Dict[str, Any] = {}


# ============================================================================
# Unified Command Protocol Models
# ============================================================================

class CommandStatus(str, Enum):
    """命令状态枚举"""
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class TargetResult(BaseModel):
    """单个目标的执行结果"""
    status: CommandStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class UnifiedCommandRequest(BaseModel):
    """统一命令请求"""
    request_id: Optional[str] = None
    command: str
    targets: List[str]
    params: Dict[str, Any] = {}
    mode: str = "sync"  # sync or async
    timeout: int = 30


class UnifiedCommandResponse(BaseModel):
    """统一命令响应"""
    request_id: str
    status: CommandStatus
    created_at: str
    completed_at: Optional[str] = None
    results: Dict[str, TargetResult]
