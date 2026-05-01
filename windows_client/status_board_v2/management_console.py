"""
windows_client/status_board_v2/management_console.py
=====================================================
Desktop Management Console Surface
------------------------------------

Renders a comprehensive management view for the integrated dual-repo system,
covering:

- **Cross-device & multi-device status** — all connected Android/desktop
  devices, their capabilities, execution stage, and task summary.
- **Task chain status** — active, pending, and recently completed task chains
  across all devices, with per-chain step visibility.
- **Model / provider fill-in panel** — shows which LLM providers have keys set
  and which are missing, with CLI instructions for filling them in.
- **System long-run readiness** — summarises whether the integrated system
  can plausibly run continuously based on the current configuration state.

This surface addresses the user concern:

    "The desktop should show cross-device management, multi-device status,
     task chains, model fill-in, and status display — all in one place."

The management console is rendered as an additional panel below the standard
status board surfaces.  It is activated by passing ``--management`` to the
status board CLI.

Usage
-----
::

    # Show the management console alongside the standard board
    python -m windows_client.status_board_v2 --management

    # Show the management console only (no other surfaces)
    python -m windows_client.status_board_v2 --management-only
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from . import _ansi

logger = logging.getLogger("Galaxy.ManagementConsole")

# ANSI colour shortcuts
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_RESET  = _ansi.RESET
_BOLD   = _ansi.BOLD


# ---------------------------------------------------------------------------
# Device status section
# ---------------------------------------------------------------------------

class DeviceManagementSection:
    """Renders the multi-device / cross-device connection status panel."""

    def render(self, projection: Dict[str, Any]) -> str:
        lines: List[str] = [_ansi.c("  ── Connected Devices ──", _BOLD)]

        devices = self._get_devices(projection)
        if not devices:
            lines.append(_ansi.c("  ✗  No devices connected", _YELLOW))
            lines.append("     Start the Galaxy server and connect Android/desktop clients.")
            return "\n".join(lines)

        for dev in devices:
            did     = dev.get("device_id", "?")
            dtype   = dev.get("device_type", "?")
            stage   = dev.get("execution_stage", "idle")
            task    = dev.get("current_task_summary", "")
            caps    = dev.get("capabilities", [])
            online  = dev.get("online", True)

            status_icon  = "✓" if online else "✗"
            status_colour = _GREEN if online else _RED
            cap_str = ", ".join(caps[:4]) + ("…" if len(caps) > 4 else "")
            lines.append(
                _ansi.c(f"  {status_icon}  {did:<20} [{dtype}]", status_colour)
            )
            lines.append(f"     stage: {stage:<16} task: {task or '—'}")
            if cap_str:
                lines.append(f"     caps : {cap_str}")

        return "\n".join(lines)

    def _get_devices(self, projection: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract device list from the projection dict or live registry."""
        # 1. Try projection first (fast, no I/O)
        devices = projection.get("devices") or projection.get("active_devices") or []
        if devices:
            return list(devices)

        # 2. Fall back to the live device registry
        try:
            from core.device_registry import DeviceRegistry
            registry = DeviceRegistry()
            raw = registry.get_all_devices() if hasattr(registry, "get_all_devices") else []
            return [d if isinstance(d, dict) else vars(d) for d in raw]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Task chain section
# ---------------------------------------------------------------------------

