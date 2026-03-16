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
import socket
import time
import uuid
from typing import Any, Dict, List, Optional, TYPE_CHECKING

logger = logging.getLogger("Galaxy.OpenClawd")

# ============================================================================
# Helper: local-device detection (PR155)
# ============================================================================

_LOCAL_DEVICE_PREFIXES = ("local", "openclawd", "server")
_LOCAL_HOSTNAME = socket.gethostname().lower()


def _is_local_device(device_id: str) -> bool:
    """Return True when *device_id* refers to the local host / process.

    A device is considered local when its ID:
      - starts with a known local prefix (``local``, ``openclawd``, ``server``), or
      - contains the current hostname, or
      - is empty / None.
    """
    if not device_id:
        return True
    dl = device_id.lower()
    if any(dl.startswith(p) for p in _LOCAL_DEVICE_PREFIXES):
        return True
    if _LOCAL_HOSTNAME and _LOCAL_HOSTNAME in dl:
        return True
    return False


# ============================================================================
# Parallel-group state machine
# ============================================================================

class _SubtaskStatus(str, enum.Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    SUCCESS   = "success"
    FAILED    = "failed"
    TIMEOUT   = "timeout"
    CANCELLED = "cancelled"


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
    summary_status: str          # "success" | "partial" | "failed" | "cancelled"
    succeeded:      int
    failed:         int
    cancelled:      int
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

    def mark_cancelled(self, group_id: str, task_id: str) -> None:
        """Mark a subtask as cancelled (idempotent — safe to call multiple times)."""
        entry = self._get_entry(group_id, task_id)
        if entry and entry.status != _SubtaskStatus.CANCELLED:
            entry.status = _SubtaskStatus.CANCELLED
            entry.finished_at = time.monotonic()
            entry.error = "cancelled"

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

        succeeded  = sum(1 for e in entries if e.status == _SubtaskStatus.SUCCESS)
        cancelled  = sum(1 for e in entries if e.status == _SubtaskStatus.CANCELLED)
        failed     = len(entries) - succeeded - cancelled  # only actual failures/timeouts

        if succeeded == len(entries):
            summary = "success"
        elif succeeded > 0:
            summary = "partial"
        elif cancelled == len(entries):
            summary = "cancelled"
        else:
            summary = "failed"

        return ParallelResult(
            group_id=group_id,
            device_results=device_results,
            summary_status=summary,
            succeeded=succeeded,
            failed=failed,
            cancelled=cancelled,
            total=len(entries),
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_entry(self, group_id: str, task_id: str) -> Optional[_SubtaskEntry]:
        return self._groups.get(group_id, {}).get(task_id)


# 当能力总线和直接加载路径均无法提供 Skill 参数 schema 时使用的默认值
_DEFAULT_SKILL_SCHEMA: Dict = {
    "type": "object",
    "properties": {
        "input": {"type": "string", "description": "输入参数"}
    },
}

# GitHub 插件内置工具定义（供 LLM function calling 使用）
_GITHUB_BUILTIN_TOOLS: List[Dict] = [
    {
        "type": "function",
        "function": {
            "name": "github__install",
            "description": (
                "从 GitHub 仓库安装 MCP 工具或 Skill 插件，安装后可立即在当前会话中调用。"
                "GITHUB_TOKEN 须在环境变量或 Dashboard 中配置，勿在对话中提供 Token。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "GitHub HTTPS 仓库 URL，例如 https://github.com/owner/repo 或 https://github.com/owner/repo/tree/main",
                    },
                    "ref": {
                        "type": "string",
                        "description": "指定分支、Tag 或 Commit SHA（可选，覆盖 URL 中的分支）",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["mcp", "skill"],
                        "description": "插件类型：mcp（MCP 工具服务器）或 skill（Skill 技能）；不填则自动检测",
                    },
                    "dry_run": {
                        "type": "boolean",
                        "description": "设为 true 时只验证 URL 格式，不实际安装",
                    },
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__uninstall",
            "description": "卸载通过 github__install 安装的 MCP 工具或 Skill 插件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "插件名称（与安装时 manifest 中的 name 字段一致）",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__list",
            "description": "列出当前已安装的所有 GitHub 来源的 MCP 工具和 Skill 插件及其安装信息。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "github__status",
            "description": "查看 GitHub 插件安装器状态，包括 GITHUB_TOKEN 是否已配置、安装目录、已安装数量等。",
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


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

    # ── Timeout / Cancel configuration ──────────────────────────────────────
    # Timeout for a single goal_execution dispatch (seconds). Override via
    # subclass or instance attribute for test / production tuning.
    GOAL_EXECUTION_TIMEOUT: float = 60.0
    # Timeout for each parallel_subtask dispatch (seconds).
    PARALLEL_SUBTASK_TIMEOUT: float = 60.0
    # Maximum number of dynamically discovered node tools to expose to LLM.
    # LLM function calling APIs typically recommend ≤ 128 tools to avoid
    # context overflow; keep this value in sync with that constraint.
    NODE_DYNAMIC_TOOL_LIMIT: int = 128

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
        # Cancel registry — set of task_ids or group_ids that have been cancelled.
        # Using a set makes repeated cancel() calls idempotent.
        # task_ids follow the pattern "goal_<hex12>" or "<group_id>_sub<idx>";
        # group_ids are short hex strings (uuid4().hex[:8]).  The distinct
        # prefixes prevent accidental collisions between the two namespaces.
        self._cancel_registry: set = set()

        # Phase 9: 工具权限检查器
        self._tool_permission_checker = None
        try:
            from core.tool_permissions import get_tool_permission_checker
            self._tool_permission_checker = get_tool_permission_checker()
        except Exception as e:
            logger.warning(f"工具权限检查器不可用，所有工具将无限制: {e}")

        logger.info("OpenClawd 星枢核心智能体初始化")

    # ========================================================================
    # Control Plane Phase 2 helpers
    # ========================================================================

    def _emit_audit(
        self,
        event_type,
        *,
        trace_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        device_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        message: str = "",
        payload: Optional[Dict] = None,
    ) -> Optional[str]:
        """Emit a :class:`~core.control_plane.TraceEvent` to the shared ledger.

        Silently swallows all exceptions so a ledger failure never breaks
        the main execution path.  Returns the new ``event_id`` or ``None``.
        """
        try:
            from core.control_plane._globals import get_audit_ledger
            from core.control_plane.audit_ledger import Severity
            return get_audit_ledger().append(
                event_type,
                severity=Severity.INFO,
                source="openclawd",
                message=message,
                trace_id=trace_id,
                task_id=task_id,
                session_id=session_id,
                device_id=device_id,
                agent_id=agent_id,
                payload=payload or {},
            )
        except Exception:
            return None

    def _select_device_via_scheduler(
        self,
        required_capabilities: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Use the smart scheduler to pick the best available device.

        Reads the device list from the shared ``connection_manager`` and
        applies :class:`~core.control_plane.DeviceScoringEngine` to return
        the highest-scoring eligible device ID, or ``None`` if no suitable
        device is found.

        Parameters
        ----------
        required_capabilities:
            List of capability strings the selected device must support.
        """
        try:
            from core.control_plane._globals import get_scoring_engine, get_audit_ledger
            from core.control_plane.smart_scheduler import DeviceScoreInput, DeviceStatus as SchedDeviceStatus
            from core.control_plane.audit_ledger import EventType, Severity
            from core.routes._shared import connection_manager

            all_devices = connection_manager.get_all_devices()
            if not all_devices:
                return None

            candidates = []
            for did, info in all_devices.items():
                raw_status = info.get("status", "offline")
                if raw_status not in (SchedDeviceStatus.ONLINE, "online", "connected"):
                    continue
                caps = info.get("capabilities", [])
                if isinstance(caps, list):
                    cap_names = [
                        c if isinstance(c, str) else (c.get("name", "") if isinstance(c, dict) else str(c))
                        for c in caps
                    ]
                else:
                    cap_names = []
                candidates.append(
                    DeviceScoreInput(
                        device_id=did,
                        status=SchedDeviceStatus.ONLINE,
                        ping_latency_ms=float(info.get("ping_ms", 0.0)),
                        load_pct=float(info.get("load_pct", 0.0)),
                        capabilities=cap_names,
                    )
                )

            if not candidates:
                return None

            engine = get_scoring_engine()
            best = engine.select_best_device(candidates, required_capabilities or [])
            if best is not None:
                # Record scheduler decision in audit ledger
                try:
                    get_audit_ledger().append(
                        EventType.SCHEDULER_DECISION,
                        severity=Severity.INFO,
                        source="openclawd.scheduler",
                        message=f"Auto-selected device {best.device_id} (score={best.total:.3f})",
                        payload={
                            "selected_device_id": best.device_id,
                            "score": best.total,
                            "required_capabilities": required_capabilities or [],
                            "candidates_count": len(candidates),
                        },
                    )
                except Exception:
                    pass
                return best.device_id
        except Exception as e:
            logger.debug("_select_device_via_scheduler failed (non-fatal): %s", e)
        return None

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
    # Cancel / Abort API
    # ========================================================================

    def cancel_task(self, task_id: str) -> bool:
        """Mark a task (by task_id) as cancelled.

        Idempotent — calling multiple times for the same task_id is safe.

        Returns:
            True  if the task_id was newly added to the cancel registry.
            False if it was already cancelled (idempotent no-op).
        """
        if task_id in self._cancel_registry:
            logger.debug("cancel_task: %s already cancelled (idempotent)", task_id)
            return False
        self._cancel_registry.add(task_id)
        logger.info("cancel_task: %s added to cancel registry", task_id)
        return True

    def cancel_group(self, group_id: str) -> bool:
        """Mark an entire parallel group (by group_id) as cancelled.

        Adds the group_id itself to the cancel registry so that any
        in-flight subtask that checks ``_is_cancelled(entry)`` will abort.

        Idempotent — safe to call multiple times.

        Returns:
            True  if the group_id was newly added to the cancel registry.
            False if it was already cancelled.
        """
        if group_id in self._cancel_registry:
            logger.debug("cancel_group: %s already cancelled (idempotent)", group_id)
            return False
        self._cancel_registry.add(group_id)
        logger.info("cancel_group: %s added to cancel registry", group_id)
        return True

    def _is_cancelled(self, task_id: str, group_id: Optional[str] = None) -> bool:
        """Return True if task_id or its group_id is in the cancel registry."""
        if task_id in self._cancel_registry:
            return True
        if group_id and group_id in self._cancel_registry:
            return True
        return False

    # ========================================================================
    # 主入口
    # ========================================================================

    async def process(
        self,
        message: str,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[List[Dict]] = None,
        required_capabilities: Optional[List[str]] = None,
        multimodal_context: Optional[Any] = None,
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
            required_capabilities: Phase 2 scheduler hint — list of device capabilities required
            multimodal_context: Multi-modal context bundle (PR 1).  When present,
                ``multimodal_context.images`` carries base64-encoded image payloads
                that are forwarded to the model router.  Text-only requests leave
                this as ``None`` and existing behaviour is fully preserved.

        Returns:
            统一响应 dict: {success, response, intent, metadata}
        """
        self._ensure_initialized()
        self._request_count += 1
        t0 = time.monotonic()
        request_id = uuid.uuid4().hex
        # trace_id is the stable end-to-end identifier for this request.
        # It equals request_id at the top level and is threaded through all
        # internal dispatch hops so that every lifecycle log entry can be
        # correlated back to the originating request.
        trace_id = request_id

        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"

        # ── Multi-modal context: log presence and prepare serialized form ────
        # ``multimodal_context`` is forwarded as-is through the pipeline and
        # included in metadata so the model router can consume it in future PRs.
        # Text-only requests leave this as None and are unaffected.
        _mm_context_dict: Optional[Dict[str, Any]] = None
        if multimodal_context is not None:
            try:
                _mm_context_dict = multimodal_context.model_dump()
                _img_count = len(_mm_context_dict.get("images", []))
                _aud_count = len(_mm_context_dict.get("audio", []))
                logger.debug(
                    "OpenClawd process: multimodal_context present — images=%d audio=%d",
                    _img_count,
                    _aud_count,
                )
            except Exception as _mm_err:
                logger.debug(
                    "Failed to serialize multimodal_context (type=%s): %s",
                    type(multimodal_context).__name__,
                    _mm_err,
                )

        try:
            from core.task_logger import emit_task_log
            emit_task_log(
                "task_received",
                trace_id=trace_id,
                session_id=session_id,
                device_id=device_id,
                status="received",
            )
        except Exception:
            pass

        # ── Audit ledger: TASK_CREATED ────────────────────────────────────────
        task_id_for_trace = f"task_{uuid.uuid4().hex[:12]}"
        try:
            from core.control_plane.audit_ledger import EventType as _EvType
            self._emit_audit(
                _EvType.TASK_CREATED,
                trace_id=trace_id,
                task_id=task_id_for_trace,
                session_id=session_id,
                device_id=device_id,
                message="Intent received",
                payload={"message_preview": message[:120]},
            )
        except Exception:
            pass

        # 同步新设备能力（确保 OpenClawd 始终感知最新设备）
        try:
            self.sync_device_capabilities()
        except Exception:
            pass

        try:
            # ── Audit ledger: TASK_STARTED ────────────────────────────────────
            try:
                from core.control_plane.audit_ledger import EventType as _EvType2
                self._emit_audit(
                    _EvType2.TASK_STARTED,
                    trace_id=trace_id,
                    task_id=task_id_for_trace,
                    session_id=session_id,
                    device_id=device_id,
                    message="Processing started",
                )
            except Exception:
                pass

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
                    # ── Audit ledger: TASK_COMPLETED ──────────────────────────
                    try:
                        from core.control_plane.audit_ledger import EventType as _EvType3
                        _ev = _EvType3.TASK_COMPLETED if kernel_result.success else _EvType3.TASK_FAILED
                        self._emit_audit(
                            _ev,
                            trace_id=trace_id,
                            task_id=task_id_for_trace,
                            session_id=session_id,
                            device_id=device_id,
                            message="AgentKernel completed",
                            payload={"latency_ms": round(latency_ms, 1), "handler": "agent_kernel"},
                        )
                    except Exception:
                        pass
                    return {
                        "success": kernel_result.success,
                        "response": kernel_result.reply,
                        "intent": kernel_result.intent.raw_intent,
                        "error": kernel_result.error,
                        "trace_id": trace_id,
                        "metadata": {
                            "request_id": request_id,
                            "trace_id": trace_id,
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
                            "multimodal_context": _mm_context_dict,
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

            # Phase 2: if no device_id provided but required_capabilities given, auto-select
            effective_device_id = device_id
            if not effective_device_id and required_capabilities and intent_type in ("device_control", "task_manage"):
                selected = self._select_device_via_scheduler(required_capabilities)
                if selected:
                    logger.info(
                        "process: scheduler auto-selected device=%s for caps=%s",
                        selected, required_capabilities,
                    )
                    effective_device_id = selected

            result = await handler(
                message=message,
                intent=parsed_intent,
                device_id=effective_device_id,
                session_id=session_id,
                trace_id=trace_id,
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

            # ── Audit ledger: TASK_COMPLETED ──────────────────────────────────
            try:
                from core.control_plane.audit_ledger import EventType as _EvType4
                _success_flag = result.get("success", True)
                self._emit_audit(
                    _EvType4.TASK_COMPLETED if _success_flag else _EvType4.TASK_FAILED,
                    trace_id=trace_id,
                    task_id=task_id_for_trace,
                    session_id=session_id,
                    device_id=device_id,
                    message="Handler completed",
                    payload={"latency_ms": round(latency_ms, 1), "handler": handler_name, "intent": intent_type},
                )
            except Exception:
                pass

            return {
                "success": result.get("success", True),
                "response": response_text,
                "intent": intent_type,
                "trace_id": trace_id,
                "metadata": {
                    "request_id": request_id,
                    "trace_id": trace_id,
                    "session_id": session_id,
                    "device_id": device_id,
                    "latency_ms": round(latency_ms, 1),
                    "confidence": parsed_intent.confidence if parsed_intent else 0.0,
                    "suggestions": parsed_intent.suggestions if parsed_intent else [],
                    "handler": handler_name,
                    **provider_info,
                    **(result.get("metadata", {})),
                    "multimodal_context": _mm_context_dict,
                },
            }

        except Exception as e:
            self._error_count += 1
            latency_ms = (time.monotonic() - t0) * 1000
            logger.error(f"OpenClawd.process 失败: {e}", exc_info=True)
            # ── Audit ledger: TASK_FAILED ─────────────────────────────────────
            try:
                from core.control_plane.audit_ledger import EventType as _EvType5, Severity as _Sev5
                from core.control_plane._globals import get_audit_ledger
                get_audit_ledger().append(
                    _EvType5.TASK_FAILED,
                    severity=_Sev5.ERROR,
                    source="openclawd",
                    message=f"process() raised: {e}",
                    trace_id=trace_id,
                    task_id=task_id_for_trace,
                    session_id=session_id,
                    device_id=device_id,
                    payload={"error": str(e)},
                )
            except Exception:
                pass
            return {
                "success": False,
                "response": f"处理请求时发生错误: {str(e)}",
                "intent": "error",
                "trace_id": trace_id,
                "metadata": {
                    "request_id": request_id,
                    "trace_id": trace_id,
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
        trace_id: Optional[str] = None,
    ) -> dict:
        """纯聊天分派"""
        return await self.handle_chat(message, session_id or "default")

    async def _dispatch_device(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """设备操控分派 — 经由 send_gateway_command → CommandRouter → trace"""
        if not device_id:
            # Phase 2: try to auto-select a device via the smart scheduler
            required_caps = getattr(intent, "required_capabilities", None) if intent else None
            selected = self._select_device_via_scheduler(required_caps)
            if selected:
                logger.info(
                    "_dispatch_device: no device_id provided; scheduler selected %s", selected
                )
                device_id = selected
            else:
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
        trace_id: Optional[str] = None,
    ) -> dict:
        """Agent 任务分派（PR155: 支持远程设备分发；PR154: trace 贯穿）

        当 ``intent.target_device`` 或环境指定的设备 ID 表明任务应在远程设备上
        执行时，优先走 :meth:`_dispatch_remote_agent`；否则保持本地执行。
        """
        # PR155: 检测远程分发条件
        target_device = None
        if intent is not None:
            target_device = getattr(intent, "target_device", None)
        # 也接受外部通过 device_id 传入的远端设备
        effective_target = target_device or device_id

        # 仅当明确指定了非本地设备时走远程路径
        if effective_target and not _is_local_device(effective_target):
            return await self._dispatch_remote_agent(
                message=message,
                intent=intent,
                device_id=effective_target,
                session_id=session_id,
                trace_id=trace_id,
            )

        return await self.handle_agent_task(
            message, intent,
            device_id=device_id,
            session_id=session_id,
            trace_id=trace_id,
        )

    # ========================================================================
    # _dispatch_remote_agent — PR155: 远程 Agent 分发
    # ========================================================================

    async def _dispatch_remote_agent(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """将 Agent 任务通过 CommandRouter 分发到远程设备执行（PR155）。

        PR-2：在入口立即构造 TaskEnvelope，统一内部路由格式。
        链路：OpenClawd → TaskEnvelope → CommandRouter.dispatch_agent_remote →
              gateway/WS → device agent_execute handler → result backflow

        如果设备离线或 CommandRouter 返回错误，自动降级到本地执行并在
        返回值中标注 ``remote_fallback=True``。

        Parameters
        ----------
        message:
            用户原始指令（透传给远程设备 Agent）。
        intent:
            已解析的意图对象（可为 None）。
        device_id:
            目标设备 ID。
        session_id / trace_id:
            跟踪字段，贯穿整条链路。

        Returns
        -------
        dict
            含 ``success``、``response``、``metadata``（agent_id / task_id /
            trace_id / device_id / remote_dispatch）的标准响应。
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        agent_id = f"remote_agent_{uuid.uuid4().hex[:8]}"
        agent_template = (
            getattr(intent, "intent", None) or "coordinator"
        )

        # PR-2: construct TaskEnvelope immediately at entry for unified internal routing.
        try:
            from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
            _remote_envelope = _TaskEnvelope(
                task_id=task_id,
                trace_id=trace_id,
                source="openclawd._dispatch_remote_agent",
                targets=[device_id] if device_id else [],
                tool_name="agent_remote",
                args={
                    "message": message,
                    "agent_template": agent_template,
                    "session_id": session_id or "",
                },
                metadata={
                    "agent_id": agent_id,
                    "device_id": device_id or "",
                    "session_id": session_id or "",
                },
            )
            logger.debug(
                "OpenClawd._dispatch_remote_agent envelope | task_id=%s trace_id=%s agent_id=%s",
                _remote_envelope.task_id,
                _remote_envelope.trace_id,
                agent_id,
            )
        except Exception as _env_err:
            logger.debug("_dispatch_remote_agent: TaskEnvelope construction skipped — %s", _env_err)

        logger.info(
            "OpenClawd._dispatch_remote_agent | trace_id=%s task_id=%s "
            "agent_id=%s device_id=%s template=%s",
            trace_id, task_id, agent_id, device_id, agent_template,
        )

        try:
            from core.command_router import get_command_router
            cr = get_command_router()
            cr_result = await cr.dispatch_agent_remote(
                device_id=device_id,
                agent_id=agent_id,
                agent_template=agent_template,
                task=message,
                session_id=session_id or "",
                trace_id=trace_id,
                task_id=task_id,
                context={
                    "intent": getattr(intent, "intent", "") if intent else "",
                    "params": getattr(intent, "params", {}) if intent else {},
                },
            )
        except Exception as cr_exc:
            logger.warning(
                "OpenClawd._dispatch_remote_agent: CommandRouter 不可用，降级本地 | "
                "trace_id=%s error=%s",
                trace_id, cr_exc,
            )
            # Fallback: local execution
            local_result = await self.handle_agent_task(
                message, intent,
                device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
            )
            local_result.setdefault("metadata", {})
            local_result["metadata"]["remote_fallback"] = True
            local_result["metadata"]["fallback_reason"] = str(cr_exc)
            return local_result

        remote_success = cr_result.get("success", False)
        remote_error_code = cr_result.get("error_code")

        # Fallback when device offline / timeout / disconnect
        if not remote_success and remote_error_code in (
            "DEVICE_OFFLINE",
            "DEVICE_NOT_FOUND",
            "COMMAND_TIMEOUT",
            "DISCONNECT",
        ):
            logger.warning(
                "OpenClawd._dispatch_remote_agent: 远程失败(%s)，降级本地执行 | "
                "trace_id=%s device_id=%s",
                remote_error_code, trace_id, device_id,
            )
            local_result = await self.handle_agent_task(
                message, intent,
                device_id=device_id,
                session_id=session_id,
                trace_id=trace_id,
            )
            local_result.setdefault("metadata", {})
            local_result["metadata"]["remote_fallback"] = True
            local_result["metadata"]["fallback_reason"] = remote_error_code
            local_result["metadata"]["remote_error"] = cr_result.get("error_message", "")
            return local_result

        # Remote execution returned a structured result
        raw_result = cr_result.get("result") or {}
        if isinstance(raw_result, str):
            response_text = raw_result
        elif isinstance(raw_result, dict):
            response_text = raw_result.get("response") or raw_result.get("output") or str(raw_result)
        else:
            response_text = str(raw_result) if raw_result else "远程 Agent 任务已完成"

        # PR155: 结果回流到 TaskMemory
        try:
            from core.openclawd_memory_backflow import store_task_result
            await store_task_result(
                task_id=task_id,
                device_id=device_id or "remote",
                route_mode="remote_agent",
                result={
                    "status": "completed" if remote_success else "error",
                    "task_type": "agent_execute",
                    "task_description": message[:200],
                    "result_summary": response_text[:200],
                    "agent_id": agent_id,
                    "trace_id": trace_id,
                },
                session_id=session_id,
            )
        except Exception as _bf_err:
            logger.warning(
                "_dispatch_remote_agent: memory backflow 失败（非致命）: %s", _bf_err
            )

        return {
            "success": remote_success,
            "response": response_text if remote_success else (
                cr_result.get("error_message") or "远程 Agent 执行失败"
            ),
            "metadata": {
                "agent_id": agent_id,
                "agent_template": agent_template,
                "task_id": task_id,
                "trace_id": trace_id,
                "device_id": device_id or "",
                "session_id": session_id or "",
                "remote_dispatch": True,
                "latency_ms": cr_result.get("latency_ms", 0.0),
                "error_code": remote_error_code,
            },
        }

    async def _dispatch_tool(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """工具调用分派"""
        return await self.handle_tool_call(intent)

    async def _dispatch_status(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
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
        trace_id: Optional[str] = None,
    ) -> dict:
        """Priority D: 高层自治目标执行分派。

        流程：
          1. 优先从 CapabilityRegistry autonomous__* 条目选择支持
             goal_execution_enabled 的设备（Phase-3 SSOT）。
          2. 若 CapabilityRegistry 无结果，回退到 UnifiedDeviceManager 自治设备列表。
          3. 若仍无可用自治设备，降级到普通 _dispatch_agent 并记录明确消息。
        """
        from core.task_logger import emit_task_log

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

        # Generate a task_id so callers can cancel before / during execution
        task_id = f"goal_{uuid.uuid4().hex[:12]}"

        # ── Cancel check before dispatch ──────────────────────────────────
        if self._is_cancelled(task_id):
            logger.info("goal_execution: task %s cancelled before dispatch", task_id)
            emit_task_log(
                "task_cancelled",
                task_id=task_id,
                trace_id=trace_id,
                device_id=target_device_id,
                task_type="goal_execution",
                status="cancelled",
            )
            return {
                "success": False,
                "response": f"目标任务 '{goal}' 已被取消（取消发生在执行前）",
                "intent": "goal_execution",
                "task_id": task_id,
                "trace_id": trace_id,
                "cancelled": True,
            }

        emit_task_log(
            "task_dispatched",
            task_id=task_id,
            trace_id=trace_id,
            device_id=target_device_id,
            task_type="goal_execution",
            status="dispatched",
        )
        t_dispatch = time.monotonic()

        try:
            result = await _asyncio_module.wait_for(
                self.send_gateway_command(
                    device_id=target_device_id,
                    command="goal_execution",
                    payload={
                        "task_type": "goal_execution",
                        "goal": goal,
                        "task_id": task_id,
                        "trace_id": trace_id,
                        **params,
                    },
                    task_id=task_id,
                    session_id=session_id,
                ),
                timeout=self.GOAL_EXECUTION_TIMEOUT,
            )
        except _asyncio_module.TimeoutError:
            latency_ms = (time.monotonic() - t_dispatch) * 1000
            logger.warning(
                "goal_execution timed out after %.1fs | device=%s task_id=%s",
                self.GOAL_EXECUTION_TIMEOUT, target_device_id, task_id,
            )
            emit_task_log(
                "task_timeout",
                task_id=task_id,
                trace_id=trace_id,
                device_id=target_device_id,
                task_type="goal_execution",
                latency_ms=round(latency_ms, 1),
                status="timeout",
            )
            return {
                "success": False,
                "response": (
                    f"目标任务 '{goal}' 执行超时（超过 {self.GOAL_EXECUTION_TIMEOUT:.0f} 秒），"
                    "请稍后重试或检查设备状态。"
                ),
                "intent": "goal_execution",
                "task_id": task_id,
                "trace_id": trace_id,
                "timed_out": True,
            }

        latency_ms = (time.monotonic() - t_dispatch) * 1000
        if "response" not in result:
            result["response"] = (
                result.get("result")
                or f"目标任务 '{goal}' 已提交至设备 {target_device_id}"
            )
        result["intent"] = "goal_execution"
        result.setdefault("task_id", task_id)
        result.setdefault("trace_id", trace_id)
        success = result.get("success", False)
        logger.info(
            "goal_execution dispatched | device=%s success=%s",
            target_device_id,
            success,
        )
        emit_task_log(
            "task_completed" if success else "task_failed",
            task_id=task_id,
            trace_id=trace_id,
            device_id=target_device_id,
            task_type="goal_execution",
            latency_ms=round(latency_ms, 1),
            status="success" if success else "failed",
        )
        return result

    async def _dispatch_parallel_goal(
        self,
        message: str,
        intent=None,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
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
        from core.task_logger import emit_task_log

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

        t_parallel_start = time.monotonic()

        async def _execute_entry(entry: _SubtaskEntry) -> None:
            """Execute one subtask with retry/backoff, timeout, and cancel support."""
            while True:
                # ── Cancel check (before each attempt) ──────────────────────
                if self._is_cancelled(entry.task_id, entry.group_id):
                    logger.info(
                        "parallel_goal: subtask %d on device %s cancelled",
                        entry.subtask_index, entry.device_id,
                    )
                    tracker.mark_cancelled(entry.group_id, entry.task_id)
                    emit_task_log(
                        "task_cancelled",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        status="cancelled",
                    )
                    return

                tracker.mark_running(entry.group_id, entry.task_id)
                emit_task_log(
                    "task_dispatched",
                    task_id=entry.task_id,
                    trace_id=trace_id,
                    device_id=entry.device_id,
                    group_id=entry.group_id,
                    subtask_index=entry.subtask_index,
                    task_type="parallel_subtask",
                    status="dispatched",
                )
                t_sub = time.monotonic()
                try:
                    r = await _asyncio_module.wait_for(
                        self.send_gateway_command(
                            device_id=entry.device_id,
                            command="goal_execution",
                            payload={
                                "task_type": "parallel_subtask",
                                "goal": entry.subtask,
                                "parallel_group": entry.group_id,
                                "subtask_index": entry.subtask_index,
                                "trace_id": trace_id,
                            },
                            task_id=entry.task_id,
                            session_id=session_id,
                        ),
                        timeout=self.PARALLEL_SUBTASK_TIMEOUT,
                    )
                    sub_latency_ms = (time.monotonic() - t_sub) * 1000
                    # Propagate command_id / task_id / trace_id into result
                    r.setdefault("command_id", "")
                    r.setdefault("task_id", entry.task_id)
                    r.setdefault("trace_id", trace_id)
                    success = bool(r.get("success"))
                    tracker.mark_done(entry.group_id, entry.task_id, r, success=success)
                    emit_task_log(
                        "task_completed" if success else "task_failed",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        latency_ms=round(sub_latency_ms, 1),
                        status="success" if success else "failed",
                    )
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
                except _asyncio_module.TimeoutError:
                    sub_latency_ms = (time.monotonic() - t_sub) * 1000
                    logger.warning(
                        "parallel_goal: subtask %d on device %s timed out after %.1fs",
                        entry.subtask_index, entry.device_id, self.PARALLEL_SUBTASK_TIMEOUT,
                    )
                    tracker.mark_timeout(entry.group_id, entry.task_id)
                    emit_task_log(
                        "task_timeout",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        latency_ms=round(sub_latency_ms, 1),
                        status="timeout",
                    )
                    if tracker.needs_retry(entry.group_id, entry.task_id):
                        delay = tracker.backoff_delay(entry.group_id, entry.task_id)
                        tracker.increment_retry(entry.group_id, entry.task_id)
                        await _asyncio_module.sleep(delay)
                        continue
                    return
                except Exception as exc:
                    sub_latency_ms = (time.monotonic() - t_sub) * 1000
                    err_result = {
                        "success": False,
                        "response": str(exc),
                        "task_id": entry.task_id,
                        "trace_id": trace_id,
                        "device_id": entry.device_id,
                    }
                    tracker.mark_done(entry.group_id, entry.task_id, err_result, success=False)
                    emit_task_log(
                        "task_failed",
                        task_id=entry.task_id,
                        trace_id=trace_id,
                        device_id=entry.device_id,
                        group_id=entry.group_id,
                        subtask_index=entry.subtask_index,
                        task_type="parallel_subtask",
                        latency_ms=round(sub_latency_ms, 1),
                        status="failed",
                        error=str(exc),
                    )
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
        cancelled_count = parallel_result.cancelled
        parallel_latency_ms = (time.monotonic() - t_parallel_start) * 1000
        summary_text = (
            f"并行任务 '{goal}' 已分发至 {len(parallel_devices)} 台设备："
            f"{parallel_result.succeeded} 成功，"
            f"{parallel_result.failed} 失败，"
            f"{cancelled_count} 已取消。"
        )
        logger.info(
            "parallel_goal done | group=%s devices=%d succeeded=%d failed=%d cancelled=%d status=%s",
            task_id_base,
            len(parallel_devices),
            parallel_result.succeeded,
            parallel_result.failed,
            cancelled_count,
            parallel_result.summary_status,
        )
        emit_task_log(
            "aggregation_done",
            trace_id=trace_id,
            group_id=task_id_base,
            task_type="parallel_goal",
            total=parallel_result.total,
            succeeded=parallel_result.succeeded,
            failed=parallel_result.failed,
            cancelled=cancelled_count,
            latency_ms=round(parallel_latency_ms, 1),
            status=parallel_result.summary_status,
        )
        return {
            "success": parallel_result.succeeded > 0,
            "response": summary_text,
            "intent": "parallel_goal",
            "trace_id": trace_id,
            "metadata": {
                "parallel_group": task_id_base,
                "subtask_results": parallel_result.device_results,
                "device_count": len(parallel_devices),
                "parallel_result": parallel_result.to_dict(),
                "cancelled_count": cancelled_count,
                "trace_id": trace_id,
            },
        }

    def _collect_tools(self) -> List[Dict]:
        """统一收集三层工具（MCP / Skill / Node），转为 OpenAI function calling 格式

        返回格式: [{"type": "function", "function": {"name": "mcp__server__tool", ...}}, ...]
        前缀约定:
          - mcp__<server_id>__<tool_name>   → MCP 协议工具
          - skill__<skill_id>               → Skill 技能
          - node__<node_id>__<action>       → Node 节点操作

        执行链路：MCP/Skill 工具优先从能力总线 (CapabilityRegistry) 取，
        确保加载后立即可用且经过 schema 校验；Node 工具沿用直接加载路径。
        """
        tools: List[Dict] = []

        # ── 能力总线: CapabilityRegistry (MCP + Skill SSOT) ──
        # 优先从能力总线取 MCP/Skill 工具；若总线为空则回退直接加载路径
        _bus_loaded = False
        try:
            from core.agent.capability_registry import CapabilityRegistry
            reg = CapabilityRegistry.get_instance()
            bus_tools = [
                item.to_tool_schema()
                for item in reg.list_tools()
                if item.source in ("mcp", "skill")
            ]
            if bus_tools:
                tools.extend(bus_tools)
                _bus_loaded = True
                logger.debug("_collect_tools: 从能力总线获取 %d 个 MCP/Skill 工具", len(bus_tools))
        except Exception as e:
            logger.debug("能力总线不可用，回退直接加载: %s", e)

        if not _bus_loaded:
            # ── 回退层 1: MCP 服务器工具 (直接加载) ──
            try:
                from core.mcp_loader import mcp_loader

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

            # ── 回退层 2: Skill 技能 (直接加载) ──
            try:
                from core.skill_loader import skill_loader

                for skill_info in skill_loader.list_skills():
                    skill_id = skill_info.get("id", "")
                    if not skill_id or skill_info.get("status") == "error":
                        continue
                    # 使用 to_mcp_tool_schema 获取正确的 JSON Schema
                    mcp_schema = skill_loader.to_mcp_tool_schema(skill_id)
                    params = mcp_schema.get("inputSchema", _DEFAULT_SKILL_SCHEMA) if mcp_schema else _DEFAULT_SKILL_SCHEMA
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": f"skill__{skill_id}",
                            "description": skill_info.get("description", f"Skill: {skill_id}"),
                            "parameters": params,
                        },
                    })
            except Exception as e:
                logger.debug(f"收集 Skill 工具失败: {e}")

        # ── 层 1.5: MCP Gateway 自造工具 (始终收集，不在能力总线) ──
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

        # ── 层 3: Node 节点操作 (静态 action 目录 + 动态发现全量节点) ──
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

            # 已注册的工具名集合，避免重复添加
            _registered_tool_names: set = set()

            # 从静态目录生成工具列表（_CORE_NODE_ACTIONS 作为高优先级回退）
            for node_id, actions_map in self._CORE_NODE_ACTIONS.items():
                node_name = registry_names.get(node_id, f"Node_{node_id}")
                for action_name, action_desc in actions_map.items():
                    tool_name_key = f"node__{node_id}__{action_name}"
                    if tool_name_key not in _registered_tool_names:
                        _registered_tool_names.add(tool_name_key)
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": tool_name_key,
                                "description": f"Node {node_name}: {action_desc}",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "params": {"type": "object", "description": "操作参数"}
                                    },
                                },
                            },
                        })

            # 动态发现：遍历注册表中所有节点，尝试从 fusion_entry.py 获取 actions
            # 已在 _CORE_NODE_ACTIONS 中覆盖的节点仍可通过动态发现补充额外 action
            _DYNAMIC_SCAN_LIMIT = self.NODE_DYNAMIC_TOOL_LIMIT  # LLM function calling 建议上限
            _dynamic_added = 0
            for node_id, node_key in list(self._node_id_to_key.items()):
                if _dynamic_added >= _DYNAMIC_SCAN_LIMIT:
                    break
                # 先检查缓存
                if node_id in self._node_actions_cache:
                    discovered = self._node_actions_cache[node_id]
                else:
                    try:
                        discovered = self._discover_node_actions(node_id, node_key)
                        self._node_actions_cache[node_id] = discovered
                    except Exception as _e:
                        logger.debug(f"动态发现节点 {node_id} actions 失败: {_e}")
                        self._node_actions_cache[node_id] = {}
                        discovered = {}

                node_name = registry_names.get(node_id, f"Node_{node_id}")
                for action_name, action_desc in discovered.items():
                    tool_name_key = f"node__{node_id}__{action_name}"
                    if tool_name_key not in _registered_tool_names:
                        _registered_tool_names.add(tool_name_key)
                        _dynamic_added += 1
                        tools.append({
                            "type": "function",
                            "function": {
                                "name": tool_name_key,
                                "description": f"Node {node_name}: {action_desc}",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "params": {"type": "object", "description": "操作参数"}
                                    },
                                },
                            },
                        })

            logger.debug(
                "Node 工具收集: 静态 %d + 动态发现 %d，注册表节点 %d 个",
                len(self._CORE_NODE_ACTIONS),
                _dynamic_added,
                len(self._node_id_to_key),
            )
        except Exception as e:
            logger.debug(f"收集 Node 工具失败: {e}")

        logger.info(f"工具总线收集完成: {len(tools)} 个工具")

        # ── GitHub 插件工具 (始终收集) ─────────────────────────────────────
        tools.extend(_GITHUB_BUILTIN_TOOLS)

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

            elif tool_name.startswith("github__"):
                # GitHub addon tools: github__install, github__uninstall, github__list
                action = tool_name[8:]  # strip "github__"
                return await self._dispatch_github_tool(action, arguments)

            else:
                return {"success": False, "error": f"未知工具前缀: {tool_name}"}

        except Exception as e:
            logger.warning(f"工具执行失败 [{tool_name}]: {e}")
            return {"success": False, "error": str(e)}

    # ========================================================================
    # GitHub Addon Tools — github__install / github__uninstall / github__list
    # ========================================================================

    async def _dispatch_github_tool(self, action: str, arguments: dict) -> dict:
        """Dispatch GitHub addon tool calls.

        Supported actions:
            install   — install MCP tool or Skill from GitHub URL.
            uninstall — uninstall addon by name.
            list      — list all installed GitHub addons.

        Args:
            action:    Action name (strip of ``github__`` prefix).
            arguments: Tool arguments from LLM tool_calls.

        Returns:
            ``{"success": bool, "result": Any, "error": Optional[str]}``
        """
        try:
            from core.github_installer import get_github_installer
            installer = get_github_installer()

            if action == "install":
                url = arguments.get("url", "")
                if not url:
                    return {"success": False, "error": "github__install requires 'url' argument"}
                result = await installer.install(
                    url=url,
                    ref=arguments.get("ref"),
                    addon_type=arguments.get("type"),
                    dry_run=bool(arguments.get("dry_run", False)),
                )
                return result

            elif action == "uninstall":
                name = arguments.get("name", "")
                if not name:
                    return {"success": False, "error": "github__uninstall requires 'name' argument"}
                return await installer.uninstall(name)

            elif action == "list":
                return installer.list_installed()

            elif action == "status":
                return installer.get_status()

            else:
                return {
                    "success": False,
                    "error": (
                        f"Unknown github action: '{action}'. "
                        "Valid actions: install, uninstall, list, status."
                    ),
                }
        except Exception as exc:
            logger.warning("_dispatch_github_tool '%s' failed: %s", action, exc)
            return {"success": False, "error": str(exc)}

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

    async def handle_agent_task(
        self,
        message: str,
        intent,
        device_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
    ) -> dict:
        """复杂任务处理 — 使用 AgentFactory 创建 Agent，必要时组建团队

        PR-2：在入口立即构造 TaskEnvelope，统一 task_id/trace_id 贯穿链路。
        内部唯一任务格式：TaskEnvelope。

        Args:
            message: 用户消息
            intent: 解析后的意图 (ParsedIntent)
            device_id: 设备 ID（PR154: 贯穿 trace）
            session_id: 会话 ID（PR154: 贯穿 trace）
            trace_id: 请求追踪 ID（PR154: 贯穿 trace）

        Returns:
            Agent 执行结果 dict（含 task_id / trace_id）
        """
        try:
            from core.agent_factory import get_agent_factory
            from core.multi_llm_router import get_llm_router

            router = get_llm_router()
            factory = get_agent_factory(router)

            # PR-2: 在入口立即构造 TaskEnvelope，task_id/trace_id 贯穿整条执行链路。
            task_id = f"task_{uuid.uuid4().hex[:12]}"
            _envelope_trace_id = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
            try:
                from core.schemas.task_envelope import TaskEnvelope as _TaskEnvelope
                _agent_envelope = _TaskEnvelope(
                    task_id=task_id,
                    trace_id=_envelope_trace_id,
                    source="openclawd.handle_agent_task",
                    targets=[device_id] if device_id else [],
                    tool_name="agent_task",
                    args={
                        "message": message,
                        "intent": intent.intent if intent else "general",
                    },
                    metadata={
                        "session_id": session_id or "",
                        "device_id": device_id or "",
                    },
                )
                logger.debug(
                    "OpenClawd.handle_agent_task envelope | task_id=%s trace_id=%s",
                    _agent_envelope.task_id,
                    _agent_envelope.trace_id,
                )
            except Exception as _env_err:
                logger.debug("handle_agent_task: TaskEnvelope construction skipped — %s", _env_err)

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
                team_result = await self._execute_team_task(message, intent, factory, router)
                # PR154: 将 task_id / trace_id 注入团队协作结果 metadata
                meta = team_result.get("metadata", {})
                meta.setdefault("task_id", task_id)
                meta.setdefault("trace_id", _envelope_trace_id)
                meta.setdefault("device_id", device_id or "")
                team_result["metadata"] = meta
                return team_result

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
            success = result.get("status") != "error"

            # 清理 Agent
            factory.terminate_agent(agent.id)

            # PR154: 将任务结果写入 TaskMemory（记忆回流）
            try:
                from core.openclawd_memory_backflow import store_task_result
                await store_task_result(
                    task_id=task_id,
                    device_id=device_id or "openclawd",
                    route_mode="agent",
                    result={
                        "status": "completed" if success else "error",
                        "task_type": "agent_task",
                        "task_description": message[:200],
                        "result_summary": reply[:200],
                    },
                    session_id=session_id,
                )
            except Exception as _bf_err:
                logger.warning("handle_agent_task: memory backflow 失败（非致命）: %s", _bf_err)

            return {
                "success": success,
                "response": reply,
                "metadata": {
                    "agent_id": agent.id,
                    "agent_role": agent.config.role.value,
                    "template": template,
                    "result_count": len(result.get("results", [])),
                    "task_id": task_id,
                    # PR-2: use envelope trace_id (guaranteed non-empty)
                    "trace_id": _envelope_trace_id,
                    "device_id": device_id or "",
                    "session_id": session_id or "",
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
        """将设备能力同步为 CapabilityRegistry 条目。

        Priority A: 使用 UnifiedDeviceManager 作为 SSOT。
        Fallback B: 当 UnifiedDeviceManager 不可用或为空时，回退到 DeviceRegistry
        （保证向后兼容，同时确保新设备能力能正确注册到能力总线）。
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
            from core.agent.capability_registry import CapabilityRegistry, CapabilityItem

            reg = CapabilityRegistry.get_instance()

            # ── Priority A: UnifiedDeviceManager ────────────────────────────
            devices = []
            try:
                from core.unified.device_manager import get_unified_device_manager
                udm = get_unified_device_manager()
                devices = udm.list_devices() or []
            except (ImportError, AttributeError, RuntimeError) as _udm_err:
                logger.debug("UnifiedDeviceManager unavailable: %s", _udm_err)

            # ── Fallback B: DeviceRegistry ───────────────────────────────────
            if not devices:
                try:
                    from core.device_registry import DeviceRegistry
                    dr = DeviceRegistry.get_instance()
                    raw = dr.list_devices()
                    # list_devices may return a dict {id: obj} or a list
                    if isinstance(raw, dict):
                        devices = list(raw.values())
                    else:
                        devices = list(raw or [])
                except (ImportError, AttributeError, RuntimeError) as _dr_err:
                    logger.debug("DeviceRegistry fallback unavailable: %s", _dr_err)

            if not devices:
                return 0

            for device in devices:
                # Accept both object attributes and dict keys
                if isinstance(device, dict):
                    device_id = device.get("device_id", "")
                    d_name = device.get("device_name", device_id)
                    d_type = str(device.get("device_type", "unknown"))
                    caps = device.get("capabilities", [])
                    meta: Dict[str, Any] = device.get("metadata", {}) or {}
                else:
                    device_id = getattr(device, "device_id", "")
                    d_name = getattr(device, "device_name", None) or device_id
                    d_type = str(getattr(device, "device_type", "unknown"))
                    caps = getattr(device, "capabilities", []) or []
                    meta = getattr(device, "metadata", {}) or {}

                # 低层设备能力
                for cap in caps:
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
                    "OpenClawd: 已同步 %d 个设备能力到 CapabilityRegistry",
                    count,
                )
        except Exception as e:
            logger.debug("sync_device_capabilities 失败: %s", e)
        return count

    # ========================================================================
    # 网关统一命令路径 — PR-1: OpenClawd -> TaskEnvelope -> route_envelope -> device -> result
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

        链路：OpenClawd → TaskEnvelope → route_envelope → gateway/device_router → device → result

        构造 TaskEnvelope 并经由 CommandRouter.route_envelope() 进入内部路由链路。
        保留所有原入口参数与返回字段，与旧调用者完全兼容。
        """
        command_id = uuid.uuid4().hex
        task_id = task_id or uuid.uuid4().hex
        trace_id = f"trace_{uuid.uuid4().hex[:12]}"
        t0 = time.monotonic()
        logger.info(
            "OpenClawd.send_gateway_command | command_id=%s task_id=%s trace_id=%s "
            "session_id=%s device_id=%s command=%s",
            command_id, task_id, trace_id, session_id, device_id, command,
        )

        result: Dict = {
            "success": False,
            "command_id": command_id,
            "task_id": task_id,
            "session_id": session_id,
            "device_id": device_id,
            "command": command,
        }

        # 尝试通过 command_router.route_envelope 发送（PR-1: 统一入口）
        try:
            from core.command_router import get_command_router
            from core.schemas.task_envelope import TaskEnvelope

            cr = get_command_router()
            # 构造 TaskEnvelope，携带 session_id 和 command_id 进入统一链路
            envelope = TaskEnvelope(
                task_id=task_id,
                trace_id=trace_id,
                source="openclawd",
                targets=[device_id],
                tool_name=command,
                args=payload or {},
                metadata={
                    "command_id": command_id,
                    "session_id": session_id,
                    "source": "openclawd",
                },
            )
            cr_result = await cr.route_envelope(envelope)
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
