#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.orchestration_authority.authority_summary
===============================================

PR-9 (V3) — Orchestration Authority Consolidation

Provides a stable, **serialisable** :class:`AuthoritySummary` dataclass and
helper functions that downstream systems (observability dashboards,
RuntimeProjection, manifest stage, status board) can consume to understand
which orchestration authority path handled a given request.

This module integrates with:
* PR-7 ``core.execution_observability`` — attaches authority metadata to
  :class:`~core.execution_observability.event_schema.ExecutionEvent` dicts.
* PR-8 ``core.envelope_consolidation`` — can annotate
  :class:`~core.envelope_consolidation.EnvelopeSummary` with authority role.
* :mod:`~.authority_resolver` — drives classification from module paths.

Usage::

    from core.orchestration_authority.authority_summary import (
        AuthoritySummary,
        summarise_authority,
        authority_summary_for_projection,
    )

    # Build a summary for a request that came through DesktopPresenceRuntime
    summary = summarise_authority(
        source_module="core.desktop_presence_runtime",
        trace_id="trace_abc123",
        runtime_session_id="rsess_xyz",
    )
    print(summary.to_dict())
    # {'role': 'authoritative_entrypoint', 'active': True, …}

    # Projection-friendly helper (returns minimal dict for Status Board / Manifest)
    proj = authority_summary_for_projection(summary)
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Dict, Optional

from .authority_roles import AuthorityRole, ROLE_CATALOG, role_label, is_authoritative
from .authority_resolver import classify_module, authority_chain

logger = logging.getLogger("Galaxy.OrchestrationAuthority")

__all__ = [
    "AuthoritySummary",
    "summarise_authority",
    "authority_summary_for_projection",
    "attach_authority_to_event",
    "attach_authority_to_envelope_summary",
]


