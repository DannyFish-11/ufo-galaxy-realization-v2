#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.orchestration_authority.authority_resolver
================================================

PR-9 (V3) — Orchestration Authority Consolidation

Provides a **resolver** that classifies arbitrary module/path strings into
:class:`~.authority_roles.AuthorityRole` values and can produce a
machine-readable catalog of the complete authority topology.

The resolver is intentionally *read-only* and *additive*: it never modifies
any existing module and never introduces a new orchestration layer.

Key capabilities
----------------
* :func:`classify_module` — classify a dotted module path into an
  :class:`~.authority_roles.AuthorityRole`.
* :func:`authority_catalog` — return a serialisable dict describing the
  complete authority topology (suitable for API responses, docs generation,
  or observability dashboards).
* :func:`authority_chain` — return the ordered entry-chain list as a sequence
  of ``(AuthorityRole, module_path)`` pairs.
* :func:`resolve_trace_authority` — given an existing PR-7
  :class:`~core.execution_observability.trace_schema.TraceCorrelation`, attach
  an authority annotation so observability consumers know which authority path
  handled the traced request.

Usage::

    from core.orchestration_authority.authority_resolver import (
        classify_module,
        authority_catalog,
    )

    role = classify_module("core.constellation_runtime")
    # → AuthorityRole.EXECUTION_RUNTIME_DELEGATE

    catalog = authority_catalog()
    # → dict with 'authority_chain', 'role_catalog', 'legacy_paths', …
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from .authority_roles import AuthorityRole, ROLE_CATALOG, is_authoritative
from .legacy_paths import LEGACY_PATH_REGISTRY, LegacyPathStatus

logger = logging.getLogger("Galaxy.OrchestrationAuthority")

__all__ = [
    "classify_module",
    "authority_catalog",
    "authority_chain",
    "resolve_trace_authority",
]

# ---------------------------------------------------------------------------
# Static classification table
# ---------------------------------------------------------------------------
#
# Maps dotted module/path prefixes (or exact module strings) → AuthorityRole.
# Entries are evaluated longest-match first so more-specific rules win.

_CLASSIFICATION_TABLE: List[Tuple[str, AuthorityRole]] = [
    # Authoritative control-plane entrypoint
    ("core.desktop_presence_runtime", AuthorityRole.AUTHORITATIVE_ENTRYPOINT),
    # Execution runtime delegate
    ("core.constellation_runtime", AuthorityRole.EXECUTION_RUNTIME_DELEGATE),
    # DAG execution engine
    ("core.task_graph", AuthorityRole.DAG_EXECUTION_ENGINE),
    # Orchestration coordinator
    ("core.e2e_orchestrator", AuthorityRole.ORCHESTRATION_COORDINATOR),
    # Orchestration coordinator (legacy multi-device entry)
    ("galaxy_gateway.orchestrator.multi_device", AuthorityRole.ORCHESTRATION_COORDINATOR),
    # Legacy / deprecated paths — resolved via LEGACY_PATH_REGISTRY below;
    # listed here for prefix-based fallback
    ("nodes.Node_110_SmartOrchestrator", AuthorityRole.LEGACY_COMPATIBILITY),
    ("nodes.Node_81_Orchestrator", AuthorityRole.LEGACY_COMPATIBILITY),
    ("nodes.Node_50_Transformer", AuthorityRole.DEPRECATED),
    ("galaxy_gateway.orchestrator.task_orchestrator", AuthorityRole.LEGACY_COMPATIBILITY),
    ("galaxy_gateway.orchestrator", AuthorityRole.LEGACY_COMPATIBILITY),
    ("fusion.unified_orchestrator", AuthorityRole.LEGACY_COMPATIBILITY),
    ("core.orchestrator_engine", AuthorityRole.LEGACY_COMPATIBILITY),
]

# Sort by length descending so longest prefix wins
_CLASSIFICATION_TABLE.sort(key=lambda t: len(t[0]), reverse=True)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_module(module_path: str) -> AuthorityRole:
    """Classify *module_path* into an :class:`~.authority_roles.AuthorityRole`.

    Classification strategy (in priority order):

    1. Exact or prefix match against the static table above.
    2. Lookup in :data:`~.legacy_paths.LEGACY_PATH_REGISTRY` (exact match).
    3. If the registry entry status is :attr:`~LegacyPathStatus.DEPRECATED`,
       return :attr:`~AuthorityRole.DEPRECATED`.
    4. Fallback: :attr:`~AuthorityRole.UNKNOWN`.

    Parameters
    ----------
    module_path:
        Dotted module path, e.g. ``"core.constellation_runtime"`` or
        ``"nodes.Node_110_SmartOrchestrator.server"``.

    Returns
    -------
    AuthorityRole
    """
    if not module_path:
        return AuthorityRole.UNKNOWN

    # 1. Static table (longest prefix first)
    for prefix, role in _CLASSIFICATION_TABLE:
        if module_path == prefix or module_path.startswith(prefix + ".") or module_path.startswith(prefix + ":"):
            return role

    # 2. Legacy registry exact lookup
    entry = LEGACY_PATH_REGISTRY.get(module_path)
    if entry is not None:
        if entry.status == LegacyPathStatus.DEPRECATED:
            return AuthorityRole.DEPRECATED
        return AuthorityRole.LEGACY_COMPATIBILITY

    return AuthorityRole.UNKNOWN


