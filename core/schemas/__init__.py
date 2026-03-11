#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Pydantic Schema Package
======================================

Central re-export of all Pydantic schemas used across the Galaxy-Nexus
platform.  Import from this package for convenience::

    from core.schemas import DeviceRegisterSchema, AgentCreateSchema
"""

# -- Device schemas ----------------------------------------------------------
from core.schemas.device import (
    DeviceModel,
    DeviceCapabilityModel,
    DeviceRegisterSchema,
    DeviceStatusSchema,
    DeviceCapabilitySchema,
    DeviceCommandSchema,
    DeviceCommandResultSchema,
)

# -- Orchestration schemas ---------------------------------------------------
from core.schemas.orchestration import (
    SubTask,
    SubTaskStatus,
    TaskDecomposition,
    OrchestrationRequest,
    OrchestrationResult,
    OrchestrationStatus,
)

# -- Agent schemas -----------------------------------------------------------
from core.schemas.agent import (
    AgentCreateSchema,
    AgentTaskSchema,
    AgentResponseSchema,
    TwinCreateSchema,
    SwarmCreateSchema,
    # Phase 2: Team Manifest
    TeamStrategyEnum,
    TeamMemberSchema,
    TeamManifestSchema,
    TeamMemberResultSchema,
    TeamResultSchema,
)

# -- Routing schemas ---------------------------------------------------------
from core.schemas.routing import (
    RoutingRequestSchema,
    RoutingDecisionSchema,
    ProviderStatusSchema,
    # Phase 2: Complexity & Response
    ModelTier,
    ComplexityVector,
    RouterResponseSchema,
)

# -- Tool call schemas -------------------------------------------------------
from core.schemas.tool_call import (
    ToolLayer,
    ToolCallStatus,
    ToolCallRecord,
    ReactLoopResult,
)

# -- Protocol schemas --------------------------------------------------------
from core.schemas.protocol import (
    AIPMessageSchema,
    MCPServerSchema,
    MCPToolSchema,
    SkillSchema,
)

# -- Session schemas ---------------------------------------------------------
from core.schemas.session import (
    SessionSchema,
    SessionMigrateSchema,
)

# -- Contract models (Agentic OS) -------------------------------------------
from core.schemas.contracts import (
    # Enums
    Priority,
    TaskStatus,
    WorkerStatus,
    TaskType,
    CodeLanguage,
    FileOperation,
    DiagnosticSeverity,
    MCPRegistrationAction,
    AgentMessageType,
    EventDomain,
    EventSeverity,
    # Common
    TimestampModel,
    ErrorInfoModel,
    ResourceUsageModel,
    # Task payloads
    CodePayloadModel,
    SandboxConfigModel,
    FilePayloadModel,
    DeviceCommandPayloadModel,
    ShellPayloadModel,
    MCPCallPayloadModel,
    # Task dispatch/result
    TaskDispatchModel,
    TaskResultModel,
    # LSP
    LSPDiagnosticModel,
    LSPCheckResultModel,
    # Execution
    ExecutionOutputModel,
    ArtifactModel,
    # MCP
    MCPToolDescriptorModel,
    MCPCallRequestModel,
    MCPCallResponseModel,
    MCPDiscoveryRequestModel,
    MCPDiscoveryResponseModel,
    MCPToolRegistrationModel,
    MCPToolRegistrationResultModel,
    # Worker
    WorkerCapabilityModel,
    WorkerRegistrationModel,
    WorkerHeartbeatModel,
    WorkerShutdownModel,
    # Events
    AgentEventModel,
    # Envelope
    AgentMessageModel,
)

__all__ = [
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
