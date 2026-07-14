#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Pydantic Schema Package
======================================

Central re-export of all Pydantic schemas used across the Galaxy-Nexus
platform.  Import from this package for convenience::

    from core.schemas import DeviceRegisterSchema, AgentCreateSchema
"""

# -- Agent schemas -----------------------------------------------------------
from core.schemas.agent import (  # Phase 2: Team Manifest
    AgentCreateSchema,
    AgentResponseSchema,
    AgentTaskSchema,
    SwarmCreateSchema,
    TeamManifestSchema,
    TeamMemberResultSchema,
    TeamMemberSchema,
    TeamResultSchema,
    TeamStrategyEnum,
    TwinCreateSchema,
)

# -- Contract models (Agentic OS) -------------------------------------------
# Enums; Common; Task payloads; Task dispatch/result; LSP; Execution; MCP; Worker;
# Events; Envelope
from core.schemas.contracts import (
    AgentEventModel,
    AgentMessageModel,
    AgentMessageType,
    ArtifactModel,
    CodeLanguage,
    CodePayloadModel,
    DeviceCommandPayloadModel,
    DiagnosticSeverity,
    ErrorInfoModel,
    EventDomain,
    EventSeverity,
    ExecutionOutputModel,
    FileOperation,
    FilePayloadModel,
    LSPCheckResultModel,
    LSPDiagnosticModel,
    MCPCallPayloadModel,
    MCPCallRequestModel,
    MCPCallResponseModel,
    MCPDiscoveryRequestModel,
    MCPDiscoveryResponseModel,
    MCPRegistrationAction,
    MCPToolDescriptorModel,
    MCPToolRegistrationModel,
    MCPToolRegistrationResultModel,
    Priority,
    ResourceUsageModel,
    SandboxConfigModel,
    ShellPayloadModel,
    TaskDispatchModel,
    TaskResultModel,
    TaskStatus,
    TaskType,
    TimestampModel,
    WorkerCapabilityModel,
    WorkerHeartbeatModel,
    WorkerRegistrationModel,
    WorkerShutdownModel,
    WorkerStatus,
)

# -- Device schemas ----------------------------------------------------------
from core.schemas.device import (
    DeviceCapabilityModel,
    DeviceCapabilitySchema,
    DeviceCommandResultSchema,
    DeviceCommandSchema,
    DeviceModel,
    DeviceRegisterSchema,
    DeviceStatusSchema,
)

# -- Multi-modal input schemas (PR 1) ----------------------------------------
from core.schemas.multimodal import (
    MultiModalAudio,
    MultiModalContext,
    MultiModalImage,
    MultiModalInput,
)

# -- Orchestration schemas ---------------------------------------------------
from core.schemas.orchestration import (
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationStatus,
    SubTask,
    SubTaskStatus,
    TaskDecomposition,
)

# -- Protocol schemas --------------------------------------------------------
from core.schemas.protocol import (
    AIPMessageSchema,
    MCPServerSchema,
    MCPToolSchema,
    SkillSchema,
)

# -- Executor target type (PR-E) -----------------------------------------------
from core.schemas.remote_execution import ExecutorTargetType, RemoteExecutionMode

# -- Routing schemas ---------------------------------------------------------
from core.schemas.routing import (  # Phase 2: Complexity & Response
    ComplexityVector,
    ModelTier,
    ProviderStatusSchema,
    RouterResponseSchema,
    RoutingDecisionSchema,
    RoutingRequestSchema,
)

# -- Session schemas ---------------------------------------------------------
from core.schemas.session import (
    SessionMigrateSchema,
    SessionSchema,
)

# -- TaskEnvelope (canonical Agent-Bus schema) --------------------------------
from core.schemas.task_envelope import (
    TaskEnvelope,
    envelope_from_command_request,
    envelope_from_mcp_call,
    envelope_from_relay_request,
)

# -- Tool call schemas -------------------------------------------------------
from core.schemas.tool_call import (
    ReactLoopResult,
    ToolCallRecord,
    ToolCallStatus,
    ToolLayer,
)

__all__ = [
    # multi-modal input (PR 1)
    "MultiModalImage",
    "MultiModalAudio",
    "MultiModalContext",
    "MultiModalInput",
    # task envelope (canonical Agent-Bus schema)
    "TaskEnvelope",
    "envelope_from_command_request",
    "envelope_from_relay_request",
    "envelope_from_mcp_call",
    # executor target type (PR-E)
    "ExecutorTargetType",
    "RemoteExecutionMode",
    # device (unified models)
    "DeviceModel",
    "DeviceCapabilityModel",
    # device (API schemas)
    "DeviceRegisterSchema",
    "DeviceStatusSchema",
    "DeviceCapabilitySchema",
    "DeviceCommandSchema",
    "DeviceCommandResultSchema",
    # agent
    "AgentCreateSchema",
    "AgentTaskSchema",
    "AgentResponseSchema",
    "TwinCreateSchema",
    "SwarmCreateSchema",
    "TeamStrategyEnum",
    "TeamMemberSchema",
    "TeamManifestSchema",
    "TeamMemberResultSchema",
    "TeamResultSchema",
    # routing
    "RoutingRequestSchema",
    "RoutingDecisionSchema",
    "ProviderStatusSchema",
    "ModelTier",
    "ComplexityVector",
    "RouterResponseSchema",
    # tool call
    "ToolLayer",
    "ToolCallStatus",
    "ToolCallRecord",
    "ReactLoopResult",
    # protocol
    "AIPMessageSchema",
    "MCPServerSchema",
    "MCPToolSchema",
    "SkillSchema",
    # session
    "SessionSchema",
    "SessionMigrateSchema",
    # contracts — enums
    "Priority",
    "TaskStatus",
    "WorkerStatus",
    "TaskType",
    "CodeLanguage",
    "FileOperation",
    "DiagnosticSeverity",
    "MCPRegistrationAction",
    "AgentMessageType",
    "EventDomain",
    "EventSeverity",
    # contracts — common
    "TimestampModel",
    "ErrorInfoModel",
    "ResourceUsageModel",
    # contracts — task payloads
    "CodePayloadModel",
    "SandboxConfigModel",
    "FilePayloadModel",
    "DeviceCommandPayloadModel",
    "ShellPayloadModel",
    "MCPCallPayloadModel",
    # contracts — task dispatch/result
    "TaskDispatchModel",
    "TaskResultModel",
    # contracts — LSP
    "LSPDiagnosticModel",
    "LSPCheckResultModel",
    # contracts — execution
    "ExecutionOutputModel",
    "ArtifactModel",
    # contracts — MCP
    "MCPToolDescriptorModel",
    "MCPCallRequestModel",
    "MCPCallResponseModel",
    "MCPDiscoveryRequestModel",
    "MCPDiscoveryResponseModel",
    "MCPToolRegistrationModel",
    "MCPToolRegistrationResultModel",
    # contracts — worker
    "WorkerCapabilityModel",
    "WorkerRegistrationModel",
    "WorkerHeartbeatModel",
    "WorkerShutdownModel",
    # contracts — events
    "AgentEventModel",
    # contracts — envelope
    "AgentMessageModel",
    # orchestration
    "SubTask",
    "SubTaskStatus",
    "TaskDecomposition",
    "OrchestrationRequest",
    "OrchestrationResult",
    "OrchestrationStatus",
]
