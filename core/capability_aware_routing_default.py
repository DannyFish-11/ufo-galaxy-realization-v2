#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/capability_aware_routing_default.py
==========================================
Capability-aware routing as the default main path.

Problem addressed
-----------------
Prior to this module, capability-aware routing was only activated when callers
explicitly declared ``required_capabilities``.  When a cross-device dispatch
carried an explicit ``device_id`` but no ``required_capabilities``, the
capability gate was silently skipped — ``device_id`` became the effective
routing decision rather than capability-driven participant selection.

This introduced three structural gaps:

1. Android capability declarations did not become true decision factors in
   the default dispatch main path.
2. The system defaulted to "hard-coded target dispatch" rather than
   "capability-driven intelligent selection".
3. Capability mismatch remained warning-only rather than a routing constraint.

This module closes those gaps by:

1. Declaring **capability-aware routing as the default main path** via policy
   sentinels and enforcement machinery.
2. Making explicit ``device_id`` the **exception path** (override / debug /
   forced routing scenarios), not the default dispatch mechanism.  Exception-
   path requests still run the capability gate.
3. Declaring capability mismatch as a **routing constraint** — the system
   must reroute to a capable alternative or produce a structured rejection,
   never silently proceed with an incapable device.
4. Providing :func:`apply_capability_aware_default` — the enforcement function
   wired into the canonical dispatch paths (``route_envelope``, ``process()``).

Design principles
-----------------
- **Default ON** — capability-aware routing runs on every cross-device dispatch
  regardless of whether ``required_capabilities`` is declared.  Capability
  inference from the tool/command name fills the gap when the caller omits
  explicit requirements.
- **Explicit routing is the exception** — passing an explicit ``device_id``
  moves the request to an override path that still runs the capability gate.
- **Mismatch is a constraint** — a capability mismatch produces a structured
  routing decision (reroute to capable alternative, or reject) rather than a
  warning log entry.
- **Additive only** — does not modify ``capability_routing_gate``,
  ``mainline_routing_enforcement``, or ``capability_enforcement_hardener``.

Public API
----------
Sentinels::

    CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY
    CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_POLICY
    EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_POLICY
    CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_POLICY

Enumerations::

    CapabilityRoutingOutcome

Data class::

    CapabilityAwareRoutingDecision

Functions::

    infer_dispatch_capabilities(tool_name) -> List[str]
    apply_capability_aware_default(tool_name, explicit_targets, routable, ...)
        -> CapabilityAwareRoutingDecision
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Sequence

logger = logging.getLogger("Galaxy.CapabilityAwareRoutingDefault")

__all__ = [
    # Sentinels
    "CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY",
    "CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_POLICY",
    "EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_POLICY",
    "CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_POLICY",
    # Enumerations
    "CapabilityRoutingOutcome",
    # Data class
    "CapabilityAwareRoutingDecision",
    # Functions
    "infer_dispatch_capabilities",
    "apply_capability_aware_default",
]

# ---------------------------------------------------------------------------
# Policy sentinels
# ---------------------------------------------------------------------------

CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY: str = (
    "CAPABILITY_AWARE_ROUTING_DEFAULT_AUTHORITY_V1: "
    "core.capability_aware_routing_default is the canonical module that "
    "promotes capability-aware routing to the default main path for all "
    "cross-device dispatch.  Callers that omit required_capabilities receive "
    "capability inference from the tool/command name.  Explicit device_id is "
    "the exception path, not the default dispatch mechanism.  All canonical "
    "dispatch paths (route_envelope, process) must wire this module."
)

CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_POLICY: str = (
    "POLICY::CAPABILITY_AWARE_ROUTING_IS_DEFAULT_MAINLINE_V1: "
    "Cross-device participant selection MUST default to capability-driven "
    "routing via the capability graph / routing policy.  Capability inference "
    "from the tool/command name provides a default capability set when callers "
    "omit required_capabilities.  The system does NOT default to explicit "
    "device_id dispatch.  This policy is enforced in route_envelope() and "
    "process().  Resolves the structural gap where capability declarations "
    "were not true decision factors in the default dispatch main path."
)

EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_POLICY: str = (
    "POLICY::EXPLICIT_DEVICE_ID_IS_EXCEPTION_PATH_V1: "
    "An explicit device_id in a cross-device dispatch request is an EXCEPTION "
    "PATH (override / debug / forced routing).  It is NOT the default main "
    "path.  Explicit device_id requests still run the capability gate.  When "
    "the explicit target fails the capability gate, the system MUST either "
    "reroute to a capable alternative or reject the dispatch.  Silently "
    "proceeding with an incapable device is prohibited on all canonical "
    "dispatch paths."
)

CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_POLICY: str = (
    "POLICY::CAPABILITY_MISMATCH_IS_ROUTING_CONSTRAINT_V1: "
    "A capability mismatch is a routing constraint, not an advisory warning.  "
    "When a device cannot satisfy the task requirements, the routing system "
    "MUST select an alternative capable device (reroute) or return a structured "
    "CAPABILITY_MISMATCH error (reject).  Proceeding with an incapable device "
    "while only emitting a log warning is prohibited on all canonical dispatch "
    "paths.  This policy closes the gap where mismatch remained warning-only "
    "rather than a hard behavioural constraint."
)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class CapabilityRoutingOutcome(str, Enum):
    """Outcome of a capability-aware routing decision."""

    CAPABILITY_MATCHED = "capability_matched"
    """The explicit or selected target(s) satisfy all required capabilities."""

    CAPABILITY_REROUTED = "capability_rerouted"
    """Explicit target(s) failed capability gate; rerouted to capable
    alternatives found in the capability graph."""

    CAPABILITY_REJECTED = "capability_rejected"
    """No device satisfies the required capabilities; dispatch must be
    rejected with a structured CAPABILITY_MISMATCH error."""

    EXPLICIT_OVERRIDE = "explicit_override"
    """Explicit device_id provided but no capabilities were inferrable for
    the tool/command; proceeding as an audited exception-path override."""

    NO_REQUIREMENTS = "no_requirements"
    """No capabilities are required or inferrable; routing proceeds without
    the capability gate (backward-compatible no-op path)."""

    INSUFFICIENT_DATA = "insufficient_data"
    """The capability graph has no executor data; routing proceeds with an
    INSUFFICIENT_DATA record for observability."""


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass
class CapabilityAwareRoutingDecision:
    """Result of a capability-aware routing decision.

    Attributes
    ----------
    outcome:
        The routing outcome classification.
    recommended_targets:
        Device IDs recommended by the capability-aware decision.  Empty
        when ``outcome`` is ``CAPABILITY_REJECTED``.
    inferred_capabilities:
        Capabilities inferred from the tool/command name.  May be empty
        when none were inferrable or when explicit capabilities were provided.
    applied_capabilities:
        Effective required capabilities used in the gate (explicit or
        inferred).  Empty when ``outcome`` is ``NO_REQUIREMENTS``.
    original_explicit_targets:
        The device ID(s) provided by the caller before any gate redirection.
        Empty when no explicit target was supplied.
    reason:
        Human-readable explanation of the routing decision.
    is_explicit_override:
        ``True`` when the decision is an exception-path explicit override
        (tool had no inferrable capabilities and an explicit target was
        supplied).
    """

    outcome: CapabilityRoutingOutcome
    recommended_targets: List[str] = field(default_factory=list)
    inferred_capabilities: List[str] = field(default_factory=list)
    applied_capabilities: List[str] = field(default_factory=list)
    original_explicit_targets: List[str] = field(default_factory=list)
    reason: str = ""
    is_explicit_override: bool = False

    def to_dict(self) -> dict:
        """Serialise to a plain dict for response metadata / audit records."""
        return {
            "outcome": self.outcome.value,
            "recommended_targets": list(self.recommended_targets),
            "inferred_capabilities": list(self.inferred_capabilities),
            "applied_capabilities": list(self.applied_capabilities),
            "original_explicit_targets": list(self.original_explicit_targets),
            "reason": self.reason,
            "is_explicit_override": self.is_explicit_override,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def infer_dispatch_capabilities(tool_name: str) -> List[str]:
    """Infer required capabilities for *tool_name*.

    Delegates to
    :func:`~core.gateway_capability_default_enforcement.infer_required_capabilities`
    which consults the canonical command-to-capability table.

    Parameters
    ----------
    tool_name:
        Tool or command name (e.g. ``"take_photo"``, ``"screen_click"``).

    Returns
    -------
    list[str]
        Inferred capability strings, or an empty list when none are
        inferrable.
    """
    if not tool_name:
        return []
    try:
        from core.gateway_capability_default_enforcement import (
            infer_required_capabilities,
        )

        return infer_required_capabilities(tool_name)
    except Exception as exc:
        logger.debug(
            "infer_dispatch_capabilities: inference unavailable for tool=%r: %s",
            tool_name,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Core enforcement function
# ---------------------------------------------------------------------------


def apply_capability_aware_default(
    tool_name: str,
    explicit_targets: Sequence[str],
    routable_executors: Optional[List[Any]] = None,
    *,
    required_capabilities: Optional[Sequence[str]] = None,
    calling_site: str = "unknown",
) -> CapabilityAwareRoutingDecision:
    """Apply capability-aware routing as the default main path.

    This is the canonical enforcement point that makes capability-driven
    routing the default for all cross-device dispatches, regardless of
    whether the caller declared ``required_capabilities``.

    Logic
    -----
    1. Resolve effective required capabilities:

       * Use *required_capabilities* if non-empty.
       * Otherwise infer from *tool_name* via
         :func:`infer_dispatch_capabilities`.

    2. If no capabilities are resolvable:

       * When *explicit_targets* are present → ``EXPLICIT_OVERRIDE``
         (exception path, audited).
       * Otherwise → ``NO_REQUIREMENTS`` (no-op gate).

    3. If capabilities are available and *explicit_targets* given:

       * Identify which targets are confirmed in *routable_executors*.
       * All confirmed → ``CAPABILITY_MATCHED`` (proceed unchanged).
       * Some confirmed → ``CAPABILITY_MATCHED`` (filter to confirmed subset,
         warn about unconfirmed).
       * None confirmed AND alternatives exist → ``CAPABILITY_REROUTED`` to
         those alternatives (explicit target demoted to exception path).
       * None confirmed AND no alternatives → ``CAPABILITY_REJECTED``
         (structured rejection, not a warning).

    4. If capabilities are available and NO *explicit_targets*:

       * Capability graph candidates → ``CAPABILITY_MATCHED`` (best-match
         selection).
       * No candidates in graph → ``INSUFFICIENT_DATA``.

    Parameters
    ----------
    tool_name:
        Tool or command name used for capability inference when
        *required_capabilities* is absent.
    explicit_targets:
        Explicit device IDs provided by the caller.  May be empty when
        the caller defers selection to the capability graph.
    routable_executors:
        List of capability-graph executor records.  Each object should
        have a ``node_id`` attribute.  ``None`` is treated as an empty
        list.
    required_capabilities:
        Explicit required capabilities.  When ``None`` or empty, inference
        from *tool_name* is attempted.
    calling_site:
        Human-readable label for the call site (used in log messages).

    Returns
    -------
    CapabilityAwareRoutingDecision
        The routing decision record.  Never raises.
    """
    # Step 1: resolve effective required capabilities
    eff_explicit = list(required_capabilities) if required_capabilities else []
    inferred: List[str] = []
    if not eff_explicit:
        inferred = infer_dispatch_capabilities(tool_name)
    applied_caps: List[str] = eff_explicit or inferred

    explicit_target_list = list(explicit_targets)
    routable_list: List[Any] = routable_executors or []
    routable_ids = {
        (getattr(e, "node_id", None) if getattr(e, "node_id", None) else str(e))
        for e in routable_list
        if e is not None
    }
    # Remove empty strings that may result from missing node_id
    routable_ids.discard("")

    # ── Step 2: no capabilities resolvable ───────────────────────────────────
    if not applied_caps:
        if explicit_target_list:
            logger.debug(
                "[%s] capability-aware routing: no capabilities inferrable for "
                "tool=%r; accepting explicit target(s) %s as exception-path "
                "override (EXPLICIT_OVERRIDE)",
                calling_site,
                tool_name,
                explicit_target_list,
            )
            return CapabilityAwareRoutingDecision(
                outcome=CapabilityRoutingOutcome.EXPLICIT_OVERRIDE,
                recommended_targets=explicit_target_list,
                inferred_capabilities=inferred,
                applied_capabilities=[],
                original_explicit_targets=explicit_target_list,
                reason=(
                    f"No capabilities inferrable for tool={tool_name!r}; "
                    "explicit target accepted as exception-path override"
                ),
                is_explicit_override=True,
            )
        return CapabilityAwareRoutingDecision(
            outcome=CapabilityRoutingOutcome.NO_REQUIREMENTS,
            recommended_targets=[],
            inferred_capabilities=inferred,
            applied_capabilities=[],
            original_explicit_targets=explicit_target_list,
            reason="No capabilities required or inferrable from tool name",
            is_explicit_override=False,
        )

    # ── Step 3: capabilities available, explicit targets provided ────────────
    if explicit_target_list:
        confirmed = [t for t in explicit_target_list if t in routable_ids]
        unconfirmed = [t for t in explicit_target_list if t not in routable_ids]

        if confirmed:
            if unconfirmed:
                logger.warning(
                    "[%s] capability-aware routing: explicit target(s) %s NOT "
                    "confirmed in capability graph for caps=%s; routing to "
                    "confirmed subset %s only",
                    calling_site,
                    unconfirmed,
                    applied_caps,
                    confirmed,
                )
            else:
                logger.debug(
                    "[%s] capability-aware routing: all %d explicit target(s) "
                    "confirmed in capability graph for caps=%s",
                    calling_site,
                    len(confirmed),
                    applied_caps,
                )
            return CapabilityAwareRoutingDecision(
                outcome=CapabilityRoutingOutcome.CAPABILITY_MATCHED,
                recommended_targets=confirmed,
                inferred_capabilities=inferred,
                applied_capabilities=applied_caps,
                original_explicit_targets=explicit_target_list,
                reason=(
                    f"Explicit target(s) {confirmed} confirmed in capability "
                    f"graph for caps={applied_caps}"
                ),
                is_explicit_override=False,
            )

        # None of the explicit targets are in the capability graph.
        # Capability mismatch — this is a routing constraint, not a warning.
        # Try to find alternative capable devices in the graph.
        _explicit_set = set(explicit_target_list)
        fallback_targets = sorted(
            r for r in routable_ids if r not in _explicit_set
        )
        if fallback_targets:
            logger.warning(
                "[%s] capability-aware routing [REROUTE]: explicit target(s) %s "
                "NOT confirmed in capability graph for caps=%s; rerouting to "
                "capable alternative(s) %s (explicit device_id demoted to "
                "exception path — CAPABILITY_REROUTED)",
                calling_site,
                explicit_target_list,
                applied_caps,
                fallback_targets,
            )
            return CapabilityAwareRoutingDecision(
                outcome=CapabilityRoutingOutcome.CAPABILITY_REROUTED,
                recommended_targets=fallback_targets,
                inferred_capabilities=inferred,
                applied_capabilities=applied_caps,
                original_explicit_targets=explicit_target_list,
                reason=(
                    f"Explicit target(s) {explicit_target_list} failed "
                    f"capability gate for caps={applied_caps}; rerouted to "
                    f"capable alternative(s) {fallback_targets}"
                ),
                is_explicit_override=False,
            )

        # No alternatives — structured rejection (not a warning).
        logger.warning(
            "[%s] capability-aware routing [REJECT]: explicit target(s) %s NOT "
            "confirmed in capability graph for caps=%s and no capable "
            "alternatives found; dispatch REJECTED (CAPABILITY_REJECTED)",
            calling_site,
            explicit_target_list,
            applied_caps,
        )
        return CapabilityAwareRoutingDecision(
            outcome=CapabilityRoutingOutcome.CAPABILITY_REJECTED,
            recommended_targets=[],
            inferred_capabilities=inferred,
            applied_capabilities=applied_caps,
            original_explicit_targets=explicit_target_list,
            reason=(
                f"Explicit target(s) {explicit_target_list} do not satisfy "
                f"required capabilities {applied_caps} and no capable "
                "alternatives exist in the capability graph"
            ),
            is_explicit_override=False,
        )

    # ── Step 4: capabilities available, NO explicit targets ──────────────────
    # Default main path: capability graph drives participant selection.
    if routable_ids:
        candidates = sorted(routable_ids)
        logger.debug(
            "[%s] capability-aware routing: no explicit target; capability graph "
            "provided %d candidate(s) for caps=%s (default main path)",
            calling_site,
            len(candidates),
            applied_caps,
        )
        return CapabilityAwareRoutingDecision(
            outcome=CapabilityRoutingOutcome.CAPABILITY_MATCHED,
            recommended_targets=candidates,
            inferred_capabilities=inferred,
            applied_capabilities=applied_caps,
            original_explicit_targets=[],
            reason=(
                f"Capability graph provided {len(candidates)} candidate(s) "
                f"for caps={applied_caps} (capability-driven default selection)"
            ),
            is_explicit_override=False,
        )

    # No candidates in the capability graph at all.
    logger.warning(
        "[%s] capability-aware routing: no executable candidates in capability "
        "graph for caps=%s and no explicit target provided (INSUFFICIENT_DATA)",
        calling_site,
        applied_caps,
    )
    return CapabilityAwareRoutingDecision(
        outcome=CapabilityRoutingOutcome.INSUFFICIENT_DATA,
        recommended_targets=[],
        inferred_capabilities=inferred,
        applied_capabilities=applied_caps,
        original_explicit_targets=[],
        reason=(
            f"Capability graph has no executors for caps={applied_caps}"
        ),
        is_explicit_override=False,
    )
