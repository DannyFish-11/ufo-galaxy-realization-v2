"""
Galaxy - 统一 API 响应格式
================================

所有聊天/对话相关端点统一使用此响应模型，
确保前端可以用一套解析逻辑处理所有响应。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UnifiedChatResponse(BaseModel):
    """
    统一聊天响应格式

    所有 /api/v1/chat、/api/v1/dashboard/chat 等端点
    都返回此格式，前端只需一套解析逻辑。
    """
    success: bool = True
    response: str = ""                          # 主要回复文本
    intent: str = ""                            # 识别的意图 (device_control, chat, task_manage, ...)
    confidence: float = 0.0                     # 意图置信度 0-1
    mode: str = "chat"                          # 处理模式: chat / agent_react / fallback
    suggestions: List[str] = Field(default_factory=list)   # 后续建议
    data: Dict[str, Any] = Field(default_factory=dict)     # 附加数据 (steps, device info, etc.)
    error: str = ""                             # 错误信息 (success=False 时)
    session_id: str = ""                        # 会话 ID
    model: str = ""                             # 使用的 LLM 模型名称
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())

    def to_json_response(self):
        """转换为 FastAPI JSONResponse 兼容的 dict"""
        return self.model_dump(exclude_none=False)
