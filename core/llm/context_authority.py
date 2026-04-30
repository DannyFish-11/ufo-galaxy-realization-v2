"""
core/llm/context_authority.py — Canonical Cognitive Input Assembly Authority
=============================================================================

**L3: Canonicalize cognitive input assembly under a single context authority**

This module is the **single canonical cognitive input assembly authority** for
the Galaxy system.  It sits between the L2 supply authority and actual model
invocation, and is responsible for:

- Assembling prompt inputs, memory, tool context, runtime state, user metadata,
  continuity context, policy constraints, and execution metadata through **one
  canonical assembly path** before provider formatting and execution.
- Making it always explicit which cognitive inputs were assembled, in what order,
  and under whose rules — so there is one authoritative answer to: *"What
  cognitive context did the model actually receive?"*
- Preventing feature-specific, provider-specific, retry, fallback, replay, or
  recovery paths from silently constructing incompatible cognitive context
  realities.

Architecture
------------

.. code-block:: text

    caller  ──▶  CognitiveContextAuthority.assemble(request)   ← L3 context authority
                    │  1. Normalise system prefix (base identity + policy constraints)
                    │  2. Inject soul_policy / agents_policy / user_policy in canonical order
                    │  3. Append memory / continuity context when present
                    │  4. Include conversation history (bounded by max_history_turns)
                    │  5. Append the current user message
                    │  6. Record the full assembly trace
                    ▼
                CognitiveContextAssembly {
                    messages,          ← canonical OpenAI-compatible message list
                    tool_manifest,     ← normalised tool declarations (may be None)
                    assembly_trace,    ← ordered audit list of what was assembled
                    authority,         ← LLM_CONTEXT_AUTHORITY sentinel
                    is_canonical,      ← True for canonical path
                    source_request,    ← the originating CognitiveContextRequest
                }
                    │
                    ▼
                LLMRouteAuthority (L1) / LLMSupplyAuthority (L2)
                    │
                    ▼
                Provider execution layer (MultiLLMRouter)

Authority sentinel
------------------
``LLM_CONTEXT_AUTHORITY = "core.llm.context_authority.CognitiveContextAuthority"``

Import this sentinel to assert that a call site is producing cognitive context
through the canonical assembly authority rather than an ad-hoc, feature-specific,
or provider-specific context builder.

Assembly order contract
-----------------------
The canonical cognitive context is always assembled in the following order:

1. **System message** — constructed from, in order:
   a. ``system_prefix`` (base identity / role string)
   b. ``soul_policy`` (when present — task_execute / hybrid paths only)
   c. ``agents_policy`` (when present)
   d. ``user_policy`` (when present)
   e. ``memory_context`` (when present)
   f. ``continuity_context`` (when present)
   g. ``execution_metadata`` summary (when present)

2. **Conversation history** — the most recent ``max_history_turns`` turns from
   ``conversation_history``, appended in chronological order.

3. **Current user message** — the ``user_message`` appended as the final
   ``{"role": "user", ...}`` entry.

Feature-specific code must not redefine this order.  Provider adapters may
transform the resulting ``messages`` list for format compatibility, but they
must not alter the cognitive meaning of any message content.

Retry / fallback / recovery contract
-------------------------------------
Retry, fallback, and recovery paths must assemble context by calling
``CognitiveContextAuthority.assemble()`` with the same ``CognitiveContextRequest``
as the original path.  They must not rebuild the message list independently.
Any retry-specific metadata may be passed via ``execution_metadata``; the
assembly order and cognitive meaning remain unchanged.

Usage::

    from core.llm.context_authority import (
        LLM_CONTEXT_AUTHORITY,
        CognitiveContextRequest,
        CognitiveContextAssembly,
        CognitiveContextAuthority,
        get_cognitive_context_authority,
    )

    auth = get_cognitive_context_authority()

    assembly = auth.assemble(
        CognitiveContextRequest(
            system_prefix="You are Galaxy, an intelligent AI assistant.",
            user_policy="Respond in English.",
            conversation_history=[{"role": "user", "content": "Hello"}, ...],
            user_message="What can you do?",
            task_type="general",
            feature_context="agent_kernel.chat",
        )
    )

    # Pass assembly.messages to the LLM execution layer.
    response = await llm_router.chat(assembly.messages, task_type="general")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LLM.ContextAuthority")

# ---------------------------------------------------------------------------
# Module authority sentinel
# ---------------------------------------------------------------------------

#: Identifies this module as the **single canonical cognitive input assembly
#: authority**.
#:
#: Import this sentinel to assert that a call site assembles cognitive context
#: through the canonical authority rather than a scattered, feature-specific,
#: or provider-specific builder.
#:
#: See ``docs/MODEL_ROUTING_AUTHORITY.md`` §11 for the full assembly policy.
LLM_CONTEXT_AUTHORITY: str = (
    "core.llm.context_authority.CognitiveContextAuthority"
)


# ---------------------------------------------------------------------------
# CognitiveContextRequest — input contract for context assembly
# ---------------------------------------------------------------------------


@dataclass
class CognitiveContextRequest:
    """Input contract for a cognitive context assembly request.

    All cognitive context assembly requests must be expressed as a
    ``CognitiveContextRequest`` before being submitted to
    :class:`CognitiveContextAuthority`.  This makes the assembly inputs
    explicit and auditable regardless of which feature or execution path
    originated the request.

    Attributes
    ----------
    task_type:
        Task type string (e.g. ``"general"``, ``"reasoning"``,
        ``"coding"``).  Forwarded to the routing layer and included in
        the assembly trace.
    system_prefix:
        Base system identity / role string placed at the start of the
        system message.  When ``None``, the authority uses a canonical
        default identity.
    soul_policy:
        SOUL constraint policy text.  Must only be set for
        ``task_execute`` or ``hybrid`` execution modes; never set for
        ``chat_only`` paths.  Injected into the system message after the
        base prefix when present.
    agents_policy:
        AGENTS policy text injected into the system message after
        ``soul_policy`` when present.
    user_policy:
        USER preference text injected into the system message after
        ``agents_policy`` when present.
    policy_constraints:
        Additional free-form policy constraint strings appended to the
        system message after ``user_policy``.  Each string is included
        verbatim.
    memory_context:
        Long-term or retrieved memory text appended to the system message
        after policy constraints.
    continuity_context:
        Session continuity / replay context text appended to the system
        message after ``memory_context``.
    conversation_history:
        Ordered list of previous conversation turns in OpenAI-compatible
        format (``[{"role": "user"|"assistant", "content": ...}, ...]``).
        The authority includes the most recent ``max_history_turns`` turns.
    tool_manifest:
        Tool declarations in OpenAI-compatible format.  Passed through
        to the assembly without modification; provider adapters may
        reformat as needed.
    user_message:
        The current user message appended as the final
        ``{"role": "user", "content": ...}`` entry.  When ``None``, no
        user message is appended (useful for completion-style prompts).
    session_id:
        Session identifier included in the assembly trace for diagnostics.
    feature_context:
        Freeform label identifying the calling feature or code path
        (e.g. ``"agent_kernel.chat"``, ``"opencode_engine"``,
        ``"agent_factory.llm_generate"``).  Used for logging / audit.
    execution_mode:
        Execution mode hint (e.g. ``"chat_only"``, ``"task_execute"``,
        ``"hybrid"``).  Used for diagnostics and to validate that
        ``soul_policy`` is only present on task paths.
    execution_metadata:
        Optional dict of execution hints (e.g. retry count, recovery
        flag).  Summary is appended to the system message when present.
        Must not change cognitive meaning; conveys operational context only.
    max_history_turns:
        Maximum number of recent conversation history turns to include.
        Defaults to 8.
    """

    task_type: str = "general"
    system_prefix: Optional[str] = None
    soul_policy: Optional[str] = None
    agents_policy: Optional[str] = None
    user_policy: Optional[str] = None
    policy_constraints: Optional[List[str]] = None
    memory_context: Optional[str] = None
    continuity_context: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = None
    tool_manifest: Optional[List[Dict[str, Any]]] = None
    user_message: Optional[str] = None
    session_id: Optional[str] = None
    feature_context: Optional[str] = None
    execution_mode: Optional[str] = None
    execution_metadata: Optional[Dict[str, Any]] = None
    max_history_turns: int = 8

    def __post_init__(self) -> None:
        clamped = max(0, int(self.max_history_turns))
        if clamped != self.max_history_turns:
            logger.debug(
                "CognitiveContextRequest: max_history_turns clamped from %r to %d",
                self.max_history_turns,
                clamped,
            )
        self.max_history_turns = clamped


# ---------------------------------------------------------------------------
# CognitiveContextAssembly — canonical output of context assembly
# ---------------------------------------------------------------------------


@dataclass
class CognitiveContextAssembly:
    """Canonical output of a cognitive context assembly produced by
    :class:`CognitiveContextAuthority`.

    Carries the assembled message list, tool manifest, assembly trace,
    and the authority sentinel so that downstream layers can verify the
    cognitive context originated from the canonical authority.

    Attributes
    ----------
    messages:
        Canonical OpenAI-compatible message list ready for LLM invocation.
        Must not be modified by provider adapters in ways that change
        cognitive meaning.
    tool_manifest:
        Normalised tool declarations, or ``None`` when no tools were
        requested.  Provider adapters may reformat for transport compatibility
        but must not alter tool semantics.
    assembly_trace:
        Ordered list of human-readable strings describing which inputs
        were assembled and in what order.  Used for audit, diagnostics,
        and debugging context provenance.
    authority:
        Always ``LLM_CONTEXT_AUTHORITY`` — identifies the assembly as
        canonical.  Downstream layers MUST check this field when asserting
        that context went through the canonical authority.
    is_canonical:
        ``True`` when the assembly was produced by the canonical authority
        path.  ``False`` only for assemblies synthesised from legacy
        compatibility paths (for auditability).
    source_request:
        The original :class:`CognitiveContextRequest` that produced this
        assembly.
    """

    messages: List[Dict[str, Any]] = field(default_factory=list)
    tool_manifest: Optional[List[Dict[str, Any]]] = None
    assembly_trace: List[str] = field(default_factory=list)
    authority: str = LLM_CONTEXT_AUTHORITY
    is_canonical: bool = True
    source_request: Optional[CognitiveContextRequest] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "messages": list(self.messages),
            "tool_manifest": self.tool_manifest,
            "assembly_trace": list(self.assembly_trace),
            "authority": self.authority,
            "is_canonical": self.is_canonical,
            "source_request": {
                "task_type": self.source_request.task_type,
                "feature_context": self.source_request.feature_context,
                "execution_mode": self.source_request.execution_mode,
                "session_id": self.source_request.session_id,
                "has_soul_policy": bool(self.source_request.soul_policy),
                "has_user_policy": bool(self.source_request.user_policy),
                "has_agents_policy": bool(self.source_request.agents_policy),
                "has_memory_context": bool(self.source_request.memory_context),
                "has_continuity_context": bool(
                    self.source_request.continuity_context
                ),
                "has_tool_manifest": bool(self.source_request.tool_manifest),
                "has_user_message": bool(self.source_request.user_message),
                "history_turns": len(
                    self.source_request.conversation_history or []
                ),
                "max_history_turns": self.source_request.max_history_turns,
            }
            if self.source_request
            else None,
        }


# ---------------------------------------------------------------------------
# CognitiveContextAuthority — canonical assembly authority class
# ---------------------------------------------------------------------------

#: Default system identity used when ``CognitiveContextRequest.system_prefix``
#: is not provided.
_DEFAULT_SYSTEM_PREFIX: str = (
    "You are Galaxy, an intelligent AI assistant."
)


class CognitiveContextAuthority:
    """Single canonical authority for all cognitive input assembly.

    **All cognitive context requests must be assembled through this class.**
    Feature-specific code must not define private prompt / context assembly
    semantics outside this authority.  Provider adapters may transform
    transport format, but they must not define the cognitive world
    independently.

    Responsibilities
    ----------------
    * ``assemble(request)`` — produce a :class:`CognitiveContextAssembly`
      for a given :class:`CognitiveContextRequest`.  This is the **single
      gate** through which all cognitive input assembly must pass.
    * The assembly order is fixed and canonical:
      system message (prefix + policies + memory + continuity) →
      conversation history → user message.
    * Retry, fallback, replay, and recovery paths must use the same
      ``assemble()`` call with the same ``CognitiveContextRequest``; they
      must not rebuild the message list independently.

    The authority sentinel :data:`LLM_CONTEXT_AUTHORITY` is embedded in
    every :class:`CognitiveContextAssembly` produced by ``assemble()``.

    Usage::

        from core.llm.context_authority import (
            get_cognitive_context_authority, CognitiveContextRequest
        )

        auth = get_cognitive_context_authority()
        assembly = auth.assemble(CognitiveContextRequest(
            system_prefix="You are a coding assistant.",
            user_message="Write a Python hello-world program.",
            task_type="coding",
        ))
        response = await llm_router.chat(assembly.messages, task_type="coding")
    """

    # ------------------------------------------------------------------
    # Canonical assembly gate
    # ------------------------------------------------------------------

    def assemble(
        self,
        request: CognitiveContextRequest,
    ) -> CognitiveContextAssembly:
        """Assemble a canonical :class:`CognitiveContextAssembly` for
        *request*.

        This is the **single gate** through which all cognitive input
        assembly must pass.  The assembly order is fixed:

        1. System message:
           a. Base system prefix (default identity when not provided)
           b. Soul policy (task paths only)
           c. Agents policy
           d. User policy
           e. Additional policy constraints
           f. Memory context
           g. Continuity context
           h. Execution metadata summary

        2. Conversation history (bounded by ``max_history_turns``)

        3. Current user message

        Parameters
        ----------
        request:
            The cognitive context request to assemble.

        Returns
        -------
        CognitiveContextAssembly:
            Canonical cognitive context assembly with authority sentinel
            set to ``LLM_CONTEXT_AUTHORITY``.
        """
        trace: List[str] = []
        messages: List[Dict[str, Any]] = []

        # ── 1. System message ─────────────────────────────────────────
        system_parts: List[str] = []

        # Validate soul_policy / execution_mode contract.
        # soul_policy must only be set for task_execute or hybrid paths.
        if request.soul_policy and request.execution_mode == "chat_only":
            logger.warning(
                "CognitiveContextAuthority.assemble: soul_policy is set but "
                "execution_mode='chat_only' — soul_policy must only be present "
                "on task_execute or hybrid paths. Proceeding with assembly "
                "but this represents a context authority violation."
            )

        # 1a. Base system prefix
        prefix = (request.system_prefix or _DEFAULT_SYSTEM_PREFIX).strip()
        system_parts.append(prefix)
        trace.append(
            f"system_prefix: {'custom' if request.system_prefix else 'default'}"
        )

        # 1b. Soul policy (task_execute / hybrid paths only)
        # Note: Section labels are intentionally in Chinese to match the
        # existing Galaxy codebase policy / system prompt conventions.
        if request.soul_policy:
            system_parts.append(f"\nSOUL 约束：\n{request.soul_policy.strip()}")
            trace.append("soul_policy: injected")
        else:
            trace.append("soul_policy: absent")

        # 1c. Agents policy
        if request.agents_policy:
            system_parts.append(
                f"\nAgents 策略：\n{request.agents_policy.strip()}"
            )
            trace.append("agents_policy: injected")
        else:
            trace.append("agents_policy: absent")

        # 1d. User policy
        if request.user_policy:
            system_parts.append(
                f"\n用户偏好：\n{request.user_policy.strip()}"
            )
            trace.append("user_policy: injected")
        else:
            trace.append("user_policy: absent")

        # 1e. Additional policy constraints
        if request.policy_constraints:
            for constraint in request.policy_constraints:
                if constraint and constraint.strip():
                    system_parts.append(f"\n{constraint.strip()}")
            trace.append(
                f"policy_constraints: {len(request.policy_constraints)} injected"
            )
        else:
            trace.append("policy_constraints: absent")

        # 1f. Memory context
        if request.memory_context:
            system_parts.append(
                f"\n记忆上下文：\n{request.memory_context.strip()}"
            )
            trace.append("memory_context: injected")
        else:
            trace.append("memory_context: absent")

        # 1g. Continuity context
        if request.continuity_context:
            system_parts.append(
                f"\n连续性上下文：\n{request.continuity_context.strip()}"
            )
            trace.append("continuity_context: injected")
        else:
            trace.append("continuity_context: absent")

        # 1h. Execution metadata summary
        if request.execution_metadata:
            meta_parts = []
            for k, v in request.execution_metadata.items():
                meta_parts.append(f"{k}={v}")
            if meta_parts:
                system_parts.append(
                    f"\n执行上下文：{', '.join(meta_parts)}"
                )
                trace.append(
                    f"execution_metadata: {len(meta_parts)} entries injected"
                )
        else:
            trace.append("execution_metadata: absent")

        system_content = "\n".join(system_parts)
        messages.append({"role": "system", "content": system_content})
        trace.append("system_message: assembled")

        # ── 2. Conversation history ────────────────────────────────────
        history = request.conversation_history or []
        if history and request.max_history_turns > 0:
            bounded = history[-request.max_history_turns :]
            messages.extend(bounded)
            trace.append(
                f"conversation_history: {len(bounded)}/{len(history)} turns included"
                f" (max={request.max_history_turns})"
            )
        elif history and request.max_history_turns == 0:
            trace.append(
                f"conversation_history: 0/{len(history)} turns included"
                f" (max=0, all history suppressed)"
            )
        else:
            trace.append("conversation_history: absent")

        # ── 3. Current user message ────────────────────────────────────
        if request.user_message is not None:
            messages.append(
                {"role": "user", "content": request.user_message}
            )
            trace.append("user_message: appended")
        else:
            trace.append("user_message: absent")

        # ── Tool manifest passthrough ──────────────────────────────────
        tool_manifest = request.tool_manifest or None
        if tool_manifest is not None:
            trace.append(f"tool_manifest: {len(tool_manifest)} tools")
        else:
            trace.append("tool_manifest: absent")

        logger.debug(
            "CognitiveContextAuthority.assemble: task=%s feature=%s "
            "execution_mode=%s messages=%d trace=%s",
            request.task_type,
            request.feature_context or "unset",
            request.execution_mode or "unset",
            len(messages),
            trace,
        )

        return CognitiveContextAssembly(
            messages=messages,
            tool_manifest=tool_manifest,
            assembly_trace=trace,
            authority=LLM_CONTEXT_AUTHORITY,
            is_canonical=True,
            source_request=request,
        )


# ---------------------------------------------------------------------------
# Module-level singleton and factory
# ---------------------------------------------------------------------------

_authority_instance: Optional[CognitiveContextAuthority] = None


def get_cognitive_context_authority() -> CognitiveContextAuthority:
    """Return the module-level :class:`CognitiveContextAuthority` singleton.

    This is the canonical factory function.  All call sites that previously
    assembled cognitive context (messages, memory, policy, tools) ad-hoc
    or in feature-specific helpers should use this function so that every
    cognitive input assembly path is visible in the authority layer.

    Returns
    -------
    CognitiveContextAuthority:
        The canonical cognitive input assembly authority instance.
    """
    global _authority_instance
    if _authority_instance is None:
        _authority_instance = CognitiveContextAuthority()
    return _authority_instance


def refresh_cognitive_context_authority() -> CognitiveContextAuthority:
    """Reset and re-create the module-level :class:`CognitiveContextAuthority`
    singleton.

    Intended for use in test teardown or when the authority configuration
    has changed and a fresh instance is needed.

    Returns
    -------
    CognitiveContextAuthority:
        A freshly created :class:`CognitiveContextAuthority` instance.
    """
    global _authority_instance
    _authority_instance = CognitiveContextAuthority()
    return _authority_instance


__all__ = [
    # authority sentinel
    "LLM_CONTEXT_AUTHORITY",
    # request / assembly types
    "CognitiveContextRequest",
    "CognitiveContextAssembly",
    # authority class and factory
    "CognitiveContextAuthority",
    "get_cognitive_context_authority",
    "refresh_cognitive_context_authority",
]
