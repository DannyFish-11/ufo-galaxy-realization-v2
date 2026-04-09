"""
core/fusion_entry_adapter.py
============================
Canonical Execution Adapter Contract for fusion_entry.py  (PR-5)
-----------------------------------------------------------------

This module formalises the **execution adapter** role of ``fusion_entry.py``.

Role of ``fusion_entry.py``
~~~~~~~~~~~~~~~~~~~~~~~~~~~
``fusion_entry.py`` is **only** the local execution adapter for a node.  Its
sole responsibility is to:

1. Load the node's ``main.py`` (or equivalent) in an isolated way that does
   NOT mutate ``sys.path``.
2. Expose a ``FusionNode`` class whose async ``execute(command, **params)``
   method dispatches work to the underlying logic and returns a
   ``{"success": bool, ...}`` dict.
3. Expose a module-level ``get_node_instance() -> FusionNode`` factory
   function that the unified executor can call to obtain an adapter instance.

What ``fusion_entry.py`` is NOT
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* It is **not** a node existence definition — a node's presence on disk is
  not sufficient evidence that it belongs to the active system.
* It is **not** a registry or discovery authority — only
  ``core.nodes.node_fabric_registry.NodeFabricRegistry`` is the canonical
  runtime registry.
* It is **not** a governance eligibility check — governance metadata lives in
  ``node_dependencies.json`` and is evaluated by the governance layer.

Adapter contract
~~~~~~~~~~~~~~~~
Every ``fusion_entry.py`` in ``nodes/<NodeID>/`` MUST satisfy the following
contract so that :class:`~core.node_invocation.UnifiedNodeExecutor` can load
and call it correctly:

* **No ``sys.path`` mutation** — the adapter must use
  ``importlib.util.spec_from_file_location`` and related APIs to load its
  node's ``main.py``.
* **``FusionNode`` class** — a class (or compatible object factory) named
  ``FusionNode`` must be importable from the module.
* **``FusionNode.execute``** — must be an ``async`` method with the signature
  ``execute(self, command: str, **params) -> dict`` that returns
  ``{"success": bool, ...}``.
* **``get_node_instance``** — a module-level callable named
  ``get_node_instance`` that accepts no arguments and returns a ``FusionNode``
  (or equivalent adapter instance with an ``execute`` method).

Invocation contract
~~~~~~~~~~~~~~~~~~~
All callers MUST use :func:`~core.node_invocation.invoke_node` (or
:class:`~core.node_invocation.UnifiedNodeExecutor`) as the entry point.
Direct calls to :func:`~core.routes._helpers._load_node` or
:func:`~core.routes._helpers._execute_node` from outside the executor are
non-canonical and should be migrated to the unified executor.

Policy sentinels
~~~~~~~~~~~~~~~~
All sentinel constants in this module are machine-checkable strings that
confirm the fusion-entry adapter contract is in force.  They are re-exported
from ``core/routes/projection.py`` so that external verifiers can import them
without knowledge of internal paths.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

logger = logging.getLogger("Galaxy.FusionEntryAdapter")

# ---------------------------------------------------------------------------
# Authority and policy sentinels
# ---------------------------------------------------------------------------

FUSION_ENTRY_ADAPTER_AUTHORITY: str = (
    "FUSION_ENTRY_ADAPTER::AUTHORITY_V1: "
    "fusion_entry.py is the canonical local execution adapter for a node.  "
    "It is NOT a node existence definition, NOT a registry authority, and NOT "
    "a governance eligibility check.  NodeFabricRegistry remains the canonical "
    "runtime node registry."
)

FUSION_ENTRY_ADAPTER_PR5_SENTINEL: str = (
    "FUSION_ENTRY_ADAPTER::PR5_SENTINEL_V1"
)

ADAPTER_IS_EXECUTION_ONLY_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::EXECUTION_ONLY_POLICY_V1: "
    "fusion_entry.py exposes execute() and get_node_instance() and nothing more.  "
    "It does not register the node, does not assert discovery membership, and "
    "does not evaluate governance eligibility."
)

ADAPTER_MUST_NOT_MUTATE_SYS_PATH_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::NO_SYS_PATH_MUTATION_POLICY_V1: "
    "fusion_entry.py MUST load main.py via importlib.util.spec_from_file_location "
    "and must never call sys.path.append / sys.path.insert."
)

ADAPTER_CONTRACT_IS_EXECUTE_AND_FACTORY_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::CONTRACT_POLICY_V1: "
    "Every fusion_entry.py must expose: (1) a FusionNode class with an async "
    "execute(command, **params) -> dict method that returns {success: bool, ...}, "
    "and (2) a module-level get_node_instance() factory that returns FusionNode."
)

UNIFIED_EXECUTOR_IS_CANONICAL_CALLER_POLICY: str = (
    "FUSION_ENTRY_ADAPTER::CANONICAL_CALLER_POLICY_V1: "
    "Only UnifiedNodeExecutor (core.node_invocation) is the canonical caller of "
    "fusion_entry.  Direct callers of _load_node / _execute_node outside the "
    "executor are non-canonical and should migrate to invoke_node()."
)


# ---------------------------------------------------------------------------
# Adapter contract version
# ---------------------------------------------------------------------------

#: String embedded into every ``templates/node_template/fusion_entry.py`` so
#: that tooling can verify the template is up-to-date.
FUSION_ENTRY_ADAPTER_CONTRACT_VERSION: str = "FUSION_ENTRY_ADAPTER_CONTRACT_V1"


# ---------------------------------------------------------------------------
# Adapter contract validator
# ---------------------------------------------------------------------------

class AdapterContractViolation(Exception):
    """Raised when a loaded module does not satisfy the adapter contract."""


def validate_adapter_module(module: Any, *, node_id: str = "<unknown>") -> None:
    """Validate that *module* satisfies the fusion_entry adapter contract.

    Raises :class:`AdapterContractViolation` with a descriptive message when
    the module is missing required attributes or when they have the wrong
    shape.

    This function is used by the unified executor to provide clear diagnostic
    messages when a node's ``fusion_entry.py`` is malformed, instead of
    surfacing an opaque ``AttributeError`` or ``TypeError``.

    Parameters
    ----------
    module:
        The loaded ``fusion_entry`` module object.
    node_id:
        Human-readable identifier for the node (used in error messages only).
    """
    # Check get_node_instance factory -------------------------------------------
    if not hasattr(module, "get_node_instance"):
        raise AdapterContractViolation(
            f"[{node_id}] fusion_entry.py is missing get_node_instance().  "
            "Every adapter must expose a module-level get_node_instance() "
            "factory function."
        )
    factory = module.get_node_instance
    if not callable(factory):
        raise AdapterContractViolation(
            f"[{node_id}] fusion_entry.py: get_node_instance is not callable."
        )

    # Check FusionNode class (preferred) or instance from factory ---------------
    has_fusion_node_class = hasattr(module, "FusionNode") and isinstance(
        module.FusionNode, type
    )

    # Obtain an instance to inspect the execute method.
    try:
        instance = factory()
    except Exception as exc:  # noqa: BLE001  # any exception from factory becomes a contract violation
        raise AdapterContractViolation(
            f"[{node_id}] fusion_entry.py: get_node_instance() raised {exc!r}.  "
            "The factory must return an adapter instance without raising."
        ) from exc

    if not hasattr(instance, "execute"):
        raise AdapterContractViolation(
            f"[{node_id}] fusion_entry.py: the instance returned by "
            "get_node_instance() is missing an execute() method."
        )
    execute = getattr(instance, "execute")
    if not callable(execute):
        raise AdapterContractViolation(
            f"[{node_id}] fusion_entry.py: execute is not callable."
        )

    # Soft-warn (log) if execute is not a coroutine function.  We do NOT raise
    # here because some legacy nodes use synchronous execute() and the executor
    # handles both synchronous and asynchronous variants.
    if not inspect.iscoroutinefunction(execute):
        logger.warning(
            "[%s] fusion_entry.py: execute() is not async.  "
            "Prefer async execute() for performance; synchronous execute() "
            "will be wrapped by run_in_executor automatically.",
            node_id,
        )

    if not has_fusion_node_class:
        # Acceptable — some legacy nodes expose only get_node_instance(), not
        # a top-level FusionNode class.  Log at debug level only.
        logger.debug(
            "[%s] fusion_entry.py does not expose a top-level FusionNode class.  "
            "This is acceptable but the template pattern is preferred.",
            node_id,
        )


def check_adapter_module(
    module: Any,
    *,
    node_id: str = "<unknown>",
) -> Optional[str]:
    """Return ``None`` when *module* satisfies the contract, else an error string.

    This is a non-raising convenience wrapper around :func:`validate_adapter_module`
    suitable for diagnostic surfaces that want to report rather than raise.
    """
    try:
        validate_adapter_module(module, node_id=node_id)
        return None
    except AdapterContractViolation as exc:
        return str(exc)
