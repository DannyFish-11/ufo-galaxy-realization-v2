#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/contract_closure.py
=========================
PR-B — Internal Contract / Truth / Policy Closure

Declares the **canonical internal contract authority** for the Galaxy runtime.
This module is the single, authoritative governance record that answers:

  * Which envelope is the internal dispatch contract?
  * Which envelope is the internal result contract?
  * How do public API, edge-adapter, and internal-canonical boundaries differ?
  * Which adapters/normalizers bridge legacy payloads into the canonical path?

Governance boundaries
---------------------
``PUBLIC_API_BOUNDARY``
    External callers (REST, WebSocket, mobile client, NATS external) interact
    via **public API contracts**.  These include raw JSON payloads, legacy
    request/response models (``TaskDispatchModel``, ``TaskResultModel``), and
    proto-serialised messages.  They are NOT the internal canonical contract.

``EDGE_ADAPTER_BOUNDARY``
    ACL / gateway / normalization layers convert public-API or legacy inputs
    into the canonical shape before they enter the internal routing path.
    Adapters at this boundary include:
      - ``core.acl.AntiCorruptionLayer``
      - ``core.message_interop.normalize_to_task_envelope``
      - ``core.execution_spine.normalize_ingress_to_envelope``
      - ``core.task_adapter.TaskAdapterLayer``

``INTERNAL_CANONICAL_BOUNDARY``
    Everything **inside** the execution spine operates exclusively on the
    canonical contracts.  No legacy model may cross this boundary without
    prior normalization.

Internal canonical contracts
----------------------------
``INTERNAL_DISPATCH_CONTRACT``
    :class:`core.schemas.task_envelope.TaskEnvelope`
    The single, authoritative internal task-routing/dispatch message.
    All gateway command dispatch, device-to-device relay, node execution,
    MCP tool calls, and skill invocations use this shape.

``INTERNAL_RESULT_CONTRACT``
    :class:`core.unified.command_envelope.ResultEnvelope`
    The canonical executor-return shape, correlated back via ``task_id`` +
    ``trace_id``.  Every execution result path MUST produce this model before
    feeding results back into the orchestration or projection layers.

Authority sentinels
-------------------
``INTERNAL_CONTRACT_CLOSURE_AUTHORITY``
    Stable string token identifying this module as the PR-B contract authority.

``CONTRACT_CLOSURE_LAYER_POSITION``
    Architectural layer index.  This module governs at layer 0 (contract
    definition), above all runtime layers.

``CONTRACT_CLOSURE_VERSION``
    Contract version string — lets downstream consumers detect schema changes.

Public API
----------
Sentinels:
    INTERNAL_CONTRACT_CLOSURE_AUTHORITY
    CONTRACT_CLOSURE_LAYER_POSITION
    CONTRACT_CLOSURE_VERSION
    INTERNAL_DISPATCH_CONTRACT
    INTERNAL_RESULT_CONTRACT
    PUBLIC_API_BOUNDARY
    EDGE_ADAPTER_BOUNDARY
    INTERNAL_CANONICAL_BOUNDARY
    CANONICAL_ADAPTER_REGISTRY

Helpers:
    is_canonical_dispatch_contract(obj) -> bool
    is_canonical_result_contract(obj) -> bool
    get_contract_boundary(layer_hint) -> str
    describe_contract_closure() -> dict
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("Galaxy.ContractClosure")

__all__ = [
    # Sentinels
    "INTERNAL_CONTRACT_CLOSURE_AUTHORITY",
    "CONTRACT_CLOSURE_LAYER_POSITION",
    "CONTRACT_CLOSURE_VERSION",
    "INTERNAL_DISPATCH_CONTRACT",
    "INTERNAL_RESULT_CONTRACT",
    "PUBLIC_API_BOUNDARY",
    "EDGE_ADAPTER_BOUNDARY",
    "INTERNAL_CANONICAL_BOUNDARY",
    "CANONICAL_ADAPTER_REGISTRY",
    # Helpers
    "is_canonical_dispatch_contract",
    "is_canonical_result_contract",
    "get_contract_boundary",
    "describe_contract_closure",
]

# ---------------------------------------------------------------------------
# Authority sentinels
# ---------------------------------------------------------------------------

