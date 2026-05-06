"""tests/integration/stubs/llm_contract_stub.py
================================================
Minimal LLM contract stub for NL canonical path CI proof.

Purpose
-------
This stub replaces the real LLM backend (MultiLLMRouter / UnifiedLLMRouter)
during integration tests so that the full NL canonical chain can be exercised
without requiring live API keys.

The stub is **not** a disconnected mock.  It is injected at the LLM-router leaf
level (below AgentKernel) so the entire canonical chain runs for real:

    /api/v1/chat (or DPR.handle_request directly)
        → DesktopPresenceRuntime  (SILENT → LIMINAL → MANIFEST → SILENT)
            → OpenClawd.process()  (runtime_session_id, ingress_carrier_context)
                → AgentKernel.handle_message()  (intent routing, chat handling)
                    → IntentRouter.route()  (rule-based, LLM stub not called for
                                             high-confidence rule matches)
                    → _handle_chat() / _fallback_chat()
                        → LLMContractStub.chat()  ← stub leaf
                            → KernelResponse (structured contract result)
        → result dict (ingress_carrier_context, runtime_session_id, ...)

Compatibility
-------------
Compatible with both MultiLLMRouter and UnifiedLLMRouter interfaces:
  - async chat(messages, **kwargs) → response with .content attribute
  - is_available() → bool
  - get_default_model() → str
  - classify_task(messages) → TaskType-compatible object

The stub also handles IntentRouter's LLM-augmented classification calls by
returning a valid JSON classification payload when the message looks like an
intent classification prompt.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# LLM Response stand-in
# ---------------------------------------------------------------------------


class _StubResponse:
    """Minimal LLM response object compatible with AgentKernel's consumer logic.

    AgentKernel expects either:
    - An object with a ``.content`` attribute (LLMResponse-like), or
    - A dict with a ``content`` or ``response`` key.

    This class satisfies the first form.
    """

    def __init__(self, content: str, model: str) -> None:
        self.content: str = content
        self.model: str = model

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-style fallback access so dicts and objects both work."""
        return getattr(self, key, default)


# ---------------------------------------------------------------------------
# LLMContractStub
# ---------------------------------------------------------------------------

# Deterministic reply text so tests can assert on it.
STUB_CHAT_REPLY: str = "Galaxy NL canonical path proof: contract-stub response."
STUB_MODEL: str = "contract-stub-v1"

# Valid intent-classification JSON so IntentRouter's LLM-enhancement path
# can parse the result and route the conversation correctly.
_STUB_INTENT_JSON: str = (
    '{"mode": "chat_only", "confidence": 0.92, "intent": "chat", "task_hint": ""}'
)


class LLMContractStub:
    """Minimal LLM router contract stub for NL canonical path integration tests.

    Usage::

        stub = LLMContractStub()
        # Inject via patch:
        with patch("core.unified.get_unified_llm_router", return_value=stub):
            result = await runtime.handle_request(message="hello", source="chat")

    The stub returns:
    - An intent-classification JSON response for prompts that look like
      classification requests (detected by ``JSON`` / ``mode``+``confidence``
      keywords in the message content).
    - ``STUB_CHAT_REPLY`` for all other (chat / response) calls.
    """

    def __init__(
        self,
        reply: str = STUB_CHAT_REPLY,
        model: str = STUB_MODEL,
    ) -> None:
        self._reply = reply
        self._model = model
        # Track call counts for assertions.
        self.call_count: int = 0
        self.last_messages: Optional[List[Dict[str, str]]] = None

    # ------------------------------------------------------------------
    # Core LLM interface (async)
    # ------------------------------------------------------------------

    async def chat(
        self,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> _StubResponse:
        """Return a stub chat response compatible with AgentKernel consumers."""
        self.call_count += 1
        self.last_messages = messages

        # Detect intent-classification calls so IntentRouter can parse the
        # JSON and classify the intent correctly.  The classification prompt
        # always asks for JSON with "mode"/"confidence" fields.
        content_combined = " ".join(
            str(m.get("content", "")) for m in (messages or [])
        )
        is_classification = bool(
            "JSON" in content_combined
            or (
                re.search(r"\bmode\b", content_combined, re.I)
                and re.search(r"\bconfidence\b", content_combined, re.I)
            )
        )

        reply = _STUB_INTENT_JSON if is_classification else self._reply
        return _StubResponse(content=reply, model=self._model)

    # ------------------------------------------------------------------
    # Utility / health interface (sync)
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return True

    def get_default_model(self) -> str:
        return self._model

    def classify_task(self, messages: List[Dict[str, str]]) -> Any:
        """Return a GENERAL task-type token (used by OpenClawd PR-17 path)."""
        try:
            from core.multi_llm_router import TaskType
            return TaskType.GENERAL
        except ImportError:
            # Fall back to a duck-typed stand-in when the enum is unavailable.
            return type("_FakeTaskType", (), {"value": "general"})()

    # ------------------------------------------------------------------
    # Chat-with-tools interface (used by some paths)
    # ------------------------------------------------------------------

    async def chat_with_tools(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> _StubResponse:
        """Stub for function-calling / tool-use paths; returns plain reply."""
        self.call_count += 1
        self.last_messages = messages
        return _StubResponse(content=self._reply, model=self._model)

    # ------------------------------------------------------------------
    # repr for test diagnostics
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"LLMContractStub(model={self._model!r}, calls={self.call_count})"
        )
