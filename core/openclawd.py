"""
Galaxy-Nexus 星枢核心智能体 — OpenClawd
=========================================

统一智能交互入口，串联已有模块实现完整的意图解析 -> 模型选择 -> 执行 -> 响应流水线:

模块串联:
  - ai_intent.py        -> 意图解析 (IntentParser / ConversationMemory)
  - multi_llm_router.py -> 模型选择 (MultiLLMRouter / TaskType)
  - agent_factory.py    -> Agent 创建/复用 (AgentFactory / TaskAgent)
  - agent_team.py       -> 团队协作 (TeamManager / TeamStrategy)
  - device_orchestrator  -> 设备操控
  - mcp_loader.py       -> MCP 协议工具调用
  - skill_loader.py     -> Skill 技能调用

设计原则:
  1. 单例模式 — 全局唯一入口
  2. 懒加载 — 所有模块按需导入，避免循环依赖
  3. 容错降级 — 任何模块不可用时自动降级
  4. 统一响应 — 所有方法返回标准 dict 格式
"""

import asyncio as _asyncio_module
import dataclasses
import enum
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger("Galaxy.OpenClawd")


# ============================================================================
# Parallel-group state machine
# ============================================================================

class _SubtaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED  = "failed"
    TIMEOUT = "timeout"


@dataclasses.dataclass
class _SubtaskEntry:
    task_id:       str
    group_id:      str
    subtask_index: int
    device_id:     str
    subtask:       str
    status:        _SubtaskStatus = _SubtaskStatus.PENDING
    started_at:    Optional[float] = None
    finished_at:   Optional[float] = None
    result:        Optional[Dict] = None
    error:         Optional[str] = None
    retry_count:   int = 0


@dataclasses.dataclass
class ParallelResult:
    """Aggregated result for a parallel_group execution."""
    group_id:       str
    device_results: List[Dict]
    summary_status: str          # "success" | "partial" | "failed"
    succeeded:      int
    failed:         int
    total:          int

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


