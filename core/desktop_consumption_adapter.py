"""
core/desktop_consumption_adapter.py
=====================================
PR-9: Desktop client consumption adapter layer.

Provides the adapter/view-model that converts the PR-8
:class:`~contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload`
(delivered in PR #436) into a stable, flat, easy-to-consume client model for
desktop status board consumers.

Design
------
After PR-8 (PR #436) the server exposes one stable integrated payload through
``GET /api/v1/projection/desktop-status-board`` including the
``DesktopStatusBoardIntegrationPayload`` with convenience shorthand properties
``.readiness`` and ``.is_canonical``.  Desktop consumers previously needed to
reconstruct truth by combining outputs from multiple endpoints or legacy/
dashboard-era assembly logic.  This adapter layer eliminates that need:

- Consume the integrated payload from
  ``GET /api/v1/projection/desktop-status-board`` (or build it via
  :func:`~core.projection.build_desktop_status_board_integration_from_runtime`).
- Pass the payload to :func:`adapt_integration_payload`.
- The resulting :class:`DesktopClientViewModel` exposes every field a desktop
  consumer needs — topology state, readiness, authority, provider routing, and
  OneAPI — without requiring the consumer to inspect nested sub-structures.

Key guarantees
--------------
- **Canonical authority is never obscured** — `.is_canonical`, `.is_degraded`,
  `.is_partial`, and `.is_unavailable` reflect the PR-7/8 semantics exactly.
- **Legacy fallback is always explicit** — `.topology_legacy_fallback_active`
  and `.routing_legacy_fallback_active` are never hidden.
- **OneAPI stays lower-horizon only** — `.oneapi_is_lower_horizon_only` is
  always ``True``; the OneAPI block is surfaced as a distinct sub-summary and
  is never promoted to a top-level routing peer.
- **Graceful degradation** — the adapter never raises; if the payload is
  minimal or partially populated the view-model still provides safe defaults.

Usage::

    from core.desktop_consumption_adapter import (
        adapt_integration_payload,
        DesktopClientViewModel,
        DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
    )
    from core.projection import build_desktop_status_board_integration_from_runtime

    payload = build_desktop_status_board_integration_from_runtime(
        continuum_state=state, route_plan=plan
    )
    vm = adapt_integration_payload(payload)

    # Quick readiness check
    if vm.is_canonical:
        print("Routing is fully canonical")
    elif vm.is_degraded:
        print("WARNING: legacy fallback active")
    elif vm.is_partial:
        print("INFO: partial data — some components unavailable")
    else:
        print("Topology unavailable")

    # Flat access — no nested dict traversal required
    print(vm.readiness_state)          # e.g. DesktopReadinessState.canonical
    print(vm.topology_provider_id)     # e.g. "openai"
    print(vm.routing_authority_source) # e.g. "TopologyRoutePlan"
    print(vm.oneapi_is_lower_horizon_only)  # always True

See ``docs/DESKTOP_CONSUMPTION_ADAPTER.md`` for design rationale and the
post-PR-9 consumption guide.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

_logger = logging.getLogger("Galaxy.Projection.DesktopConsumptionAdapter")

# ---------------------------------------------------------------------------
# PR-9: Adapter authority sentinel
# ---------------------------------------------------------------------------

#: Sentinel string identifying the desktop consumption adapter as the PR-9
#: canonical client-side adapter layer.  Downstream desktop consumers can
#: check this value to confirm the view-model was produced by the canonical
#: adapter rather than assembled ad-hoc.
DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY: str = (
    "core.desktop_consumption_adapter.adapt_integration_payload"
)


# ---------------------------------------------------------------------------
# DesktopReadinessState — client-side readiness enum
# ---------------------------------------------------------------------------


class DesktopReadinessState(str, Enum):
    """PR-9: Client-facing readiness state enum.

    Maps the PR-7 :class:`~contracts.desktop_status_projection.TopologyProjectionReadiness`
    values into a top-level client property so consumers never need to drill
    into nested authority dicts or sub-blocks to determine the primary state.

    Values
    ------
    canonical
        Topology is fully authoritative.  All routing data sourced from the
        canonical ``TopologyRoutePlan``.  Safe to render and act on.
    degraded
        Legacy fallback active.  Routing data was assembled from legacy UCP
        keys, not a canonical route plan.  Surface a warning to the operator;
        do **not** treat as fully authoritative truth.
    partial
        Canonical source present but important components are missing or
        unavailable (e.g. primary provider unavailable).  Render with a
        "partial data" indicator.
    unavailable
        No topology data available.  Do not render topology; show an
        appropriate empty/error state to the operator.
    unknown
        Readiness could not be determined from the payload (e.g. minimal
        fallback payload with no authority indicators).
    """

    canonical = "canonical"
    degraded = "degraded"
    partial = "partial"
    unavailable = "unavailable"
    unknown = "unknown"


# ---------------------------------------------------------------------------
# DesktopOneAPIHorizonSummary — flattened OneAPI block for client consumption
# ---------------------------------------------------------------------------


class DesktopOneAPIHorizonSummary:
    """PR-9: Flattened OneAPI lower-horizon summary for desktop clients.

    Exposes the most relevant fields from the nested OneAPI integration block
    so consumers do not need to traverse the raw dict.

    Attributes
    ----------
    system_layer:
        OneAPI system layer identifier (e.g. ``"aggregator_integration"``).
        ``None`` when the block is unavailable.
    is_lower_horizon_only:
        Always ``True``.  OneAPI is a lower-horizon integration block and
        must never be promoted to a top-level routing peer.
    provider_id:
        OneAPI provider identifier when available.
    available:
        Whether the OneAPI block reports itself as available / active.
    raw:
        The full raw OneAPI dict from the payload for advanced inspection.
    """

    def __init__(self, oneapi_raw: Optional[Dict[str, Any]]) -> None:
        _d: Dict[str, Any] = oneapi_raw or {}
        self.system_layer: Optional[str] = _d.get("system_layer")
        self.is_lower_horizon_only: bool = True  # always lower-horizon
        self.provider_id: Optional[str] = _d.get("provider_id")
        self.available: bool = bool(_d.get("available", False))
        self.raw: Dict[str, Any] = _d

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the flattened OneAPI summary."""
        return {
            "system_layer": self.system_layer,
            "is_lower_horizon_only": self.is_lower_horizon_only,
            "provider_id": self.provider_id,
            "available": self.available,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DesktopOneAPIHorizonSummary(system_layer={self.system_layer!r}, "
            f"available={self.available})"
        )


# ---------------------------------------------------------------------------
# DesktopProviderRoutingSummary — flattened routing/provider summary
# ---------------------------------------------------------------------------


class DesktopProviderRoutingSummary:
    """PR-9: Flattened provider routing summary for desktop clients.

    Exposes key routing fields from the nested ``model_routing_summary`` and
    ``provider_health_summary`` dicts without requiring consumers to navigate
    the raw structures.

    Attributes
    ----------
    selected_provider:
        The currently selected provider identifier (e.g. ``"openai"``).
    primary_model_id:
        The primary model node identifier from the route plan.
    vendor_source:
        Vendor/source string from the routing layer.
    routing_authority_source:
        The authority source that produced the routing decision
        (e.g. ``"TopologyRoutePlan"``).
    legacy_routing_fallback_active:
        ``True`` when legacy routing keys were used instead of the canonical
        route plan.  Consumers must surface this state clearly.
    route_reason:
        Human-readable routing reason string when available.
    provider_available:
        Whether the selected provider reports itself as available.
    raw_routing:
        Full ``model_routing_summary`` dict for advanced inspection.
    raw_health:
        Full ``provider_health_summary`` dict for advanced inspection.
    """

    def __init__(
        self,
        routing_raw: Optional[Dict[str, Any]],
        health_raw: Optional[Dict[str, Any]],
    ) -> None:
        _r: Dict[str, Any] = routing_raw or {}
        _h: Dict[str, Any] = health_raw or {}
        self.selected_provider: Optional[str] = _r.get("selected_provider")
        self.primary_model_id: Optional[str] = _r.get("primary_model_id")
        self.vendor_source: Optional[str] = _r.get("vendor_source")
        self.routing_authority_source: Optional[str] = _r.get(
            "routing_authority_source"
        )
        self.legacy_routing_fallback_active: bool = bool(
            _r.get("legacy_routing_fallback_active", False)
        )
        self.route_reason: Optional[str] = _r.get("route_reason")
        self.provider_available: bool = bool(
            _h.get("provider_available", _h.get("available", False))
        )
        self.raw_routing: Dict[str, Any] = _r
        self.raw_health: Dict[str, Any] = _h

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the flattened routing summary."""
        return {
            "selected_provider": self.selected_provider,
            "primary_model_id": self.primary_model_id,
            "vendor_source": self.vendor_source,
            "routing_authority_source": self.routing_authority_source,
            "legacy_routing_fallback_active": self.legacy_routing_fallback_active,
            "route_reason": self.route_reason,
            "provider_available": self.provider_available,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DesktopProviderRoutingSummary(selected_provider={self.selected_provider!r}, "
            f"legacy_fallback={self.legacy_routing_fallback_active})"
        )


# ---------------------------------------------------------------------------
# DesktopClientViewModel — main PR-9 view-model
# ---------------------------------------------------------------------------


class DesktopClientViewModel:
    """PR-9: Stable client-consumable view-model for the desktop status board.

    Produced by :func:`adapt_integration_payload` from a PR-8
    :class:`~contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload`.

    Desktop consumers should work with this view-model rather than the raw
    integrated payload.  The view-model:

    - Flattens the most important fields so no nested dict traversal is needed.
    - Exposes ``is_canonical``, ``is_degraded``, ``is_partial``, and
      ``is_unavailable`` as top-level bool properties.
    - Keeps ``topology_legacy_fallback_active`` and
      ``routing_legacy_fallback_active`` explicitly visible.
    - Exposes OneAPI as a distinct lower-horizon sub-summary
      (:class:`DesktopOneAPIHorizonSummary`); ``oneapi_is_lower_horizon_only``
      is always ``True``.
    - Provides ``provider_routing`` as a flattened
      :class:`DesktopProviderRoutingSummary`.
    - Never raises; all fields have safe defaults when the underlying payload
      is minimal or partially populated.

    Attributes
    ----------
    view_model_id:
        Unique identifier for this view-model instance.
    adapted_at:
        Unix epoch seconds when this view-model was assembled.
    readiness_state:
        :class:`DesktopReadinessState` for the current topology/routing state.
    is_canonical:
        ``True`` when the topology projection is fully authoritative.
    is_degraded:
        ``True`` when the legacy routing fallback is active.
    is_partial:
        ``True`` when canonical source is present but components are missing.
    is_unavailable:
        ``True`` when no topology data is available.
    topology_legacy_fallback_active:
        Explicit legacy fallback flag from the topology block.
    routing_legacy_fallback_active:
        Explicit legacy fallback flag from the routing block.
    topology_provider_id:
        Provider identifier from the topology projection, when available.
    topology_primary_model_id:
        Primary model identifier from the topology projection.
    topology_route_reason:
        Routing reason from the topology block.
    routing_authority_source:
        Routing authority source string from the routing summary.
    provider_routing:
        :class:`DesktopProviderRoutingSummary` — flat routing/provider info.
    oneapi_horizon:
        :class:`DesktopOneAPIHorizonSummary` — flat OneAPI lower-horizon info.
    oneapi_is_lower_horizon_only:
        Always ``True``.  OneAPI must never be promoted to a top-level peer.
    integration_health:
        Rolled-up integration health string (``"ok"`` / ``"degraded"`` /
        ``"advisory"`` / ``"critical"`` / ``"unknown"``).
    authority_indicators:
        Full authority indicators dict from the payload for advanced inspection.
    adapter_authority:
        Equals :data:`DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY`; confirms this
        view-model was produced by the PR-9 canonical adapter.
    """

    def __init__(
        self,
        *,
        view_model_id: str,
        adapted_at: float,
        readiness_state: DesktopReadinessState,
        is_canonical: bool,
        is_degraded: bool,
        is_partial: bool,
        is_unavailable: bool,
        topology_legacy_fallback_active: bool,
        routing_legacy_fallback_active: bool,
        topology_provider_id: Optional[str],
        topology_primary_model_id: Optional[str],
        topology_route_reason: Optional[str],
        routing_authority_source: Optional[str],
        provider_routing: DesktopProviderRoutingSummary,
        oneapi_horizon: DesktopOneAPIHorizonSummary,
        integration_health: str,
        authority_indicators: Dict[str, Any],
        adapter_authority: str,
    ) -> None:
        self.view_model_id = view_model_id
        self.adapted_at = adapted_at
        self.readiness_state = readiness_state
        self.is_canonical = is_canonical
        self.is_degraded = is_degraded
        self.is_partial = is_partial
        self.is_unavailable = is_unavailable
        self.topology_legacy_fallback_active = topology_legacy_fallback_active
        self.routing_legacy_fallback_active = routing_legacy_fallback_active
        self.topology_provider_id = topology_provider_id
        self.topology_primary_model_id = topology_primary_model_id
        self.topology_route_reason = topology_route_reason
        self.routing_authority_source = routing_authority_source
        self.provider_routing = provider_routing
        self.oneapi_horizon = oneapi_horizon
        self.oneapi_is_lower_horizon_only: bool = True  # always True
        self.integration_health = integration_health
        self.authority_indicators = authority_indicators
        self.adapter_authority = adapter_authority

    def readiness_label(self) -> str:
        """Return a short human-readable readiness label for display.

        Returns one of ``"Canonical"``, ``"Degraded (legacy fallback)"``,
        ``"Partial"``, ``"Unavailable"``, or ``"Unknown"``.
        """
        _map = {
            DesktopReadinessState.canonical: "Canonical",
            DesktopReadinessState.degraded: "Degraded (legacy fallback)",
            DesktopReadinessState.partial: "Partial",
            DesktopReadinessState.unavailable: "Unavailable",
            DesktopReadinessState.unknown: "Unknown",
        }
        return _map.get(self.readiness_state, "Unknown")

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation of this view-model."""
        return {
            "view_model_id": self.view_model_id,
            "adapted_at": self.adapted_at,
            "readiness_state": (
                self.readiness_state.value
                if hasattr(self.readiness_state, "value")
                else str(self.readiness_state)
            ),
            "is_canonical": self.is_canonical,
            "is_degraded": self.is_degraded,
            "is_partial": self.is_partial,
            "is_unavailable": self.is_unavailable,
            "topology_legacy_fallback_active": self.topology_legacy_fallback_active,
            "routing_legacy_fallback_active": self.routing_legacy_fallback_active,
            "topology_provider_id": self.topology_provider_id,
            "topology_primary_model_id": self.topology_primary_model_id,
            "topology_route_reason": self.topology_route_reason,
            "routing_authority_source": self.routing_authority_source,
            "provider_routing": self.provider_routing.to_dict(),
            "oneapi_horizon": self.oneapi_horizon.to_dict(),
            "oneapi_is_lower_horizon_only": self.oneapi_is_lower_horizon_only,
            "integration_health": self.integration_health,
            "authority_indicators": self.authority_indicators,
            "adapter_authority": self.adapter_authority,
        }

    def to_json(self, **kwargs: Any) -> str:
        """Return a JSON string representation of this view-model."""
        return json.dumps(self.to_dict(), **kwargs)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"DesktopClientViewModel("
            f"readiness_state={self.readiness_state!r}, "
            f"is_canonical={self.is_canonical}, "
            f"integration_health={self.integration_health!r})"
        )


