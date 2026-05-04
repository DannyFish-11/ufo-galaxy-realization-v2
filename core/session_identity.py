from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.schemas.ugcp.shared import (
    normalize_conversation_session_id,
    normalize_runtime_attachment_session_id,
)
from core.session_manager import get_session_manager


@dataclass(frozen=True)
class CanonicalSessionIdentity:
    conversation_session_id: str
    control_session_id: str
    runtime_attachment_session_id: str = ""
    user_id: str = ""
    device_id: str = ""
    source_session_id: str = ""

    def as_metadata(self) -> Dict[str, str]:
        return {
            "conversation_session_id": self.conversation_session_id,
            "control_session_id": self.control_session_id,
            "runtime_attachment_session_id": self.runtime_attachment_session_id,
            "user_id": self.user_id,
            "device_id": self.device_id,
            "source_session_id": self.source_session_id,
        }


def build_canonical_session_identity(
    *,
    session_id: str = "",
    user_id: str = "",
    device_id: str = "",
    runtime_session_id: str = "",
    payload: Optional[Any] = None,
    create_session: bool = True,
) -> CanonicalSessionIdentity:
    conversation_session_id = ""
    runtime_attachment_session_id = ""

    if payload is not None:
        conversation_session_id = normalize_conversation_session_id(payload) or ""
        runtime_attachment_session_id = (
            normalize_runtime_attachment_session_id(payload) or ""
        )

    if not conversation_session_id:
        conversation_session_id = (
            normalize_conversation_session_id(
                {
                    "conversation_session_id": session_id,
                    "control_session_id": session_id,
                    "session_id": session_id,
                }
            )
            or ""
        )

    if not conversation_session_id:
        if create_session:
            sm = get_session_manager()
            owner = user_id or f"device::{device_id or 'default'}"
            conversation_session_id = sm.get_or_create_session(
                owner,
                device_id or "",
            ).conversation_session_id
        else:
            conversation_session_id = f"session_{uuid.uuid4().hex[:12]}"

    if create_session:
        get_session_manager().ensure_session(
            conversation_session_id,
            user_id=user_id or f"device::{device_id or 'default'}",
            device_id=device_id or "",
        )

    control_session_id = (
        f"control_{runtime_session_id[:12]}"
        if runtime_session_id
        else f"control_{uuid.uuid4().hex[:12]}"
    )

    return CanonicalSessionIdentity(
        conversation_session_id=conversation_session_id,
        control_session_id=control_session_id,
        runtime_attachment_session_id=runtime_attachment_session_id,
        user_id=user_id,
        device_id=device_id,
        source_session_id=session_id or conversation_session_id,
    )

