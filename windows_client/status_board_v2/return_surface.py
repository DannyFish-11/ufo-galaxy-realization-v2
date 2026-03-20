"""
windows_client/status_board_v2/return_surface.py
================================================
ReturnSurface — renders the return-intelligence summary as part of
Status Board V2.

READ-ONLY surface: displays information only, never sends commands.

This surface consumes the ``"return_intelligence"`` key that is optionally
attached to the projection payload by
:func:`~core.return_intelligence.attach_return_summary`.  When the key is
absent the surface renders a compact idle state, so the board degrades
gracefully when the server has not yet been updated to supply return data.

Displayed fields
----------------
- ``return_mode``        : active return mode label
- ``is_returning``       : whether a return is currently in progress
- ``return_trigger``     : what triggered the return (if any)
- ``decay_amount``       : intensity reduction bar (soft_decay only)
- ``affects_manifest``   : downstream manifest hint
- ``affects_liminal``    : downstream liminal hint
- ``reason``             : human-readable explanation from the engine
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ._ansi import BOLD, RESET, c

# Colour palette.
_COLOUR_IDLE = "\033[90m"       # grey — no return active
_COLOUR_HOLD = "\033[33m"       # yellow — hold
_COLOUR_DECAY = "\033[33m"      # yellow — soft decay
_COLOUR_STEP_DOWN = "\033[35m"  # magenta — step down
_COLOUR_HARD = "\033[31m"       # red — return_to_formless
_COLOUR_HINT = "\033[36m"       # cyan — downstream hints
_COLOUR_DIM = "\033[2m"         # dim — secondary info

_BAR_WIDTH = 12

_MODE_COLOURS: Dict[str, str] = {
    "none": _COLOUR_IDLE,
    "hold": _COLOUR_HOLD,
    "soft_decay": _COLOUR_DECAY,
    "step_down": _COLOUR_STEP_DOWN,
    "return_to_formless": _COLOUR_HARD,
}

_MODE_LABELS: Dict[str, str] = {
    "none": "idle",
    "hold": "hold",
    "soft_decay": "soft_decay",
    "step_down": "step_down",
    "return_to_formless": "return_to_formless",
}


def _bar(value: float, width: int = _BAR_WIDTH, colour: str = "") -> str:
    """Render a compact ASCII progress bar for *value* ∈ [0, 1]."""
    v = max(0.0, min(1.0, float(value)))
    filled = round(v * width)
    inner = "█" * filled + "░" * (width - filled)
    bar = f"[{inner}]"
    return c(bar, colour) if colour else bar


class ReturnSurface:
    """Renders the return-intelligence projection surface.

    READ-ONLY — this class only produces display strings.

    Reads the ``"return_intelligence"`` key from the incoming projection
    dict, which is populated by
    :func:`~core.return_intelligence.attach_return_summary` on the server
    side when return data is available.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the return surface.

        Parameters
        ----------
        projection
            A dict conforming to the ``RuntimeProjection`` schema.  May
            optionally contain a ``"return_intelligence"`` sub-dict added by
            :func:`~core.return_intelligence.attach_return_summary`.

        Returns
        -------
        str
            Multi-line string ready to ``print()``.
        """
        ri: Dict[str, Any] = projection.get("return_intelligence") or {}

        mode: str = ri.get("return_mode") or "none"
        is_returning: bool = bool(ri.get("is_returning", False))
        trigger: Optional[str] = ri.get("return_trigger")
        decay: float = float(ri.get("decay_amount") or 0.0)
        reason: str = str(ri.get("reason") or "no return active")
        affects_manifest: bool = bool(ri.get("affects_manifest", False))
        affects_liminal: bool = bool(ri.get("affects_liminal", False))

        col = _MODE_COLOURS.get(mode, _COLOUR_IDLE)
        mode_label = _MODE_LABELS.get(mode, mode)

        # Status indicator.
        if is_returning:
            status = c("↩ RETURNING", col)
        else:
            status = c("· idle", _COLOUR_IDLE)

        lines = [
            c("  ┌─ Return Intelligence ───────────────────────────┐", BOLD),
            f"  │  Mode     : {c(mode_label, col)}   {status}",
        ]

        # Trigger.
        trigger_str = trigger if trigger else "(none)"
        trigger_col = col if trigger else _COLOUR_DIM
        lines.append(f"  │  Trigger  : {c(trigger_str, trigger_col)}")

        # Decay bar — only relevant for soft_decay.
        if mode == "soft_decay":
            bar = _bar(decay, colour=col)
            lines.append(f"  │  Decay    : {bar}  {decay:.3f}")
        else:
            lines.append(f"  │  Decay    : {c('—', _COLOUR_DIM)}")

        # Downstream hints.
        manifest_str = c("! suppressed", _COLOUR_HARD) if affects_manifest else c("ok normal", _COLOUR_IDLE)
        liminal_str = c("~ softened", _COLOUR_DECAY) if affects_liminal else c("ok normal", _COLOUR_IDLE)
        lines.append(f"  │  Manifest : {manifest_str}")
        lines.append(f"  │  Liminal  : {liminal_str}")

        # Reason (truncated).
        if len(reason) > 48:
            reason = reason[:45] + "..."
        lines.append(f"  │  Reason   : {c(reason, _COLOUR_DIM)}")

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)