# ---------------------------------------------------------------------------
# adapt_integration_payload — main adapter function
# ---------------------------------------------------------------------------

def _resolve_readiness_state(
    authority_indicators: Dict[str, Any],
    topology_projection: Any,
) -> DesktopReadinessState:
    """Derive a :class:`DesktopReadinessState` from authority indicators.

    Checks ``topology_readiness`` in ``authority_indicators`` first (PR-8
    composite dict), then falls back to inspecting
    ``topology_projection.projection_quality.readiness`` directly (PR-7
    semantics), then defaults to ``unknown``.
    """
    # Primary: use authority_indicators["topology_readiness"] from PR-8
    raw_readiness = authority_indicators.get("topology_readiness")
    if raw_readiness and isinstance(raw_readiness, str):
        try:
            return DesktopReadinessState(raw_readiness)
        except ValueError:
            pass

    # Fallback: read from topology_projection.projection_quality (PR-7)
    if topology_projection is not None:
        pq = getattr(topology_projection, "projection_quality", None)
        if pq is not None:
            pq_readiness = getattr(pq, "readiness", None)
            if pq_readiness is not None:
                raw = (
                    pq_readiness.value
                    if hasattr(pq_readiness, "value")
                    else str(pq_readiness)
                )
                try:
                    return DesktopReadinessState(raw)
                except ValueError:
                    pass

    return DesktopReadinessState.unknown


