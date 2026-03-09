#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UFO Galaxy - Session Pydantic Models
======================================

Schemas for session management including creation, querying, and
cross-device session migration.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class SessionSchema(BaseModel):
    """Active session record.

    Represents a user session bound to a specific device, carrying
    arbitrary context that can be migrated across devices.
    """

    session_id: str = Field(
        ...,
        min_length=1,
        description="Unique session identifier.",
    )
    device_id: str = Field(
        ...,
        description="ID of the device currently hosting this session.",
    )
    created_at: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of session creation.",
    )
    last_active: Optional[datetime] = Field(
        default=None,
        description="UTC timestamp of the most recent activity.",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Session context payload. May include conversation "
            "history, user preferences, agent state, etc."
        ),
    )

    model_config = {"from_attributes": True}


class SessionMigrateSchema(BaseModel):
    """Session migration request.

    Used when a session needs to be transferred from one device to
    another (e.g. phone to desktop continuity).
    """

    session_id: str = Field(
        ...,
        min_length=1,
        description="ID of the session to migrate.",
    )
    source_device: str = Field(
        ...,
        description="Device ID where the session currently lives.",
    )
    target_device: str = Field(
        ...,
        description="Device ID to migrate the session to.",
    )
    context: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional context overrides to apply during migration. "
            "Merged with the existing session context."
        ),
    )

    model_config = {"from_attributes": True}
