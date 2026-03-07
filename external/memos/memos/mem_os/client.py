"""
Minimal ClientMOS - a lightweight wrapper around MOSCore for client-side usage.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ClientMOS:
    """
    Minimal client interface for the Memory Operating System (MemOS).

    Wraps :class:`memos.mem_os.core.MOSCore` when available, otherwise
    operates in a degraded (no-op) mode so that imports never fail at
    runtime.
    """

    def __init__(self, config: Optional[Any] = None) -> None:
        self._core: Optional[Any] = None
        if config is not None:
            try:
                from memos.mem_os.core import MOSCore  # type: ignore
                self._core = MOSCore(config)
                logger.info("ClientMOS: MOSCore initialised successfully.")
            except Exception as exc:  # pragma: no cover
                logger.warning("ClientMOS: could not initialise MOSCore (%s). Running in degraded mode.", exc)

    # ------------------------------------------------------------------
    # Core operations (delegate to MOSCore when available)
    # ------------------------------------------------------------------

    def chat(self, query: str, user_id: Optional[str] = None, **kwargs: Any) -> str:
        """Send a chat message and return the response string."""
        if self._core is not None:
            try:
                return self._core.chat(query, user_id=user_id, **kwargs)
            except Exception as exc:
                logger.error("ClientMOS.chat failed: %s", exc)
        return ""

    def add(self, messages: Any, user_id: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        """Add memories."""
        if self._core is not None:
            try:
                return self._core.add(messages, user_id=user_id, **kwargs)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("ClientMOS.add failed: %s", exc)
        return {"success": False, "error": "MOSCore not available"}

    def search(self, query: str, user_id: Optional[str] = None, **kwargs: Any) -> List[Any]:
        """Search memories."""
        if self._core is not None:
            try:
                return self._core.search(query, user_id=user_id, **kwargs)  # type: ignore[return-value]
            except Exception as exc:
                logger.error("ClientMOS.search failed: %s", exc)
        return []

    def get(self, mem_cube_id: str, memory_id: str, user_id: Optional[str] = None) -> Optional[Any]:
        """Get a single memory by id."""
        if self._core is not None:
            try:
                return self._core.get(mem_cube_id, memory_id, user_id=user_id)
            except Exception as exc:
                logger.error("ClientMOS.get failed: %s", exc)
        return None

    def delete(self, mem_cube_id: str, memory_id: str, user_id: Optional[str] = None) -> None:
        """Delete a memory."""
        if self._core is not None:
            try:
                self._core.delete(mem_cube_id, memory_id, user_id=user_id)
            except Exception as exc:
                logger.error("ClientMOS.delete failed: %s", exc)

    def get_user_info(self) -> Dict[str, Any]:
        """Return user information summary."""
        if self._core is not None:
            try:
                return self._core.get_user_info()  # type: ignore[return-value]
            except Exception as exc:
                logger.error("ClientMOS.get_user_info failed: %s", exc)
        return {}

    def is_available(self) -> bool:
        """Return *True* when a live MOSCore backend is connected."""
        return self._core is not None
