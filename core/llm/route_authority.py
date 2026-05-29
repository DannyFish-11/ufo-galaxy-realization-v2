"""
core/llm/route_authority.py — Canonical LLM Route Authority
============================================================

**L1: Unify LLM routing under a single router authority**

This module is the **single canonical LLM routing authority** for all
cognitive / LLM model-selection decisions in the Galaxy system.

Architecture
------------
All LLM routing decisions must flow through :class:`LLMRouteAuthority` before
reaching provider supply and execution.  The authority layer is intentionally
separated from the provider supply layer (:class:`~core.multi_llm_router.MultiLLMRouter`):

    caller  ──▶  LLMRouteAuthority.resolve(request)   ← routing authority
                    │  (decides: provider, model, reason, fallbacks)
                    ▼
                LLMRouteDecision                        ← canonical decision object
                    │
                    ▼
                MultiLLMRouter (provider supply)        ← supply + execution layer
                    │
                    ▼
                LLMResponse

Authority sentinel
------------------
``LLM_ROUTE_AUTHORITY = "core.llm.route_authority.LLMRouteAuthority"``

Import this sentinel to assert that a call site is going through the canonical
LLM routing authority rather than reaching directly into provider-specific or
feature-specific routing paths.

Backward-compatibility note
---------------------------
Provider execution (:class:`~core.multi_llm_router.MultiLLMRouter`) is still
used as the supply layer.  Callers that previously imported
``from core.multi_llm_router import get_llm_router`` for *execution* should
use ``get_llm_route_authority().execution_router`` instead, so the routing
decision is always visible and goes through the canonical authority.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("Galaxy.LLM.RouteAuthority")

# ---------------------------------------------------------------------------
# Module authority sentinel
# ---------------------------------------------------------------------------

#: Identifies this module as the **single canonical LLM routing authority**.
#:
#: Import this sentinel to assert that LLM routing decisions flow through the
#: canonical authority rather than scattered feature-specific or
#: provider-specific paths.
#:
#: See ``docs/MODEL_ROUTING_AUTHORITY.md`` §L1 for the full routing policy.
LLM_ROUTE_AUTHORITY: str = "core.llm.route_authority.LLMRouteAuthority"

# ---------------------------------------------------------------------------
# LLMRouteRequest — input to the routing authority
# ---------------------------------------------------------------------------


@dataclass
class LLMRouteRequest:
    """Input contract for an LLM routing decision.

    All routing requests must be expressed as an ``LLMRouteRequest`` before
    being submitted to :class:`LLMRouteAuthority`.  This makes the routing
    inputs explicit and auditable regardless of which feature or layer
    originated the request.

    Attributes
    ----------
    task_type:
        Task type string (e.g. ``"general"``, ``"reasoning"``,
        ``"fast_response"``).  When the caller holds a
        :class:`~core.multi_llm_router.TaskType` enum value they may pass it
        directly; it will be coerced to its string value.
    complexity:
        Complexity score for the task [0.0, 1.0].  Higher values bias toward
        heavier models.  Defaults to 0.5 (medium complexity).
    preferred_provider:
        Optional caller preference for a specific provider.  The authority
        will honour this request if the provider is available; otherwise it
        falls through to the policy-based selection.
    feature_context:
        Freeform label identifying the calling feature or code path
        (e.g. ``"agent_control"``, ``"intent_parse"``, ``"swarm_create"``).
        Used for logging / diagnostics only.
    mode:
        Optional routing mode hint (e.g. ``"standard"``, ``"fallback"``,
        ``"compatibility"``).  Informational; does not override the authority's
        policy-based decision.
    """

    task_type: str = "general"
    complexity: float = 0.5
    preferred_provider: Optional[str] = None
    feature_context: Optional[str] = None
    mode: Optional[str] = None

    def __post_init__(self) -> None:
        # Accept TaskType enum values transparently.
        if hasattr(self.task_type, "value"):
            self.task_type = self.task_type.value  # type: ignore[assignment]
        self.complexity = max(0.0, min(1.0, float(self.complexity)))


# ---------------------------------------------------------------------------
# LLMRouteDecision — output of the routing authority
# ---------------------------------------------------------------------------


@dataclass
class LLMRouteDecision:
    """Canonical output of a routing decision made by :class:`LLMRouteAuthority`.

    Carries the selected provider, model, routing rationale, and the
    authority sentinel so that downstream layers can verify the decision
    originated from the canonical authority rather than a scattered bypass
    path.

    Attributes
    ----------
    provider:
        Selected provider identifier (e.g. ``"openai"``, ``"anthropic"``).
    model:
        Selected model identifier (e.g. ``"gpt-5.5"``, ``"claude-sonnet-4-6-20251022"``).
    reason:
        Human-readable explanation of why this provider/model was selected.
    alternatives:
        Ordered list of ``"provider:model"`` fallback strings considered
        during routing (excludes the selected primary entry).
    authority:
        Always ``LLM_ROUTE_AUTHORITY`` — identifies the routing decision as
        canonical.  Downstream layers MUST check this field when asserting
        that routing went through the canonical authority.
    is_canonical:
        ``True`` when the decision was produced by the canonical authority
        path.  ``False`` only for decisions that were synthesised from legacy
        compat paths (for auditability).
    source_request:
        The original :class:`LLMRouteRequest` that produced this decision.
    """

    provider: str
    model: str
    reason: str
    alternatives: List[str] = field(default_factory=list)
    authority: str = LLM_ROUTE_AUTHORITY
    is_canonical: bool = True
    source_request: Optional[LLMRouteRequest] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        return {
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "alternatives": list(self.alternatives),
            "authority": self.authority,
            "is_canonical": self.is_canonical,
            "source_request": {
                "task_type": self.source_request.task_type,
                "complexity": self.source_request.complexity,
                "preferred_provider": self.source_request.preferred_provider,
                "feature_context": self.source_request.feature_context,
                "mode": self.source_request.mode,
            } if self.source_request else None,
        }


# ---------------------------------------------------------------------------
# LLMRouteAuthority — canonical routing authority class
# ---------------------------------------------------------------------------


class LLMRouteAuthority:
    """Single canonical authority for all LLM model-selection decisions.

    **All cognitive / LLM routing requests must flow through this class.**
    Provider-specific code must not act as a de-facto route authority.
    Feature-specific code must not define private routing semantics when a
    canonical router decision should exist.

    Responsibilities
    ----------------
    * ``resolve(request)`` — produce a :class:`LLMRouteDecision` for a
      given :class:`LLMRouteRequest`.  This is the **single gate** through
      which all routing intent must pass.
    * ``execution_router`` — expose the underlying ``MultiLLMRouter`` for
      provider supply execution.  Callers that need to execute LLM calls
      should use this property rather than importing ``get_llm_router()``
      directly from ``core.multi_llm_router``.
    * ``chat`` / ``chat_with_tools`` / ``chat_json`` — convenience wrappers
      that call ``resolve()`` first and then delegate execution to the
      provider supply layer.

    The authority sentinel :data:`LLM_ROUTE_AUTHORITY` is embedded in every
    :class:`LLMRouteDecision` produced by ``resolve()``.

    Usage::

        from core.llm.route_authority import get_llm_route_authority, LLMRouteRequest

        authority = get_llm_route_authority()

        # Pure routing decision:
        decision = authority.resolve(LLMRouteRequest(task_type="reasoning", complexity=0.8))

        # Routed execution (routing decision is resolved first internally):
        response = await authority.chat(messages, task_type="agent_control")
    """

    def __init__(self, router=None) -> None:
        """Initialise the authority.

        Parameters
        ----------
        router:
            Optional ``MultiLLMRouter`` instance.  When ``None``, the
            module-level :func:`get_llm_router` factory is called lazily on
            first use.
        """
        self._router = router

    # ------------------------------------------------------------------
    # Provider supply access
    # ------------------------------------------------------------------

    @property
    def execution_router(self):
        """Return the underlying ``MultiLLMRouter`` for provider supply.

        Callers that need to execute LLM requests should use this property
        rather than importing ``get_llm_router()`` directly, so that the
        routing authority stays in the chain.
        """
        if self._router is None:
            from core.multi_llm_router import get_llm_router
            self._router = get_llm_router()
        return self._router

    # ------------------------------------------------------------------
    # Canonical routing decision gate
    # ------------------------------------------------------------------

    def resolve(self, request: LLMRouteRequest) -> LLMRouteDecision:
        """Produce a canonical :class:`LLMRouteDecision` for *request*.

        This is the **single gate** through which all LLM routing intent
        must pass.  Routing is delegated to the underlying
        ``MultiLLMRouter`` policy layer; the result is wrapped in an
        :class:`LLMRouteDecision` carrying the ``LLM_ROUTE_AUTHORITY``
        sentinel.

        Parameters
        ----------
        request:
            The routing request to resolve.

        Returns
        -------
        LLMRouteDecision:
            Canonical routing decision with authority sentinel set to
            ``LLM_ROUTE_AUTHORITY``.
        """
        from core.multi_llm_router import TaskType

        # Coerce task_type string to TaskType enum (provider layer expectation).
        try:
            task_type_enum = TaskType(request.task_type)
        except ValueError:
            task_type_enum = TaskType.GENERAL

        routing_decision = self.execution_router.route(
            task_type=task_type_enum,
            preferred_provider=request.preferred_provider,
            complexity_score=request.complexity,
        )

        decision = LLMRouteDecision(
            provider=routing_decision.provider,
            model=routing_decision.model,
            reason=routing_decision.reason,
            alternatives=list(routing_decision.alternatives),
            authority=LLM_ROUTE_AUTHORITY,
            is_canonical=True,
            source_request=request,
        )

        logger.debug(
            "LLMRouteAuthority.resolve: task=%s complexity=%.2f → provider=%s model=%s",
            request.task_type,
            request.complexity,
            decision.provider,
            decision.model,
        )
        return decision

    # ------------------------------------------------------------------
    # Routed execution convenience wrappers
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        task_type: Union[str, Any] = "general",
        complexity: float = 0.5,
        preferred_provider: Optional[str] = None,
        feature_context: Optional[str] = None,
        **kwargs: Any,
    ):
        """Resolve a routing decision then execute via the provider supply layer.

        Parameters
        ----------
        messages:
            Conversation messages (OpenAI-compatible format).
        task_type:
            Task type string or enum.
        complexity:
            Task complexity score [0.0, 1.0].
        preferred_provider:
            Optional provider preference.
        feature_context:
            Freeform label for the calling feature (diagnostics only).
        **kwargs:
            Extra keyword arguments forwarded to ``MultiLLMRouter.chat()``.
        """
        self.resolve(LLMRouteRequest(
            task_type=task_type,
            complexity=complexity,
            preferred_provider=preferred_provider,
            feature_context=feature_context,
        ))
        return await self.execution_router.chat(
            messages=messages,
            task_type=task_type,
            **kwargs,
        )

    async def chat_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        task_type: Union[str, Any] = "agent_control",
        complexity: float = 0.5,
        preferred_provider: Optional[str] = None,
        feature_context: Optional[str] = None,
        **kwargs: Any,
    ):
        """Resolve a routing decision then execute with tool support.

        Parameters
        ----------
        messages:
            Conversation messages.
        tools:
            Tool declarations for the LLM.
        task_type:
            Task type string or enum.
        complexity:
            Task complexity score [0.0, 1.0].
        preferred_provider:
            Optional provider preference.
        feature_context:
            Freeform label for the calling feature (diagnostics only).
        **kwargs:
            Extra keyword arguments forwarded to the execution router.
        """
        self.resolve(LLMRouteRequest(
            task_type=task_type,
            complexity=complexity,
            preferred_provider=preferred_provider,
            feature_context=feature_context,
        ))
        router = self.execution_router
        if hasattr(router, "chat_with_tools"):
            return await router.chat_with_tools(
                messages=messages,
                tools=tools,
                task_type=task_type,
                **kwargs,
            )
        return await router.chat(
            messages=messages,
            tools=tools,
            task_type=task_type,
            **kwargs,
        )

    async def chat_json(
        self,
        messages: List[Dict[str, Any]],
        task_type: Union[str, Any] = "general",
        complexity: float = 0.5,
        preferred_provider: Optional[str] = None,
        feature_context: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Resolve a routing decision then execute expecting a JSON response.

        Parameters
        ----------
        messages:
            Conversation messages.
        task_type:
            Task type string or enum.
        complexity:
            Task complexity score [0.0, 1.0].
        preferred_provider:
            Optional provider preference.
        feature_context:
            Freeform label for the calling feature (diagnostics only).
        **kwargs:
            Extra keyword arguments forwarded to the execution router.
        """
        self.resolve(LLMRouteRequest(
            task_type=task_type,
            complexity=complexity,
            preferred_provider=preferred_provider,
            feature_context=feature_context,
        ))
        return await self.execution_router.chat_json(
            messages=messages,
            task_type=task_type,
            **kwargs,
        )


