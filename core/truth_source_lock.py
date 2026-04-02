#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/truth_source_lock.py
==========================
PR-B — Internal Contract / Truth / Policy Closure

Locks the **canonical device truth source** for the Galaxy runtime.
This module is the single, authoritative governance record that answers:

  * Which authority writes device truth? (SSOT)
  * Which model is the canonical single-device read contract?
  * Which projection is the canonical multi-device read contract?
  * Which models are write-only, read-only, or adapter-only?

Design invariants
-----------------
1.  **Device write SSOT** — ``UnifiedDeviceManager`` (UDM) is the only
    authoritative writer for device truth (registered, online, capabilities,
    device_id, platform).

2.  **Canonical single-device read contract** — External and downstream
    callers use :class:`contracts.registered_runtime_device.RegisteredRuntimeDevice`
    (or the equivalent canonical read projection) as the stable public
    read interface for a single device.

3.  **Canonical multi-device read projection** — Multi-device queries
    use the ``truth_integration_layer.resolve_all_device_truth()`` / the
    canonical device projection endpoint.  They must NOT fan-out to
    individual raw UDM/UCM internals directly.

4.  **Compat cache is read-only / adapter-only** — ``registered_devices``
    (``core.routes._shared``) is demoted to a compat cache.  It is NOT an
    authoritative truth source and must not be written to as a primary store.

5.  **Participation cannot override truth** — Device participation
    (``core.device_participation``) is enrichment-only and must not set
    ``registered``, ``online``, or ``routable`` independently of Layer-1
    canonical readiness.

Authority sentinels
-------------------
``TRUTH_SOURCE_LOCK_AUTHORITY``
    Identifies this module as the PR-B truth source lock authority.

``TRUTH_SOURCE_LOCK_LAYER_POSITION``
    Architectural layer index.  Sits adjacent to layer 0 (contract definition).

``DEVICE_WRITE_SSOT``
    The canonical device WRITE authority (UnifiedDeviceManager).

``CANONICAL_SINGLE_DEVICE_READ_CONTRACT``
    The canonical single-device external READ model.

``CANONICAL_MULTI_DEVICE_READ_PROJECTION``
    The canonical multi-device READ projection function.

``COMPAT_CACHE_READ_ONLY``
    Affirms that the registered_devices compat cache is READ-ONLY.

Public API
----------
Sentinels:
    TRUTH_SOURCE_LOCK_AUTHORITY
    TRUTH_SOURCE_LOCK_LAYER_POSITION
    DEVICE_WRITE_SSOT
    CANONICAL_SINGLE_DEVICE_READ_CONTRACT
    CANONICAL_MULTI_DEVICE_READ_PROJECTION
    COMPAT_CACHE_READ_ONLY
    MODEL_CLASSIFICATION

Helpers:
    get_write_ssot() -> str
    get_single_device_read_contract() -> str
    get_multi_device_read_projection() -> str
    classify_model_role(model_name) -> str
    describe_truth_source_lock() -> dict
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.TruthSourceLock")

