"""
Galaxy — Output Orchestrator package (PR-6)
============================================

Exports the :class:`~core.output.orchestrator.OutputOrchestrator` façade and
individual channel helpers.  All channel implementations other than
:mod:`~core.output.text_channel` are *stubs* that return structured plans
without performing actual rendering (TTS / 3-D avatar / overlay drawing).

Typical usage::

    from core.output import OutputOrchestrator

    plan = OutputOrchestrator().orchestrate(
        interaction_envelope=envelope_dict,
        persona_state=persona_dict,
        response_text="Hello!",
    )
    # plan["text"]["content"] == "Hello!"
    # plan["voice"]["enabled"] == False  (unless envelope enables it)
"""

from core.output.orchestrator import OutputOrchestrator

__all__ = ["OutputOrchestrator"]
