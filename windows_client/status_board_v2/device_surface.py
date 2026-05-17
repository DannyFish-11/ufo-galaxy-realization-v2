"""
windows_client/status_board_v2/device_surface.py
=================================================
DeviceSurface — renders the device and execution context fields of a
RuntimeProjection.

READ-ONLY surface: displays information only, never sends commands.

Displayed fields
----------------
- ``active_device_ids``        : IDs of currently active devices
- ``execution_stage``          : current execution stage tag (e.g. "planning")
- ``current_task_summary``     : short task description (if present)
- ``participation_truth_consumption`` : participation tier, dispatch status,
                                  fully-attached flag, lifecycle stage
- ``device_dispatch_readiness``: structured dispatch readiness blocker reasons
                                  (status, registration_gaps, blocking_notes)
                                  so operators can see *why* a device is not
                                  dispatchable, not just that it isn't.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._ansi import BOLD, RESET, c

_COLOUR_DEVICE = "\033[36m"    # cyan
_COLOUR_STAGE = "\033[33m"     # yellow
_COLOUR_TASK = "\033[37m"      # white
_COLOUR_NONE = "\033[90m"      # grey
_COLOUR_WARN = "\033[33m"      # yellow (same as stage, for warnings)
_COLOUR_ERROR = "\033[31m"     # red (for blocked/not-ready)
_COLOUR_OK = "\033[32m"        # green (for ready)


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

        # dispatch_readiness 字段可由 projection 直接携带（服务端注入）或为 None
        dispatch_readiness = projection.get("device_dispatch_readiness")
        if not isinstance(dispatch_readiness, dict):
            dispatch_readiness = {}
        acceptance_chain = projection.get("cross_repo_acceptance_chain")
        if not isinstance(acceptance_chain, dict):
            acceptance_chain = {}

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
            dispatch_colour = _COLOUR_OK if dispatch_eligible else _COLOUR_ERROR
            attach_colour = _COLOUR_OK if fully_attached else _COLOUR_WARN
            lines.append(
                "  │  "
                f"{c('Tier    :', BOLD)} {c(str(participation_tier), _COLOUR_DEVICE)} "
                f"{c(f'dispatch={dispatch_eligible}', dispatch_colour)} "
                f"{c('|', _COLOUR_NONE)} "
                f"{c(f'fully_attached={fully_attached}', attach_colour)}"
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

        # ------------------------------------------------------------------
        # Dispatch readiness blocker section
        # 当 device_dispatch_readiness 存在时，显示结构化拦截原因，
        # 而不仅仅是布尔标志。这是 control-plane 可见性的关键改进。
        # ------------------------------------------------------------------
        if dispatch_readiness:
            dr_status = dispatch_readiness.get("status") or ""
            dr_reason = dispatch_readiness.get("reason") or ""
            dr_gaps: List[str] = dispatch_readiness.get("registration_gaps") or []
            dr_notes: List[str] = dispatch_readiness.get("blocking_notes") or []
            dr_ready = bool(dispatch_readiness.get("dispatch_ready"))

            status_colour = _COLOUR_OK if dr_ready else _COLOUR_ERROR
            lines.append(
                f"  │  {c('Dispatch:', BOLD)} "
                f"{c(dr_status or '(unknown)', status_colour)}"
            )

            if not dr_ready and dr_reason:
                # 截断过长的原因说明以适应终端宽度
                truncated_reason = (
                    dr_reason if len(dr_reason) <= 56 else dr_reason[:53] + "..."
                )
                lines.append(
                    f"  │    {c('→ reason:', BOLD)} "
                    f"{c(truncated_reason, _COLOUR_WARN)}"
                )

            # 注册 gap 列表（每个失败步骤单独一行）
            if dr_gaps:
                gaps_str = ", ".join(dr_gaps)
                truncated_gaps = (
                    gaps_str if len(gaps_str) <= 54 else gaps_str[:51] + "..."
                )
                lines.append(
                    f"  │    {c('→ reg_gaps:', BOLD)} "
                    f"{c(truncated_gaps, _COLOUR_ERROR)}"
                )

            # 附加阻断说明（最多显示 2 条）
            for note in dr_notes[:2]:
                truncated_note = note if len(note) <= 54 else note[:51] + "..."
                lines.append(
                    f"  │    {c('→ note:', BOLD)} "
                    f"{c(truncated_note, _COLOUR_NONE)}"
                )

        if acceptance_chain:
            e2e_status = str(acceptance_chain.get("overall_status") or "(unknown)")
            e2e_colour = _COLOUR_OK if e2e_status == "passed" else _COLOUR_ERROR
            lines.append(f"  │  {c('E2E     :', BOLD)} {c(e2e_status, e2e_colour)}")
            summary = str(acceptance_chain.get("summary") or "")
            if summary:
                truncated_summary = summary if len(summary) <= 56 else summary[:53] + "..."
                lines.append(
                    f"  │    {c('→ chain:', BOLD)} {c(truncated_summary, _COLOUR_NONE)}"
                )
            failing_stage = acceptance_chain.get("failing_stage")
            if failing_stage not in (None, ""):
                lines.append(
                    f"  │    {c('→ stop_at:', BOLD)} {c(str(failing_stage), _COLOUR_WARN)}"
                )

        lines.append(c("  └─────────────────────────────────────────────────┘", BOLD))
        return "\n".join(lines)
