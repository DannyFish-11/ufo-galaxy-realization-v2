from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.cognitive.working_memory import get_working_memory
from core.session_manager import get_session_manager

logger = logging.getLogger("Galaxy.SessionMemoryFacade")


def _is_adjacent_duplicate(
    conversation_session_id: str,
    *,
    role: str,
    content: str,
    device_id: str = "",
) -> bool:
    try:
        wm_entries = get_working_memory().get(
            session_id=conversation_session_id,
            last_n=1,
        )
        if wm_entries:
            last = wm_entries[-1]
            last_device_id = (last.get("metadata") or {}).get("device_id", "")
            if (
                last.get("role") == role
                and last.get("content") == content
                and (not device_id or last_device_id == device_id)
            ):
                return True
    except Exception:
        pass

    try:
        history = get_session_manager().get_full_history(conversation_session_id)
        if history:
            last = history[-1]
            if (
                last.get("role") == role
                and last.get("content") == content
                and (not device_id or last.get("device_id", "") == device_id)
            ):
                return True
    except Exception:
        pass
    return False


async def record_session_turn(
    *,
    conversation_session_id: str,
    role: str,
    content: str,
    user_id: str = "",
    device_id: str = "",
    trace_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    if not conversation_session_id:
        return

    if _is_adjacent_duplicate(
        conversation_session_id,
        role=role,
        content=content,
        device_id=device_id,
    ):
        logger.debug(
            "record_session_turn: skipped adjacent duplicate turn session=%s role=%s",
            conversation_session_id,
            role,
        )
        return

    merged_metadata = dict(metadata or {})
    if trace_id:
        merged_metadata.setdefault("trace_id", trace_id)
    if device_id:
        merged_metadata.setdefault("device_id", device_id)

    sm = get_session_manager()
    sm.ensure_session(
        conversation_session_id,
        user_id=user_id or f"device::{device_id or 'default'}",
        device_id=device_id,
    )
    sm.add_message(
        conversation_session_id,
        role,
        content,
        device_id=device_id,
        metadata=merged_metadata,
    )

    try:
        get_working_memory().add(
            session_id=conversation_session_id,
            role=role,
            content=content,
            trace_id=trace_id,
            metadata=merged_metadata,
        )
    except Exception:
        pass

    try:
        from core.ai_intent import get_conversation_memory

        await get_conversation_memory().add_turn(
            conversation_session_id,
            role,
            content,
            metadata=merged_metadata,
        )
    except Exception:
        pass


def get_session_context(
    conversation_session_id: str,
    *,
    max_turns: int = 10,
) -> List[Dict[str, Any]]:
    if not conversation_session_id:
        return []

    try:
        wm_entries = get_working_memory().get(
            session_id=conversation_session_id,
            last_n=max_turns,
        )
        if wm_entries:
            return [
                {
                    "role": entry.get("role", ""),
                    "content": entry.get("content", ""),
                }
                for entry in wm_entries
            ]
    except Exception:
        pass

    try:
        history = get_session_manager().get_history(
            conversation_session_id,
            max_turns=max_turns,
        )
        if history:
            return history
    except Exception:
        pass
    return []
