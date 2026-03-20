#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.orchestration_authority
=============================

PR-9 (V3) — Orchestration Authority Consolidation

A small, **additive** package that formalises orchestration authority roles,
boundaries, and interoperability for the Galaxy runtime.

This package answers:
  1. What is the authoritative top-level entry chain?
  2. What role does ConstellationRuntime play relative to DesktopPresenceRuntime?
  3. What role does TaskGraph play relative to orchestrators?
  4. Which modules are legacy/compatibility paths versus authoritative paths?
  5. How should downstream projection/observability layers refer to
     orchestration authority consistently?

It does **not** introduce a new orchestrator, replace any existing module, or
modify any active execution path.

Public API
----------
AuthorityRole
    Enum of authority levels (AUTHORITATIVE_ENTRYPOINT → EXECUTION_RUNTIME_DELEGATE
    → DAG_EXECUTION_ENGINE → ORCHESTRATION_COORDINATOR → LEGACY_COMPATIBILITY
    → DEPRECATED → UNKNOWN).

ROLE_CATALOG
    Machine-readable dict mapping each :class:`AuthorityRole` to metadata.

LegacyPathStatus / LegacyPathEntry / LEGACY_PATH_REGISTRY
    Registry of known legacy/deprecated orchestration paths.

classify_module(module_path) → AuthorityRole
    Classify a dotted module path into an :class:`AuthorityRole`.

authority_catalog(*, include_legacy=True) → dict
    Full machine-readable catalog of the orchestration topology.

authority_chain() → list[(AuthorityRole, str)]
    Ordered entry chain from highest to lowest authority.

AuthoritySummary / summarise_authority(…) → AuthoritySummary
    Stable serialisable authority context for a request lifecycle.

authority_summary_for_projection(summary) → dict
    Minimal dict for downstream Status Board / Manifest / RuntimeProjection.

attach_authority_to_event(event_dict) → dict
    Attach authority metadata to a PR-7 ExecutionEvent dict.

attach_authority_to_envelope_summary(summary_dict) → dict
    Attach authority metadata to a PR-8 EnvelopeSummary dict.

is_legacy_path(module_path) → bool
    Quick check against :data:`LEGACY_PATH_REGISTRY`.

emit_legacy_guardrail(caller, trace_id) → None
    Structured WARNING for legacy entrypoint invocations.
"""

from .authority_roles import (
    AuthorityRole,
    ROLE_CATALOG,
    ROLE_DESCRIPTIONS,
    role_label,
    is_authoritative,
    is_legacy_or_deprecated,
)
from .legacy_paths import (
    LegacyPathStatus,
    LegacyPathEntry,
    LEGACY_PATH_REGISTRY,
    LEGACY_ORCHESTRATOR_PATHS,
    is_legacy_path,
    get_legacy_entry,
    emit_legacy_guardrail,
    classify_path_status,
)
from .authority_resolver import (
    classify_module,
    authority_catalog,
    authority_chain,
    resolve_trace_authority,
)
from .authority_summary import (
    AuthoritySummary,
    summarise_authority,
    authority_summary_for_projection,
    attach_authority_to_event,
    attach_authority_to_envelope_summary,
)

__all__ = [
    # Roles
    "AuthorityRole",
    "ROLE_CATALOG",
    "ROLE_DESCRIPTIONS",
    "role_label",
    "is_authoritative",
    "is_legacy_or_deprecated",
    # Legacy paths
    "LegacyPathStatus",
    "LegacyPathEntry",
    "LEGACY_PATH_REGISTRY",
    "LEGACY_ORCHESTRATOR_PATHS",
    "is_legacy_path",
    "get_legacy_entry",
    "emit_legacy_guardrail",
    "classify_path_status",
    # Resolver
    "classify_module",
    "authority_catalog",
    "authority_chain",
    "resolve_trace_authority",
    # Summary
    "AuthoritySummary",
    "summarise_authority",
    "authority_summary_for_projection",
    "attach_authority_to_event",
    "attach_authority_to_envelope_summary",
]
