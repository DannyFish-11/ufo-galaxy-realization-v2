"""
windows_client/status_board_v2/device_surface.py
=================================================
DeviceSurface — renders the device and execution context fields of a
RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Displayed fields
----------------
- ``active_device_ids``  : IDs of currently active devices
- ``execution_stage``    : current execution stage tag (e.g. "planning")
- ``current_task_summary``: short task description (if present)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._ansi import BOLD, RESET, c

_COLOUR_DEVICE = "\033[36m"    # cyan
_COLOUR_STAGE = "\033[33m"     # yellow
_COLOUR_TASK = "\033[37m"      # white
_COLOUR_NONE = "\033[90m"      # grey


class DeviceSurface:
    """Renders the device and execution context surface.

    READ-ONLY — this class only produces display strings.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """Return a multi-line string for the device surface.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            Multi-line string ready to print.
        """
        device_ids: List[str] = projection.get("active_device_ids") or []
        stage: Optional[str] = projection.get("execution_stage")
        task_summary: Optional[str] = projection.get("current_task_summary")

        lines = [
            c("  ┌─ Device & Execution Context ────────────────────┐", BOLD),
        ]

        # Active devices.
        if device_ids:
            devices_str = ", ".join(device_ids)
            lines.append(
                f"  │  {c('Devices :', BOLD)} {c(devices_str, _COLOUR_DEVICE)}"
            )
        else:
            lines.append(
                f"  │  {c('Devices :', BOLD)} {c('(none active)', _COLOUR_NONE)}"
            )

        # Execution stage.
        if stage:
            lines.append(
                f"  │  {c('Stage   :', BOLD)} {c(stage, _COLOUR_STAGE)}"
            )
        else:
            lines.append(
                f"  │  {c('Stage   :', BOLD)} {c('(idle)', _COLOUR_NONE)}"
            )

        # Current task summary.
        if task_summary:
            truncated = task_summary if len(task_summary) <= 46 else task_summary[:43] + "..."
            lines.append(
                f"  │  {c('Task    :', BOLD)} {c(truncated, _COLOUR_TASK)}"
            )

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)