__all__ = [
    # Sentinels
    "TRUTH_SOURCE_LOCK_AUTHORITY",
    "TRUTH_SOURCE_LOCK_LAYER_POSITION",
    "DEVICE_WRITE_SSOT",
    "CANONICAL_SINGLE_DEVICE_READ_CONTRACT",
    "CANONICAL_MULTI_DEVICE_READ_PROJECTION",
    "COMPAT_CACHE_READ_ONLY",
    "MODEL_CLASSIFICATION",
    # Helpers
    "get_write_ssot",
    "get_single_device_read_contract",
    "get_multi_device_read_projection",
    "classify_model_role",
    "describe_truth_source_lock",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Identifies this module as the PR-B truth source lock authority.
TRUTH_SOURCE_LOCK_AUTHORITY: str = "TRUTH_SOURCE_LOCK_V1"

#: Layer position — sits at layer 0 alongside contract_closure.
TRUTH_SOURCE_LOCK_LAYER_POSITION: int = 0

# ---------------------------------------------------------------------------
# Write SSOT
# ---------------------------------------------------------------------------

#: The canonical device WRITE authority.
#: Only ``UnifiedDeviceManager`` (UDM) may write device truth
#: (registered, online, capabilities, device_id, platform).
#: All other writers are demoted to adapters or compat paths.
DEVICE_WRITE_SSOT: str = "core.unified.device_manager.UnifiedDeviceManager"

# ---------------------------------------------------------------------------
# Read contracts
# ---------------------------------------------------------------------------

#: Canonical single-device external READ contract.
#: Downstream and external consumers MUST read individual device state
#: through this model (or its functional equivalent).
CANONICAL_SINGLE_DEVICE_READ_CONTRACT: str = (
    "contracts.registered_runtime_device.RegisteredRuntimeDevice"
)

#: Canonical multi-device READ projection.
#: Multi-device queries use this function to enumerate device truth.
#: Direct fan-out to internal UDM/UCM data structures is prohibited.
CANONICAL_MULTI_DEVICE_READ_PROJECTION: str = (
    "core.truth_integration_layer.resolve_all_device_truth"
)

# ---------------------------------------------------------------------------
# Compat cache governance
# ---------------------------------------------------------------------------

#: Affirms that ``registered_devices`` (core.routes._shared) is a
#: read-only compat cache.  It must NOT be written to as a primary truth
#: source.  Canonical readiness reads from UDM/UCM only.
COMPAT_CACHE_READ_ONLY: bool = True

# ---------------------------------------------------------------------------
# Model classification
# ---------------------------------------------------------------------------

#: Role classification for each device-related model in the codebase.
#:
#: Roles:
#: * ``"write"``   — canonical writer; only UDM is write authority.
#: * ``"read"``    — canonical read projection / external read contract.
#: * ``"adapter"`` — adapter/normalizer input only; must not persist.
#: * ``"compat"``  — legacy compat cache; read-only, downstream only.
#: * ``"enrich"``  — enrichment layer; must not override canonical truth.
MODEL_CLASSIFICATION: Dict[str, Dict[str, str]] = {
    "UnifiedDeviceManager": {
        "role": "write",
        "module": "core.unified.device_manager",
        "description": (
            "Canonical WRITE SSOT for device truth. The only authoritative "
            "writer for registered/online/capabilities/device_id/platform."
        ),
    },
    "UnifiedConnectionManager": {
        "role": "read",
        "module": "core.unified.connection_manager",
        "description": (
            "Canonical READ authority for connection/presence truth "
            "(UCM). Read-only from downstream; writes are internal UCM events."
        ),
    },
    "RegisteredRuntimeDevice": {
        "role": "read",
        "module": "contracts.registered_runtime_device",
        "description": (
            "Canonical single-device external READ contract. "
            "The stable public read interface for a single device."
        ),
    },
    "CanonicalDeviceTruth": {
        "role": "read",
        "module": "core.truth_integration_layer",
        "description": (
            "Canonical multi-device read projection. "
            "Fused UCM + UDM truth with explicit conflict-resolution policy."
        ),
    },
    "DeviceReadinessSummary": {
        "role": "read",
        "module": "core.device_readiness",
        "description": (
            "Canonical Layer-1 readiness read projection "
            "(registered/online/connected/routable). Read-only for consumers."
        ),
    },
    "ParticipationSummary": {
        "role": "enrich",
        "module": "core.device_participation",
        "description": (
            "Layer-2 participation enrichment. Adds role/session/mesh context. "
            "Must NOT override registered/online/routable from Layer-1."
        ),
    },
    "TaskDispatchModel": {
        "role": "adapter",
        "module": "core.schemas.contracts",
        "description": (
            "Legacy public-API input model. Adapter-only — must be normalized "
            "to TaskEnvelope before entering the internal canonical boundary."
        ),
    },
    "TaskResultModel": {
        "role": "adapter",
        "module": "core.schemas.contracts",
        "description": (
            "Legacy public-API result model. Adapter-only — must be normalized "
            "to ResultEnvelope before entering the internal canonical boundary."
        ),
    },
    "registered_devices": {
        "role": "compat",
        "module": "core.routes._shared",
        "description": (
            "Legacy compat cache. READ-ONLY from downstream. "
            "Not an authoritative truth source; not written as primary store."
        ),
    },
    "UnifiedDevice": {
        "role": "write",
        "module": "core.unified.models",
        "description": (
            "Internal UDM device record. Written exclusively by "
            "UnifiedDeviceManager. Read via canonical projection endpoints."
        ),
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_write_ssot() -> str:
    """Return the canonical device WRITE SSOT module path.

    Returns
    -------
    str
        Module path of the canonical write authority.
    """
    return DEVICE_WRITE_SSOT


def get_single_device_read_contract() -> str:
    """Return the canonical single-device external READ contract path.

    Returns
    -------
    str
        Module path of the canonical single-device read model.
    """
    return CANONICAL_SINGLE_DEVICE_READ_CONTRACT


def get_multi_device_read_projection() -> str:
    """Return the canonical multi-device READ projection function path.

    Returns
    -------
    str
        Module path + function name for the multi-device read projection.
    """
    return CANONICAL_MULTI_DEVICE_READ_PROJECTION


def classify_model_role(model_name: str) -> str:
    """Return the canonical role for a device-related model name.

    Parameters
    ----------
    model_name:
        Short class name (e.g. ``"RegisteredRuntimeDevice"``) or full module
        path (e.g. ``"contracts.registered_runtime_device.RegisteredRuntimeDevice"``).

    Returns
    -------
    str
        One of ``"write"``, ``"read"``, ``"adapter"``, ``"compat"``,
        ``"enrich"``, or ``"unknown"`` when not in the registry.
    """
    # Try short name first
    if model_name in MODEL_CLASSIFICATION:
        return MODEL_CLASSIFICATION[model_name]["role"]
    # Try matching on the last component of a fully-qualified name
    short = model_name.split(".")[-1]
    if short in MODEL_CLASSIFICATION:
        return MODEL_CLASSIFICATION[short]["role"]
    logger.debug(
        "TruthSourceLock: unknown model %r; returning 'unknown'", model_name
    )
    return "unknown"


def describe_truth_source_lock() -> Dict[str, Any]:
    """Return a JSON-safe dict summarising the PR-B truth source lock.

    Intended for operator tooling, observability dashboards, and runtime
    diagnostics.

    Returns
    -------
    dict
    """
    return {
        "authority": TRUTH_SOURCE_LOCK_AUTHORITY,
        "layer_position": TRUTH_SOURCE_LOCK_LAYER_POSITION,
        "device_write_ssot": DEVICE_WRITE_SSOT,
        "canonical_single_device_read_contract": CANONICAL_SINGLE_DEVICE_READ_CONTRACT,
        "canonical_multi_device_read_projection": CANONICAL_MULTI_DEVICE_READ_PROJECTION,
        "compat_cache_read_only": COMPAT_CACHE_READ_ONLY,
        "model_roles": {
            name: entry["role"] for name, entry in MODEL_CLASSIFICATION.items()
        },
        "invariants": [
            "UnifiedDeviceManager is the ONLY authoritative device writer",
            "External callers read device state via RegisteredRuntimeDevice only",
            "Multi-device queries use resolve_all_device_truth projection",
            "registered_devices compat cache is READ-ONLY (not a truth source)",
            "ParticipationSummary must not override registered/online/routable",
            "TaskDispatchModel and TaskResultModel are adapter-only (edge boundary)",
        ],
    }
