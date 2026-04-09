# fusion_entry.py — Execution Adapter for Node_XXX_YourNodeName
#
# Role: LOCAL EXECUTION ADAPTER ONLY.
#
# This file is the canonical execution adapter consumed by
# core.node_invocation.UnifiedNodeExecutor.  Its sole responsibility is to
# load the node's main.py in an isolated way and expose a uniform execution
# interface (FusionNode + get_node_instance).
#
# This file is NOT:
#   - a node existence definition
#   - a node registry or discovery authority
#   - a governance eligibility check
#
# The canonical runtime node registry is NodeFabricRegistry
# (core.nodes.node_fabric_registry).  A node having a fusion_entry.py on
# disk does NOT imply active system membership or governance approval.
#
# Adapter contract version: FUSION_ENTRY_ADAPTER_CONTRACT_V1
# (see core/fusion_entry_adapter.py for the full contract specification)
#
# Replace:
#   Node_XXX_YourNodeName  → actual node ID  (e.g. Node_042_Scheduler)

import asyncio
import importlib.util
import logging
import os

_node_dir = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("Node_XXX_YourNodeName")

# Adapter contract version sentinel — machine-checkable by tooling.
FUSION_ENTRY_ADAPTER_CONTRACT_VERSION: str = "FUSION_ENTRY_ADAPTER_CONTRACT_V1"


# ---------------------------------------------------------------------------
# Isolated import helper — avoids sys.path pollution
# ---------------------------------------------------------------------------

def _import_node_main():
    """Load this node's main.py using importlib so that sys.path is not mutated."""
    main_path = os.path.join(_node_dir, "main.py")
    if not os.path.exists(main_path):
        logger.warning("main.py not found in %s", _node_dir)
        return None
    spec = importlib.util.spec_from_file_location(
        "Node_XXX_YourNodeName.main",
        main_path,
        submodule_search_locations=[_node_dir],
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# FusionNode — public interface consumed by the fusion / orchestration layer
# ---------------------------------------------------------------------------

class FusionNode:
    """Execution adapter — exposes the node's logic through a uniform interface.

    This class is the execution adapter consumed by
    :class:`~core.node_invocation.UnifiedNodeExecutor`.  It loads the node's
    ``main.py`` lazily and dispatches ``execute()`` calls to the underlying
    logic.

    Contract (FUSION_ENTRY_ADAPTER_CONTRACT_V1):
    - ``execute(command, **params)`` must be async and return ``{"success": bool, ...}``
    - Constructing a ``FusionNode`` must not raise even if ``main.py`` is absent.
    - This class must NOT register the node, must NOT assert discovery membership,
      and must NOT perform governance eligibility checks.
    """

    def __init__(self) -> None:
        self.node_id = "Node_XXX_YourNodeName"
        self.instance = None
        self._load()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            module = _import_node_main()
            if module is None:
                return
            # Prefer an explicit factory function; fall back to a Node class.
            if hasattr(module, "get_instance"):
                self.instance = module.get_instance()
            elif hasattr(module, "Node"):
                self.instance = module.Node()
            else:
                self.instance = module
            logger.info("✅ %s logic loaded successfully", self.node_id)
        except Exception as exc:
            logger.error("❌ %s failed to load: %s", self.node_id, exc)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, command: str, **params) -> dict:
        """Dispatch *command* to the node instance.

        Returns ``{"success": True, "data": ...}`` on success, or
        ``{"success": False, "error": "..."}`` on failure.
        """
        if not self.instance:
            return {"success": False, "error": "Node logic not loaded"}
        try:
            method = None
            for candidate in ("process", "execute", "run", "handle"):
                if hasattr(self.instance, candidate):
                    method = getattr(self.instance, candidate)
                    break
            if method is None:
                if callable(self.instance):
                    method = self.instance
                else:
                    return {"success": False, "error": "No executable method found"}
            result = (
                await method(command, **params)
                if asyncio.iscoroutinefunction(method)
                else method(command, **params)
            )
            return {"success": True, "data": result}
        except Exception as exc:
            logger.error("❌ %s execution error: %s", self.node_id, exc)
            return {"success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Module-level accessor
# ---------------------------------------------------------------------------

def get_node_instance() -> FusionNode:
    """Return a ready-to-use FusionNode.

    This is the canonical factory function called by
    :class:`~core.node_invocation.UnifiedNodeExecutor` to obtain an adapter
    instance.  It must accept no arguments and must not raise.
    """
    return FusionNode()
