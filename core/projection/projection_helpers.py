"""
core/projection/projection_helpers.py
======================================
Reusable projection helper functions — PR-3.

These helpers extract canonical routing / provider / OneAPI semantics from
structured input dicts so that the projection layer can consume them without
coupling to dashboard UI or legacy routing helpers.

Design
------
- All functions are pure helpers (no global state, no side effects).
- All functions degrade gracefully: they accept ``None`` / incomplete inputs
  and return ``None`` or an empty default rather than raising.
- No dashboard imports; no UI-layer dependencies.

Exported functions
------------------
extract_oneapi_source_from_route_plan(route_plan_dict)
    Detect whether a serialised ``TopologyRoutePlan`` dict routes through
    OneAPI (``vendor_source == "oneapi"`` on the primary node) and, if so,
    return the canonical OneAPI integration position summary.

extract_provider_status_summary(model_supply_dict)
    Build a compact provider health/availability summary from a serialised
    canonical model supply state dict.

build_oneapi_projection_summary()
    Return the canonical OneAPI system-level integration position summary
    as a plain dict (safe for embedding in projections and API responses).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.Projection.ProjectionHelpers")

__all__ = [
    "extract_oneapi_source_from_route_plan",
    "extract_provider_status_summary",
    "build_oneapi_projection_summary",
]


# ---------------------------------------------------------------------------
# build_oneapi_projection_summary
# ---------------------------------------------------------------------------


def build_oneapi_projection_summary() -> Optional[Dict[str, Any]]:
    """Return the canonical OneAPI system-level integration position summary.

    Delegates to :func:`core.oneapi_system_position.build_oneapi_integration_summary`.
    Returns a plain dict on success; ``None`` if the module is unavailable.

    This function is cheap to call (no I/O, no config reads).  It is safe
    to call from projection compilers, projection API endpoints, and
    diagnostic surfaces without any runtime dependency concerns.

    Returns
    -------
    dict or None
        Keys: ``system_layer``, ``node_path``, ``provider_category_value``,
        ``registered_dimensions``, ``routing_authority_ref``.
    """
    try:
        from core.oneapi_system_position import build_oneapi_integration_summary
        return build_oneapi_integration_summary().to_dict()
    except Exception as exc:
        logger.debug("build_oneapi_projection_summary: unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# extract_oneapi_source_from_route_plan
# ---------------------------------------------------------------------------


def extract_oneapi_source_from_route_plan(
    route_plan_dict: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Detect OneAPI participation in a serialised ``TopologyRoutePlan`` dict.

    Inspects the ``primary_model`` node in *route_plan_dict*.  If its
    ``vendor_source`` is ``"oneapi"``, returns the canonical OneAPI
    integration summary via :func:`build_oneapi_projection_summary`.

    Also inspects ``support_models`` — if *any* support node has
    ``vendor_source == "oneapi"`` the summary is returned.

    Parameters
    ----------
    route_plan_dict:
        Serialised ``TopologyRoutePlan.to_dict()`` output.  ``None`` or an
        empty dict causes an immediate ``None`` return.

    Returns
    -------
    dict or None
        Canonical OneAPI summary dict if OneAPI participates in the plan;
        ``None`` otherwise.
    """
    if not isinstance(route_plan_dict, dict):
        return None

    _ONEAPI_VALUE = "oneapi"

    # Check primary model node.
    primary = route_plan_dict.get("primary_model")
    if isinstance(primary, dict):
        if primary.get("vendor_source") == _ONEAPI_VALUE:
            return build_oneapi_projection_summary()

    # Check any support model node.
    support_nodes = route_plan_dict.get("support_models")
    if isinstance(support_nodes, list):
        for node in support_nodes:
            if isinstance(node, dict) and node.get("vendor_source") == _ONEAPI_VALUE:
                return build_oneapi_projection_summary()

    return None


# ---------------------------------------------------------------------------
# extract_provider_status_summary
# ---------------------------------------------------------------------------


def extract_provider_status_summary(
    model_supply_dict: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Build a compact provider health/availability summary.

    Parses the ``providers`` list from a serialised canonical model supply
    state dict and returns a structured summary with total/available/
    degraded/unavailable counts and per-provider health records.

    Parameters
    ----------
    model_supply_dict:
        Serialised canonical model supply state dict (e.g.
        ``ucp["canonical_model_supply"]``).  ``None`` or an empty dict
        causes an immediate ``None`` return.

    Returns
    -------
    dict or None
        ``{"total": int, "available": int, "degraded": int,
        "unavailable": int, "providers": [{"provider_id": str,
        "health_status": str}]}``
        or ``None`` when no valid input is available.
    """
    if not isinstance(model_supply_dict, dict):
        return None

    provider_records: List[Dict[str, Any]] = model_supply_dict.get("providers") or []
    if not isinstance(provider_records, list):
        return None
    if not provider_records:
        return None

    total = len(provider_records)
    available = 0
    degraded = 0
    unavailable = 0
    per_provider: List[Dict[str, str]] = []

    for rec in provider_records:
        if not isinstance(rec, dict):
            continue
        pid = str(rec.get("provider_id") or "unknown")
        # Normalise to lowercase for consistent comparison; canonical model
        # supply state should always use lowercase values but this handles
        # any mixed-case values from legacy or external sources.
        health = str(rec.get("health_status") or "unknown").lower()
        per_provider.append({"provider_id": pid, "health_status": health})
        if health in ("unavailable", "error"):
            unavailable += 1
        elif health == "degraded":
            degraded += 1
        else:
            available += 1

    return {
        "total": total,
        "available": available,
        "degraded": degraded,
        "unavailable": unavailable,
        "providers": per_provider,
    }
