"""galaxy_gateway/routing/router.py — Thin routing orchestration entry-point.

This module exposes ``RoutingOrchestrator``, a lightweight class that wires
together the concern-separated routing sub-modules:

- :mod:`galaxy_gateway.routing.policy` — command analysis
- :mod:`galaxy_gateway.routing.device_selection` — device eligibility
- :mod:`galaxy_gateway.routing.health_policy` — health / availability gating
- :mod:`galaxy_gateway.routing.dispatch` — dispatch mechanics

``DeviceRouter`` in ``galaxy_gateway/device_router.py`` remains the single
canonical dispatch entry for the gateway and delegates to this orchestrator
for its core routing logic.  External callers that depend on ``DeviceRouter``
are unaffected.

Usage::

    from galaxy_gateway.routing.router import RoutingOrchestrator

    orchestrator = RoutingOrchestrator()
    analysis = orchestrator.analyze("打开手机相册", context)
    devices = orchestrator.select(analysis, get_devices_by_type_fn)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

from galaxy_gateway.routing.policy import analyze_command, ROUTING_POLICY_AUTHORITY
from galaxy_gateway.routing.device_selection import select_devices, DEVICE_SELECTION_AUTHORITY
from galaxy_gateway.routing.health_policy import (
    filter_eligible_devices,
    is_device_available,
    is_device_online,
    DEVICE_HEALTH_POLICY_AUTHORITY,
)
from galaxy_gateway.routing.dispatch import (
    build_aip_message,
    dispatch_to_websocket,
    DISPATCH_AUTHORITY,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Authority sentinel
# ---------------------------------------------------------------------------

ROUTING_ORCHESTRATION_AUTHORITY = "galaxy_gateway.routing.router.RoutingOrchestrator"
"""Sentinel string identifying this module as the routing-orchestration layer."""


# ---------------------------------------------------------------------------
# RoutingOrchestrator
# ---------------------------------------------------------------------------


class RoutingOrchestrator:
    """Thin orchestrator that wires together the routing concern sub-modules.

    This class does not hold device session state; that remains in
    ``DeviceRouter``.  It provides a cohesive API so that ``DeviceRouter``
    can delegate each step to the appropriate specialised module instead of
    mixing all logic in a single monolithic class.

    Sub-module authorities consumed
    --------------------------------
    - ``ROUTING_POLICY_AUTHORITY``     — command analysis
    - ``DEVICE_SELECTION_AUTHORITY``   — device selection
    - ``DEVICE_HEALTH_POLICY_AUTHORITY`` — health gating
    - ``DISPATCH_AUTHORITY``           — send/wait mechanics
    """

    # Expose sub-module authorities as class-level constants for introspection.
    POLICY_AUTHORITY = ROUTING_POLICY_AUTHORITY
    SELECTION_AUTHORITY = DEVICE_SELECTION_AUTHORITY
    HEALTH_AUTHORITY = DEVICE_HEALTH_POLICY_AUTHORITY
    DISPATCH_AUTHORITY = DISPATCH_AUTHORITY

    # ------------------------------------------------------------------
    # Policy step
    # ------------------------------------------------------------------

    def analyze(
        self,
        command: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Analyse *command* and return the routing-policy analysis dict.

        Delegates to :func:`galaxy_gateway.routing.policy.analyze_command`.
        """
        return analyze_command(command, context)

    # ------------------------------------------------------------------
    # Selection step
    # ------------------------------------------------------------------

    def select(
        self,
        analysis: Dict[str, Any],
        candidates: List[Any],
    ) -> List[Any]:
        """Select the best device(s) from *candidates* for *analysis*.

        Delegates to
        :func:`galaxy_gateway.routing.device_selection.select_devices`.
        """
        return select_devices(analysis, candidates)

    # ------------------------------------------------------------------
    # Health gating helpers
    # ------------------------------------------------------------------

    def filter_eligible(self, devices: List[Any]) -> List[Any]:
        """Return *devices* that pass the online health gate."""
        return filter_eligible_devices(devices)

    def is_available(self, device: Any) -> bool:
        """Return ``True`` when *device* has an active transport session."""
        return is_device_available(device)

    def is_online(self, device: Any) -> bool:
        """Return ``True`` when *device*'s status is ``"online"``."""
        return is_device_online(device)

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    def build_message(
        self,
        device_id: str,
        task_id: str,
        trace_id: str,
        command: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build an AIP v3 command envelope for WebSocket dispatch."""
        return build_aip_message(
            device_id=device_id,
            task_id=task_id,
            trace_id=trace_id,
            command=command,
            payload=payload,
        )

    async def send(
        self,
        device: Any,
        message: Dict[str, Any],
        task_id: str,
        task_events: Dict[str, Any],
        task_results: Dict[str, Dict],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Send *message* via *device*'s WebSocket and await the result."""
        return await dispatch_to_websocket(
            device=device,
            message=message,
            task_id=task_id,
            task_events=task_events,
            task_results=task_results,
            timeout=timeout,
        )
