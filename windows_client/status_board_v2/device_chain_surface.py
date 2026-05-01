"""
windows_client/status_board_v2/device_chain_surface.py
========================================================
Multi-device and cross-device task chain display surface for Status Board V2.

Renders a live operator view of:
- All registered devices and their connection status
- Active task chains across devices (local + delegated)
- Per-device execution stage and last-seen task summary
- Cross-device dispatch pipeline status

Design constraints
------------------
- **Projection-driven** — all data is read from the RuntimeProjection dict
  produced by the V2 server; never reconstructed from subsystem internals.
- **Read-only** — this surface has no write path.
- **Graceful degradation** — missing projection keys produce a safe
  placeholder rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import _ansi

logger = logging.getLogger("Galaxy.DeviceChainSurface")

_BOLD = _ansi.BOLD
_COLOUR_OK = "\033[32m"
_COLOUR_WARN = "\033[33m"
_COLOUR_ERROR = "\033[31m"
_COLOUR_DIM = "\033[90m"

DEVICE_CHAIN_SURFACE_AUTHORITY: str = (
    "DEVICE_CHAIN_SURFACE_AUTHORITY_V1: "
    "windows_client.status_board_v2.device_chain_surface renders the "
    "multi-device and cross-device task chain operator panel from the "
    "RuntimeProjection produced by the V2 server.  Read-only surface."
)


class DeviceChainSurface:
    """
    Multi-device and cross-device task chain surface.

    Reads the following keys from the RuntimeProjection:

    ``devices``
        A list of device dicts with at minimum ``device_id``,
        ``connection_state``, ``last_seen``, ``capabilities`` (list of
        capability ids), and ``execution_stage``.

    ``task_chains``
        Optional list of task chain dicts with ``chain_id``,
        ``status``, ``steps`` (list of step dicts with ``device_id``,
        ``step_type``, ``state``), and ``summary``.

    ``cross_device_dispatch``
        Optional dict with ``active`` (bool), ``pending_tasks`` (int),
        ``delegated_tasks`` (int), ``completed_tasks`` (int).

    All keys are optional; missing data degrades to placeholder text.
    """

    def render(self, projection: Dict[str, Any]) -> str:
        """
        Render the multi-device and task chain panel.

        Parameters
        ----------
        projection:
            A dict conforming to the RuntimeProjection schema.

        Returns
        -------
        str
            Multi-line panel string ready for ``print()``.
        """
        lines: List[str] = []

        # ── Devices ──────────────────────────────────────────────────
        lines.append(_ansi.c("  ── Devices ──", _BOLD))
        devices: List[Dict] = projection.get("devices") or []
        if not devices:
            # Try alternative projection key used by some surfaces
            active_ids: List[str] = projection.get("active_device_ids") or []
            if active_ids:
                for dev_id in active_ids:
                    lines.append(f"  [{_ansi.c('●', _COLOUR_OK)}] {dev_id}")
            else:
                lines.append(_ansi.c("  (no devices registered)", _COLOUR_DIM))
        else:
            for dev in devices:
                dev_id = dev.get("device_id") or dev.get("id") or "unknown"
                state = (dev.get("connection_state") or "unknown").lower()
                if state in ("connected", "online", "active"):
                    dot = _ansi.c("●", _COLOUR_OK)
                    state_label = _ansi.c(state, _COLOUR_OK)
                elif state in ("reconnecting", "degraded"):
                    dot = _ansi.c("◑", _COLOUR_WARN)
                    state_label = _ansi.c(state, _COLOUR_WARN)
                else:
                    dot = _ansi.c("○", _COLOUR_DIM)
                    state_label = _ansi.c(state, _COLOUR_DIM)
                caps = dev.get("capabilities") or []
                cap_summary = ", ".join(str(c) for c in caps[:5])
                if len(caps) > 5:
                    cap_summary += f" +{len(caps) - 5}"
                stage = dev.get("execution_stage") or ""
                stage_str = f"  stage={stage}" if stage else ""
                lines.append(
                    f"  [{dot}] {dev_id:<20} {state_label:<12}{stage_str}"
                )
                if cap_summary:
                    lines.append(
                        _ansi.c(f"       caps: {cap_summary}", _COLOUR_DIM)
                    )

        # ── Cross-device dispatch ─────────────────────────────────────
        lines.append("")
        lines.append(_ansi.c("  ── Cross-Device Dispatch ──", _BOLD))
        cd = projection.get("cross_device_dispatch") or {}
        if isinstance(cd, dict) and cd:
            active = cd.get("active", False)
            active_label = (
                _ansi.c("active", _COLOUR_OK)
                if active
                else _ansi.c("idle", _COLOUR_DIM)
            )
            pending = cd.get("pending_tasks", 0)
            delegated = cd.get("delegated_tasks", 0)
            completed = cd.get("completed_tasks", 0)
            lines.append(
                f"  state={active_label}  "
                f"pending={pending}  delegated={delegated}  "
                f"completed={completed}"
            )
        else:
            lines.append(_ansi.c("  (no cross-device dispatch data)", _COLOUR_DIM))

        # ── Task chains ───────────────────────────────────────────────
        lines.append("")
        lines.append(_ansi.c("  ── Task Chains ──", _BOLD))
        chains: List[Dict] = projection.get("task_chains") or []
        if not chains:
            # Fall back to current_task_summary from execution projection
            task_summary = projection.get("current_task_summary") or ""
            exec_stage = projection.get("execution_stage") or ""
            if task_summary or exec_stage:
                lines.append(
                    f"  stage={exec_stage or '—'}  task={task_summary or '—'}"
                )
            else:
                lines.append(_ansi.c("  (no active task chains)", _COLOUR_DIM))
        else:
            for chain in chains[:5]:  # show at most 5 chains
                chain_id = chain.get("chain_id") or chain.get("id") or "?"
                status = (chain.get("status") or "unknown").lower()
                if status in ("completed", "success"):
                    s_label = _ansi.c(status, _COLOUR_OK)
                elif status in ("running", "executing", "in_progress"):
                    s_label = _ansi.c(status, _COLOUR_WARN)
                elif status in ("failed", "error"):
                    s_label = _ansi.c(status, _COLOUR_ERROR)
                else:
                    s_label = _ansi.c(status, _COLOUR_DIM)
                summary = chain.get("summary") or ""
                lines.append(f"  chain={chain_id}  [{s_label}]  {summary}")

                steps: List[Dict] = chain.get("steps") or []
                for step in steps[:4]:  # show at most 4 steps per chain
                    step_dev = step.get("device_id") or "local"
                    step_type = step.get("step_type") or "?"
                    step_state = (step.get("state") or "?").lower()
                    if step_state in ("done", "completed"):
                        arrow = _ansi.c("✓", _COLOUR_OK)
                    elif step_state in ("running", "executing"):
                        arrow = _ansi.c("→", _COLOUR_WARN)
                    else:
                        arrow = _ansi.c("·", _COLOUR_DIM)
                    lines.append(
                        _ansi.c(
                            f"       {arrow} [{step_dev}] {step_type}",
                            _COLOUR_DIM,
                        )
                    )
                if len(steps) > 4:
                    lines.append(
                        _ansi.c(
                            f"       … +{len(steps) - 4} more steps",
                            _COLOUR_DIM,
                        )
                    )

        return "\n".join(lines)