# ---------------------------------------------------------------------------
# Module-level singleton and factory
# ---------------------------------------------------------------------------

_authority_instance: Optional[LLMRouteAuthority] = None


def get_llm_route_authority() -> LLMRouteAuthority:
    """Return the module-level :class:`LLMRouteAuthority` singleton.

    This is the canonical factory function.  All callers that previously used
    ``from core.multi_llm_router import get_llm_router`` for making routing
    decisions or obtaining a router for execution should switch to this
    function, so that every LLM routing path is visible in the authority layer.

    Returns
    -------
    LLMRouteAuthority:
        The canonical LLM routing authority instance.
    """
    global _authority_instance
    if _authority_instance is None:
        _authority_instance = LLMRouteAuthority()
    return _authority_instance


def refresh_llm_route_authority() -> LLMRouteAuthority:
    """Reset and re-create the module-level :class:`LLMRouteAuthority` singleton.

    Intended for use in test teardown or when the provider configuration has
    changed and the authority should pick up a fresh ``MultiLLMRouter``.

    Returns
    -------
    LLMRouteAuthority:
        A freshly created :class:`LLMRouteAuthority` instance.
    """
    global _authority_instance
    _authority_instance = LLMRouteAuthority()
    return _authority_instance


__all__ = [
    # authority sentinel
    "LLM_ROUTE_AUTHORITY",
    # request / decision types
    "LLMRouteRequest",
    "LLMRouteDecision",
    # authority class and factory
    "LLMRouteAuthority",
    "get_llm_route_authority",
    "refresh_llm_route_authority",
]
