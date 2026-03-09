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
    DeviceRegisterSchema,
    DeviceStatusSchema,
    DeviceCapabilitySchema,
    DeviceCommandSchema,
    DeviceCommandResultSchema,
)

# -- Agent schemas -----------------------------------------------------------
from core.schemas.agent import (
    AgentCreateSchema,
    AgentTaskSchema,
    AgentResponseSchema,
    TwinCreateSchema,
    SwarmCreateSchema,
)

# -- Routing schemas ---------------------------------------------------------
from core.schemas.routing import (
    RoutingRequestSchema,
    RoutingDecisionSchema,
    ProviderStatusSchema,
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

__all__ = [
    # device
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
    # routing
    "RoutingRequestSchema",
    "RoutingDecisionSchema",
    "ProviderStatusSchema",
    # protocol
    "AIPMessageSchema",
    "MCPServerSchema",
    "MCPToolSchema",
    "SkillSchema",
    # session
    "SessionSchema",
    "SessionMigrateSchema",
]
