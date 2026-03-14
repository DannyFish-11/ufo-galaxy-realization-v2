"""
Galaxy Agentic OS — Pydantic V2 Contract Mirror Models
=======================================================

Python-side enforcement layer that mirrors every Protobuf message defined in
``contracts/proto/galaxy/v1/*.proto``.  All business code MUST use these
models — never raw dicts — when crossing module boundaries.

Design constraints (see plan 强约束 C3, C4, C7):
  - DeviceType imported from ``core.device_types`` (canonical source)
  - Validators use ``resolve_device_type()`` for string→enum coercion
  - JSON field names are snake_case, matching Go ``json:`` tags exactly
  - All models are Pydantic V2 (``pydantic>=2.9.0``)
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from core.device_types import DeviceType, DevicePlatform, resolve_device_type


# ═══════════════════════════════════════════════════════════════════════════════
# Enums (mirroring proto enums)
# ═══════════════════════════════════════════════════════════════════════════════


class Priority(str, Enum):
    UNSPECIFIED = "unspecified"
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    UNSPECIFIED = "unspecified"
    PENDING = "pending"
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    LSP_FAILED = "lsp_failed"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


class WorkerStatus(str, Enum):
    UNSPECIFIED = "unspecified"
    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    OFFLINE = "offline"
    ERROR = "error"


class TaskType(str, Enum):
    UNSPECIFIED = "unspecified"
    CODE_EXEC = "code_exec"
    FILE_OP = "file_op"
    DEVICE_CMD = "device_cmd"
    MCP_CALL = "mcp_call"
    SHELL = "shell"
    LSP_CHECK = "lsp_check"
    HEALTH_CHECK = "health_check"
    CAPABILITY_PROBE = "capability_probe"


class CodeLanguage(str, Enum):
    UNSPECIFIED = "unspecified"
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    GO = "go"
    RUST = "rust"
    BASH = "bash"
    C = "c"
    CPP = "cpp"
    JAVA = "java"


class FileOperation(str, Enum):
    UNSPECIFIED = "unspecified"
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    MOVE = "move"
    COPY = "copy"
    LIST = "list"
    STAT = "stat"


class DiagnosticSeverity(str, Enum):
    UNSPECIFIED = "unspecified"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    HINT = "hint"


class MCPRegistrationAction(str, Enum):
    UNSPECIFIED = "unspecified"
    REGISTER = "register"
    DEREGISTER = "deregister"
    UPDATE = "update"
    HOT_RELOAD = "hot_reload"


class AgentMessageType(str, Enum):
    UNSPECIFIED = "unspecified"
    TASK_DISPATCH = "task_dispatch"
    TASK_RESULT = "task_result"
    MCP_CALL_REQUEST = "mcp_call_request"
    MCP_CALL_RESPONSE = "mcp_call_response"
    MCP_REGISTRATION = "mcp_registration"
    MCP_DISCOVERY = "mcp_discovery"
    HEARTBEAT = "heartbeat"
    WORKER_REGISTER = "worker_register"
    WORKER_SHUTDOWN = "worker_shutdown"
    EVENT = "event"


class EventDomain(str, Enum):
    UNSPECIFIED = "unspecified"
    UI = "ui"
    AI = "ai"
    HARDWARE = "hardware"
    COMMAND = "command"
    PERFORMANCE = "performance"
    L4 = "l4"
    SECURITY = "security"
    MCP = "mcp"
    WORKER = "worker"


class EventSeverity(str, Enum):
    UNSPECIFIED = "unspecified"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ═══════════════════════════════════════════════════════════════════════════════
# Common types  (common.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class TimestampModel(BaseModel):
    """High-precision timestamp with nanosecond resolution."""

    seconds: int = Field(default_factory=lambda: int(time.time()))
    nanos: int = Field(default=0, ge=0, le=999_999_999)

    @classmethod
    def now(cls) -> TimestampModel:
        t = time.time()
        return cls(seconds=int(t), nanos=int((t % 1) * 1_000_000_000))


class ErrorInfoModel(BaseModel):
    """Machine-readable error with source attribution."""

    code: str = ""
    message: str = ""
    details: str = ""
    source: str = ""


class ResourceUsageModel(BaseModel):
    """Resource consumption metrics for a task execution."""

    memory_peak_bytes: int = 0
    cpu_time_ms: int = 0
    wall_time_ms: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Task payloads  (task.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class CodePayloadModel(BaseModel):
    """Source code execution payload."""

    language: CodeLanguage = CodeLanguage.PYTHON
    source: str = ""
    entrypoint: str = ""
    dependencies: List[str] = Field(default_factory=list)
    env_vars: Dict[str, str] = Field(default_factory=dict)
    working_dir: str = ""


class SandboxConfigModel(BaseModel):
    """Docker sandbox resource constraints."""

    network_enabled: bool = False
    memory_limit_mb: int = 512
    cpu_limit_ms: int = 30_000
    timeout_ms: int = 60_000
    disk_limit_mb: int = 100
    image: str = ""
    mount_paths: List[str] = Field(default_factory=list)
    gpu_enabled: bool = False


class FilePayloadModel(BaseModel):
    """File operation payload."""

    operation: FileOperation = FileOperation.UNSPECIFIED
    source_path: str = ""
    dest_path: str = ""
    content: bytes = b""
    encoding: str = "utf-8"
    recursive: bool = False


class DeviceCommandPayloadModel(BaseModel):
    """Device-specific command payload."""

    command: str = ""
    params: Dict[str, str] = Field(default_factory=dict)
    target_device_id: str = ""


class ShellPayloadModel(BaseModel):
    """Shell command execution payload."""

    command: str = ""
    working_dir: str = ""
    env: Dict[str, str] = Field(default_factory=dict)


class MCPCallPayloadModel(BaseModel):
    """MCP tool call payload (embedded in TaskDispatch)."""

    server_id: str = ""
    tool_name: str = ""
    arguments_json: str = "{}"


# ═══════════════════════════════════════════════════════════════════════════════
# TaskDispatch — Brain → Worker  (task.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class TaskDispatchModel(BaseModel):
    """Primary outbound message from MasterBrain to Edge Worker.

    Published to NATS subject: ``galaxy.tasks.dispatch.{target_worker_id}``
    """

    # ── Identity
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_task_id: str = ""
    workflow_run_id: str = ""

    # ── Routing
    source_agent_id: str = ""
    target_worker_id: str = ""
    target_device_type: str = DeviceType.UNKNOWN.value
    task_type: TaskType = TaskType.UNSPECIFIED

    # ── Payload (exactly one should be set)
    code_payload: Optional[CodePayloadModel] = None
    file_payload: Optional[FilePayloadModel] = None
    device_payload: Optional[DeviceCommandPayloadModel] = None
    mcp_payload: Optional[MCPCallPayloadModel] = None
    shell_payload: Optional[ShellPayloadModel] = None

    # ── Execution parameters
    sandbox_config: Optional[SandboxConfigModel] = None
    priority: Priority = Priority.NORMAL
    timeout_ms: int = 60_000
    max_retries: int = 0
    lsp_check_required: bool = True

    # ── Context
    context: Dict[str, str] = Field(default_factory=dict)
    created_at: Optional[TimestampModel] = None
    idempotency_key: str = ""

    @field_validator("target_device_type", mode="before")
    @classmethod
    def _coerce_device_type(cls, v: Any) -> str:
        if isinstance(v, DeviceType):
            return v.value
        if isinstance(v, str) and v:
            return resolve_device_type(v).value
        return DeviceType.UNKNOWN.value

    @model_validator(mode="after")
    def _set_defaults(self) -> TaskDispatchModel:
        if self.created_at is None:
            self.created_at = TimestampModel.now()
        return self


# ═══════════════════════════════════════════════════════════════════════════════
# LSP Diagnostics  (task.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class LSPDiagnosticModel(BaseModel):
    """Single LSP diagnostic entry."""

    file_path: str = ""
    line: int = 0
    column: int = 0
    severity: DiagnosticSeverity = DiagnosticSeverity.UNSPECIFIED
    message: str = ""
    source: str = ""
    code: str = ""


class LSPCheckResultModel(BaseModel):
    """Aggregated LSP pre-check result."""

    passed: bool = True
    diagnostics: List[LSPDiagnosticModel] = Field(default_factory=list)
    error_count: int = 0
    warning_count: int = 0
    check_duration_ms: int = 0


# ═══════════════════════════════════════════════════════════════════════════════
# Execution Output  (task.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class ExecutionOutputModel(BaseModel):
    """Sandbox execution result (stdout/stderr/exit)."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0
    timed_out: bool = False
    oom_killed: bool = False


