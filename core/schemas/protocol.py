#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Protocol & Infrastructure Pydantic Models
========================================================

Schemas for the AIP v3.0 messaging protocol, MCP (Model Context Protocol)
servers and tools, and the skill system.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class AIPMessageSchema(BaseModel):
    """AIP v3.0 protocol message.

    Represents a single message exchanged between devices or between a
    device and the Galaxy-Nexus hub via the AIP v3.0 protocol.
    """

    version: str = Field(
        default="3.0",
        description="AIP protocol version.",
    )
    message_id: str = Field(
        ...,
        min_length=1,
        description="Globally unique message identifier.",
    )
    type: str = Field(
        ...,
        description=(
            "Message type, e.g. 'command', 'event', 'response', "
            "'heartbeat', 'discovery'."
        ),
    )
    device_id: str = Field(
        ...,
        description="ID of the originating or target device.",
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Message payload; structure depends on 'type'.",
    )
    timestamp: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of when the message was created.",
    )

    model_config = {"from_attributes": True}


class MCPServerSchema(BaseModel):
    """MCP server registration / status record.

    Tracks a Model Context Protocol server that exposes tools to
    Galaxy agents.
    """

    name: str = Field(
        ...,
        min_length=1,
        description="Human-readable server name.",
    )
    url: str = Field(
        ...,
        description="Base URL of the MCP server (e.g. 'http://localhost:8090').",
    )
    status: str = Field(
        default="unknown",
        description="Server status: 'online', 'offline', 'error', 'unknown'.",
    )
    tools_count: int = Field(
        default=0,
        ge=0,
        description="Number of tools currently registered on this server.",
    )
    last_health_check: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the last successful health check.",
    )

    model_config = {"from_attributes": True}


class MCPToolSchema(BaseModel):
    """Descriptor for a single MCP tool.

    Provides enough metadata for an agent to discover and invoke the
    tool at runtime.
    """

    name: str = Field(
        ...,
        min_length=1,
        description="Tool name (unique within its server).",
    )
    description: str = Field(
        default="",
        description="Short description of what the tool does.",
    )
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "JSON-Schema style parameter definition accepted by the "
            "tool."
        ),
    )
    server_name: str = Field(
        default="",
        description="Name of the MCP server that hosts this tool.",
    )

    model_config = {"from_attributes": True}


class SkillSchema(BaseModel):
    """Skill metadata record.

    Represents a loadable skill module in the Galaxy skill system.
    """

    name: str = Field(
        ...,
        min_length=1,
        description="Skill name.",
    )
    version: str = Field(
        default="1.0.0",
        description="Semantic version of the skill.",
    )
    status: str = Field(
        default="unloaded",
        description="Skill status: 'loaded', 'unloaded', 'error', 'disabled'.",
    )
    description: str = Field(
        default="",
        description="Brief description of the skill's purpose.",
    )
    loaded_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of when the skill was last loaded.",
    )

    model_config = {"from_attributes": True}
