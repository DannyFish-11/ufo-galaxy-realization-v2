"""
Galaxy — Output Orchestrator (PR-6)
=====================================

:class:`OutputOrchestrator` converts an :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
(or its dict representation) plus a :class:`~core.schemas.persona_state.PersonaState` dict and the
final ``response_text`` into a **multi-channel output plan**.

The plan has five top-level keys:

* ``text``    — always enabled; contains content + formatting hints.
* ``voice``   — stub TTS plan (enabled when ``OutputPlan.voice`` is True).
* ``avatar``  — stub avatar animation plan (enabled when ``OutputPlan.avatar`` is True).
* ``overlay`` — stub screen-overlay plan (enabled when ``OutputPlan.overlay`` is True).
* ``actions`` — list of downstream action descriptors (populated from task_state).

No external dependencies.  Safe to import in any context.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from core.output.text_channel import TextChannel
from core.output.voice_channel import VoiceChannel
from core.output.avatar_channel import AvatarChannel
from core.output.overlay_channel import OverlayChannel

logger = logging.getLogger(__name__)


def _extract_output_plan(interaction_envelope: Any) -> Dict[str, Any]:
    """Return the ``output_plan`` sub-dict from an envelope (dict or object).

    Falls back to text-only defaults on any error.
    """
    try:
        if interaction_envelope is None:
            return {"text": True, "voice": False, "avatar": False,
                    "overlay": False, "ui_surface": "chat_panel"}
        if isinstance(interaction_envelope, dict):
            return interaction_envelope.get(
                "output_plan",
                {"text": True, "voice": False, "avatar": False,
                 "overlay": False, "ui_surface": "chat_panel"},
            )
        # dataclass / Pydantic object
        op = getattr(interaction_envelope, "output_plan", None)
        if op is None:
            return {"text": True, "voice": False, "avatar": False,
                    "overlay": False, "ui_surface": "chat_panel"}
        if isinstance(op, dict):
            return op
        # OutputPlan dataclass
        return {
            "text": getattr(op, "text", True),
            "voice": getattr(op, "voice", False),
            "avatar": getattr(op, "avatar", False),
            "overlay": getattr(op, "overlay", False),
            "ui_surface": getattr(op, "ui_surface", "chat_panel"),
        }
    except Exception as exc:  # pragma: no cover
        logger.debug("_extract_output_plan fallback: %s", exc)
        return {"text": True, "voice": False, "avatar": False,
                "overlay": False, "ui_surface": "chat_panel"}


def _extract_mode(interaction_envelope: Any) -> str:
    """Return the interaction mode string from an envelope (dict or object)."""
    try:
        if interaction_envelope is None:
            return "chat"
        if isinstance(interaction_envelope, dict):
            return interaction_envelope.get("mode", "chat")
        return getattr(interaction_envelope, "mode", "chat")
    except Exception:  # pragma: no cover
        return "chat"


def _build_actions(task_state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract action descriptors from *task_state* (best-effort)."""
    if not task_state or not isinstance(task_state, dict):
        return []
    raw = task_state.get("actions", task_state.get("pending_actions", []))
    if not isinstance(raw, list):
        return []
    actions: List[Dict[str, Any]] = []
    for item in raw[:10]:
        if isinstance(item, dict):
            actions.append(item)
        elif isinstance(item, str):
            actions.append({"type": "generic", "label": item})
    return actions


class OutputOrchestrator:
    """Converts interaction context into a multi-channel output plan.

    The orchestrator is **stateless** — create one instance and call
    :meth:`orchestrate` as many times as needed.

    Example::

        from core.output import OutputOrchestrator

        plan = OutputOrchestrator().orchestrate(
            interaction_envelope=envelope_dict,
            persona_state=persona_dict,
            response_text="Hello!",
        )
        assert plan["text"]["enabled"] is True
        assert plan["text"]["content"] == "Hello!"
    """

    def __init__(self) -> None:
        self._text = TextChannel()
        self._voice = VoiceChannel()
        self._avatar = AvatarChannel()
        self._overlay = OverlayChannel()

    def orchestrate(
        self,
        interaction_envelope: Any,
        persona_state: Optional[Dict[str, Any]],
        response_text: str,
        task_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build and return the multi-channel output plan.

        Args:
            interaction_envelope: :class:`~core.schemas.interaction_envelope.InteractionEnvelope`
                instance *or* its ``to_dict()`` representation *or* ``None``
                (falls back to text-only defaults).
            persona_state:        Serialised persona-state dict (from
                                  ``PersonaState.to_dict()``) or ``None``.
            response_text:        The final text reply produced by OpenClawd.
            task_state:           Optional task-state dict containing pending
                                  actions, step lists, etc.

        Returns:
            A JSON-serialisable dict with keys ``text``, ``voice``,
            ``avatar``, ``overlay``, and ``actions``.
        """
        op = _extract_output_plan(interaction_envelope)
        mode = _extract_mode(interaction_envelope)

        ui_surface: str = op.get("ui_surface", "chat_panel") if isinstance(op, dict) else "chat_panel"
        # 语音默认开关：OutputPlan 显式指定则尊重之；否则按全局 GALAXY_VOICE（默认开）/模式判定，
        # 让 AI 起来就会用本地 edge-tts 说话。
        if isinstance(op, dict) and "voice" in op:
            voice_enabled = bool(op.get("voice"))
        else:
            voice_enabled = VoiceChannel.is_voice_enabled_for_mode(mode)
        avatar_enabled: bool = bool(op.get("avatar", False)) if isinstance(op, dict) else False
        overlay_enabled: bool = bool(op.get("overlay", False)) if isinstance(op, dict) else False

        text_plan = self._text.build(
            response_text=response_text,
            ui_surface=ui_surface,
            persona_state=persona_state,
        )
        voice_plan = self._voice.build(
            response_text=response_text,
            enabled=voice_enabled,
            mode=mode,
            persona_state=persona_state,
        )
        # 修复(三态/语音链路稳定性排查):这里之前会在 build 完计划后，自己再
        # 起一个后台任务用独立的 VoiceChannel/EdgeTTSEngine 实例真正合成并
        # 播放——但 core/desktop_presence_runtime.py::handle_request() 收尾
        # 已经无条件调用 core.speech_output.speak_response(result["response"])
        # 把"任何渠道的回复都默认朗读"做成了集中式 TTS（这是仓库既有的、
        # 明确的设计意图）。本模块顶部文档字符串也写着 voice 是"stub TTS
        # plan"——即这里本该只产出"计划"，不该自己动手播放。两条路径叠加的
        # 真实后果:任何被 scene_interpreter 归类为 ambient_companion/
        # field_assistant 的消息(包括所有 ≤8 字的短消息，语音场景下极常见)
        # 会被两个完全独立的 TTS 引擎实例各合成播放一遍——用户听感上就是
        # "AI 把同一句话念了两遍"。这里改回只产计划，真正的播放动作交给
        # 唯一的集中入口 speak_response()，不再重复触发。
        avatar_plan = self._avatar.build(
            enabled=avatar_enabled,
            mode=mode,
            persona_state=persona_state,
        )
        overlay_plan = self._overlay.build(
            enabled=overlay_enabled,
            mode=mode,
            response_text=response_text,
            task_state=task_state,
        )
        actions = _build_actions(task_state)

        return {
            "text": text_plan,
            "voice": voice_plan,
            "avatar": avatar_plan,
            "overlay": overlay_plan,
            "actions": actions,
        }


__all__ = ["OutputOrchestrator"]
