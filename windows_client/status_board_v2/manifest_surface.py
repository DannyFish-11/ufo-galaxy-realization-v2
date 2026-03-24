"""
windows_client/status_board_v2/manifest_surface.py
===================================================
ManifestSurface — renders the manifest-stage (显现台) projection as part of
Status Board V2.

READ-ONLY surface: displays information only, never sends commands.

Display boundary
----------------
This surface sits at the boundary between the liminal middle-state space and
the manifest phase.  It represents the **execution context** that emerges from
the liminal field's transition into manifest — it is NOT a second status board
or a provider/metrics panel.

Permitted content: execution focus (focus intensity, active stage, routed
models, active devices, route reason) — fields that describe *where the
execution field landed*, not a general system information panel.

Prohibited content: provider list cards, dashboard-style model panels, full
metrics/status-board panels, generic operator information blocks.  Those belong
exclusively to the right-side desktop status board.

See ``docs/DESKTOP_DISPLAY_BOUNDARIES.md`` for the canonical boundary contract.

Architecture
------------
This surface integrates with :class:`~desktop_projection.ManifestStageController`
to show the manifest-stage state that emerges from the liminal projection.
It mirrors the structure of :class:`~windows_client.status_board_v2.liminal_surface.LiminalSurface`
but focuses on execution context: which models are routing, which devices are
active, and how focused/committed the system field is.

Displayed fields
----------------
- ``source_phase``       : tri-state phase of the underlying projection
- ``stage_ready``        : whether the manifest surface is active
- ``focus_intensity``    : focus-field strength bar
- ``primary_model_id``   : primary routed model
- ``support_model_ids``  : supporting models
- ``active_weights``     : top-N model weight bars
- ``active_device_ids``  : devices in execution
- ``execution_stage``    : lifecycle stage label
- ``task_summary``       : current task description
- ``route_reason``       : routing rationale
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ._ansi import BOLD, RESET, c

# Colour palette.
_COLOUR_GREEN = "\033[32m"      # green
_COLOUR_READY = _COLOUR_GREEN   # stage is ready
_COLOUR_HOLD = "\033[33m"       # yellow — stage is holding / liminal
_COLOUR_SILENT = "\033[90m"     # grey   — silent / not ready
_COLOUR_PRIMARY = _COLOUR_GREEN # primary model
_COLOUR_SUPPORT = "\033[36m"    # cyan   — support models
_COLOUR_WEIGHT = "\033[33m"     # yellow — weight bars
_COLOUR_DIM = "\033[2m"         # dim    — secondary info

_BAR_WIDTH = 16

_PHASE_COLOURS: Dict[str, str] = {
    "silent": _COLOUR_SILENT,
    "liminal": _COLOUR_HOLD,
    "manifest": _COLOUR_READY,
}


def _bar(value: float, width: int = _BAR_WIDTH, colour: str = "") -> str:
    """Render a compact ASCII progress bar for *value* ∈ [0, 1]."""
    v = max(0.0, min(1.0, value))
    filled = round(v * width)
    inner = "█" * filled + "░" * (width - filled)
    bar = f"[{inner}]"
    return c(bar, colour) if colour else bar


class ManifestSurface:
    """Renders the manifest-stage (显现台) projection surface.

    READ-ONLY — this class only produces display strings.

    This surface uses :class:`~desktop_projection.ManifestStageController`
    internally to derive manifest state from a raw ``RuntimeProjection`` dict
    and its corresponding liminal state.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the manifest surface.

        Parameters
        ----------
        projection
            A dict conforming to the ``RuntimeProjection`` schema.

        Returns
        -------
        str
            Multi-line string ready to ``print()``.
        """
        try:
            from desktop_projection import StateSpaceMapper, ManifestStageController
            liminal = StateSpaceMapper().map(projection)
            manifest = ManifestStageController().update(projection, liminal)
        except Exception:  # pragma: no cover
            return self._render_unavailable()

        phase = manifest.source_phase
        col = _PHASE_COLOURS.get(phase, _COLOUR_DIM)

        # Header + readiness.
        ready_str = c("● READY", _COLOUR_READY) if manifest.stage_ready else c("○ HOLD", _COLOUR_HOLD)
        focus_bar = _bar(manifest.focus_intensity, colour=col)

        lines: List[str] = [
            c("  ┌─ Manifest Stage (显现台) ────────────────────────┐", BOLD),
            f"  │  Phase    : {c(phase, col)}   Status: {ready_str}",
            f"  │  Focus    : {focus_bar}  {manifest.focus_intensity:.3f}",
        ]

        # Execution context.
        stage_str = manifest.execution_stage or "—"
        task_str = (manifest.task_summary or "—")
        if len(task_str) > 44:
            task_str = task_str[:41] + "..."
        lines.append(f"  │  Stage    : {c(stage_str, col)}")
        lines.append(f"  │  Task     : {c(task_str, _COLOUR_DIM)}")

        # Model routing.
        primary_str = manifest.primary_model_id or "(none)"
        primary_col = _COLOUR_PRIMARY if manifest.primary_model_id else _COLOUR_DIM
        lines.append(f"  │  Primary  : {c(primary_str, primary_col)}")

        if manifest.support_model_ids:
            support_str = ", ".join(manifest.support_model_ids)
            if len(support_str) > 42:
                support_str = support_str[:39] + "..."
            lines.append(f"  │  Support  : {c(support_str, _COLOUR_SUPPORT)}")
        else:
            lines.append(f"  │  Support  : {c('(none)', _COLOUR_DIM)}")

        # Top-N weight bars.
        if manifest.active_weights:
            lines.append(f"  │  {c('Weights :', BOLD)}")
            items: List[Tuple[str, float]] = list(manifest.active_weights.items())
            for model_id, wt in items:
                is_primary = model_id == manifest.primary_model_id
                bar_col = _COLOUR_PRIMARY if is_primary else _COLOUR_WEIGHT
                marker = "★ " if is_primary else "  "
                wbar = _bar(wt, colour=bar_col)
                lines.append(f"  │   {marker}{wbar}  {model_id}")
        else:
            lines.append(f"  │  {c('Weights  : (no topology data)', _COLOUR_DIM)}")

        # Devices.
        if manifest.active_device_ids:
            devices_str = ", ".join(manifest.active_device_ids)
            if len(devices_str) > 42:
                devices_str = devices_str[:39] + "..."
            lines.append(f"  │  Devices  : {c(devices_str, col)}")
        else:
            lines.append(f"  │  Devices  : {c('(none)', _COLOUR_DIM)}")

        # Route reason.
        if manifest.route_reason:
            reason = manifest.route_reason
            if len(reason) > 44:
                reason = reason[:41] + "..."
            lines.append(f"  │  {c('Reason   : ' + reason, _COLOUR_DIM)}")

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_unavailable() -> str:
        """Render a graceful degradation placeholder."""
        return (
            c("  ┌─ Manifest Stage (显现台) ────────────────────────┐", BOLD) + "\n"
            "  │  (desktop_projection package not available)\n"
            + c("  └─────────────────────────────────────────────────┘", BOLD)
        )
