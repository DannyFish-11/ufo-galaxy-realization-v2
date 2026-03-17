"""
Galaxy — Scene Interpreter (PR 2)
===================================

:class:`SceneInterpreter` analyses the fused multimodal context together with
the raw message text and produces an :class:`~core.interaction.interaction_types.InteractionDecision`
that downstream components (UI renderer, voice channel, avatar engine) can
consume to adapt the interaction surface.

Design principles
-----------------
* **Rule-based, no model calls** — decisions are made deterministically from
  keyword heuristics and context flags.  This keeps latency near-zero and
  makes the rules easy to audit and override.
* **Caller override** — pass ``mode_hint`` to bypass all rules and force a
  specific :class:`~core.interaction.interaction_types.InteractionMode`.
* **EventBus integration** — emits ``INTERACTION_MODE_SELECTED`` after every
  successful decision so that other subsystems can react.
* **Never raises** — every exception is caught and logged; on failure the
  interpreter returns a ``CHAT`` decision so the main request path is
  unaffected.

Rule priority (highest → lowest)
---------------------------------
1. ``mode_hint`` caller override
2. ``EXECUTION_BRIDGE`` — reserved for future use (not matched by default rules)
3. ``CONTROL_CONSOLE`` — execution/task/script keywords
4. ``FIELD_ASSISTANT`` — visual context present **and** pointing keywords
5. ``DEEP_THINKING`` — long text with analytical keywords
6. ``AMBIENT_COMPANION`` — very short messages with no strong signal
7. ``CHAT`` — default fallback

Usage::

    from core.interaction.scene_interpreter import SceneInterpreter

    interpreter = SceneInterpreter()
    decision = interpreter.interpret(
        message="帮我执行这个部署脚本",
        fused_context={"images": [], "fusion_summary": ""},
    )
    # decision.mode == InteractionMode.CONTROL_CONSOLE
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.interaction.interaction_types import InteractionDecision, InteractionMode
from core.interaction.mode_selector import ModeSelector

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword sets (tuples for O(n) scan; kept small by design)
# ---------------------------------------------------------------------------

#: Words that indicate the user wants task/command/script execution.
_CONTROL_KEYWORDS: tuple = (
    "执行", "任务", "脚本", "命令", "流程", "部署",
    "运行", "启动", "停止", "重启", "安装", "配置",
    "execute", "deploy", "script", "command", "run", "task",
)

#: Words that indicate on-site visual guidance is needed.
_FIELD_KEYWORDS: tuple = (
    "看", "指", "这个", "那里", "这里", "那个",
    "怎么修", "帮我看", "这是什么", "怎么弄",
    "show", "point", "here", "there", "fix", "look",
)

#: Words that suggest deep analytical or philosophical exploration.
_DEEP_THINKING_KEYWORDS: tuple = (
    "哲学", "原理", "结构", "系统", "本质", "理论",
    "架构", "机制", "逻辑", "推演", "分析", "深度",
    "philosophy", "principle", "structure", "system", "essence",
    "theory", "architecture", "mechanism", "analysis",
)

#: Minimum message character length to qualify for DEEP_THINKING.
_DEEP_THINKING_MIN_LEN: int = 40

#: Maximum message length that may qualify for AMBIENT_COMPANION.
_AMBIENT_MAX_LEN: int = 8


def _has_keyword(text: str, keywords: tuple) -> bool:
    """Return True if *text* contains any of the given *keywords* (case-insensitive).

    Note: matching is substring-based (not word-boundary) to handle compound
    Chinese terms (e.g. "执行" matches "执行任务") and common English fragments
    (e.g. "deploy" inside "deployment").  This is intentional for a heuristic
    rule engine where recall is preferred over precision.
    """
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _has_visual_context(fused_context: Optional[Dict[str, Any]]) -> bool:
    """Return True when the fused context contains image or screen data."""
    if not fused_context:
        return False
    if fused_context.get("images"):
        return True
    if fused_context.get("screen"):
        return True
    summary: str = fused_context.get("fusion_summary") or ""
    return "image" in summary.lower() or "screen" in summary.lower()


class SceneInterpreter:
    """Rule-based scene/interaction-mode interpreter.

    Each call to :meth:`interpret` is stateless — the interpreter holds no
    mutable request-level state, making it safe to use as a singleton.
    """

    def __init__(self) -> None:
        self._selector = ModeSelector()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def interpret(
        self,
        message: str,
        fused_context: Optional[Dict[str, Any]] = None,
        device_metadata: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        mode_hint: Optional[str] = None,
    ) -> InteractionDecision:
        """Interpret the scene and return an :class:`InteractionDecision`.

        Args:
            message:         The raw user message text.
            fused_context:   Fused multimodal context dict produced by
                             :class:`~core.perception.multimodal_bus.MultimodalBus`.
                             Pass ``None`` for text-only requests.
            device_metadata: Optional device/session metadata dict
                             (e.g. ``{"device_id": …, "session_id": …}``).
            session_id:      Session identifier used for event bus emission.
            mode_hint:       When present, bypass all rules and force this
                             :class:`InteractionMode` value (string or enum).

        Returns:
            An :class:`InteractionDecision` describing the selected mode and
            associated UI/voice/avatar hints.
        """
        try:
            decision = self._interpret_safe(
                message=message,
                fused_context=fused_context,
                device_metadata=device_metadata,
                mode_hint=mode_hint,
            )
        except Exception as exc:
            logger.warning("SceneInterpreter.interpret failed, falling back to CHAT: %s", exc)
            decision = self._selector.build_decision(
                mode=InteractionMode.CHAT,
                confidence=0.0,
                rationale=f"fallback (error: {exc})",
            )

        self._emit_event(decision=decision, session_id=session_id)
        return decision

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _interpret_safe(
        self,
        message: str,
        fused_context: Optional[Dict[str, Any]],
        device_metadata: Optional[Dict[str, Any]],
        mode_hint: Optional[str],
    ) -> InteractionDecision:
        """Core rule engine — may raise; callers must wrap with try/except."""

        # ── 1. Caller override ────────────────────────────────────────────
        if mode_hint is not None:
            try:
                forced_mode = InteractionMode(mode_hint)
            except ValueError:
                # Invalid hint — log and fall through to rules
                logger.debug("SceneInterpreter: unknown mode_hint %r, ignoring", mode_hint)
            else:
                return self._selector.build_decision(
                    mode=forced_mode,
                    confidence=1.0,
                    rationale=f"caller override: mode_hint={mode_hint!r}",
                )

        # ── 2. CONTROL_CONSOLE ────────────────────────────────────────────
        if _has_keyword(message, _CONTROL_KEYWORDS):
            return self._selector.build_decision(
                mode=InteractionMode.CONTROL_CONSOLE,
                confidence=0.9,
                rationale="execution/task/command keywords detected",
            )

        # ── 3. FIELD_ASSISTANT ────────────────────────────────────────────
        if _has_visual_context(fused_context) and _has_keyword(message, _FIELD_KEYWORDS):
            return self._selector.build_decision(
                mode=InteractionMode.FIELD_ASSISTANT,
                confidence=0.85,
                rationale="visual context present with pointing/guidance keywords",
            )

        # ── 4. DEEP_THINKING ──────────────────────────────────────────────
        if len(message) > _DEEP_THINKING_MIN_LEN and _has_keyword(message, _DEEP_THINKING_KEYWORDS):
            return self._selector.build_decision(
                mode=InteractionMode.DEEP_THINKING,
                confidence=0.8,
                rationale="long message with analytical/philosophical keywords",
            )

        # ── 5. AMBIENT_COMPANION ──────────────────────────────────────────
        if len(message.strip()) <= _AMBIENT_MAX_LEN:
            return self._selector.build_decision(
                mode=InteractionMode.AMBIENT_COMPANION,
                confidence=0.6,
                rationale="very short message — ambient companion mode",
            )

        # ── 6. Default: CHAT ──────────────────────────────────────────────
        return self._selector.build_decision(
            mode=InteractionMode.CHAT,
            confidence=0.95,
            rationale="no special keywords matched — default chat mode",
        )

    def _emit_event(
        self,
        decision: InteractionDecision,
        session_id: Optional[str],
    ) -> None:
        """Emit INTERACTION_MODE_SELECTED on the Galaxy EventBus (best-effort)."""
        try:
            from integration.event_bus import EventType, UIGalaxyEvent
            from integration.event_bus import event_bus as _event_bus

            _event_bus.emit(
                UIGalaxyEvent(
                    event_type=EventType.INTERACTION_MODE_SELECTED,
                    source="scene_interpreter",
                    data={
                        "mode": decision.mode.value,
                        "relationship_mode": decision.relationship_mode,
                        "ui_surface": decision.ui_surface,
                        "voice_mode": decision.voice_mode,
                        "avatar_mode": decision.avatar_mode,
                        "confidence": decision.confidence,
                        "rationale": decision.rationale,
                        "session_id": session_id,
                    },
                )
            )
        except Exception as exc:  # EventBus must never crash the interpreter
            logger.debug("SceneInterpreter._emit_event failed: %s", exc)


__all__ = ["SceneInterpreter"]