def adapt_integration_payload(payload: Any) -> "DesktopClientViewModel":
    """PR-9: Adapt a PR-8 integrated payload into a desktop client view-model.

    Converts a
    :class:`~contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload`
    into a :class:`DesktopClientViewModel` that desktop consumers can work
    with directly.

    The adapter:

    - Derives :class:`DesktopReadinessState` from the authority indicators and
      topology projection quality block (preserving PR-7/8 semantics).
    - Exposes ``is_canonical`` / ``is_degraded`` / ``is_partial`` /
      ``is_unavailable`` as top-level booleans.
    - Flattens topology, routing, and OneAPI fields for direct access.
    - Ensures ``oneapi_is_lower_horizon_only`` is always ``True``.
    - Never raises; returns a safe minimal view-model on any error.

    Parameters
    ----------
    payload:
        A
        :class:`~contracts.desktop_status_projection.DesktopStatusBoardIntegrationPayload`
        instance produced by
        :func:`~contracts.desktop_status_projection.build_desktop_status_board_integration_payload`
        or
        :func:`~core.projection.build_desktop_status_board_integration_from_runtime`.

    Returns
    -------
    DesktopClientViewModel
        A stable, flat, client-consumable view-model.  Never raises; degrades
        gracefully on any internal error.
    """
    try:
        authority_indicators: Dict[str, Any] = {}
        topology_projection = None
        model_routing_summary: Dict[str, Any] = {}
        provider_health_summary: Optional[Dict[str, Any]] = None
        oneapi_raw: Optional[Dict[str, Any]] = None
        integration_health_str = "unknown"

        if payload is not None:
            authority_indicators = dict(
                getattr(payload, "authority_indicators", {}) or {}
            )
            topology_projection = getattr(payload, "topology_projection", None)
            model_routing_summary = dict(
                getattr(payload, "model_routing_summary", {}) or {}
            )
            _ph = getattr(payload, "provider_health_summary", None)
            provider_health_summary = dict(_ph) if _ph else None
            _oa = getattr(payload, "oneapi_integration", None)
            if _oa is not None:
                if hasattr(_oa, "model_dump"):
                    oneapi_raw = _oa.model_dump()
                elif isinstance(_oa, dict):
                    oneapi_raw = _oa
                else:
                    oneapi_raw = {}
            _ih = getattr(payload, "integration_health", None)
            integration_health_str = (
                _ih.value if hasattr(_ih, "value") else str(_ih)
            ) if _ih is not None else "unknown"

            # PR-436/PR-8 shorthand properties: supplement authority_indicators
            # when the compact shorthand is present on the payload (introduced
            # in PR-8 final contract).  This covers both the full
            # DesktopStatusBoardIntegrationPayload model and any minimal dict-
            # or dataclass-based payload that exposes the same surface.
            if "topology_readiness" not in authority_indicators:
                _pr8_readiness = getattr(payload, "readiness", None)
                if _pr8_readiness is not None and isinstance(_pr8_readiness, str):
                    authority_indicators["topology_readiness"] = _pr8_readiness
            if "topology_authoritative" not in authority_indicators:
                _pr8_is_canonical = getattr(payload, "is_canonical", None)
                if isinstance(_pr8_is_canonical, bool):
                    authority_indicators["topology_authoritative"] = _pr8_is_canonical

        # --- Readiness state -----------------------------------------------
        readiness_state = _resolve_readiness_state(
            authority_indicators, topology_projection
        )

        # --- Boolean readiness flags ----------------------------------------
        is_canonical = readiness_state == DesktopReadinessState.canonical
        is_degraded = readiness_state == DesktopReadinessState.degraded
        is_partial = readiness_state == DesktopReadinessState.partial
        is_unavailable = readiness_state == DesktopReadinessState.unavailable

        # Cross-check: if authority_indicators["topology_authoritative"] is
        # explicitly False while readiness resolved to "canonical", the
        # authoritative flag takes precedence.  This can occur when the
        # topology_readiness string in authority_indicators is "canonical" but
        # the topology_authoritative boolean was set to False by the compiler
        # (e.g. provider availability check failed after readiness was
        # labelled).  We demote to "degraded" so consumers never see
        # is_canonical=True when the authority flag disagrees.
        auth_flag = authority_indicators.get("topology_authoritative")
        if isinstance(auth_flag, bool) and not auth_flag and is_canonical:
            # Payload says not authoritative despite readiness=="canonical" —
            # respect the authority flag to avoid misrepresenting fallback data.
            is_canonical = False
            is_degraded = True
            readiness_state = DesktopReadinessState.degraded

        # --- Legacy fallback flags ------------------------------------------
        topology_legacy_fallback_active: bool = bool(
            authority_indicators.get("topology_legacy_fallback_active", False)
        )
        routing_legacy_fallback_active: bool = bool(
            authority_indicators.get("model_routing_legacy_fallback_active", False)
        )

        # --- Topology fields ------------------------------------------------
        topology_provider_id: Optional[str] = None
        topology_primary_model_id: Optional[str] = None
        topology_route_reason: Optional[str] = None

        if topology_projection is not None:
            topology_provider_id = getattr(topology_projection, "provider_id", None)
            topology_primary_model_id = getattr(
                topology_projection, "primary_model_id", None
            )
            topology_route_reason = getattr(topology_projection, "route_reason", None)

        # Routing summary may also carry provider_id / primary_model_id
        if topology_provider_id is None:
            topology_provider_id = model_routing_summary.get("selected_provider")
        if topology_primary_model_id is None:
            topology_primary_model_id = model_routing_summary.get("primary_model_id")
        if topology_route_reason is None:
            topology_route_reason = model_routing_summary.get("route_reason")

        # --- Sub-summaries --------------------------------------------------
        provider_routing = DesktopProviderRoutingSummary(
            model_routing_summary, provider_health_summary
        )
        oneapi_horizon = DesktopOneAPIHorizonSummary(oneapi_raw)

        return DesktopClientViewModel(
            view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
            adapted_at=time.time(),
            readiness_state=readiness_state,
            is_canonical=is_canonical,
            is_degraded=is_degraded,
            is_partial=is_partial,
            is_unavailable=is_unavailable,
            topology_legacy_fallback_active=topology_legacy_fallback_active,
            routing_legacy_fallback_active=routing_legacy_fallback_active,
            topology_provider_id=topology_provider_id,
            topology_primary_model_id=topology_primary_model_id,
            topology_route_reason=topology_route_reason,
            routing_authority_source=model_routing_summary.get(
                "routing_authority_source"
            ),
            provider_routing=provider_routing,
            oneapi_horizon=oneapi_horizon,
            integration_health=integration_health_str,
            authority_indicators=authority_indicators,
            adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
        )

    except Exception as _err:
        _logger.warning(
            "adapt_integration_payload failed, returning minimal view-model: %s", _err
        )
        return DesktopClientViewModel(
            view_model_id=f"dcvm_{uuid.uuid4().hex[:12]}",
            adapted_at=time.time(),
            readiness_state=DesktopReadinessState.unknown,
            is_canonical=False,
            is_degraded=False,
            is_partial=False,
            is_unavailable=False,
            topology_legacy_fallback_active=False,
            routing_legacy_fallback_active=False,
            topology_provider_id=None,
            topology_primary_model_id=None,
            topology_route_reason=None,
            routing_authority_source=None,
            provider_routing=DesktopProviderRoutingSummary(None, None),
            oneapi_horizon=DesktopOneAPIHorizonSummary(None),
            integration_health="unknown",
            authority_indicators={},
            adapter_authority=DESKTOP_CONSUMPTION_ADAPTER_AUTHORITY,
        )
