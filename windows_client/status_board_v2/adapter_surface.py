"""
windows_client/status_board_v2/adapter_surface.py
==================================================
PR-10: First usable desktop status board UI surface.

Consumes the :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`
produced by the PR-9 adapter layer and renders a clear, operator-visible
status board surface covering:

- Readiness / quality state (canonical / degraded / partial / unavailable)
- Canonical-vs-fallback authority state
- Primary topology / provider identity when available
- Provider and routing summary
- OneAPI lower-horizon summary (always clearly visually distinct)
- Degraded / partial / unavailable states in a visually distinct way

Design constraints
------------------
- **Adapter-driven** — the surface consumes a :class:`DesktopClientViewModel`
  (or a plain dict from :meth:`~DesktopClientViewModel.to_dict`) and never
  reconstructs truth from raw nested authority dictionaries.
- **OneAPI stays lower-horizon** — the OneAPI block is rendered in a separate
  lower section and is never promoted to a top-level routing-authority peer.
- **Read-only** — this surface never sends commands or modifies state.
- **Graceful** — all fields are treated as optional; the surface renders a
  safe "unavailable" frame when the view-model is ``None`` or minimal.

Usage::

    from windows_client.status_board_v2.adapter_surface import AdapterSurface
    from core.desktop_consumption_adapter import adapt_integration_payload

    surface = AdapterSurface()
    vm = adapt_integration_payload(payload)
    print(surface.render_view_model(vm))
"""

from __future__ import annotations

import datetime
import json
from typing import Any, Dict, Optional

from ._ansi import BOLD, RESET, c

# ---------------------------------------------------------------------------
# Colour palette for the adapter surface
# ---------------------------------------------------------------------------

_COLOUR_CANONICAL = "\033[32m"      # green  — healthy / canonical
_COLOUR_DEGRADED = "\033[33m"       # yellow — degraded / legacy fallback
_COLOUR_PARTIAL = "\033[36m"        # cyan   — partial / some components missing
_COLOUR_UNAVAILABLE = "\033[31m"    # red    — unavailable / no topology
_COLOUR_UNKNOWN = "\033[90m"        # grey   — unknown readiness
_COLOUR_FALLBACK_WARN = "\033[33m"  # yellow — legacy-fallback warning label
_COLOUR_ONEAPI = "\033[35m"         # magenta — OneAPI lower-horizon block
_COLOUR_DIM = "\033[90m"            # dim grey — secondary info
_COLOUR_LABEL = "\033[37m"          # white  — field labels

# ---------------------------------------------------------------------------
# Readiness display metadata
# ---------------------------------------------------------------------------

_READINESS_SYMBOL: Dict[str, str] = {
    "canonical":   "●",
    "degraded":    "◑",
    "partial":     "◔",
    "unavailable": "○",
    "unknown":     "?",
}

_READINESS_COLOUR: Dict[str, str] = {
    "canonical":   _COLOUR_CANONICAL,
    "degraded":    _COLOUR_DEGRADED,
    "partial":     _COLOUR_PARTIAL,
    "unavailable": _COLOUR_UNAVAILABLE,
    "unknown":     _COLOUR_UNKNOWN,
}

_READINESS_DESCRIPTION: Dict[str, str] = {
    "canonical":   "CANONICAL — fully authoritative topology",
    "degraded":    "DEGRADED  — legacy fallback active (not authoritative)",
    "partial":     "PARTIAL   — canonical source present, some components missing",
    "unavailable": "UNAVAILABLE — no topology data available",
    "unknown":     "UNKNOWN   — readiness could not be determined",
}

# Separator rule for OneAPI lower-horizon section.
_RULE_WIDTH = 48
_RULE = "  │  " + "─" * _RULE_WIDTH


def _trunc(s: Optional[str], maxlen: int = 45) -> str:
    """Truncate *s* to *maxlen* characters, appending '…' if needed."""
    if not s:
        return "(none)"
    return s if len(s) <= maxlen else s[:maxlen - 1] + "…"


