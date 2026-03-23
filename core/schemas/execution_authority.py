#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.schemas.execution_authority — Canonical Execution Authority Schema
========================================================================

PR-9 — Execution Authority Contract
PR-006 — Tighten OpenClawd–AgentKernel execution contract

Defines the canonical data types for representing the **execution authority
contract** across the Galaxy runtime stack.  Every layer in the main execution
path declares its role using the :class:`ExecutionLayerRole` enum so that the
authority chain is explicit, inspectable, and hard to regress.

PR-006 tightens the contract between OpenClawd and AgentKernel:
- ``SUBJECT_DECISION_AUTHORITY`` (OpenClawd) owns final multi-model routing.
- ``COGNITION_PLANNING_LAYER`` (AgentKernel) returns advisory ``KernelResponse``
  artifacts; ``delegation_hint`` and routing suggestions are never binding.
- SOUL/AGENTS policy injection is constrained to task_execute/hybrid phases.
- ``delegation_hint_decision`` metadata tracks whether hints were noted or absent.

Architecture (outer → inner)::

    ENTRY_SURFACE              ← /api/v1/chat, external adapters (compat surfaces)
    RUNTIME_SHELL_AUTHORITY    ← DesktopPresenceRuntime (session owner, tri-state)
    SUBJECT_DECISION_AUTHORITY ← OpenClawd (cognition + execution branching)
    COGNITION_PLANNING_LAYER   ← AgentKernel (embedded planning sub-layer)
    EXECUTION_SUBSTRATE        ← CommandRouter.route_envelope (transport)
    ORCHESTRATION_LAYER        ← SwarmCoordinator / E2EOrchestrator (coordination)

These roles are **additive metadata** — they do not change any execution logic.
They are designed to be embedded in response ``metadata`` dicts, log entries,
and diagnostics without breaking existing consumers.

Relationship to ``core.orchestration_authority``
-------------------------------------------------
``core.orchestration_authority`` (PR-9 V3) provides the broader orchestration
authority taxonomy (``AuthorityRole``) covering legacy/compat path tracking
and module classification.  This module defines a complementary, finer-grained
set of roles specifically for the **main execution path** from entry surface
down to the substrate.  Both are stable and additive.

Usage::

    from core.schemas.execution_authority import (
        ExecutionLayerRole,
        ExecutionAuthorityMetadata,
        build_authority_metadata,
        get_layer_authority,
        CANONICAL_AUTHORITY_CHAIN,
    )

    # Build authority metadata for a layer
    meta = build_authority_metadata(
        ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
        canonical_module="core.desktop_presence_runtime",
        canonical_class="DesktopPresenceRuntime",
        pr_introduced="PR-1",
    )

    # Resolve role from module path
    role = get_layer_authority("core.desktop_presence_runtime")
    # → ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY

    # Iterate the canonical chain
    for role, module, cls in CANONICAL_AUTHORITY_CHAIN:
        print(role.value, module, cls)
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

__all__ = [
    "ExecutionLayerRole",
    "ExecutionAuthorityMetadata",
    "CANONICAL_AUTHORITY_CHAIN",
    "build_authority_metadata",
    "get_layer_authority",
]


# ---------------------------------------------------------------------------
# Execution Layer Role enum
# ---------------------------------------------------------------------------