#: Identifies this module as the PR-B canonical contract closure authority.
INTERNAL_CONTRACT_CLOSURE_AUTHORITY: str = "INTERNAL_CONTRACT_CLOSURE_V1"

#: Layer 0 — contract definition, above all runtime layers.
CONTRACT_CLOSURE_LAYER_POSITION: int = 0

#: Version of the contract closure specification.
CONTRACT_CLOSURE_VERSION: str = "CONTRACT_CLOSURE_V1"

# ---------------------------------------------------------------------------
# Canonical contract declarations
# ---------------------------------------------------------------------------

#: Internal dispatch contract.
#: TaskEnvelope is the ONLY valid internal task routing/dispatch message.
#: Canonical class: ``core.schemas.task_envelope.TaskEnvelope``
INTERNAL_DISPATCH_CONTRACT: str = "core.schemas.task_envelope.TaskEnvelope"

#: Internal result contract.
#: ResultEnvelope is the ONLY valid executor-return message inside the system.
#: Canonical class: ``core.unified.command_envelope.ResultEnvelope``
INTERNAL_RESULT_CONTRACT: str = "core.unified.command_envelope.ResultEnvelope"

# ---------------------------------------------------------------------------
# Boundary declarations
# ---------------------------------------------------------------------------

#: External-facing contract boundary.
#: Raw JSON payloads, legacy request/response models, proto messages,
#: and mobile/REST client shapes reside here.  They must NOT enter the
#: internal routing path without normalization.
PUBLIC_API_BOUNDARY: str = "PUBLIC_API_BOUNDARY"

#: Edge/adapter boundary.
#: ACL, gateway, and normalization layers that convert public-API inputs
#: into canonical contracts.  This is the ONLY place where legacy models
#: may coexist with canonical ones.
EDGE_ADAPTER_BOUNDARY: str = "EDGE_ADAPTER_BOUNDARY"

#: Internal canonical boundary.
#: Everything inside the execution spine uses ONLY canonical contracts.
#: TaskEnvelope for dispatch, ResultEnvelope for results.
INTERNAL_CANONICAL_BOUNDARY: str = "INTERNAL_CANONICAL_BOUNDARY"

# ---------------------------------------------------------------------------
# Canonical adapter registry
# ---------------------------------------------------------------------------

