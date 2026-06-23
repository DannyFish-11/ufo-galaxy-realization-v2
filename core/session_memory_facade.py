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

    # 1b. Long-term memory — 按 query 的 BM25 相关召回（零依赖词法检索，无需 embedding）。
    #     与上面「直接列 preferences」互补：这里跨 namespace 找与当前 query 最相关的条目。
    if query:
        try:
            from core.cognitive.long_term_memory import get_long_term_memory
            ltm = get_long_term_memory()
            hits: List[Dict[str, Any]] = []
            for ns in ("preferences", "facts", "skills", "global"):
                hits.extend(ltm.search(query=query, namespace=ns, top_k=3))
            hits.sort(key=lambda h: h.get("_score", 0.0), reverse=True)
            if hits:
                lines = [f"- {h['key']}: {h['value']}" for h in hits[:5]]
                messages.append({
                    "role": "system",
                    "content": "[Long-term memory — relevant to query]\n" + "\n".join(lines),
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


# ════════════════════════ 显式 recall → run → commit 生命周期 ════════════════════════
# 把「跑前召回相关记忆、跑后提交本轮」从隐式约定升格为显式 API。recall() 聚合全部记忆源
# （短期/任务/长期 + BM25 词法 + 向量），commit_turn() 落库（会话历史/工作记忆/统一记忆 +
# 证据链）。MemoryScope 把两步包成一个上下文管理器，调用方一目了然、不易漏掉 commit。


def recall(
    session_id: str,
    query: str = "",
    *,
    depth: str = "auto",
    max_turns: int = 10,
) -> List[Dict[str, str]]:
    """【run 前】召回与本轮相关的记忆，返回可直接喂给 LLM 的 messages。

    它是 :func:`get_unified_context` 的语义化别名（统一入口），并在会话证据链上留一条
    recall 记录，便于事后回放「这次参考了哪些记忆」。best-effort。
    """
    msgs = get_unified_context(session_id, query=query, depth=depth, max_turns=max_turns)
    try:
        from core.session_manager import record_evidence, EvidenceKind
        record_evidence(
            session_id, EvidenceKind.NOTE, actor="memory.recall",
            payload={"event": "recall", "query": query[:200],
                     "recalled_blocks": len(msgs)},
        )
    except Exception:  # noqa: BLE001
        pass
    return msgs


async def commit_turn(
    *,
    conversation_session_id: str,
    role: str,
    content: str,
    user_id: str = "",
    device_id: str = "",
    trace_id: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """【run 后】提交本轮到所有记忆源。:func:`record_session_turn` 的生命周期语义别名。"""
    await record_session_turn(
        conversation_session_id=conversation_session_id,
        role=role,
        content=content,
        user_id=user_id,
        device_id=device_id,
        trace_id=trace_id,
        metadata=metadata,
    )


class MemoryScope:
    """recall → run → commit 的异步上下文管理器。

    用法::

        async with MemoryScope(session_id, query=user_text,
                               user_id=uid, device_id=did) as mem:
            messages = mem.context            # 已召回的记忆，喂给 LLM
            await mem.commit("user", user_text)
            reply = await llm(messages + [...])
            await mem.commit("assistant", reply)

    进入作用域即完成 recall（结果在 ``mem.context``）；``commit`` 可多次调用提交各轮。
    退出作用域不强制 commit（由调用方按需提交），但会在证据链上标记一次 scope 结束。
    """

    def __init__(
        self,
        session_id: str,
        query: str = "",
        *,
        user_id: str = "",
        device_id: str = "",
        trace_id: str = "",
        depth: str = "auto",
        max_turns: int = 10,
    ) -> None:
        self.session_id = session_id
        self.query = query
        self.user_id = user_id
        self.device_id = device_id
        self.trace_id = trace_id
        self._depth = depth
        self._max_turns = max_turns
        self.context: List[Dict[str, str]] = []

    async def __aenter__(self) -> "MemoryScope":
        # 先确保会话存在，recall 的证据 note 才能落进该会话（首轮时会话尚未建立）。
        try:
            await get_session_manager().ensure_session(
                self.session_id,
                user_id=self.user_id or f"device::{self.device_id or 'default'}",
                device_id=self.device_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("MemoryScope ensure_session 跳过: %s", exc)
        self.context = recall(
            self.session_id, self.query,
            depth=self._depth, max_turns=self._max_turns,
        )
        return self

    async def commit(
        self,
        role: str,
        content: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        await commit_turn(
            conversation_session_id=self.session_id,
            role=role,
            content=content,
            user_id=self.user_id,
            device_id=self.device_id,
            trace_id=self.trace_id,
            metadata=metadata,
        )

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        # 不吞异常（返回 False）；仅在证据链上标记 scope 结束，便于回放。
        try:
            from core.session_manager import record_evidence, EvidenceKind
            record_evidence(
                self.session_id, EvidenceKind.NOTE, actor="memory.scope",
                payload={"event": "scope_exit", "errored": exc_type is not None},
            )
        except Exception:  # noqa: BLE001
            pass
        return False
