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
        participation = projection.get("participation_truth_consumption")
        if not isinstance(participation, dict):
            participation = {}
        semantics = participation.get("participation_semantics")
        if not isinstance(semantics, dict):
            semantics = {}
        mode_semantics = semantics.get("mode_semantics")
        if not isinstance(mode_semantics, dict):
            mode_semantics = {}

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

        selected_device_id = participation.get("selected_device_id")
        if selected_device_id:
            lines.append(
                f"  │  {c('Selected:', BOLD)} {c(str(selected_device_id), _COLOUR_DEVICE)}"
            )

        participation_tier = participation.get("participation_tier")
        if participation_tier not in (None, ""):
            # 首选 projection 层已归一化的字段；仅在旧 payload 缺失时回退到语义子块。
            dispatch_eligible = bool(
                participation.get("dispatch_eligible")
                if participation.get("dispatch_eligible") is not None
                else semantics.get("dispatch_gate_passed")
            )
            fully_attached = bool(
                participation.get("fully_attached")
                if participation.get("fully_attached") is not None
                else str(participation_tier) == "fully_attached"
            )
            lines.append(
                "  │  "
                f"{c('Tier    :', BOLD)} {c(str(participation_tier), _COLOUR_DEVICE)} "
                f"{c(f'[dispatch={dispatch_eligible} | fully_attached={fully_attached}]', _COLOUR_NONE)}"
            )

        local_mode_active = bool(
            participation.get("local_mode_active")
            if participation.get("local_mode_active") is not None
            else mode_semantics.get("local_mode_active")
        )
        runtime_constrained = bool(
            participation.get("runtime_constrained")
            if participation.get("runtime_constrained") is not None
            # mode_semantics 使用 constrained 命名；投影归一化后统一为 runtime_constrained。
            else mode_semantics.get("constrained")
        )
        if participation_tier not in (None, "") or mode_semantics:
            lines.append(
                "  │  "
                f"{c('Mode    :', BOLD)} "
                f"{c(f'local={local_mode_active} | constrained={runtime_constrained}', _COLOUR_NONE)}"
            )

        lifecycle_stage = participation.get("device_lifecycle_stage")
        if lifecycle_stage not in (None, ""):
            lines.append(
                f"  │  {c('Attach  :', BOLD)} {c(str(lifecycle_stage), _COLOUR_NONE)}"
            )

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)