# ---------------------------------------------------------------------------
# Authority chain
# ---------------------------------------------------------------------------

#: The canonical top-to-bottom authority entry chain as (role, module) pairs.
_AUTHORITY_CHAIN: List[Tuple[AuthorityRole, str]] = [
    (
        AuthorityRole.AUTHORITATIVE_ENTRYPOINT,
        ROLE_CATALOG[AuthorityRole.AUTHORITATIVE_ENTRYPOINT]["canonical_module"],
    ),
    (
        AuthorityRole.ORCHESTRATION_COORDINATOR,
        ROLE_CATALOG[AuthorityRole.ORCHESTRATION_COORDINATOR]["canonical_module"],
    ),
    (
        AuthorityRole.EXECUTION_RUNTIME_DELEGATE,
        ROLE_CATALOG[AuthorityRole.EXECUTION_RUNTIME_DELEGATE]["canonical_module"],
    ),
    (
        AuthorityRole.DAG_EXECUTION_ENGINE,
        ROLE_CATALOG[AuthorityRole.DAG_EXECUTION_ENGINE]["canonical_module"],
    ),
]


def authority_chain() -> List[Tuple[AuthorityRole, str]]:
    """Return the ordered authority entry-chain.

    Each element is a ``(AuthorityRole, canonical_module_path)`` pair ordered
    from highest to lowest authority level.

    Returns
    -------
    list of (AuthorityRole, str)
    """
    return list(_AUTHORITY_CHAIN)


# ---------------------------------------------------------------------------
# Full authority catalog
# ---------------------------------------------------------------------------


def authority_catalog(*, include_legacy: bool = True) -> Dict[str, Any]:
    """Produce a machine-readable catalog of the complete orchestration authority
    topology.

    The returned dict is JSON-serialisable (all values are primitives, lists,
    or nested dicts — no Enum instances).

    Parameters
    ----------
    include_legacy:
        When True (default) include legacy/deprecated path entries in the
        ``"legacy_paths"`` section.

    Returns
    -------
    dict
        Keys:
        ``"schema_version"``
            Integer version of this catalog format (currently ``1``).
        ``"pr"``
            PR that introduced this catalog (``"PR-9"``).
        ``"authority_chain"``
            List of ``{"rank": int, "role": str, "module": str}`` dicts,
            ordered from highest to lowest authority.
        ``"role_catalog"``
            Dict mapping role-value → role metadata (from :data:`ROLE_CATALOG`).
        ``"legacy_paths"``
            List of serialised :class:`~.legacy_paths.LegacyPathEntry` dicts
            (only if *include_legacy* is True).
    """
    chain_list = [
        {
            "rank": idx + 1,
            "role": role.value,
            "module": module,
            "label": ROLE_CATALOG[role]["label"],
        }
        for idx, (role, module) in enumerate(_AUTHORITY_CHAIN)
    ]

    role_cat: Dict[str, Any] = {}
    for role, info in ROLE_CATALOG.items():
        entry: Dict[str, Any] = {k: v for k, v in info.items()}
        # Normalise list elements that are role-value strings
        entry["role"] = role.value
        if "downstream_delegates" in entry:
            entry["downstream_delegates"] = list(entry["downstream_delegates"])
        role_cat[role.value] = entry

    catalog: Dict[str, Any] = {
        "schema_version": 1,
        "pr": "PR-9",
        "authority_chain": chain_list,
        "role_catalog": role_cat,
    }

    if include_legacy:
        catalog["legacy_paths"] = [
            entry.to_dict() for entry in LEGACY_PATH_REGISTRY.values()
        ]

    return catalog


# ---------------------------------------------------------------------------
# Trace authority annotation
# ---------------------------------------------------------------------------


def resolve_trace_authority(
    trace_dict: Dict[str, Any],
    *,
    source_module: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach authority metadata to an existing observability trace dict.

    This helper is designed for use alongside the PR-7
    :class:`~core.execution_observability.trace_schema.TraceCorrelation`
    pattern.  It accepts a plain dict (the ``.to_dict()`` of a
    ``TraceCorrelation`` or any dict with a ``trace_id`` field) and returns a
    new dict with an extra ``"authority"`` key.

    It never raises; on any error it returns the original dict unchanged with
    an ``"authority_error"`` field.

    Parameters
    ----------
    trace_dict:
        Existing trace correlation dict.  Must contain at least a ``trace_id``
        key to be useful.
    source_module:
        Optional dotted module path of the code that originated the trace.
        If provided, it is classified and the role is included in the result.

    Returns
    -------
    dict
        Copy of *trace_dict* with an additional ``"authority"`` sub-dict.
    """
    try:
        result = dict(trace_dict)
        role = (
            classify_module(source_module)
            if source_module
            else AuthorityRole.UNKNOWN
        )
        result["authority"] = {
            "role": role.value,
            "label": ROLE_CATALOG[role]["label"],
            "source_module": source_module,
            "active": is_authoritative(role),
        }
        return result
    except Exception as exc:  # pragma: no cover
        logger.warning("resolve_trace_authority failed: %s", exc)
        fallback = dict(trace_dict)
        fallback["authority_error"] = str(exc)
        return fallback
