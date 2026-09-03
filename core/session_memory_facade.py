from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

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
    # 融合(域3):轮次唯一属主是 SessionManager,只需查它(此前还要交叉查
    # WorkingMemory 的副本——副本已不存在,WM 对话读也透传 SM)。
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


#: 一条轮次带进来的模态,用**感知契约那套名字**(screen / camera / microphone /
#: system_audio)加上两个多模态请求特有的(image / video)。
#:
#: 名字必须与 core/phase_contract.py 的 PerceptionModality 对得上:岛上四条通路
#: 用那套名字,记忆卡片上那一栏也用那套名字。各写一套的话,同一件事在两处叫不同
#: 的名字,而没人会去对。
_MODALITY_IMAGE = "image"
_MODALITY_AUDIO = "microphone"
_MODALITY_SCREEN = "screen"
_MODALITY_VIDEO = "video"


def modalities_of(multimodal_context: Any) -> List[str]:
    """这一轮带进来了哪些模态。**判断只在这里做一次。**

    记忆卡片上那一栏靠它才有内容 —— 不写的话那一栏永远是空的,一个看着接好了、
    其实没有任何生产者的字段。而「那三天是看着屏幕聊的还是纯打字」恰恰是回头找
    那几天时最好用的线索。

    **拿不准就不写。** 猜一个「文字」出来,卡面上就出现了一个谁也没说过的事实;
    空列表在渲染那侧是「没记录」,与「确实只有文字」不必分开(两者对人是一样的)。
    """
    if multimodal_context is None:
        return []
    out: List[str] = []
    if getattr(multimodal_context, "images", None):
        out.append(_MODALITY_IMAGE)
    if getattr(multimodal_context, "audio", None):
        out.append(_MODALITY_AUDIO)
    if getattr(multimodal_context, "video", None):
        out.append(_MODALITY_VIDEO)
    # screen 是个自由字典(分辨率、窗口标题、抓取时刻);**空字典不算**,
    # 那是「带了这个字段但里面什么都没有」,不是「看了屏幕」。
    if getattr(multimodal_context, "screen", None):
        out.append(_MODALITY_SCREEN)
    return out


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

    # 融合(域3):轮次【单写】唯一属主 SessionManager。此前同一轮要四写
    # (SM + WorkingMemory + ConversationMemory + UnifiedMemory)——WM/CM 的轮次
    # 副本已删,它们的读全部透传 SM;CM 只保留独有的偏好学习(learn 钩子);
    # UnifiedMemory 是语义向量【索引】(不同的数据形态),仍经本门写入。
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

    # 偏好学习钩子(ConversationMemory 的独有能力;不再让它另存一份轮次)。
    try:
        from core.ai_intent import get_conversation_memory

        get_conversation_memory().learn(conversation_session_id, role, content)
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
                            _um2.remember_media,
                            _snap["image_b64"],
                            modality="image",
                            mime=_snap.get("image_mime", ""),
                            tags=["perception"],
                            metadata=dict(_md),
                            caption=f"[camera @ user turn] {content[:80]}",
                        )
                    if _snap.get("audio_b64"):
                        await _aio_mm.to_thread(
                            _um2.remember_media,
                            _snap["audio_b64"],
                            modality="audio",
                            mime=_snap.get("audio_mime", ""),
                            tags=["perception"],
                            metadata=dict(_md),
                            caption=f"[mic @ user turn] {content[:80]}",
                        )
        except Exception as exc:  # noqa: BLE001 — 跨模态记忆写入失败不影响主流程
            logger.debug("cross-modal memory write skipped: %s", exc)

    # ── 预判式上下文注入(ACI):告知轮次已落库,并在助手轮次后安排预取 ──
    #
    # 放在这里而不是 handle_request 里,是因为轮次写入是**唯一**的收敛点:文字对话、
    # 实时双工、跨设备回流全都经过它。挂在请求路径上就会漏掉双工(它根本不走
    # handle_request)。
    #
    # 两件事:
    #   1. note_turn_recorded —— 让 ACI 把该会话的既有预判作废(上下文含最近轮次,
    #      轮次一变旧的就少一轮),同时给"请求在飞"计数收尾。
    #   2. role == "assistant" 时安排下一轮的预取 —— 助手轮次落库 = 这一轮真的结束了,
    #      从此刻到用户下一句之间就是那段空档。
    # 全程 best-effort,永不影响对话。
    # ── 焦点栈:用户发言驱动"当前在做什么 / 被搁下的还有哪些" ──
    # 与 ACI 挂在同一处、同样的理由:轮次写入是唯一收敛点(文字、双工、跨设备回流
    # 全经过它)。只看用户轮次 —— 助手的回复不改变"在做哪件事"。
    if role == "user":
        try:
            from core.focus_stack import get_focus_stack

            get_focus_stack(conversation_session_id).observe(content)
        except Exception as exc:  # noqa: BLE001
            logger.debug("焦点栈更新跳过(非致命): %s", exc)

    try:
        from core.anticipatory_context import get_anticipatory_context

        _aci = get_anticipatory_context()
        _aci.note_turn_recorded(conversation_session_id, role)
        if role == "assistant":
            _last_user = ""
            for _turn in reversed(get_session_context(conversation_session_id, max_turns=6)):
                if _turn.get("role") == "user":
                    _last_user = str(_turn.get("content") or "")
                    break
            _aci.schedule_after_turn(
                conversation_session_id,
                last_user_query=_last_user,
                last_assistant_text=content,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("ACI 轮次钩子跳过(非致命): %s", exc)


def get_session_context(
    conversation_session_id: str,
    *,
    max_turns: int = 10,
) -> List[Dict[str, Any]]:
    # 融合(域3):直读唯一属主 SessionManager(此前先读 WorkingMemory 副本、
    # 再退 SM——两处可能不一致;现在只有一处)。
    if not conversation_session_id:
        return []
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

    预判式上下文注入(ACI)
    ----------------------
    本函数是**同步**的,却要串行跑完 BM25 检索 + 会话历史 + 任务史 + 事件链 +
    向量召回 —— 整段压在请求路径上。ACI 会在上一轮结束后的空档里把它预先算好;
    这里先问一次缓存,命中就直接返回,那段耗时从请求路径上消失。

    命中判定在 :mod:`core.anticipatory_context` 里,四道闸(同会话/轮次未变/
    词法足够接近/一次性)。任何一道不过都是 miss,走下面的原路现算 —— 也就是说
    ACI 关掉或猜错时,本函数的行为与它存在之前**逐字节相同**。
    """
    try:
        from core.anticipatory_context import get_anticipatory_context

        aci = get_anticipatory_context()
        aci.note_context_requested(session_id)
        prefetched = aci.take(session_id, query)
        if prefetched is not None:
            return prefetched
    except Exception as exc:  # noqa: BLE001 — ACI 失灵绝不能让记忆读不出来
        logger.debug("ACI 取用跳过(非致命): %s", exc)

    return build_unified_context_uncached(session_id, query, depth, max_turns)


def build_unified_context_uncached(
    session_id: str,
    query: str = "",
    depth: str = "auto",
    max_turns: int = 10,
) -> List[Dict[str, str]]:
    """真正的组装体 —— 不查 ACI 缓存,永远现算。

    从 :func:`get_unified_context` 里拆出来,是因为 ACI 的预取协程需要一个
    **不会递归进缓存**的入口:它调用的若还是带缓存的那个,预取自己就会去消费
    自己上一次的预取结果,缓存永远填不满、命中率永远是零。
    """
    messages: List[Dict[str, str]] = []

    # 1. Long-term preferences
    try:
        from core.cognitive.long_term_memory import get_long_term_memory

        ltm = get_long_term_memory()
        prefs = ltm.retrieve_all(namespace="preferences")
        if prefs:
            lines = [f"- {e['key']}: {e['value']}" for e in prefs[:10]]
            messages.append(
                {
                    "role": "system",
                    "content": "[Long-term memory — user preferences]\n" + "\n".join(lines),
                }
            )
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
                messages.append(
                    {
                        "role": "system",
                        "content": "[Long-term memory — relevant to query]\n" + "\n".join(lines),
                    }
                )
        except Exception as exc:
            logger.warning("Exception suppressed: %s", exc)

    # 1c. 焦点栈 —— 放在轮次历史**之前**。
    #
    # 轮次历史是扁平的时间流,读到"行了,继续"时,模型只能自己从十几轮里推断这是要
    # 继续哪件事。焦点栈把结构显式化(当前在做什么、被搁下的还有哪些、各搁了多久),
    # 先给结构再给流水,"继续"就有了确定的指代。
    #
    # 只有栈里真有结构可讲时才输出(见 as_context_message):栈里只有一件事的时候
    # 把它复述一遍是纯噪声,轮次历史里已经有了。
    try:
        from core.focus_stack import get_focus_stack

        _focus_msg = get_focus_stack(session_id).as_context_message()
        if _focus_msg:
            messages.append(_focus_msg)
    except Exception as exc:  # noqa: BLE001
        logger.debug("焦点栈上下文跳过(非致命): %s", exc)

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
                    messages.append(
                        {
                            "role": "system",
                            "content": "[Semantic long-term memory]\n" + "\n".join(_lines),
                        }
                    )
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
        from core.session_manager import EvidenceKind, record_evidence

        record_evidence(
            session_id,
            EvidenceKind.NOTE,
            actor="memory.recall",
            payload={"event": "recall", "query": query[:200], "recalled_blocks": len(msgs)},
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
        # recall() 内部经统一记忆层做语义召回,对 Chroma 后端要先把 query 编码成
        # 向量(SentenceTransformer.encode，CPU 密集)。同步函数;在 async __aenter__
        # 里直接调用会占住共享事件循环——offload 到线程,避免每次进入 MemoryScope
        # 都让其它并发请求集体卡顿。
        import asyncio as _aio

        self.context = await _aio.to_thread(
            recall,
            self.session_id,
            self.query,
            depth=self._depth,
            max_turns=self._max_turns,
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
            from core.session_manager import EvidenceKind, record_evidence

            record_evidence(
                self.session_id,
                EvidenceKind.NOTE,
                actor="memory.scope",
                payload={"event": "scope_exit", "errored": exc_type is not None},
            )
        except Exception:  # noqa: BLE001
            pass
        return False
