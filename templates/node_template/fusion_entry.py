# Fusion layer integration shim — Node_XXX_YourNodeName
#
# This file is the entry point used by the fusion layer to load and interact
# with the node without polluting sys.path.  The pattern must stay consistent
# across all nodes so that the launcher and audit engine can discover nodes
# reliably.
#
# Replace:
#   Node_XXX_YourNodeName  → actual node ID  (e.g. Node_042_Scheduler)

import asyncio
import importlib.util
import logging
import os

_node_dir = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("Node_XXX_YourNodeName")


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
    """Thin wrapper that exposes a uniform execution interface."""

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
    """Return a ready-to-use FusionNode.  Called by the fusion loader."""
    return FusionNode()