class ExecutionLayerRole(str, Enum):
    """Canonical roles in the execution authority chain.

    These roles describe *what authority a layer holds* in the main execution
    path, not what protocol or transport it uses.

    Outer layers may call inner layers; inner layers should not call outer
    layers (except via well-defined callback contracts).

    Values are stable lowercase strings suitable for serialisation, logging,
    and API responses.
    """

    #: External adapter surface — receives requests from outside the subject
    #: core.  Has no subject-core authority; hands off to
    #: :attr:`RUNTIME_SHELL_AUTHORITY`.
    #: Examples: ``/api/v1/chat``, gateway adapters.
    ENTRY_SURFACE = "entry_surface"

    #: Outer runtime shell — owns the canonical session, tri-state lifecycle,
    #: and native multimodal ingress.  All execution begins and ends here.
    #: Canonical component: ``DesktopPresenceRuntime``
    #: (``core.desktop_presence_runtime``).
    RUNTIME_SHELL_AUTHORITY = "runtime_shell_authority"

    #: Subject core / decision authority — performs cognition, execution
    #: branching, and manifestation.  Operates inside the liminal phase of
    #: the runtime shell.
    #: Canonical component: ``OpenClawd`` (``core.openclawd``).
    SUBJECT_DECISION_AUTHORITY = "subject_decision_authority"

    #: Embedded cognition/planning sub-layer — called by the subject core to
    #: route intent and plan execution steps.  Not an independent entrypoint.
    #: Canonical component: ``AgentKernel`` (``core.agent.kernel``).
    #:
    #: PR-006 contract: AgentKernel returns ``KernelResponse`` (advisory artifact).
    #: ``KernelResponse.delegation_hint`` and ``routing_authority`` are advisory
    #: only — OpenClawd retains all final decision authority.
    #: ``KernelResponse.soul_injection_phase`` is None for chat_only paths.
    COGNITION_PLANNING_LAYER = "cognition_planning_layer"

    #: Execution substrate — the transport and routing layer that carries
    #: task envelopes to their target devices.  Handles retries and device
    #: selection within a dispatch; does not plan multi-device coordination.
    #: Canonical component: ``CommandRouter.route_envelope``
    #: (``core.command_router``).
    EXECUTION_SUBSTRATE = "execution_substrate"

    #: Coordination / orchestration — selects devices, builds plans, and
    #: aggregates results.  Operates *above* the substrate.
    #: Examples: ``SwarmCoordinator`` (``core.swarm_coordinator``),
    #: ``E2EOrchestrator`` (``core.e2e_orchestrator``).
    ORCHESTRATION_LAYER = "orchestration_layer"

    #: Compatibility adapter — bridges a legacy or external API surface into
    #: the current authority chain.  Not a source of new authority.
    COMPATIBILITY_ADAPTER = "compatibility_adapter"

    #: Unknown or unclassified layer.
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Canonical authority chain (ordered outer → inner)
# ---------------------------------------------------------------------------

#: Ordered list of ``(ExecutionLayerRole, canonical_module, canonical_class)``
#: tuples representing the main execution authority chain from outermost
#: (entry surface) to the execution substrate.
#:
#: This is the authoritative reference for which component holds which role.
#: Future contributors should update this list when architectural boundaries
#: change rather than introducing ad-hoc string constants.
CANONICAL_AUTHORITY_CHAIN: List[Tuple[ExecutionLayerRole, str, str]] = [
    (
        ExecutionLayerRole.ENTRY_SURFACE,
        "core.routes.chat",
        "chat_route",
    ),
    (
        ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY,
        "core.desktop_presence_runtime",
        "DesktopPresenceRuntime",
    ),
    (
        ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY,
        "core.openclawd",
        "OpenClawd",
    ),
    (
        ExecutionLayerRole.COGNITION_PLANNING_LAYER,
        "core.agent.kernel",
        "AgentKernel",
    ),
    (
        ExecutionLayerRole.EXECUTION_SUBSTRATE,
        "core.command_router",
        "CommandRouter",
    ),
    (
        ExecutionLayerRole.ORCHESTRATION_LAYER,
        "core.swarm_coordinator",
        "SwarmCoordinator",
    ),
]


# ---------------------------------------------------------------------------
# ExecutionAuthorityMetadata schema
# ---------------------------------------------------------------------------