class ArtifactModel(BaseModel):
    """Output file produced by execution."""

    name: str = ""
    path: str = ""
    mime_type: str = ""
    size_bytes: int = 0
    checksum: str = ""
    content: bytes = b""
    storage_url: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# TaskResult — Worker → Brain  (task.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class TaskResultModel(BaseModel):
    """Primary inbound message from Edge Worker to MasterBrain.

    Published to NATS subject: ``galaxy.tasks.result.{task_id}``
    """

    # ── Identity
    task_id: str = ""
    worker_id: str = ""
    status: TaskStatus = TaskStatus.UNSPECIFIED

    # ── Results
    lsp_result: Optional[LSPCheckResultModel] = None
    execution_output: Optional[ExecutionOutputModel] = None
    artifacts: List[ArtifactModel] = Field(default_factory=list)

    # ── Diagnostics
    resource_usage: Optional[ResourceUsageModel] = None
    error: Optional[ErrorInfoModel] = None
    attempt_number: int = 1

    # ── Timing
    started_at: Optional[TimestampModel] = None
    completed_at: Optional[TimestampModel] = None
    queue_wait_ms: int = 0

    # ── Context
    metadata: Dict[str, str] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# MCP contracts  (mcp.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class MCPToolDescriptorModel(BaseModel):
    """Descriptor for a single MCP tool."""

    name: str = ""
    description: str = ""
    input_schema: str = "{}"
    output_schema: str = ""
    server_id: str = ""
    server_name: str = ""
    version: str = ""
    tags: List[str] = Field(default_factory=list)
    requires_auth: bool = False
    timeout_ms: int = 30_000