class ParallelGroupTracker:
    """
    State machine for tracking parallel subtask groups.

    Lifecycle per group:
      register_group() → mark_running() → mark_done() (or mark_timeout()) → aggregate()

    Retry policy: 1 retry per subtask, exponential backoff starting at 2 s, capped at 30 s.
    """

    _MAX_RETRIES: int = 1
    _BACKOFF_BASE: float = 2.0
    _BACKOFF_CAP: float = 30.0

    def __init__(self) -> None:
        # group_id → {task_id → _SubtaskEntry}
        self._groups: Dict[str, Dict[str, _SubtaskEntry]] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_group(
        self,
        group_id: str,
        entries: List[_SubtaskEntry],
    ) -> None:
        self._groups[group_id] = {e.task_id: e for e in entries}
        logger.debug(
            "ParallelGroupTracker: registered group=%s subtasks=%d",
            group_id, len(entries),
        )

    def mark_running(self, group_id: str, task_id: str) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.status = _SubtaskStatus.RUNNING
            entry.started_at = time.monotonic()

    def mark_done(
        self,
        group_id: str,
        task_id: str,
        result: Dict,
        *,
        success: bool,
    ) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.status = _SubtaskStatus.SUCCESS if success else _SubtaskStatus.FAILED
            entry.finished_at = time.monotonic()
            entry.result = result
            if not success:
                entry.error = result.get("response") or result.get("error") or "unknown error"

    def mark_timeout(self, group_id: str, task_id: str) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.status = _SubtaskStatus.TIMEOUT
            entry.finished_at = time.monotonic()
            entry.error = "timeout"

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------

    def needs_retry(self, group_id: str, task_id: str) -> bool:
        entry = self._get_entry(group_id, task_id)
        if entry is None:
            return False
        return (
            entry.status in (_SubtaskStatus.FAILED, _SubtaskStatus.TIMEOUT)
            and entry.retry_count < self._MAX_RETRIES
        )

    def backoff_delay(self, group_id: str, task_id: str) -> float:
        entry = self._get_entry(group_id, task_id)
        if entry is None:
            return 0.0
        delay = self._BACKOFF_BASE ** (entry.retry_count + 1)
        return min(delay, self._BACKOFF_CAP)

    def increment_retry(self, group_id: str, task_id: str) -> None:
        entry = self._get_entry(group_id, task_id)
        if entry:
            entry.retry_count += 1
            entry.status = _SubtaskStatus.PENDING
            entry.started_at = None
            entry.finished_at = None
            entry.result = None
            entry.error = None

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def aggregate(self, group_id: str) -> ParallelResult:
        entries = list(self._groups.get(group_id, {}).values())
        device_results: List[Dict] = []
        for e in entries:
            latency_ms: Optional[float] = None
            if e.started_at is not None and e.finished_at is not None:
                latency_ms = round((e.finished_at - e.started_at) * 1000, 1)
            device_results.append({
                "group_id":      group_id,
                "subtask_index": e.subtask_index,
                "device_id":     e.device_id,
                "task_id":       e.task_id,
                "status":        e.status.value,
                "result":        e.result,
                "error":         e.error,
                "latency_ms":    latency_ms,
            })

        succeeded = sum(1 for e in entries if e.status == _SubtaskStatus.SUCCESS)
        failed = len(entries) - succeeded

        if succeeded == len(entries):
            summary = "success"
        elif succeeded > 0:
            summary = "partial"
        else:
            summary = "failed"

        return ParallelResult(
            group_id=group_id,
            device_results=device_results,
            summary_status=summary,
            succeeded=succeeded,
            failed=failed,
            total=len(entries),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_entry(self, group_id: str, task_id: str) -> Optional[_SubtaskEntry]:
        return self._groups.get(group_id, {}).get(task_id)


class OpenClawd:
    """Galaxy-Nexus 星枢核心智能体 — 统一智能交互入口

    串联已有模块实现完整的意图解析 -> 模型选择 -> 执行 -> 响应流水线:
    - ai_intent.py       -> 意图解析
    - multi_llm_router.py -> 模型选择
    - agent_factory.py   -> Agent 创建/复用
    - agent_team.py      -> 团队协作
    - device_orchestrator -> 设备操控
    - mcp_loader.py + skill_loader.py -> 协议工具调用
    """

    # 意图 -> 处理器映射
    _INTENT_HANDLER_MAP = {
        "chat": "_dispatch_chat",
        "device_control": "_dispatch_device",
        "task_manage": "_dispatch_agent",
        "file_operation": "_dispatch_agent",
        "search": "_dispatch_agent",
        "ocr": "_dispatch_tool",
        "system_status": "_dispatch_status",
        "network": "_dispatch_agent",
        "code": "_dispatch_agent",
        # Priority D: 高层自治目标执行
        "goal_execution": "_dispatch_goal_execution",
        # Priority E: 多设备并行任务
        "parallel_goal": "_dispatch_parallel_goal",
    }

    # 核心节点静态 action 目录 — 精确的节点能力描述供 LLM 工具选择
    # 格式: {node_id: {action_name: description, ...}}
    # 仅暴露高价值节点，避免工具列表膨胀 (LLM function calling 建议 ≤ 128 工具)
    _CORE_NODE_ACTIONS: Dict[str, Dict[str, str]] = {
        "06": {  # Filesystem
            "list": "列出目录内容",
            "read": "读取文件内容",
            "write": "写入文件",
            "mkdir": "创建目录",
            "delete": "删除文件或目录",
            "move": "移动/重命名文件",
            "copy": "复制文件",
            "search": "搜索文件",
        },
        "07": {  # Git
            "status": "查看仓库状态",
            "clone": "克隆仓库",
            "commit": "提交更改",
            "push": "推送到远程",
            "pull": "拉取远程更新",
            "log": "查看提交日志",
            "diff": "查看代码差异",
            "checkout": "切换分支或版本",
        },
        "08": {  # Fetch — HTTP 客户端
            "get": "发送 HTTP GET 请求",
            "post": "发送 HTTP POST 请求",
        },
        "09": {  # Sandbox — 代码沙箱
            "execute": "在安全沙箱中执行代码 (支持 Python/JS/Bash/Go/Rust/C 等 14 种语言)",
        },
        "15": {  # OCR
            "extract_text": "从图像中提取文字 (OCR)",
            "document_markdown": "将文档图像转换为 Markdown",
            "table_extract": "从图像中提取表格",
            "ui_analysis": "分析 UI 界面元素",
        },
        "17": {  # EdgeTTS — 语音合成
            "synthesize": "文本转语音合成 (支持中/英/日/韩等多语言)",
            "voices": "列出可用语音列表",
        },
        "22": {  # BraveSearch
            "search": "使用 Brave Search 进行网络搜索",
        },
        "25": {  # GoogleSearch
            "search": "使用 Google 进行网络搜索",
        },
        "33": {  # ADB — Android 设备控制
            "tap": "点击屏幕坐标",
            "swipe": "滑动屏幕",
            "shell": "执行 ADB shell 命令",
            "screenshot": "截取设备屏幕",
            "input": "输入文本",
        },
        "45": {  # DesktopAuto — 桌面自动化
            "click": "点击屏幕坐标",
            "type": "输入文本",
            "hotkey": "按下组合键",
            "screenshot": "截取桌面屏幕",
            "scroll": "滚动鼠标",
        },
        "101": {  # CodeEngine
            "parse_code": "解析和分析代码结构 (AST)",
            "generate_code": "根据需求生成代码",
            "refactor_code": "代码重构和优化",
            "review_code": "代码质量审查",
        },
        "120": {  # File (新版)
            "read": "读取文件内容",
            "write": "写入文件",
            "list": "列出目录内容",
            "search": "搜索文件",
            "info": "获取文件信息",
        },
        "121": {  # Web
            "http_request": "发送 HTTP 请求",
            "scrape": "网页抓取",
            "download": "下载文件",
            "api_call": "调用 API",
        },
        "122": {  # Shell
            "execute": "执行系统命令",
            "script": "执行脚本",
            "list_processes": "列出进程",
        },
    }

    # 从静态目录提取节点 ID 白名单
    _CORE_NODE_IDS = set(_CORE_NODE_ACTIONS.keys())

    def __init__(self):
        self._initialized = False
        self._session_memory: Dict[str, List[Dict]] = {}
        self._request_count = 0
        self._error_count = 0
        self._start_time = time.time()
        # Node action 发现缓存: {node_id: {action_name: description}}
        self._node_actions_cache: Dict[str, Dict[str, str]] = {}
        # Node registry 缓存: {node_id: node_key}
        self._node_id_to_key: Dict[str, str] = {}
        # PR86: 持有 Router 实例（单一来源）
        self._router = None
        # PR86: 内嵌 AgentKernel（懒加载）
        self._kernel = None

        # Phase 9: 工具权限检查器
        self._tool_permission_checker = None
        try:
            from core.tool_permissions import get_tool_permission_checker
            self._tool_permission_checker = get_tool_permission_checker()
        except Exception as e:
            logger.warning(f"工具权限检查器不可用，所有工具将无限制: {e}")

        logger.info("OpenClawd 星枢核心智能体初始化")

    def _ensure_initialized(self):
        """标记为已初始化 (懒加载模式，模块在各方法内按需导入)"""
        if not self._initialized:
            self._initialized = True
            logger.info("OpenClawd 就绪 — 所有模块将按需懒加载")

    def _get_router(self):
        """获取 OpenClawd 持有的 LLM 路由器（单例，Dashboard > ENV > defaults）"""
        if self._router is None:
            try:
                from core.multi_llm_router import get_llm_router
                self._router = get_llm_router()
            except Exception as e:
                logger.warning(f"LLM 路由器加载失败: {e}")
        return self._router

    def _get_kernel(self):
        """获取内嵌的 AgentKernel（懒加载，由 OpenClawd 独占管理）"""
        if self._kernel is None:
            try:
                from core.agent.kernel import AgentKernel
                self._kernel = AgentKernel()
                # 将 OpenClawd 持有的 router 注入到 Kernel
                router = self._get_router()
                if router is not None:
                    self._kernel._llm_router = router
            except Exception as e:
                logger.warning(f"AgentKernel 加载失败: {e}")
        return self._kernel

    # ========================================================================
    # 主入口
    # ========================================================================

    async def process(
        self,
        message: str,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[List[Dict]] = None,
    ) -> dict:
        """主入口 — PR86 架构：OpenClawd 是唯一入口，内嵌 AgentKernel

        架构约束（PR86）：
        - OpenClawd 是 /api/v1/chat 的唯一处理器
        - AgentKernel 由本方法内部调用（Kernel 不再对外作为主入口）
        - SOUL 注入规则：chat_only 不注 SOUL；task_execute/hybrid 强制注入
        - 多模型路由由本实例持有的 _router 统一管理
        - 每次请求携带 request_id (trace ID)

        Args:
            message: 用户输入的自然语言消息
            device_id: 设备 ID (可选，用于设备操控场景)
            session_id: 会话 ID (可选，用于上下文管理)
            context: 对话历史上下文（可选）

        Returns:
            统一响应 dict: {success, response, intent, metadata}
        """
        self._ensure_initialized()
        self._request_count += 1
        t0 = time.monotonic()
        request_id = uuid.uuid4().hex

        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        # 同步新设备能力（确保 OpenClawd 始终感知最新设备）
        try:
            self.sync_device_capabilities()
        except Exception:
            pass

        try:
            # Step 1: 尝试通过内嵌 AgentKernel 处理（chat_only / task_execute / hybrid）
            kernel = self._get_kernel()
            if kernel is not None:
                try:
                    kernel_result = await kernel.handle_message(
                        message=message,
                        session_id=session_id,
                        device_id=device_id or "",
                        context=context or [],
                    )
                    api_dict = kernel_result.to_api_dict()
                    mode = kernel_result.mode
                    # 记录路由决策日志
                    router = self._get_router()
                    provider_info = {}
                    if router:
                        try:
                            provider_info = {
                                "provider": getattr(router, "_last_provider", ""),
                                "model": kernel_result.model or router.get_default_model(),
                                "available_providers": [
                                    p for p in getattr(router, "providers", {}).keys()
                                ],
                            }
                        except Exception:
                            pass
                    logger.info(
                        "OpenClawd request | request_id=%s session=%s mode=%s "
                        "provider=%s model=%s",
                        request_id,
                        session_id,
                        mode,
                        provider_info.get("provider", ""),
                        provider_info.get("model", ""),
                    )
                    latency_ms = (time.monotonic() - t0) * 1000
                    await self._record_turn(session_id, "user", message)
                    await self._record_turn(session_id, "assistant", kernel_result.reply)
                    return {
                        "success": kernel_result.success,
                        "response": kernel_result.reply,
                        "intent": kernel_result.intent.raw_intent,
                        "error": kernel_result.error,
                        "metadata": {
                            "request_id": request_id,
                            "session_id": session_id,
                            "device_id": device_id,
                            "latency_ms": round(latency_ms, 1),
                            "confidence": kernel_result.intent.confidence,
                            "mode": mode,
                            "model": kernel_result.model,
                            "handler": "agent_kernel",
                            **provider_info,
                            "agent_steps": api_dict["agent_steps"],
                            "tool_calls": api_dict["tool_calls"],
                            "task_result": api_dict["task_result"],
                        },
                    }
                except Exception as e:
                    logger.warning("AgentKernel 处理异常，降级到 OpenClawd 直接处理: %s", e)

            # Step 2: AgentKernel 不可用时，OpenClawd 直接处理
            # Step 2a: 意图解析
            parsed_intent = await self._parse_intent(message, session_id)

            # Step 2b: 记录用户消息到会话记忆
            await self._record_turn(session_id, "user", message)

            # Step 2c: 根据意图路由到对应处理器
            intent_type = parsed_intent.intent if parsed_intent else "chat"
            handler_name = self._INTENT_HANDLER_MAP.get(intent_type, "_dispatch_chat")
            if not hasattr(self, handler_name):
                logger.warning(f"Handler {handler_name} not found, falling back to chat")
                handler_name = "_dispatch_chat"
            handler = getattr(self, handler_name)

            result = await handler(
                message=message,
                intent=parsed_intent,
                device_id=device_id,
                session_id=session_id,
            )

            # Step 2d: 记录路由决策
            router = self._get_router()
            provider_info = {}
            if router:
                try:
                    provider_info = {
                        "provider": getattr(router, "_last_provider", ""),
                        "model": router.get_default_model(),
                    }
                except Exception:
                    pass
            logger.info(
                "OpenClawd request | request_id=%s session=%s intent=%s "
                "provider=%s model=%s",
                request_id,
                session_id,
                intent_type,
                provider_info.get("provider", ""),
                provider_info.get("model", ""),
            )

            # Step 2e: 记录助手回复到会话记忆
            response_text = result.get("response", "")
            await self._record_turn(session_id, "assistant", response_text)

            latency_ms = (time.monotonic() - t0) * 1000

            return {
                "success": result.get("success", True),
                "response": response_text,
                "intent": intent_type,
                "metadata": {
                    "request_id": request_id,
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
                    "confidence": parsed_intent.confidence if parsed_intent else 0.0,
                    "suggestions": parsed_intent.suggestions if parsed_intent else [],
                    "handler": handler_name,
                    **provider_info,
                    **(result.get("metadata", {})),
                },
            }

        except Exception as e:
            self._error_count += 1
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error(f"OpenClawd.process 失败: {e}", exc_info=True)
            return {
                "success": False,
                "response": f"处理请求时发生错误: {str(e)}",
                "intent": "error",
                "metadata": {
                    "request_id": request_id,
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
                    "error": str(e),
                },
            }

    # ========================================================================
    # 意图解析
    # ========================================================================

    async def _parse_intent(self, message: str, session_id: str):
        """解析用户意图 (懒加载 IntentParser)"""
        try:
            from core.ai_intent import get_intent_parser

            parser = get_intent_parser()

            # 构建上下文
            context = None
            session_history = self._session_memory.get(session_id, [])
            if session_history:
                context = {"history": session_history[-10:]}

            parsed = await parser.parse(message, context)
            logger.info(
                f"意图解析: intent={parsed.intent}, "
                f"confidence={parsed.confidence:.2f}, "
                f"command={parsed.command}"
            )
            return parsed

        except Exception as e:
            logger.warning(f"意图解析失败，降级到默认 chat 意图: {e}")
            return None

    # ========================================================================
    # 分派处理器
    # ========================================================================

    async def _dispatch_chat(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """纯聊天分派"""
        return await self.handle_chat(message, session_id or "default")

    async def _dispatch_device(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """设备操控分派 — 经由 send_gateway_command → CommandRouter → trace"""
        if not device_id:
            return {
                "success": False,
                "response": "设备操控需要指定 device_id，请连接设备后重试。",
            }
        command = intent.command if intent else "device_control"
        params = intent.params if intent else {}
        result = await self.send_gateway_command(
            device_id=device_id,
            command=command,
            payload=params,
            session_id=session_id,
        )
        # 统一响应字段（send_gateway_command 返回 response/success，保持 handle_device_command 兼容）
        if "response" not in result:
            if result.get("success"):
                result["response"] = result.get("result") or f"设备命令 '{command}' 已发送到 {device_id}"
            else:
                result["response"] = result.get("result") or f"无法向设备 {device_id} 发送命令 '{command}'"
        return result

    async def _dispatch_agent(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Agent 任务分派"""
        return await self.handle_agent_task(message, intent)

    async def _dispatch_tool(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """工具调用分派"""
        return await self.handle_tool_call(intent)

    async def _dispatch_status(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """系统状态分派"""
        status = await self.get_status()
        # 将状态格式化为可读文本
        provider_count = status.get("llm_router", {}).get("total_providers", 0)
        agent_count = status.get("agent_factory", {}).get("total_agents", 0)
        mcp_count = status.get("mcp", {}).get("server_count", 0)
        skill_count = status.get("skills", {}).get("loaded_skills", 0)

        summary_lines = [
            "Galaxy 系统状态概览:",
            f"  LLM 提供商: {provider_count} 个",
            f"  活跃 Agent: {agent_count} 个",
            f"  MCP 服务器: {mcp_count} 个",
            f"  已加载技能: {skill_count} 个",
            f"  总请求数: {self._request_count}",
            f"  错误数: {self._error_count}",
            f"  运行时间: {int(time.time() - self._start_time)}s",
        ]
        return {
            "success": True,
            "response": "\n".join(summary_lines),
            "metadata": {"status_detail": status},
        }

    @staticmethod
    def _pick_autonomous_device_id(
        device_id: Optional[str],
        capability_key: str = "goal_execution_enabled",
    ) -> Optional[str]:
        """
        Select the best device for autonomous execution.

        Priority order:
          1. Explicit ``device_id`` if provided (caller takes responsibility for
             the device being capable).
          2. CapabilityRegistry autonomous__* entries matching ``capability_key``
             (Phase-3 SSOT, preferred over raw UDM when no explicit device is given).
          3. UnifiedDeviceManager.get_autonomous_devices() (UDM-based fallback).

        Returns None when no suitable device can be identified so the caller
        can degrade gracefully.
        """
        # 1. Caller-supplied device_id takes highest priority
        if device_id:
            logger.debug(
                "_pick_autonomous_device_id: using caller-supplied device_id=%s", device_id,
            )
            return device_id

        # 2. Try CapabilityRegistry (autonomous__* prefix = Phase-3 SSOT)
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            items = [
                item for item in reg.list_tools(source="autonomous")
                if item.available
                and capability_key in item.name
            ]
            if items:
                selected_id = items[0].metadata.get("device_id") or items[0].source_id
                logger.info(
                    "_pick_autonomous_device_id: CapabilityRegistry selected device=%s (cap=%s)",
                    selected_id, capability_key,
                )
                return selected_id
        except Exception as exc:
            logger.debug("_pick_autonomous_device_id: CapabilityRegistry lookup failed: %s", exc)

        # 3. Fallback to UDM
        try:
            from core.unified.device_manager import get_unified_device_manager
            auto_devices = get_unified_device_manager().get_autonomous_devices()
            if auto_devices:
                selected_id = auto_devices[0].device_id
                logger.info(
                    "_pick_autonomous_device_id: UDM selected device=%s", selected_id,
                )
                return selected_id
        except Exception as exc:
            logger.debug("_pick_autonomous_device_id: UDM lookup failed: %s", exc)

        return None

    async def _dispatch_goal_execution(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Priority D: 高层自治目标执行分派。

        流程：
          1. 优先从 CapabilityRegistry autonomous__* 条目选择支持
             goal_execution_enabled 的设备（Phase-3 SSOT）。
          2. 若 CapabilityRegistry 无结果，回退到 UnifiedDeviceManager 自治设备列表。
          3. 若仍无可用自治设备，降级到普通 _dispatch_agent 并记录明确消息。
        """
        goal = message
        params = {}
        if intent:
            goal = getattr(intent, "goal", None) or getattr(intent, "command", None) or message
            params = getattr(intent, "params", {}) or {}

        # 确定目标设备（自治能力感知）
        target_device_id = self._pick_autonomous_device_id(
            device_id, capability_key="goal_execution_enabled"
        )

        if not target_device_id:
            logger.info(
                "goal_execution: 无可用自治设备（CapabilityRegistry autonomous__* 和 UDM 均未返回结果），"
                "降级为 agent 执行"
            )
            return await self._dispatch_agent(message, intent, device_id, session_id)

        result = await self.send_gateway_command(
            device_id=target_device_id,
            command="goal_execution",
            payload={
                "task_type": "goal_execution",
                "goal": goal,
                **params,
            },
            session_id=session_id,
        )
        if "response" not in result:
            result["response"] = (
                result.get("result")
                or f"目标任务 '{goal}' 已提交至设备 {target_device_id}"
            )
        result["intent"] = "goal_execution"
        logger.info(
            "goal_execution dispatched | device=%s success=%s",
            target_device_id,
            result.get("success"),
        )
        return result

    async def _dispatch_parallel_goal(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> dict:
        """Priority E: 多设备并行任务拆分与下发（Phase-3 状态机 + 重试）。

        流程：
          1. 优先从 CapabilityRegistry 选择声明 autonomous__* / parallel_execution_enabled
             能力的设备；回退到 UDM get_autonomous_devices()。
          2. 若无可用设备，降级并返回明确降级消息（不走 goal_execution）。
          3. 使用 ParallelGroupTracker 追踪每个子任务状态。
          4. 对失败子任务执行最多 1 次指数退避重试（上限 30 s）。
          5. 所有子任务完成后聚合 ParallelResult 并返回统一结构。
        """
        goal = message
        params = {}
        if intent:
            goal = getattr(intent, "goal", None) or getattr(intent, "command", None) or message
            params = getattr(intent, "params", {}) or {}

        # 查找支持并行执行的设备（autonomous__* 优先）
        parallel_devices = []
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            # devices with parallel_execution_enabled in autonomous__* items
            auto_items = [
                item for item in reg.list_tools(source="autonomous")
                if item.available and "parallel_execution_enabled" in item.name
            ]
            seen_ids: set = set()
            for item in auto_items:
                did = item.metadata.get("device_id") or item.source_id
                if did and did not in seen_ids:
                    seen_ids.add(did)
                    parallel_devices.append(did)
        except Exception as exc:
            logger.debug("parallel_goal: CapabilityRegistry 查询失败: %s", exc)

        # Fallback: UDM
        if not parallel_devices:
            try:
                from core.unified.device_manager import get_unified_device_manager
                udm = get_unified_device_manager()
                devs = udm.get_devices_with_capability("parallel_execution_enabled")
                if not devs:
                    devs = udm.get_autonomous_devices()
                parallel_devices = [d.device_id for d in devs]
            except Exception as exc:
                logger.debug("parallel_goal: UDM 设备查询失败: %s", exc)

        if not parallel_devices:
            logger.info(
                "parallel_goal: 无支持并行执行的自治设备（autonomous__* 和 UDM 均无结果），"
                "降级：无法执行并行任务"
            )
            return {
                "success": False,
                "response": (
                    "当前无支持并行执行的自治设备。"
                    "请确保至少一台设备注册了 parallel_execution_enabled 能力后重试。"
                ),
                "intent": "parallel_goal",
                "metadata": {"parallel_group": None, "device_count": 0},
            }

        subtasks = params.get("subtasks") or [goal] * len(parallel_devices)
        task_id_base = uuid.uuid4().hex[:8]

        # ── 初始化状态追踪 ──
        tracker = ParallelGroupTracker()
        entries: List[_SubtaskEntry] = []
        for idx, dev_id in enumerate(parallel_devices):
            sub_task_id = f"{task_id_base}_sub{idx}"
            entries.append(_SubtaskEntry(
                task_id=sub_task_id,
                group_id=task_id_base,
                subtask_index=idx,
                device_id=dev_id,
                subtask=subtasks[idx % len(subtasks)],
            ))
        tracker.register_group(task_id_base, entries)

        async def _execute_entry(entry: _SubtaskEntry) -> None:
            """Execute one subtask with retry/backoff, updating tracker in-place."""
            while True:
                tracker.mark_running(entry.group_id, entry.task_id)
                try:
                    r = await self.send_gateway_command(
                        device_id=entry.device_id,
                        command="goal_execution",
                        payload={
                            "task_type": "parallel_subtask",
                            "goal": entry.subtask,
                            "parallel_group": entry.group_id,
                            "subtask_index": entry.subtask_index,
                        },
                        task_id=entry.task_id,
                        session_id=session_id,
                    )
                    # Propagate command_id / task_id into result
                    r.setdefault("command_id", "")
                    r.setdefault("task_id", entry.task_id)
                    success = bool(r.get("success"))
                    tracker.mark_done(entry.group_id, entry.task_id, r, success=success)
                    if not success and tracker.needs_retry(entry.group_id, entry.task_id):
                        delay = tracker.backoff_delay(entry.group_id, entry.task_id)
                        logger.warning(
                            "parallel_goal: subtask %d on device %s failed, "
                            "retry in %.1fs (attempt %d/%d)",
                            entry.subtask_index, entry.device_id,
                            delay, entry.retry_count + 1, ParallelGroupTracker._MAX_RETRIES,
                        )
                        tracker.increment_retry(entry.group_id, entry.task_id)
                        await _asyncio_module.sleep(delay)
                        continue
                    return
                except Exception as exc:
                    err_result = {
                        "success": False,
                        "response": str(exc),
                        "task_id": entry.task_id,
                        "device_id": entry.device_id,
                    }
                    tracker.mark_done(entry.group_id, entry.task_id, err_result, success=False)
                    if tracker.needs_retry(entry.group_id, entry.task_id):
                        delay = tracker.backoff_delay(entry.group_id, entry.task_id)
                        logger.warning(
                            "parallel_goal: subtask %d on device %s raised %s, "
                            "retry in %.1fs",
                            entry.subtask_index, entry.device_id, exc, delay,
                        )
                        tracker.increment_retry(entry.group_id, entry.task_id)
                        await _asyncio_module.sleep(delay)
                        continue
                    logger.warning(
                        "parallel_goal: subtask %d on device %s permanently failed: %s",
                        entry.subtask_index, entry.device_id, exc,
                    )
                    return

        await _asyncio_module.gather(
            *[_execute_entry(e) for e in entries],
            return_exceptions=True,
        )

        parallel_result = tracker.aggregate(task_id_base)
        summary_text = (
            f"并行任务 '{goal}' 已分发至 {len(parallel_devices)} 台设备："
            f"{parallel_result.succeeded} 成功，{parallel_result.failed} 失败。"
        )
        logger.info(
            "parallel_goal done | group=%s devices=%d succeeded=%d failed=%d status=%s",
            task_id_base,
            len(parallel_devices),
            parallel_result.succeeded,
            parallel_result.failed,
            parallel_result.summary_status,
        )
        return {
            "success": parallel_result.succeeded > 0,
            "response": summary_text,
            "intent": "parallel_goal",
            "metadata": {
                "parallel_group": task_id_base,
                "subtask_results": parallel_result.device_results,
                "device_count": len(parallel_devices),
                "parallel_result": parallel_result.to_dict(),
            },
        }

    def _collect_tools(self) -> List[Dict]:
        """统一收集三层工具（MCP / Skill / Node），转为 OpenAI function calling 格式

        返回格式: [{"type": "function", "function": {"name": "mcp__server__tool", ...}}, ...]
        前缀约定:
          - mcp__<server_id>__<tool_name>   → MCP 协议工具
          - skill__<skill_id>               → Skill 技能
          - node__<node_id>__<action>       → Node 节点操作
        """
        tools: List[Dict] = []

        # ── 层 1: MCP 服务器工具 ──
        try:
            from core.mcp_loader import mcp_loader
            import asyncio

            for server_info in mcp_loader.list_servers():
                server_id = server_info.get("id", "")
                if server_info.get("status") != "running":
                    continue
                # list_tools 是 async，但 _collect_tools 是 sync
                # 使用已缓存的 tools 列表（如果可用）
                cached_tools = server_info.get("tools", [])
                for tool in cached_tools:
                    tool_name = tool.get("name", "")
                    if not tool_name:
                        continue
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"mcp__{server_id}__{tool_name}",
                            "description": tool.get("description", f"MCP tool: {tool_name}"),
                            "parameters": tool.get("inputSchema", tool.get("parameters", {
                                "type": "object", "properties": {}
                            })),
                        },
                    })
        except Exception as e:
            logger.debug(f"收集 MCP 工具失败: {e}")

        # ── 层 1.5: MCP Gateway 自造工具 ──
        try:
            from core.mcp_gateway import get_mcp_gateway
            gateway = get_mcp_gateway()
            for tool in gateway.list_generated_tools():
                tool_name = tool.get("name", "")
                if not tool_name:
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"mcp__gateway__{tool_name}",
                        "description": tool.get("description", f"Generated tool: {tool_name}"),
                        "parameters": tool.get("parameters", {
                            "type": "object", "properties": {}
                        }),
                    },
                })
        except Exception as e:
            logger.debug(f"收集 MCP Gateway 工具失败: {e}")

        # ── 层 2: Skill 技能 ──
        try:
            from core.skill_loader import skill_loader

            for skill_info in skill_loader.list_skills():
                skill_id = skill_info.get("id", "")
                if not skill_id or skill_info.get("status") == "error":
                    continue
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"skill__{skill_id}",
                        "description": skill_info.get("description", f"Skill: {skill_id}"),
                        "parameters": skill_info.get("parameters", {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "description": "输入参数"}
                            },
                        }),
                    },
                })
        except Exception as e:
            logger.debug(f"收集 Skill 工具失败: {e}")

        # ── 层 3: Node 节点操作 (静态 action 目录 + 注册表验证) ──
        try:
            import json as _json
            import os as _os
            registry_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(__file__)), "config", "node_registry.json"
            )
            # 加载注册表获取节点名称和 node_key 映射
            registry_names: Dict[str, str] = {}  # node_id → node_name
            if _os.path.exists(registry_path):
                with open(registry_path, "r", encoding="utf-8") as f:
                    registry = _json.load(f)
                for node_key, node_info in registry.get("nodes", {}).items():
                    nid = node_info.get("id", "")
                    if nid and node_info.get("status") == "active" and node_info.get("has_main"):
                        registry_names[nid] = node_info.get("name", nid)
                        self._node_id_to_key[nid] = node_key

            # 从静态目录生成工具列表
            for node_id, actions_map in self._CORE_NODE_ACTIONS.items():
                node_name = registry_names.get(node_id, f"Node_{node_id}")
                for action_name, action_desc in actions_map.items():
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"node__{node_id}__{action_name}",
                            "description": f"Node {node_name}: {action_desc}",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "params": {"type": "object", "description": "操作参数"}
                                },
                            },
                        },
                    })
        except Exception as e:
            logger.debug(f"收集 Node 工具失败: {e}")

        logger.info(f"工具总线收集完成: {len(tools)} 个工具")
        return tools

    async def _dispatch_tool_call(self, tool_name: str, arguments: dict) -> dict:
        """根据工具名前缀分发到对应执行器

        Args:
            tool_name: 格式为 "mcp__server__tool" / "skill__id" / "node__id__action"
            arguments: 工具参数

        Returns:
            {"success": bool, "result": Any, "error": Optional[str]}
        """
        # Phase 9: 工具调用权限检查
        if self._tool_permission_checker:
            try:
                check = self._tool_permission_checker.check(
                    tool_name=tool_name,
                    session_id=getattr(self, "_current_session_id", ""),
                    device_id=getattr(self, "_current_device_id", ""),
                )
                if not check.allowed:
                    logger.warning(f"工具调用被拒绝: {tool_name} — {check.reason}")
                    return {"success": False, "error": f"权限拒绝: {check.reason}"}
                if check.requires_confirmation:
                    return {
                        "success": False,
                        "needs_confirmation": True,
                        "tool": tool_name,
                        "risk_level": check.risk_level,
                        "error": f"操作 [{tool_name}] 需要用户确认（风险等级: {check.risk_level}）",
                    }
            except Exception as e:
                logger.debug(f"权限检查异常（放行）: {e}")

        try:
            if tool_name.startswith("mcp__"):
                parts = tool_name.split("__", 2)
                if len(parts) < 3:
                    return {"success": False, "error": f"无效 MCP 工具名: {tool_name}"}
                server_id, mcp_tool_name = parts[1], parts[2]

                # 特殊处理 gateway 自造工具
                if server_id == "gateway":
                    try:
                        from core.mcp_gateway import get_mcp_gateway
                        gateway = get_mcp_gateway()
                        result = await gateway.execute_tool(mcp_tool_name, arguments)
                        return {"success": True, "result": result}
                    except Exception as e:
                        return {"success": False, "error": f"Gateway 工具执行失败: {e}"}

                from core.mcp_loader import mcp_loader
                result = await mcp_loader.call_tool(server_id, mcp_tool_name, arguments)
                return {"success": True, "result": result}

            elif tool_name.startswith("skill__"):
                skill_id = tool_name[7:]  # len("skill__") == 7
                from core.skill_loader import skill_loader
                result = await skill_loader.execute(skill_id, **arguments)
                return {"success": True, "result": result}

            elif tool_name.startswith("node__"):
                parts = tool_name.split("__", 2)
                if len(parts) < 3:
                    return {"success": False, "error": f"无效 Node 工具名: {tool_name}"}
                node_id, action_name = parts[1], parts[2]
                # 通过已验证的 fusion_entry 执行路径
                from core.routes._helpers import _load_node, _execute_node, nodes_root
                import os as _os

                node_key = self._find_node_key(node_id)
                if not node_key:
                    return {"success": False, "error": f"节点 {node_id} 未在注册表中"}

                node_dir = _os.path.join(nodes_root, node_key)
                fusion_path = _os.path.join(node_dir, "fusion_entry.py")
                if not _os.path.exists(fusion_path):
                    return {"success": False, "error": f"节点 {node_id} 无 fusion_entry.py"}

                node_info = _load_node(node_id, node_dir, fusion_path)
                if not node_info:
                    return {"success": False, "error": f"节点 {node_id} 加载失败"}

                params = arguments.get("params", arguments)
                result = await _execute_node(
                    node_info, action_name, params if isinstance(params, dict) else {}
                )
                return {"success": True, "result": result}

            else:
                return {"success": False, "error": f"未知工具前缀: {tool_name}"}

        except Exception as e:
            logger.warning(f"工具执行失败 [{tool_name}]: {e}")
            return {"success": False, "error": str(e)}

    # ========================================================================
    # Node 辅助方法
    # ========================================================================

    def _find_node_key(self, node_id: str) -> Optional[str]:
        """根据 node_id 在注册表/缓存中查找 node_key (如 'Node_06_Filesystem')"""
        # 先查内存缓存
        if node_id in self._node_id_to_key:
            return self._node_id_to_key[node_id]
        # 回退到文件读取
        try:
            import json, os
            registry_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "config", "node_registry.json"
            )
            with open(registry_path, "r", encoding="utf-8") as f:
                registry = json.load(f)
            for key, info in registry.get("nodes", {}).items():
                if info.get("id") == node_id:
                    self._node_id_to_key[node_id] = key
                    return key
        except Exception:
            pass
        return None

    def _discover_node_actions(self, node_id: str, node_key: str) -> Dict[str, str]:
        """通过加载 fusion_entry 发现节点的可用 actions

        Returns:
            {action_name: description} — 不含 status/help 元操作
        """
        try:
            from core.routes._helpers import _load_node, nodes_root
            import os
            import inspect
            import asyncio

            node_dir = os.path.join(nodes_root, node_key)
            fusion_path = os.path.join(node_dir, "fusion_entry.py")
            if not os.path.exists(fusion_path):
                return {}

            node_info = _load_node(node_id, node_dir, fusion_path)
            if not node_info:
                return {}

            def _call_sync(action: str):
                """调用 execute，处理 sync/async 两种模式"""
                try:
                    if node_info["type"] == "function":
                        func = node_info["execute"]
                        if inspect.iscoroutinefunction(func):
                            # 尝试在新事件循环中运行（仅在非 async 上下文有效）
                            try:
                                loop = asyncio.get_running_loop()
                                # 已在运行的 loop 中 → asyncio.run 会崩溃，跳过
                                return None
                            except RuntimeError:
                                return asyncio.run(func(action, {}))
                        else:
                            return func(action, {})
                    else:
                        method = node_info["instance"].execute
                        if inspect.iscoroutinefunction(method):
                            try:
                                loop = asyncio.get_running_loop()
                                return None
                            except RuntimeError:
                                return asyncio.run(method(action))
                        else:
                            return method(action)
                except Exception:
                    return None

            _skip = {"status", "help"}

            # 优先尝试 help → 获取带描述的 actions dict
            try:
                help_result = _call_sync("help")
                if isinstance(help_result, dict):
                    actions_map = help_result.get("actions", {})
                    if isinstance(actions_map, dict) and actions_map:
                        return {k: str(v) for k, v in actions_map.items() if k not in _skip}
            except Exception:
                pass

            # 退化到 status → 获取 available_actions 列表
            try:
                status_result = _call_sync("status")
                if isinstance(status_result, dict):
                    actions = status_result.get("available_actions", status_result.get("actions", []))
                    if isinstance(actions, dict):
                        return {k: str(v) for k, v in actions.items() if k not in _skip}
                    if isinstance(actions, list):
                        return {a: f"Execute {a}" for a in actions
                                if isinstance(a, str) and a not in _skip}
            except Exception:
                pass

            return {}
        except Exception as e:
            logger.debug(f"发现节点 {node_id} ({node_key}) actions 失败: {e}")
            return {}

    # ========================================================================
    # ReAct 工具调用循环
    # ========================================================================

    async def _react_loop(
        self,
        messages: List[Dict],
        tools: List[Dict],
        max_iterations: int = 10,
        task_type: Optional[str] = None,
        timeout: float = 120.0,
    ) -> dict:
        """ReAct 工具调用循环 (含总超时保护)

        循环流程:
          1. 调用 LLM（带 tools）
          2. 如果 LLM 返回 tool_calls → 执行每个工具 → 追加结果到 messages → 继续
          3. 如果 LLM 返回纯文本（无 tool_calls） → break，返回最终文本

        Args:
            timeout: 总超时秒数，防止工具挂起导致系统永久阻塞

        Returns:
            dict 兼容格式 (内部使用 ToolCallRecord 结构化记录)
        """
        import asyncio as _asyncio
        import time as _time
        from core.multi_llm_router import get_llm_router
        from core.schemas.tool_call import ToolCallRecord, ToolCallStatus

        router = get_llm_router()

        tool_records: List[ToolCallRecord] = []
        last_response = None
        total_tokens = 0

        # Phase 9: 频率限制计数器
        _total_tool_calls = 0
        _MAX_TOOL_CALLS = 20  # 单次请求最大工具调用次数
        _consecutive_same: Dict[str, int] = {}  # 连续同名工具计数
        _last_tool_name = ""

        async def _inner_loop():
            nonlocal last_response, total_tokens
            nonlocal _total_tool_calls, _last_tool_name

            for iteration in range(max_iterations):
                response = await router.chat(
                    messages=messages,
                    tools=tools if tools else None,
                    task_type=task_type,
                    max_tokens=4096,
                )
                last_response = response
                total_tokens += (response.input_tokens + response.output_tokens)

                if not response.tool_calls:
                    # 无工具调用 → 最终回复
                    break

                # 先把 assistant 的 tool_calls 消息追加到 messages
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": response.content or "",
                }
                if response.tool_calls:
                    assistant_msg["tool_calls"] = response.tool_calls
                messages.append(assistant_msg)

                for tc in response.tool_calls:
                    tc_func = tc.get("function", {})
                    tc_name = tc_func.get("name", "")
                    tc_id = tc.get("id", f"call_{tc_name}")

                    # 解析参数
                    try:
                        import json as _json
                        tc_args = _json.loads(tc_func.get("arguments", "{}"))
                    except (ValueError, TypeError):
                        tc_args = {}

                    logger.info(f"ReAct 迭代 {iteration+1}: 调用工具 {tc_name}")

                    # Phase 9: 频率限制检查
                    _total_tool_calls += 1
                    if _total_tool_calls > _MAX_TOOL_CALLS:
                        logger.warning(
                            f"ReAct 工具调用总次数超限 ({_MAX_TOOL_CALLS})，强制终止"
                        )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": f"[系统] 工具调用次数已达上限 ({_MAX_TOOL_CALLS})，请直接给出最终回答",
                        })
                        break

                    # 连续同一工具检查
                    if tc_name == _last_tool_name:
                        _consecutive_same[tc_name] = _consecutive_same.get(tc_name, 1) + 1
                        if _consecutive_same[tc_name] >= 3:
                            logger.warning(
                                f"连续调用同一工具 {tc_name} 达 3 次，疑似幻觉循环，终止"
                            )
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "content": f"[系统] 检测到重复调用 {tc_name}，请直接给出最终回答",
                            })
                            break
                    else:
                        _consecutive_same.clear()
                    _last_tool_name = tc_name

                    # 执行工具 (带计时 + 单工具超时)
                    t0 = _time.time()
                    try:
                        result = await _asyncio.wait_for(
                            self._dispatch_tool_call(tc_name, tc_args),
                            timeout=30.0  # 单个工具调用最多 30 秒
                        )
                    except _asyncio.TimeoutError:
                        result = {"success": False, "error": f"工具 {tc_name} 执行超时 (30s)"}
                    elapsed_ms = (_time.time() - t0) * 1000

                    # 构造结构化记录
                    layer = ToolCallRecord.classify_layer(tc_name)
                    status = ToolCallStatus.SUCCESS if result.get("success", True) else ToolCallStatus.ERROR
                    result_str = str(result.get("result", result.get("error", "")))
                    tool_records.append(ToolCallRecord(
                        tool_name=tc_name,
                        layer=layer,
                        arguments=tc_args,
                        result=result_str[:2000],
                        status=status,
                        error=result.get("error") if not result.get("success", True) else None,
                        latency_ms=round(elapsed_ms, 1),
                        iteration=iteration,
                    ))

                    # 追加 tool result 到 messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_str[:4000],
                    })

        try:
            await _asyncio.wait_for(_inner_loop(), timeout=timeout)
        except _asyncio.TimeoutError:
            logger.warning(f"ReAct 循环总超时 ({timeout}s)，返回已有内容")

        final_text = last_response.content if last_response else ""
        timed_out = last_response is None  # 如果整个循环超时还没拿到 response

        # 返回兼容 dict (同时携带结构化 tool_records)
        return {
            "response": final_text if not timed_out else "处理超时，请稍后重试",
            "tool_calls_log": [r.model_dump() for r in tool_records],
            "tool_records": tool_records,  # 结构化版本
            "iterations": len(tool_records),
            "provider": last_response.provider if last_response else "",
            "model": last_response.model if last_response else "",
            "total_tokens": total_tokens,
            "timeout": timed_out,
        }

    # ========================================================================
    # handle_chat — 对话（带 ReAct 工具调用能力）
    # ========================================================================

    async def handle_chat(self, message: str, session_id: str) -> dict:
        """对话处理 — 使用 ReAct 循环，支持自动工具调用

        流程: 构建 messages → 收集 tools → _react_loop() → 返回结果
        如果没有可用工具，退化为普通 LLM 对话。

        Args:
            message: 用户消息
            session_id: 会话 ID

        Returns:
            响应 dict
        """
        try:
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()

            if not router.is_available():
                return {
                    "success": False,
                    "response": (
                        "LLM 服务未配置。请设置 API Key "
                        "(OPENAI_API_KEY / ANTHROPIC_API_KEY / DEEPSEEK_API_KEY)。"
                    ),
                }

            # 构建消息列表
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是 Galaxy 智能助手 (OpenClawd)，一个桌面级超级 AI 智能体。\n"
                        "你可以帮助用户进行对话、任务管理、设备控制、代码执行等操作。\n"
                        "当你需要执行操作时，请使用提供的工具。\n"
                        "如果没有合适的工具，直接用文字回答。"
                    ),
                },
            ]

            # 添加会话历史
            session_history = self._session_memory.get(session_id, [])
            for turn in session_history[-10:]:
                messages.append(turn)

            messages.append({"role": "user", "content": message})

            # 收集可用工具
            tools = self._collect_tools()

            # 计算复杂度 (结构化向量)
            cv = router._compute_complexity_vector(messages, tools if tools else None)

            # 使用 ReAct 循环
            result = await self._react_loop(messages, tools)

            # 构建层级使用统计
            tool_records = result.get("tool_records", [])
            layers_used = list(set(r.layer.value for r in tool_records)) if tool_records else []

            return {
                "success": True,
                "response": result["response"],
                "metadata": {
                    "provider": result.get("provider", ""),
                    "model": result.get("model", ""),
                    "iterations": result.get("iterations", 1),
                    "tool_calls": len(result.get("tool_calls_log", [])),
                    "tool_calls_log": result.get("tool_calls_log", []),
                    "total_tokens": result.get("total_tokens", 0),
                    "complexity_score": cv.weighted_score,
                    "model_tier": cv.tier.value,
                    "complexity_vector": cv.model_dump(),
                    "layers_used": layers_used,
                    "hit_max_iterations": result.get("hit_max_iterations", False),
                },
            }

        except Exception as e:
            logger.error(f"handle_chat 失败: {e}")
            return {
                "success": False,
                "response": f"聊天处理失败: {str(e)}",
            }

    # ========================================================================
    # handle_device_command — 设备操控
    # ========================================================================

    async def handle_device_command(self, intent, device_id: str) -> dict:
        """设备操控 — 通过 DeviceOrchestrator 执行设备命令

        Args:
            intent: 解析后的意图 (ParsedIntent)
            device_id: 目标设备 ID

        Returns:
            执行结果 dict
        """
        command = intent.command if intent else "device_control"
        params = intent.params if intent else {}

        # 尝试使用 DeviceOrchestrator
        try:
            from core.device_orchestrator import get_device_orchestrator

            orchestrator = get_device_orchestrator()
            result = await orchestrator.execute_command(
                device_id=device_id,
                command=command,
                params=params,
            )

            success = result.get("success", False) if isinstance(result, dict) else bool(result)
            response_text = (
                result.get("message", "设备命令已执行")
                if isinstance(result, dict)
                else str(result)
            )

            return {
                "success": success,
                "response": response_text,
                "metadata": {
                    "device_id": device_id,
                    "command": command,
                    "result": result if isinstance(result, dict) else {"output": str(result)},
                },
            }

        except ImportError:
            logger.warning("DeviceOrchestrator 不可用，尝试直接设备通信")
        except Exception as e:
            logger.warning(f"DeviceOrchestrator 执行失败: {e}")

        # 降级: 尝试通过 WebSocket 直接发送命令
        try:
            from core.routes._shared import connection_manager

            sent = await connection_manager.send_to_device(
                device_id,
                {
                    "type": "task",
                    "task_type": command,
                    "payload": params,
                },
            )

            if sent:
                return {
                    "success": True,
                    "response": f"设备命令已通过 WebSocket 发送到 {device_id}",
                    "metadata": {"device_id": device_id, "command": command, "via": "websocket"},
                }

        except Exception as e:
            logger.debug(f"WebSocket 发送失败: {e}")

        return {
            "success": False,
            "response": f"无法向设备 {device_id} 发送命令 '{command}'，设备可能未连接。",
            "metadata": {"device_id": device_id, "command": command},
        }

    # ========================================================================
    # handle_agent_task — 复杂任务 (Agent 协作)
    # ========================================================================

    async def handle_agent_task(self, message: str, intent) -> dict:
        """复杂任务处理 — 使用 AgentFactory 创建 Agent，必要时组建团队

        Args:
            message: 用户消息
            intent: 解析后的意图 (ParsedIntent)

        Returns:
            Agent 执行结果 dict
        """
        try:
            from core.agent_factory import get_agent_factory
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
            factory = get_agent_factory(router)

            # 判断是否需要团队协作 (复杂度驱动)
            tools = self._collect_tools()
            cv = router._compute_complexity_vector(
                [{"role": "user", "content": message}],
                tools if tools else None,
            )
            targets = intent.targets if intent else []
            is_complex = (
                cv.weighted_score >= 0.6
                or len(targets) > 2
                or (intent and intent.intent in ("workflow", "batch_task", "multi_device"))
            )

            if is_complex:
                # 复杂任务 -> 团队协作
                return await self._execute_team_task(message, intent, factory, router)

            # 普通 Agent 任务
            # 根据意图匹配模板
            template = self._select_agent_template(intent)

            try:
                agent = factory.create_from_template(template)
            except ValueError:
                agent = factory.create_from_template("coordinator")

            # 构建任务
            task_payload = {
                "task": message,
                "intent": intent.intent if intent else "general",
                "params": intent.params if intent else {"message": message},
            }

            result = await factory.execute_agent_task(agent.id, task_payload)

            # 防御: result 可能为 None
            if not result or not isinstance(result, dict):
                result = {"status": "error", "results": [{"error": "Agent 任务执行返回空结果"}]}

            # 提取输出
            outputs = []
            for r in result.get("results", []):
                if isinstance(r, dict):
                    if "output" in r:
                        outputs.append(r["output"])
                    elif "error" in r:
                        outputs.append(f"[错误] {r['error']}")

            reply = "\n".join(outputs) if outputs else "Agent 任务已完成"

            # 清理 Agent
            factory.terminate_agent(agent.id)

            return {
                "success": result.get("status") != "error",
                "response": reply,
                "metadata": {
                    "agent_id": agent.id,
                    "agent_role": agent.config.role.value,
                    "template": template,
                    "result_count": len(result.get("results", [])),
                },
            }

        except Exception as e:
            logger.error(f"handle_agent_task 失败: {e}")
            # 降级到纯聊天
            return await self.handle_chat(message, "fallback")

    async def _execute_team_task(self, message: str, intent, factory, router) -> dict:
        """执行团队协作任务 — 复杂度驱动策略 + 工具注入 + Manifest 记录"""
        try:
            from core.agent_team import TeamManager, TeamStrategy
            from core.schemas.agent import TeamManifestSchema, TeamMemberSchema, TeamStrategyEnum

            manager = TeamManager(agent_factory=factory, llm_router=router)

            # 收集工具 & 计算复杂度向量
            tools = self._collect_tools()
            cv = router._compute_complexity_vector(
                [{"role": "user", "content": message}],
                tools if tools else None,
            )

            # 复杂度驱动策略选择
            if cv.weighted_score >= 0.7:
                strategy = "specialized"
            elif cv.weighted_score >= 0.4:
                strategy = "parallel"
            else:
                strategy = "parallel"

            # 意图覆写
            if intent and intent.intent == "workflow":
                strategy = "specialized"
            elif intent and hasattr(intent, "targets") and len(intent.targets) > 5:
                strategy = "swarm"

            # 创建团队 (传复杂度)
            team = await manager.create_team(
                strategy=strategy, task_hint=message,
                complexity_score=cv.weighted_score,
            )

            # 注入工具能力
            team.set_tools(tools, dispatch_fn=self._dispatch_tool_call)

            # 生成 Manifest 记录
            manifest = TeamManifestSchema(
                team_id=team.team_id,
                strategy=TeamStrategyEnum(strategy),
                task=message,
                members=[TeamMemberSchema.from_dataclass(m) for m in team.members],
                complexity_score=cv.weighted_score,
            )

            team_result = await team.execute(message)

            # 解散团队释放资源
            manager.disband_team(team.team_id)

            return {
                "success": True,
                "response": team_result.synthesized,
                "metadata": {
                    "team_id": team_result.team_id,
                    "strategy": team_result.strategy,
                    "member_count": len(team_result.member_results),
                    "total_latency_ms": round(team_result.total_latency_ms, 1),
                    "total_tokens": team_result.total_tokens,
                    "manifest": manifest.model_dump(),
                    "complexity_vector": cv.model_dump(),
                    "model_tier": cv.tier.value,
                },
            }

        except Exception as e:
            logger.warning(f"团队协作失败，降级到单 Agent: {e}")
            try:
                agent = factory.create_from_template("coordinator")
                result = await factory.execute_agent_task(
                    agent.id, {"task": message}
                )
                outputs = []
                for r in result.get("results", []):
                    if isinstance(r, dict) and "output" in r:
                        outputs.append(r["output"])
                factory.terminate_agent(agent.id)
                return {
                    "success": True,
                    "response": "\n".join(outputs) if outputs else "任务已完成",
                    "metadata": {"fallback": "single_agent"},
                }
            except Exception as inner_e:
                return {
                    "success": False,
                    "response": f"任务执行失败: {str(inner_e)}",
                }

    def _select_agent_template(self, intent) -> str:
        """根据意图选择最佳 Agent 模板"""
        if not intent:
            return "coordinator"

        template_map = {
            "task_manage": "coordinator",
            "file_operation": "code_executor",
            "search": "research",
            "code": "code_executor",
            "network": "device_controller",
            "ocr": "research",
            "device_control": "device_controller",
        }
        return template_map.get(intent.intent, "coordinator")

    # ========================================================================
    # handle_tool_call — MCP / Skill 工具调用
    # ========================================================================

    async def handle_tool_call(self, intent) -> dict:
        """MCP / Skill 工具调用

        Args:
            intent: 解析后的意图 (ParsedIntent)

        Returns:
            工具执行结果 dict
        """
        command = intent.command if intent else ""
        params = intent.params if intent else {}
        tool_name = params.get("tool_name", "")
        tool_args = params.get("arguments", params)

        # 尝试 MCP 工具调用
        mcp_result = await self._try_mcp_tool(tool_name, tool_args)
        if mcp_result is not None:
            return mcp_result

        # 尝试 Skill 调用
        skill_result = await self._try_skill_execute(command, params)
        if skill_result is not None:
            return skill_result

        # 两者都不可用，降级到 Agent 处理
        return {
            "success": False,
            "response": (
                f"未找到匹配的 MCP 工具或 Skill 来处理命令 '{command}'。"
                "请确认工具已加载或使用其他方式处理。"
            ),
            "metadata": {"command": command, "params": params},
        }

    async def _try_mcp_tool(self, tool_name: str, arguments: dict) -> Optional[dict]:
        """尝试通过 MCP 调用工具"""
        try:
            from core.mcp_loader import mcp_loader

            servers = mcp_loader.list_servers()
            if not servers:
                return None

            # 遍历所有 MCP 服务器查找匹配的工具
            for server_info in servers:
                server_id = server_info.get("id", "")
                if server_info.get("status") != "running":
                    continue

                tools = await mcp_loader.list_tools(server_id)
                for tool in tools:
                    if tool.get("name") == tool_name:
                        result = await mcp_loader.call_tool(
                            server_id, tool_name, arguments
                        )
                        return {
                            "success": result.get("success", False),
                            "response": str(result.get("result", result.get("error", "MCP 工具调用完成"))),
                            "metadata": {
                                "source": "mcp",
                                "server_id": server_id,
                                "tool_name": tool_name,
                                "result": result,
                            },
                        }

        except ImportError:
            logger.debug("MCP Loader 不可用")
        except Exception as e:
            logger.warning(f"MCP 工具调用失败: {e}")

        return None

    async def _try_skill_execute(self, skill_name: str, params: dict) -> Optional[dict]:
        """尝试通过 SkillLoader 执行技能"""
        try:
            from core.skill_loader import skill_loader

            skills = skill_loader.list_skills()
            if not skills:
                return None

            # 查找匹配的技能
            target_skill = None
            for skill_info in skills:
                if (
                    skill_info.get("name") == skill_name
                    or skill_info.get("id") == skill_name
                ):
                    target_skill = skill_info
                    break

            if not target_skill:
                # 搜索匹配
                search_results = skill_loader.search(skill_name)
                if search_results:
                    target_skill = search_results[0]

            if target_skill:
                skill_id = target_skill.get("id", "")
                # 过滤掉非技能参数
                exec_params = {
                    k: v
                    for k, v in params.items()
                    if k not in ("tool_name", "arguments", "instruction", "message")
                }
                result = await skill_loader.execute(skill_id, **exec_params)
                return {
                    "success": result.get("success", False),
                    "response": str(result.get("result", result.get("error", "技能执行完成"))),
                    "metadata": {
                        "source": "skill",
                        "skill_id": skill_id,
                        "skill_name": target_skill.get("name", ""),
                        "result": result,
                    },
                }

        except ImportError:
            logger.debug("Skill Loader 不可用")
        except Exception as e:
            logger.warning(f"Skill 执行失败: {e}")

        return None

    # ========================================================================
    # get_status — 系统状态
    # ========================================================================

    async def get_status(self) -> dict:
        """系统状态概览 — 聚合所有子模块状态

        Returns:
            系统状态 dict
        """
        status = {
            "openclawd": {
                "initialized": self._initialized,
                "request_count": self._request_count,
                "error_count": self._error_count,
                "uptime_seconds": int(time.time() - self._start_time),
                "active_sessions": len(self._session_memory),
            },
        }

        # LLM Router 状态
        try:
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
            router_status = router.get_status()
            status["llm_router"] = {
                "available": router.is_available(),
                "total_providers": router_status.get("total_providers", 0),
                "healthy_providers": router_status.get("healthy_providers", 0),
                "total_calls": router_status.get("total_calls", 0),
                "providers": list(router_status.get("providers", {}).keys()),
            }
        except Exception as e:
            status["llm_router"] = {"available": False, "error": str(e)}

        # Agent Factory 状态
        try:
            from core.agent_factory import get_agent_factory

            factory = get_agent_factory()
            factory_status = factory.get_status()
            status["agent_factory"] = {
                "total_agents": factory_status.get("total_agents", 0),
                "by_state": factory_status.get("by_state", {}),
                "templates": factory_status.get("templates", []),
            }
        except Exception as e:
            status["agent_factory"] = {"total_agents": 0, "error": str(e)}

        # MCP 状态
        try:
            from core.mcp_loader import mcp_loader

            servers = mcp_loader.list_servers()
            running = sum(1 for s in servers if s.get("status") == "running")
            total_tools = sum(s.get("tools_count", 0) for s in servers)
            status["mcp"] = {
                "server_count": len(servers),
                "running_count": running,
                "total_tools": total_tools,
            }
        except Exception as e:
            status["mcp"] = {"server_count": 0, "error": str(e)}

        # Skill 状态
        try:
            from core.skill_loader import skill_loader

            stats = skill_loader.get_stats()
            status["skills"] = {
                "loaded_skills": stats.get("loaded_skills", 0),
                "total_executions": stats.get("total_executions", 0),
                "successful_executions": stats.get("successful_executions", 0),
                "failed_executions": stats.get("failed_executions", 0),
            }
        except Exception as e:
            status["skills"] = {"loaded_skills": 0, "error": str(e)}

        # 意图解析器状态
        try:
            from core.ai_intent import get_intent_parser

            parser = get_intent_parser()
            status["intent_parser"] = {
                "cache_size": len(parser._parse_cache),
                "supported_intents": list(parser.RULE_PATTERNS.keys()),
            }
        except Exception as e:
            status["intent_parser"] = {"error": str(e)}

        return status

    # ========================================================================
    # 会话记忆管理
    # ========================================================================

    async def _record_turn(self, session_id: str, role: str, content: str):
        """记录对话轮次到内部会话记忆"""
        if session_id not in self._session_memory:
            self._session_memory[session_id] = []

        self._session_memory[session_id].append({
            "role": role,
            "content": content,
        })

        # 限制会话长度
        if len(self._session_memory[session_id]) > 40:
            self._session_memory[session_id] = self._session_memory[session_id][-20:]

        # 同步到 ConversationMemory (如果可用)
        try:
            from core.ai_intent import get_conversation_memory

            memory = get_conversation_memory()
            await memory.add_turn(session_id, role, content)
        except Exception:
            pass

    async def clear_session(self, session_id: str):
        """清除会话记忆"""
        self._session_memory.pop(session_id, None)
        try:
            from core.ai_intent import get_conversation_memory

            memory = get_conversation_memory()
            await memory.clear_session(session_id)
        except Exception:
            pass

    def get_session_history(self, session_id: str, max_turns: int = 20) -> List[Dict]:
        """获取会话历史"""
        history = self._session_memory.get(session_id, [])
        return history[-max_turns:]

    def list_sessions(self) -> List[Dict]:
        """列出所有活跃会话"""
        sessions = []
        for sid, turns in self._session_memory.items():
            sessions.append({
                "session_id": sid,
                "turn_count": len(turns),
                "last_message": turns[-1]["content"][:100] if turns else "",
            })
        return sessions

    # ========================================================================
    # 设备感知 — PR86: 设备注册可见性，新设备自动进入 capability bus
    # ========================================================================

    def sync_device_capabilities(self) -> int:
        """将 UnifiedDeviceManager 中的设备同步为 CapabilityRegistry 条目。

        Priority A: 使用 UnifiedDeviceManager 作为 SSOT，取代旧 DeviceRegistry。
        包括低层设备能力和高层自治能力（metadata 声明）。
        返回同步的能力条目数量。
        """
        _AUTONOMOUS_CAPABILITY_KEYS = (
            "goal_execution_enabled",
            "local_task_planning",
            "local_ui_reasoning",
            "cross_device_coordination",
            "parallel_execution_enabled",
            "local_model_enabled",
        )
        count = 0
        try:
            from core.unified.device_manager import get_unified_device_manager
            from core.agent.capability_registry import CapabilityRegistry, CapabilityItem

            reg = CapabilityRegistry.get_instance()
            udm = get_unified_device_manager()
            devices = udm.list_devices()

            if not devices:
                return 0

            for device in devices:
                device_id = device.device_id
                d_name = device.device_name or device_id
                d_type = str(device.device_type)

                # 低层设备能力
                for cap in (device.capabilities or []):
                    cap_name = cap if isinstance(cap, str) else str(cap)
                    key = f"gateway__{device_id}__{cap_name}"
                    reg.register(CapabilityItem(
                        name=key,
                        description=f"[Gateway:{d_name}({d_type})] 设备能力: {cap_name}",
                        source="gateway",
                        source_id=device_id,
                        available=True,
                        metadata={"device_name": d_name, "device_type": d_type},
                    ))
                    count += 1

                # Priority C: 高层自治能力（从 metadata 声明）
                meta = device.metadata or {}
                for cap_key in _AUTONOMOUS_CAPABILITY_KEYS:
                    if meta.get(cap_key):
                        key = f"autonomous__{device_id}__{cap_key}"
                        reg.register(CapabilityItem(
                            name=key,
                            description=f"[Autonomous:{d_name}] {cap_key}",
                            source="autonomous",
                            source_id=device_id,
                            available=True,
                            metadata={
                                "device_id": device_id,
                                "device_name": d_name,
                                "device_type": d_type,
                                "capability_key": cap_key,
                            },
                        ))
                        count += 1

            if count:
                logger.info(
                    "OpenClawd: 已从 UnifiedDeviceManager 同步 %d 个设备能力到 CapabilityRegistry",
                    count,
                )
        except Exception as e:
            logger.debug("sync_device_capabilities 失败: %s", e)
        return count

    # ========================================================================
    # 网关统一命令路径 — PR86: OpenClawd -> command_router -> gateway -> device -> result
    # ========================================================================

    async def send_gateway_command(
        self,
        device_id: str,
        command: str,
        payload: Optional[Dict] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> Dict:
        """统一网关命令路径（带 trace ID）。

        链路：OpenClawd → command_router → gateway/device_router → device → result
        每次调用生成唯一 command_id，所有日志均含 trace 字段。
        """
        command_id = uuid.uuid4().hex
        task_id = task_id or uuid.uuid4().hex
        t0 = time.monotonic()
        logger.info(
            "OpenClawd.send_gateway_command | command_id=%s task_id=%s "
            "session_id=%s device_id=%s command=%s",
            command_id, task_id, session_id, device_id, command,
        )

        result: Dict = {
            "success": False,
            "command_id": command_id,
            "task_id": task_id,
            "session_id": session_id,
            "device_id": device_id,
            "command": command,
        }

        # 尝试通过 command_router 发送
        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            cr_result = await cr.route_command(
                device_id=device_id,
                command=command,
                payload=payload or {},
                command_id=command_id,
                task_id=task_id,
            )
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": cr_result.get("success", False),
                "response": cr_result.get("response") or cr_result.get("result"),
                "latency_ms": round(latency_ms, 1),
                "via": "command_router",
            })
            logger.info(
                "OpenClawd.send_gateway_command done | command_id=%s success=%s latency=%.1fms",
                command_id, result["success"], latency_ms,
            )
            return result
        except Exception as e:
            logger.debug("command_router 不可用，尝试 DeviceOrchestrator: %s", e)

        # 降级：DeviceOrchestrator
        try:
            from core.device_orchestrator import get_device_orchestrator
            orch = get_device_orchestrator()
            orch_result = await orch.execute_command(
                device_id=device_id,
                command=command,
                params=payload or {},
            )
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": orch_result.get("success", False) if isinstance(orch_result, dict) else bool(orch_result),
                "response": orch_result.get("message", "") if isinstance(orch_result, dict) else str(orch_result),
                "latency_ms": round(latency_ms, 1),
                "via": "device_orchestrator",
            })
            return result
        except Exception as e:
            logger.debug("DeviceOrchestrator 不可用，尝试 WebSocket: %s", e)

        # 最终降级：WebSocket
        try:
            from core.routes._shared import connection_manager
            sent = await connection_manager.send_to_device(
                device_id,
                {
                    "type": "command",
                    "command": command,
                    "payload": payload or {},
                    "command_id": command_id,
                    "task_id": task_id,
                },
            )
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": sent,
                "response": f"命令已通过 WebSocket 发送到 {device_id}" if sent else f"设备 {device_id} 未连接",
                "latency_ms": round(latency_ms, 1),
                "via": "websocket",
            })
        except Exception as e:
            latency_ms = (time.monotonic() - t0) * 1000
            result.update({
                "success": False,
                "response": f"无法向设备 {device_id} 发送命令: {e}",
                "latency_ms": round(latency_ms, 1),
                "error": str(e),
            })

        logger.info(
            "OpenClawd.send_gateway_command done | command_id=%s success=%s via=%s latency=%.1fms",
            command_id, result.get("success"), result.get("via", "none"),
            result.get("latency_ms", 0),
        )
        return result


# ============================================================================
# 单例
# ============================================================================

_openclawd_instance: Optional[OpenClawd] = None


def get_openclawd() -> OpenClawd:
    """获取 OpenClawd 全局单例"""
    global _openclawd_instance
    if _openclawd_instance is None:
        _openclawd_instance = OpenClawd()
    return _openclawd_instance
