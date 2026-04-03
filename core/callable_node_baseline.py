#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core.callable_node_baseline
============================
Phase-B consolidation — Callable-Node Baseline.

Encodes which :class:`~core.nodes.node_fabric_registry.NodeArchitecturalClass`
values make a node **truly callable by OpenClawd** (i.e. a node whose
capabilities are surfaced into the CapabilityRegistry and consumed by
``OpenClawd._collect_tools()``).

This baseline is **distinct from startup readiness**: a node may start
successfully but still not be callable if it is classified as SERVICE_NODE,
LEGACY_ORCHESTRATOR_NODE, EXPERIMENTAL_NODE, or ARCHIVED_NODE.

Sentinel
--------
:data:`CALLABLE_NODE_BASELINE_ESTABLISHED` — import this to assert that the
baseline definition is present and enforced in code.

Usage
-----
::

    from core.callable_node_baseline import (
        CALLABLE_NODE_BASELINE_ESTABLISHED,
        CALLABLE_ARCHITECTURAL_CLASSES,
        is_callable_by_openclawd,
        get_callable_node_names,
    )

    # Check whether a node's class makes it callable.
    from core.nodes.node_fabric_registry import NodeArchitecturalClass
    print(is_callable_by_openclawd(NodeArchitecturalClass.CAPABILITY_NODE))   # True
    print(is_callable_by_openclawd(NodeArchitecturalClass.SERVICE_NODE))       # False

    # List all registered nodes that are currently callable.
    for name in get_callable_node_names():
        print(name)
"""
from __future__ import annotations

import logging
from typing import FrozenSet, List

logger = logging.getLogger("Galaxy.CallableNodeBaseline")

# ---------------------------------------------------------------------------
# Sentinel
# ---------------------------------------------------------------------------

#: Phase-B consolidation sentinel.  Presence of this string confirms that the
#: callable-node baseline is encoded in code and not merely documented.
CALLABLE_NODE_BASELINE_ESTABLISHED: str = (
    "CALLABLE_NODE_BASELINE_V1: "
    "core/callable_node_baseline.py defines CALLABLE_ARCHITECTURAL_CLASSES "
    "and exposes is_callable_by_openclawd() / get_callable_node_names()."
)

# ---------------------------------------------------------------------------
# Canonical callable-class set
# ---------------------------------------------------------------------------

def _build_callable_classes() -> "FrozenSet":
    """Return the frozenset of NodeArchitecturalClass values that are callable.

    The import is deferred so this module can be imported without requiring
    the full node subsystem to be initialised (e.g. in lightweight tests or
    the validate_runtime.py script).
    """
    try:
        from core.nodes.node_fabric_registry import (
            NodeArchitecturalClass,
            _CAPABILITY_SYNC_ELIGIBLE,
        )
        # _CAPABILITY_SYNC_ELIGIBLE is the authoritative set defined in
        # node_fabric_registry.py.  We mirror it here so callers can check
        # callability without importing the registry directly.
        return frozenset(_CAPABILITY_SYNC_ELIGIBLE)
    except Exception:
        # Fallback: hardcode the known callable class if the registry is not
        # importable (e.g. test environment without the full dep tree).
        return frozenset({"capability_node"})


#: Frozenset of :class:`~core.nodes.node_fabric_registry.NodeArchitecturalClass`
#: values (or their string equivalents) that make a node callable by OpenClawd.
#:
#: Currently only ``CAPABILITY_NODE`` nodes are callable; all other classes
#: are excluded from the capability bus by design.
CALLABLE_ARCHITECTURAL_CLASSES: "FrozenSet" = _build_callable_classes()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_callable_by_openclawd(architectural_class: "object") -> bool:
    """Return ``True`` if *architectural_class* makes a node callable by OpenClawd.

    Parameters
    ----------
    architectural_class:
        A :class:`~core.nodes.node_fabric_registry.NodeArchitecturalClass`
        enum member **or** its string value (e.g. ``"capability_node"``).

    Returns
    -------
    bool
        ``True`` only when the class is in :data:`CALLABLE_ARCHITECTURAL_CLASSES`.
    """
    # Accept both enum members and raw strings.
    value = (
        architectural_class.value
        if hasattr(architectural_class, "value")
        else str(architectural_class)
    )
    return value in CALLABLE_ARCHITECTURAL_CLASSES


def get_callable_node_names() -> List[str]:
    """Return node IDs of all currently registered callable nodes.

    A node is *callable* when it is registered in
    :class:`~core.nodes.node_fabric_registry.NodeFabricRegistry` **and** its
    :attr:`~core.nodes.node_fabric_registry.NodeInfo.architectural_class` is in
    :data:`CALLABLE_ARCHITECTURAL_CLASSES`.

    Returns an empty list (not an error) when the registry is unavailable.
    """
    try:
        from core.nodes.node_fabric_registry import get_node_fabric_registry
        registry = get_node_fabric_registry()
        names: List[str] = []
        for node in registry.list_nodes():
            if is_callable_by_openclawd(node.architectural_class):
                names.append(node.node_id)
        return names
    except Exception as exc:
        logger.debug("get_callable_node_names: registry unavailable: %s", exc)
        return []


def get_callable_node_count() -> int:
    """Return the number of currently registered callable nodes.

    Convenience wrapper around :func:`get_callable_node_names`.
    """
    return len(get_callable_node_names())