# ---------------------------------------------------------------------------
# AuthoritySummary dataclass
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class AuthoritySummary:
    """Stable, serialisable authority context for a single request lifecycle.

    Attributes
    ----------
    role:
        Classified :class:`~.authority_roles.AuthorityRole` of the originating
        module.
    label:
        Human-readable role label.
    source_module:
        Dotted module path that was classified (e.g.
        ``"core.desktop_presence_runtime"``).
    active:
        True if the role represents a currently active authority path.
    trace_id:
        Distributed trace ID (from PR-7 TraceCorrelation).
    runtime_session_id:
        Galaxy runtime session ID (from DesktopPresenceRuntime).
    canonical_module:
        Canonical module path for this authority role (from ROLE_CATALOG).
    canonical_class:
        Canonical class name for this authority role (from ROLE_CATALOG), if any.
    pr_introduced:
        PR that introduced this authority path.
    extra:
        Optional free-form metadata dict for context-specific additions.
    """

    role: AuthorityRole
    label: str
    source_module: Optional[str]
    active: bool
    trace_id: Optional[str] = None
    runtime_session_id: Optional[str] = None
    canonical_module: Optional[str] = None
    canonical_class: Optional[str] = None
    pr_introduced: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict representation."""
        d: Dict[str, Any] = {
            "role": self.role.value,
            "label": self.label,
            "source_module": self.source_module,
            "active": self.active,
            "trace_id": self.trace_id,
            "runtime_session_id": self.runtime_session_id,
            "canonical_module": self.canonical_module,
            "canonical_class": self.canonical_class,
            "pr_introduced": self.pr_introduced,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthoritySummary":
        """Reconstruct an :class:`AuthoritySummary` from a previously
        serialised dict (e.g. read from a log or API response).

        Unknown or missing fields are silently ignored / defaulted.
        """
        try:
            role = AuthorityRole(data.get("role", AuthorityRole.UNKNOWN.value))
        except ValueError:
            role = AuthorityRole.UNKNOWN
        return cls(
            role=role,
            label=data.get("label", role_label(role)),
            source_module=data.get("source_module"),
            active=bool(data.get("active", False)),
            trace_id=data.get("trace_id"),
            runtime_session_id=data.get("runtime_session_id"),
            canonical_module=data.get("canonical_module"),
            canonical_class=data.get("canonical_class"),
            pr_introduced=data.get("pr_introduced"),
            extra=data.get("extra"),
        )


# ---------------------------------------------------------------------------
# Factory helper
# ---------------------------------------------------------------------------


def summarise_authority(
    source_module: Optional[str] = None,
    *,
    trace_id: Optional[str] = None,
    runtime_session_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> AuthoritySummary:
    """Classify *source_module* and return an :class:`AuthoritySummary`.

    This is the primary factory for creating authority summaries in request
    handlers, middleware, or observability callbacks.

    Parameters
    ----------
    source_module:
        Dotted module path of the code that originated the request.  If
        omitted, the role will be :attr:`~AuthorityRole.UNKNOWN`.
    trace_id:
        PR-7 distributed trace ID to embed in the summary.
    runtime_session_id:
        Galaxy ``runtime_session_id`` from :class:`DesktopPresenceRuntime`.
    extra:
        Optional free-form metadata.

    Returns
    -------
    AuthoritySummary
    """
    role = classify_module(source_module or "")
    info = ROLE_CATALOG[role]
    return AuthoritySummary(
        role=role,
        label=role_label(role),
        source_module=source_module,
        active=is_authoritative(role),
        trace_id=trace_id,
        runtime_session_id=runtime_session_id,
        canonical_module=info.get("canonical_module"),
        canonical_class=info.get("canonical_class"),
        pr_introduced=info.get("pr_introduced"),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Projection-friendly helper
# ---------------------------------------------------------------------------


def authority_summary_for_projection(
    summary: AuthoritySummary,
) -> Dict[str, Any]:
    """Return a minimal dict suitable for downstream projection layers.

    The Status Board v2, RuntimeProjection, and Manifest stage surfaces can
    embed this dict directly in their output without depending on the full
    :class:`AuthoritySummary` type.

    Returns
    -------
    dict
        Keys: ``role``, ``label``, ``active``, ``trace_id``,
        ``runtime_session_id``, ``canonical_module``.
    """
    return {
        "role": summary.role.value,
        "label": summary.label,
        "active": summary.active,
        "trace_id": summary.trace_id,
        "runtime_session_id": summary.runtime_session_id,
        "canonical_module": summary.canonical_module,
    }


# ---------------------------------------------------------------------------
# PR-7 integration helper: attach authority to ExecutionEvent dict
# ---------------------------------------------------------------------------


def attach_authority_to_event(
    event_dict: Dict[str, Any],
    *,
    source_module: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach an authority summary to a PR-7 ``ExecutionEvent`` dict.

    Accepts the plain dict returned by
    :meth:`~core.execution_observability.event_schema.ExecutionEvent.to_dict`
    (or any dict that has ``trace_id`` / ``runtime_session_id`` keys) and
    returns a **new** dict with an ``"orchestration_authority"`` key.

    This helper never raises; on error it returns the original dict with an
    ``"orchestration_authority_error"`` key.

    Parameters
    ----------
    event_dict:
        PR-7 ExecutionEvent dict (or compatible dict).
    source_module:
        Optional dotted module path to classify.  If omitted, the function
        attempts to read ``event_dict.get("source_module")``.

    Returns
    -------
    dict
    """
    try:
        mod = source_module or event_dict.get("source_module")
        trace_id = event_dict.get("trace_id")
        rsid = event_dict.get("runtime_session_id")
        summary = summarise_authority(
            source_module=mod,
            trace_id=trace_id,
            runtime_session_id=rsid,
        )
        result = dict(event_dict)
        result["orchestration_authority"] = authority_summary_for_projection(summary)
        return result
    except Exception as exc:  # pragma: no cover
        logger.warning("attach_authority_to_event failed: %s", exc)
        fallback = dict(event_dict)
        fallback["orchestration_authority_error"] = str(exc)
        return fallback


# ---------------------------------------------------------------------------
# PR-8 integration helper: attach authority to EnvelopeSummary dict
# ---------------------------------------------------------------------------


def attach_authority_to_envelope_summary(
    envelope_summary_dict: Dict[str, Any],
    *,
    source_module: Optional[str] = None,
) -> Dict[str, Any]:
    """Attach an authority summary to a PR-8 ``EnvelopeSummary`` dict.

    Accepts the dict returned by
    :func:`~core.envelope_consolidation.envelope_summary.summarise_envelope`
    (or ``EnvelopeSummary.to_dict()``) and returns a **new** dict with an
    ``"orchestration_authority"`` key.

    Parameters
    ----------
    envelope_summary_dict:
        PR-8 EnvelopeSummary dict.
    source_module:
        Optional dotted module path to classify.

    Returns
    -------
    dict
    """
    try:
        mod = source_module or envelope_summary_dict.get("source_module")
        trace_id = envelope_summary_dict.get("trace_id")
        rsid = envelope_summary_dict.get("runtime_session_id")
        summary = summarise_authority(
            source_module=mod,
            trace_id=trace_id,
            runtime_session_id=rsid,
        )
        result = dict(envelope_summary_dict)
        result["orchestration_authority"] = authority_summary_for_projection(summary)
        return result
    except Exception as exc:  # pragma: no cover
        logger.warning("attach_authority_to_envelope_summary failed: %s", exc)
        fallback = dict(envelope_summary_dict)
        fallback["orchestration_authority_error"] = str(exc)
        return fallback
