"""
core/fusion_entry_adapter.py
============================
Canonical Local Execution Adapter Contract  (PR-5)
---------------------------------------------------

This module formalises ``fusion_entry.py`` as the **canonical local execution
adapter** for every node in the Galaxy system, and explicitly narrows its
scope to that single responsibility.

Role of ``fusion_entry.py``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
``fusion_entry.py`` is an **execution adapter**: a thin per-node shim that
loads the node's core logic (``main.py``) in an isolated namespace and exposes
a uniform execution interface to the unified executor layer
(``core.node_invocation``).

It is explicitly **NOT**:

* A node registry or discovery authority.
* A source of truth for whether a node is part of the active system.
* A governance eligibility oracle.

The canonical registry authority is :data:`NodeFabricRegistry`
(``core.nodes.node_fabric_registry``).  Node membership in the active system
is determined exclusively by ``node_dependencies.json``.  Governance
eligibility is computed by the governance layer, not by the presence or
absence of ``fusion_entry.py`` on disk.

Adapter contract
~~~~~~~~~~~~~~~~
Every ``fusion_entry.py`` MUST satisfy the following contract so that
:class:`~core.node_invocation.UnifiedNodeExecutor` can load and execute it:

1. **No ``sys.path`` mutation** — use ``importlib.util.spec_from_file_location``
   to load ``main.py`` in isolation; never append to ``sys.path`` from within
   ``fusion_entry.py``.
2. **``FusionNode`` class** — expose a class named ``FusionNode`` with an
   async ``execute(command: str, **params) -> dict`` method.  The method MUST
   return ``{"success": bool, ...}``.  Async is strongly recommended; the
   unified executor also accepts sync ``execute`` methods for backward
   compatibility with existing nodes.
3. **``get_node_instance()``** — expose a module-level factory function that
   returns a ``FusionNode`` instance.  This is the primary entry point used by
   the loader.

The reference implementation is at ``templates/node_template/fusion_entry.py``.

Policy sentinels
~~~~~~~~~~~~~~~~
All sentinel constants in this module are machine-checkable strings that
confirm the adapter contract is in force.  They are re-exported from
``core/routes/projection.py`` so that external verifiers can import them
without knowledge of internal paths.

Non-goals
~~~~~~~~~
- This module does NOT change execution plumbing (that is PR-4).
- This module does NOT change registry or discovery architecture.
- This module does NOT require immediate rewrites of existing nodes; the
  contract is backward-compatible with nodes already using the template.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("Galaxy.FusionEntryAdapter")

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

FUSION_ENTRY_IS_EXECUTION_ADAPTER_AUTHORITY: str = (
    "FUSION_ENTRY_ADAPTER::AUTHORITY_V1: "
    "fusion_entry.py is the canonical local execution adapter for node runtime "
    "loading.  Its sole responsibility is to load the node's core logic in an "
    "isolated namespace and expose a uniform execution interface to the unified "
    "executor (core.node_invocation).  It is NOT a node registry, NOT a "
    "discovery authority, and NOT a governance eligibility oracle."
)

FUSION_ENTRY_ADAPTER_CONTRACT_PR5_SENTINEL: str = (
    "FUSION_ENTRY_ADAPTER::PR5_SENTINEL_V1"
)

FUSION_ENTRY_NOT_A_REGISTRY_AUTHORITY_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::NOT_REGISTRY_AUTHORITY_POLICY_V1: "
    "The presence or absence of fusion_entry.py on disk MUST NOT be used to "
    "determine canonical node membership in the active system.  Node membership "
    "is determined exclusively by node_dependencies.json and the canonical "
    "runtime node registry (NodeFabricRegistry)."
)

FUSION_ENTRY_NOT_A_DISCOVERY_AUTHORITY_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::NOT_DISCOVERY_AUTHORITY_POLICY_V1: "
    "Loading fusion_entry.py is an execution-time operation, not a discovery "
    "or registration operation.  Node discovery and registration MUST go "
    "through NodeDiscoveryService and NodeFabricRegistry, not through scanning "
    "for fusion_entry.py files."
)

ADAPTER_CONTRACT_IS_STANDARDISED_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::STANDARDISED_CONTRACT_POLICY_V1: "
    "Every fusion_entry.py MUST expose FusionNode (async execute(command, "
    "**params) -> dict) and module-level get_node_instance().  It MUST load "
    "main.py via importlib.util.spec_from_file_location and MUST NOT mutate "
    "sys.path.  The reference implementation is "
    "templates/node_template/fusion_entry.py."
)

UNIFIED_EXECUTOR_IS_CANONICAL_LOADER_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::CANONICAL_LOADER_POLICY_V1: "
    "Direct calls to core.routes._helpers._load_node / _execute_node are an "
    "implementation detail of the unified executor.  All external call sites "
    "MUST go through core.node_invocation.invoke_node() or "
    "UnifiedNodeExecutor.execute() instead of calling helpers directly."
)


# ---------------------------------------------------------------------------
# Adapter contract descriptor
# ---------------------------------------------------------------------------

@dataclass
class FusionEntryAdapterContract:
    """Machine-readable description of the fusion_entry.py adapter contract.

    This dataclass is used by :func:`validate_fusion_entry_adapter` to check
    whether a loaded ``fusion_entry`` module satisfies the canonical contract.
    """

    has_fusion_node_class: bool = False
    fusion_node_has_execute: bool = False
    execute_is_async: bool = False
    has_get_node_instance: bool = False
    get_node_instance_callable: bool = False

    @property
    def is_compliant(self) -> bool:
        """Return ``True`` iff the module fully satisfies the adapter contract.

        Note: ``execute_is_async`` is recorded for diagnostics but is not
        required for basic compliance.  The unified executor handles both sync
        and async ``execute`` methods via ``asyncio.run_in_executor``, so
        existing nodes with synchronous ``execute`` remain compatible.  New
        nodes SHOULD use async execute per the template, but the compliance
        gate does not block sync adapters to preserve backward compatibility.
        """
        return (
            self.has_fusion_node_class
            and self.fusion_node_has_execute
            and self.has_get_node_instance
            and self.get_node_instance_callable
        )

    def compliance_report(self) -> dict:
        """Return a dict summarising contract compliance status."""
        return {
            "is_compliant": self.is_compliant,
            "has_fusion_node_class": self.has_fusion_node_class,
            "fusion_node_has_execute": self.fusion_node_has_execute,
            "execute_is_async": self.execute_is_async,
            "has_get_node_instance": self.has_get_node_instance,
            "get_node_instance_callable": self.get_node_instance_callable,
        }


# ---------------------------------------------------------------------------
# Contract validator
# ---------------------------------------------------------------------------

def validate_fusion_entry_adapter(module: Any) -> FusionEntryAdapterContract:
    """Validate that *module* satisfies the fusion_entry adapter contract.

    Parameters
    ----------
    module:
        A Python module object loaded from a ``fusion_entry.py`` file.

    Returns
    -------
    FusionEntryAdapterContract:
        A dataclass describing which parts of the contract are satisfied.
        Check :attr:`FusionEntryAdapterContract.is_compliant` for a quick
        pass/fail answer.
    """
    import asyncio
    import inspect

    contract = FusionEntryAdapterContract()

    # 1. FusionNode class
    fusion_node_cls = getattr(module, "FusionNode", None)
    if fusion_node_cls is not None and isinstance(fusion_node_cls, type):
        contract.has_fusion_node_class = True

        # 2. async execute method on FusionNode
        execute_method = getattr(fusion_node_cls, "execute", None)
        if execute_method is not None and callable(execute_method):
            contract.fusion_node_has_execute = True
            # asyncio.iscoroutinefunction works on unbound methods too
            if inspect.iscoroutinefunction(execute_method):
                contract.execute_is_async = True

    # 3. get_node_instance factory function
    gni = getattr(module, "get_node_instance", None)
    if gni is not None:
        contract.has_get_node_instance = True
        if callable(gni):
            contract.get_node_instance_callable = True

    return contract


# ---------------------------------------------------------------------------
# Adapter compliance helper for loaders
# ---------------------------------------------------------------------------

def check_fusion_entry_compliance(
    module: Any,
    node_id: Optional[str] = None,
) -> bool:
    """Return ``True`` if *module* is a compliant fusion_entry adapter.

    Logs a warning for each missing contract requirement.  Intended for use
    by loader code that needs a simple bool gate rather than the full
    :class:`FusionEntryAdapterContract` report.

    Parameters
    ----------
    module:
        The loaded fusion_entry module.
    node_id:
        Optional node identifier used in log messages.
    """
    label = node_id or "<unknown node>"
    contract = validate_fusion_entry_adapter(module)

    if contract.is_compliant:
        return True

    report = contract.compliance_report()
    missing = [k for k, v in report.items() if k != "is_compliant" and not v]
    logger.warning(
        "fusion_entry for %s does not fully satisfy adapter contract; "
        "missing: %s",
        label,
        ", ".join(missing),
    )
    return False
