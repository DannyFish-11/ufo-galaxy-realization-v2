"""
Galaxy — Interaction Builder (PR-4)
=====================================

:class:`InteractionBuilder` assembles an :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
from the outputs of the three preceding pipeline stages:

* **PR-1** — fused multimodal context dict (from ``MultimodalBus.ingest()``)
* **PR-2** — scene interpreter decision (:class:`~core.interaction.interaction_types.InteractionDecision`)
* **PR-3** — persona state (:class:`~core.schemas.persona_state.PersonaState` or its ``to_dict()`` dict)

Design principles
-----------------
* **Purely additive** — the builder never modifies any upstream object.
* **No external dependencies** — only stdlib and internal Galaxy modules.
* **Never raises** — every exception is caught so that the caller's request
  path is unaffected.  On error a minimal text-only envelope is returned.
* **Stable ``trace_id``** — if *trace_id* is supplied it is preserved as-is;
  the builder never generates a new one.

Usage::

    from core.interaction.interaction_builder import InteractionBuilder

    builder = InteractionBuilder()
    envelope = builder.build(
        trace_id="trace_abc123",
        session_id="sess_xyz",
        scene_decision=decision,          # InteractionDecision from SceneInterpreter
        persona_state=persona_state,       # PersonaState (or its to_dict())
        fused_context=mm_context_dict,     # dict from MultimodalBus.ingest()
    )
    # envelope.to_dict() is JSON-serialisable
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


class InteractionBuilder:
    """Assembles an :class:`~core.schemas.interaction_envelope.InteractionEnvelope`.

    Each call to :meth:`build` is **stateless** — no request-level mutable
    state is kept, making this class safe to use as a singleton.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        trace_id: Optional[str] = None,
        session_id: str = "__global__",
        scene_decision: Optional[Any] = None,
        persona_state: Optional[Any] = None,
        fused_context: Optional[Dict[str, Any]] = None,
        output_plan: Optional[Any] = None,
    ) -> Any:
        """Build and return an :class:`~core.schemas.interaction_envelope.InteractionEnvelope`.

        Args:
            trace_id:       End-to-end trace identifier.  Re-used as-is so
                            the envelope can be correlated with log entries.
            session_id:     Session identifier.
            scene_decision: :class:`~core.interaction.interaction_types.InteractionDecision`
                            produced by :class:`~core.interaction.scene_interpreter.SceneInterpreter`.
                            May be ``None`` for text-only fallback.
            persona_state:  Either a
                            :class:`~core.schemas.persona_state.PersonaState`
                            instance **or** its ``to_dict()`` dict.  May be
                            ``None`` when the persona engine is unavailable.
            fused_context:  Fused multimodal context dict from
                            ``MultimodalBus.ingest()``.  May be ``None`` for
                            text-only requests.
            output_plan:    Optional pre-built :class:`~core.schemas.interaction_envelope.OutputPlan`.
                            When ``None``, a default plan is derived from the
                            interaction mode.

        Returns:
            A fully-populated :class:`~core.schemas.interaction_envelope.InteractionEnvelope`.
            On any internal error a minimal text-only envelope is returned so
            that callers are never blocked.
        """
        try:
            return self._build_safe(
                trace_id=trace_id,
                session_id=session_id,
                scene_decision=scene_decision,
                persona_state=persona_state,
                fused_context=fused_context,
                output_plan=output_plan,
            )
        except Exception as exc:
            logger.warning(
                "InteractionBuilder.build failed, returning text-only fallback: %s", exc
            )
            return self._fallback_envelope(trace_id=trace_id, session_id=session_id)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_safe(
        self,
        trace_id: Optional[str],
        session_id: str,
        scene_decision: Optional[Any],
        persona_state: Optional[Any],
        fused_context: Optional[Dict[str, Any]],
        output_plan: Optional[Any],
    ) -> Any:
        from core.schemas.interaction_envelope import InteractionEnvelope, OutputPlan

        # ── Extract mode / relationship_mode from scene decision ──────────
        mode = "chat"
        relationship_mode = "user_companion"
        if scene_decision is not None:
            try:
                mode = scene_decision.mode.value  # InteractionDecision.mode is an enum
            except AttributeError:
                mode = str(getattr(scene_decision, "mode", "chat"))
            relationship_mode = getattr(scene_decision, "relationship_mode", "user_companion")

        # ── Serialise persona_state ───────────────────────────────────────
        persona_dict: Optional[Dict[str, Any]] = None
        if persona_state is not None:
            if isinstance(persona_state, dict):
                persona_dict = persona_state
            elif hasattr(persona_state, "to_dict"):
                persona_dict = persona_state.to_dict()
            else:
                persona_dict = dict(vars(persona_state))

        # ── Strip binary payloads from multimodal context ─────────────────
        # base64 image/audio payloads are already stripped by MultimodalBus
        # before it returns the fused dict, but we guard here as well to
        # avoid accidentally propagating large blobs in API responses.
        clean_context: Optional[Dict[str, Any]] = None
        if fused_context is not None:
            filtered = {
                k: v
                for k, v in fused_context.items()
                if k not in ("images", "audio")
            }
            # Represent an all-stripped context as None rather than an empty dict
            # so that downstream serialisers can omit the field cleanly.
            clean_context = filtered if filtered else None

        # ── Resolve output_plan ────────────────────────────────────────────
        if output_plan is None:
            resolved_plan = OutputPlan.from_mode(mode)
        else:
            resolved_plan = output_plan

        return InteractionEnvelope(
            trace_id=trace_id,
            session_id=session_id,
            mode=mode,
            relationship_mode=relationship_mode,
            persona_state=persona_dict,
            multimodal_context=clean_context,
            output_plan=resolved_plan,
        )

    def _fallback_envelope(
        self,
        trace_id: Optional[str] = None,
        session_id: str = "__global__",
    ) -> Any:
        """Return a minimal text-only envelope used when build() fails."""
        from core.schemas.interaction_envelope import InteractionEnvelope, OutputPlan

        return InteractionEnvelope(
            trace_id=trace_id,
            session_id=session_id,
            mode="chat",
            relationship_mode="user_companion",
            output_plan=OutputPlan.text_only(),
        )


__all__ = ["InteractionBuilder"]