class ExecutionAuthorityMetadata(BaseModel):
    """Structured authority metadata attached to a request/response at one layer.

    Instances are created by :func:`build_authority_metadata` and are designed
    to be embedded in response ``metadata`` dicts or log entries without
    breaking existing consumers (additive fields only).

    Attributes
    ----------
    layer_role:
        The :class:`ExecutionLayerRole` of the component that produced this
        metadata.
    canonical_module:
        Fully-qualified dotted module path
        (e.g. ``"core.desktop_presence_runtime"``).
    canonical_class:
        Optional class name within the module.
    is_adapter_surface:
        ``True`` if this layer is only an adapter/compat surface and holds no
        subject-core authority.
    pr_introduced:
        The PR that introduced this layer's authority contract (informational).
    extra:
        Optional additional key/value pairs for observability tooling.
    """

    layer_role: ExecutionLayerRole = Field(
        description="The authority role of the component at this layer.",
    )
    canonical_module: str = Field(
        description="Fully-qualified dotted module path.",
    )
    canonical_class: Optional[str] = Field(
        default=None,
        description="Optional class name within the module.",
    )
    is_adapter_surface: bool = Field(
        default=False,
        description="True if this layer is a compat/adapter surface only.",
    )
    pr_introduced: Optional[str] = Field(
        default=None,
        description="PR that introduced this authority contract.",
    )
    extra: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extra metadata for observability tooling.",
    )

    model_config = {"use_enum_values": True}

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict (omits ``None`` optional fields)."""
        d: Dict[str, Any] = {
            "layer_role": (
                self.layer_role
                if isinstance(self.layer_role, str)
                else self.layer_role.value
            ),
            "canonical_module": self.canonical_module,
        }
        if self.canonical_class is not None:
            d["canonical_class"] = self.canonical_class
        if self.is_adapter_surface:
            d["is_adapter_surface"] = True
        if self.pr_introduced is not None:
            d["pr_introduced"] = self.pr_introduced
        if self.extra:
            d["extra"] = self.extra
        return d


# ---------------------------------------------------------------------------
# Module-path → role resolution
# ---------------------------------------------------------------------------

#: List of ``(module_prefix, ExecutionLayerRole)`` pairs evaluated
#: longest-prefix-first so more-specific rules win.
_MODULE_ROLE_PREFIXES: List[Tuple[str, ExecutionLayerRole]] = [
    ("core.routes.chat", ExecutionLayerRole.ENTRY_SURFACE),
    ("core.api_routes", ExecutionLayerRole.ENTRY_SURFACE),
    ("core.desktop_presence_runtime", ExecutionLayerRole.RUNTIME_SHELL_AUTHORITY),
    ("core.openclawd", ExecutionLayerRole.SUBJECT_DECISION_AUTHORITY),
    ("core.agent.kernel", ExecutionLayerRole.COGNITION_PLANNING_LAYER),
    ("core.command_router", ExecutionLayerRole.EXECUTION_SUBSTRATE),
    ("core.swarm_coordinator", ExecutionLayerRole.ORCHESTRATION_LAYER),
    ("core.e2e_orchestrator", ExecutionLayerRole.ORCHESTRATION_LAYER),
    ("core.orchestration", ExecutionLayerRole.ORCHESTRATION_LAYER),
    ("core.constellation_runtime", ExecutionLayerRole.ORCHESTRATION_LAYER),
]
# Sort longest-prefix first so more-specific entries win
_MODULE_ROLE_PREFIXES.sort(key=lambda t: len(t[0]), reverse=True)


def get_layer_authority(module_path: str) -> ExecutionLayerRole:
    """Resolve *module_path* to an :class:`ExecutionLayerRole`.

    Uses longest-prefix matching.  The prefix must match at a Python module
    boundary (dot separator or exact match) so that, for example,
    ``"core.openclawd_extra"`` does not accidentally match ``"core.openclawd"``.

    Unknown paths return :attr:`ExecutionLayerRole.UNKNOWN`.

    Parameters
    ----------
    module_path:
        Dotted module path (e.g. ``"core.desktop_presence_runtime"``).

    Returns
    -------
    ExecutionLayerRole
    """
    if not module_path:
        return ExecutionLayerRole.UNKNOWN
    for prefix, role in _MODULE_ROLE_PREFIXES:
        if module_path == prefix or module_path.startswith(prefix + "."):
            return role
    return ExecutionLayerRole.UNKNOWN


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def build_authority_metadata(
    layer_role: ExecutionLayerRole,
    canonical_module: str,
    *,
    canonical_class: Optional[str] = None,
    is_adapter_surface: bool = False,
    pr_introduced: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> ExecutionAuthorityMetadata:
    """Construct an :class:`ExecutionAuthorityMetadata` for the given layer.

    Parameters
    ----------
    layer_role:
        The :class:`ExecutionLayerRole` of the calling component.
    canonical_module:
        Fully-qualified module path.
    canonical_class:
        Optional class name.
    is_adapter_surface:
        Whether this layer is a compat/adapter surface (default ``False``).
    pr_introduced:
        PR that introduced this authority contract.
    extra:
        Optional extra metadata dict.

    Returns
    -------
    ExecutionAuthorityMetadata
    """
    return ExecutionAuthorityMetadata(
        layer_role=layer_role,
        canonical_module=canonical_module,
        canonical_class=canonical_class,
        is_adapter_surface=is_adapter_surface,
        pr_introduced=pr_introduced,
        extra=extra,
    )
