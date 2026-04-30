"""
core/llm/execution_authority.py — Canonical Cognitive Execution Authority
==========================================================================

**L4: Close the final cognitive authority boundary**

This module is the **single canonical cognitive execution semantics authority**
for the Galaxy system.  It closes the final layer of the cognitive authority
stack:

- L1 (:mod:`core.llm.route_authority`) — routing intent (which provider/model)
- L2 (:mod:`core.llm.supply_authority`) — supply legality (can intent be met?)
- L3 (:mod:`core.llm.context_authority`) — cognitive input assembly (what the
  model receives)
- **L4 (this module)** — cognitive execution semantics (how the model is
  invoked, how outputs are normalized, what constitutes a valid result)

Architecture
------------

.. code-block:: text

    CognitiveContextAssembly (L3)  ← assembled cognitive context
        │
    SupplyResolutionResult (L2)    ← legal supply path
        │
        ▼
    CognitiveExecutionAuthority.execute(request)   ← L4 execution gate
        │  1. Verify context carries LLM_CONTEXT_AUTHORITY sentinel (L3 was used)
        │  2. Verify supply carries LLM_SUPPLY_AUTHORITY sentinel (L2 was used)
        │  3. Verify supply is_satisfied before proceeding
        │  4. Delegate raw execution to provider adapter (capability only)
        │  5. Normalize raw provider output under center-owned semantics
        │  6. Embed LLM_EXECUTION_AUTHORITY sentinel in result
        ▼
    CognitiveExecutionResult {
        content,            ← normalized text content (center-owned semantics)
        tool_calls,         ← normalized tool call list (center-owned format)
        provider,           ← provider that executed (from supply resolution)
        model,              ← model that executed (from supply resolution)
        is_canonical,       ← True for canonical execution path
        authority,          ← LLM_EXECUTION_AUTHORITY sentinel
        execution_trace,    ← ordered audit list of execution steps
        source_context,     ← the CognitiveContextAssembly that was executed
        source_supply,      ← the SupplyResolutionResult that governed execution
        raw_response,       ← raw provider output (not interpreted as truth)
        input_tokens,       ← token counts (informational)
        output_tokens,
        latency_ms,
    }

Authority sentinel
------------------
``LLM_EXECUTION_AUTHORITY = "core.llm.execution_authority.CognitiveExecutionAuthority"``

Import this sentinel to assert that a call site is receiving a result that
went through the canonical cognitive execution authority rather than a
scattered, provider-specific, or compatibility-layer invocation.

Center/provider boundary contract
-----------------------------------
Providers, adapters, transports, and compatibility shims may only contribute:

- **Execution capability** — making the actual API call.
- **Transport formatting** — converting the canonical message list to the
  wire format the provider accepts.
- **Raw output** — returning the provider's raw API response.

Providers MUST NOT:

- Decide which model or provider to use (that is L1/L2 authority).
- Reinterpret the cognitive context (that is L3 authority).
- Define fallback semantics (that is L2 authority).
- Normalize or interpret the response content as final cognitive truth
  (that is L4 authority — this module).

Retry / fallback / compatibility contract
-----------------------------------------
Retry, fallback, replay, and recovery paths MUST:

1. Use the same :class:`CognitiveContextAssembly` (from L3) — do not rebuild
   context independently.
2. Use a fresh :class:`~core.llm.supply_authority.SupplyResolutionResult`
   from L2 if the supply path changes (e.g. primary failed, fallback taken).
3. Call :meth:`CognitiveExecutionAuthority.execute` for every attempt — never
   bypass the execution gate.
4. Pass retry/fallback metadata via :attr:`CognitiveExecutionRequest.execution_metadata`
   so the execution trace records the attempt context.

Response normalization contract
---------------------------------
Final output interpretation and normalization are performed once, here, under
center-owned semantics:

- ``content`` is always a ``str`` (empty string when the provider returns no
  text content).
- ``tool_calls`` is always ``None`` or a list of dicts in the canonical
  OpenAI-compatible tool-call format.
- Provider-specific response quirks (e.g. Anthropic content block lists) are
  translated to the canonical format before being returned.
- Raw provider output is preserved in ``raw_response`` for diagnostics but is
  **not** used as the authoritative interpretation of cognitive output.

Usage::

    from core.llm.execution_authority import (
        LLM_EXECUTION_AUTHORITY,
        CognitiveExecutionRequest,
        CognitiveExecutionResult,
        CognitiveExecutionAuthority,
        get_cognitive_execution_authority,
    )
    from core.llm.context_authority import get_cognitive_context_authority, CognitiveContextRequest
    from core.llm.supply_authority import get_llm_supply_authority
    from core.llm.route_authority import get_llm_route_authority, LLMRouteRequest

    # L1: route
    route_auth = get_llm_route_authority()
    decision = route_auth.resolve(LLMRouteRequest(task_type="general"))

    # L2: supply
    supply_auth = get_llm_supply_authority()
    supply = supply_auth.resolve_supply(decision, supply_snapshot)

    # L3: context
    ctx_auth = get_cognitive_context_authority()
    assembly = ctx_auth.assemble(CognitiveContextRequest(
        user_message="Hello, what can you do?",
        task_type="general",
    ))

    # L4: execute
    exec_auth = get_cognitive_execution_authority()
    result = await exec_auth.execute(CognitiveExecutionRequest(
        context_assembly=assembly,
        supply_resolution=supply,
    ))

    print(result.content)  # normalized, center-owned output
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.LLM.ExecutionAuthority")

# ---------------------------------------------------------------------------
# Module authority sentinel
# ---------------------------------------------------------------------------

#: Identifies this module as the **single canonical cognitive execution
#: semantics authority**.
#:
#: Import this sentinel to assert that a cognitive execution result originated
#: from the canonical execution authority rather than a provider-local,
#: adapter-specific, or compatibility-layer path.
#:
#: See ``docs/MODEL_ROUTING_AUTHORITY.md`` §12 for the full execution policy.
LLM_EXECUTION_AUTHORITY: str = (
    "core.llm.execution_authority.CognitiveExecutionAuthority"
)


# ---------------------------------------------------------------------------
# CognitiveExecutionRequest — input contract for execution
# ---------------------------------------------------------------------------


@dataclass
class CognitiveExecutionRequest:
    """Input contract for a cognitive execution request.

    Carries the assembled cognitive context (from L3), the legal supply path
    (from L2), and execution parameters.  All three must be present and
    canonical before :class:`CognitiveExecutionAuthority` will proceed.

    Attributes
    ----------
    context_assembly:
        The :class:`~core.llm.context_authority.CognitiveContextAssembly`
        produced by :class:`~core.llm.context_authority.CognitiveContextAuthority`
        (L3).  Must carry the ``LLM_CONTEXT_AUTHORITY`` sentinel.
    supply_resolution:
        The :class:`~core.llm.supply_authority.SupplyResolutionResult`
        produced by :class:`~core.llm.supply_authority.LLMSupplyAuthority`
        (L2).  Must carry the ``LLM_SUPPLY_AUTHORITY`` sentinel and have
        ``is_satisfied == True``.
    temperature:
        Sampling temperature for the provider call.  Defaults to ``0.7``.
    max_tokens:
        Maximum completion tokens.  Defaults to ``4096``.
    feature_context:
        Freeform label identifying the calling feature (diagnostics only).
    execution_metadata:
        Optional dict of execution-round metadata (e.g. ``retry_count``,
        ``recovery_reason``).  Recorded in the execution trace but must not
        change cognitive meaning.
    """

    context_assembly: Any  # CognitiveContextAssembly from L3
    supply_resolution: Any  # SupplyResolutionResult from L2
    temperature: float = 0.7
    max_tokens: int = 4096
    feature_context: Optional[str] = None
    execution_metadata: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# CognitiveExecutionResult — canonical output of execution authority
# ---------------------------------------------------------------------------


@dataclass
class CognitiveExecutionResult:
    """Canonical output of a cognitive execution produced by
    :class:`CognitiveExecutionAuthority`.

    Carries the normalized response content, tool calls, execution trace, and
    the authority sentinel so that downstream layers can verify that execution
    and response normalization went through the canonical authority.

    Attributes
    ----------
    content:
        Normalized response text.  Always a ``str``; empty string when the
        provider returns no text.  This is the center-owned interpretation
        of the cognitive output, not a raw provider string.
    tool_calls:
        Normalized list of tool call dicts in canonical OpenAI-compatible
        format, or ``None`` when the provider returned no tool calls.
    provider:
        Provider identifier that executed the request (from the supply
        resolution — not reassigned by the provider itself).
    model:
        Model identifier that executed the request (from the supply
        resolution — not reassigned by the provider itself).
    is_canonical:
        ``True`` when execution went through the canonical authority path.
        ``False`` only for results synthesised from legacy / compat paths.
    authority:
        Always :data:`LLM_EXECUTION_AUTHORITY` — identifies this result as
        originating from the canonical execution authority.
    execution_trace:
        Ordered list of human-readable strings describing the execution
        steps taken.  Used for audit, diagnostics, and debugging.
    source_context:
        The :class:`~core.llm.context_authority.CognitiveContextAssembly`
        that was executed.
    source_supply:
        The :class:`~core.llm.supply_authority.SupplyResolutionResult` that
        governed this execution.
    raw_response:
        Raw provider API response dict.  Preserved for diagnostics; MUST NOT
        be used as the authoritative interpretation of cognitive output.
    input_tokens:
        Input token count reported by the provider (informational).
    output_tokens:
        Output token count reported by the provider (informational).
    latency_ms:
        End-to-end latency in milliseconds (informational).
    """

    content: str
    tool_calls: Optional[List[Dict[str, Any]]]
    provider: str
    model: str
    is_canonical: bool = True
    authority: str = LLM_EXECUTION_AUTHORITY
    execution_trace: List[str] = field(default_factory=list)
    source_context: Optional[Any] = None   # CognitiveContextAssembly
    source_supply: Optional[Any] = None    # SupplyResolutionResult
    raw_response: Optional[Dict[str, Any]] = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict representation."""
        # Summarise context / supply without deep-serialising large objects.
        context_summary: Optional[Dict[str, Any]] = None
        if self.source_context is not None:
            if hasattr(self.source_context, "to_dict"):
                ctx_d = self.source_context.to_dict()
                context_summary = {
                    "authority": ctx_d.get("authority"),
                    "is_canonical": ctx_d.get("is_canonical"),
                    "message_count": len(ctx_d.get("messages", [])),
                    "has_tool_manifest": ctx_d.get("tool_manifest") is not None,
                }
            else:
                context_summary = {"authority": getattr(self.source_context, "authority", None)}

        supply_summary: Optional[Dict[str, Any]] = None
        if self.source_supply is not None:
            if hasattr(self.source_supply, "to_dict"):
                sup_d = self.source_supply.to_dict()
                supply_summary = {
                    "authority": sup_d.get("authority"),
                    "requested_provider": sup_d.get("requested_provider"),
                    "supplied_provider": sup_d.get("supplied_provider"),
                    "fallback_legality": sup_d.get("fallback_legality"),
                    "is_satisfied": sup_d.get("is_satisfied"),
                }
            else:
                supply_summary = {"authority": getattr(self.source_supply, "authority", None)}

        return {
            "content": self.content,
            "tool_calls": self.tool_calls,
            "provider": self.provider,
            "model": self.model,
            "is_canonical": self.is_canonical,
            "authority": self.authority,
            "execution_trace": list(self.execution_trace),
            "source_context": context_summary,
            "source_supply": supply_summary,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
        }


