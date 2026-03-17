"""
Galaxy — Overlay Channel stub (PR-6)
======================================

Returns a **structured screen-overlay annotation plan** without performing any
actual rendering.  A future PR will connect this to the Windows/Android
overlay rendering pipeline; clients consuming the plan dict do not need to
change.

Overlay is primarily useful for ``field_assistant`` mode where on-screen
annotations guide a user through a real-world task.

No external dependencies.  Safe to import in any context.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# Interaction modes that request overlay by default
_OVERLAY_MODES = frozenset({"field_assistant"})


class OverlayChannel:
    """Builds the screen-overlay plan (stub).

    The channel assembles annotation metadata (position hints, content
    snippets, highlight targets) for the overlay renderer.
    """

    def build(
        self,
        enabled: bool = False,
        mode: str = "chat",
        response_text: str = "",
        task_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Return an overlay-channel plan dict.

        Args:
            enabled:       Whether overlay output is requested (mirrors
                           ``OutputPlan.overlay``).
            mode:          Active interaction mode string.
            response_text: The response text; used to seed annotation content
                           when overlay is active.
            task_state:    Optional task state dict; used to populate step
                           indicators in the overlay.

        Returns:
            A JSON-serialisable dict with keys:

            * ``enabled`` — whether overlay should be rendered.
            * ``overlay_plan`` — nested dict of overlay parameters (only
              present when *enabled* is ``True``).
            * ``note`` — human-readable stub notice.
        """
        if not enabled:
            return {
                "enabled": False,
                "overlay_plan": None,
                "note": "stub: overlay not requested for this interaction mode",
            }

        # Build minimal step list from task_state if available
        steps: List[Dict[str, Any]] = []
        if task_state and isinstance(task_state, dict):
            raw_steps = task_state.get("steps", [])
            if isinstance(raw_steps, list):
                steps = [{"label": str(s)} for s in raw_steps[:5]]

        overlay_plan: Dict[str, Any] = {
            "type": "annotation",
            "position": "auto",
            "content_snippet": response_text[:120] if response_text else "",
            "highlight_targets": [],
            "steps": steps,
            "opacity": 0.85,
        }

        return {
            "enabled": True,
            "overlay_plan": overlay_plan,
            "note": "stub: overlay plan ready — screen rendering not yet implemented",
        }


__all__ = ["OverlayChannel"]