class TaskChainSection:
    """Renders the active / pending / recent task chain status panel."""

    _MAX_RECENT = 5

    def render(self, projection: Dict[str, Any]) -> str:
        lines: List[str] = [_ansi.c("  ── Task Chains ──", _BOLD)]

        chains = self._get_task_chains(projection)
        if not chains:
            lines.append("  —  No active task chains")
            return "\n".join(lines)

        for chain in chains:
            chain_id  = chain.get("task_id") or chain.get("chain_id", "?")
            status    = chain.get("status", "?")
            steps     = chain.get("steps") or []
            device_id = chain.get("device_id", "")
            step_str  = f"  {len(steps)} step(s)" if steps else ""

            colour = _GREEN if status in ("completed", "success") else (
                _RED if status in ("failed", "error") else _YELLOW
            )
            lines.append(
                _ansi.c(
                    f"  {'✓' if status == 'completed' else ('✗' if status == 'failed' else '…')}"
                    f"  {chain_id[:24]:<26} [{status}]{step_str}",
                    colour,
                )
            )
            if device_id:
                lines.append(f"     device: {device_id}")
            # Show first 3 steps
            for i, step in enumerate(steps[:3]):
                step_name   = step.get("name") or step.get("action", "step")
                step_status = step.get("status", "")
                lines.append(f"       {i+1}. {step_name} [{step_status}]")
            if len(steps) > 3:
                lines.append(f"       … {len(steps)-3} more step(s)")

        return "\n".join(lines)

    def _get_task_chains(self, projection: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract task chain list from the projection or task registry."""
        chains = (
            projection.get("task_chains") or
            projection.get("active_tasks") or
            projection.get("tasks") or
            []
        )
        if chains:
            return list(chains)[: self._MAX_RECENT]

        try:
            from core.task_lifecycle import get_task_lifecycle_tracker
            tracker = get_task_lifecycle_tracker()
            return list(tracker.get_recent(self._MAX_RECENT))
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Model / provider fill-in section
# ---------------------------------------------------------------------------

class ModelFillInSection:
    """Renders the LLM provider status and fill-in instructions panel."""

    def render(self, _projection: Optional[Dict[str, Any]] = None) -> str:
        lines: List[str] = [_ansi.c("  ── LLM Providers ──", _BOLD)]
        statuses = self._get_provider_statuses()

        if not statuses:
            lines.append("  —  Provider status unavailable")
            return "\n".join(lines)

        ready = [p for p in statuses if p.get("ready")]
        not_ready = [p for p in statuses if not p.get("ready")]

        for p in ready:
            lines.append(_ansi.c(f"  ✓  {p['provider_id']:<14} enabled + key set", _GREEN))

        for p in not_ready:
            pid     = p["provider_id"]
            enabled = p.get("enabled", False)
            has_key = p.get("has_key", False)
            if enabled and not has_key:
                lines.append(
                    _ansi.c(
                        f"  ✗  {pid:<14} enabled but API key missing  "
                        f"→ --set-api-key {pid}=YOUR_KEY",
                        _RED,
                    )
                )
            elif not enabled:
                lines.append(
                    _ansi.c(
                        f"  —  {pid:<14} disabled  "
                        f"→ --apply-toggle {pid}=true",
                        _YELLOW,
                    )
                )

        if not ready:
            lines.append(
                _ansi.c(
                    "  ⚠  No ready providers — set at least one API key to enable inference.",
                    _RED,
                )
            )
        return "\n".join(lines)

    def _get_provider_statuses(self) -> List[Dict[str, Any]]:
        try:
            from core.config_service import get_config_service
            svc = get_config_service()
            return [p.to_dict() for p in svc.get_provider_statuses()]
        except Exception:
            return []


# ---------------------------------------------------------------------------
# Long-run readiness section
# ---------------------------------------------------------------------------

class LongRunReadinessSection:
    """Renders a long-run operability checklist for the integrated system."""

    def render(self, projection: Dict[str, Any]) -> str:
        lines: List[str] = [_ansi.c("  ── Long-Run Readiness ──", _BOLD)]
        items = self._collect_items(projection)
        ready_count = sum(1 for _, ok, _ in items if ok)
        for label, ok, hint in items:
            icon   = "✓" if ok else "✗"
            colour = _GREEN if ok else _YELLOW
            row    = f"  {icon}  {label}"
            if not ok and hint:
                row += f"  → {hint}"
            lines.append(_ansi.c(row, colour))
        lines.append(
            _ansi.c(
                f"\n  Readiness: {ready_count}/{len(items)} checks passed",
                _GREEN if ready_count == len(items) else _YELLOW,
            )
        )
        return "\n".join(lines)

    def _collect_items(self, projection: Dict[str, Any]) -> List[tuple]:
        """Return list of (label, ok, hint) tuples."""
        items: List[tuple] = []

        # LLM provider
        try:
            from core.config_service import get_config_service
            svc = get_config_service()
            statuses = svc.get_provider_statuses()
            has_ready = any(p.ready for p in statuses)
            items.append((
                "LLM provider configured",
                has_ready,
                "--set-api-key PROVIDER=YOUR_KEY",
            ))

            # Gateway URL
            gw = svc.get_network_url("gateway_url")
            items.append((
                "Gateway URL set",
                bool(gw),
                "--set-url gateway_url=ws://IP:8765",
            ))

            # Android gateway URL
            agw = svc.get_network_url("android_gateway_url")
            items.append((
                "Android gateway URL set",
                bool(agw or gw),
                "--set-url android_gateway_url=ws://IP:8765",
            ))

            # Android inference mode
            cfg = svc._store.read_config()
            amode = cfg.get("android", {}).get("inference_mode", "")
            items.append((
                f"Android inference mode set ({amode or 'not set'})",
                bool(amode),
                "--set-android-inference-mode center",
            ))
        except Exception:
            items.append(("Config service available", False, "start the Galaxy server"))

        # Device connectivity
        try:
            devices = self._get_devices(projection)
            items.append((
                f"Devices connected ({len(devices)})",
                len(devices) > 0,
                "install + configure the Galaxy Android app",
            ))
        except Exception:
            items.append(("Device registry available", False, "start the Galaxy server"))

        # Active multimodal provider
        try:
            router = self._get_router()
            has_mm = False
            if router is not None:
                providers = getattr(router, "_providers", {})
                has_mm = any(getattr(cfg, "multimodal", False) for cfg in providers.values())
            items.append((
                "Native multimodal provider available",
                has_mm,
                "enable openai or gemini with a key that supports vision",
            ))
        except Exception:
            items.append(("Multimodal router available", False, "start the Galaxy server"))

        return items

    def _get_devices(self, projection: Dict[str, Any]) -> List[Any]:
        devices = projection.get("devices") or projection.get("active_devices") or []
        if devices:
            return list(devices)
        try:
            from core.device_registry import DeviceRegistry
            reg = DeviceRegistry()
            return reg.get_all_devices() if hasattr(reg, "get_all_devices") else []
        except Exception:
            return []

    def _get_router(self):
        try:
            from core.unified.llm_router import get_unified_llm_router
            return get_unified_llm_router()
        except Exception:
            pass
        try:
            from core.multi_llm_router import get_llm_router
            return get_llm_router()
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Top-level management console
# ---------------------------------------------------------------------------

class ManagementConsole:
    """
    Integrated desktop management console.

    Aggregates all management panels into a single cohesive display:
    connected devices, task chains, model/provider fill-in, and long-run
    readiness.  Rendered as a panel block below the standard status board.
    """

    def __init__(self) -> None:
        self._devices  = DeviceManagementSection()
        self._tasks    = TaskChainSection()
        self._models   = ModelFillInSection()
        self._readiness = LongRunReadinessSection()

    def render(self, projection: Dict[str, Any]) -> str:
        """Render all management sections."""
        sep = _ansi.c("─" * 52, _BOLD)
        parts = [
            sep,
            _ansi.c("  Management Console", _BOLD),
            sep,
            self._devices.render(projection),
            sep,
            self._tasks.render(projection),
            sep,
            self._models.render(projection),
            sep,
            self._readiness.render(projection),
            sep,
        ]
        return "\n".join(parts)