class MCPCallRequestModel(BaseModel):
    """MCP tool invocation request."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    server_id: str = ""
    arguments_json: str = "{}"
    timeout_ms: int = 30_000
    caller_agent_id: str = ""
    caller_task_id: str = ""
    created_at: Optional[TimestampModel] = None
    priority: Priority = Priority.NORMAL


class MCPCallResponseModel(BaseModel):
    """MCP tool invocation response."""

    request_id: str = ""
    is_error: bool = False
    result_json: str = "{}"
    error: Optional[ErrorInfoModel] = None
    duration_ms: int = 0
    completed_at: Optional[TimestampModel] = None
    server_id: str = ""


class MCPDiscoveryRequestModel(BaseModel):
    """Request to discover available MCP tools."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name_filter: str = ""
    tags: List[str] = Field(default_factory=list)
    server_id: str = ""
    include_schemas: bool = False


class MCPDiscoveryResponseModel(BaseModel):
    """Response listing discovered MCP tools."""

    request_id: str = ""
    tools: List[MCPToolDescriptorModel] = Field(default_factory=list)
    total: int = 0
    as_of: Optional[TimestampModel] = None


class MCPToolRegistrationModel(BaseModel):
    """Register/deregister/update an MCP tool (Self-Tool-Making)."""

    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: MCPRegistrationAction = MCPRegistrationAction.REGISTER
    tool: Optional[MCPToolDescriptorModel] = None

    # For REGISTER / UPDATE / HOT_RELOAD
    server_command: str = ""
    server_args: List[str] = Field(default_factory=list)
    server_env: Dict[str, str] = Field(default_factory=dict)
    script_content: str = ""
    script_language: str = "python"

    # Metadata
    generated_by: str = ""
    generation_prompt: str = ""
    created_at: Optional[TimestampModel] = None


class MCPToolRegistrationResultModel(BaseModel):
    """Result of a tool registration request."""

    request_id: str = ""
    success: bool = False
    error: Optional[ErrorInfoModel] = None
    server_id: str = ""
    tool_name: str = ""
    registered_at: Optional[TimestampModel] = None


# ═══════════════════════════════════════════════════════════════════════════════
# Agent / Worker contracts  (agent.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class WorkerCapabilityModel(BaseModel):
    """Single capability advertisement from a worker."""

    name: str = ""
    version: str = ""
    enabled: bool = True


class WorkerRegistrationModel(BaseModel):
    """Worker registration message sent on first NATS connect."""

    worker_id: str = ""
    hostname: str = ""
    device_type: str = DeviceType.UNKNOWN.value
    platform: str = ""
    os_version: str = ""
    worker_version: str = ""

    # Capabilities
    capabilities: List[WorkerCapabilityModel] = Field(default_factory=list)
    supported_languages: List[CodeLanguage] = Field(default_factory=list)
    has_docker: bool = False
    has_gpu: bool = False
    memory_total_mb: int = 0
    cpu_cores: int = 0

    # Network
    nats_inbox: str = ""
    addresses: List[str] = Field(default_factory=list)
    grpc_port: int = 0

    # Timing
    registered_at: Optional[TimestampModel] = None

    @field_validator("device_type", mode="before")
    @classmethod
    def _coerce_device_type(cls, v: Any) -> str:
        if isinstance(v, DeviceType):
            return v.value
        if isinstance(v, str) and v:
            return resolve_device_type(v).value
        return DeviceType.UNKNOWN.value


