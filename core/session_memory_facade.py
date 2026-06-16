from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.cognitive.working_memory import get_working_memory
from core.session_manager import get_session_manager

logger = logging.getLogger("Galaxy.SessionMemoryFacade")


# ── TaskMemory bridge (unified access) ──

def _get_task_memory():
    """Lazy import to avoid circular deps."""
    from core.task_memory import get_task_memory
    return get_task_memory()


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
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

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
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)
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
    await sm.ensure_session(
        conversation_session_id,
        user_id=user_id or f"device::{device_id or 'default'}",
        device_id=device_id,
    )
    await sm.add_message(
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
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    try:
        from core.ai_intent import get_conversation_memory

        await get_conversation_memory().add_turn(
            conversation_session_id,
            role,
            content,
            metadata=merged_metadata,
        )
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 统一记忆层（core/memory：向量 + 可选 Omni-SimpleMem 跨模态）—— 写入用户/助手轮次。
    # best-effort；offload 到线程避免嵌入/向量写入阻塞事件循环；任何异常都吞掉。
    if content and role in ("user", "assistant"):
        try:
            import asyncio as _aio
            from core.memory import get_unified_memory

            _um = get_unified_memory()
            if _um.enabled:
                await _aio.to_thread(
                    _um.remember,
                    content,
                    modality="text",
                    tags=[role],
                    metadata={"session_id": conversation_session_id, **merged_metadata},
                )
        except Exception as exc:  # noqa: BLE001 — 记忆写入失败不影响主流程
            logger.debug("unified memory remember skipped: %s", exc)

    # 跨模态记忆：用户开口的那一刻，把当前桌面摄像头/麦克风快照也写进记忆，
    # 让"看到/听到的"与对话绑定（跨模态终身记忆的核心用法）。默认关闭
    # （GALAXY_MEMORY_MEDIA=1 开启；媒体摄入较重，尤其 Omni-SimpleMem）。失败即跳过。
    if role == "user":
        try:
            import os as _os_mm
            if _os_mm.getenv("GALAXY_MEMORY_MEDIA", "0").strip().lower() in ("1", "true", "yes", "on"):
                import asyncio as _aio_mm
                from core.memory import get_unified_memory as _gum
                _um2 = _gum()
                if _um2.enabled:
                    from core.perception.desktop_perception_store import get_desktop_perception_store
                    _snap = get_desktop_perception_store().snapshot_media()
                    _md = {"session_id": conversation_session_id, "linked_turn": content[:120]}
                    if _snap.get("image_b64"):
                        await _aio_mm.to_thread(
                            _um2.remember_media, _snap["image_b64"],
                            modality="image", mime=_snap.get("image_mime", ""),
                            tags=["perception"], metadata=dict(_md),
                            caption=f"[camera @ user turn] {content[:80]}",
                        )
                    if _snap.get("audio_b64"):
                        await _aio_mm.to_thread(
                            _um2.remember_media, _snap["audio_b64"],
                            modality="audio", mime=_snap.get("audio_mime", ""),
                            tags=["perception"], metadata=dict(_md),
                            caption=f"[mic @ user turn] {content[:80]}",
                        )
        except Exception as exc:  # noqa: BLE001 — 跨模态记忆写入失败不影响主流程
            logger.debug("cross-modal memory write skipped: %s", exc)


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
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    try:
        history = get_session_manager().get_history(
            conversation_session_id,
            max_turns=max_turns,
        )
        if history:
            return history
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)
    return []


# ── Unified TaskMemory queries (NEW) ──
# These expose TaskMemory capabilities through the single facade entry point.


def get_adaptive_context(
    session_id: str,
    query: str,
    depth: str = "auto",
) -> str:
    """Unified adaptive context — retrieves task history via TaskMemory.

    depth: "shallow" | "standard" | "deep" | "auto"
    """
    if not session_id or not query:
        return ""
    try:
        return _get_task_memory().adaptive_context(query, depth)
    except Exception as e:
        logger.debug("get_adaptive_context failed (non-fatal): %s", e)
        return ""


def get_event_chain(session_id: str) -> str:
    """Unified event chain — all tasks in a session, sorted by time."""
    if not session_id:
        return ""
    try:
        records = _get_task_memory().get_event_chain(session_id)
        if not records:
            return ""
        lines = [f"- [{r.timestamp:.0f}] {r.task} → {r.result_summary[:60]}" for r in records]
        return "Session event chain:\n" + "\n".join(lines)
    except Exception as e:
        logger.debug("get_event_chain failed (non-fatal): %s", e)
        return ""


def get_task_lineage(keyword: str) -> str:
    """Unified task lineage — similar tasks across sessions."""
    if not keyword:
        return ""
    try:
        records = _get_task_memory().get_task_lineage(keyword)
        if not records:
            return ""
        lines = [f"- [{r.timestamp:.0f}] {r.task} → {r.result_summary[:60]}" for r in records]
        return "Related task lineage:\n" + "\n".join(lines)
    except Exception as e:
        logger.debug("get_task_lineage failed (non-fatal): %s", e)
        return ""


# ── Unified memory query (single entry point for ALL memory) ──

def get_unified_context(
    session_id: str,
    query: str = "",
    depth: str = "auto",
    max_turns: int = 10,
) -> List[Dict[str, str]]:
    """THE single entry point for all memory queries.

    Returns a list of system messages containing:
    1. Long-term preferences
    2. Short-term conversation context
    3. Adaptive task history (cross-session)
    4. Event chain (current session)

    OpenClawd should call this instead of querying individual memory modules.
    """
    messages: List[Dict[str, str]] = []

    # 1. Long-term preferences
    try:
        from core.cognitive.long_term_memory import get_long_term_memory
        ltm = get_long_term_memory()
        prefs = ltm.retrieve_all(namespace="preferences")
        if prefs:
            lines = [f"- {e['key']}: {e['value']}" for e in prefs[:10]]
            messages.append({
                "role": "system",
                "content": "[Long-term memory — user preferences]\n" + "\n".join(lines),
            })
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 2. Short-term conversation context
    try:
        turns = get_session_context(session_id, max_turns=max_turns)
        for turn in turns:
            messages.append({"role": turn["role"], "content": turn["content"]})
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 3. Adaptive task history (cross-session, NEW)
    if query:
        try:
            ctx = get_adaptive_context(session_id, query, depth)
            if ctx:
                messages.append({"role": "system", "content": ctx})
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # 4. Event chain (current session, NEW)
    try:
        chain = get_event_chain(session_id)
        if chain:
            messages.append({"role": "system", "content": chain})
    except Exception as exc:
        logger.warning("Exception suppressed: %s", exc)

    # 5. 统一记忆层语义召回（core/memory：向量 + 可选 Omni-SimpleMem 跨模态）
    #    这是仓库里第一个真正接进 live 路径的语义/跨模态长程记忆召回点。
    if query:
        try:
            from core.memory import get_unified_memory

            _um = get_unified_memory()
            if _um.enabled:
                _hits = _um.recall(query, top_k=3)
                _lines = [f"- {h.content[:300]}" for h in _hits if h.content]
                if _lines:
                    messages.append({
                        "role": "system",
                        "content": "[Semantic long-term memory]\n" + "\n".join(_lines),
                    })
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    return messages