#: Registry of canonical adapters that bridge legacy/public inputs to the
#: internal canonical boundary.  Each entry maps a human-readable adapter name
#: to its module path and the canonical contract it produces.
CANONICAL_ADAPTER_REGISTRY: Dict[str, Dict[str, str]] = {
    "AntiCorruptionLayer": {
        "module": "core.acl",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Validates and normalises LLM output, worker results, and MCP "
            "tool results into typed contract models before crossing into the "
            "canonical internal boundary."
        ),
    },
    "normalize_to_task_envelope": {
        "module": "core.message_interop",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Converts heterogeneous payloads (legacy dicts, bridge frames, "
            "NATS dispatches, scheduler args) into TaskEnvelope."
        ),
    },
    "normalize_ingress_to_envelope": {
        "module": "core.execution_spine",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Execution spine ingress normalizer — maps any ingress source "
            "(scheduler, bridge, NATS, relay, mesh) to TaskEnvelope before "
            "entering the canonical routing path."
        ),
    },
    "TaskAdapterLayer": {
        "module": "core.task_adapter",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "PR-A canonical task adapter — normalises legacy dispatch "
            "models into CanonicalTask / TaskEnvelope shape."
        ),
    },
    "normalize_to_result_envelope": {
        "module": "core.message_interop",
        "produces": INTERNAL_RESULT_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Converts raw device results, NATS results, and bridge responses "
            "into ResultEnvelope."
        ),
    },
    "envelope_from_command_request": {
        "module": "core.schemas.task_envelope",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Adapter helper — builds TaskEnvelope from legacy "
            "CommandDispatchRequest / UnifiedCommandRequest."
        ),
    },
    "envelope_from_relay_request": {
        "module": "core.schemas.task_envelope",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Adapter helper — builds TaskEnvelope from a ProxyRelay "
            "RelayRequest."
        ),
    },
    "envelope_from_mcp_call": {
        "module": "core.schemas.task_envelope",
        "produces": INTERNAL_DISPATCH_CONTRACT,
        "boundary": EDGE_ADAPTER_BOUNDARY,
        "description": (
            "Adapter helper — builds TaskEnvelope from an MCP tool-call "
            "request."
        ),
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DISPATCH_CLASS_NAMES: frozenset[str] = frozenset(
    {
        "TaskEnvelope",
        "core.schemas.task_envelope.TaskEnvelope",
    }
)

_RESULT_CLASS_NAMES: frozenset[str] = frozenset(
    {
        "ResultEnvelope",
        "core.unified.command_envelope.ResultEnvelope",
    }
)


def is_canonical_dispatch_contract(obj: Any) -> bool:
    """Return ``True`` when *obj* is a canonical internal dispatch contract.

    Accepts either a class type or an instance.  Checks by class name so
    that the check remains import-safe (avoids circular imports from
    ``core.schemas.task_envelope``).

    Parameters
    ----------
    obj:
        A class type or instance to check.

    Returns
    -------
    bool
    """
    cls = obj if isinstance(obj, type) else type(obj)
    qname = f"{cls.__module__}.{cls.__qualname__}"
    return cls.__name__ in _DISPATCH_CLASS_NAMES or qname in _DISPATCH_CLASS_NAMES


def is_canonical_result_contract(obj: Any) -> bool:
    """Return ``True`` when *obj* is a canonical internal result contract.

    Parameters
    ----------
    obj:
        A class type or instance to check.

    Returns
    -------
    bool
    """
    cls = obj if isinstance(obj, type) else type(obj)
    qname = f"{cls.__module__}.{cls.__qualname__}"
    return cls.__name__ in _RESULT_CLASS_NAMES or qname in _RESULT_CLASS_NAMES


def get_contract_boundary(layer_hint: Optional[str]) -> str:
    """Return the canonical boundary string for a given layer hint.

    Accepts common keywords (``"public"``, ``"edge"``, ``"internal"``) as
    well as the full sentinel strings.  Defaults to
    :data:`INTERNAL_CANONICAL_BOUNDARY` when the hint is unrecognised.

    Parameters
    ----------
    layer_hint:
        A boundary hint string (case-insensitive).

    Returns
    -------
    str
        One of :data:`PUBLIC_API_BOUNDARY`, :data:`EDGE_ADAPTER_BOUNDARY`,
        or :data:`INTERNAL_CANONICAL_BOUNDARY`.
    """
    if not layer_hint:
        return INTERNAL_CANONICAL_BOUNDARY
    hint = str(layer_hint).lower()
    if "public" in hint or "api" in hint or "external" in hint:
        return PUBLIC_API_BOUNDARY
    if "edge" in hint or "adapter" in hint or "acl" in hint or "gateway" in hint:
        return EDGE_ADAPTER_BOUNDARY
    return INTERNAL_CANONICAL_BOUNDARY


def describe_contract_closure() -> Dict[str, Any]:
    """Return a JSON-safe dict summarising the PR-B contract closure.

    Intended for operator tooling, observability dashboards, and runtime
    diagnostics.

    Returns
    -------
    dict
    """
    return {
        "authority": INTERNAL_CONTRACT_CLOSURE_AUTHORITY,
        "version": CONTRACT_CLOSURE_VERSION,
        "layer_position": CONTRACT_CLOSURE_LAYER_POSITION,
        "contracts": {
            "internal_dispatch_contract": INTERNAL_DISPATCH_CONTRACT,
            "internal_result_contract": INTERNAL_RESULT_CONTRACT,
        },
        "boundaries": {
            "public_api": PUBLIC_API_BOUNDARY,
            "edge_adapter": EDGE_ADAPTER_BOUNDARY,
            "internal_canonical": INTERNAL_CANONICAL_BOUNDARY,
        },
        "canonical_adapters": list(CANONICAL_ADAPTER_REGISTRY.keys()),
        "invariants": [
            "TaskEnvelope is the ONLY valid internal dispatch contract",
            "ResultEnvelope is the ONLY valid internal result contract",
            "Legacy models must be normalized at the EDGE_ADAPTER boundary",
            "Adapters may coexist with canonical contracts only at EDGE boundary",
            "INTERNAL_CANONICAL_BOUNDARY code must only consume TaskEnvelope/ResultEnvelope",
        ],
    }