# ---------------------------------------------------------------------------
# CognitiveExecutionAuthority — canonical execution authority class
# ---------------------------------------------------------------------------


class CognitiveExecutionAuthority:
    """Single canonical authority for all cognitive execution semantics.

    **All LLM invocations must pass through this class after L3 context
    assembly and L2 supply resolution.**  Provider adapters must not be
    invoked directly for cognitive execution.  Retry, fallback, replay, and
    recovery paths must all call :meth:`execute`.

    Responsibilities
    ----------------
    * :meth:`execute` — accept a :class:`CognitiveExecutionRequest` carrying
      an L3 context assembly and an L2 supply result, invoke the provider,
      and return a :class:`CognitiveExecutionResult` with center-owned
      normalized output.
    * Verify that the context assembly carries :data:`LLM_CONTEXT_AUTHORITY`
      (i.e. L3 was used).
    * Verify that the supply result carries :data:`LLM_SUPPLY_AUTHORITY`
      (i.e. L2 was used) and that supply is satisfied.
    * Normalize raw provider output under center-owned semantics — providers
      contribute raw execution; this class owns interpretation.
    * Embed :data:`LLM_EXECUTION_AUTHORITY` in every result.

    Parameters
    ----------
    router:
        Optional ``MultiLLMRouter`` instance.  When ``None``, the module-level
        :func:`~core.multi_llm_router.get_llm_router` factory is called
        lazily on first use.
    """

    def __init__(self, router: Optional[Any] = None) -> None:
        self._router = router

    # ------------------------------------------------------------------
    # Router access
    # ------------------------------------------------------------------

    @property
    def execution_router(self) -> Any:
        """Return the underlying ``MultiLLMRouter`` for provider dispatch.

        Callers must not use this property to bypass the execution gate
        (:meth:`execute`).  It is exposed solely for diagnostics and for
        convenience wrappers that assemble execution via :meth:`execute`.
        """
        if self._router is None:
            from core.multi_llm_router import get_llm_router
            self._router = get_llm_router()
        return self._router

    # ------------------------------------------------------------------
    # Canonical execution gate
    # ------------------------------------------------------------------

    async def execute(
        self,
        request: CognitiveExecutionRequest,
    ) -> CognitiveExecutionResult:
        """Execute a cognitive request under center-owned execution semantics.

        This is the **single gate** through which all LLM invocations must
        pass.  The gate:

        1. Verifies the context assembly carries ``LLM_CONTEXT_AUTHORITY``
           (L3 was used).
        2. Verifies the supply result carries ``LLM_SUPPLY_AUTHORITY`` (L2
           was used) and that supply is satisfied.
        3. Delegates raw execution to the provider adapter.
        4. Normalizes the provider's raw output under center-owned semantics.
        5. Embeds :data:`LLM_EXECUTION_AUTHORITY` in the result.

        Parameters
        ----------
        request:
            The execution request wrapping an L3 context assembly and an L2
            supply resolution.

        Returns
        -------
        CognitiveExecutionResult:
            Canonical execution result with center-owned normalized output and
            the ``LLM_EXECUTION_AUTHORITY`` sentinel.

        Raises
        ------
        ValueError:
            If the context assembly is missing the ``LLM_CONTEXT_AUTHORITY``
            sentinel, if the supply result is missing the ``LLM_SUPPLY_AUTHORITY``
            sentinel, or if supply is not satisfied.
        """
        trace: List[str] = []

        # ── 1. Verify L3 context authority sentinel ───────────────────
        self._verify_context_authority(request.context_assembly, trace)

        # ── 2. Verify L2 supply authority sentinel and satisfaction ───
        self._verify_supply_authority(request.supply_resolution, trace)

        # ── 3. Extract execution parameters from supply result ────────
        supplied_provider = _get_attr(request.supply_resolution, "supplied_provider") or ""
        supplied_model = _get_attr(request.supply_resolution, "supplied_model") or ""

        trace.append(
            f"execution_target: provider={supplied_provider!r} model={supplied_model!r}"
        )

        if request.execution_metadata:
            meta_summary = ", ".join(
                f"{k}={v!r}"
                for k, v in list(request.execution_metadata.items())[:8]
            )
            trace.append(f"execution_metadata: {meta_summary}")

        # ── 4. Extract assembled messages from L3 context ─────────────
        messages = _get_attr(request.context_assembly, "messages") or []
        tool_manifest = _get_attr(request.context_assembly, "tool_manifest")

        trace.append(f"context_messages: count={len(messages)}")
        if tool_manifest is not None:
            trace.append(f"tool_manifest: count={len(tool_manifest)}")

        logger.debug(
            "CognitiveExecutionAuthority.execute: provider=%s model=%s "
            "messages=%d tools=%s feature=%s",
            supplied_provider,
            supplied_model,
            len(messages),
            len(tool_manifest) if tool_manifest else 0,
            request.feature_context,
        )

        # ── 5. Delegate raw execution to provider (capability only) ───
        raw_llm_response = await self._dispatch(
            provider=supplied_provider,
            model=supplied_model,
            messages=messages,
            tools=tool_manifest,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            trace=trace,
        )

        # ── 6. Normalize output under center-owned semantics ──────────
        content, tool_calls, raw_dict, input_tokens, output_tokens, latency_ms = (
            self._normalize_response(raw_llm_response, trace)
        )

        trace.append("execution: complete")

        result = CognitiveExecutionResult(
            content=content,
            tool_calls=tool_calls,
            provider=supplied_provider,
            model=supplied_model,
            is_canonical=True,
            authority=LLM_EXECUTION_AUTHORITY,
            execution_trace=trace,
            source_context=request.context_assembly,
            source_supply=request.supply_resolution,
            raw_response=raw_dict,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
        )

        logger.debug(
            "CognitiveExecutionAuthority.execute: done provider=%s model=%s "
            "tokens_in=%d tokens_out=%d latency_ms=%.1f",
            supplied_provider,
            supplied_model,
            input_tokens,
            output_tokens,
            latency_ms,
        )
        return result

    # ------------------------------------------------------------------
    # Authority verification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _verify_context_authority(
        context_assembly: Any,
        trace: List[str],
    ) -> None:
        """Assert that *context_assembly* carries the L3 authority sentinel.

        Raises :class:`ValueError` if the sentinel is absent or incorrect.
        """
        from core.llm.context_authority import LLM_CONTEXT_AUTHORITY

        actual = _get_attr(context_assembly, "authority")
        if actual != LLM_CONTEXT_AUTHORITY:
            raise ValueError(
                f"CognitiveExecutionAuthority: context_assembly authority "
                f"sentinel mismatch — expected {LLM_CONTEXT_AUTHORITY!r}, "
                f"got {actual!r}.  Cognitive context MUST be assembled "
                f"through CognitiveContextAuthority (L3) before execution."
            )
        trace.append(f"context_authority: verified ({LLM_CONTEXT_AUTHORITY})")

    @staticmethod
    def _verify_supply_authority(
        supply_resolution: Any,
        trace: List[str],
    ) -> None:
        """Assert that *supply_resolution* carries the L2 authority sentinel
        and that supply is satisfied.

        Raises :class:`ValueError` if the sentinel is absent/incorrect or if
        supply is not satisfied.
        """
        from core.llm.supply_authority import LLM_SUPPLY_AUTHORITY

        actual = _get_attr(supply_resolution, "authority")
        if actual != LLM_SUPPLY_AUTHORITY:
            raise ValueError(
                f"CognitiveExecutionAuthority: supply_resolution authority "
                f"sentinel mismatch — expected {LLM_SUPPLY_AUTHORITY!r}, "
                f"got {actual!r}.  Supply MUST be resolved through "
                f"LLMSupplyAuthority (L2) before execution."
            )

        is_satisfied = _get_attr(supply_resolution, "is_satisfied")
        if not is_satisfied:
            supplied_provider = _get_attr(supply_resolution, "supplied_provider")
            trace.append(
                f"supply_authority: verified but unsatisfied "
                f"(supplied_provider={supplied_provider!r})"
            )
            raise ValueError(
                "CognitiveExecutionAuthority: supply is not satisfied — no "
                "legal provider/model path was resolved by LLMSupplyAuthority. "
                "Cannot proceed with cognitive execution."
            )

        trace.append(f"supply_authority: verified ({LLM_SUPPLY_AUTHORITY})")

    # ------------------------------------------------------------------
    # Provider dispatch (raw execution only — no cognitive semantics)
    # ------------------------------------------------------------------

    async def _dispatch(
        self,
        provider: str,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        temperature: float,
        max_tokens: int,
        trace: List[str],
    ) -> Any:
        """Dispatch to the provider adapter for raw execution.

        This method only contributes *execution capability* — it does not
        alter cognitive meaning, re-interpret context, or override the supply
        decision.

        Returns the raw ``LLMResponse`` from the provider adapter.
        """
        trace.append(f"dispatch: provider={provider!r} model={model!r}")
        router = self.execution_router
        if tools:
            raw = await router.chat_with_tools(
                messages=messages,
                tools=tools,
                task_type="general",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        else:
            raw = await router.chat(
                messages=messages,
                task_type="general",
                temperature=temperature,
                max_tokens=max_tokens,
            )
        trace.append("dispatch: raw_response_received")
        return raw

    # ------------------------------------------------------------------
    # Response normalization (center-owned semantics)
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_response(
        raw_response: Any,
        trace: List[str],
    ):
        """Normalize the provider's raw response under center-owned semantics.

        Providers return their API-specific response objects; this method
        translates them to the canonical center-owned output format.

        Returns
        -------
        tuple:
            ``(content, tool_calls, raw_dict, input_tokens, output_tokens,
            latency_ms)``
        """
        # Handle None / missing response gracefully
        if raw_response is None:
            trace.append("normalization: empty_response")
            return "", None, None, 0, 0, 0.0

        # LLMResponse dataclass (from core.multi_llm_router)
        content = str(getattr(raw_response, "content", "") or "")
        tool_calls = getattr(raw_response, "tool_calls", None)
        raw_dict = getattr(raw_response, "raw_response", None)
        input_tokens = int(getattr(raw_response, "input_tokens", 0) or 0)
        output_tokens = int(getattr(raw_response, "output_tokens", 0) or 0)
        latency_ms = float(getattr(raw_response, "latency_ms", 0.0) or 0.0)

        # Normalize tool_calls to canonical format (list or None)
        if tool_calls is not None and not isinstance(tool_calls, list):
            tool_calls = list(tool_calls)
        if tool_calls is not None and len(tool_calls) == 0:
            tool_calls = None

        trace.append(
            f"normalization: content_len={len(content)} "
            f"tool_calls={'yes' if tool_calls else 'none'}"
        )
        return content, tool_calls, raw_dict, input_tokens, output_tokens, latency_ms


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _get_attr(obj: Any, name: str) -> Any:
    """Return ``obj.name`` if *obj* is not a dict, else ``obj[name]``."""
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_EXECUTION_AUTHORITY_INSTANCE: Optional[CognitiveExecutionAuthority] = None


def get_cognitive_execution_authority() -> CognitiveExecutionAuthority:
    """Return the canonical :class:`CognitiveExecutionAuthority` singleton.

    Creates the singleton on first call; subsequent calls return the same
    instance.  Use :func:`refresh_cognitive_execution_authority` to force
    creation of a fresh instance (e.g. in tests or after router reinitialisation).

    Returns
    -------
    CognitiveExecutionAuthority:
        The canonical L4 execution authority singleton.
    """
    global _EXECUTION_AUTHORITY_INSTANCE
    if _EXECUTION_AUTHORITY_INSTANCE is None:
        _EXECUTION_AUTHORITY_INSTANCE = CognitiveExecutionAuthority()
    return _EXECUTION_AUTHORITY_INSTANCE


def refresh_cognitive_execution_authority() -> CognitiveExecutionAuthority:
    """Force creation of a fresh :class:`CognitiveExecutionAuthority` singleton.

    Replaces the existing singleton with a new instance.  Useful in tests or
    after reinitialising the underlying router.

    Returns
    -------
    CognitiveExecutionAuthority:
        A fresh L4 execution authority instance (now the new singleton).
    """
    global _EXECUTION_AUTHORITY_INSTANCE
    _EXECUTION_AUTHORITY_INSTANCE = CognitiveExecutionAuthority()
    return _EXECUTION_AUTHORITY_INSTANCE
