"""
Galaxy - 统一 API 响应格式
================================

所有聊天/对话相关端点统一使用此响应模型，
确保前端可以用一套解析逻辑处理所有响应。

架构说明 (PR-2):
  /api/v1/chat 是兼容性适配器表面 (compatibility adapter surface)，
  不是系统主权中心。真实执行权威在 DesktopPresenceRuntime → OpenClawd。
  UnifiedChatResponse 中的可选元数据字段 (runtime_session_id, entry_surface,
  entry_source, execution_authority, surface_role) 向调用方披露这一真实的
  执行路径，同时对现有客户端保持完全向后兼容。

PR-11 新增:
  - execution_plan_summary: 执行计划摘要 (可选, 默认 None, 不影响旧客户端)
    由 OpenClawd 在执行决策后生成，包含 plan_id、execution_path、step_count
    等字段，用于可观测性、诊断和后续生命周期追踪。
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ParallelGroupSummary(BaseModel):
    """并行任务组汇总（parallel_goal 执行后附加到响应中）。"""
    group_id: str = ""
    device_results: List[Dict[str, Any]] = Field(default_factory=list)
    summary_status: str = ""     # "success" | "partial" | "failed"


class UnifiedChatResponse(BaseModel):
    """
    统一聊天响应格式

    所有 /api/v1/chat、/api/v1/dashboard/chat 等端点
    都返回此格式，前端只需一套解析逻辑。

    向后兼容保证:
      已有字段 (success, response, intent, confidence, mode, suggestions,
      data, error, session_id, model, timestamp) 永远存在于序列化输出中，
      现有客户端无需任何修改。

    PR-2 新增可选元数据字段 (均为 Optional, 默认 None, 不影响旧客户端):
      - runtime_session_id   : DesktopPresenceRuntime 分配的运行时会话 ID
      - entry_surface        : 请求进入系统的适配器表面名称 (e.g. "chat_adapter")
      - entry_source         : 原始请求来源协议 (e.g. "http_post")
      - execution_authority  : 持有执行主权的运行时 (e.g. "DesktopPresenceRuntime/OpenClawd")
      - surface_role         : 本表面在架构中的角色 (e.g. "compat_adapter")

    PR-11 新增可选字段 (均为 Optional, 默认 None, 不影响旧客户端):
      - execution_plan_summary: 执行计划摘要 dict，由 OpenClawd 在
                                执行决策后生成。用于可观测性、诊断和后续
                                生命周期追踪。旧客户端可安全忽略。
    """
    # ── 核心字段（向后兼容，永远序列化） ──────────────────────────────────
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
    parallel_group: Optional[ParallelGroupSummary] = None  # 并行任务组汇总（仅 parallel_goal）

    # ── PR-2 执行路径元数据（可选，非破坏性，旧客户端可安全忽略） ───────────
    # 这些字段让调用方能识别真实的执行链路和主权归属，以防止将 /api/v1/chat
    # 误认为系统主权核心。所有字段默认为 None，不改变旧客户端的解析逻辑。
    runtime_session_id: Optional[str] = None   # DesktopPresenceRuntime 会话 ID
    entry_surface: Optional[str] = None        # 适配器表面名称 ("chat_adapter")
    entry_source: Optional[str] = None         # 请求来源协议 ("http_post")
    execution_authority: Optional[str] = None  # 执行主权持有者 ("DesktopPresenceRuntime/OpenClawd")
    surface_role: Optional[str] = None         # 本表面架构角色 ("compat_adapter")

    # ── PR-11 执行计划摘要（可选，非破坏性，旧客户端可安全忽略） ────────────
    # 由 OpenClawd 在执行决策后生成，字段结构与 plan_summary() 返回值一致。
    # 包含: plan_id, execution_path, delegation_point, step_count,
    #       primary_step_type, is_local_only, is_remote, is_orchestration,
    #       is_observe, trace_id, session_id.
    execution_plan_summary: Optional[Dict[str, Any]] = None

    def to_json_response(self):
        """转换为 FastAPI JSONResponse 兼容的 dict"""
        return self.model_dump(exclude_none=False)