class AdapterSurface:
    """PR-10: First usable desktop status board UI surface.

    Renders the adapter-driven status board surface from a
    :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`.

    READ-ONLY — this class only produces display strings.
    """

    # ------------------------------------------------------------------
    # Primary entry points
    # ------------------------------------------------------------------

    def render_view_model(
        self,
        vm: Any,
    ) -> str:
        """Render the status board surface from a :class:`DesktopClientViewModel`.

        Parameters
        ----------
        vm:
            A :class:`~core.desktop_consumption_adapter.DesktopClientViewModel`
            instance, or ``None`` to render a safe unavailable frame.

        Returns
        -------
        str
            Multi-line string ready for ``print()``.
        """
        if vm is None:
            return self._render_unavailable_frame("no view-model available")

        readiness_state = getattr(vm, "readiness_state", None)
        readiness_str = (
            readiness_state.value
            if hasattr(readiness_state, "value")
            else str(readiness_state or "unknown")
        )
        is_canonical: bool = bool(getattr(vm, "is_canonical", False))
        is_degraded: bool = bool(getattr(vm, "is_degraded", False))
        is_partial: bool = bool(getattr(vm, "is_partial", False))
        is_unavailable: bool = bool(getattr(vm, "is_unavailable", False))
        topology_legacy: bool = bool(getattr(vm, "topology_legacy_fallback_active", False))
        routing_legacy: bool = bool(getattr(vm, "routing_legacy_fallback_active", False))
        provider_id: Optional[str] = getattr(vm, "topology_provider_id", None)
        model_id: Optional[str] = getattr(vm, "topology_primary_model_id", None)
        route_reason: Optional[str] = getattr(vm, "topology_route_reason", None)
        routing_auth: Optional[str] = getattr(vm, "routing_authority_source", None)
        integration_health: str = str(
            getattr(vm, "integration_health", "unknown") or "unknown"
        )
        adapter_authority: Optional[str] = getattr(vm, "adapter_authority", None)
        view_model_id: Optional[str] = getattr(vm, "view_model_id", None)

        provider_routing = getattr(vm, "provider_routing", None)
        oneapi_horizon = getattr(vm, "oneapi_horizon", None)

        return self._render(
            readiness_str=readiness_str,
            is_canonical=is_canonical,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            topology_legacy=topology_legacy,
            routing_legacy=routing_legacy,
            provider_id=provider_id,
            model_id=model_id,
            route_reason=route_reason,
            routing_auth=routing_auth,
            integration_health=integration_health,
            adapter_authority=adapter_authority,
            view_model_id=view_model_id,
            provider_routing=provider_routing,
            oneapi_horizon=oneapi_horizon,
        )

    def render_dict(self, vm_dict: Dict[str, Any]) -> str:
        """Render the status board surface from a view-model dict.

        Accepts the output of :meth:`DesktopClientViewModel.to_dict`.
        Useful when the view-model has been serialised (e.g. from JSON).

        Parameters
        ----------
        vm_dict:
            A dict as returned by ``DesktopClientViewModel.to_dict()``.

        Returns
        -------
        str
            Multi-line string ready for ``print()``.
        """
        if not vm_dict:
            return self._render_unavailable_frame("empty view-model dict")

        readiness_str: str = str(vm_dict.get("readiness_state") or "unknown")
        is_canonical: bool = bool(vm_dict.get("is_canonical", False))
        is_degraded: bool = bool(vm_dict.get("is_degraded", False))
        is_partial: bool = bool(vm_dict.get("is_partial", False))
        is_unavailable: bool = bool(vm_dict.get("is_unavailable", False))
        topology_legacy: bool = bool(
            vm_dict.get("topology_legacy_fallback_active", False)
        )
        routing_legacy: bool = bool(
            vm_dict.get("routing_legacy_fallback_active", False)
        )
        provider_id: Optional[str] = vm_dict.get("topology_provider_id")
        model_id: Optional[str] = vm_dict.get("topology_primary_model_id")
        route_reason: Optional[str] = vm_dict.get("topology_route_reason")
        routing_auth: Optional[str] = vm_dict.get("routing_authority_source")
        integration_health: str = str(
            vm_dict.get("integration_health") or "unknown"
        )
        adapter_authority: Optional[str] = vm_dict.get("adapter_authority")
        view_model_id: Optional[str] = vm_dict.get("view_model_id")

        # Build lightweight proxy objects for provider_routing / oneapi_horizon
        # from their nested dicts so _render() can use attribute access.
        pr_dict = vm_dict.get("provider_routing") or {}
        oa_dict = vm_dict.get("oneapi_horizon") or {}

        class _RoutingProxy:
            def __init__(self, d: Dict[str, Any]) -> None:
                self.selected_provider: Optional[str] = d.get("selected_provider")
                self.primary_model_id: Optional[str] = d.get("primary_model_id")
                self.vendor_source: Optional[str] = d.get("vendor_source")
                self.routing_authority_source: Optional[str] = d.get(
                    "routing_authority_source"
                )
                self.legacy_routing_fallback_active: bool = d.get(
                    "legacy_routing_fallback_active", False
                )
                self.route_reason: Optional[str] = d.get("route_reason")
                self.provider_available: bool = d.get("provider_available", False)

        class _OneAPIProxy:
            def __init__(self, d: Dict[str, Any]) -> None:
                self.system_layer: Optional[str] = d.get("system_layer")
                self.is_lower_horizon_only: bool = True
                self.provider_id: Optional[str] = d.get("provider_id")
                self.available: bool = d.get("available", False)

        return self._render(
            readiness_str=readiness_str,
            is_canonical=is_canonical,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            topology_legacy=topology_legacy,
            routing_legacy=routing_legacy,
            provider_id=provider_id,
            model_id=model_id,
            route_reason=route_reason,
            routing_auth=routing_auth,
            integration_health=integration_health,
            adapter_authority=adapter_authority,
            view_model_id=view_model_id,
            provider_routing=_RoutingProxy(pr_dict) if pr_dict else None,
            oneapi_horizon=_OneAPIProxy(oa_dict) if oa_dict else None,
        )

    # ------------------------------------------------------------------
    # Internal rendering
    # ------------------------------------------------------------------

    def _render(
        self,
        *,
        readiness_str: str,
        is_canonical: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        topology_legacy: bool,
        routing_legacy: bool,
        provider_id: Optional[str],
        model_id: Optional[str],
        route_reason: Optional[str],
        routing_auth: Optional[str],
        integration_health: str,
        adapter_authority: Optional[str],
        view_model_id: Optional[str],
        provider_routing: Any,
        oneapi_horizon: Any,
    ) -> str:
        """Core rendering method."""
        sym = _READINESS_SYMBOL.get(readiness_str, "?")
        col = _READINESS_COLOUR.get(readiness_str, _COLOUR_UNKNOWN)
        desc = _READINESS_DESCRIPTION.get(readiness_str, readiness_str.upper())

        lines = [
            c("  ┌─ Desktop Status Board ─ Adapter-Driven ──────────┐", BOLD),
        ]

        # ── Readiness state (primary, visually prominent) ─────────────────
        lines.append(
            f"  │  {c(sym + '  ' + desc, col)}"
        )

        # Legacy fallback warning banner — visible when degraded
        if topology_legacy or routing_legacy:
            labels = []
            if topology_legacy:
                labels.append("topology-legacy")
            if routing_legacy:
                labels.append("routing-legacy")
            warn_str = "  ⚠  LEGACY FALLBACK ACTIVE: " + ", ".join(labels)
            lines.append(f"  │  {c(warn_str, _COLOUR_FALLBACK_WARN)}")

        # ── Integration health ────────────────────────────────────────────
        health_col = _COLOUR_CANONICAL if integration_health == "ok" else (
            _COLOUR_DEGRADED if integration_health in ("degraded", "advisory")
            else (_COLOUR_UNAVAILABLE if integration_health == "critical"
                  else _COLOUR_UNKNOWN)
        )
        lines.append(
            f"  │  {c('Health   :', BOLD)}"
            f"  {c(integration_health, health_col)}"
        )

        # ── Primary topology / provider identity ──────────────────────────
        lines.append(f"  │")
        lines.append(
            c("  │  ┌─ Topology / Provider ─────────────────────────┐", _COLOUR_DIM)
        )

        if provider_id or model_id:
            if provider_id:
                lines.append(
                    f"  │  │  {c('Provider :', BOLD)}"
                    f"  {c(_trunc(provider_id), col)}"
                )
            if model_id:
                lines.append(
                    f"  │  │  {c('Model    :', BOLD)}"
                    f"  {c(_trunc(model_id), col)}"
                )
        else:
            lines.append(
                f"  │  │  {c('Provider / Model:', BOLD)}"
                f"  {c('(none available)', _COLOUR_UNKNOWN)}"
            )

        if route_reason:
            lines.append(
                f"  │  │  {c('Reason   :', BOLD)}"
                f"  {c(_trunc(route_reason, 42), _COLOUR_DIM)}"
            )
        if routing_auth:
            lines.append(
                f"  │  │  {c('Authority:', BOLD)}"
                f"  {c(_trunc(routing_auth, 40), _COLOUR_DIM)}"
            )

        lines.append(
            c("  │  └───────────────────────────────────────────────┘", _COLOUR_DIM)
        )

        # ── Provider / routing summary ────────────────────────────────────
        lines.append(f"  │")
        lines.append(
            c("  │  ┌─ Provider / Routing Summary ──────────────────┐", _COLOUR_DIM)
        )

        if provider_routing is not None:
            sel = getattr(provider_routing, "selected_provider", None)
            prim = getattr(provider_routing, "primary_model_id", None)
            vendor = getattr(provider_routing, "vendor_source", None)
            pr_auth = getattr(provider_routing, "routing_authority_source", None)
            pr_legacy = bool(
                getattr(provider_routing, "legacy_routing_fallback_active", False)
            )
            pr_avail = bool(getattr(provider_routing, "provider_available", False))

            if sel:
                lines.append(
                    f"  │  │  {c('Selected :', BOLD)}"
                    f"  {c(_trunc(sel), _COLOUR_LABEL)}"
                )
            if prim:
                lines.append(
                    f"  │  │  {c('Model    :', BOLD)}"
                    f"  {c(_trunc(prim), _COLOUR_DIM)}"
                )
            if vendor:
                lines.append(
                    f"  │  │  {c('Vendor   :', BOLD)}"
                    f"  {c(_trunc(vendor), _COLOUR_DIM)}"
                )
            avail_col = _COLOUR_CANONICAL if pr_avail else _COLOUR_UNAVAILABLE
            avail_str = "available" if pr_avail else "unavailable"
            lines.append(
                f"  │  │  {c('Provider :', BOLD)}"
                f"  {c(avail_str, avail_col)}"
            )
            if pr_legacy:
                lines.append(
                    f"  │  │  {c('⚠  routing-legacy fallback active', _COLOUR_FALLBACK_WARN)}"
                )
            if pr_auth:
                lines.append(
                    f"  │  │  {c('Authority:', BOLD)}"
                    f"  {c(_trunc(pr_auth, 38), _COLOUR_DIM)}"
                )
        else:
            lines.append(
                f"  │  │  {c('(no routing summary available)', _COLOUR_UNKNOWN)}"
            )

        lines.append(
            c("  │  └───────────────────────────────────────────────┘", _COLOUR_DIM)
        )

        # ── OneAPI lower-horizon block (always distinct, lower row) ────────
        lines.append(_RULE)
        lines.append(
            f"  │  {c('ONEAPI LOWER-HORIZON', BOLD)}"
            f"  {c('(integration layer — not a canonical routing peer)', _COLOUR_DIM)}"
        )

        if oneapi_horizon is not None:
            oa_layer = getattr(oneapi_horizon, "system_layer", None)
            oa_provider = getattr(oneapi_horizon, "provider_id", None)
            oa_avail = bool(getattr(oneapi_horizon, "available", False))
            oa_lower = bool(getattr(oneapi_horizon, "is_lower_horizon_only", True))

            oa_avail_str = "available" if oa_avail else "not available"
            oa_avail_col = _COLOUR_ONEAPI if oa_avail else _COLOUR_DIM
            lines.append(
                f"  │    {c('Layer    :', BOLD)}"
                f"  {c(_trunc(oa_layer) if oa_layer else '(none)', _COLOUR_ONEAPI)}"
            )
            if oa_provider:
                lines.append(
                    f"  │    {c('Provider :', BOLD)}"
                    f"  {c(_trunc(oa_provider), _COLOUR_ONEAPI)}"
                )
            lines.append(
                f"  │    {c('Status   :', BOLD)}"
                f"  {c(oa_avail_str, oa_avail_col)}"
            )
            # Always show lower-horizon-only flag — enforces the constraint visually.
            lines.append(
                f"  │    {c('Horizon  :', BOLD)}"
                f"  {c('lower-horizon only', _COLOUR_ONEAPI)}"
                f"  {c('[is_lower_horizon_only=True]', _COLOUR_DIM)}"
            )
        else:
            lines.append(
                f"  │    {c('(no OneAPI integration data)', _COLOUR_DIM)}"
            )

        # ── Footer — adapter authority and view-model ID ───────────────────
        lines.append(_RULE)
        if adapter_authority:
            short_auth = (
                adapter_authority
                if len(adapter_authority) <= 45
                else "…" + adapter_authority[-44:]
            )
            lines.append(
                f"  │  {c('Adapter  : ' + short_auth, _COLOUR_DIM)}"
            )
        if view_model_id:
            lines.append(
                f"  │  {c('VM-ID    : ' + view_model_id, _COLOUR_DIM)}"
            )

        lines.append(
            c("  └─────────────────────────────────────────────────┘", BOLD)
        )
        return "\n".join(lines)

    def _render_unavailable_frame(self, reason: str) -> str:
        """Render a safe 'unavailable' frame when no view-model is available."""
        sym = _READINESS_SYMBOL["unavailable"]
        col = _COLOUR_UNAVAILABLE
        lines = [
            c("  ┌─ Desktop Status Board ─ Adapter-Driven ──────────┐", BOLD),
            f"  │  {c(sym + '  UNAVAILABLE — ' + reason, col)}",
            f"  │  {c('(no DesktopClientViewModel available)', _COLOUR_DIM)}",
            c("  └─────────────────────────────────────────────────┘", BOLD),
        ]
        return "\n".join(lines)