class WorkerHeartbeatModel(BaseModel):
    """Periodic worker heartbeat (default: every 10s)."""

    worker_id: str = ""
    status: WorkerStatus = WorkerStatus.IDLE
    timestamp: Optional[TimestampModel] = None

    # Trace correlation — matches TaskEnvelope.trace_id when a task triggered this heartbeat
    trace_id: str = ""

    # Load metrics
    active_tasks: int = 0
    queued_tasks: int = 0
    max_concurrent: int = 4
    cpu_usage_percent: float = 0.0
    memory_usage_percent: float = 0.0
    disk_free_mb: int = 0

    # Docker status
    running_containers: int = 0
    docker_disk_mb: int = 0

    # Cumulative stats
    tasks_completed_total: int = 0
    tasks_failed_total: int = 0
    uptime_seconds: int = 0


class WorkerShutdownModel(BaseModel):
    """Worker graceful shutdown notification."""

    worker_id: str = ""
    reason: str = ""
    drain_timeout_s: int = 30
    shutdown_at: Optional[TimestampModel] = None


class AgentEventModel(BaseModel):
    """System-wide event for observability."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    domain: EventDomain = EventDomain.UNSPECIFIED
    event_type: str = ""
    severity: EventSeverity = EventSeverity.INFO
    source: str = ""
    message: str = ""
    data_json: str = "{}"
    timestamp: Optional[TimestampModel] = None
    trace_id: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# AgentMessage envelope  (agent.proto)
# ═══════════════════════════════════════════════════════════════════════════════


class AgentMessageModel(BaseModel):
    """Unified message envelope for all inter-component communication.

    Wraps all specific message types and adds routing metadata.  A single
    NATS subscriber can handle heterogeneous message types by inspecting
    ``type`` and accessing the corresponding payload field.
    """

    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: AgentMessageType = AgentMessageType.UNSPECIFIED
    source: str = ""
    target: str = ""
    timestamp: Optional[TimestampModel] = None
    trace_id: str = ""
    correlation_id: str = ""

    # ── Payload (exactly one should be set based on 'type')
    task_dispatch: Optional[TaskDispatchModel] = None
    task_result: Optional[TaskResultModel] = None
    mcp_call_request: Optional[MCPCallRequestModel] = None
    mcp_call_response: Optional[MCPCallResponseModel] = None
    mcp_registration: Optional[MCPToolRegistrationModel] = None
    mcp_discovery: Optional[MCPDiscoveryRequestModel] = None
    heartbeat: Optional[WorkerHeartbeatModel] = None
    worker_register: Optional[WorkerRegistrationModel] = None
    worker_shutdown: Optional[WorkerShutdownModel] = None
    event: Optional[AgentEventModel] = None

    @model_validator(mode="after")
    def _set_timestamp(self) -> AgentMessageModel:
        if self.timestamp is None:
            self.timestamp = TimestampModel.now()
        return self

    # ── Node Protocol adapters (constraint C9)

    def to_node_message(self) -> dict:
        """Convert to node_protocol.Message-compatible dict."""
        from core.node_protocol import MessageType as NMT, MessagePriority

        _type_map = {
            AgentMessageType.TASK_DISPATCH: NMT.REQUEST,
            AgentMessageType.TASK_RESULT: NMT.RESPONSE,
            AgentMessageType.HEARTBEAT: NMT.PING,
            AgentMessageType.EVENT: NMT.EVENT,
        }
        return {
            "header": {
                "message_id": self.message_id,
                "message_type": _type_map.get(self.type, NMT.REQUEST).value,
                "timestamp": self.timestamp.seconds if self.timestamp else 0,
                "source_node": self.source,
                "target_node": self.target,
                "correlation_id": self.correlation_id or None,
                "priority": MessagePriority.NORMAL.value,
                "ttl": 30,
            },
            "action": self.type.value,
            "payload": self.model_dump(exclude_none=True, exclude={"message_id", "type", "source", "target", "timestamp", "trace_id", "correlation_id"}),
            "metadata": {"trace_id": self.trace_id},
        }

    @classmethod
    def from_node_message(cls, msg: dict) -> AgentMessageModel:
        """Create from node_protocol.Message-compatible dict."""
        header = msg.get("header", {})
        payload = msg.get("payload", {})
        metadata = msg.get("metadata", {})
        action = msg.get("action", "")

        try:
            msg_type = AgentMessageType(action)
        except ValueError:
            msg_type = AgentMessageType.UNSPECIFIED

        return cls(
            message_id=header.get("message_id", str(uuid.uuid4())),
            type=msg_type,
            source=header.get("source_node", ""),
            target=header.get("target_node", ""),
            trace_id=metadata.get("trace_id", ""),
            correlation_id=header.get("correlation_id", ""),
            **payload,
        )
